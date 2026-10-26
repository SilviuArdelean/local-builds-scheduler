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
from lbs.config import Config, Settings, Job, BuildStatus
from lbs.runner import (
    run_scheduler,
    CommandTask,
    build_job_command_tasks,
    compute_build_status,
)


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
    assert "job-two              ->  ABORTED    (never started)" in session_content
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
    assert "job-two              ->  DISABLED   (build_it: false)" in session_log_content
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


def test_command_task_serialization():
    """Verify CommandTask dict conversion and roundtrip parsing."""
    task = CommandTask(
        index=2,
        phase="build",
        command="python3 build.py",
        status=BuildStatus.DONE,
        exit_code=0,
        duration=12.34567,
    )
    d = task.to_dict()
    assert d == {
        "index": 2,
        "phase": "build",
        "command": "python3 build.py",
        "status": "DONE",
        "exit_code": 0,
        "duration": 12.3457,
    }

    restored = CommandTask.from_dict(d)
    assert restored.index == 2
    assert restored.phase == "build"
    assert restored.command == "python3 build.py"
    assert restored.status == BuildStatus.DONE
    assert restored.exit_code == 0
    assert restored.duration == 12.3457

    # Test fallback on invalid status
    invalid_data = {"status": "INVALID_STATE", "command": "echo test"}
    fallback_task = CommandTask.from_dict(invalid_data)
    assert fallback_task.status == BuildStatus.PENDING


def test_build_job_command_tasks(tmp_path):
    """Verify building ordered command tasks for flat commands and phased jobs."""
    # 1. Flat commands
    job_flat = Job(
        name="flat-job",
        cwd=str(tmp_path),
        commands=["echo 1", "echo 2"],
    )
    tasks_flat = build_job_command_tasks(job_flat)
    assert len(tasks_flat) == 2
    assert tasks_flat[0].index == 0
    assert tasks_flat[0].phase == "default"
    assert tasks_flat[0].command == "echo 1"
    assert tasks_flat[0].status == BuildStatus.PENDING
    assert tasks_flat[1].index == 1
    assert tasks_flat[1].command == "echo 2"

    # 2. Phased commands
    job_phased = Job(
        name="phased-job",
        cwd=str(tmp_path),
        phases={
            "sync": ["fetch_sources"],
            "build": ["configure", "compile"],
        },
    )
    tasks_phased = build_job_command_tasks(job_phased)
    assert len(tasks_phased) == 3
    assert [(t.index, t.phase, t.command) for t in tasks_phased] == [
        (0, "sync", "fetch_sources"),
        (1, "build", "configure"),
        (2, "build", "compile"),
    ]
    assert all(t.status == BuildStatus.PENDING for t in tasks_phased)


def test_compute_build_status():
    """Verify computing aggregate BuildStatus from command tasks list."""
    # 1. Disabled job
    assert compute_build_status([], job_build_it=False) == BuildStatus.SKIPPED

    # 2. Empty tasks list
    assert compute_build_status([], job_build_it=True) == BuildStatus.DONE

    # 3. All pending
    t0 = CommandTask(index=0,
                     phase="build",
                     command="cmd0",
                     status=BuildStatus.PENDING)
    t1 = CommandTask(index=1,
                     phase="build",
                     command="cmd1",
                     status=BuildStatus.PENDING)
    assert compute_build_status([t0, t1]) == BuildStatus.PENDING

    # 4. In progress (RUNNING)
    t0.status = BuildStatus.DONE
    t1.status = BuildStatus.RUNNING
    assert compute_build_status([t0, t1]) == BuildStatus.RUNNING

    # 5. Failed
    t1.status = BuildStatus.FAILED
    assert compute_build_status([t0, t1]) == BuildStatus.FAILED

    # 6. All Done
    t1.status = BuildStatus.DONE
    assert compute_build_status([t0, t1]) == BuildStatus.DONE


