# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for session resuming functionality.
"""

import json
import sys
import pytest

from lbs.config import Config, Settings, Job
from lbs.runner import Scheduler


def test_resume_no_state_error(tmp_path):
    """Verify that attempting to resume when no state exists raises a ValueError."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    jobs = [Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"])]
    config = Config(settings=settings, jobs=jobs)

    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, resume="latest")
    assert "No active session state found to resume." in str(exc.value)


def test_resume_completed_run(tmp_path, capsys):
    """Verify that attempting to resume a fully successful run exits early with success."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    jobs = [Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"])]
    config = Config(settings=settings, jobs=jobs)

    # 1. Run successfully
    success = Scheduler.run(config)
    assert success is True

    # 2. Try to resume
    success_resume = Scheduler.run(config, resume="latest")
    assert success_resume is True

    captured = capsys.readouterr()
    expected_msg = ("All selected jobs in the previous session completed "
                    "successfully. Nothing to resume.")
    assert expected_msg in captured.out


def test_resume_failed_run(tmp_path):
    """Verify that resuming a failed session execution only runs non-succeeded jobs."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))

    # We will write to log file to track how many times a command ran
    run_tracker_1 = tmp_path / "run_tracker_1.txt"
    run_tracker_2 = tmp_path / "run_tracker_2.txt"

    py_cmd_1 = f'"{sys.executable}" -c "with open(r\'{run_tracker_1.as_posix()}\', \'a\') as f: f.write(\'ran\\n\')"'
    # Command 2 fails on first run, succeeds on second run
    fail_flag = tmp_path / "fail_flag.txt"
    py_cmd_2 = (f'"{sys.executable}" -c "'
                f'import os, sys; '
                f'exists = os.path.exists(r\'{fail_flag.as_posix()}\'); '
                f'open(r\'{fail_flag.as_posix()}\', \'w\').close(); '
                f'f = open(r\'{run_tracker_2.as_posix()}\', \'a\'); '
                f'f.write(\'ran, exists: \' + str(exists) + \'\\n\'); '
                f'f.close(); '
                f'sys.exit(0 if exists else 1)"')

    jobs = [
        Job(name="job-1", cwd=str(tmp_path), commands=[py_cmd_1]),
        Job(name="job-2", cwd=str(tmp_path), commands=[py_cmd_2])
    ]
    config = Config(settings=settings, jobs=jobs)

    # First run: job-1 succeeds, job-2 fails
    success1 = Scheduler.run(config)
    assert success1 is False

    assert run_tracker_1.read_text().splitlines() == ["ran"]
    assert run_tracker_2.read_text().splitlines() == ["ran, exists: False"]

    # Verify state file
    state_path = log_dir / "lbs_state.json"
    assert state_path.is_file()
    with open(state_path, "r", encoding="utf-8") as f:
        state_data = json.load(f)
    assert state_data["jobs"]["job-1"]["status"] == "SUCCESS"
    assert state_data["jobs"]["job-2"]["status"] == "FAILED"

    # Second run: resume. job-1 is already SUCCESS, so only job-2 runs (and now succeeds)
    success2 = Scheduler.run(config, resume="latest")
    if not success2:
        log_files = list(log_dir.glob("*_job-2.log"))
        log_content = log_files[0].read_text(
            encoding="utf-8") if log_files else "No job-2 log file found"
        assert success2 is True, f"Second run failed! Job 2 log:\n{log_content}"
    assert success2 is True

    # Job-1 should NOT have run again
    assert run_tracker_1.read_text().splitlines() == ["ran"]
    # Job-2 should have run again
    assert run_tracker_2.read_text().splitlines() == [
        "ran, exists: False", "ran, exists: True"
    ]


