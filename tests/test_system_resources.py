# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for collectors and monitor scheduling behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lbs.monitoring.collectors import PsutilDiskIoCollector
from lbs.monitoring.monitor import SystemResourcesMonitor


@dataclass
class _DiskCounters:
    read_bytes: int
    write_bytes: int


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _RecordingCollector:
    def __init__(self, value_factory):
        self.calls = 0
        self.value_factory = value_factory

    def sample(self, now: float):
        self.calls += 1
        return self.value_factory(now)


class _RecordingDiskFreeCollector:
    def __init__(self, value_factory):
        self.calls = 0
        self.workspaces: list[Path] = []
        self.value_factory = value_factory

    def sample(self, now: float, workspace: Path):
        self.calls += 1
        self.workspaces.append(workspace)
        return self.value_factory(now, workspace)


def test_disk_io_collector_returns_baseline_then_rates():
    payloads = iter([
        _DiskCounters(1_000, 2_000),
        _DiskCounters(1_600, 2_600),
    ])
    collector = PsutilDiskIoCollector(disk_io_counters_fn=lambda: next(payloads))

    baseline = collector.sample(10.0)
    assert baseline.available is False

    next_sample = collector.sample(12.0)
    assert next_sample.available is True
    assert next_sample.read_bytes_per_second == 300.0
    assert next_sample.write_bytes_per_second == 300.0


def test_disk_io_collector_detects_counter_reset():
    payloads = iter([
        _DiskCounters(1_000, 2_000),
        _DiskCounters(900, 1_900),
    ])
    collector = PsutilDiskIoCollector(disk_io_counters_fn=lambda: next(payloads))

    collector.sample(10.0)
    reset = collector.sample(11.0)
    assert reset.available is False
    assert reset.error == "counter reset detected"


def test_system_resources_monitor_uses_independent_deadlines():
    from lbs.monitoring.models import (
        DiskFreeSample,
        DiskIoSample,
        MemorySample,
        PercentSample,
    )

    clock = _FakeClock(start=100.0)
    cpu = _RecordingCollector(
        lambda now: PercentSample(available=True, sampled_at=now, value=42.0)
    )
    memory = _RecordingCollector(
        lambda now: MemorySample(
            available=True,
            sampled_at=now,
            used_bytes=128,
            total_bytes=512,
            used_percent=25.0,
        )
    )
    disk_io = _RecordingCollector(
        lambda now: DiskIoSample(
            available=True,
            sampled_at=now,
            read_bytes_per_second=1024.0,
            write_bytes_per_second=512.0,
        )
    )
    disk_free = _RecordingDiskFreeCollector(
        lambda now, workspace: DiskFreeSample(
            available=True,
            sampled_at=now,
            volume="C:\\",
            free_bytes=100,
            total_bytes=200,
        )
    )

    monitor = SystemResourcesMonitor(
        cpu_collector=cpu,
        memory_collector=memory,
        disk_io_collector=disk_io,
        disk_free_collector=disk_free,
        cpu_interval_seconds=5.0,
        memory_interval_seconds=10.0,
        disk_io_interval_seconds=30.0,
        disk_free_interval_seconds=300.0,
        clock=clock,
    )

    monitor.poll(workspace=Path("C:\\repo"), now=clock.now)
    assert (cpu.calls, memory.calls, disk_io.calls, disk_free.calls) == (1, 1, 1, 1)

    clock.advance(4.9)
    monitor.poll(now=clock.now)
    assert (cpu.calls, memory.calls, disk_io.calls, disk_free.calls) == (1, 1, 1, 1)

    clock.advance(0.2)  # 5.1 seconds from initial poll
    monitor.poll(now=clock.now)
    assert (cpu.calls, memory.calls, disk_io.calls, disk_free.calls) == (2, 1, 1, 1)

    clock.advance(5.0)  # 10.1 seconds from initial poll
    monitor.poll(now=clock.now)
    assert (cpu.calls, memory.calls, disk_io.calls, disk_free.calls) == (3, 2, 1, 1)

    clock.advance(20.0)  # 30.1 seconds from initial poll
    monitor.poll(now=clock.now)
    assert (cpu.calls, memory.calls, disk_io.calls, disk_free.calls) == (4, 3, 2, 1)


def test_system_resources_monitor_refreshes_disk_free_on_volume_change():
    from lbs.monitoring.models import (
        DiskFreeSample,
        DiskIoSample,
        MemorySample,
        PercentSample,
    )

    clock = _FakeClock(start=10.0)
    cpu = _RecordingCollector(
        lambda now: PercentSample(available=True, sampled_at=now, value=10.0)
    )
    memory = _RecordingCollector(
        lambda now: MemorySample(
            available=True,
            sampled_at=now,
            used_bytes=1,
            total_bytes=2,
            used_percent=50.0,
        )
    )
    disk_io = _RecordingCollector(
        lambda now: DiskIoSample(
            available=True,
            sampled_at=now,
            read_bytes_per_second=1.0,
            write_bytes_per_second=1.0,
        )
    )
    disk_free = _RecordingDiskFreeCollector(
        lambda now, workspace: DiskFreeSample(
            available=True,
            sampled_at=now,
            volume=str(workspace),
            free_bytes=50,
            total_bytes=100,
        )
    )

    monitor = SystemResourcesMonitor(
        cpu_collector=cpu,
        memory_collector=memory,
        disk_io_collector=disk_io,
        disk_free_collector=disk_free,
        clock=clock,
        volume_id_fn=lambda p: "VOL-C" if str(p).startswith("C:") else "VOL-D",
    )
    monitor.poll(workspace=Path("C:\\repo"), now=clock.now)
    assert disk_free.calls == 1

    clock.advance(1.0)
    monitor.set_workspace(Path("D:\\repo"))
    assert disk_free.calls == 2
    assert disk_free.workspaces[-1] == Path("D:\\repo")


def test_system_resources_monitor_isolates_failed_metric_updates():
    from lbs.monitoring.models import (
        DiskFreeSample,
        DiskIoSample,
        MemorySample,
    )

    class _FailingCpuCollector:
        def sample(self, now: float):
            raise OSError("cpu collection failed")

    clock = _FakeClock(start=0.0)
    monitor = SystemResourcesMonitor(
        cpu_collector=_FailingCpuCollector(),
        memory_collector=_RecordingCollector(
            lambda now: MemorySample(
                available=True,
                sampled_at=now,
                used_bytes=256,
                total_bytes=1024,
                used_percent=25.0,
            )
        ),
        disk_io_collector=_RecordingCollector(
            lambda now: DiskIoSample(
                available=True,
                sampled_at=now,
                read_bytes_per_second=4.0,
                write_bytes_per_second=2.0,
            )
        ),
        disk_free_collector=_RecordingDiskFreeCollector(
            lambda now, workspace: DiskFreeSample(
                available=True,
                sampled_at=now,
                volume="C:\\",
                free_bytes=300,
                total_bytes=600,
            )
        ),
        clock=clock,
    )

    snapshot = monitor.poll(workspace=Path("C:\\repo"), now=clock.now)
    assert snapshot.cpu.available is False
    assert snapshot.cpu.error == "cpu collection failed"
    assert snapshot.memory.available is True
    assert snapshot.disk_io.available is True
    assert snapshot.disk_free.available is True
    assert snapshot.memory.used_percent == 25.0
    assert snapshot.disk_io.read_bytes_per_second == 4.0
