# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for the sequential runner (lbs.runner).
"""

import datetime
import os
import sys
from pathlib import Path
from lbs.config import Config, Settings, Job
from lbs.runner import run_scheduler


def test_runner_success(tmp_path):
    """Verify that a successful run creates logs and correct summaries."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # We will use sys.executable to run a python command cross-platform
    py_cmd = f'"{sys.executable}" -c "print(\'hello from stdout\')"'

    jobs = [
        Job(name="job-one",
            cwd=str(tmp_path),
            commands=[py_cmd],
            env={"TEST_VAR": "job-one-env"})
    ]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is True

    # Verify files created
    assert log_dir.is_dir()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    session_log = log_dir / f"{date_str}_session.log"
    job_log = log_dir / f"{date_str}_job-one.log"

    assert session_log.exists()
    assert job_log.exists()

    # Verify job log contains stdout output
    job_log_content = job_log.read_text(encoding="utf-8")
    assert "hello from stdout" in job_log_content
    assert "Job 'job-one' started" in job_log_content
    assert "Command succeeded" in job_log_content

    # Verify session log contains starting and summary
    session_log_content = session_log.read_text(encoding="utf-8")
    assert "--- Session started ---" in session_log_content
    assert "Starting job: job-one" in session_log_content
    assert "Job job-one: SUCCESS" in session_log_content
    assert "LBS Session Summary" in session_log_content
    assert "Session completed: SUCCESS" in session_log_content
    assert "Run Summary" in session_log_content
    assert "Passed: 1" in session_log_content
    assert "Failed: 0" in session_log_content
    assert "Skipped: 0" in session_log_content
    assert "Duration: 00:00:" in session_log_content


def test_runner_failure_non_stop(tmp_path):
    """Verify failure isolation when stop_on_failure is False."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # job 1 has command 1 succeed, command 2 fail, command 3 not executed
    py_success = f'"{sys.executable}" -c "print(\'first command\')"'
    py_fail = f'"{sys.executable}" -c "import sys; print(\'second command failing\'); sys.exit(42)"'
    py_not_run = f'"{sys.executable}" -c "print(\'third command not run\')"'

    # job 2 should run despite job 1 failure
    py_job2 = f'"{sys.executable}" -c "print(\'job two executed\')"'

    jobs = [
        Job(name="job-one",
            cwd=str(tmp_path),
            commands=[py_success, py_fail, py_not_run]),
        Job(name="job-two", cwd=str(tmp_path), commands=[py_job2])
    ]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is False

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    session_log = log_dir / f"{date_str}_session.log"
    job_one_log = log_dir / f"{date_str}_job-one.log"
    job_two_log = log_dir / f"{date_str}_job-two.log"

    # Check job-one log: first command ran, second failed, third did not run
    job_one_content = job_one_log.read_text(encoding="utf-8")
    assert "first command" in job_one_content
    assert "second command failing" in job_one_content
    assert "Command failed with exit code 42" in job_one_content
    assert "third command not run" not in job_one_content

    # Check job-two log: it did run because stop_on_failure is False
    assert job_two_log.exists()
    job_two_content = job_two_log.read_text(encoding="utf-8")
    assert "job two executed" in job_two_content

    # Check session log
    session_content = session_log.read_text(encoding="utf-8")
    assert "Job job-one: FAILED" in session_content
    assert "Job job-two: SUCCESS" in session_content
    assert "Session completed: FAILED" in session_content
    assert "job-one              ->  FAILED" in session_content
    assert "job-two              ->  SUCCESS" in session_content
    assert "Run Summary" in session_content
    assert "Passed: 1" in session_content
    assert "Failed: 1" in session_content
    assert "Skipped: 0" in session_content


def test_runner_stop_on_failure(tmp_path):
    """Verify immediate abort on job failure when stop_on_failure is True."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))

    py_fail = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
    py_job2 = f'"{sys.executable}" -c "print(\'job two executed\')"'

    jobs = [
        Job(name="job-one", cwd=str(tmp_path), commands=[py_fail]),
        Job(name="job-two", cwd=str(tmp_path), commands=[py_job2])
    ]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is False

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    session_log = log_dir / f"{date_str}_session.log"
    job_two_log = log_dir / f"{date_str}_job-two.log"

    # Job two should not even have a log file created because it was aborted/skipped
    assert not job_two_log.exists()

    # Check session log
    session_content = session_log.read_text(encoding="utf-8")
    assert "Aborting execution of subsequent jobs (stop_on_failure is enabled)" in session_content
    assert "job-one              ->  FAILED" in session_content
    assert "job-two              ->  SKIPPED" in session_content
    assert "Session completed: FAILED" in session_content
    assert "Run Summary" in session_content
    assert "Passed: 0" in session_content
    assert "Failed: 1" in session_content
    assert "Skipped: 1" in session_content