def test_resume_interrupted_run(tmp_path):
    """Verify that we can resume from a manually constructed interrupted state and unify logs/dates."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    run_tracker_1 = tmp_path / "run_tracker_1.txt"
    run_tracker_2 = tmp_path / "run_tracker_2.txt"

    py_cmd_1 = f'"{sys.executable}" -c "with open(r\'{run_tracker_1.as_posix()}\', \'a\') as f: f.write(\'ran\\n\')"'
    py_cmd_2 = f'"{sys.executable}" -c "with open(r\'{run_tracker_2.as_posix()}\', \'a\') as f: f.write(\'ran\\n\')"'

    jobs = [
        Job(name="job-1", cwd=str(tmp_path), commands=[py_cmd_1]),
        Job(name="job-2", cwd=str(tmp_path), commands=[py_cmd_2])
    ]
    config = Config(settings=settings, jobs=jobs)

    # Pre-populate state: job-1 is SUCCESS, job-2 is PENDING, session_date is 2026-06-17
    state_path = log_dir / "lbs_state.json"
    state_data = {
        "config_file": "some_config.yaml",
        "session_date": "2026-06-17",
        "jobs": {
            "job-1": {
                "status": "SUCCESS",
                "duration": 5.0
            },
            "job-2": {
                "status": "PENDING",
                "duration": None
            }
        }
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    success = Scheduler.run(config, resume="latest")
    assert success is True

    # job-1 was skipped because it was marked SUCCESS
    assert not run_tracker_1.exists()
    # job-2 executed and succeeded
    assert run_tracker_2.read_text().splitlines() == ["ran"]

    # Verify session log is unified under the original date
    session_log = log_dir / "2026-06-17_session.log"
    assert session_log.is_file()
    session_content = session_log.read_text(encoding="utf-8")
    assert "--- Session resumed ---" in session_content
    assert "Job: job-2                ->  SUCCESS" in session_content


def test_resume_dry_run(tmp_path, capsys):
    """Verify that --dry-run prints ALREADY SUCCEEDED for completed jobs when resuming."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    jobs = [
        Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"]),
        Job(name="job-2", cwd=str(tmp_path), commands=["echo 2"])
    ]
    config = Config(settings=settings, jobs=jobs)

    state_path = log_dir / "lbs_state.json"
    state_data = {
        "config_file": "config.yaml",
        "session_date": "2026-06-17",
        "jobs": {
            "job-1": {
                "status": "SUCCESS",
                "duration": 5.0
            },
            "job-2": {
                "status": "PENDING",
                "duration": None
            }
        }
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)

    success = Scheduler.run(config, dry_run=True, resume="latest")
    assert success is True

    captured = capsys.readouterr()
    assert "Resuming Session from latest state" in captured.out
    assert "Job: job-1 [ALREADY SUCCEEDED]" in captured.out
    assert "Job: job-2" in captured.out


def test_resume_invalid_json_shape(tmp_path):
    """Verify that malformed state file JSON shape raises ValueError."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))
    config = Config(
        settings=settings,
        jobs=[Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"])])
    state_path = log_dir / "lbs_state.json"

    # Scenario A: Not a JSON object (e.g., a list)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump([1, 2, 3], f)
    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, resume="latest")
    assert "state file content is not a JSON object" in str(exc.value)

    # Scenario B: Missing or wrong type for 'jobs'
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"session_date": "2026-06-17", "jobs": [1, 2]}, f)
    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, resume="latest")
    assert "'jobs' field is missing or not a JSON object" in str(exc.value)

    # Scenario C: Missing or wrong type for 'session_date'
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump({"session_date": 12345, "jobs": {}}, f)
    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, resume="latest")
    assert "'session_date' field is missing or not a string" in str(exc.value)


def test_resume_invalid_session_date(tmp_path):
    """Verify that invalid or malicious session_date string formats raise ValueError."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))
    config = Config(
        settings=settings,
        jobs=[Job(name="job-1", cwd=str(tmp_path), commands=["echo 1"])])
    state_path = log_dir / "lbs_state.json"

    # Scenario A: Path traversal attempt
    state_data = {
        "config_file": "config.yaml",
        "session_date": "../../../etc/passwd",
        "jobs": {}
    }
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)
    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, resume="latest")
    assert "invalid session_date format" in str(exc.value)

    # Scenario B: Wrong separator
    state_data["session_date"] = "2026/06/17"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)
    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, resume="latest")
    assert "invalid session_date format" in str(exc.value)

    # Scenario C: Letters instead of numbers
    state_data["session_date"] = "yyyy-mm-dd"
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_data, f)
    with pytest.raises(ValueError) as exc:
        Scheduler.run(config, resume="latest")
    assert "invalid session_date format" in str(exc.value)
