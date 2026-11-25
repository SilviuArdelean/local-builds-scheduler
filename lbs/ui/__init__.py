# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.ui – Terminal dashboard presentation layer.
"""

from __future__ import annotations

from lbs.ui.dashboard import (
    DashboardRenderer,
    LayoutTier,
    RenderProfile,
    render_plain_milestone,
    select_layout_tier,
)
from lbs.ui.progress_parser import BuildProgressParser
from lbs.ui.state import (
    BuildProgress,
    DashboardSnapshot,
    ExecutionStatus,
    format_compact_duration,
    format_hms,
)
from lbs.ui.terminal import (
    SplitViewportManager,
    TerminalCapabilities,
    detect_capabilities,
    enable_windows_vt_processing,
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
    "BuildProgressParser",
    "CYAN",
    "DARK_GRAY",
    "DashboardRenderer",
    "DashboardSnapshot",
    "ExecutionStatus",
    "GRAY",
    "GREEN",
    "GlyphSet",
    "LayoutTier",
    "MAGENTA",
    "PALETTE",
    "RED",
    "RenderProfile",
    "SplitViewportManager",
    "TEXT_PRIMARY",
    "TerminalCapabilities",
    "UNICODE_GLYPHS",
    "YELLOW",
    "build_rich_theme",
    "detect_capabilities",
    "enable_windows_vt_processing",
    "format_compact_duration",
    "format_hms",
    "get_glyphs",
    "highlight_command",
    "render_plain_milestone",
    "select_layout_tier",
    "status_color",
]
