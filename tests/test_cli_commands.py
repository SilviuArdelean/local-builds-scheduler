# Local Builds Scheduler
# SPDX-License-Identifier: Apache-2.0

"""
Integration tests for LBS CLI commands (validate, list).
"""

import subprocess
import sys
import pytest
import yaml



def test_cli_validate_success(tmp_path):
    """Running 'lbs validate' with a valid config should exit with code 0 and success message."""
    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    yaml_content = f"""
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "validate", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Configuration is valid" in result.stdout


def test_cli_validate_failure(tmp_path):
    """Running 'lbs validate' with an invalid config should exit with code 1 and print error to stderr."""
    config_file = tmp_path / "invalid.yaml"
    # CWD directory does not exist, which causes validation failure
    yaml_content = """
    jobs:
      - name: job-1
        cwd: "/does/not/exist/path/to/dir"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "validate", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Error:" in result.stderr


def test_cli_list_success(tmp_path):
    """Running 'lbs list' with a valid config should print job names to stdout and exit with code 0."""
    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    yaml_content = f"""
    jobs:
      - name: build-debug
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
      - name: build-release
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 2"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "list", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    # Output should contain job names, one per line
    lines = result.stdout.strip().splitlines()
    assert lines == ["build-debug", "build-release"]


def test_cli_list_failure(tmp_path):
    """Running 'lbs list' with an invalid config should exit with code 1 and print error to stderr."""
    config_file = tmp_path / "invalid.yaml"
    # Jobs list cannot be empty
    yaml_content = """
    jobs: []
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "list", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Error:" in result.stderr


def test_cli_run_success(tmp_path):
    """Running 'lbs run' with a valid config and succeeding command should exit with code 0."""
    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    py_cmd = f'"{sys.executable}" -c "print(\'cli-run-success\')"'

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-1",
                "cwd": str(workspace_dir),
                "commands": [py_cmd]
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "LBS Session Summary" in result.stdout
    assert "job-1                ->  SUCCESS" in result.stdout


def test_cli_run_failure(tmp_path):
    """Running 'lbs run' with a failing command should exit with code 1."""
    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    py_cmd = f'"{sys.executable}" -c "import sys; sys.exit(42)"'

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-1",
                "cwd": str(workspace_dir),
                "commands": [py_cmd]
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "LBS Session Summary" in result.stdout
    assert "job-1                ->  FAILED" in result.stdout



def test_cli_run_invalid_config(tmp_path):
    """Running 'lbs run' with an invalid config should exit with code 1 and print Error to stderr."""
    config_file = tmp_path / "invalid.yaml"
    yaml_content = """
    jobs: []
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "Error:" in result.stderr

