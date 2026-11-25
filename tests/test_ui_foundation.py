# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for Phase 1 UI foundation: lbs.ui.theme and lbs.ui.state.
"""

from __future__ import annotations

import math

import pytest
from rich import box

from lbs.ui import (
    ASCII_GLYPHS,
    CYAN,
    DARK_GRAY,
    GRAY,
    GREEN,
    MAGENTA,
    PALETTE,
    RED,
    UNICODE_GLYPHS,
    YELLOW,
    BuildProgress,
    DashboardSnapshot,
    ExecutionStatus,
    build_rich_theme,
    format_compact_duration,
    format_hms,
    get_glyphs,
    highlight_command,
    status_color,
)


def test_palette_matches_btop_specification():
    """Verify exact hex color values defined in the dashboard color scheme."""
    assert CYAN == "#55D8ED"
    assert GREEN == "#64DE91"
    assert YELLOW == "#F5D078"
    assert RED == "#F17878"
    assert MAGENTA == "#B69CF5"
    assert GRAY == "#8999A8"
    assert DARK_GRAY == "#29343C"

    assert PALETTE["cyan"] == "#55D8ED"
    assert PALETTE["green"] == "#64DE91"
    assert PALETTE["yellow"] == "#F5D078"
    assert PALETTE["red"] == "#F17878"
    assert PALETTE["magenta"] == "#B69CF5"
    assert PALETTE["gray"] == "#8999A8"
    assert PALETTE["dark_gray"] == "#29343C"


def test_glyph_sets_and_ascii_encodability():
    """Verify Unicode vs ASCII glyph selection and strict ASCII compatibility."""
    uni = get_glyphs(True)
    asc = get_glyphs(False)

    assert uni is UNICODE_GLYPHS
    assert asc is ASCII_GLYPHS

    assert uni.box_style is box.ROUNDED
    assert asc.box_style is box.ASCII

    # Every ASCII glyph must be strictly ASCII-encodable
    for field_val in (
        asc.bar_fill,
        asc.bar_empty,
        asc.passed,
        asc.failed,
        asc.remaining,
        asc.dot,
        asc.rule_char,
        asc.em_dash,
    ):
        field_val.encode("ascii")


def test_build_rich_theme_contains_expected_styles():
    """Verify Rich Theme registers all semantic dashboard style keys."""
    theme = build_rich_theme()
    for key in (
        "dashboard.header",
        "dashboard.border.main",
        "dashboard.border.passed",
        "dashboard.border.failed",
        "dashboard.border.remaining",
        "dashboard.border.muted",
        "dashboard.queue",
        "dashboard.build",
        "dashboard.elapsed",
        "dashboard.passed",
        "dashboard.failed",
        "dashboard.remaining",
        "dashboard.target",
        "dashboard.config",
        "dashboard.muted",
        "dashboard.track",
    ):
        assert key in theme.styles


@pytest.mark.parametrize(
    ("status", "expected_color"),
    [
        (ExecutionStatus.RUNNING, GREEN),
        (ExecutionStatus.COMPLETED, GREEN),
        (ExecutionStatus.RETRYING, YELLOW),
        (ExecutionStatus.FAILED, RED),
        (ExecutionStatus.INTERRUPTED, RED),
    ],
)
def test_status_color_mapping(status, expected_color):
    """Verify execution statuses map to the intended semantic palette colors."""
    assert status_color(status) == expected_color


def test_highlight_command_styles_build_config_tokens_and_preserves_text():
    """Verify --debug/--release/out/Debug tokens are styled in magenta without altering text."""
    cmd = "python3 build.py --shared --debug --ccache -t chrome [literal]"
    text = highlight_command(cmd, use_color=True)

    # Literal text (including Rich-like brackets) must remain untouched
    assert text.plain == cmd

    magenta_spans = [
        cmd[s.start:s.end]
        for s in text.spans
        if MAGENTA.lower() in str(s.style).lower()
    ]
    assert magenta_spans == ["--debug"]


def test_highlight_command_various_build_systems_and_no_false_positives():
    """Verify highlighting for cargo, cmake, ninja, msbuild and non-matching identifiers."""
    cases = [
        ("cargo build --release", ["--release"]),
        ("cmake -DCMAKE_BUILD_TYPE=Release ..", ["Release"]),
        (r"ninja -C out\Debug chrome", ["Debug"]),
        ("ninja -C out/RelWithDebInfo chrome", ["RelWithDebInfo"]),
        ("msbuild /p:Configuration=Debug app.sln", ["Debug"]),
        ("echo debugger release_notes my_debug", []),
    ]
    for cmd, expected in cases:
        text = highlight_command(cmd, use_color=True)
        assert text.plain == cmd
        matched = [
            cmd[s.start:s.end]
            for s in text.spans
            if MAGENTA.lower() in str(s.style).lower()
        ]
        assert matched == expected


def test_highlight_command_no_color_returns_plain_text():
    """When use_color is False, command text has no styling spans."""
    cmd = "python3 build.py --debug --release"
    text = highlight_command(cmd, use_color=False)
    assert text.plain == cmd
    assert text.spans == []
    assert str(text.style) == ""


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00:00:00"),
        (-5.2, "00:00:00"),
        (float("nan"), "00:00:00"),
        (float("inf"), "00:00:00"),
        (59.9, "00:00:59"),
        (60, "00:01:00"),
        (2596, "00:43:16"),
        (3661, "01:01:01"),
        (360000, "100:00:00"),
    ],
)
def test_format_hms(seconds, expected):
    """Verify HH:MM:SS duration formatting and invalid-input clamping."""
    assert format_hms(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (-10, "0s"),
        (float("nan"), "0s"),
        (43.8, "43s"),
        (60, "1m 00s"),
        (65, "1m 05s"),
        (1543, "25m 43s"),
        (3600, "1h 00m 00s"),
        (3912, "1h 05m 12s"),
    ],
)
def test_format_compact_duration(seconds, expected):
    """Verify compact human-readable duration formatting."""
    assert format_compact_duration(seconds) == expected


def test_build_progress_percent_and_formatted_counts():
    """Verify BuildProgress percentage computation, clamping, and comma formatting."""
    bp = BuildProgress(completed=43345, total=63295)
    assert bp.percent == pytest.approx(68.48092266371751)
    assert f"{bp.percent:.1f}%" == "68.5%"
    assert bp.formatted_counts == "43,345 / 63,295"

    # Edge cases: zero total, negative completed, overflow completed
    assert BuildProgress(completed=5, total=0).percent == 0.0
    assert BuildProgress(completed=-10, total=100).percent == 0.0
    assert BuildProgress(completed=150, total=100).percent == 100.0


def test_dashboard_snapshot_helpers_and_immutability():
    """Verify DashboardSnapshot clamped percent, phase_label, status_label, and immutability."""
    snap = DashboardSnapshot(
        queue_percent=50.0,
        current_job_idx=2,
        total_jobs=2,
        build_progress=BuildProgress(43345, 63295),
        total_elapsed_seconds=2596,
        active_elapsed_seconds=1543,
        passed_jobs=1,
        failed_jobs=0,
        remaining_jobs=1,
        target_name="asb-d-main",
        phase_name="build",
        command_text="python3 build.py --shared --debug --ccache -t chrome",
        log_path=r"logs\2026-11-11_asb-d-main_build.log",
        status=ExecutionStatus.RUNNING,
    )
    assert snap.clamped_queue_percent == 50.0
    assert snap.phase_label == "BUILD"
    assert snap.status_label == "RUNNING"

    # Frozen dataclass rejects mutation
    with pytest.raises(AttributeError):
        snap.target_name = "mutated"  # type: ignore[misc]

    # Default / blank phase maps to RUN
    snap_default = DashboardSnapshot(
        queue_percent=120.5,
        current_job_idx=1,
        total_jobs=1,
        phase_name="default",
    )
    assert snap_default.clamped_queue_percent == 100.0
    assert snap_default.phase_label == "RUN"

    # NaN / negative queue_percent clamps to 0.0
    snap_nan = DashboardSnapshot(
        queue_percent=math.nan,
        current_job_idx=1,
        total_jobs=1,
        phase_name="",
    )
    assert snap_nan.clamped_queue_percent == 0.0
    assert snap_nan.phase_label == "RUN"

    # Retrying status label includes attempt counter
    snap_retry = DashboardSnapshot(
        queue_percent=25.0,
        current_job_idx=1,
        total_jobs=2,
        status=ExecutionStatus.RETRYING,
        retry_attempt=2,
        max_retries=3,
    )
    assert snap_retry.status_label == "RETRYING (1/3)"
