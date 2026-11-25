# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.ui.state – Immutable state snapshots and formatting helpers for the dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math


class ExecutionStatus(str, Enum):
    """High-level execution state displayed in the dashboard status indicator."""

    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    COMPLETED = "COMPLETED"


def _clamp_non_negative_int(seconds: float) -> int:
    """Safely converts a duration in seconds to a non-negative integer."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        return 0
    if not math.isfinite(seconds) or seconds <= 0:
        return 0
    return int(seconds)


def format_hms(seconds: float) -> str:
    """Formats a duration in seconds as HH:MM:SS (e.g. '00:43:16')."""
    total = _clamp_non_negative_int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_compact_duration(seconds: float) -> str:
    """Formats a duration in compact human-readable form (e.g. '25m 43s')."""
    total = _clamp_non_negative_int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes > 0:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


@dataclass(frozen=True)
class BuildProgress:
    """Active compiler/build action progress parsed from live build output."""

    completed: int
    total: int
    source: str = "ninja"

    @property
    def percent(self) -> float:
        """Completion percentage clamped to [0.0, 100.0]."""
        if self.total <= 0:
            return 0.0
        raw = (self.completed / self.total) * 100.0
        return max(0.0, min(100.0, raw))

    @property
    def formatted_counts(self) -> str:
        """Comma-formatted action counts (e.g. '43,345 / 63,295')."""
        return f"{self.completed:,} / {self.total:,}"


@dataclass(frozen=True)
class DashboardSnapshot:
    """Immutable point-in-time snapshot of all metrics rendered by the dashboard."""

    queue_percent: float
    current_job_idx: int
    total_jobs: int
    completed_commands: int = 0
    total_commands: int = 0
    build_progress: BuildProgress | None = None
    total_elapsed_seconds: float = 0.0
    active_elapsed_seconds: float = 0.0
    passed_jobs: int = 0
    failed_jobs: int = 0
    remaining_jobs: int = 0
    target_name: str = ""
    phase_name: str = "default"
    command_text: str = ""
    log_path: str = ""
    cmd_idx: int = 0
    phase_cmd_total: int = 0
    status: ExecutionStatus = ExecutionStatus.RUNNING
    retry_attempt: int = 1
    max_retries: int = 0

    @property
    def clamped_queue_percent(self) -> float:
        """Queue completion percentage safely clamped to [0.0, 100.0]."""
        if not math.isfinite(self.queue_percent):
            return 0.0
        return max(0.0, min(100.0, float(self.queue_percent)))

    @property
    def phase_label(self) -> str:
        """Uppercase phase badge label, defaulting to 'RUN' for unnamed phases."""
        cleaned = (self.phase_name or "").strip()
        if not cleaned or cleaned.lower() == "default":
            return "RUN"
        return cleaned.upper()

    @property
    def status_label(self) -> str:
        """Human-readable status indicator text, including retry counter when active."""
        if self.status == ExecutionStatus.RETRYING and self.max_retries > 0:
            retry_num = max(1, self.retry_attempt - 1)
            return f"RETRYING ({retry_num}/{self.max_retries})"
        return self.status.value