def test_runner_environment_propagation(tmp_path):
    """Verify that child processes inherit custom environment overlays."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # Command prints environment variables to stdout
    py_cmd = f'"{sys.executable}" -c "import os; print(\'LBS_VAL_ONE:\' + os.environ.get(\'LBS_TEST_ONE\', \'\')); print(\'LBS_VAL_TWO:\' + os.environ.get(\'LBS_TEST_TWO\', \'\'))"'

    # Set standard system environment variable to verify inheritance
    os.environ["LBS_TEST_ONE"] = "inherited-value"

    try:
        jobs = [
            Job(name="job-one",
                cwd=str(tmp_path),
                commands=[py_cmd],
                env={"LBS_TEST_TWO": "overlaid-value"})
        ]
        config = Config(settings=settings, jobs=jobs)

        success = run_scheduler(config)
        assert success is True

        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
        job_log = log_dir / f"{date_str}_job-one.log"
        job_log_content = job_log.read_text(encoding="utf-8")

        assert "LBS_VAL_ONE:inherited-value" in job_log_content
        assert "LBS_VAL_TWO:overlaid-value" in job_log_content

    finally:
        # Clean up global env modification
        if "LBS_TEST_ONE" in os.environ:
            del os.environ["LBS_TEST_ONE"]


def test_runner_retry_success(tmp_path):
    """Verify that a job failing on first attempt but succeeding on retry is reported as SUCCESS."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # Creates a flag file. Succeeds only if flag file already exists.
    flag_file = tmp_path / "flag.txt"
    py_cmd = (f'"{sys.executable}" -c "import os, sys; '
              f'exists = os.path.exists(r\'{flag_file}\'); '
              f'open(r\'{flag_file}\', \'w\').close(); '
              f'sys.exit(0 if exists else 1)"')

    jobs = [
        Job(name="job-retry-success",
            cwd=str(tmp_path),
            commands=[py_cmd],
            retries=1,
            retry_delay_seconds=0.01)
    ]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is True

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    job_log = log_dir / f"{date_str}_job-retry-success.log"
    session_log = log_dir / f"{date_str}_session.log"

    assert job_log.exists()
    job_content = job_log.read_text(encoding="utf-8")
    assert "--- Retry Attempt 1 / 1 ---" in job_content

    session_content = session_log.read_text(encoding="utf-8")
    assert "Job job-retry-success failed. Retrying in 0.01 seconds" in session_content
    assert "Job job-retry-success: ATTEMPT FAILED" in session_content
    assert "Job job-retry-success: FAILED" not in session_content
    assert "Job job-retry-success: SUCCESS" in session_content


def test_runner_retry_exhausted(tmp_path):
    """Verify that retries are exhausted, delay is respected, and failure is reported."""
    from unittest.mock import patch
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    py_fail = f'"{sys.executable}" -c "import sys; sys.exit(1)"'

    jobs = [
        Job(name="job-retry-fail",
            cwd=str(tmp_path),
            commands=[py_fail],
            retries=2,
            retry_delay_seconds=15)
    ]
    config = Config(settings=settings, jobs=jobs)

    with patch("time.sleep") as mock_sleep:
        success = run_scheduler(config)
        assert success is False

        # Should sleep twice (once after first try, once after second try)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(15)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    job_log = log_dir / f"{date_str}_job-retry-fail.log"
    session_log = log_dir / f"{date_str}_session.log"

    job_content = job_log.read_text(encoding="utf-8")
    assert "--- Retry Attempt 1 / 2 ---" in job_content
    assert "--- Retry Attempt 2 / 2 ---" in job_content

    session_content = session_log.read_text(encoding="utf-8")
    assert "Job job-retry-fail failed. Retrying in 15 seconds (attempt 1/2)..." in session_content
    assert "Job job-retry-fail failed. Retrying in 15 seconds (attempt 2/2)..." in session_content
    assert "Job job-retry-fail: ATTEMPT FAILED" in session_content
    assert "Job job-retry-fail: FAILED" in session_content


