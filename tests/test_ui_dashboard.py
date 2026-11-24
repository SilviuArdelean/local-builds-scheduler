# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for Phase 3: lbs.ui.dashboard responsive Rich renderer.
"""

from __future__ import annotations

from dataclasses import replace
import re

import pytest
from rich.cells import cell_len

from lbs.ui import (
    BuildProgress,
    DashboardRenderer,
    DashboardSnapshot,
    ExecutionStatus,
    LayoutTier,
    RenderProfile,
    render_plain_milestone,
    select_layout_tier,
)

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _strip_ansi(line: str) -> str:
    return _ANSI_RE.sub("", line)


def _sample_snapshot(
    *,
    with_build_progress: bool = True,
    command_text: str = "python3 build.py --shared --debug --ccache -t chrome",
    log_path: str = r"logs\2026-11-11_asb-d-main_build.log",
    status: ExecutionStatus = ExecutionStatus.RUNNING,
    phase_name: str = "build",
    cmd_idx: int = 1,
    phase_cmd_total: int = 1,
) -> DashboardSnapshot:
    return DashboardSnapshot(
        queue_percent=50.0,
        current_job_idx=2,
        total_jobs=2,
        completed_commands=1,
        total_commands=2,
        build_progress=BuildProgress(43345, 63295) if with_build_progress else None,
        total_elapsed_seconds=2596,  # 00:43:16
        active_elapsed_seconds=1543,  # 25m 43s
        passed_jobs=1,
        failed_jobs=0,
        remaining_jobs=1,
        target_name="asb-d-main",
        phase_name=phase_name,
        command_text=command_text,
        log_path=log_path,
        cmd_idx=cmd_idx,
        phase_cmd_total=phase_cmd_total,
        status=status,
    )


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [
        (120, 36, LayoutTier.FULL),
        (80, 26, LayoutTier.FULL),
        (79, 26, LayoutTier.MEDIUM),
        (80, 24, LayoutTier.MEDIUM),
        (60, 22, LayoutTier.MEDIUM),
        (59, 22, LayoutTier.COMPACT),
        (100, 18, LayoutTier.COMPACT),
        (80, 12, LayoutTier.MINIMAL),
        (80, 9, LayoutTier.PLAIN),
        (25, 30, LayoutTier.PLAIN),
    ],
)
def test_select_layout_tier_breakpoints(width, height, expected):
    """Verify responsive layout tier selection across width/height boundaries."""
    assert select_layout_tier(width, height) == expected


def test_full_layout_contains_all_btop_sections_and_truecolor_palette():
    """Verify full layout renders all 4 sections, rounded borders, and exact hex colors."""
    renderer = DashboardRenderer()
    snap = _sample_snapshot()
    lines = renderer.render(
        snap,
        width=100,
        height=34,
        profile=RenderProfile(use_ansi=True, color_system="truecolor", use_unicode=True),
    )

    assert len(lines) == 15
    plain_lines = [_strip_ansi(line) for line in lines]
    plain = "\n".join(plain_lines)
    raw = "\n".join(lines)

    # Every line fits cleanly within terminal width
    for pl in plain_lines:
        assert cell_len(pl) <= 100

    # Rounded Unicode borders and btop glyphs
    assert "╭" in plain and "╮" in plain and "╰" in plain and "╯" in plain
    assert "█" in plain and "░" in plain

    # Section 1: Build monitor
    assert "LOCAL BUILDS SCHEDULER" in plain
    assert "● RUNNING" in plain
    assert "Queue progress" in plain
    assert "50.0%" in plain
    assert "Job 2 of 2" in plain
    assert "Build progress" in plain
    assert "68.5%" in plain
    assert "43,345 / 63,295" in plain
    assert "Total elapsed" in plain
    assert "00:43:16" in plain
    assert "Build: 25m 43s" in plain

    # Section 2: Dedicated horizontal stats panels (all on the same row)
    stats_border_row = next(line for line in plain_lines if "PASSED" in line)
    assert "FAILED" in stats_border_row
    assert "REMAINING" in stats_border_row
    stats_value_row = next(line for line in plain_lines if "✓ 1" in line)
    assert "✗ 0" in stats_value_row
    assert "◉ 1" in stats_value_row

    # Section 3: Active target panel
    assert "ACTIVE TARGET" in plain
    assert "● BUILD" in plain
    assert "asb-d-main" in plain
    assert "CMD" in plain
    assert "python3 build.py --shared --debug --ccache -t chrome" in plain
    assert "LOG" in plain
    assert r"logs\2026-11-11_asb-d-main_build.log" in plain

    # Section 4: Live compiler output separator is the final row
    assert "LIVE COMPILER OUTPUT" in plain_lines[-1]

    # Exact btop RGB truecolor sequences for all 7 palette colors
    for rgb in (
        "85;216;237",   # #55D8ED Cyan
        "100;222;145",  # #64DE91 Green
        "245;208;120",  # #F5D078 Yellow
        "241;120;120",  # #F17878 Red
        "182;156;245",  # #B69CF5 Magenta (--debug highlight)
        "137;153;168",  # #8999A8 Gray
        "41;52;60",     # #29343C Dark gray
    ):
        assert rgb in raw


def test_unavailable_build_progress_does_not_fabricate_percentage():
    """When build_progress is None, render subdued dash and step/no-progress note."""
    renderer = DashboardRenderer()
    snap = _sample_snapshot(
        with_build_progress=False,
        phase_name="sync",
        cmd_idx=2,
        phase_cmd_total=4,
    )
    lines = renderer.render(snap, width=100, height=34)
    plain = "\n".join(_strip_ansi(line) for line in lines)

    assert "Build progress" in plain
    assert "—" in plain
    assert "Step 2 of 4" in plain
    assert "68.5%" not in plain
    assert "● SYNC" in plain


def test_stats_values_render_inline_with_double_space_separator():
    """Multiline stats values should be flattened inline with two-space separators."""
    renderer = DashboardRenderer()
    snap = replace(_sample_snapshot(), failed_jobs="✗ 0\n✗ 1")
    lines = renderer.render(snap, width=120, height=34)
    plain = "\n".join(_strip_ansi(line) for line in lines)

    assert "✗ 0  ✗ 1" in plain


def test_long_command_and_log_path_wrap_without_truncation():
    """Verify full active command and log path are preserved via wrapping."""
    long_cmd = (
        "python3 scripts/build.py --shared --debug --ccache --enable-jumbo "
        "--target chrome_public_apk --gn-args is_component_build=true "
        "--extra-flag-alpha=1 --extra-flag-beta=2 --final-sentinel-token"
    )
    long_log = (
        r"D:\sources\silviu\local-builds-scheduler\logs\nested_dir\2026-11-11_"
        r"asb-d-main_chromium_debug_component_build_final_log_file.log"
    )
    renderer = DashboardRenderer()
    snap = _sample_snapshot(command_text=long_cmd, log_path=long_log)
    lines = renderer.render(snap, width=84, height=34, use_ansi=False)

    # Full layout grows beyond 15 lines to accommodate wrapped CMD and LOG
    assert len(lines) > 15
    for line in lines:
        assert cell_len(line) <= 84

    # Reconstruct non-border content and confirm every part of CMD and LOG survived
    joined = "".join(line.strip("│ ") for line in lines)
    assert "--final-sentinel-token" in joined
    assert "is_component_build=true" in joined
    assert "final_log_file.log" in joined


@pytest.mark.parametrize(
    ("width", "height"),
    [
        (140, 40),
        (100, 30),
        (80, 24),
        (70, 22),
        (60, 20),
        (50, 18),
        (40, 12),
        (30, 8),
    ],
)
def test_responsive_render_respects_width_and_leaves_scroll_room(width, height):
    """Across every terminal size, rows stay within width and never starve compiler output."""
    renderer = DashboardRenderer()
    snap = _sample_snapshot()
    lines = renderer.render(snap, width=width, height=height)

    assert len(lines) >= 1
    assert len(lines) < height
    for line in lines:
        assert cell_len(_strip_ansi(line)) <= width


def test_no_ansi_and_ascii_fallback_are_strictly_plain_ascii():
    """When use_ansi=False and use_unicode=False, output has zero ANSI escapes and pure ASCII."""
    renderer = DashboardRenderer()
    snap = _sample_snapshot()
    profile = RenderProfile(use_ansi=False, color_system=None, use_unicode=False)

    lines = renderer.render(snap, width=90, height=30, profile=profile)
    output = "\n".join(lines)

    assert "\x1b" not in output
    output.encode("ascii")  # Must not raise UnicodeEncodeError
    assert "+" in output and "-" in output and "|" in output
    assert "LOCAL BUILDS SCHEDULER" in output
    assert "* RUNNING" in output
    assert "+ 1" in output
    assert "x 0" in output
    assert "* 1" in output
    assert "LIVE COMPILER OUTPUT" in lines[-1]

    # Minimal tier with long command must also stay strictly ASCII-encodable (no Unicode ellipsis)
    minimal_lines = renderer.render(snap, width=48, height=12, profile=profile)
    minimal_output = "\n".join(minimal_lines)
    assert "\x1b" not in minimal_output
    minimal_output.encode("ascii")


def test_render_plain_milestone_contains_expected_fields_without_ansi():
    """Verify non-TTY milestone divider has zero ANSI codes and clean ASCII fallback."""
    snap = _sample_snapshot()
    text_ascii = render_plain_milestone(snap, use_unicode=False)

    assert "\x1b" not in text_ascii
    text_ascii.encode("ascii")
    assert "Queue Progress:" in text_ascii
    assert "50.0%" in text_ascii
    assert "Job 2 of 2" in text_ascii
    assert "asb-d-main" in text_ascii
    assert "phase: build" in text_ascii
    assert "python3 build.py --shared --debug --ccache -t chrome" in text_ascii
    assert "00:43:16" in text_ascii
    assert r"logs\2026-11-11_asb-d-main_build.log" in text_ascii
