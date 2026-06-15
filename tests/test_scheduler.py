# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for LBS Scheduler job queuing and filtering (lbs.runner.Scheduler).
"""

import datetime
import os
import subprocess
import sys
import pytest
import yaml
from lbs.config import Config, Settings, Job
from lbs.runner import Scheduler


def test_scheduler_queue_order(tmp_path):
    """Verify that multiple jobs run in the exact sequential order defined by the config."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # We will write to a shared tracking file to prove exact execution order
    tracker_file = tmp_path / "order_tracker.txt"

    py_cmd_1 = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'jobA\\n\')"'
    py_cmd_2 = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'jobB\\n\')"'
    py_cmd_3 = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'jobC\\n\')"'

    jobs = [
        Job(name="job-A", cwd=str(tmp_path), commands=[py_cmd_1]),
        Job(name="job-B", cwd=str(tmp_path), commands=[py_cmd_2]),
        Job(name="job-C", cwd=str(tmp_path), commands=[py_cmd_3]),
    ]
    config = Config(settings=settings, jobs=jobs)

    success = Scheduler.run(config)
    assert success is True

    # Check execution order in file
    order = tracker_file.read_text().splitlines()
    assert order == ["jobA", "jobB", "jobC"]


def test_scheduler_filtering_success(tmp_path):
    """Verify that only the jobs matching the job_filter are executed, leaving others SKIPPED."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    tracker_file = tmp_path / "filter_tracker.txt"
    py_cmd_A = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'A\\n\')"'
    py_cmd_B = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'B\\n\')"'
    py_cmd_C = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'C\\n\')"'

    jobs = [
        Job(name="job-A", cwd=str(tmp_path), commands=[py_cmd_A]),
        Job(name="job-B", cwd=str(tmp_path), commands=[py_cmd_B]),
        Job(name="job-C", cwd=str(tmp_path), commands=[py_cmd_C]),
    ]
    config = Config(settings=settings, jobs=jobs)

    # Filter to only run job-A and job-C
    success = Scheduler.run(config, job_filter=["job-A", "job-C"])
    assert success is True

    # Check execution tracker: job-B should be omitted
    order = tracker_file.read_text().splitlines()
    assert order == ["A", "C"]

    # Verify log files created
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    assert (log_dir / f"{date_str}_job-A.log").exists()
    assert not (log_dir / f"{date_str}_job-B.log").exists()
    assert (log_dir / f"{date_str}_job-C.log").exists()

    # Check session log summary output to see that job-B is marked SKIPPED
    session_log = log_dir / f"{date_str}_session.log"
    session_content = session_log.read_text(encoding="utf-8")
    assert "job-A                ->  SUCCESS" in session_content
    assert "job-B                ->  SKIPPED" in session_content
    assert "job-C                ->  SUCCESS" in session_content


def test_scheduler_filtering_invalid_name(tmp_path):
    """Verify that passing non-existent job name filters raises a ValueError."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    jobs = [
        Job(name="job-A", cwd=str(tmp_path), commands=["echo A"]),
    ]
    config = Config(settings=settings, jobs=jobs)

    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, job_filter=["job-A", "missing-job"])
    assert "Job filter contains invalid job names: missing-job" in str(
        exc.value)

    # Assert log_dir was not created
    assert not log_dir.exists()


def test_cli_filtering_success(tmp_path):
    """Integration test: Verify running 'lbs run' command with multiple --job flags."""
    config_file = tmp_path / "config.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"
    tracker_file = tmp_path / "cli_filter_tracker.txt"

    py_cmd_A = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'cliA\\n\')"'
    py_cmd_B = f'"{sys.executable}" -c "with open(r\'{tracker_file}\', \'a\') as f: f.write(\'cliB\\n\')"'

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "commands": [py_cmd_A]
        }, {
            "name": "job-B",
            "cwd": str(workspace_dir),
            "commands": [py_cmd_B]
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    # Run CLI command selecting only job-B
    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--job", "job-B"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "job-B                ->  SUCCESS" in result.stdout
    assert "job-A                ->  SKIPPED" in result.stdout

    # Check that only cliB was executed
    executed = tracker_file.read_text().splitlines()
    assert executed == ["cliB"]


def test_cli_filtering_invalid_name(tmp_path):
    """Integration test: Verify that invalid job name filters print an Error and exit with code 2."""
    config_file = tmp_path / "config.yaml"
    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    log_dir = tmp_path / "logs"

    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [{
            "name": "job-A",
            "cwd": str(workspace_dir),
            "commands": ["echo A"]
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    # Run CLI command with invalid job filter name
    result = subprocess.run(
        [
            sys.executable, "-m", "lbs", "run",
            str(config_file), "--job", "bad-name-xyz"
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Error: Job filter contains invalid job names: bad-name-xyz" in result.stderr


def test_cli_run_value_error_without_job(tmp_path):
    """Verify that a ValueError raised during run without --job is not masked by cmd_run."""
    from lbs.cli import cmd_run
    import argparse
    from unittest.mock import patch
    
    args = argparse.Namespace(config="some_config.yaml", verbose=False, job=None)
    
    with patch("lbs.cli.load_config") as mock_load, \
         patch("lbs.cli.Scheduler.run", side_effect=ValueError("Programming error")):
        mock_load.return_value = None
        
        with pytest.raises(ValueError) as exc:
            cmd_run(args)
        assert "Programming error" in str(exc.value)

