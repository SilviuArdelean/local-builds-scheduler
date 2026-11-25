# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for Phase 2: lbs.ui.progress_parser.BuildProgressParser.
"""

from __future__ import annotations

import pytest

from lbs.ui import BuildProgress, BuildProgressParser


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        (
            "[43345/63295] 25m43.62s F CXX obj/content/browser/browser/sd_jwt.obj",
            BuildProgress(completed=43345, total=63295, source="ninja"),
        ),
        (
            "[120/450] CXX obj/foo.o",
            BuildProgress(completed=120, total=450, source="ninja"),
        ),
        (
            "[1/1] LINK chrome.exe",
            BuildProgress(completed=1, total=1, source="ninja"),
        ),
        (
            "[0/100] Regenerating ninja files",
            BuildProgress(completed=0, total=100, source="ninja"),
        ),
        (
            "  [ 12 / 340 ] CC obj/bar.obj",
            BuildProgress(completed=12, total=340, source="ninja"),
        ),
    ],
)
def test_parse_line_valid_ninja_and_siso_formats(line, expected):
    """Verify reliable extraction across Chromium Siso, Ninja, and padded formats."""
    assert BuildProgressParser.parse_line(line) == expected


@pytest.mark.parametrize(
    "line",
    [
        "",
        "   ",
        "HEAD is now at 9f8e7d6",
        "warning: unused variable 'x' [-Wunused-variable]",
        "error: [12/34] not anchored at start of line",
        "[0/0] invalid zero total",
        "[50/10] completed exceeds total",
        "[12/34]",
        "[12/34]   ",
        "[2026-11-24 19:50:00] timestamp line",
        "[11/24/2026] date with two slashes",
        "ninja: no work to do.",
    ],
)
def test_parse_line_rejects_unreliable_or_non_progress_lines(line):
    """Verify non-progress output and invalid ratios return None."""
    assert BuildProgressParser.parse_line(line) is None


def test_feed_line_tracks_state_deduplicates_and_resets():
    """Verify stateful tracking, duplicate suppression, and reset() between commands."""
    parser = BuildProgressParser()
    assert parser.current is None

    # Non-progress lines leave state as None
    assert parser.feed_line("git fetch origin\n") is None
    assert parser.current is None

    # First valid line updates state and returns BuildProgress
    p1 = parser.feed_line("[10/100] CXX a.obj\n")
    assert p1 == BuildProgress(completed=10, total=100)
    assert parser.current == p1

    # Duplicate count returns None to avoid redundant dashboard redraws
    assert parser.feed_line("[10/100] CXX b.obj\n") is None
    assert parser.current == p1

    # Advancing count returns updated progress
    p2 = parser.feed_line("[11/100] CXX c.obj\n")
    assert p2 == BuildProgress(completed=11, total=100)
    assert parser.current == p2

    # Non-progress compiler warning preserves last known progress without emitting update
    assert parser.feed_line("src/c.cc(42): warning C4100: unreferenced param\n") is None
    assert parser.current == p2

    # Reset clears cached state cleanly for the next command/phase
    parser.reset()
    assert parser.current is None
    assert parser.feed_line("[11/100] CXX c.obj\n") == BuildProgress(completed=11, total=100)


def test_feed_line_handles_multiline_cr_normalized_chunks():
    """Verify multi-line chunks (from CR->LF sanitization) yield the latest progress."""
    parser = BuildProgressParser()
    chunk = (
        "[100/500] 1m01.10s F CXX a.obj\n"
        "[101/500] 1m01.20s F CXX b.obj\n"
        "[102/500] 1m01.30s F CXX c.obj\n"
    )
    updated = parser.feed_line(chunk)
    assert updated == BuildProgress(completed=102, total=500)
    assert parser.current == BuildProgress(completed=102, total=500)
