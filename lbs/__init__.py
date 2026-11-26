# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs – Local Builds Scheduler.

A sequential build job runner for local development workflows.
"""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "1.0.0"

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "run_scheduler": ("lbs.runner", "run_scheduler"),
    "Scheduler": ("lbs.runner", "Scheduler"),
    "clean_session_state": ("lbs.runner", "clean_session_state"),
    "format_session_status": ("lbs.runner", "format_session_status"),
    "JobExecutor": ("lbs.utils.executor", "JobExecutor"),
    "CommandResult": ("lbs.utils.executor", "CommandResult"),
}

__all__ = list(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    value = getattr(importlib.import_module(module_name), attr_name)
    globals()[name] = value
    return value
