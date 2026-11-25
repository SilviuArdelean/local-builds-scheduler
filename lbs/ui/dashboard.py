# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.ui.dashboard – Responsive btop-inspired terminal dashboard renderer using Rich.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import io
from typing import Literal, Protocol

from rich.console import Console, Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from lbs.monitoring import format_bytes_iec, format_bytes_rate_iec
from lbs.ui.state import (
    DashboardSnapshot,
    format_compact_duration,
    format_hms,
)
from lbs.ui.theme import (
    CYAN,
    DARK_GRAY,
    GRAY,
    GREEN,
    RED,
    TEXT_PRIMARY,
    YELLOW,
    GlyphSet,
    build_rich_theme,
    get_glyphs,
    highlight_command,
    status_color,
)

ColorSystem = Literal["auto", "standard", "256", "truecolor", "windows"] | None


class LayoutTier(str, Enum):
    """Responsive layout density selected from available terminal dimensions."""

    FULL = "full"
    MEDIUM = "medium"
    COMPACT = "compact"
    MINIMAL = "minimal"
    PLAIN = "plain"


class RenderProfileProtocol(Protocol):
    """Structural interface satisfied by RenderProfile and TerminalCapabilities."""

    @property
    def use_ansi(self) -> bool: ...

    @property
    def color_system(self) -> ColorSystem: ...

    @property
    def use_unicode(self) -> bool: ...


@dataclass(frozen=True)
class RenderProfile:
    """Controls color, ANSI, and Unicode rendering for a dashboard frame."""

    use_ansi: bool = True
    color_system: ColorSystem = "truecolor"
    use_unicode: bool = True


def select_layout_tier(width: int, height: int) -> LayoutTier:
    """Selects the most readable layout tier that leaves ample scrolling space
    for live compiler output.
    """
    if height < 10 or width < 28:
        return LayoutTier.PLAIN
    if height < 14:
        return LayoutTier.MINIMAL
    if width < 60 or height < 22:
        return LayoutTier.COMPACT
    if width < 80 or height < 26:
        return LayoutTier.MEDIUM
    return LayoutTier.FULL


def _style(style_name: str, use_color: bool) -> str:
    return style_name if use_color else ""


def _make_bar(
    percent: float,
    bar_width: int,
    fill_color: str,
    glyphs: GlyphSet,
    use_color: bool,
    available: bool = True,
) -> Text:
    """Builds a fixed-width horizontal progress bar with dark-gray inactive track."""
    width = max(4, bar_width)
    if not available:
        return Text(glyphs.bar_empty * width, style=_style(DARK_GRAY, use_color))

    clamped = max(0.0, min(100.0, percent))
    filled = max(0, min(width, round((clamped / 100.0) * width)))
    empty = width - filled

    bar = Text()
    if filled > 0:
        bar.append(glyphs.bar_fill * filled, style=_style(fill_color, use_color))
    if empty > 0:
        bar.append(glyphs.bar_empty * empty, style=_style(DARK_GRAY, use_color))
    return bar


def _make_border_title(
    left: Text,
    right: Text | None,
    panel_width: int,
    border_char: str,
    border_color: str,
    use_color: bool,
) -> Text:
    """Creates a left+right aligned title string embedded inside a Panel's top border.

    Produces borders matching:
        ╭─ LOCAL BUILDS SCHEDULER ─────────────────────── ● RUNNING ─╮
    Gracefully collapses on narrow widths without overflowing panel_width.
    """
    # Rich Panel wraps title with "╭─ " (3 cols) on the left and " ─╮" (3 cols) on the right
    avail = max(0, panel_width - 6)
    if right is None or avail <= 0:
        return left

    left_len = left.cell_len
    right_len = right.cell_len

    # Need at least 1 space + 1 border char + 1 space between left and right
    if left_len + right_len + 3 <= avail:
        filler_len = avail - left_len - right_len - 2
        combined = Text()
        combined.append_text(left)
        combined.append(" ")
        combined.append(border_char * filler_len, style=_style(border_color, use_color))
        combined.append(" ")
        combined.append_text(right)
        return combined

    if left_len + right_len + 1 <= avail:
        combined = Text()
        combined.append_text(left)
        combined.append(" ")
        combined.append_text(right)
        return combined

    return left


