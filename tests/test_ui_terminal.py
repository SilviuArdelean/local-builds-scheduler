# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for Phase 4: lbs.ui.terminal capabilities and flicker-free SplitViewportManager.
"""

from __future__ import annotations

import io
import os
import re
from unittest.mock import patch

from lbs.ui import (
    SplitViewportManager,
    TerminalCapabilities,
    detect_capabilities,
)


class _EncodedStream(io.StringIO):
    def __init__(self, encoding: str = "utf-8", is_tty: bool = True) -> None:
        super().__init__()
        self._encoding = encoding
        self._is_tty = is_tty

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return self._encoding

    def isatty(self) -> bool:
        return self._is_tty


def test_detect_capabilities_non_tty_disables_ansi_and_split():
    """Non-TTY streams disable ANSI colors, OSC titles, and DECSTBM split-screen."""
    stream = _EncodedStream(encoding="utf-8", is_tty=False)
    caps = detect_capabilities(stream, env={"COLORTERM": "truecolor"}, platform="linux")

    assert caps.is_tty is False
    assert caps.use_ansi is False
    assert caps.color_system is None
    assert caps.use_unicode is True
    assert caps.supports_split_screen is False
    assert caps.supports_osc_title is False


def test_detect_capabilities_dumb_terminal_falls_back_to_plain():
    """TERM=dumb disables ANSI colors and split-screen even on a TTY."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps = detect_capabilities(stream, env={"TERM": "dumb"}, platform="linux")

    assert caps.is_tty is True
    assert caps.use_ansi is False
    assert caps.color_system is None
    assert caps.supports_split_screen is False
    assert caps.supports_osc_title is False


def test_detect_capabilities_no_color_preserves_monochrome_split_on_tty():
    """NO_COLOR=1 disables color styling while keeping monochrome TTY split-screen."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps = detect_capabilities(
        stream,
        env={"NO_COLOR": "1", "COLORTERM": "truecolor"},
        platform="linux",
    )

    assert caps.is_tty is True
    assert caps.use_ansi is False
    assert caps.color_system is None
    assert caps.use_unicode is True
    assert caps.supports_split_screen is True


def test_detect_capabilities_windows_terminal_and_ascii_codepage():
    """Windows Terminal enables truecolor; cp1252/ascii stream disables Unicode glyphs."""
    utf8_stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps_wt = detect_capabilities(
        utf8_stream,
        env={"WT_SESSION": "wt-guid"},
        platform="win32",
    )
    assert caps_wt.use_ansi is True
    assert caps_wt.color_system == "truecolor"
    assert caps_wt.use_unicode is True
    assert caps_wt.supports_split_screen is True

    ascii_stream = _EncodedStream(encoding="cp1252", is_tty=True)
    caps_cp1252 = detect_capabilities(
        ascii_stream,
        env={"TERM": "xterm-256color"},
        platform="linux",
    )
    assert caps_cp1252.use_ansi is True
    assert caps_cp1252.color_system == "256"
    assert caps_cp1252.use_unicode is False


def test_detect_capabilities_cmder_uses_safe_non_split_fallback():
    """Cmder keeps ANSI features but avoids unreliable DECSTBM split-screen."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)

    for env in (
        {"CMDER_ROOT": r"C:\tools\cmder", "TERM": "xterm-256color"},
        {"ConEmuPID": "1234", "ConEmuANSI": "ON", "TERM": "xterm-256color"},
    ):
        caps = detect_capabilities(
            stream,
            env=env,
            platform="linux",
        )
        assert caps.is_tty is True
        assert caps.use_ansi is True
        assert caps.supports_osc_title is True
        assert caps.supports_split_screen is False


def test_viewport_enable_paint_row_diffing_and_disable():
    """Verify atomic row-level diffing: unchanged frames write 0 bytes, single-row changes repaint only that row."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps = TerminalCapabilities(
        is_tty=True,
        use_ansi=True,
        color_system="truecolor",
        use_unicode=True,
        supports_split_screen=True,
        supports_osc_title=True,
    )
    vp = SplitViewportManager(stream=stream, capabilities=caps)

    with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))):
        assert vp.enable(initial_height=4) is True
        assert vp.active is True
        assert vp.status_start == 1
        assert vp.status_lines_count == 4
        assert vp.scroll_start == 5
        assert vp.scroll_end == 30

        enable_out = stream.getvalue()
        assert "\033[2J\033[3J\033[H" in enable_out
        assert "\033[5;30r" in enable_out
        assert "\033[5;1H" in enable_out

        # Frame 1: paints all 4 rows
        stream.seek(0)
        stream.truncate(0)
        frame1 = ["row-1", "row-2", "elapsed 00:00:01", "sep"]
        assert vp.paint(frame1) is True
        out1 = stream.getvalue()
        for r in range(1, 5):
            assert f"\033[{r};1H\033[2K" in out1
        assert out1.startswith("\033[?25l\033[?7l\0337")
        assert out1.endswith("\0338\033[?7h\033[?25h")

        # Frame 2 (identical): writes ZERO bytes
        stream.seek(0)
        stream.truncate(0)
        assert vp.paint(list(frame1)) is False
        assert stream.getvalue() == ""

        # Frame 3 (only row 3 changed, simulating 1 Hz timer tick): paints ONLY row 3
        stream.seek(0)
        stream.truncate(0)
        frame3 = ["row-1", "row-2", "elapsed 00:00:02", "sep"]
        assert vp.paint(frame3) is True
        out3 = stream.getvalue()
        assert "\033[3;1H\033[2Kelapsed 00:00:02\033[0m\033[K" in out3
        for row_num in (1, 2, 3, 4):
            assert f"\033[{row_num};1H\033[2K" in out3
        assert "\033[?7l" in out3
        assert "\033[?7h" in out3

        # Disable restores full-screen margins and cursor
        stream.seek(0)
        stream.truncate(0)
        vp.disable()
        assert vp.active is False
        out_disable = stream.getvalue()
        assert "\033[r" in out_disable
        assert "\033[30;1H\033[?25h\n\033[K" in out_disable


def test_viewport_uses_supplied_terminal_size_consistently():
    """A frame uses the caller's geometry snapshot instead of sampling during paint."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps = TerminalCapabilities(
        is_tty=True,
        use_ansi=True,
        color_system="truecolor",
        use_unicode=True,
        supports_split_screen=True,
        supports_osc_title=True,
    )
    vp = SplitViewportManager(stream=stream, capabilities=caps)

    with patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
        assert vp.enable(initial_height=3) is True

    stream.seek(0)
    stream.truncate(0)
    assert vp.paint(
        ["one", "two", "three"],
        terminal_size=(120, 36),
    ) is True

    assert vp.last_term_cols == 120
    assert vp.last_term_lines == 36
    assert vp.scroll_end == 36