def test_runner_skips_disabled_jobs(tmp_path):
    """Verify that disabled jobs are correctly skipped, marked as SKIPPED, and logs are not created for them."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))

    py_cmd1 = f'"{sys.executable}" -c "print(\'job-one\')"'
    py_cmd2 = f'"{sys.executable}" -c "print(\'job-two\')"'
    py_cmd3 = f'"{sys.executable}" -c "print(\'job-three\')"'

    jobs = [
        Job(name="job-one",
            cwd=str(tmp_path),
            commands=[py_cmd1],
            build_it=True),
        Job(name="job-two",
            cwd=str(tmp_path),
            commands=[py_cmd2],
            build_it=False),
        Job(name="job-three",
            cwd=str(tmp_path),
            commands=[py_cmd3],
            build_it=True)
    ]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is True

    # Verify files created
    assert log_dir.is_dir()
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")

    session_log = log_dir / f"{date_str}_session.log"
    job_one_log = log_dir / f"{date_str}_job-one.log"
    job_two_log = log_dir / f"{date_str}_job-two.log"
    job_three_log = log_dir / f"{date_str}_job-three.log"

    assert session_log.exists()
    assert job_one_log.exists()
    assert not job_two_log.exists()
    assert job_three_log.exists()

    # Verify session log contains correct notes
    session_log_content = session_log.read_text(encoding="utf-8")
    assert "Starting job: job-one" in session_log_content
    assert "Job job-two is disabled. Skipping." in session_log_content
    assert "Starting job: job-three" in session_log_content

    assert "job-one              ->  SUCCESS" in session_log_content
    assert "job-two              ->  SKIPPED" in session_log_content
    assert "job-three            ->  SUCCESS" in session_log_content
    assert "Passed: 2" in session_log_content
    assert "Failed: 0" in session_log_content
    assert "Skipped: 1" in session_log_content
    assert "Session completed: SUCCESS" in session_log_content


def test_runner_directory_persistence(tmp_path):
    """Verify that working directory changes persist across sequential commands."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))

    if sys.platform == "win32":
        commands = [
            "mkdir test_dir",
            "cd test_dir",
            "echo persistence > test.txt",
            "type test.txt",
            "cd ..",
            "rmdir /s /q test_dir",
        ]
    else:
        commands = [
            "mkdir test_dir",
            "cd test_dir",
            "echo persistence > test.txt",
            "cat test.txt",
            "cd ..",
            "rm -rf test_dir",
        ]

    jobs = [Job(name="job-dir-test", cwd=str(tmp_path), commands=commands)]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is True

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    job_log = log_dir / f"{date_str}_job-dir-test.log"
    job_log_content = job_log.read_text(encoding="utf-8")

    assert "persistence" in job_log_content


def test_runner_environment_persistence(tmp_path):
    """Verify that environment variable assignments persist across sequential commands."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))

    if sys.platform == "win32":
        commands = [
            "set LBS_TEST_PERSIST=success_env",
            "echo LBS_ENV_VAL:%LBS_TEST_PERSIST%",
        ]
    else:
        commands = [
            "export LBS_TEST_PERSIST=success_env",
            "echo LBS_ENV_VAL:$LBS_TEST_PERSIST",
        ]

    jobs = [Job(name="job-env-test", cwd=str(tmp_path), commands=commands)]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is True

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    job_log = log_dir / f"{date_str}_job-env-test.log"
    job_log_content = job_log.read_text(encoding="utf-8")

    assert "LBS_ENV_VAL:success_env" in job_log_content
