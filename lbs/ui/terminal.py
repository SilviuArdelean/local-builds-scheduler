# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.ui.terminal – Terminal capability detection, Windows VT enablement,
and flicker-free DECSTBM split-screen viewport painting.
"""

from __future__ import annotations

import atexit
from collections.abc import Mapping
import ctypes
from dataclasses import dataclass
import os
import shutil
import sys
import threading

from lbs.ui.dashboard import ColorSystem

_UNICODE_PROBE_CHARS = "╭╮╰╯│─█░✓✗◉●—"
_STD_OUTPUT_HANDLE = -11
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004


@dataclass(frozen=True)
class TerminalCapabilities:
    """Detected terminal capabilities controlling rendering and viewport behavior."""

    is_tty: bool
    use_ansi: bool
    color_system: ColorSystem
    use_unicode: bool
    supports_split_screen: bool
    supports_osc_title: bool


def _stream_supports_unicode(stream) -> bool:
    """Returns True if the target stream encoding can encode all dashboard glyphs."""
    encoding = (
        getattr(stream, "encoding", None)
        or getattr(sys.stdout, "encoding", None)
        or "utf-8"
    )
    try:
        _UNICODE_PROBE_CHARS.encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def _has_real_fileno(stream) -> bool:
    """Returns True only if stream is backed by a real OS file descriptor."""
    if stream is None:
        return True
    try:
        stream.fileno()
        return True
    except (AttributeError, OSError, ValueError):
        return False


def enable_windows_vt_processing(
    stream=None,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Enables ANSI Virtual Terminal Processing on Windows consoles via Win32 API.

    On non-Windows platforms returns True immediately.
    On Windows, attempts SetConsoleMode(ENABLE_VIRTUAL_TERMINAL_PROCESSING) on
    STD_OUTPUT_HANDLE and falls back cleanly if unavailable.
    """
    if sys.platform != "win32":
        return True

    # Synthetic in-memory streams (e.g. io.StringIO in tests) have no OS console handle
    if not _has_real_fileno(stream):
        return True

    env_map = env if env is not None else os.environ
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(_STD_OUTPUT_HANDLE)
        if handle in (0, -1):
            return False

        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            # Handle may be a PTY/mintty pipe where GetConsoleMode returns 0
            # while ANSI sequences are natively supported.
            return bool(env_map.get("WT_SESSION") or env_map.get("TERM"))

        if mode.value & _ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True

        if kernel32.SetConsoleMode(
            handle, mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
        ):
            return True
    except Exception:
        pass

    try:
        os.system("")
        return True
    except Exception:
        return False


def _detect_color_system(
    env: Mapping[str, str],
    vt_enabled: bool,
    platform: str,
) -> ColorSystem:
    """Infers the best Rich color system supported by the current terminal."""
    colorterm = (env.get("COLORTERM") or "").strip().lower()
    term = (env.get("TERM") or "").strip().lower()
    term_program = (env.get("TERM_PROGRAM") or "").strip()

    if colorterm in ("truecolor", "24bit"):
        return "truecolor"
    if env.get("WT_SESSION"):
        return "truecolor"
    if term_program in (
        "vscode",
        "iTerm.app",
        "WezTerm",
        "Alacritty",
        "Hyper",
        "ghostty",
    ):
        return "truecolor"
    if platform == "win32" and vt_enabled:
        return "truecolor"
    if "256color" in term:
        return "256"
    if term and term != "dumb":
        return "standard"
    if vt_enabled:
        return "standard"
    return None


def detect_capabilities(
    stream=None,
    force_tty: bool | None = None,
    env: Mapping[str, str] | None = None,
    platform: str | None = None,
) -> TerminalCapabilities:
    """Detects TTY, ANSI color level, Unicode, and DECSTBM split-screen support."""
    target_stream = stream if stream is not None else sys.stdout
    env_map = env if env is not None else os.environ
    plat = platform if platform is not None else sys.platform

    if force_tty is not None:
        is_tty = bool(force_tty)
    else:
        is_tty = bool(getattr(target_stream, "isatty", lambda: False)())

    use_unicode = _stream_supports_unicode(target_stream)
    term = (env_map.get("TERM") or "").strip().lower()
    no_color = bool(env_map.get("NO_COLOR"))

    if not is_tty or term == "dumb":
        return TerminalCapabilities(
            is_tty=is_tty,
            use_ansi=False,
            color_system=None,
            use_unicode=use_unicode,
            supports_split_screen=False,
            supports_osc_title=False,
        )

    if plat == "win32":
        vt_enabled = enable_windows_vt_processing(target_stream, env=env_map)
    else:
        vt_enabled = True

    if not vt_enabled:
        return TerminalCapabilities(
            is_tty=is_tty,
            use_ansi=False,
            color_system=None,
            use_unicode=use_unicode,
            supports_split_screen=False,
            supports_osc_title=False,
        )

    if no_color:
        return TerminalCapabilities(
            is_tty=is_tty,
            use_ansi=False,
            color_system=None,
            use_unicode=use_unicode,
            supports_split_screen=True,
            supports_osc_title=True,
        )

    color_system = _detect_color_system(env_map, vt_enabled=vt_enabled, platform=plat)
    return TerminalCapabilities(
        is_tty=is_tty,
        use_ansi=color_system is not None,
        color_system=color_system,
        use_unicode=use_unicode,
        supports_split_screen=True,
        supports_osc_title=True,
    )


