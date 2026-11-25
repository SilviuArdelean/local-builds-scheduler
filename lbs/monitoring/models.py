# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.monitoring.models – Immutable system resource snapshots and formatting helpers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field


def _as_finite_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    float_val = float(value)
    if not math.isfinite(float_val):
        return default
    return float_val


def _clamp_non_negative_float(value: object) -> float:
    return max(0.0, _as_finite_float(value, default=0.0))


def _clamp_non_negative_int(value: object) -> int:
    return int(_clamp_non_negative_float(value))


def _clamp_percent(value: object) -> float:
    return min(100.0, max(0.0, _as_finite_float(value, default=0.0)))


def format_bytes_iec(
    byte_count: int | float,
    decimals: int = 1,
) -> str:
    """Formats a byte count into IEC units (KiB, MiB, GiB...)."""
    value = _clamp_non_negative_float(byte_count)
    precision = max(0, int(decimals))
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")

    unit_idx = 0
    while value >= 1024.0 and unit_idx < (len(units) - 1):
        value /= 1024.0
        unit_idx += 1

    if unit_idx == 0:
        return f"{int(value)} {units[unit_idx]}"
    return f"{value:.{precision}f} {units[unit_idx]}"


def format_bytes_rate_iec(
    bytes_per_second: int | float,
    decimals: int = 1,
) -> str:
    """Formats a throughput value in IEC units per second."""
    return f"{format_bytes_iec(bytes_per_second, decimals=decimals)}/s"


@dataclass(frozen=True)
class ResourceSample:
    """Common metadata for a single metric sample."""

    available: bool
    sampled_at: float | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "available", bool(self.available))
        sampled = self.sampled_at
        if sampled is None:
            return
        sampled_val = _as_finite_float(sampled, default=0.0)
        object.__setattr__(self, "sampled_at", max(0.0, sampled_val))


@dataclass(frozen=True)
class PercentSample(ResourceSample):
    """Percent metric in range [0, 100]."""

    value: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(self, "value", _clamp_percent(self.value))


@dataclass(frozen=True)
class MemorySample(ResourceSample):
    """Memory usage sample with bytes and percent."""

    used_bytes: int = 0
    total_bytes: int = 0
    used_percent: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        total = _clamp_non_negative_int(self.total_bytes)
        used = _clamp_non_negative_int(self.used_bytes)
        if total > 0:
            used = min(used, total)
            percent = _clamp_percent((used / total) * 100.0)
        else:
            percent = _clamp_percent(self.used_percent)
        object.__setattr__(self, "total_bytes", total)
        object.__setattr__(self, "used_bytes", used)
        object.__setattr__(self, "used_percent", percent)


@dataclass(frozen=True)
class DiskIoSample(ResourceSample):
    """Disk I/O throughput sample."""

    read_bytes_per_second: float = 0.0
    write_bytes_per_second: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        object.__setattr__(
            self,
            "read_bytes_per_second",
            _clamp_non_negative_float(self.read_bytes_per_second),
        )
        object.__setattr__(
            self,
            "write_bytes_per_second",
            _clamp_non_negative_float(self.write_bytes_per_second),
        )


@dataclass(frozen=True)
class DiskFreeSample(ResourceSample):
    """Disk free-space sample for the active workspace volume."""

    volume: str = ""
    free_bytes: int = 0
    total_bytes: int = 0
    used_percent: float = 0.0

    def __post_init__(self) -> None:
        super().__post_init__()
        total = _clamp_non_negative_int(self.total_bytes)
        free = _clamp_non_negative_int(self.free_bytes)
        if total > 0:
            free = min(free, total)
            used = max(0, total - free)
            percent = _clamp_percent((used / total) * 100.0)
        else:
            percent = _clamp_percent(self.used_percent)
        object.__setattr__(self, "total_bytes", total)
        object.__setattr__(self, "free_bytes", free)
        object.__setattr__(self, "used_percent", percent)


@dataclass(frozen=True)
class SystemResourcesSnapshot:
    """Immutable aggregate snapshot for all system resource metrics."""

    cpu: PercentSample = field(default_factory=lambda: PercentSample(available=False))
    memory: MemorySample = field(default_factory=lambda: MemorySample(available=False))
    disk_io: DiskIoSample = field(default_factory=lambda: DiskIoSample(available=False))
    disk_free: DiskFreeSample = field(
        default_factory=lambda: DiskFreeSample(available=False)
    )
