# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for session resuming functionality.
"""

import json
import sys
import pytest

from lbs.config import Config, Settings, Job, resolve_status_path, BuildStatus
from lbs.runner import (
    Scheduler,
    _save_status,
    _parse_and_validate_resume_status,
)


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


def test_profile_scoped_status_file_creation(tmp_path):
    """Verify that different config files create isolated status files in the log directory."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # Profile 1: build-debug
    config1 = Config(
        settings=settings,
        jobs=[
            Job(name="job-debug", cwd=str(tmp_path), commands=["echo debug"])
        ],
    )
    success1 = Scheduler.run(
        config1,
        config_path="configs/build-debug.yaml",
    )
    assert success1 is True

    status_path_1 = log_dir / "lbs_status_build-debug.json"
    assert status_path_1.is_file()

    with open(status_path_1, "r", encoding="utf-8") as f:
        data1 = json.load(f)
    assert "job-debug" in data1["jobs"]
    assert data1["jobs"]["job-debug"]["build_status"] == "DONE"

    # Profile 2: nightly-release
    config2 = Config(
        settings=settings,
        jobs=[
            Job(name="job-release",
                cwd=str(tmp_path),
                commands=["echo release"])
        ],
    )
    success2 = Scheduler.run(
        config2,
        config_path="configs/nightly-release.yaml",
    )
    assert success2 is True

    status_path_2 = log_dir / "lbs_status_nightly-release.json"
    assert status_path_2.is_file()

    with open(status_path_2, "r", encoding="utf-8") as f:
        data2 = json.load(f)
    assert "job-release" in data2["jobs"]
    assert data2["jobs"]["job-release"]["build_status"] == "DONE"

    # Verify that profile 1's status file was untouched and isolated
    with open(status_path_1, "r", encoding="utf-8") as f:
        data1_after = json.load(f)
    assert "job-debug" in data1_after["jobs"]
    assert "job-release" not in data1_after["jobs"]


