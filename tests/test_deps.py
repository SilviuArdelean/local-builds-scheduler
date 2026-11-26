# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for lbs.utils.deps (generic runtime dependency detection).
"""

from __future__ import annotations

import importlib.metadata
from types import SimpleNamespace

import pytest

from lbs.utils.deps import (
    GENERIC_SOFT_IMPACT,
    INSTALL_HINT,
    DependencyIssue,
    find_missing_dependencies,
    format_dependency_warning,
    format_missing_required_error,
    is_distribution_installed,
    load_declared_dependencies,
    normalize_dist_name,
    parse_requirement_name,
    resolve_ignored_dependencies,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("PyYAML", "pyyaml"),
        ("my_pkg.name", "my-pkg-name"),
        ("foo--bar__baz", "foo-bar-baz"),
        ("  psutil  ", "psutil"),
    ],
)
def test_normalize_dist_name(raw: str, expected: str) -> None:
    assert normalize_dist_name(raw) == expected


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("psutil", "psutil"),
        ("psutil>=5.9", "psutil"),
        ("PyYAML>=6.0,<7.0", "PyYAML"),
        ("pkg[extra,dev]>=1.2.3", "pkg"),
        ('rich>=13.7; sys_platform == "win32"', "rich"),
        ("  foo.bar_baz ~= 2.0  ", "foo.bar_baz"),
        ("", None),
        ("   ", None),
        ("# comment", None),
    ],
)
def test_parse_requirement_name(spec: str, expected: str | None) -> None:
    assert parse_requirement_name(spec) == expected


def test_load_declared_dependencies_reads_pyproject_and_ignores_optional(
    tmp_path,
) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "lbs"
dependencies = [
    "pyyaml>=6.0",
    "rich>=13.7",
    "psutil>=5.9",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.1.0",
]
""".strip(),
        encoding="utf-8",
    )

    deps = load_declared_dependencies(pyproject_path=pyproject)
    assert deps == ["pyyaml", "rich", "psutil"]


def test_load_declared_dependencies_falls_back_to_metadata_when_no_pyproject(
    tmp_path,
) -> None:
    missing_pyproject = tmp_path / "pyproject.toml"

    def fake_requires(dist_name: str) -> list[str]:
        assert dist_name == "lbs"
        return [
            "pyyaml>=6.0",
            "rich>=13.7",
            "psutil>=5.9",
            'pytest>=8.0; extra == "dev"',
            'ruff>=0.1.0; extra == "dev"',
        ]

    deps = load_declared_dependencies(
        pyproject_path=missing_pyproject,
        requires_fn=fake_requires,
    )
    assert deps == ["pyyaml", "rich", "psutil"]


def test_load_declared_dependencies_returns_empty_when_metadata_missing(
    tmp_path,
) -> None:
    missing_pyproject = tmp_path / "pyproject.toml"

    def fake_requires(dist_name: str) -> list[str]:
        raise importlib.metadata.PackageNotFoundError(dist_name)

    deps = load_declared_dependencies(
        pyproject_path=missing_pyproject,
        requires_fn=fake_requires,
    )
    assert deps == []


def test_is_distribution_installed() -> None:
    def fake_dist(name: str) -> object:
        if name == "rich":
            return object()
        raise importlib.metadata.PackageNotFoundError(name)

    assert is_distribution_installed("rich", distribution_fn=fake_dist) is True
    assert is_distribution_installed("psutil", distribution_fn=fake_dist) is False


def test_find_missing_dependencies_known_and_generic_impacts(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "lbs"
dependencies = [
    "pyyaml>=6.0",
    "rich>=13.7",
    "psutil>=5.9",
    "brand-new-lib>=1.0",
]
""".strip(),
        encoding="utf-8",
    )

    installed = {"pyyaml", "rich"}
    issues = find_missing_dependencies(
        pyproject_path=pyproject,
        is_installed_fn=lambda name: normalize_dist_name(name) in installed,
    )

    assert issues == [
        DependencyIssue(
            package="psutil",
            normalized="psutil",
            severity="warning",
            impact="CPU, RAM, and Disk I/O metrics will show as N/A",
        ),
        DependencyIssue(
            package="brand-new-lib",
            normalized="brand-new-lib",
            severity="warning",
            impact=GENERIC_SOFT_IMPACT,
        ),
    ]


def test_find_missing_dependencies_respects_ignored(tmp_path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[project]
name = "lbs"
dependencies = [
    "pyyaml>=6.0",
    "psutil>=5.9",
]
""".strip(),
        encoding="utf-8",
    )

    issues = find_missing_dependencies(
        pyproject_path=pyproject,
        ignored={"PSUTIL"},
        is_installed_fn=lambda name: normalize_dist_name(name) == "pyyaml",
    )
    assert issues == []


def test_format_dependency_warning() -> None:
    issue = DependencyIssue(
        package="psutil",
        normalized="psutil",
        severity="warning",
        impact="CPU, RAM, and Disk I/O metrics will show as N/A",
    )
    msg = format_dependency_warning(issue)
    assert msg == (
        "[WARNING] Missing dependency 'psutil': "
        "CPU, RAM, and Disk I/O metrics will show as N/A. "
        f"{INSTALL_HINT}"
    )


@pytest.mark.parametrize(
    ("missing_name", "expected_pkg"),
    [
        ("yaml", "pyyaml"),
        ("rich.console", "rich"),
        ("rich", "rich"),
        ("some_pkg", "some_pkg"),
    ],
)
def test_format_missing_required_error(missing_name: str, expected_pkg: str) -> None:
    msg = format_missing_required_error(missing_name)
    assert msg == (
        f"Error: Missing required dependency '{expected_pkg}'. {INSTALL_HINT}"
    )


def test_resolve_ignored_dependencies() -> None:
    cfg_disabled = SimpleNamespace(
        settings=SimpleNamespace(system_resources=SimpleNamespace(enabled=False))
    )
    cfg_enabled = SimpleNamespace(
        settings=SimpleNamespace(system_resources=SimpleNamespace(enabled=True))
    )

    assert resolve_ignored_dependencies(cfg_disabled) == {"psutil"}
    assert resolve_ignored_dependencies(cfg_enabled) == set()
    assert resolve_ignored_dependencies(None) == set()
