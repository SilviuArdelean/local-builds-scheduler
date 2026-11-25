# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.monitoring.monitor – Scheduling and caching for system resource collection.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from lbs.monitoring.collectors import (
    PsutilCpuCollector,
    PsutilDiskIoCollector,
    PsutilMemoryCollector,
    WorkspaceDiskFreeCollector,
    workspace_volume_id,
)
from lbs.monitoring.models import (
    DiskFreeSample,
    DiskIoSample,
    MemorySample,
    PercentSample,
    SystemResourcesSnapshot,
)


class SystemResourcesMonitor:
    """Caches and refreshes resource samples on independent intervals."""

    def __init__(
        self,
        *,
        cpu_collector: PsutilCpuCollector | None = None,
        memory_collector: PsutilMemoryCollector | None = None,
        disk_io_collector: PsutilDiskIoCollector | None = None,
        disk_free_collector: WorkspaceDiskFreeCollector | None = None,
        cpu_interval_seconds: float = 1.0,
        memory_interval_seconds: float = 30.0,
        disk_io_interval_seconds: float = 3.0,
        disk_free_interval_seconds: float = 300.0,
        enabled: bool = True,
        disk_io_enabled: bool = True,
        clock: Callable[[], float] | None = None,
        workspace: Path | str | None = None,
        volume_id_fn: Callable[[Path], str] = workspace_volume_id,
    ) -> None:
        self.enabled = bool(enabled)
        self.disk_io_enabled = bool(disk_io_enabled)
        self._clock = clock or time.perf_counter
        self._volume_id_fn = volume_id_fn

        self._cpu_collector = cpu_collector or PsutilCpuCollector()
        self._memory_collector = memory_collector or PsutilMemoryCollector()
        self._disk_io_collector = disk_io_collector or PsutilDiskIoCollector()
        self._disk_free_collector = disk_free_collector or WorkspaceDiskFreeCollector()

        self._cpu_interval = max(0.001, float(cpu_interval_seconds))
        self._memory_interval = max(0.001, float(memory_interval_seconds))
        self._disk_io_interval = max(0.001, float(disk_io_interval_seconds))
        self._disk_free_interval = max(0.001, float(disk_free_interval_seconds))

        self._workspace = Path(workspace) if workspace is not None else Path.cwd()
        self._workspace_volume_id = self._volume_id_fn(self._workspace)

        self._snapshot = SystemResourcesSnapshot()
        self._next_cpu_at = 0.0
        self._next_memory_at = 0.0
        self._next_disk_io_at = 0.0
        self._next_disk_free_at = 0.0
        self._closed = False

    def snapshot(self) -> SystemResourcesSnapshot:
        return self._snapshot

    def close(self) -> None:
        self._closed = True

    def set_workspace(self, workspace: Path | str) -> None:
        new_workspace = Path(workspace)
        new_volume = self._volume_id_fn(new_workspace)
        volume_changed = new_volume != self._workspace_volume_id
        self._workspace = new_workspace
        self._workspace_volume_id = new_volume
        if volume_changed and self.enabled and not self._closed:
            now = self._clock()
            self._sample_disk_free(now)
            self._next_disk_free_at = now + self._disk_free_interval

    def poll(
        self,
        workspace: Path | str | None = None,
        now: float | None = None,
    ) -> SystemResourcesSnapshot:
        if self._closed or not self.enabled:
            return self._snapshot

        if workspace is not None:
            self.set_workspace(workspace)

        sampled_at = self._clock() if now is None else now
        if sampled_at >= self._next_cpu_at:
            self._sample_cpu(sampled_at)
            self._next_cpu_at = sampled_at + self._cpu_interval

        if sampled_at >= self._next_memory_at:
            self._sample_memory(sampled_at)
            self._next_memory_at = sampled_at + self._memory_interval

        if self.disk_io_enabled and sampled_at >= self._next_disk_io_at:
            sample = self._sample_disk_io(sampled_at)
            # Disk I/O rates need a baseline first; warm up quickly so values appear
            # in ~1 tick rather than waiting a full interval.
            if not sample.available and sample.error == "collecting baseline":
                self._next_disk_io_at = sampled_at + min(self._disk_io_interval, 1.0)
            else:
                self._next_disk_io_at = sampled_at + self._disk_io_interval

        if sampled_at >= self._next_disk_free_at:
            self._sample_disk_free(sampled_at)
            self._next_disk_free_at = sampled_at + self._disk_free_interval

        return self._snapshot

    def _sample_cpu(self, now: float) -> None:
        try:
            sample = self._cpu_collector.sample(now)
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
            sample = PercentSample(
                available=False,
                sampled_at=now,
                error=str(exc) or "cpu error",
            )
        self._snapshot = replace(self._snapshot, cpu=sample)

    def _sample_memory(self, now: float) -> None:
        try:
            sample = self._memory_collector.sample(now)
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
            sample = MemorySample(
                available=False,
                sampled_at=now,
                error=str(exc) or "memory error",
            )
        self._snapshot = replace(self._snapshot, memory=sample)

    def _sample_disk_io(self, now: float) -> DiskIoSample:
        try:
            sample = self._disk_io_collector.sample(now)
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
            sample = DiskIoSample(
                available=False,
                sampled_at=now,
                error=str(exc) or "disk I/O error",
            )
        self._snapshot = replace(self._snapshot, disk_io=sample)
        return sample

    def _sample_disk_free(self, now: float) -> None:
        try:
            sample = self._disk_free_collector.sample(now, self._workspace)
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
            sample = DiskFreeSample(
                available=False,
                sampled_at=now,
                error=str(exc) or "disk free error",
                volume=self._workspace_volume_id,
            )
        self._snapshot = replace(self._snapshot, disk_free=sample)
