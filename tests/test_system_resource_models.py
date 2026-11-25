# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for system resource models and formatters.
"""

from __future__ import annotations

import math

import pytest

from lbs.monitoring import (
    DiskFreeSample,
    DiskIoSample,
    MemorySample,
    PercentSample,
    SystemResourcesSnapshot,
    format_bytes_iec,
    format_bytes_rate_iec,
)
from lbs.ui import DashboardSnapshot


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (-10, 0.0),
        (0, 0.0),
        (32.25, 32.25),
        (130.0, 100.0),
        (math.nan, 0.0),
    ],
)
def test_percent_sample_clamps_to_valid_range(value, expected):
    sample = PercentSample(available=True, value=value)
    assert sample.value == expected


def test_memory_sample_clamps_bytes_and_derives_percent_from_bytes():
    sample = MemorySample(
        available=True,
        used_bytes=2_000,
        total_bytes=1_000,
        used_percent=12.0,
    )
    assert sample.used_bytes == 1_000
    assert sample.total_bytes == 1_000
    assert sample.used_percent == 100.0


def test_memory_sample_uses_explicit_percent_when_total_is_missing():
    sample = MemorySample(
        available=True,
        used_bytes=-10,
        total_bytes=0,
        used_percent=42.5,
    )
    assert sample.used_bytes == 0
    assert sample.total_bytes == 0
    assert sample.used_percent == 42.5


def test_disk_io_sample_clamps_negative_rates():
    sample = DiskIoSample(
        available=True,
        read_bytes_per_second=-1,
        write_bytes_per_second=1024.0,
    )
    assert sample.read_bytes_per_second == 0.0
    assert sample.write_bytes_per_second == 1024.0


def test_disk_free_sample_clamps_and_derives_used_percent():
    sample = DiskFreeSample(
        available=True,
        volume="D:\\",
        free_bytes=2_000,
        total_bytes=1_000,
        used_percent=5.0,
    )
    assert sample.free_bytes == 1_000
    assert sample.total_bytes == 1_000
    assert sample.used_percent == 0.0


def test_system_resources_snapshot_defaults_to_unavailable_metrics():
    snapshot = SystemResourcesSnapshot()
    assert snapshot.cpu.available is False
    assert snapshot.memory.available is False
    assert snapshot.disk_io.available is False
    assert snapshot.disk_free.available is False


def test_dashboard_snapshot_has_default_system_resources_payload():
    dashboard = DashboardSnapshot(queue_percent=10.0, current_job_idx=1, total_jobs=3)
    assert dashboard.system_resources.cpu.available is False
    assert dashboard.system_resources.memory.available is False
    assert dashboard.system_resources.disk_io.available is False
    assert dashboard.system_resources.disk_free.available is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KiB"),
        (1536, "1.5 KiB"),
        (1024**2, "1.0 MiB"),
        (5 * 1024**3, "5.0 GiB"),
    ],
)
def test_format_bytes_iec(value, expected):
    assert format_bytes_iec(value) == expected


def test_format_bytes_iec_clamps_invalid_values():
    assert format_bytes_iec(-1) == "0 B"
    assert format_bytes_iec(math.nan) == "0 B"


def test_format_bytes_rate_iec_uses_per_second_suffix():
    assert format_bytes_rate_iec(1024) == "1.0 KiB/s"
