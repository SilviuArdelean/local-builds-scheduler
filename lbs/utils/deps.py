# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.utils.deps – Stdlib-only runtime dependency discovery and diagnostics.
"""

from __future__ import annotations

import importlib.metadata
import re
import tomllib
from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

INSTALL_HINT = "Run 'python -m pip install -e .' to install missing dependencies."
GENERIC_SOFT_IMPACT = "some features may be unavailable"
MANDATORY_IMPACT = "required for LBS to run"

_KNOWN_SOFT_IMPACTS: dict[str, str] = {
    "psutil": "CPU, RAM, and Disk I/O metrics will show as N/A",
}

_IMPORT_TO_DIST_MAP: dict[str, str] = {
    "yaml": "pyyaml",
}

_MANDATORY_DISTS: frozenset[str] = frozenset({"pyyaml", "rich"})

_PEP503_RE = re.compile(r"[-_.]+")
_REQ_NAME_RE = re.compile(
    r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
)
_EXTRA_MARKER_RE = re.compile(r";.*\bextra\s*==", re.IGNORECASE)


@dataclass(frozen=True)
class DependencyIssue:
    """Represents a missing runtime dependency and its user-facing impact."""

    package: str
    normalized: str
    severity: Literal["error", "warning"]
    impact: str


def normalize_dist_name(name: str) -> str:
    """Normalizes a Python distribution name according to PEP 503."""
    return _PEP503_RE.sub("-", name.strip()).lower()


def parse_requirement_name(spec: str) -> str | None:
    """Extracts the distribution name from a PEP 508 requirement string."""
    if not isinstance(spec, str):
        return None
    stripped = spec.strip()
    if not stripped or stripped.startswith("#"):
        return None
    match = _REQ_NAME_RE.match(stripped)
    if not match:
        return None
    return match.group(1)


def default_pyproject_path() -> Path:
    """Returns the repository pyproject.toml path relative to this module."""
    return Path(__file__).resolve().parents[2] / "pyproject.toml"


def _dedupe_requirement_names(specs: Collection[object]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        if not isinstance(spec, str):
            continue
        name = parse_requirement_name(spec)
        if not name:
            continue
        norm = normalize_dist_name(name)
        if norm not in seen:
            seen.add(norm)
            names.append(name)
    return names


def load_declared_dependencies(
    pyproject_path: Path | None = None,
    dist_name: str = "lbs",
    requires_fn: Callable[[str], list[str] | None] | None = None,
) -> list[str]:
    """Loads declared runtime dependencies from pyproject.toml or package metadata.

    Prefers pyproject.toml when present so editable installs immediately detect
    newly added dependencies after a git pull, before pip install -e . is re-run.
    Falls back to importlib.metadata.requires(dist_name) for non-editable installs.
    """
    target_path = (
        pyproject_path if pyproject_path is not None else default_pyproject_path()
    )
    if target_path.is_file():
        try:
            with target_path.open("rb") as f:
                data = tomllib.load(f)
            project = data.get("project")
            if isinstance(project, dict):
                deps = project.get("dependencies")
                if isinstance(deps, list):
                    return _dedupe_requirement_names(deps)
            return []
        except (OSError, tomllib.TOMLDecodeError):
            pass

    resolver = requires_fn or importlib.metadata.requires
    try:
        raw_reqs = resolver(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return []
    if not raw_reqs:
        return []

    runtime_specs = [
        spec
        for spec in raw_reqs
        if isinstance(spec, str) and not _EXTRA_MARKER_RE.search(spec)
    ]
    return _dedupe_requirement_names(runtime_specs)


def is_distribution_installed(
    dist_name: str,
    distribution_fn: Callable[[str], object] | None = None,
) -> bool:
    """Returns True if the given Python distribution is installed."""
    lookup = distribution_fn or importlib.metadata.distribution
    try:
        lookup(dist_name)
        return True
    except importlib.metadata.PackageNotFoundError:
        return False


def find_missing_dependencies(
    pyproject_path: Path | None = None,
    dist_name: str = "lbs",
    ignored: Collection[str] = (),
    *,
    requires_fn: Callable[[str], list[str] | None] | None = None,
    is_installed_fn: Callable[[str], bool] | None = None,
) -> list[DependencyIssue]:
    """Checks declared runtime dependencies and returns any that are missing."""
    ignored_normalized = {normalize_dist_name(name) for name in ignored if name}
    installed_check = is_installed_fn or is_distribution_installed
    declared = load_declared_dependencies(
        pyproject_path=pyproject_path,
        dist_name=dist_name,
        requires_fn=requires_fn,
    )

    issues: list[DependencyIssue] = []
    for pkg in declared:
        norm = normalize_dist_name(pkg)
        if norm in ignored_normalized:
            continue
        if not installed_check(pkg):
            if norm in _MANDATORY_DISTS:
                severity: Literal["error", "warning"] = "error"
                impact = MANDATORY_IMPACT
            else:
                severity = "warning"
                impact = _KNOWN_SOFT_IMPACTS.get(norm, GENERIC_SOFT_IMPACT)
            issues.append(
                DependencyIssue(
                    package=pkg,
                    normalized=norm,
                    severity=severity,
                    impact=impact,
                )
            )
    return issues


def format_dependency_warning(issue: DependencyIssue) -> str:
    """Formats a user-facing warning message for a missing soft dependency."""
    return (
        f"[WARNING] Missing dependency '{issue.package}': "
        f"{issue.impact}. {INSTALL_HINT}"
    )


def format_missing_required_error(module_or_package: str) -> str:
    """Formats a user-facing error message for a missing mandatory dependency."""
    root_name = module_or_package.strip().split(".", 1)[0]
    dist_name = _IMPORT_TO_DIST_MAP.get(root_name.lower(), root_name)
    return f"Error: Missing required dependency '{dist_name}'. {INSTALL_HINT}"


def format_dependency_issue(issue: DependencyIssue) -> str:
    """Formats a DependencyIssue according to its severity."""
    if issue.severity == "error":
        return format_missing_required_error(issue.package)
    return format_dependency_warning(issue)


def format_startup_dependency_report(
    trigger_module: str,
    pyproject_path: Path | None = None,
    dist_name: str = "lbs",
    *,
    requires_fn: Callable[[str], list[str] | None] | None = None,
    is_installed_fn: Callable[[str], bool] | None = None,
) -> list[str]:
    """Formats fatal errors and any additional soft-dependency warnings on startup.

    Always reports the missing module that triggered startup failure as a fatal
    error, plus any other error-severity dependencies as errors and any
    warning-severity dependencies as warnings so the user sees the full picture.
    """
    root_name = trigger_module.strip().split(".", 1)[0]
    trigger_pkg = _IMPORT_TO_DIST_MAP.get(root_name.lower(), root_name)
    trigger_norm = normalize_dist_name(trigger_pkg)

    issues = find_missing_dependencies(
        pyproject_path=pyproject_path,
        dist_name=dist_name,
        requires_fn=requires_fn,
        is_installed_fn=is_installed_fn,
    )

    error_lines: list[str] = []
    warning_lines: list[str] = []
    seen_errors: set[str] = set()

    for issue in issues:
        if issue.normalized == trigger_norm or issue.severity == "error":
            if issue.normalized not in seen_errors:
                seen_errors.add(issue.normalized)
                error_lines.append(format_missing_required_error(issue.package))
        else:
            warning_lines.append(format_dependency_warning(issue))

    if trigger_norm not in seen_errors:
        error_lines.insert(0, format_missing_required_error(trigger_pkg))

    return error_lines + warning_lines


def resolve_ignored_dependencies(config: object | None) -> set[str]:
    """Returns normalized dependency names that should be skipped for this config."""
    settings = getattr(config, "settings", None)
    system_resources = getattr(settings, "system_resources", None)
    if (
        system_resources is not None
        and getattr(system_resources, "enabled", True) is False
    ):
        return {"psutil"}
    return set()
