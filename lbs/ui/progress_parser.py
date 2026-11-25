# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.ui.progress_parser – Extracts reliable build action progress from compiler output.
"""

from __future__ import annotations

import re

from lbs.ui.state import BuildProgress

# Matches Ninja / Siso / Autoninja progress lines anchored at line start, e.g.:
#   [43345/63295] 25m43.62s F CXX obj/content/browser/browser/sd_jwt.obj
#   [120/450] CXX obj/foo.o
#   [1/1] LINK chrome.exe
_NINJA_SISO_RE = re.compile(r"^\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]\s+\S")


class BuildProgressParser:
    """Stateful parser extracting reliable (completed, total) build progress
    from sanitized compiler output lines.
    """

    def __init__(self) -> None:
        self._current: BuildProgress | None = None

    @property
    def current(self) -> BuildProgress | None:
        """Most recently observed valid BuildProgress, or None if unavailable."""
        return self._current

    def reset(self) -> None:
        """Clears cached build progress (called when starting a new command/phase)."""
        self._current = None

    @staticmethod
    def parse_line(line: str) -> BuildProgress | None:
        """Parses a single sanitized output line into BuildProgress if reliable."""
        if not line:
            return None

        match = _NINJA_SISO_RE.match(line)
        if not match:
            return None

        completed = int(match.group(1))
        total = int(match.group(2))
        if total <= 0 or completed < 0 or completed > total:
            return None

        return BuildProgress(completed=completed, total=total, source="ninja")

    def feed_line(self, text: str) -> BuildProgress | None:
        """Processes a sanitized output line (or multi-line chunk from CR->LF
        normalization). Returns the new BuildProgress if it changed since the
        last accepted value, otherwise None.
        """
        if not text:
            return None

        latest: BuildProgress | None = None
        for subline in text.splitlines():
            parsed = self.parse_line(subline)
            if parsed is not None:
                latest = parsed

        if latest is None or latest == self._current:
            return None

        self._current = latest
        return latest