def test_resume_from_legacy_state_file(tmp_path):
    """Verify that legacy lbs_state.json files are correctly loaded and normalized."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    legacy_file = log_dir / "lbs_state.json"
    legacy_data = {
        "config_file": "old_config.yaml",
        "session_date": "2026-06-17",
        "jobs": {
            "legacy-job": {
                "status": "SUCCESS",
                "duration": 4.2,
            }
        },
    }
    with open(legacy_file, "w", encoding="utf-8") as f:
        json.dump(legacy_data, f)

    # Calling _parse_and_validate_resume_status on a non-existent status path falls back to lbs_state.json
    non_existent_status_path = log_dir / "lbs_status_old_config.json"
    session_date, summaries = _parse_and_validate_resume_status(
        non_existent_status_path)
    assert session_date == "2026-06-17"
    assert "legacy-job" in summaries
    assert summaries["legacy-job"]["status"] == "SUCCESS"
    assert summaries["legacy-job"]["build_status"] == "DONE"


def test_stale_running_reconciler_job_level(tmp_path, capsys):
    """Verify that a stale RUNNING job status is detected, warned, and reconciled to FAILED."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    status_path = log_dir / "lbs_status_crashed_run.json"

    stale_data = {
        "config_file": "crashed_run.yaml",
        "session_date": "2026-10-20",
        "jobs": {
            "crashed-job": {
                "build_status": "RUNNING",
                "status": "RUNNING",
                "duration": None,
            }
        },
    }
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(stale_data, f)

    session_date, summaries = _parse_and_validate_resume_status(status_path)
    assert summaries["crashed-job"]["build_status"] == "FAILED"
    assert summaries["crashed-job"]["status"] == "FAILED"

    # Verify warning emitted to stderr
    captured = capsys.readouterr()
    assert "Detected interrupted execution for job 'crashed-job'" in captured.err
    assert "Reconciling stale RUNNING state to FAILED" in captured.err

    # Verify file on disk was reconciled atomically
    with open(status_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["jobs"]["crashed-job"]["build_status"] == "FAILED"
    assert disk_data["jobs"]["crashed-job"]["status"] == "FAILED"


def test_stale_running_reconciler_command_level(tmp_path, capsys):
    """Verify that a stale RUNNING command is detected, warned, and reconciled to FAILED."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    status_path = log_dir / "lbs_status_interrupted_cmd.json"

    stale_data = {
        "config_file": "interrupted_cmd.yaml",
        "session_date": "2026-10-20",
        "jobs": {
            "multi-step-job": {
                "build_status":
                "RUNNING",
                "status":
                "RUNNING",
                "commands": [
                    {
                        "index": 0,
                        "command": "echo step1",
                        "status": "DONE"
                    },
                    {
                        "index": 1,
                        "command": "compile_code",
                        "status": "RUNNING"
                    },
                    {
                        "index": 2,
                        "command": "echo step3",
                        "status": "PENDING"
                    },
                ],
            }
        },
    }
    with open(status_path, "w", encoding="utf-8") as f:
        json.dump(stale_data, f)

    session_date, summaries = _parse_and_validate_resume_status(status_path)
    job_summary = summaries["multi-step-job"]
    assert job_summary["build_status"] == "FAILED"
    assert job_summary["status"] == "FAILED"
    assert job_summary["commands"][1]["status"] == "FAILED"
    assert job_summary["commands"][0]["status"] == "DONE"
    assert job_summary["commands"][2]["status"] == "PENDING"

    # Verify warning mentioned the specific command
    captured = capsys.readouterr()
    assert "Detected interrupted execution for job 'multi-step-job' (command: 'compile_code')" in captured.err

    # Verify file on disk updated
    with open(status_path, "r", encoding="utf-8") as f:
        disk_data = json.load(f)
    assert disk_data["jobs"]["multi-step-job"]["commands"][1][
        "status"] == "FAILED"
    assert disk_data["jobs"]["multi-step-job"]["build_status"] == "FAILED"


def test_granular_command_skipping_on_resume(tmp_path):
    """Verify that commands marked DONE are skipped on --resume latest, starting at the failed command."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))
    config_path = "configs/build-granular.yaml"

    trace_file = tmp_path / "trace.txt"
    fix_file = tmp_path / "fix.txt"

    # Command 0: appends "cmd0"
    py_cmd0 = (
        f'"{sys.executable}" -c "f = open(r\'{trace_file}\', \'a\'); f.write(\'cmd0\\n\'); f.close()"'
    )
    # Command 1: appends "cmd1", fails if fix_file does not exist
    py_cmd1 = (
        f'"{sys.executable}" -c "import os, sys; '
        f'f = open(r\'{trace_file}\', \'a\'); f.write(\'cmd1\\n\'); f.close(); '
        f'sys.exit(0 if os.path.exists(r\'{fix_file}\') else 1)"')
    # Command 2: appends "cmd2"
    py_cmd2 = (
        f'"{sys.executable}" -c "f = open(r\'{trace_file}\', \'a\'); f.write(\'cmd2\\n\'); f.close()"'
    )

    job = Job(
        name="job-granular",
        cwd=str(tmp_path),
        commands=[py_cmd0, py_cmd1, py_cmd2],
    )
    config = Config(settings=settings, jobs=[job])

    # Run 1: Should fail on command 1
    success1 = Scheduler.run(config, config_path=config_path)
    assert success1 is False

    status_file = log_dir / "lbs_status_build-granular.json"
    assert status_file.is_file()

    with open(status_file, "r", encoding="utf-8") as f:
        status_data1 = json.load(f)

    job_data1 = status_data1["jobs"]["job-granular"]
    assert job_data1["build_status"] == "FAILED"
    assert len(job_data1["commands"]) == 3
    assert job_data1["commands"][0]["status"] == "DONE"
    assert job_data1["commands"][0]["exit_code"] == 0
    assert job_data1["commands"][1]["status"] == "FAILED"
    assert job_data1["commands"][1]["exit_code"] != 0
    assert job_data1["commands"][2]["status"] == "PENDING"

    trace_content_1 = trace_file.read_text(
        encoding="utf-8").strip().splitlines()
    assert trace_content_1 == ["cmd0", "cmd1"]

    # Now create fix_file so command 1 will succeed on resume
    fix_file.write_text("fixed")

    # Run 2: Resume latest
    success2 = Scheduler.run(config, resume="latest", config_path=config_path)
    assert success2 is True

    # Verify command 0 was NOT executed again, while command 1 and 2 were executed
    trace_content_2 = trace_file.read_text(
        encoding="utf-8").strip().splitlines()
    assert trace_content_2 == ["cmd0", "cmd1", "cmd1", "cmd2"]

    # Verify final status file on disk
    with open(status_file, "r", encoding="utf-8") as f:
        status_data2 = json.load(f)

    job_data2 = status_data2["jobs"]["job-granular"]
    assert job_data2["build_status"] == "DONE"
    assert job_data2["status"] == "SUCCESS"
    for c in job_data2["commands"]:
        assert c["status"] == "DONE"
        assert c["exit_code"] == 0


def test_granular_phased_command_resumption(tmp_path):
    """Verify that in phased mode, completed phases and completed commands are skipped on resume."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))
    config_path = "configs/build-phased.yaml"

    trace_file = tmp_path / "phased_trace.txt"
    fix_file = tmp_path / "phased_fix.txt"

    sync_cmd = (
        f'"{sys.executable}" -c "f = open(r\'{trace_file}\', \'a\'); f.write(\'sync\\n\'); f.close()"'
    )
    build_cmd1 = (
        f'"{sys.executable}" -c "import os, sys; '
        f'f = open(r\'{trace_file}\', \'a\'); f.write(\'build1\\n\'); f.close(); '
        f'sys.exit(0 if os.path.exists(r\'{fix_file}\') else 1)"')
    build_cmd2 = (
        f'"{sys.executable}" -c "f = open(r\'{trace_file}\', \'a\'); f.write(\'build2\\n\'); f.close()"'
    )

    job = Job(
        name="job-phased",
        cwd=str(tmp_path),
        commands=[],
        phases={
            "sync": [sync_cmd],
            "build": [build_cmd1, build_cmd2],
        },
    )
    config = Config(settings=settings, jobs=[job])

    # Run 1: Should fail on build1
    success1 = Scheduler.run(config, config_path=config_path, mode="phased")
    assert success1 is False

    trace1 = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert trace1 == ["sync", "build1"]

    fix_file.write_text("fixed")

    # Run 2: Resume latest
    success2 = Scheduler.run(config,
                             resume="latest",
                             config_path=config_path,
                             mode="phased")
    assert success2 is True

    # sync was completed in Run 1 and must NOT run again
    trace2 = trace_file.read_text(encoding="utf-8").strip().splitlines()
    assert trace2 == ["sync", "build1", "build1", "build2"]


def test_disabled_job_command_tasks_skipped(tmp_path):
    """Verify that disabled jobs (build_it: false) have their commands initialized to SKIPPED."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))
    config_path = "configs/build-disabled.yaml"

    job_enabled = Job(
        name="job-enabled",
        cwd=str(tmp_path),
        commands=["echo active"],
        build_it=True,
    )
    job_disabled = Job(
        name="job-disabled",
        cwd=str(tmp_path),
        commands=["echo skipped1", "echo skipped2"],
        build_it=False,
    )
    config = Config(settings=settings, jobs=[job_enabled, job_disabled])

    success = Scheduler.run(config, config_path=config_path)
    assert success is True

    status_file = log_dir / "lbs_status_build-disabled.json"
    with open(status_file, "r", encoding="utf-8") as f:
        status_data = json.load(f)

    disabled_info = status_data["jobs"]["job-disabled"]
    assert disabled_info["build_status"] == "SKIPPED"
    assert disabled_info["status"] == "SKIPPED"
    for c in disabled_info["commands"]:
        assert c["status"] == "SKIPPED"


def test_command_duration_preserved_accurately(tmp_path):
    """Verify that command durations are preserved accurately and not reset to ~0 by post-run drains."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))
    config_path = "configs/build-duration.yaml"

    py_sleep_1 = f'"{sys.executable}" -c "import time; time.sleep(0.15)"'
    py_sleep_2 = f'"{sys.executable}" -c "import time; time.sleep(0.10)"'

    job = Job(
        name="job-duration",
        cwd=str(tmp_path),
        commands=[py_sleep_1, py_sleep_2],
    )
    config = Config(settings=settings, jobs=[job])

    success = Scheduler.run(config, config_path=config_path)
    assert success is True

    status_file = log_dir / "lbs_status_build-duration.json"
    with open(status_file, "r", encoding="utf-8") as f:
        status_data = json.load(f)

    job_data = status_data["jobs"]["job-duration"]
    commands = job_data["commands"]
    assert len(commands) == 2
    assert commands[0]["status"] == "DONE"
    assert commands[0]["duration"] is not None
    assert commands[0][
        "duration"] >= 0.12, f"Expected duration >= 0.12s, got {commands[0]['duration']}s"

    assert commands[1]["status"] == "DONE"
    assert commands[1]["duration"] is not None
    assert commands[1][
        "duration"] >= 0.08, f"Expected duration >= 0.08s, got {commands[1]['duration']}s"
