# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for command-level timeout constraints.
"""

import datetime
import sys
from lbs.config import Config, Settings, Job
from lbs.runner import run_scheduler


def test_runner_command_timeout(tmp_path):
    """Verify that a hanging command is terminated when its timeout is exceeded."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # Run a python command that sleeps for 5 seconds
    py_hang = f'"{sys.executable}" -c "import time; time.sleep(5)"'

    jobs = [
        Job(
            name="job-timeout",
            cwd=str(tmp_path),
            commands=[py_hang],
            command_timeout_minutes=0.01  # 0.6 seconds
        )
    ]
    config = Config(settings=settings, jobs=jobs)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    success = run_scheduler(config)
    assert success is False

    job_log = log_dir / f"{date_str}_job-timeout.log"
    session_log = log_dir / f"{date_str}_session.log"

    assert job_log.exists()
    job_content = job_log.read_text(encoding="utf-8")
    assert "Command timed out after 0.6 seconds" in job_content

    assert session_log.exists()
    session_content = session_log.read_text(encoding="utf-8")
    assert "Command timed out after 0.6 seconds" in session_content
    assert "Job job-timeout: FAILED" in session_content


def test_runner_command_success_before_timeout(tmp_path):
    """Verify that a command completing within its timeout executes successfully."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    py_fast = f'"{sys.executable}" -c "print(\'completed fast\')"'

    jobs = [
        Job(
            name="job-fast",
            cwd=str(tmp_path),
            commands=[py_fast],
            command_timeout_minutes=0.5  # 30 seconds
        )
    ]
    config = Config(settings=settings, jobs=jobs)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    success = run_scheduler(config)
    assert success is True

    job_log = log_dir / f"{date_str}_job-fast.log"

    assert job_log.exists()
    job_content = job_log.read_text(encoding="utf-8")
    assert "completed fast" in job_content


def test_runner_command_timeout_group_termination(tmp_path):
    """Verify that on timeout, the entire process group (including grandchild processes) is terminated."""
    import os
    import time

    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    pid_file = tmp_path / "child_pid.txt"
    grandchild_path = tmp_path / "grandchild.py"
    grandchild_path.write_text(
        f"import os, time\n"
        f"open(r'{pid_file.as_posix()}', 'w').write(str(os.getpid()))\n"
        f"time.sleep(100)\n",
        encoding="utf-8")

    child_path = tmp_path / "child.py"
    child_path.write_text(
        f"import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, r'{grandchild_path.as_posix()}'])\n"
        f"time.sleep(100)\n",
        encoding="utf-8")

    py_cmd = f'"{sys.executable}" "{child_path.as_posix()}"'

    jobs = [
        Job(
            name="job-group-timeout",
            cwd=str(tmp_path),
            commands=[py_cmd],
            command_timeout_minutes=0.05  # 3 seconds timeout
        )
    ]
    config = Config(settings=settings, jobs=jobs)

    success = run_scheduler(config)
    assert success is False

    # Wait for OS process cleanup
    time.sleep(0.5)

    # Verify the grandchild process was killed
    assert pid_file.exists(
    ), "Grandchild process should have created the PID file before timeout"
    child_pid = int(pid_file.read_text().strip())

    # Check if process exists
    exists = False
    try:
        os.kill(child_pid, 0)
        exists = True
    except OSError:
        exists = False

    assert exists is False, f"Grandchild process {child_pid} should have been terminated"


def test_runner_command_false_timeout_prevention(tmp_path):
    """Verify that a command executing close to but under the timeout limit succeeds and drains cleanly."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=False, log_dir=str(log_dir))

    # Sleep 0.5s and print, with a 1.8s timeout
    py_cmd = f'"{sys.executable}" -c "import time; time.sleep(0.5); print(\'near-boundary-output\')"'

    jobs = [
        Job(
            name="job-boundary",
            cwd=str(tmp_path),
            commands=[py_cmd],
            command_timeout_minutes=0.03  # 1.8 seconds timeout
        )
    ]
    config = Config(settings=settings, jobs=jobs)

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    success = run_scheduler(config)
    assert success is True

    job_log = log_dir / f"{date_str}_job-boundary.log"
    assert job_log.exists()

    content = job_log.read_text(encoding="utf-8")
    assert "near-boundary-output" in content
    assert "Command timed out" not in content