def _make_output_separator(width: int, glyphs: GlyphSet, use_color: bool) -> Text:
    """Builds the subtle single-line separator above the live compiler output area."""
    safe_width = max(1, width)
    rule_ch = glyphs.rule_char
    label = "LIVE COMPILER OUTPUT"

    prefix = f"{rule_ch * 2} "
    label_part = f"{label} "
    if len(prefix) + len(label_part) < safe_width:
        tail_len = safe_width - len(prefix) - len(label_part)
        line = Text()
        line.append(prefix, style=_style(DARK_GRAY, use_color))
        line.append(label_part, style=_style(GRAY, use_color))
        line.append(rule_ch * tail_len, style=_style(DARK_GRAY, use_color))
        return line

    short_label = "OUTPUT"
    short_prefix = f"{rule_ch} {short_label} "
    if len(short_prefix) < safe_width:
        tail_len = safe_width - len(short_prefix)
        line = Text()
        line.append(f"{rule_ch} ", style=_style(DARK_GRAY, use_color))
        line.append(f"{short_label} ", style=_style(GRAY, use_color))
        line.append(rule_ch * tail_len, style=_style(DARK_GRAY, use_color))
        return line

    return Text(rule_ch * safe_width, style=_style(DARK_GRAY, use_color))


def _sanitize_single_line(text: str) -> str:
    """Normalizes embedded newlines/tabs in command or path strings for panel display."""
    return " ".join((text or "").replace("\r", " ").replace("\n", " ").replace("\t", " ").split())


def _iter_inline_items(value: object) -> list[str]:
    """Normalizes scalar/list/multiline values into a clean list of inline items."""
    if isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = str(value).replace("\r", "\n").split("\n")
    items: list[str] = []
    for item in raw_items:
        cleaned = " ".join(item.replace("\t", " ").split())
        if cleaned:
            items.append(cleaned)
    return items


def render_plain_milestone(
    snapshot: DashboardSnapshot,
    use_unicode: bool = False,
) -> str:
    """Renders a plain-text, ANSI-free milestone block for non-TTY or unsupported terminals."""
    glyphs = get_glyphs(use_unicode)
    pct = snapshot.clamped_queue_percent
    bar_width = 16
    filled = max(0, min(bar_width, round((pct / 100.0) * bar_width)))
    bar = glyphs.bar_fill * filled + glyphs.bar_empty * (bar_width - filled)

    divider = f"[LBS] {glyphs.rule_char * 60}"
    phase_suffix = (
        f" (phase: {snapshot.phase_name})"
        if snapshot.phase_name and snapshot.phase_name != "default"
        else ""
    )
    elapsed_str = format_hms(snapshot.total_elapsed_seconds)
    cmd_text = _sanitize_single_line(snapshot.command_text)

    lines = [
        "",
        divider,
        (
            f"[LBS] Queue Progress: [{bar}] {pct:.1f}% "
            f"(Job {snapshot.current_job_idx} of {snapshot.total_jobs} | "
            f"{snapshot.passed_jobs} passed, {snapshot.failed_jobs} failed, "
            f"{snapshot.remaining_jobs} remaining)"
        ),
        f"[LBS] Now starting: '{snapshot.target_name}'{phase_suffix} [{snapshot.status_label}]",
    ]
    if cmd_text:
        lines.append(f"[LBS] Command: {cmd_text}")
    lines.append(
        f"[LBS] Elapsed: {elapsed_str} | Active log: {snapshot.log_path}"
    )
    lines.append(divider)
    lines.append("")
    return "\n".join(lines)


