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
        quiet=False,
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
        quiet=False,
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


@patch("lbs.cli.subprocess.run")
def test_cli_run_shutdown_skipped_when_job_fails(mock_sub_run, tmp_path,
                                                 capsys):
    """--shutdown must not power off the machine when a job fails, so the
    failure stays diagnosable."""
    from lbs.cli import cmd_run
    import argparse
    from unittest.mock import patch as local_patch

    config_file = tmp_path / "failing.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    yaml_content = f"""
    settings:
      log_dir: "{log_dir.as_posix()}"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["exit 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    args = argparse.Namespace(
        config=str(config_file),
        quiet=False,
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
        assert mock_exit.call_args[0][0] == 1

    assert mock_sub_run.call_count == 0
    captured = capsys.readouterr()
    assert "skipping the requested system shutdown" in captured.err


@patch("lbs.cli.subprocess.run")
def test_cli_run_shutdown_skipped_on_dry_run(mock_sub_run, tmp_path, capsys):
    """--dry-run runs no jobs, so --shutdown must not power off the machine."""
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
        quiet=False,
        job=None,
        dry_run=True,
        resume=None,
        notifications_config=None,
        notifications=False,
        shutdown=True,
    )

    with local_patch("sys.exit") as mock_exit:
        cmd_run(args)
        assert mock_exit.call_count == 1
        assert mock_exit.call_args[0][0] == 0

    assert mock_sub_run.call_count == 0
    captured = capsys.readouterr()
    assert "Dry run: skipping the requested system shutdown." in captured.out


@patch("lbs.cli.subprocess.run")
def test_cli_run_shutdown_skipped_when_jobs_remain_unexecuted(
        mock_sub_run, tmp_path, capsys):
    """Ticket 4: a filtered run that succeeds must not power off while other
    enabled jobs are still unexecuted."""
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
      - name: build-a
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo a"]
      - name: build-b
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo b"]
      - name: build-c
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo c"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    args = argparse.Namespace(
        config=str(config_file),
        quiet=False,
        job=["build-b"],
        dry_run=False,
        resume=None,
        notifications_config=None,
        notifications=False,
        shutdown=True,
    )

    with local_patch("sys.exit") as mock_exit:
        cmd_run(args)
        assert mock_exit.call_args[0][0] == 0

    assert mock_sub_run.call_count == 0
    captured = capsys.readouterr()
    assert ("System shutdown cancelled: 2 jobs in the configuration "
            "remain unexecuted or skipped.") in captured.err
    assert "run without job filters" in captured.err


def test_cli_run_mode_sequential(tmp_path):
    """Running 'lbs run' with --mode sequential should execute jobs in sequential mode."""
    config_file = tmp_path / "valid.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    py_cmd = f'"{sys.executable}" -c "import sys; print(sys.argv[1])"'

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [
            {
                "name": "job-1",
                "cwd": str(workspace_dir),
                "phases": {
                    "sync": [f"{py_cmd} j1-sync"],
                    "build": [f"{py_cmd} j1-build"],
                }
            },
            {
                "name": "job-2",
                "cwd": str(workspace_dir),
                "phases": {
                    "sync": [f"{py_cmd} j2-sync"],
                    "build": [f"{py_cmd} j2-build"],
                }
            }
        ]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--mode", "sequential"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "job-1                ->  SUCCESS" in result.stdout
    assert "job-2                ->  SUCCESS" in result.stdout


def test_cli_argparser_quiet_flags():
    """Verify that -q and --quiet are parsed, and --verbose is rejected."""
    from lbs.cli import build_parser

    parser = build_parser()
    args_short = parser.parse_args(["run", "config.yaml", "-q"])
    assert args_short.quiet is True

    args_long = parser.parse_args(["run", "config.yaml", "--quiet"])
    assert args_long.quiet is True

    args_default = parser.parse_args(["run", "config.yaml"])
    assert args_default.quiet is False

    # --verbose should no longer be accepted
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "config.yaml", "--verbose"])

    with pytest.raises(SystemExit):
        parser.parse_args(["run", "config.yaml", "-v"])


def test_cli_run_default_streaming(tmp_path):
    """Running 'lbs run' without -q should default to verbose=True (live streaming enabled)."""
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
        quiet=False,
        job=None,
        dry_run=False,
        resume=None,
        notifications_config=None,
        notifications=False,
        shutdown=False,
    )

    with local_patch("lbs.cli.Scheduler.run") as mock_sched_run, local_patch("sys.exit"):
        mock_sched_run.return_value = True
        cmd_run(args)
        assert mock_sched_run.call_count == 1
        config_passed = mock_sched_run.call_args[0][0]
        assert config_passed.settings.verbose is True
        assert config_passed.settings.quiet is False


def test_cli_run_quiet_flag(tmp_path):
    """Running 'lbs run' with quiet=True should set verbose=False and quiet=True."""
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
        quiet=True,
        job=None,
        dry_run=False,
        resume=None,
        notifications_config=None,
        notifications=False,
        shutdown=False,
    )

    with local_patch("lbs.cli.Scheduler.run") as mock_sched_run, local_patch("sys.exit"):
        mock_sched_run.return_value = True
        cmd_run(args)
        assert mock_sched_run.call_count == 1
        config_passed = mock_sched_run.call_args[0][0]
        assert config_passed.settings.verbose is False
        assert config_passed.settings.quiet is True