def test_summary_distinguishes_job_lifecycle_states():
    """Ticket 5: summary table separates PARTIAL, FAILED, ABORTED and DISABLED jobs."""
    from lbs.runner import _build_summary_text

    def tasks(*specs):
        return [
            CommandTask(index=i, phase=p, command=f"cmd{i}", status=s)
            for i, (p, s) in enumerate(specs)
        ]

    job_summaries = {
        "client-repo": {
            "status":
            "PARTIAL",
            "duration":
            1935.0,
            "commands":
            tasks(("sync", BuildStatus.DONE), ("build", BuildStatus.SKIPPED)),
        },
        "server-repo": {
            "status":
            "FAILED",
            "duration":
            250.0,
            "commands":
            tasks(("sync", BuildStatus.DONE), ("build", BuildStatus.FAILED)),
        },
        "integration-tests": {
            "status": "ABORTED",
            "duration": None,
            "commands": tasks(("default", BuildStatus.SKIPPED)),
        },
        "legacy-tool": {
            "status": "DISABLED",
            "duration": None,
            "commands": tasks(("default", BuildStatus.SKIPPED)),
        },
    }

    text, _, passed, failed, skipped = _build_summary_text(
        job_summaries, False, 10.0)

    assert "PARTIAL    (1/2 phases complete)" in text
    assert "FAILED     (phase 'build')" in text
    assert "ABORTED    (never started)" in text
    assert "DISABLED   (build_it: false)" in text
    assert (passed, failed, skipped) == (0, 1, 3)


def test_runner_partial_job_when_other_job_aborts_run(tmp_path):
    """Ticket 5: a job that finished its first phase is PARTIAL, not SKIPPED,
    when another job's failure aborts the rest of the run."""
    log_dir = tmp_path / "logs"
    settings = Settings(stop_on_failure=True, log_dir=str(log_dir))

    py_ok = f'"{sys.executable}" -c "print(1)"'
    py_fail = f'"{sys.executable}" -c "import sys; sys.exit(1)"'

    jobs = [
        Job(name="job-a",
            cwd=str(tmp_path),
            phases={
                "sync": [py_ok],
                "build": [py_ok]
            }),
        Job(name="job-b",
            cwd=str(tmp_path),
            phases={
                "sync": [py_fail],
                "build": [py_ok]
            }),
    ]
    config = Config(settings=settings, jobs=jobs)

    assert run_scheduler(config) is False

    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    content = (log_dir / f"{date_str}_session.log").read_text(encoding="utf-8")
    assert "job-a                ->  PARTIAL    (1/2 phases complete)" in content
    assert "job-b                ->  FAILED     (phase 'sync')" in content


def test_queue_progress_reporter_quiet_bar_rendering():
    """Ticket 10: In quiet mode with a TTY, renders live in-place updating single-line bar."""
    import io
    import time
    from lbs.runner import _QueueProgressReporter, CommandTask

    stream = io.StringIO()
    reporter = _QueueProgressReporter(
        total_jobs=3,
        total_commands=6,
        session_start_time=time.perf_counter(),
        is_quiet=True,
        stream=stream,
        force_tty=True,
    )

    job = Job(name="build-debug", cwd=".")
    tasks = [
        CommandTask(index=0, phase="compile", command="compile 1"),
        CommandTask(index=1, phase="compile", command="compile 2"),
    ]

    reporter.start_phase(
        job=job,
        phase_name="compile",
        cmds_to_run_tasks=tasks,
        log_path="logs/build-debug.log",
        job_idx=2,
    )

    val = stream.getvalue()
    assert "\r" in val
    assert "[LBS]" in val
    assert "[2/3]" in val
    assert "'build-debug'" in val
    assert "compile" in val
    assert "Elapsed:" in val

    # Simulate command 1 completing and command 2 running
    tasks[0].status = BuildStatus.DONE
    tasks[1].status = BuildStatus.RUNNING
    job_cmd_tasks = {"build-debug": tasks}
    reporter.on_command_update(job_cmd_tasks)

    val2 = stream.getvalue()
    assert "2/2" in val2


def test_queue_progress_reporter_milestone_divider():
    """Ticket 10: In verbose mode, outputs milestone dividers between jobs/phases."""
    import io
    from lbs.runner import _QueueProgressReporter, CommandTask

    stream = io.StringIO()
    reporter = _QueueProgressReporter(
        total_jobs=2,
        total_commands=4,
        session_start_time=100.0,
        is_quiet=False,
        stream=stream,
        force_tty=True,
    )

    job = Job(name="test-job", cwd=".")
    tasks = [CommandTask(index=0, phase="build", command="make")]

    reporter.start_phase(
        job=job,
        phase_name="build",
        cmds_to_run_tasks=tasks,
        log_path="logs/test-job.log",
        job_idx=1,
    )

    val = stream.getvalue()
    assert "Queue Progress:" in val
    assert "Now starting: 'test-job' (phase: build)" in val
    assert "Active log: logs/test-job.log" in val