class SplitViewportManager:
    """Manages a top-pinned DECSTBM dashboard viewport with atomic repainting.

    Rows `1 .. status_lines_count` stay pinned at the top of the viewport while
    rows `scroll_start .. scroll_end` act as a native hardware scrolling region
    for raw live compiler output.
    """

    def __init__(
        self,
        stream=None,
        capabilities: TerminalCapabilities | None = None,
        lock: threading.RLock | None = None,
        min_terminal_lines: int = 10,
    ) -> None:
        self.stream = stream if stream is not None else sys.stdout
        self.capabilities = (
            capabilities
            if capabilities is not None
            else detect_capabilities(self.stream)
        )
        self.lock = lock if lock is not None else threading.RLock()
        self.min_terminal_lines = min_terminal_lines

        self.active = False
        self.status_start = 1
        self.status_lines_count = 0
        self.scroll_start = 1
        self.scroll_end = 24
        self.last_term_cols = 80
        self.last_term_lines = 24
        self._last_rendered_rows: list[str] = []
        self._pending_terminal_size: tuple[int, int] | None = None
        self._pending_terminal_size_count = 0
        self._atexit_registered = False

    def get_terminal_size(self) -> tuple[int, int]:
        """Returns current (columns, lines), clamped to at least (1, 1)."""
        size = shutil.get_terminal_size(fallback=(80, 24))
        return max(1, size.columns), max(1, size.lines)

    def get_stable_terminal_size(self) -> tuple[int, int]:
        """Debounces transient sizes reported while a terminal is being resized."""
        current = self.get_terminal_size()
        active = (self.last_term_cols, self.last_term_lines)
        if not self.active or current == active:
            self._pending_terminal_size = None
            self._pending_terminal_size_count = 0
            return current

        # Never keep drawing against a viewport larger than the real terminal.
        # Shrinks are applied immediately; only growth is debounced to avoid
        # repainting every intermediate maximize/drag size.
        if current[0] < active[0] or current[1] < active[1]:
            self._pending_terminal_size = None
            self._pending_terminal_size_count = 0
            return current

        if current == self._pending_terminal_size:
            self._pending_terminal_size_count += 1
        else:
            self._pending_terminal_size = current
            self._pending_terminal_size_count = 1

        if self._pending_terminal_size_count >= 2:
            self._pending_terminal_size = None
            self._pending_terminal_size_count = 0
            return current
        return active

    def invalidate(self) -> None:
        """Clears cached row contents so the next paint redraws all dashboard rows."""
        with self.lock:
            self._last_rendered_rows = []

    def enable(self, initial_height: int | None = None) -> bool:
        """Activates the top-pinned DECSTBM scrolling region if supported."""
        with self.lock:
            if self.active or not self.capabilities.supports_split_screen:
                return False

            term_cols, term_lines = self.get_terminal_size()
            if term_lines < self.min_terminal_lines:
                return False

            default_height = max(5, min(15, term_lines - 5))
            desired = default_height if initial_height is None else initial_height
            self.status_lines_count = max(1, min(desired, term_lines - 1))
            self.status_start = 1
            self.scroll_start = self.status_lines_count + 1
            self.scroll_end = term_lines
            self.last_term_cols = term_cols
            self.last_term_lines = term_lines
            self._last_rendered_rows = []
            self.active = True

            if not self._atexit_registered:
                try:
                    atexit.register(self.disable)
                    self._atexit_registered = True
                except Exception:
                    pass

            # Clear screen, scrollback buffer, home cursor, set bottom scroll region,
            # and position cursor at the first scrolling row.
            buf = (
                "\033[2J\033[3J\033[H"
                f"\033[{self.scroll_start};{self.scroll_end}r"
                f"\033[{self.scroll_start};1H"
            )
            self.stream.write(buf)
            self.stream.flush()
            return True

    def paint(
        self,
        rows: list[str],
        terminal_size: tuple[int, int] | None = None,
    ) -> bool:
        """Paints rendered dashboard rows into the top-pinned region.

        Identical frames are skipped. Changed frames repaint the complete pinned
        region so terminal reflow cannot leave fragments from a previous frame.
        """
        with self.lock:
            if not self.active:
                return False

            if terminal_size is None:
                term_cols, term_lines = self.get_terminal_size()
            else:
                term_cols, term_lines = terminal_size
                term_cols = max(1, term_cols)
                term_lines = max(1, term_lines)
            if term_lines > 1:
                desired_height = max(1, min(len(rows), term_lines - 1))
            else:
                desired_height = 1

            visible_rows = list(rows[:desired_height])

            old_term_cols = self.last_term_cols
            old_term_lines = self.last_term_lines
            old_status_start = self.status_start
            old_status_lines_count = self.status_lines_count
            old_scroll_start = self.scroll_start

            geometry_changed = (
                term_cols != old_term_cols
                or term_lines != old_term_lines
                or desired_height != old_status_lines_count
            )

            if not geometry_changed:
                if visible_rows == self._last_rendered_rows:
                    return False

                parts = ["\033[?25l\033[?7l\0337"]
                for idx, line in enumerate(visible_rows):
                    row_num = self.status_start + idx
                    if row_num > term_lines:
                        break
                    parts.append(
                        f"\033[{row_num};1H\033[2K{line}\033[0m\033[K"
                    )
                parts.append("\0338\033[?7h\033[?25h")

                self.stream.write("".join(parts))
                self.stream.flush()
                self._last_rendered_rows = visible_rows
                return True

            # Geometry changed (terminal resized or dashboard height grew/shrank)
            parts = ["\033[?25l\033[?7l\0337"]

            new_status_start = 1
            if term_lines > 1:
                new_status_lines_count = desired_height
                new_scroll_start = new_status_lines_count + 1
                new_scroll_end = term_lines
            else:
                new_status_lines_count = 1
                new_scroll_start = 1
                new_scroll_end = 1

            old_bottom = old_status_start + max(1, old_status_lines_count) - 1
            new_bottom = new_status_start + new_status_lines_count - 1
            erase_start = max(1, min(old_status_start, new_status_start))
            erase_end = min(term_lines, max(old_bottom, new_bottom))
            for row_num in range(erase_start, erase_end + 1):
                parts.append(f"\033[{row_num};1H\033[2K")

            self.status_start = new_status_start
            self.status_lines_count = new_status_lines_count
            self.scroll_start = new_scroll_start
            self.scroll_end = new_scroll_end
            self.last_term_cols = term_cols
            self.last_term_lines = term_lines

            parts.append(f"\033[{self.scroll_start};{self.scroll_end}r")

            # Keep saved cursor safely inside [scroll_start..scroll_end]
            if term_lines < old_term_lines:
                parts.append(f"\033[{self.scroll_end};1H\0337")
            elif self.scroll_start > old_scroll_start:
                parts.append(f"\033[{self.scroll_start};1H\0337")
            else:
                parts.append("\0338\0337")

            for idx, line in enumerate(visible_rows):
                row_num = self.status_start + idx
                if row_num > term_lines:
                    break
                parts.append(f"\033[{row_num};1H\033[2K{line}\033[0m\033[K")

            status_end = min(
                term_lines, self.status_start + self.status_lines_count - 1
            )
            for row_num in range(
                self.status_start + len(visible_rows), status_end + 1
            ):
                parts.append(f"\033[{row_num};1H\033[2K\033[K")

            parts.append("\0338\033[?7h\033[?25h")

            self.stream.write("".join(parts))
            self.stream.flush()
            self._last_rendered_rows = visible_rows
            return True

    def disable(self) -> None:
        """Restores full-screen terminal scrolling margins and cursor visibility."""
        with self.lock:
            if not self.active:
                return
            try:
                _, term_lines = self.get_terminal_size()
                self.stream.write(
                    f"\033[r\033[{term_lines};1H\033[?25h\n\033[K"
                )
                self.stream.flush()
            except Exception:
                pass
            finally:
                self.active = False
                self._last_rendered_rows = []
                if self._atexit_registered:
                    try:
                        atexit.unregister(self.disable)
                    except Exception:
                        pass
                    self._atexit_registered = False