def test_cli_clean_existing_state(tmp_path):
    """Running 'lbs clean <config>' removes saved session state and temporary files."""
    config_file = tmp_path / "build.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    yaml_content = f"""
    settings:
      log_dir: "{log_dir.as_posix()}"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")

    status_file = log_dir / "lbs_status_build.json"
    status_file.write_text('{"jobs": {}}', encoding="utf-8")
    tmp_file = log_dir / "lbs_status_build_123.tmp"
    tmp_file.write_text("temp", encoding="utf-8")
    reconcile_tmp = log_dir / "lbs_status_build_reconcile_456.tmp"
    reconcile_tmp.write_text("reconcile", encoding="utf-8")

    # Another profile's files in the same log directory
    other_status = log_dir / "lbs_status_other.json"
    other_status.write_text('{"jobs": {}}', encoding="utf-8")
    other_tmp = log_dir / "lbs_status_other_789.tmp"
    other_tmp.write_text("other temp", encoding="utf-8")
    other_reconcile = log_dir / "lbs_status_other_reconcile_012.tmp"
    other_reconcile.write_text("other reconcile", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "clean", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert f"Cleared saved session state for {config_file}." in result.stdout
    # Target profile files are deleted
    assert not status_file.exists()
    assert not tmp_file.exists()
    assert not reconcile_tmp.exists()
    # Other profile files remain untouched
    assert other_status.exists()
    assert other_tmp.exists()
    assert other_reconcile.exists()


def test_cli_clean_nonexistent_state(tmp_path):
    """Running 'lbs clean <config>' when no state exists prints a clean message."""
    config_file = tmp_path / "clean_empty.yaml"
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

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "clean", str(config_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert f"No saved session state found for {config_file}. Nothing to clean." in result.stdout


def test_cli_clean_invalid_config(tmp_path):
    """Running 'lbs clean <config>' on invalid config exits with code 2."""
    missing_file = tmp_path / "nonexistent.yaml"
    result = subprocess.run(
        [sys.executable, "-m", "lbs", "clean", str(missing_file)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Error:" in result.stderr


def test_cli_clean_locked(tmp_path):
    """Running 'lbs clean' while another instance holds the lock exits with code 2."""
    from lbs.utils.lock import FileLock

    config_file = tmp_path / "locked.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    yaml_content = f"""
    settings:
      log_dir: "{log_dir.as_posix()}"
    jobs:
      - name: job-1
        cwd: "{workspace_dir.as_posix()}"
        commands: ["echo 1"]
    """
    config_file.write_text(yaml_content, encoding="utf-8")
    status_file = log_dir / "lbs_status_locked.json"
    status_file.write_text('{"jobs": {}}', encoding="utf-8")

    lock_file = log_dir / "lbs.lock"
    with FileLock(lock_file):
        result = subprocess.run(
            [sys.executable, "-m", "lbs", "clean", str(config_file)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 2
        assert "Another Local Builds Scheduler instance is already running" in result.stderr
    assert status_file.exists()


def test_cli_run_fresh_flag(tmp_path):
    """Running 'lbs run --fresh' discards previous state and starts all jobs from beginning."""
    config_file = tmp_path / "fresh_test.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    marker_file = tmp_path / "job1_executed_count.txt"
    py_script = f"""import sys
with open(r'{marker_file.as_posix()}', 'a') as f:
    f.write('1\\n')
"""
    script_path = tmp_path / "record.py"
    script_path.write_text(py_script, encoding="utf-8")

    config_data = {
        "settings": {
            "log_dir": str(log_dir),
            "stop_on_failure": True,
        },
        "jobs": [
            {
                "name": "job-1",
                "cwd": str(workspace_dir),
                "commands": [f'"{sys.executable}" "{script_path}"'],
            },
            {
                "name": "job-2",
                "cwd": str(workspace_dir),
                "commands": [f'"{sys.executable}" -c "import sys; sys.exit(1)"'],
            },
        ],
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    # 1. First run: job-1 passes, job-2 fails
    res1 = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res1.returncode == 1
    assert marker_file.read_text().splitlines() == ["1"]

    # If we resume, job-1 should be skipped
    res_resume = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file), "--resume", "latest"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res_resume.returncode == 1
    # marker_file should still have 1 entry (job-1 was skipped on resume)
    assert marker_file.read_text().splitlines() == ["1"]

    # 2. Run with --fresh: job-1 must execute again from the start
    res2 = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file), "--fresh"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res2.returncode == 1
    assert marker_file.read_text().splitlines() == ["1", "1"]


def test_cli_run_ignore_saved_state_alias(tmp_path):
    """Running 'lbs run --ignore-saved-state' works as an alias for --fresh."""
    config_file = tmp_path / "fresh_alias.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    marker_file = tmp_path / "job1_alias_count.txt"
    py_script = f"""import sys
with open(r'{marker_file.as_posix()}', 'a') as f:
    f.write('1\\n')
"""
    script_path = tmp_path / "record_alias.py"
    script_path.write_text(py_script, encoding="utf-8")

    config_data = {
        "settings": {
            "log_dir": str(log_dir),
            "stop_on_failure": True,
        },
        "jobs": [
            {
                "name": "job-1",
                "cwd": str(workspace_dir),
                "commands": [f'"{sys.executable}" "{script_path}"'],
            },
            {
                "name": "job-2",
                "cwd": str(workspace_dir),
                "commands": [f'"{sys.executable}" -c "import sys; sys.exit(1)"'],
            },
        ],
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    # 1. First run: job-1 passes, job-2 fails
    subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert marker_file.read_text().splitlines() == ["1"]

    # 2. Run with --ignore-saved-state
    res = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file), "--ignore-saved-state"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 1
    assert marker_file.read_text().splitlines() == ["1", "1"]


def test_cli_run_fresh_and_resume_mutually_exclusive(tmp_path):
    """Passing both --resume and --fresh exits with error code 2."""
    config_file = tmp_path / "conflict.yaml"
    config_file.write_text("jobs: []", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run", str(config_file), "--resume", "latest", "--fresh"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr or "mutually exclusive" in result.stderr