def test_queue_progress_reporter_window_title_updates():
    """Ticket 10: Emits ANSI OSC 0 escape sequences to update window/tab title on TTY."""
    import io
    from lbs.runner import _QueueProgressReporter, CommandTask

    stream = io.StringIO()
    reporter = _QueueProgressReporter(
        total_jobs=4,
        total_commands=10,
        session_start_time=100.0,
        is_quiet=True,
        stream=stream,
        force_tty=True,
    )

    job = Job(name="neo-debug", cwd=".")
    tasks = [CommandTask(index=0, phase="sync", command="git fetch")]

    reporter.start_phase(
        job=job,
        phase_name="sync",
        cmds_to_run_tasks=tasks,
        log_path="logs/neo.log",
        job_idx=3,
    )

    val = stream.getvalue()
    assert "\033]0;[3/4] (0%) LBS: neo-debug (sync)\007" in val

    reporter.finish(True)
    assert "\033]0;LBS: Session SUCCESS\007" in stream.getvalue()


def test_queue_progress_reporter_non_tty_degradation():
    """Ticket 10: Disables ANSI OSC escape sequences and \\r bar when not a TTY."""
    import io
    from lbs.runner import _QueueProgressReporter, CommandTask

    stream = io.StringIO()
    reporter = _QueueProgressReporter(
        total_jobs=2,
        total_commands=4,
        session_start_time=100.0,
        is_quiet=True,
        stream=stream,
        force_tty=False,
    )

    job = Job(name="job-pipe", cwd=".")
    tasks = [CommandTask(index=0, phase="default", command="test")]

    reporter.start_phase(
        job=job,
        phase_name="default",
        cmds_to_run_tasks=tasks,
        log_path="logs/pipe.log",
        job_idx=1,
    )

    val = stream.getvalue()
    # No ANSI escape sequence
    assert "\033]0;" not in val
    # No \\r in quiet mode when non-TTY
    assert "\r" not in val


def test_queue_progress_reporter_safe_chars_fallback():
    """Ticket 10: Falls back to ASCII chars (#, -, =) if stream cannot encode Unicode."""
    import io
    from lbs.runner import _QueueProgressReporter

    class AsciiStream(io.StringIO):
        encoding = "ascii"

    stream = AsciiStream()
    reporter = _QueueProgressReporter(
        total_jobs=2,
        total_commands=4,
        session_start_time=100.0,
        is_quiet=False,
        stream=stream,
        force_tty=True,
    )

    fill_ch, empty_ch, div_ch = reporter._safe_chars()
    assert fill_ch == "#"
    assert empty_ch == "-"
    assert div_ch == "="


def test_queue_progress_reporter_end_phase_frozen_badge():
    """Ticket 10: In quiet mode, prints frozen badge line when phase finishes."""
    import io
    from lbs.runner import _QueueProgressReporter

    stream = io.StringIO()
    reporter = _QueueProgressReporter(
        total_jobs=1,
        total_commands=2,
        session_start_time=100.0,
        is_quiet=True,
        stream=stream,
        force_tty=True,
    )

    reporter.end_phase(
        job_name="clean-build",
        phase_name="default",
        success=True,
        duration=72.0,
        is_last_phase=True,
    )

    val = stream.getvalue()
    assert "[LBS] [PASS] 'clean-build' completed in 00:01:12\n" in val


