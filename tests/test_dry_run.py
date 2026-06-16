# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for the dry-run command validation mode.
"""

import sys
import subprocess
import yaml


def test_dry_run_output_structure(tmp_path):
    """Verify that --dry-run prints a complete plan and does not create directories/files."""
    config_file = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-A",
                "cwd": str(workspace_dir),
                "env": {
                    "BUILD_TYPE": "debug"
                },
                "commands": ["echo A1", "echo A2"]
            },
            {
                "name": "job-B",
                "cwd": str(workspace_dir),
                "commands": ["echo B1"]
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--dry-run"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Dry-Run Execution Plan" in result.stdout
    assert f"Log Directory: {log_dir}" in result.stdout
    
    # Assert Job A details
    assert "Job: job-A" in result.stdout
    assert f"  CWD: {workspace_dir}" in result.stdout
    assert "  Environment: BUILD_TYPE=debug" in result.stdout
    assert "    - echo A1" in result.stdout
    assert "    - echo A2" in result.stdout

    # Assert Job B details
    assert "Job: job-B" in result.stdout
    assert "  Environment: None" in result.stdout
    assert "    - echo B1" in result.stdout

    # Assert no side effects on the filesystem
    assert not log_dir.exists()
    assert not (log_dir / "lbs.lock").exists()


def test_dry_run_with_filtering(tmp_path):
    """Verify that passing job filters alongside --dry-run restricts the printed execution plan."""
    config_file = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-A",
                "cwd": str(workspace_dir),
                "commands": ["echo A1"]
            },
            {
                "name": "job-B",
                "cwd": str(workspace_dir),
                "commands": ["echo B1"]
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--job", "job-B", "--dry-run"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Dry-Run Execution Plan" in result.stdout
    assert "Job: job-B" in result.stdout
    assert "Job: job-A" not in result.stdout


def test_dry_run_invalid_filter(tmp_path):
    """Verify that invalid filters are still checked and fail with code 2 during dry-run."""
    config_file = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-A",
                "cwd": str(workspace_dir),
                "commands": ["echo A1"]
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--job", "missing-job", "--dry-run"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Error: Job filter contains invalid job names: missing-job" in result.stderr


def test_dry_run_with_retries(tmp_path):
    """Verify that --dry-run prints job retries details if configured."""
    config_file = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-A",
                "cwd": str(workspace_dir),
                "commands": ["echo A1"],
                "retries": 3,
                "retry_delay_seconds": 12
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--dry-run"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Dry-Run Execution Plan" in result.stdout
    assert "Job: job-A" in result.stdout
    assert "  Retries: 3 (delay: 12s)" in result.stdout


def test_dry_run_with_timeout(tmp_path):
    """Verify that --dry-run prints job command timeout details if configured."""
    config_file = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-A",
                "cwd": str(workspace_dir),
                "commands": ["echo A1"],
                "command_timeout_minutes": 15.5
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--dry-run"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Dry-Run Execution Plan" in result.stdout
    assert "Job: job-A" in result.stdout
    assert "  Timeout: 15.5m" in result.stdout