class DashboardRenderer:
    """Renders DashboardSnapshot into exact-width styled lines using Rich."""

    def __init__(self) -> None:
        self._theme = build_rich_theme()

    def _build_monitor_panel(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        glyphs: GlyphSet,
        use_color: bool,
        compact_padding: bool = False,
    ) -> Panel:
        st_color = status_color(snapshot.status)
        left_title = Text(
            "LOCAL BUILDS SCHEDULER",
            style=_style(f"bold {CYAN}", use_color),
        )
        right_title = Text(
            f"{glyphs.dot} {snapshot.status_label}",
            style=_style(f"bold {st_color}", use_color),
        )
        title = _make_border_title(
            left=left_title,
            right=right_title,
            panel_width=width,
            border_char=glyphs.rule_char,
            border_color=CYAN,
            use_color=use_color,
        )

        # Horizontal padding inside panel: 2 cells each side in full, 1 cell in medium
        h_pad = 1 if compact_padding else 2
        inner_width = max(12, width - 2 - (h_pad * 2))
        col_width = max(8, (inner_width - 4) // 3)
        bar_width = max(8, min(20, col_width - 2))

        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(ratio=1, no_wrap=True)
        grid.add_column(ratio=1, no_wrap=True)
        grid.add_column(ratio=1, no_wrap=True)

        # Row 1: Column titles
        grid.add_row(
            Text("Queue progress", style=_style(GRAY, use_color)),
            Text("Build progress", style=_style(GRAY, use_color)),
            Text("Total elapsed", style=_style(GRAY, use_color)),
        )

        # Row 2: Prominent primary metrics
        queue_pct = snapshot.clamped_queue_percent
        queue_metric = Text(f"{queue_pct:.1f}%", style=_style(f"bold {CYAN}", use_color))

        bp = snapshot.build_progress
        if bp is not None:
            build_metric = Text(f"{bp.percent:.1f}%", style=_style(f"bold {GREEN}", use_color))
        else:
            build_metric = Text(glyphs.em_dash, style=_style(GRAY, use_color))

        elapsed_metric = Text(
            format_hms(snapshot.total_elapsed_seconds),
            style=_style(f"bold {YELLOW}", use_color),
        )
        grid.add_row(queue_metric, build_metric, elapsed_metric)

        # Row 3: Progress bars (spacer under elapsed)
        queue_bar = _make_bar(queue_pct, bar_width, CYAN, glyphs, use_color, available=True)
        if bp is not None:
            build_bar = _make_bar(bp.percent, bar_width, GREEN, glyphs, use_color, available=True)
        else:
            build_bar = _make_bar(0.0, bar_width, GREEN, glyphs, use_color, available=False)
        grid.add_row(queue_bar, build_bar, Text(""))

        # Row 4: Sublabels
        queue_sub = Text(
            f"Job {snapshot.current_job_idx} of {snapshot.total_jobs}",
            style=_style(TEXT_PRIMARY, use_color),
        )
        if bp is not None:
            build_sub = Text(bp.formatted_counts, style=_style(TEXT_PRIMARY, use_color))
        elif snapshot.phase_cmd_total > 1:
            build_sub = Text(
                f"Step {snapshot.cmd_idx} of {snapshot.phase_cmd_total}",
                style=_style(GRAY, use_color),
            )
        else:
            build_sub = Text("No build progress", style=_style(GRAY, use_color))

        active_dur = format_compact_duration(snapshot.active_elapsed_seconds)
        elapsed_sub = Text(f"Build: {active_dur}", style=_style(TEXT_PRIMARY, use_color))

        grid.add_row(queue_sub, build_sub, elapsed_sub)

        return Panel(
            grid,
            title=title,
            title_align="left",
            box=glyphs.box_style,
            border_style=_style(CYAN, use_color),
            padding=(0, h_pad),
        )

    def _build_system_resources_panel(
        self,
        snapshot: DashboardSnapshot,
        panel_width: int,
        glyphs: GlyphSet,
        use_color: bool,
        compact_padding: bool = False,
    ) -> Panel:
        overflow_mode: Literal["ellipsis", "crop"] = (
            "ellipsis" if glyphs.rule_char != "-" else "crop"
        )
        h_pad = 1 if compact_padding else 2
        inner_width = max(24, panel_width - 2 - (h_pad * 2))
        col_width = max(6, (inner_width - 6) // 4)
        bar_width = max(4, min(14, col_width - 1))

        resources = snapshot.system_resources

        cpu = resources.cpu
        memory = resources.memory
        disk_io = resources.disk_io
        disk_free = resources.disk_free

        cpu_value = (
            f"{cpu.value:.0f}%"
            if cpu.available
            else "N/A"
        )
        if memory.available:
            memory_value = (
                f"{format_bytes_iec(memory.used_bytes, decimals=0)} / "
                f"{format_bytes_iec(memory.total_bytes, decimals=0)}"
            )
        else:
            memory_value = "N/A"
        disk_io_value = (
            f"R: {format_bytes_rate_iec(disk_io.read_bytes_per_second)}"
            f"  W: {format_bytes_rate_iec(disk_io.write_bytes_per_second)}"
            if disk_io.available
            else "N/A"
        )
        if disk_free.available:
            disk_free_value = (
                f"{format_bytes_iec(disk_free.free_bytes, decimals=0)} / "
                f"{format_bytes_iec(disk_free.total_bytes, decimals=0)}"
            )
        else:
            disk_free_value = "N/A"

        grid = Table.grid(expand=True, padding=(0, 1))
        for _ in range(4):
            grid.add_column(ratio=1, no_wrap=True)

        grid.add_row(
            Text("CPU", style=_style(GRAY, use_color)),
            Text("RAM", style=_style(GRAY, use_color)),
            Text("DISK I/O", style=_style(GRAY, use_color)),
            Text("DISK FREE", style=_style(GRAY, use_color)),
        )
        grid.add_row(
            Text(
                cpu_value,
                style=_style(f"bold {GREEN}" if cpu.available else GRAY, use_color),
                overflow=overflow_mode,
                no_wrap=True,
            ),
            Text(
                memory_value,
                style=_style(f"bold {CYAN}" if memory.available else GRAY, use_color),
                overflow=overflow_mode,
                no_wrap=True,
            ),
            Text(
                disk_io_value,
                style=_style(f"bold {YELLOW}" if disk_io.available else GRAY, use_color),
                overflow=overflow_mode,
                no_wrap=True,
            ),
            Text(
                disk_free_value,
                style=_style(f"bold {GREEN}" if disk_free.available else GRAY, use_color),
                overflow=overflow_mode,
                no_wrap=True,
            ),
        )
        grid.add_row(
            _make_bar(
                cpu.value,
                bar_width,
                GREEN,
                glyphs,
                use_color,
                available=cpu.available,
            ),
            _make_bar(
                memory.used_percent,
                bar_width,
                CYAN,
                glyphs,
                use_color,
                available=memory.available,
            ),
            Text(""),
            _make_bar(
                disk_free.used_percent,
                bar_width,
                GREEN,
                glyphs,
                use_color,
                available=disk_free.available,
            ),
        )

        return Panel(
            grid,
            title=Text("SYSTEM RESOURCES", style=_style(GRAY, use_color)),
            title_align="left",
            box=glyphs.box_style,
            border_style=_style(DARK_GRAY, use_color),
            padding=(0, h_pad),
        )

    def _build_jobs_panel(
        self,
        snapshot: DashboardSnapshot,
        panel_width: int,
        glyphs: GlyphSet,
        use_color: bool,
        compact_padding: bool = False,
    ) -> Panel:
        overflow_mode: Literal["ellipsis", "crop"] = (
            "ellipsis" if glyphs.rule_char != "-" else "crop"
        )
        short_labels = panel_width < 34
        specs = [
            (
                "PASS" if short_labels else "PASSED",
                glyphs.passed,
                snapshot.passed_jobs,
                GREEN,
            ),
            (
                "FAIL" if short_labels else "FAILED",
                glyphs.failed,
                snapshot.failed_jobs,
                RED,
            ),
            (
                "LEFT" if short_labels else "REMAINING",
                glyphs.remaining,
                snapshot.remaining_jobs,
                YELLOW,
            ),
        ]

        grid = Table.grid(expand=True, padding=(0, 1))
        for _ in range(3):
            grid.add_column(ratio=1, no_wrap=True)

        label_row: list[Text] = []
        value_row: list[Text] = []
        for label, icon, count, color in specs:
            label_row.append(Text(label, style=_style(GRAY, use_color)))
            inline_items = _iter_inline_items(count)
            formatted_values: list[str] = []
            for item in inline_items:
                if item == icon or item.startswith(f"{icon} "):
                    formatted_values.append(item)
                else:
                    formatted_values.append(f"{icon} {item}")
            formatted_count = "  ".join(formatted_values) if formatted_values else f"{icon} 0"
            value_row.append(
                Text(
                    formatted_count.rstrip(),
                    style=_style(f"bold {color}", use_color),
                    overflow=overflow_mode,
                    no_wrap=True,
                )
            )
        grid.add_row(*label_row)
        grid.add_row(*value_row)
        grid.add_row(Text(""), Text(""), Text(""))

        h_pad = 1 if compact_padding else 2
        return Panel(
            grid,
            title=Text("JOBS", style=_style(GRAY, use_color)),
            title_align="left",
            box=glyphs.box_style,
            border_style=_style(DARK_GRAY, use_color),
            padding=(0, h_pad),
        )

    def _build_resources_and_jobs_row(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        glyphs: GlyphSet,
        use_color: bool,
        compact_padding: bool,
    ) -> Table:
        right_width = max(24, int(width * 0.28))
        right_width = min(right_width, max(24, width - 24))
        left_width = max(24, width - right_width - 1)

        resources_panel = self._build_system_resources_panel(
            snapshot=snapshot,
            panel_width=left_width,
            glyphs=glyphs,
            use_color=use_color,
            compact_padding=compact_padding,
        )
        jobs_panel = self._build_jobs_panel(
            snapshot=snapshot,
            panel_width=right_width,
            glyphs=glyphs,
            use_color=use_color,
            compact_padding=compact_padding,
        )

        row = Table.grid(expand=True, padding=(0, 0))
        row.add_column(width=left_width)
        row.add_column(width=1)
        row.add_column(width=right_width)
        row.add_row(resources_panel, "", jobs_panel)
        return row

    def _build_active_target_panel(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        glyphs: GlyphSet,
        use_color: bool,
        compact_padding: bool = False,
    ) -> Panel:
        phase_color = status_color(snapshot.status)
        left_title = Text("ACTIVE TARGET", style=_style(GRAY, use_color))
        right_title = Text(
            f"{glyphs.dot} {snapshot.phase_label}",
            style=_style(f"bold {phase_color}", use_color),
        )
        title = _make_border_title(
            left=left_title,
            right=right_title,
            panel_width=width,
            border_char=glyphs.rule_char,
            border_color=DARK_GRAY,
            use_color=use_color,
        )

        h_pad = 1 if compact_padding else 2
        target_name = snapshot.target_name or "-"
        cmd_clean = _sanitize_single_line(snapshot.command_text) or "-"
        log_clean = _sanitize_single_line(snapshot.log_path) or "-"

        target_line = Text(target_name, style=_style(f"bold {YELLOW}", use_color), overflow="fold")

        details = Table.grid(expand=True, padding=(0, 0))
        details.add_column(width=5, no_wrap=True)
        details.add_column(ratio=1)

        cmd_value = highlight_command(cmd_clean, use_color=use_color)
        cmd_value.overflow = "fold"

        log_value = Text(log_clean, style=_style(GRAY, use_color), overflow="fold")

        details.add_row(Text("CMD  ", style=_style(f"bold {GRAY}", use_color)), cmd_value)
        details.add_row(Text("LOG  ", style=_style(f"bold {GRAY}", use_color)), log_value)

        return Panel(
            Group(target_line, details),
            title=title,
            title_align="left",
            box=glyphs.box_style,
            border_style=_style(DARK_GRAY, use_color),
            padding=(0, h_pad),
        )

    def _build_full_or_medium(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        glyphs: GlyphSet,
        use_color: bool,
        compact_padding: bool,
    ) -> RenderableType:
        monitor = self._build_monitor_panel(
            snapshot=snapshot,
            width=width,
            glyphs=glyphs,
            use_color=use_color,
            compact_padding=compact_padding,
        )
        resources_jobs = self._build_resources_and_jobs_row(
            snapshot=snapshot,
            width=width,
            glyphs=glyphs,
            use_color=use_color,
            compact_padding=compact_padding,
        )
        active = self._build_active_target_panel(
            snapshot=snapshot,
            width=width,
            glyphs=glyphs,
            use_color=use_color,
            compact_padding=compact_padding,
        )
        sep = _make_output_separator(width=width, glyphs=glyphs, use_color=use_color)
        return Group(monitor, resources_jobs, active, sep)

    def _build_compact(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        glyphs: GlyphSet,
        use_color: bool,
    ) -> RenderableType:
        st_color = status_color(snapshot.status)
        left_title = Text(
            "LOCAL BUILDS SCHEDULER",
            style=_style(f"bold {CYAN}", use_color),
        )
        right_title = Text(
            f"{glyphs.dot} {snapshot.status_label}",
            style=_style(f"bold {st_color}", use_color),
        )
        title = _make_border_title(
            left=left_title,
            right=right_title,
            panel_width=width,
            border_char=glyphs.rule_char,
            border_color=CYAN,
            use_color=use_color,
        )

        # Row 1: Queue %, Build % (if available), Elapsed
        bar_w = 6 if width < 52 else 10
        queue_pct = snapshot.clamped_queue_percent
        metrics_line = Text(overflow="fold")
        metrics_line.append("Q ", style=_style(GRAY, use_color))
        metrics_line.append(f"{queue_pct:.1f}% ", style=_style(f"bold {CYAN}", use_color))
        metrics_line.append_text(_make_bar(queue_pct, bar_w, CYAN, glyphs, use_color))
        metrics_line.append(
            f" ({snapshot.current_job_idx}/{snapshot.total_jobs})",
            style=_style(GRAY, use_color),
        )

        bp = snapshot.build_progress
        if bp is not None:
            metrics_line.append("  B ", style=_style(GRAY, use_color))
            metrics_line.append(f"{bp.percent:.1f}% ", style=_style(f"bold {GREEN}", use_color))
            metrics_line.append(bp.formatted_counts, style=_style(GRAY, use_color))
        else:
            metrics_line.append(f"  B {glyphs.em_dash}", style=_style(GRAY, use_color))

        metrics_line.append("  ", style="")
        metrics_line.append(
            format_hms(snapshot.total_elapsed_seconds),
            style=_style(f"bold {YELLOW}", use_color),
        )
        metrics_line.append(
            f" ({format_compact_duration(snapshot.active_elapsed_seconds)})",
            style=_style(GRAY, use_color),
        )

        # Row 2: Inline counters + Target + Phase
        summary_line = Text(overflow="fold")
        summary_line.append(
            f"{glyphs.passed} {snapshot.passed_jobs}",
            style=_style(f"bold {GREEN}", use_color),
        )
        summary_line.append("  ")
        summary_line.append(
            f"{glyphs.failed} {snapshot.failed_jobs}",
            style=_style(f"bold {RED}", use_color),
        )
        summary_line.append("  ")
        summary_line.append(
            f"{glyphs.remaining} {snapshot.remaining_jobs}",
            style=_style(f"bold {YELLOW}", use_color),
        )
        summary_line.append("  |  ", style=_style(DARK_GRAY, use_color))
        summary_line.append(
            snapshot.target_name or "-",
            style=_style(f"bold {YELLOW}", use_color),
        )
        summary_line.append(
            f" [{snapshot.phase_label}]",
            style=_style(f"bold {st_color}", use_color),
        )

        # Row 3: Compact system resources summary (when monitoring has samples)
        resource_line = self._build_compact_resource_line(
            snapshot=snapshot,
            glyphs=glyphs,
            use_color=use_color,
        )

        # Row 4-5: Wrapped CMD & LOG
        details = Table.grid(expand=True, padding=(0, 0))
        details.add_column(width=4, no_wrap=True)
        details.add_column(ratio=1)
        cmd_clean = _sanitize_single_line(snapshot.command_text) or "-"
        log_clean = _sanitize_single_line(snapshot.log_path) or "-"
        cmd_val = highlight_command(cmd_clean, use_color=use_color)
        cmd_val.overflow = "fold"
        log_val = Text(log_clean, style=_style(GRAY, use_color), overflow="fold")
        details.add_row(Text("CMD ", style=_style(f"bold {GRAY}", use_color)), cmd_val)
        details.add_row(Text("LOG ", style=_style(f"bold {GRAY}", use_color)), log_val)

        render_items: list[RenderableType] = [metrics_line, summary_line]
        if resource_line is not None:
            render_items.append(resource_line)
        render_items.append(details)

        panel = Panel(
            Group(*render_items),
            title=title,
            title_align="left",
            box=glyphs.box_style,
            border_style=_style(CYAN, use_color),
            padding=(0, 1),
        )
        sep = _make_output_separator(width=width, glyphs=glyphs, use_color=use_color)
        return Group(panel, sep)

    def _build_minimal(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        glyphs: GlyphSet,
        use_color: bool,
    ) -> RenderableType:
        st_color = status_color(snapshot.status)
        queue_pct = snapshot.clamped_queue_percent

        overflow_mode: Literal["ellipsis", "crop"] = (
            "ellipsis" if glyphs.rule_char != "-" else "crop"
        )
        line1 = Text(no_wrap=True, overflow=overflow_mode)
        line1.append("LBS ", style=_style(f"bold {CYAN}", use_color))
        line1.append(
            f"Q:{queue_pct:.1f}% ({snapshot.current_job_idx}/{snapshot.total_jobs}) ",
            style=_style(CYAN, use_color),
        )
        if snapshot.build_progress is not None:
            line1.append(
                f"B:{snapshot.build_progress.percent:.1f}% ",
                style=_style(GREEN, use_color),
            )
        line1.append(
            f"{format_hms(snapshot.total_elapsed_seconds)} ",
            style=_style(YELLOW, use_color),
        )
        line1.append(
            f"{glyphs.dot} {snapshot.status_label}",
            style=_style(f"bold {st_color}", use_color),
        )
        minimal_suffix = self._build_minimal_resource_suffix(snapshot)
        if minimal_suffix:
            line1.append(
                f" {minimal_suffix}",
                style=_style(GRAY, use_color),
            )

        line2 = Text(no_wrap=True, overflow=overflow_mode)
        line2.append(
            f"{snapshot.target_name or '-'} ",
            style=_style(f"bold {YELLOW}", use_color),
        )
        line2.append(f"[{snapshot.phase_label}] ", style=_style(st_color, use_color))
        line2.append(f"{glyphs.passed}{snapshot.passed_jobs} ", style=_style(GREEN, use_color))
        line2.append(f"{glyphs.failed}{snapshot.failed_jobs} ", style=_style(RED, use_color))
        line2.append(f"{glyphs.remaining}{snapshot.remaining_jobs} ", style=_style(YELLOW, use_color))
        cmd_clean = _sanitize_single_line(snapshot.command_text)
        if cmd_clean:
            line2.append(cmd_clean, style=_style(GRAY, use_color))

        sep = _make_output_separator(width=width, glyphs=glyphs, use_color=use_color)
        return Group(line1, line2, sep)

    def _build_compact_resource_line(
        self,
        snapshot: DashboardSnapshot,
        glyphs: GlyphSet,
        use_color: bool,
    ) -> Text | None:
        resources = snapshot.system_resources
        if not (
            resources.cpu.available
            or resources.memory.available
            or resources.disk_io.available
            or resources.disk_free.available
        ):
            return None

        overflow_mode: Literal["ellipsis", "crop"] = (
            "ellipsis" if glyphs.rule_char != "-" else "crop"
        )
        line = Text(overflow=overflow_mode, no_wrap=True)

        cpu_value = f"{resources.cpu.value:.0f}%" if resources.cpu.available else "N/A"
        memory_value = (
            f"{resources.memory.used_percent:.0f}%"
            if resources.memory.available
            else "N/A"
        )
        io_value = (
            f"{format_bytes_rate_iec(resources.disk_io.read_bytes_per_second)}"
            f"/{format_bytes_rate_iec(resources.disk_io.write_bytes_per_second)}"
            if resources.disk_io.available
            else "N/A"
        )
        free_value = (
            format_bytes_iec(resources.disk_free.free_bytes, decimals=0)
            if resources.disk_free.available
            else "N/A"
        )

        line.append("RES ", style=_style(GRAY, use_color))
        line.append("CPU ", style=_style(GRAY, use_color))
        line.append(cpu_value, style=_style(f"bold {GREEN}", use_color))
        line.append("  RAM ", style=_style(GRAY, use_color))
        line.append(memory_value, style=_style(f"bold {CYAN}", use_color))
        line.append("  IO ", style=_style(GRAY, use_color))
        line.append(io_value, style=_style(f"bold {YELLOW}", use_color))
        line.append("  FREE ", style=_style(GRAY, use_color))
        line.append(free_value, style=_style(f"bold {GREEN}", use_color))
        return line

    def _build_minimal_resource_suffix(self, snapshot: DashboardSnapshot) -> str:
        resources = snapshot.system_resources
        if not (resources.cpu.available or resources.memory.available):
            return ""

        cpu = f"{resources.cpu.value:.0f}" if resources.cpu.available else "-"
        ram = f"{resources.memory.used_percent:.0f}" if resources.memory.available else "-"
        return f"R:{cpu}/{ram}"

    def _render_to_lines(
        self,
        renderable: RenderableType,
        width: int,
        use_ansi: bool,
        color_system: ColorSystem,
    ) -> list[str]:
        buf = io.StringIO()
        console = Console(
            file=buf,
            width=max(1, width),
            force_terminal=use_ansi,
            color_system=color_system if use_ansi else None,
            legacy_windows=False,
            no_color=not use_ansi,
            highlight=False,
            soft_wrap=False,
            theme=self._theme,
        )
        console.print(renderable, end="")
        return buf.getvalue().splitlines()

    def render_milestone(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        profile: RenderProfileProtocol | None = None,
        *,
        use_ansi: bool = True,
        color_system: ColorSystem = "truecolor",
        use_unicode: bool = True,
    ) -> str:
        """Renders a compact, colorized single-shot milestone panel for ANSI TTYs
        where DECSTBM split-screen is disabled (e.g. ConEmu/Cmder).
        """
        if profile is not None:
            use_ansi = profile.use_ansi
            color_system = profile.color_system
            use_unicode = profile.use_unicode

        safe_width = max(28, width)
        use_color = bool(use_ansi and color_system is not None)
        glyphs = get_glyphs(use_unicode)
        renderable = self._build_compact(snapshot, safe_width, glyphs, use_color)
        lines = self._render_to_lines(renderable, safe_width, use_ansi, color_system)
        return "\n" + "\n".join(lines) + "\n"

    def render(
        self,
        snapshot: DashboardSnapshot,
        width: int,
        height: int,
        profile: RenderProfileProtocol | None = None,
        *,
        use_ansi: bool = True,
        color_system: ColorSystem = "truecolor",
        use_unicode: bool = True,
    ) -> list[str]:
        """Renders the dashboard into a list of exact-width terminal rows,
        automatically adapting tier to available terminal width and height.
        """
        if profile is not None:
            use_ansi = profile.use_ansi
            color_system = profile.color_system
            use_unicode = profile.use_unicode

        safe_width = max(1, width)
        safe_height = max(1, height)
        use_color = bool(use_ansi and color_system is not None)
        glyphs = get_glyphs(use_unicode)

        tier = select_layout_tier(safe_width, safe_height)
        if tier == LayoutTier.PLAIN:
            max_plain_rows = max(1, safe_height - 1) if safe_height > 1 else 1
            minimal_lines = self._render_to_lines(
                self._build_minimal(snapshot, safe_width, glyphs, use_color),
                safe_width,
                use_ansi,
                color_system,
            )
            return minimal_lines[:max_plain_rows]

        # Ensure live compiler output always keeps at least 5 rows (or ~35%+ of terminal)
        max_rows = max(3, min(safe_height - 5, int(safe_height * 0.65)))

        candidates: list[LayoutTier]
        if tier == LayoutTier.FULL:
            candidates = [LayoutTier.FULL, LayoutTier.MEDIUM, LayoutTier.COMPACT, LayoutTier.MINIMAL]
        elif tier == LayoutTier.MEDIUM:
            candidates = [LayoutTier.MEDIUM, LayoutTier.COMPACT, LayoutTier.MINIMAL]
        elif tier == LayoutTier.COMPACT:
            candidates = [LayoutTier.COMPACT, LayoutTier.MINIMAL]
        else:
            candidates = [LayoutTier.MINIMAL]

        lines: list[str] = []
        for candidate in candidates:
            if candidate == LayoutTier.FULL:
                renderable = self._build_full_or_medium(
                    snapshot, safe_width, glyphs, use_color, compact_padding=False
                )
            elif candidate == LayoutTier.MEDIUM:
                renderable = self._build_full_or_medium(
                    snapshot, safe_width, glyphs, use_color, compact_padding=True
                )
            elif candidate == LayoutTier.COMPACT:
                renderable = self._build_compact(snapshot, safe_width, glyphs, use_color)
            else:
                renderable = self._build_minimal(snapshot, safe_width, glyphs, use_color)

            lines = self._render_to_lines(renderable, safe_width, use_ansi, color_system)
            if len(lines) <= max_rows or candidate == LayoutTier.MINIMAL:
                break

        if len(lines) > max_rows:
            sep_lines = self._render_to_lines(
                _make_output_separator(safe_width, glyphs, use_color),
                safe_width,
                use_ansi,
                color_system,
            )
            if max_rows >= 2 and sep_lines:
                lines = lines[: max_rows - 1] + [sep_lines[-1]]
            else:
                lines = lines[:max_rows]

        return lines
