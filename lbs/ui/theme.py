# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.ui.theme – Color palette, glyph sets, and styling helpers for the LBS dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from rich import box
from rich.text import Text
from rich.theme import Theme

from lbs.ui.state import ExecutionStatus

# btop-inspired high-contrast palette for dark terminals
CYAN = "#55D8ED"
GREEN = "#64DE91"
YELLOW = "#F5D078"
RED = "#F17878"
MAGENTA = "#B69CF5"
GRAY = "#8999A8"
DARK_GRAY = "#29343C"
TEXT_PRIMARY = "#E6EDF3"

PALETTE: dict[str, str] = {
    "cyan": CYAN,
    "green": GREEN,
    "yellow": YELLOW,
    "red": RED,
    "magenta": MAGENTA,
    "gray": GRAY,
    "dark_gray": DARK_GRAY,
    "text_primary": TEXT_PRIMARY,
}

# Matches build configuration flags (case-insensitive, e.g. --debug, --release)
# and capitalized configuration values in assignments/paths/standalone tokens
# (e.g. out/Debug, -DCMAKE_BUILD_TYPE=Release) without matching inside identifiers.
_BUILD_CONFIG_FLAG_RE = re.compile(
    r"(?:(?<=^)|(?<=\s))--(?:debug|release|relwithdebinfo|minsizerel)(?=$|\s|=)",
    re.IGNORECASE,
)
_BUILD_CONFIG_VALUE_RE = re.compile(
    r"(?<==)(?:Debug|Release|RelWithDebInfo|MinSizeRel)(?=$|\s|[\"'\\/,;])"
    r"|(?<=[\\/])(?:Debug|Release|RelWithDebInfo|MinSizeRel)(?=$|\s|[\\/\"'])"
    r"|(?:(?<=^)|(?<=\s))(?:Debug|Release|RelWithDebInfo|MinSizeRel)(?=$|\s)"
)


@dataclass(frozen=True)
class GlyphSet:
    """Box-drawing, bar, and status glyphs for Unicode or ASCII terminals."""

    bar_fill: str
    bar_empty: str
    passed: str
    failed: str
    remaining: str
    dot: str
    rule_char: str
    em_dash: str
    box_style: box.Box


UNICODE_GLYPHS = GlyphSet(
    bar_fill="█",
    bar_empty="░",
    passed="✓",
    failed="✗",
    remaining="◉",
    dot="●",
    rule_char="─",
    em_dash="—",
    box_style=box.ROUNDED,
)

ASCII_GLYPHS = GlyphSet(
    bar_fill="#",
    bar_empty="-",
    passed="+",
    failed="x",
    remaining="*",
    dot="*",
    rule_char="-",
    em_dash="-",
    box_style=box.ASCII,
)


def get_glyphs(use_unicode: bool) -> GlyphSet:
    """Returns Unicode or ASCII glyph set based on terminal encoding capabilities."""
    return UNICODE_GLYPHS if use_unicode else ASCII_GLYPHS


def build_rich_theme() -> Theme:
    """Constructs the Rich Theme mapping semantic dashboard styles to palette colors."""
    return Theme(
        {
            "dashboard.header": f"bold {CYAN}",
            "dashboard.border.main": CYAN,
            "dashboard.border.passed": GREEN,
            "dashboard.border.failed": RED,
            "dashboard.border.remaining": YELLOW,
            "dashboard.border.muted": DARK_GRAY,
            "dashboard.queue": f"bold {CYAN}",
            "dashboard.queue.bar": CYAN,
            "dashboard.build": f"bold {GREEN}",
            "dashboard.build.bar": GREEN,
            "dashboard.elapsed": f"bold {YELLOW}",
            "dashboard.passed": f"bold {GREEN}",
            "dashboard.failed": f"bold {RED}",
            "dashboard.remaining": f"bold {YELLOW}",
            "dashboard.target": f"bold {YELLOW}",
            "dashboard.config": f"bold {MAGENTA}",
            "dashboard.muted": GRAY,
            "dashboard.track": DARK_GRAY,
            "dashboard.text": TEXT_PRIMARY,
        }
    )


def status_color(status: ExecutionStatus) -> str:
    """Maps an ExecutionStatus to its semantic hex color."""
    if status in (ExecutionStatus.RUNNING, ExecutionStatus.COMPLETED):
        return GREEN
    if status == ExecutionStatus.RETRYING:
        return YELLOW
    return RED


def highlight_command(command: str, use_color: bool = True) -> Text:
    """Returns a Rich Text representation of a command, highlighting build
    configuration tokens (e.g. --debug, --release, out/Debug) in magenta when
    color is enabled. Literal brackets and characters are preserved untouched.
    """
    if not use_color:
        return Text(command)

    styled = Text(command, style=TEXT_PRIMARY)
    for pattern in (_BUILD_CONFIG_FLAG_RE, _BUILD_CONFIG_VALUE_RE):
        for match in pattern.finditer(command):
            styled.stylize(f"bold {MAGENTA}", match.start(), match.end())
    return styled