def test_viewport_debounces_transient_terminal_sizes():
    """A resized terminal is adopted after two consecutive identical samples."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps = TerminalCapabilities(
        is_tty=True,
        use_ansi=True,
        color_system="truecolor",
        use_unicode=True,
        supports_split_screen=True,
        supports_osc_title=True,
    )
    vp = SplitViewportManager(stream=stream, capabilities=caps)

    sizes = iter([
        os.terminal_size((80, 24)),
        os.terminal_size((120, 36)),
        os.terminal_size((100, 30)),
        os.terminal_size((120, 36)),
        os.terminal_size((120, 36)),
    ])
    with patch("shutil.get_terminal_size", side_effect=lambda fallback: next(sizes)):
        assert vp.enable(initial_height=3) is True
        assert vp.get_stable_terminal_size() == (80, 24)
        assert vp.get_stable_terminal_size() == (80, 24)
        assert vp.get_stable_terminal_size() == (80, 24)
        assert vp.get_stable_terminal_size() == (120, 36)


def test_viewport_dynamic_dashboard_height_and_terminal_resize():
    """Verify growing/shrinking dashboard rows (e.g. wrapped CMD) and terminal shrinks stay clamped."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps = TerminalCapabilities(
        is_tty=True,
        use_ansi=True,
        color_system="truecolor",
        use_unicode=True,
        supports_split_screen=True,
        supports_osc_title=True,
    )
    vp = SplitViewportManager(stream=stream, capabilities=caps)

    with patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 24))):
        assert vp.enable(initial_height=5) is True
        vp.paint(["a", "b", "c", "d", "e"])

        # Dashboard grows from 5 rows to 8 rows (e.g. long command wrapped)
        stream.seek(0)
        stream.truncate(0)
        vp.paint(["a", "b", "c", "d", "e", "f", "g", "h"])
        out_grow = stream.getvalue()

        assert vp.status_lines_count == 8
        assert vp.scroll_start == 9
        assert vp.scroll_end == 24
        assert "\033[9;24r" in out_grow
        for row_num in range(1, 9):
            assert f"\033[{row_num};1H\033[2K" in out_grow

    # Terminal shrinks to 50x6 while dashboard tries to draw 10 rows -> must clamp to 6 rows max
    stream.seek(0)
    stream.truncate(0)
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((50, 6))):
        vp.paint([f"line-{i}" for i in range(10)])

    out_shrink = stream.getvalue()
    assert vp.status_lines_count == 5
    assert vp.scroll_start == 6
    assert vp.scroll_end == 6
    addressed_rows = [int(m) for m in re.findall(r"\x1b\[(\d+);1H", out_shrink)]
    assert addressed_rows
    assert min(addressed_rows) >= 1
    assert max(addressed_rows) <= 6

    vp.disable()


def test_viewport_disabled_when_terminal_too_short_or_unsupported():
    """enable() returns False and writes nothing when terminal is too short or non-TTY."""
    stream = _EncodedStream(encoding="utf-8", is_tty=True)
    caps_ok = detect_capabilities(stream, force_tty=True, env={"WT_SESSION": "1"}, platform="win32")
    vp_short = SplitViewportManager(stream=stream, capabilities=caps_ok)

    with patch("shutil.get_terminal_size", return_value=os.terminal_size((80, 8))):
        assert vp_short.enable() is False
    assert vp_short.active is False
    assert stream.getvalue() == ""

    caps_plain = detect_capabilities(stream, force_tty=False)
    vp_plain = SplitViewportManager(stream=stream, capabilities=caps_plain)
    with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 30))):
        assert vp_plain.enable() is False
    assert vp_plain.active is False
    assert stream.getvalue() == ""
