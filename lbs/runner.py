# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.runner – Sequential job execution and logging.
"""

from dataclasses import dataclass
import datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import threading
import time

from lbs.config import Config, Job, BuildStatus, resolve_status_path
from lbs.utils.executor import JobExecutor
from lbs.utils.lock import FileLock


@dataclass
class CommandTask:
    """Represents an individual command execution unit with its lifecycle status."""
    index: int
    phase: str
    command: str
    status: BuildStatus = BuildStatus.PENDING
    exit_code: int | None = None
    duration: float | None = None

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "phase": self.phase,
            "command": self.command,
            "status": self.status.value if isinstance(self.status, BuildStatus) else str(self.status),
            "exit_code": self.exit_code,
            "duration": round(self.duration, 4) if self.duration is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CommandTask":
        raw_status = data.get("status", BuildStatus.PENDING.value)
        try:
            status = BuildStatus(raw_status)
        except ValueError:
            status = BuildStatus.PENDING
        return cls(
            index=data.get("index", 0),
            phase=data.get("phase", "default"),
            command=data.get("command", ""),
            status=status,
            exit_code=data.get("exit_code"),
            duration=data.get("duration"),
        )


def build_job_command_tasks(job: Job) -> list[CommandTask]:
    """Builds the ordered list of CommandTasks for a job across its phases."""
    tasks = []
    idx = 0
    if job.phases:
        for phase_name, cmds in job.phases.items():
            for cmd in cmds:
                tasks.append(
                    CommandTask(
                        index=idx,
                        phase=phase_name,
                        command=cmd,
                        status=BuildStatus.PENDING,
                    )
                )
                idx += 1
    elif job.commands:
        for cmd in job.commands:
            tasks.append(
                CommandTask(
                    index=idx,
                    phase="default",
                    command=cmd,
                    status=BuildStatus.PENDING,
                )
            )
            idx += 1
    return tasks


def compute_build_status(
    tasks: list[CommandTask],
    job_build_it: bool = True,
) -> BuildStatus:
    """Computes aggregate BuildStatus from a list of command tasks."""
    if not job_build_it:
        return BuildStatus.SKIPPED
    if not tasks:
        return BuildStatus.DONE
    if any(t.status == BuildStatus.RUNNING for t in tasks):
        return BuildStatus.RUNNING
    if any(t.status == BuildStatus.FAILED for t in tasks):
        return BuildStatus.FAILED
    if all(t.status == BuildStatus.DONE for t in tasks):
        return BuildStatus.DONE
    return BuildStatus.PENDING


def _save_status(
    status_path: Path,
    config_file: str | Path | None,
    session_date: str,
    job_summaries: dict,
) -> None:
    """Save the current execution status atomically to JSON."""
    serializable_jobs = {}
    for name, info in job_summaries.items():
        raw_commands = info.get("commands", [])
        serialized_commands = []
        for cmd_item in raw_commands:
            if isinstance(cmd_item, CommandTask):
                serialized_commands.append(cmd_item.to_dict())
            elif isinstance(cmd_item, dict):
                serialized_commands.append(cmd_item)

        build_status = info.get("build_status")
        if build_status is None:
            if raw_commands and all(isinstance(c, CommandTask) for c in raw_commands):
                build_status = compute_build_status(raw_commands).value
            else:
                legacy_status = info.get("status")
                if legacy_status == "SUCCESS":
                    build_status = BuildStatus.DONE.value
                elif legacy_status in (
                    BuildStatus.FAILED.value,
                    BuildStatus.PENDING.value,
                    BuildStatus.SKIPPED.value,
                    BuildStatus.RUNNING.value,
                ):
                    build_status = legacy_status
                else:
                    build_status = BuildStatus.PENDING.value

        status_val = info.get("status", build_status)
        duration_val = info.get("duration")
        if duration_val is not None:
            duration_val = round(duration_val, 4)

        job_record = {
            "build_status": build_status if isinstance(build_status, str) else build_status.value,
            "status": status_val if isinstance(status_val, str) else status_val.value,
            "duration": duration_val,
        }
        if serialized_commands:
            job_record["commands"] = serialized_commands
        if "cwd" in info:
            job_record["cwd"] = info["cwd"]

        serializable_jobs[name] = job_record

    data = {
        "config_file": str(config_file) if config_file is not None else None,
        "session_date": session_date,
        "last_updated": datetime.datetime.now().isoformat(timespec="seconds"),
        "jobs": serializable_jobs,
    }

    status_path.parent.mkdir(parents=True, exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(
        dir=str(status_path.parent),
        prefix="lbs_status_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, str(status_path))
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise

    # If saving to default lbs_status.json (no config_file specified), also write legacy lbs_state.json for backward compatibility
    if status_path.name == "lbs_status.json":
        legacy_path = status_path.parent / "lbs_state.json"
        try:
            with open(legacy_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass


# Backward-compatible alias
_save_state = _save_status


def _parse_and_validate_resume_status(status_path: Path) -> tuple[str, dict]:
    """Loads, validates, and returns (session_date, saved_summaries)
    from the status file. If status_path does not exist, checks legacy
    lbs_status.json and lbs_state.json fallbacks in the same directory.
    """
    target_path = status_path
    if not target_path.is_file():
        fallback_status = status_path.parent / "lbs_status.json"
        fallback_legacy = status_path.parent / "lbs_state.json"
        if fallback_status.is_file():
            target_path = fallback_status
        elif fallback_legacy.is_file():
            target_path = fallback_legacy
        else:
            raise ValueError("No active session state found to resume.")

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            status_data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Failed to load session state: {e}") from e

    if not isinstance(status_data, dict):
        raise ValueError(
            "Failed to load session state: state file content is not a JSON object"
        )

    saved_summaries = status_data.get("jobs")
    if not isinstance(saved_summaries, dict):
        raise ValueError(
            "Failed to load session state: 'jobs' field is missing or not a JSON object"
        )

    session_date = status_data.get("session_date")
    if not isinstance(session_date, str):
        raise ValueError(
            "Failed to load session state: 'session_date' field is missing or not a string"
        )

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", session_date):
        raise ValueError(
            f"Failed to load session state: invalid session_date format '{session_date}'"
        )

    # Detect and reconcile stale RUNNING states (interrupted executions)
    stale_reconciled = False
    for job_name, info in saved_summaries.items():
        if not isinstance(info, dict):
            continue

        job_stale = False
        raw_commands = info.get("commands", [])
        if isinstance(raw_commands, list):
            for cmd_info in raw_commands:
                if isinstance(cmd_info, dict) and cmd_info.get("status") == BuildStatus.RUNNING.value:
                    cmd_str = cmd_info.get("command", "")
                    print(
                        f"Warning: Detected interrupted execution for job '{job_name}' "
                        f"(command: '{cmd_str}'). Reconciling stale RUNNING state to FAILED.",
                        file=sys.stderr,
                    )
                    cmd_info["status"] = BuildStatus.FAILED.value
                    job_stale = True
                    stale_reconciled = True

        status_val = info.get("status")
        build_status_val = info.get("build_status")
        if (
            status_val == BuildStatus.RUNNING.value
            or build_status_val == BuildStatus.RUNNING.value
            or job_stale
        ):
            if not job_stale:
                print(
                    f"Warning: Detected interrupted execution for job '{job_name}'. "
                    f"Reconciling stale RUNNING state to FAILED.",
                    file=sys.stderr,
                )
            info["build_status"] = BuildStatus.FAILED.value
            info["status"] = BuildStatus.FAILED.value
            stale_reconciled = True

        # Normalize jobs for backward compatibility
        if info.get("status") == "SUCCESS" and not info.get("build_status"):
            info["build_status"] = BuildStatus.DONE.value
        elif info.get("build_status") == BuildStatus.DONE.value and not info.get("status"):
            info["status"] = "SUCCESS"

    if stale_reconciled:
        temp_fd, temp_path = tempfile.mkstemp(
            dir=str(target_path.parent),
            prefix="lbs_status_reconcile_",
            suffix=".tmp",
        )
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(status_data, f, indent=2)
            os.replace(temp_path, str(target_path))
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    return session_date, saved_summaries


# Backward-compatible alias
_parse_and_validate_resume_state = _parse_and_validate_resume_status


def _print_dry_run_plan(
    config: Config,
    jobs_to_run: set[str],
    succeeded_jobs: set[str],
    resume: str | None,
    saved_summaries: dict | None = None,
    status_path: Path | None = None,
) -> None:
    """Prints the dry-run execution plan to standard output."""
    print("Dry-Run Execution Plan")
    print("======================")
    print(f"Log Directory: {config.settings.log_dir}")
    if resume == "latest":
        status_file_info = f" ({status_path.name})" if status_path else ""
        print(f"Resuming Session from latest state{status_file_info}")
    print()
    for job in config.jobs:
        if job.name not in jobs_to_run:
            continue
        if not job.build_it:
            print(f"Job: {job.name} [DISABLED]")
            print()
            continue
        if job.name in succeeded_jobs:
            print(f"Job: {job.name} [ALREADY SUCCEEDED]")
            continue

        # Handle resume command-level visualization
        if resume == "latest" and saved_summaries is not None:
            default_tasks = build_job_command_tasks(job)
            job_info = saved_summaries.get(job.name, {})
            saved_cmds = job_info.get("commands", [])
            for t in default_tasks:
                matching = next(
                    (c for c in saved_cmds
                     if isinstance(c, dict) and (c.get("index") == t.index or (c.get("command") == t.command and c.get("phase") == t.phase))),
                    None,
                )
                if matching:
                    raw_st = matching.get("status", BuildStatus.PENDING.value)
                    try:
                        t.status = BuildStatus(raw_st)
                    except ValueError:
                        t.status = BuildStatus.PENDING
                    t.duration = matching.get("duration")

            done_count = sum(1 for t in default_tasks if t.status == BuildStatus.DONE)
            total_count = len(default_tasks)
            if done_count > 0:
                print(f"Job: {job.name} [RESUMING - {done_count} of {total_count} commands completed]")
            else:
                print(f"Job: {job.name}")

            print(f"  CWD: {job.cwd}")
            env_str = (", ".join(
                f"{k}={v}" for k, v in job.env.items()) if job.env else "None")
            print(f"  Environment: {env_str}")
            if job.retries > 0:
                print(
                    f"  Retries: {job.retries} (delay: {job.retry_delay_seconds}s)"
                )
            if job.command_timeout_minutes is not None:
                print(f"  Timeout: {job.command_timeout_minutes}m")
            print("  Commands:")
            first_incomplete = True
            for t in default_tasks:
                if t.status == BuildStatus.DONE:
                    tag = "[DONE]"
                    dur_str = f" (took {t.duration:.1f}s)" if t.duration is not None else ""
                elif first_incomplete:
                    tag = "[RESUME]"
                    first_incomplete = False
                    dur_str = ""
                else:
                    tag = "[PENDING]"
                    dur_str = ""
                phase_tag = f"({t.phase})  " if t.phase != "default" else ""
                print(f"    {tag:<10}{phase_tag}{t.command}{dur_str}")
            print()
            continue

        print(f"Job: {job.name}")
        print(f"  CWD: {job.cwd}")
        env_str = (", ".join(
            f"{k}={v}" for k, v in job.env.items()) if job.env else "None")
        print(f"  Environment: {env_str}")
        if job.retries > 0:
            print(
                f"  Retries: {job.retries} (delay: {job.retry_delay_seconds}s)"
            )
        if job.command_timeout_minutes is not None:
            print(f"  Timeout: {job.command_timeout_minutes}m")
        if len(job.phases) == 1 and "default" in job.phases:
            print("  Commands:")
            for cmd in job.phases["default"]:
                print(f"    - {cmd}")
        else:
            print("  Phases:")
            for phase_name, cmds in job.phases.items():
                print(f"    [{phase_name}]")
                for cmd in cmds:
                    print(f"      - {cmd}")
        print()


def _execute_job_attempt(
    job: Job,
    verbose: bool,
    attempt: int,
    total_attempts: int,
    job_log_path: Path,
    log_to_session,
    commands: list[str] | None = None,
    phase_name: str | None = None,
    tasks: list[CommandTask] | None = None,
    on_status_change=None,
) -> bool:
    """Executes all commands of a job phase in a single attempt, logging outputs."""
    if commands is None:
        if tasks is not None:
            commands = [t.command for t in tasks]
        else:
            commands = job.commands

    job_success = True
    with open(job_log_path, "a", encoding="utf-8") as job_log:

        def log_to_job(msg: str) -> None:
            now = datetime.datetime.now()
            timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
            job_log.write(f"[{timestamp}] {msg}\n")
            job_log.flush()

        phase_suffix = f" (phase '{phase_name}')" if phase_name and phase_name != "default" else ""
        if attempt > 1:
            log_to_job(f"--- Retry Attempt {attempt - 1} / {job.retries} ---")
        else:
            log_to_job(f"Job '{job.name}'{phase_suffix} started")
            log_to_job(f"CWD: {job.cwd}")
            log_to_job(f"Environment overlays: {job.env}")

        if verbose:
            sys.stdout.write(f"\n[LBS] Executing job '{job.name}'{phase_suffix} [CWD: {job.cwd}]\n")
            sys.stdout.flush()

        # Write commands to a temp script to preserve state sequentially
        suffix = ".bat" if sys.platform == "win32" else ".sh"
        fd, temp_script_path_str = tempfile.mkstemp(suffix=suffix,
                                                    prefix="lbs_job_")
        temp_script_path = Path(temp_script_path_str)

        progress_path = None
        if tasks:
            prog_fd, prog_path_str = tempfile.mkstemp(prefix="lbs_prog_", suffix=".log")
            os.close(prog_fd)
            progress_path = Path(prog_path_str)

        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                if sys.platform == "win32":
                    f.write("@echo off\n")
                    if tasks and progress_path:
                        for i, cmd in enumerate(commands):
                            f.write(f'>>"{progress_path}" echo START:{i}\n')
                            f.write(f"{cmd}\n")
                            f.write("if %ERRORLEVEL% neq 0 (\n")
                            f.write(f'    >>"{progress_path}" echo FAIL:{i}:%ERRORLEVEL%\n')
                            f.write("    exit /b %ERRORLEVEL%\n")
                            f.write(")\n")
                            f.write(f'>>"{progress_path}" echo DONE:{i}:0\n')
                    else:
                        for cmd in commands:
                            f.write(f"{cmd}\n")
                            f.write("if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%\n")
                else:
                    f.write("#!/bin/sh\n")
                    if tasks and progress_path:
                        f.write("__lbs_current=0\n")
                        f.write(f'trap \'__lbs_rc=$?; if [ $__lbs_rc -ne 0 ]; then echo "FAIL:${{__lbs_current}}:$__lbs_rc" >> "{progress_path}"; fi\' EXIT\n')
                        f.write("set -e\n")
                        for i, cmd in enumerate(commands):
                            f.write(f"__lbs_current={i}\n")
                            f.write(f'echo "START:{i}" >> "{progress_path}"\n')
                            f.write(f"{cmd}\n")
                            f.write(f'echo "DONE:{i}:0" >> "{progress_path}"\n')
                        f.write("trap - EXIT\n")
                    else:
                        f.write("set -e\n")
                        for cmd in commands:
                            f.write(f"{cmd}\n")

            monitor_thread = None
            stop_monitor = threading.Event()
            task_start_times: dict[int, float] = {}
            last_pos = [0]

            if tasks and progress_path:
                def apply_progress_line(raw_line: str) -> None:
                    line = raw_line.strip()
                    if not line:
                        return
                    parts = line.split(":")
                    if len(parts) >= 2:
                        action = parts[0]
                        try:
                            cmd_idx = int(parts[1])
                        except ValueError:
                            return
                        if 0 <= cmd_idx < len(tasks):
                            t = tasks[cmd_idx]
                            # Idempotency guard: ignore replayed events for tasks that already reached a terminal state
                            if t.status in (BuildStatus.DONE, BuildStatus.FAILED):
                                return

                            if action == "START":
                                t.status = BuildStatus.RUNNING
                                if cmd_idx not in task_start_times:
                                    task_start_times[cmd_idx] = time.perf_counter()
                                if on_status_change:
                                    on_status_change()
                            elif action == "DONE":
                                t.status = BuildStatus.DONE
                                t.exit_code = 0
                                if cmd_idx in task_start_times and t.duration is None:
                                    t.duration = round(time.perf_counter() - task_start_times[cmd_idx], 4)
                                if on_status_change:
                                    on_status_change()
                            elif action == "FAIL":
                                t.status = BuildStatus.FAILED
                                exit_code = 1
                                if len(parts) > 2:
                                    try:
                                        exit_code = int(parts[2])
                                    except ValueError:
                                        exit_code = 1
                                t.exit_code = exit_code
                                if cmd_idx in task_start_times and t.duration is None:
                                    t.duration = round(time.perf_counter() - task_start_times[cmd_idx], 4)
                                if on_status_change:
                                    on_status_change()

                def monitor_progress() -> None:
                    while not stop_monitor.is_set():
                        if progress_path.is_file():
                            try:
                                with open(progress_path, "r", encoding="utf-8", errors="replace") as pf:
                                    pf.seek(last_pos[0])
                                    lines = pf.readlines()
                                    last_pos[0] = pf.tell()
                                    for l in lines:
                                        apply_progress_line(l)
                            except Exception:
                                pass
                        stop_monitor.wait(0.05)

                monitor_thread = threading.Thread(target=monitor_progress, daemon=True)
                monitor_thread.start()

            executor = JobExecutor(verbose=verbose)

            if sys.platform == "win32":
                run_cmd = f'"{temp_script_path.resolve()}"'
            else:
                run_cmd = f'sh "{temp_script_path.resolve()}"'

            if job.command_timeout_minutes is not None:
                timeout_sec = job.command_timeout_minutes * 60
            else:
                timeout_sec = None

            result = executor.run_command(
                run_cmd,
                cwd=job.cwd,
                env=job.env,
                log_file=job_log,
                timeout=timeout_sec,
            )

            if monitor_thread:
                stop_monitor.set()
                monitor_thread.join(timeout=1.0)
                if progress_path and progress_path.is_file():
                    try:
                        with open(progress_path, "r", encoding="utf-8", errors="replace") as pf:
                            pf.seek(last_pos[0])
                            for l in pf:
                                apply_progress_line(l)
                    except Exception:
                        pass

            if not result.success:
                if tasks:
                    for idx, t in enumerate(tasks):
                        if t.status == BuildStatus.RUNNING:
                            t.status = BuildStatus.FAILED
                            t.exit_code = result.exit_code if result.exit_code is not None else 1
                            if idx in task_start_times:
                                t.duration = round(time.perf_counter() - task_start_times[idx], 4)
                    if not any(t.status == BuildStatus.FAILED for t in tasks):
                        for idx, t in enumerate(tasks):
                            if t.status != BuildStatus.DONE:
                                t.status = BuildStatus.FAILED
                                t.exit_code = result.exit_code if result.exit_code is not None else 1
                                if idx in task_start_times:
                                    t.duration = round(time.perf_counter() - task_start_times[idx], 4)
                                break
                    if on_status_change:
                        on_status_change()

                if attempt < total_attempts:
                    status_label = "ATTEMPT FAILED"
                else:
                    status_label = "FAILED"
                phase_label = f" (phase '{phase_name}')" if phase_name and phase_name != "default" else ""
                if result.error_message:
                    log_to_job(
                        f"Process execution error: {result.error_message}")
                    log_to_session(f"Job {job.name}{phase_label}: {status_label} "
                                   f"(Command failed: {result.error_message})")
                else:
                    log_to_job(
                        f"Command failed with exit code {result.exit_code}")
                    log_to_session(f"Job {job.name}{phase_label}: {status_label} "
                                   f"(Command failed with exit code "
                                   f"{result.exit_code})")
                job_success = False
            else:
                log_to_job("Command succeeded")
        finally:
            try:
                temp_script_path.unlink()
            except OSError:
                pass
            if progress_path:
                try:
                    progress_path.unlink()
                except OSError:
                    pass

    return job_success


def _run_single_job(
    job: Job,
    verbose: bool,
    log_dir: Path,
    session_date: str,
    log_to_session,
    phase_name: str | None = None,
    commands: list[str] | None = None,
    tasks: list[CommandTask] | None = None,
    on_status_change=None,
) -> tuple[bool, float]:
    """
    Executes the commands inside a single job or phase, coordinating retries and log files.
    Does not mutate scheduler orchestration state.
    """
    if phase_name and phase_name != "default":
        job_log_path = log_dir / f"{session_date}_{job.name}_{phase_name}.log"
    else:
        job_log_path = log_dir / f"{session_date}_{job.name}.log"

    if commands is None:
        if tasks is not None:
            commands = [t.command for t in tasks]
        elif phase_name and phase_name in job.phases:
            commands = job.phases[phase_name]
        else:
            commands = job.commands

    job_success = False
    job_duration = 0.0
    total_attempts = 1 + job.retries

    for attempt in range(1, total_attempts + 1):
        job_start_time = time.perf_counter()

        job_success = _execute_job_attempt(
            job=job,
            verbose=verbose,
            attempt=attempt,
            total_attempts=total_attempts,
            job_log_path=job_log_path,
            log_to_session=log_to_session,
            commands=commands,
            phase_name=phase_name,
            tasks=tasks,
            on_status_change=on_status_change,
        )

        job_duration += time.perf_counter() - job_start_time

        if job_success:
            break
        else:
            if attempt < total_attempts:
                if tasks:
                    for t in tasks:
                        if t.status == BuildStatus.FAILED:
                            t.status = BuildStatus.PENDING
                phase_str = f" (phase '{phase_name}')" if phase_name and phase_name != "default" else ""
                log_to_session(f"Job {job.name}{phase_str} failed. Retrying in "
                               f"{job.retry_delay_seconds} seconds "
                               f"(attempt {attempt}/{job.retries})...")
                time.sleep(job.retry_delay_seconds)

    return job_success, job_duration


def _format_job_duration(dur: float | None) -> str:
    """Formats job duration as HH:MM:SS (total seconds)."""
    if dur is None:
        return "(-)"
    total_sec = int(dur)
    hours = total_sec // 3600
    minutes = (total_sec % 3600) // 60
    seconds = total_sec % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d} ({total_sec} seconds)"


def _build_summary_text(
    job_summaries: dict,
    overall_success: bool,
    elapsed_time: float,
) -> tuple[str, str, int, int, int]:
    """Constructs the formatted multi-line summary string and counts statistics."""
    summary_lines = [
        "",
        "=" * 50,
        "              LBS Session Summary",
        "=" * 50,
    ]
    for name, summary in job_summaries.items():
        status = summary["status"]
        dur = summary["duration"]
        dur_str = _format_job_duration(dur)
        summary_lines.append(f"Job: {name:<20} ->  {status:<10} {dur_str}")
    summary_lines.append("=" * 50)

    session_status = "SUCCESS" if overall_success else "FAILED"
    summary_lines.append(f"Session completed: {session_status}")
    summary_lines.append("")

    passed_count = sum(1 for s in job_summaries.values()
                       if s["status"] == "SUCCESS")
    failed_count = sum(1 for s in job_summaries.values()
                       if s["status"] == "FAILED")
    skipped_count = sum(1 for s in job_summaries.values()
                        if s["status"] in ("SKIPPED", "PENDING"))

    total_seconds = int(elapsed_time)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    summary_lines.extend([
        "Run Summary",
        "-----------",
        f"Passed: {passed_count}",
        f"Failed: {failed_count}",
        f"Skipped: {skipped_count}",
        f"Duration: {duration_str}",
        "",
    ])

    summary_text = "\n".join(summary_lines)
    return summary_text, duration_str, passed_count, failed_count, skipped_count


class Scheduler:
    """Orchestrates execution of job queues, phase filtering, and logging."""

    @staticmethod
    def run(
        config: Config,
        job_filter: list[str] | str | None = None,
        phase_filter: list[str] | str | None = None,
        dry_run: bool = False,
        resume: str | None = None,
        config_path: str | Path | None = None,
        mode: str = "phased",
    ) -> bool:
        """
        Main execution loop for LBS jobs.
        
        Creates the configured log directory, manages the session and job-specific
        log files, runs commands or phases under each job with environment overlays,
        tracks durations, and returns True if all executed jobs succeeded, or False if any failed.
        
        If job_filter is specified, only executes jobs with names in the filter.
        If phase_filter is specified, only executes phases with names in the filter.
        Raises ValueError if filters contain invalid job or phase names.
        """
        session_start_time = time.perf_counter()
        # Normalize job_filter
        if job_filter is None:
            filter_list = []
        elif isinstance(job_filter, str):
            filter_list = [job_filter]
        else:
            filter_list = list(job_filter)

        # Validate job_filter if present (before any filesystem operations)
        if filter_list:
            filter_set = set(filter_list)
            existing_names = {job.name for job in config.jobs}
            invalid_names = filter_set - existing_names
            if invalid_names:
                raise ValueError(
                    f"Job filter contains invalid job names: {', '.join(sorted(invalid_names))}"
                )
            jobs_to_run = {
                job.name
                for job in config.jobs if job.name in filter_set
            }
        else:
            jobs_to_run = {job.name for job in config.jobs}

        # Normalize and validate phase_filter
        if phase_filter is None:
            p_filter_list = []
        elif isinstance(phase_filter, str):
            p_filter_list = [phase_filter]
        else:
            p_filter_list = list(phase_filter)

        all_defined_phases = []
        for j in config.jobs:
            for p_name in j.phases.keys():
                if p_name not in all_defined_phases:
                    all_defined_phases.append(p_name)

        if p_filter_list:
            p_filter_set = set(p_filter_list)
            invalid_phases = p_filter_set - set(all_defined_phases)
            if invalid_phases:
                raise ValueError(
                    f"Phase filter contains invalid phase names: {', '.join(sorted(invalid_phases))}"
                )
            phases_to_run = [p for p in all_defined_phases if p in p_filter_set]
        else:
            phases_to_run = all_defined_phases

        # Resolve resume status if configured
        status_path = resolve_status_path(config.settings.log_dir, config_path)
        succeeded_jobs = set()
        session_date = None
        saved_summaries = {}

        if resume == "latest":
            session_date, saved_summaries = _parse_and_validate_resume_status(
                status_path)
            succeeded_jobs = {
                name
                for name, info in saved_summaries.items()
                if isinstance(info, dict) and (
                    info.get("status") == "SUCCESS"
                    or info.get("build_status") == BuildStatus.DONE.value
                )
            }

            # If all selected jobs are already succeeded:
            selected_succeeded = all(
                isinstance(saved_summaries.get(name), dict)
                and (
                    saved_summaries[name].get("status") == "SUCCESS"
                    or saved_summaries[name].get("build_status") == BuildStatus.DONE.value
                )
                for name in jobs_to_run)
            if selected_succeeded:
                print(
                    "All selected jobs in the previous session completed successfully. Nothing to resume."
                )
                return True

        if dry_run:
            _print_dry_run_plan(
                config=config,
                jobs_to_run=jobs_to_run,
                succeeded_jobs=succeeded_jobs,
                resume=resume,
                saved_summaries=saved_summaries if resume == "latest" else None,
                status_path=status_path if resume == "latest" else None,
            )
            return True

        # Initialize filesystem logs
        log_dir = Path(config.settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        lock_path = log_dir / "lbs.lock"
        with FileLock(lock_path):
            if resume == "latest":
                if session_date is None:
                    session_date = datetime.datetime.now().strftime("%Y-%m-%d")
            else:
                session_date = datetime.datetime.now().strftime("%Y-%m-%d")

            session_log_path = log_dir / f"{session_date}_session.log"

            # Reconstruct job summaries from state if resuming
            job_summaries = {}
            job_durations = {}
            job_failed = {}
            job_phase_results = {}
            job_command_tasks: dict[str, list[CommandTask]] = {}

            for job in config.jobs:
                default_tasks = build_job_command_tasks(job)
                if resume == "latest":
                    job_info = saved_summaries.get(job.name, {})
                    saved_cmds = job_info.get("commands", [])
                    if saved_cmds:
                        restored_tasks = []
                        for t in default_tasks:
                            matching = next(
                                (c for c in saved_cmds
                                 if isinstance(c, dict) and (c.get("index") == t.index or (c.get("command") == t.command and c.get("phase") == t.phase))),
                                None,
                            )
                            if matching:
                                raw_st = matching.get("status", BuildStatus.PENDING.value)
                                try:
                                    t.status = BuildStatus(raw_st)
                                except ValueError:
                                    t.status = BuildStatus.PENDING
                                t.exit_code = matching.get("exit_code")
                                t.duration = matching.get("duration")
                            restored_tasks.append(t)
                        job_command_tasks[job.name] = restored_tasks
                    else:
                        if job.name in succeeded_jobs:
                            for t in default_tasks:
                                t.status = BuildStatus.DONE
                        job_command_tasks[job.name] = default_tasks

                    if job.name in succeeded_jobs:
                        job_summaries[job.name] = {
                            "build_status": BuildStatus.DONE.value,
                            "status": "SUCCESS",
                            "duration": job_info.get("duration"),
                            "commands": job_command_tasks[job.name],
                            "cwd": job.cwd,
                        }
                    else:
                        b_status = compute_build_status(job_command_tasks[job.name], job.build_it)
                        st_val = "SUCCESS" if b_status == BuildStatus.DONE else b_status.value
                        if not job.build_it:
                            st_val = "SKIPPED"
                        job_summaries[job.name] = {
                            "build_status": b_status.value,
                            "status": st_val,
                            "duration": job_info.get("duration"),
                            "commands": job_command_tasks[job.name],
                            "cwd": job.cwd,
                        }
                else:
                    job_command_tasks[job.name] = default_tasks
                    if not job.build_it:
                        for t in default_tasks:
                            t.status = BuildStatus.SKIPPED
                    status_val = "PENDING" if (job.name in jobs_to_run and job.build_it) else "SKIPPED"
                    b_status_val = BuildStatus.PENDING.value if (job.name in jobs_to_run and job.build_it) else BuildStatus.SKIPPED.value
                    job_summaries[job.name] = {
                        "build_status": b_status_val,
                        "status": status_val,
                        "duration": None,
                        "commands": job_command_tasks[job.name],
                        "cwd": job.cwd,
                    }
                job_durations[job.name] = (job_summaries[job.name]["duration"] or 0.0)
                job_phase_results[job.name] = {}

            overall_success = True
            aborted = False

            def log_to_session(msg: str) -> None:
                timestamp = datetime.datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S")
                formatted_msg = f"[{timestamp}] {msg}\n"
                with open(session_log_path, "a", encoding="utf-8") as f:
                    f.write(formatted_msg)

            if resume == "latest":
                log_to_session("--- Session resumed ---")
            else:
                log_to_session("--- Session started ---")

            log_to_session(
                f"Settings: stop_on_failure={config.settings.stop_on_failure}, log_dir={config.settings.log_dir}"
            )

            # Save initial state if not resuming
            if resume != "latest":
                _save_status(status_path, config_path, session_date,
                             job_summaries)

            verbose_mode = getattr(config.settings, "verbose", True)
            if getattr(config.settings, "quiet", False):
                verbose_mode = False

            for job in config.jobs:
                if job.name in jobs_to_run and not job.build_it:
                    log_to_session(f"Job {job.name} is disabled. Skipping.")

            # Build execution sequence of (job, phase_name) tuples based on mode
            execution_tasks: list[tuple[Job, str]] = []
            if mode == "phased":
                for p_name in phases_to_run:
                    for job in config.jobs:
                        if job.name in jobs_to_run and job.build_it and p_name in job.phases:
                            execution_tasks.append((job, p_name))
            else:
                for job in config.jobs:
                    if job.name in jobs_to_run and job.build_it:
                        for p_name in phases_to_run:
                            if p_name in job.phases:
                                execution_tasks.append((job, p_name))

            current_phase_header = None
            for job, phase_name in execution_tasks:
                is_job_done = (
                    job_summaries[job.name].get("status") == "SUCCESS"
                    or job_summaries[job.name].get("build_status") == BuildStatus.DONE.value
                )
                if is_job_done and resume == "latest":
                    continue

                if not job.build_it:
                    continue

                if aborted:
                    if job_summaries[job.name]["status"] == "PENDING":
                        job_summaries[job.name]["status"] = "SKIPPED"
                        job_summaries[job.name]["build_status"] = BuildStatus.SKIPPED.value
                        for t in job_command_tasks[job.name]:
                            if t.status == BuildStatus.PENDING:
                                t.status = BuildStatus.SKIPPED
                    continue

                phase_tasks = [t for t in job_command_tasks[job.name] if t.phase == phase_name]
                if resume == "latest" and phase_tasks and all(t.status == BuildStatus.DONE for t in phase_tasks):
                    job_phase_results[job.name][phase_name] = True
                    continue

                cmds_to_run_tasks = [t for t in phase_tasks if t.status != BuildStatus.DONE] if resume == "latest" else phase_tasks
                if not cmds_to_run_tasks:
                    job_phase_results[job.name][phase_name] = True
                    continue

                if mode == "phased" and current_phase_header != phase_name and phase_name != "default":
                    current_phase_header = phase_name
                    log_to_session(f"--- Starting Phase: {phase_name} ---")

                phase_display = f" (phase: {phase_name})" if phase_name != "default" else ""
                log_to_session(f"Starting job: {job.name}{phase_display} (cwd: {job.cwd})")

                def status_cb():
                    b_st = compute_build_status(job_command_tasks[job.name], job.build_it)
                    job_summaries[job.name]["build_status"] = b_st.value
                    job_summaries[job.name]["status"] = "SUCCESS" if b_st == BuildStatus.DONE else b_st.value
                    _save_status(status_path, config_path, session_date, job_summaries)

                cmds_to_run_tasks[0].status = BuildStatus.RUNNING
                job_summaries[job.name]["build_status"] = BuildStatus.RUNNING.value
                job_summaries[job.name]["status"] = "RUNNING"
                _save_status(status_path, config_path, session_date, job_summaries)

                p_success, p_duration = _run_single_job(
                    job=job,
                    verbose=verbose_mode,
                    log_dir=log_dir,
                    session_date=session_date,
                    log_to_session=log_to_session,
                    phase_name=phase_name,
                    commands=[t.command for t in cmds_to_run_tasks],
                    tasks=cmds_to_run_tasks,
                    on_status_change=status_cb,
                )

                job_durations[job.name] += p_duration
                job_phase_results[job.name][phase_name] = p_success

                if p_success:
                    succ_msg = f"Job {job.name}{phase_display}: SUCCESS (took {p_duration:.2f}s)"
                    log_to_session(succ_msg)
                else:
                    overall_success = False
                    job_failed[job.name] = True
                    fail_msg = f"Job {job.name}{phase_display}: FAILED (took {p_duration:.2f}s)"
                    log_to_session(fail_msg)

                    if config.settings.stop_on_failure:
                        log_to_session(
                            "Aborting execution of subsequent jobs (stop_on_failure is enabled)"
                        )
                        aborted = True

                # Update job_summaries state for completed phases
                target_phases = [p for p in job.phases.keys() if p in phases_to_run]
                all_target_succeeded = all(
                    job_phase_results[job.name].get(p) is True for p in target_phases
                )
                any_target_failed = any(
                    job_phase_results[job.name].get(p) is False for p in target_phases
                )

                if any_target_failed:
                    job_summaries[job.name]["build_status"] = BuildStatus.FAILED.value
                    job_summaries[job.name]["status"] = "FAILED"
                    job_summaries[job.name]["duration"] = job_durations[job.name]
                elif all_target_succeeded and len(job_phase_results[job.name]) == len(target_phases):
                    job_summaries[job.name]["build_status"] = BuildStatus.DONE.value
                    job_summaries[job.name]["status"] = "SUCCESS"
                    job_summaries[job.name]["duration"] = job_durations[job.name]
                else:
                    b_st = compute_build_status(job_command_tasks[job.name], job.build_it)
                    job_summaries[job.name]["build_status"] = b_st.value
                    job_summaries[job.name]["status"] = "SUCCESS" if b_st == BuildStatus.DONE else b_st.value
                    job_summaries[job.name]["duration"] = job_durations[job.name]

                _save_status(status_path, config_path, session_date, job_summaries)

            elapsed_time = time.perf_counter() - session_start_time
            (
                summary_text,
                duration_str,
                passed_count,
                failed_count,
                skipped_count,
            ) = _build_summary_text(
                job_summaries=job_summaries,
                overall_success=overall_success,
                elapsed_time=elapsed_time,
            )
            session_status = "SUCCESS" if overall_success else "FAILED"

            print(summary_text)

            with open(session_log_path, "a", encoding="utf-8") as f:
                f.write(summary_text)

            log_to_session(f"--- Session ended (status: {session_status}) ---")

            # Dispatch notification callbacks
            from lbs.utils.notifier import dispatch_notifications
            dispatch_notifications(
                settings=config.settings,
                success=overall_success,
                passed_count=passed_count,
                failed_count=failed_count,
                skipped_count=skipped_count,
                duration_str=duration_str,
                job_summaries=job_summaries,
            )

            return overall_success


def run_scheduler(config: Config) -> bool:
    """
    Deprecated: use Scheduler.run(config) instead.
    Main sequential execution loop for LBS jobs.
    """
    return Scheduler.run(config)
