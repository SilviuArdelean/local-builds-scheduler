# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Integration tests for LBS CLI commands (validate, list).
"""

import subprocess
import sys
from unittest.mock import patch
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
        [sys.executable, "-m", "lbs", "validate",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Configuration is valid" in result.stdout


def test_cli_validate_failure(tmp_path):
    """Running 'lbs validate' with an invalid config should exit with code 2 and print error to stderr."""
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
        [sys.executable, "-m", "lbs", "validate",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
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
        [sys.executable, "-m", "lbs", "list",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    # Output should contain job names, one per line
    lines = result.stdout.strip().splitlines()
    assert lines == ["build-debug", "build-release"]


def test_cli_list_failure(tmp_path):
    """Running 'lbs list' with an invalid config should exit with code 2 and print error to stderr."""
    config_file = tmp_path / "invalid.yaml"
    # Jobs list cannot be empty
    yaml_content = """
    jobs: []
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "list",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
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
        "jobs": [{
            "name": "job-1",
            "cwd": str(workspace_dir),
            "commands": [py_cmd]
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file)],
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
        "jobs": [{
            "name": "job-1",
            "cwd": str(workspace_dir),
            "commands": [py_cmd]
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "LBS Session Summary" in result.stdout
    assert "job-1                ->  FAILED" in result.stdout


def test_cli_run_invalid_config(tmp_path):
    """Running 'lbs run' with an invalid config should exit with code 2 and print Error to stderr."""
    config_file = tmp_path / "invalid.yaml"
    yaml_content = """
    jobs: []
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Error:" in result.stderr


def test_cli_validate_with_notifications(tmp_path):
    """Running 'lbs validate' with -n and a valid notifications config should exit with code 0."""
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

    notif_file = tmp_path / "notif.yaml"
    notif_file.write_text("""
    desktop: true
    """, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "lbs",
            "validate",
            str(config_file),
            "-n",
            str(notif_file),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Configuration is valid" in result.stdout


def test_cli_run_notifications_opt_in(tmp_path):
    """Running 'lbs run' with --notifications should execute jobs normally and exit with code 0."""
    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    yaml_content = f"""
    settings:
      log_dir: "{log_dir.as_posix()}"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    # Verify that run works with --notifications
    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--notifications"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "LBS Session Summary" in result.stdout

    # Verify that run also works without the flag (notifications are disabled by default)
    result_default = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result_default.returncode == 0
    assert "LBS Session Summary" in result_default.stdout


@patch("lbs.cli.subprocess.run")
def test_cli_run_shutdown(mock_sub_run, tmp_path):
    """Running 'lbs run' with --shutdown should execute jobs normally and call system shutdown."""
    from lbs.cli import cmd_run
    import argparse
    from unittest.mock import patch as local_patch

    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    yaml_content = f"""
    settings:
      log_dir: "{log_dir.as_posix()}"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    args = argparse.Namespace(
        config=str(config_file),
        verbose=False,
        job=None,
        dry_run=False,
        resume=None,
        notifications_config=None,
        notifications=False,
        shutdown=True,
    )

    with local_patch("sys.exit") as mock_exit:
        cmd_run(args)
        assert mock_exit.call_count == 1
        assert mock_exit.call_args[0][0] == 0

    # Verify that subprocess.run was called to trigger shutdown
    assert mock_sub_run.call_count == 1
    call_args = mock_sub_run.call_args[0][0]
    assert call_args[0] == "shutdown"
    # Ensure it passed shutdown arguments appropriate for the platform
    import sys
    if sys.platform == "win32":
        assert "/s" in call_args
        assert "/t" in call_args
    else:
        assert "-h" in call_args


@patch("lbs.cli.subprocess.run")
def test_cli_run_shutdown_failure(mock_sub_run, tmp_path, capsys):
    """Running 'lbs run' with --shutdown should handle shutdown errors gracefully without crashing."""
    from lbs.cli import cmd_run
    import argparse
    from unittest.mock import patch as local_patch

    mock_sub_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["shutdown"], stderr="Permission denied")

    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    yaml_content = f"""
    settings:
      log_dir: "{log_dir.as_posix()}"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    args = argparse.Namespace(
        config=str(config_file),
        verbose=False,
        job=None,
        dry_run=False,
        resume=None,
        notifications_config=None,
        notifications=False,
        shutdown=True,
    )

    with local_patch("sys.exit") as mock_exit:
        cmd_run(args)
        assert mock_exit.call_count == 1
        assert mock_exit.call_args[0][0] == 0

    captured = capsys.readouterr()
    # Check that error was printed to stderr
    assert "Failed to initiate system shutdown (exit code 1): Permission denied" in captured.err
    # Verify that the warning message about scheduled shutdown was NOT printed
    assert "System shutdown scheduled" not in captured.out