def test_scheduler_quiet_and_verbose_progress_integration(tmp_path):
    """Ticket 10: Scheduler.run executes cleanly with progress reporting in quiet and verbose modes."""
    log_dir = tmp_path / "logs"
    py_cmd = f'"{sys.executable}" -c "print(\'running\')"'

    # 1. Test quiet mode
    settings_quiet = Settings(stop_on_failure=False,
                              log_dir=str(log_dir),
                              quiet=True)
    jobs = [
        Job(name="job-q1", cwd=str(tmp_path), commands=[py_cmd]),
        Job(name="job-q2", cwd=str(tmp_path), commands=[py_cmd]),
    ]
    config_quiet = Config(settings=settings_quiet, jobs=jobs)
    assert run_scheduler(config_quiet) is True

    # 2. Test verbose mode
    settings_verbose = Settings(stop_on_failure=False,
                                log_dir=str(log_dir),
                                verbose=True)
    jobs_v = [
        Job(name="job-v1",
            cwd=str(tmp_path),
            phases={
                "sync": [py_cmd],
                "build": [py_cmd]
            }),
    ]
    config_verbose = Config(settings=settings_verbose, jobs=jobs_v)
    assert run_scheduler(config_verbose) is True


def test_queue_progress_reporter_split_screen_enable_disable():
    """Ticket 10: Verifies 75%/25% split-screen DECSTBM scrolling regions and restoration."""
    import io
    from lbs.runner import _QueueProgressReporter

    stream = io.StringIO()
    reporter = _QueueProgressReporter(
        total_jobs=3,
        total_commands=6,
        session_start_time=100.0,
        is_quiet=False,
        stream=stream,
        force_tty=True,
    )

    reporter.enable_split_screen()
    assert reporter.split_active is True
    val = stream.getvalue()
    # Check that DECSTBM scrolling region is set (e.g. \033[1;...r)
    assert f"\033[1;{reporter.scroll_end}r" in val
    assert "\033[1;1H" in val

    # Test clean disable and full-margin restoration
    reporter.disable_split_screen()
    assert reporter.split_active is False
    val2 = stream.getvalue()
    # Check that margins reset to full screen (\033[r)
    assert "\033[r" in val2


def test_queue_progress_reporter_split_screen_dashboard_render():
    """Ticket 10: Verifies that split-screen dashboard paints to bottom rows with cursor restore."""
    import io
    import time
    from lbs.runner import _QueueProgressReporter, CommandTask

    stream = io.StringIO()
    reporter = _QueueProgressReporter(
        total_jobs=2,
        total_commands=4,
        session_start_time=time.perf_counter(),
        is_quiet=False,
        stream=stream,
        force_tty=True,
    )

    reporter.enable_split_screen()
    job = Job(name="build-app", cwd=".")
    tasks = [
        CommandTask(index=0,
                    phase="compile",
                    command="python3 build.py --shared"),
        CommandTask(index=1, phase="compile", command="python3 package.py"),
    ]

    reporter.start_phase(
        job=job,
        phase_name="compile",
        cmds_to_run_tasks=tasks,
        log_path="logs/build-app.log",
        job_idx=1,
    )

    val = stream.getvalue()
    # Hides cursor and saves cursor position
    assert "\033[?25l" in val
    assert "\033[s" in val or "\0337" in val
    # Writes to row status_start
    assert f"\033[{reporter.status_start};1H" in val
    # Restores cursor and shows cursor
    assert "\033[u" in val or "\0338" in val
    assert "\033[?25h" in val

    # Contains expected dashboard fields
    assert "'build-app'" in val
    assert "Active:" in val
    assert "Elapsed:" in val


def test_queue_progress_reporter_split_screen_disabled_in_quiet_and_non_tty():
    """Ticket 10: Split-screen is not enabled in quiet mode or non-TTY pipes."""
    import io
    from lbs.runner import _QueueProgressReporter

    # 1. Non-TTY
    stream_non_tty = io.StringIO()
    reporter1 = _QueueProgressReporter(
        total_jobs=2,
        total_commands=4,
        session_start_time=100.0,
        is_quiet=False,
        stream=stream_non_tty,
        force_tty=False,
    )
    reporter1.enable_split_screen()
    assert reporter1.split_active is False
    assert "\033[1;" not in stream_non_tty.getvalue()

    # 2. Quiet mode
    stream_quiet = io.StringIO()
    reporter2 = _QueueProgressReporter(
        total_jobs=2,
        total_commands=4,
        session_start_time=100.0,
        is_quiet=True,
        stream=stream_quiet,
        force_tty=True,
    )
    reporter2.enable_split_screen()
    assert reporter2.split_active is False
