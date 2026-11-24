# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.ui – Terminal dashboard presentation layer.
"""

from __future__ import annotations

from lbs.ui.state import (
    BuildProgress,
    DashboardSnapshot,
    ExecutionStatus,
    format_compact_duration,
    format_hms,
)
from lbs.ui.theme import (
    ASCII_GLYPHS,
    CYAN,
    DARK_GRAY,
    GRAY,
    GREEN,
    MAGENTA,
    PALETTE,
    RED,
    TEXT_PRIMARY,
    UNICODE_GLYPHS,
    YELLOW,
    GlyphSet,
    build_rich_theme,
    get_glyphs,
    highlight_command,
    status_color,
)

__all__ = [
    "ASCII_GLYPHS",
    "BuildProgress",
    "CYAN",
    "DARK_GRAY",
    "DashboardSnapshot",
    "ExecutionStatus",
    "GRAY",
    "GREEN",
    "GlyphSet",
    "MAGENTA",
    "PALETTE",
    "RED",
    "TEXT_PRIMARY",
    "UNICODE_GLYPHS",
    "YELLOW",
    "build_rich_theme",
    "format_compact_duration",
    "format_hms",
    "get_glyphs",
    "highlight_command",
    "status_color",
]
