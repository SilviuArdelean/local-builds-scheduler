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
        Job(
            name="job-one",
            cwd=str(tmp_path),
            commands=[py_cmd],
            env={"TEST_VAR": "job-one-env"}
        )
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
        Job(
            name="job-one",
            cwd=str(tmp_path),
            commands=[py_success, py_fail, py_not_run]
        ),
        Job(
            name="job-two",
            cwd=str(tmp_path),
            commands=[py_job2]
        )
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


def test_runner_stop_on_failure(tmp_path):
    """Verify immediate abort on job failure when stop_on_failure is True."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))
    
    py_fail = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
    py_job2 = f'"{sys.executable}" -c "print(\'job two executed\')"'
    
    jobs = [
        Job(
            name="job-one",
            cwd=str(tmp_path),
            commands=[py_fail]
        ),
        Job(
            name="job-two",
            cwd=str(tmp_path),
            commands=[py_job2]
        )
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
            Job(
                name="job-one",
                cwd=str(tmp_path),
                commands=[py_cmd],
                env={"LBS_TEST_TWO": "overlaid-value"}
            )
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
