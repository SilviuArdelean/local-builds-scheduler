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
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "env": {
                "BUILD_TYPE": "debug"
            },
            "commands": ["echo A1", "echo A2"]
        }, {
            "name": "job-B",
            "cwd": str(workspace_dir),
            "commands": ["echo B1"]
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file), "--dry-run"],
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
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "commands": ["echo A1"]
        }, {
            "name": "job-B",
            "cwd": str(workspace_dir),
            "commands": ["echo B1"]
        }]
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
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "commands": ["echo A1"]
        }]
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
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "commands": ["echo A1"],
            "retries": 3,
            "retry_delay_seconds": 12
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file), "--dry-run"],
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
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "commands": ["echo A1"],
            "command_timeout_minutes": 15.5
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Dry-Run Execution Plan" in result.stdout
    assert "Job: job-A" in result.stdout
    assert "  Timeout: 15.5m" in result.stdout


def test_dry_run_with_disabled_job(tmp_path):
    """Verify that --dry-run prints [DISABLED] suffix for disabled jobs and excludes their details."""
    config_file = tmp_path / "config.yaml"
    log_dir = tmp_path / "logs"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "commands": ["echo A1"],
            "build_it": True
        }, {
            "name": "job-B",
            "cwd": str(workspace_dir),
            "commands": ["echo B1"],
            "build_it": False
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "Dry-Run Execution Plan" in result.stdout
    assert "Job: job-A" in result.stdout
    assert f"  CWD: {workspace_dir}" in result.stdout
    assert "    - echo A1" in result.stdout

    # Split the output by "Job: " to isolate each job block
    job_blocks = result.stdout.split("Job: ")
    job_b_block = [b for b in job_blocks if b.startswith("job-B")][0]
    assert "[DISABLED]" in job_b_block
    assert "CWD: " not in job_b_block
    assert "Environment: " not in job_b_block
    assert "Commands:" not in job_b_block


def test_dry_run_resume_command_level_details(tmp_path, capsys):
    """Verify that --dry-run with --resume displays command-level [DONE], [RESUME], [PENDING] tags."""
    import json
    from lbs.config import Config, Job, Settings
    from lbs.runner import Scheduler

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    status_file = log_dir / "lbs_status_build-test.json"

    status_data = {
        "config_file": "configs/build-test.yaml",
        "session_date": "2026-10-20",
        "jobs": {
            "job-multi": {
                "build_status": "FAILED",
                "status": "FAILED",
                "commands": [
                    {"index": 0, "command": "echo step1", "status": "DONE", "duration": 1.25},
                    {"index": 1, "command": "echo step2", "status": "FAILED", "duration": 0.45},
                    {"index": 2, "command": "echo step3", "status": "PENDING", "duration": None},
                ],
            }
        },
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f)

    settings = Settings(log_dir=str(log_dir))
    job = Job(
        name="job-multi",
        cwd=str(tmp_path),
        commands=["echo step1", "echo step2", "echo step3"],
    )
    config = Config(settings=settings, jobs=[job])

    success = Scheduler.run(
        config,
        dry_run=True,
        resume="latest",
        config_path="configs/build-test.yaml",
    )
    assert success is True

    captured = capsys.readouterr()
    assert "Dry-Run Execution Plan" in captured.out
    assert "Resuming Session from latest state (lbs_status_build-test.json)" in captured.out
    assert "Job: job-multi [RESUMING - 1 of 3 commands completed]" in captured.out
    assert "[DONE]    echo step1 (took 1.2s)" in captured.out
    assert "[RESUME]  echo step2" in captured.out
    assert "[PENDING] echo step3" in captured.out


def test_dry_run_resume_phased_commands(tmp_path, capsys):
    """Verify that phased jobs display phase tags and command statuses in dry-run resume."""
    import json
    from lbs.config import Config, Job, Settings
    from lbs.runner import Scheduler

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    status_file = log_dir / "lbs_status_phased-test.json"

    status_data = {
        "config_file": "configs/phased-test.yaml",
        "session_date": "2026-10-20",
        "jobs": {
            "job-phased": {
                "build_status": "FAILED",
                "status": "FAILED",
                "commands": [
                    {"index": 0, "phase": "sync", "command": "fetch_deps.sh", "status": "DONE", "duration": 14.2},
                    {"index": 1, "phase": "sync", "command": "setup_env.sh", "status": "DONE", "duration": 1.1},
                    {"index": 2, "phase": "build", "command": "compile.py", "status": "FAILED", "duration": 5.0},
                    {"index": 3, "phase": "build", "command": "package.py", "status": "PENDING", "duration": None},
                ],
            }
        },
    }
    with open(status_file, "w", encoding="utf-8") as f:
        json.dump(status_data, f)

    settings = Settings(log_dir=str(log_dir))
    job = Job(
        name="job-phased",
        cwd=str(tmp_path),
        commands=[],
        phases={
            "sync": ["fetch_deps.sh", "setup_env.sh"],
            "build": ["compile.py", "package.py"],
        },
    )
    config = Config(settings=settings, jobs=[job])

    success = Scheduler.run(
        config,
        dry_run=True,
        resume="latest",
        config_path="configs/phased-test.yaml",
    )
    assert success is True

    captured = capsys.readouterr()
    assert "Job: job-phased [RESUMING - 2 of 4 commands completed]" in captured.out
    assert "[DONE]    (sync)  fetch_deps.sh (took 14.2s)" in captured.out
    assert "[DONE]    (sync)  setup_env.sh (took 1.1s)" in captured.out
    assert "[RESUME]  (build)  compile.py" in captured.out
    assert "[PENDING] (build)  package.py" in captured.out

