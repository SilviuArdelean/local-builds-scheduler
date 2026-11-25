# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.monitoring.collectors – System resource collectors.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

from lbs.monitoring.models import (
    DiskFreeSample,
    DiskIoSample,
    MemorySample,
    PercentSample,
)

try:
    import psutil
except ImportError:  # pragma: no cover - covered via injected callables in tests
    psutil = None  # type: ignore[assignment]


class CpuPercentFn(Protocol):
    def __call__(self, interval: float | None = None) -> float: ...


class VirtualMemoryFn(Protocol):
    def __call__(self) -> object: ...


class DiskIoCountersFn(Protocol):
    def __call__(self) -> object | None: ...


class DiskUsageFn(Protocol):
    def __call__(self, path: str | os.PathLike[str]) -> object: ...


def _sanitize_error(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _nearest_existing_path(path: Path) -> Path | None:
    current = path.expanduser()
    while True:
        if current.exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def workspace_volume_id(path: Path) -> str:
    """Returns a normalized volume identifier for a workspace path."""
    resolved = path.expanduser()
    if os.name == "nt":
        anchor = resolved.anchor or resolved.drive
        if not anchor:
            return str(resolved).upper()
        normalized = anchor.replace("/", "\\")
        if not normalized.endswith("\\"):
            normalized = f"{normalized}\\"
        return normalized.upper()
    return "/"


class PsutilCpuCollector:
    """Collects overall CPU utilization percentage."""

    def __init__(self, cpu_percent_fn: CpuPercentFn | None = None) -> None:
        if cpu_percent_fn is not None:
            self._cpu_percent = cpu_percent_fn
        elif psutil is not None:
            self._cpu_percent = psutil.cpu_percent
        else:
            self._cpu_percent = None

    def sample(self, now: float) -> PercentSample:
        if self._cpu_percent is None:
            return PercentSample(
                available=False,
                sampled_at=now,
                error="psutil is not available",
            )
        try:
            value = float(self._cpu_percent(interval=None))
        except (TypeError, ValueError, OSError, RuntimeError) as exc:
            return PercentSample(
                available=False,
                sampled_at=now,
                error=_sanitize_error(exc),
            )
        return PercentSample(available=True, value=value, sampled_at=now)


class PsutilMemoryCollector:
    """Collects total/used memory and utilization percent."""

    def __init__(self, virtual_memory_fn: VirtualMemoryFn | None = None) -> None:
        if virtual_memory_fn is not None:
            self._virtual_memory = virtual_memory_fn
        elif psutil is not None:
            self._virtual_memory = psutil.virtual_memory
        else:
            self._virtual_memory = None

    def sample(self, now: float) -> MemorySample:
        if self._virtual_memory is None:
            return MemorySample(
                available=False,
                sampled_at=now,
                error="psutil is not available",
            )
        try:
            payload = self._virtual_memory()
            total = int(payload.total)
            try:
                used = int(payload.used)
            except AttributeError:
                used = total - int(payload.available)
            try:
                percent = float(payload.percent)
            except AttributeError:
                percent = 0.0
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
            return MemorySample(
                available=False,
                sampled_at=now,
                error=_sanitize_error(exc),
            )

        if total <= 0:
            return MemorySample(
                available=False,
                sampled_at=now,
                error="invalid memory total",
            )
        return MemorySample(
            available=True,
            used_bytes=used,
            total_bytes=total,
            used_percent=percent,
            sampled_at=now,
        )


class PsutilDiskIoCollector:
    """Collects aggregate disk read/write throughput from cumulative counters."""

    def __init__(self, disk_io_counters_fn: DiskIoCountersFn | None = None) -> None:
        if disk_io_counters_fn is not None:
            self._disk_io_counters = disk_io_counters_fn
        elif psutil is not None:
            self._disk_io_counters = psutil.disk_io_counters
        else:
            self._disk_io_counters = None

        self._last_read_bytes: int | None = None
        self._last_write_bytes: int | None = None
        self._last_sampled_at: float | None = None

    def sample(self, now: float) -> DiskIoSample:
        if self._disk_io_counters is None:
            return DiskIoSample(
                available=False,
                sampled_at=now,
                error="psutil is not available",
            )
        try:
            payload = self._disk_io_counters()
            if payload is None:
                raise RuntimeError("disk I/O counters are unavailable")
            read_bytes = int(payload.read_bytes)
            write_bytes = int(payload.write_bytes)
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
            return DiskIoSample(
                available=False,
                sampled_at=now,
                error=_sanitize_error(exc),
            )

        read_bytes = max(0, read_bytes)
        write_bytes = max(0, write_bytes)
        prev_read = self._last_read_bytes
        prev_write = self._last_write_bytes
        prev_time = self._last_sampled_at
        self._last_read_bytes = read_bytes
        self._last_write_bytes = write_bytes
        self._last_sampled_at = now

        if prev_read is None or prev_write is None or prev_time is None:
            return DiskIoSample(
                available=False,
                sampled_at=now,
                error="collecting baseline",
            )

        elapsed = now - prev_time
        if elapsed <= 0:
            return DiskIoSample(
                available=False,
                sampled_at=now,
                error="non-positive elapsed time",
            )
        if read_bytes < prev_read or write_bytes < prev_write:
            return DiskIoSample(
                available=False,
                sampled_at=now,
                error="counter reset detected",
            )

        return DiskIoSample(
            available=True,
            read_bytes_per_second=(read_bytes - prev_read) / elapsed,
            write_bytes_per_second=(write_bytes - prev_write) / elapsed,
            sampled_at=now,
        )


class WorkspaceDiskFreeCollector:
    """Collects free/total bytes for the active workspace volume."""

    def __init__(self, disk_usage_fn: DiskUsageFn | None = None) -> None:
        self._disk_usage: DiskUsageFn = disk_usage_fn or shutil.disk_usage

    def sample(self, now: float, workspace: Path) -> DiskFreeSample:
        existing = _nearest_existing_path(workspace)
        if existing is None:
            return DiskFreeSample(
                available=False,
                sampled_at=now,
                error=f"workspace path is not accessible: {workspace}",
            )

        try:
            usage = self._disk_usage(existing)
            total = int(usage.total)
            free = int(usage.free)
        except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
            return DiskFreeSample(
                available=False,
                sampled_at=now,
                error=_sanitize_error(exc),
            )

        if total <= 0:
            return DiskFreeSample(
                available=False,
                sampled_at=now,
                error="invalid disk total",
                volume=workspace_volume_id(existing),
            )

        return DiskFreeSample(
            available=True,
            sampled_at=now,
            volume=workspace_volume_id(existing),
            free_bytes=free,
            total_bytes=total,
        )
