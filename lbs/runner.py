# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.runner – Sequential job execution and logging.
"""

from dataclasses import dataclass
import datetime
import hashlib
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


class ResumeStatus(tuple):
    """A 2-tuple of (session_date, saved_summaries) with config_hash metadata."""
    config_hash: str | None = None

    def __new__(
        cls,
        session_date: str,
        saved_summaries: dict,
        config_hash: str | None = None,
    ):
        instance = super().__new__(cls, (session_date, saved_summaries))
        instance.config_hash = config_hash
        return instance


class SavedJobSummaries(dict):
    """Job summaries dictionary carrying optional config_hash metadata."""
    config_hash: str | None = None


def _canonicalize_job_config(job: Job) -> dict:
    """Extracts a canonical dictionary representation of a Job specification."""
    tasks = build_job_command_tasks(job)
    return {
        "name": job.name,
        "cwd": str(job.cwd),
        "commands": [{"phase": t.phase, "command": t.command} for t in tasks],
        "env": dict(sorted(job.env.items())) if job.env else {},
        "build_it": job.build_it,
    }


def _canonicalize_summary_entry(name: str, info: dict) -> dict | None:
    """Extracts a canonical dictionary representation of a saved job summary."""
    if not isinstance(info, dict):
        return None
    cmds = []
    for c in info.get("commands", []):
        if isinstance(c, CommandTask):
            cmds.append({"phase": c.phase, "command": c.command})
        elif isinstance(c, dict):
            cmds.append({
                "phase": c.get("phase", "default"),
                "command": c.get("command", ""),
            })
    return {
        "name": name,
        "cwd": str(info.get("cwd", "")),
        "commands": cmds,
    }


def compute_config_hash(target: Config | list[Job] | dict | None) -> str:
    """Computes a deterministic SHA-256 hash of job configurations (names, cwds,
    phases/commands, env, and build_it flags) to detect configuration drift.
    """
    if target is None:
        return ""

    if isinstance(target, Config):
        canonical_jobs = [_canonicalize_job_config(j) for j in target.jobs]
    elif isinstance(target, list):
        canonical_jobs = [_canonicalize_job_config(j) for j in target]
    elif isinstance(target, dict):
        entries = (
            _canonicalize_summary_entry(name, target[name])
            for name in sorted(target.keys())
        )
        canonical_jobs = [e for e in entries if e is not None]
    else:
        return ""

    raw_bytes = json.dumps(canonical_jobs, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


def _serialize_command_list(raw_commands: list) -> list[dict]:
    """Converts a list of CommandTask instances or dicts into plain dicts."""
    serialized = []
    for cmd_item in raw_commands:
        if isinstance(cmd_item, CommandTask):
            serialized.append(cmd_item.to_dict())
        elif isinstance(cmd_item, dict):
            serialized.append(cmd_item)
    return serialized


def _resolve_job_build_status(info: dict, raw_commands: list) -> str:
    """Derives a normalized build_status string from job metadata or command tasks."""
    build_status = info.get("build_status")
    if build_status is not None:
        return build_status if isinstance(build_status, str) else build_status.value

    if raw_commands and all(isinstance(c, CommandTask) for c in raw_commands):
        return compute_build_status(raw_commands).value

    legacy_status = info.get("status")
    if legacy_status == "SUCCESS":
        return BuildStatus.DONE.value
    if legacy_status in (
        BuildStatus.FAILED.value,
        BuildStatus.PENDING.value,
        BuildStatus.SKIPPED.value,
        BuildStatus.RUNNING.value,
    ):
        return legacy_status
    return BuildStatus.PENDING.value


def _compute_commands_hash(serialized_commands: list[dict]) -> str:
    """Computes a SHA-256 digest of serialized command items for a job."""
    cmd_repr = [
        {"phase": c.get("phase", "default"), "command": c.get("command", "")}
        for c in serialized_commands
        if isinstance(c, dict)
    ]
    raw_bytes = json.dumps(cmd_repr, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


def _serialize_job_summary(info: dict) -> dict:
    """Serializes a single job summary dictionary for status persistence."""
    raw_commands = info.get("commands", [])
    serialized_commands = _serialize_command_list(raw_commands)
    build_status_str = _resolve_job_build_status(info, raw_commands)

    status_val = info.get("status", build_status_str)
    duration_val = info.get("duration")
    if duration_val is not None:
        duration_val = round(duration_val, 4)

    job_record = {
        "build_status": build_status_str,
        "status": status_val if isinstance(status_val, str) else status_val.value,
        "duration": duration_val,
    }
    if serialized_commands:
        job_record["commands"] = serialized_commands
        job_record["config_hash"] = _compute_commands_hash(serialized_commands)
    if "cwd" in info:
        job_record["cwd"] = info["cwd"]

    return job_record


def _save_status(
    status_path: Path,
    config_file: str | Path | None,
    session_date: str,
    job_summaries: dict,
    config_hash: str | None = None,
) -> None:
    """Save the current execution status atomically to JSON."""
    serializable_jobs = {
        name: _serialize_job_summary(info)
        for name, info in job_summaries.items()
    }

    if config_hash is None:
        config_hash = compute_config_hash(job_summaries)

    data = {
        "config_file": str(config_file) if config_file is not None else None,
        "config_hash": config_hash,
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


def _reconcile_stale_running_status(
    target_path: Path,
    status_data: dict,
    saved_summaries: dict,
) -> bool:
    """Detects and reconciles stale RUNNING states (from interrupted runs) to FAILED."""
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

    return stale_reconciled


def _parse_and_validate_resume_status(
    status_path: Path,
) -> tuple[str, dict]:
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

    _reconcile_stale_running_status(target_path, status_data, saved_summaries)

    config_hash = status_data.get("config_hash")
    wrapped_summaries = SavedJobSummaries(saved_summaries)
    wrapped_summaries.config_hash = config_hash

    return ResumeStatus(session_date, wrapped_summaries, config_hash=config_hash)


# Backward-compatible alias
_parse_and_validate_resume_state = _parse_and_validate_resume_status


def _find_matching_saved_command(
    task: CommandTask,
    saved_cmds: list[dict],
    consumed_indices: set[int],
) -> dict | None:
    """Finds the first unconsumed saved command matching (phase, command)."""
    for idx, c in enumerate(saved_cmds):
        if idx in consumed_indices or not isinstance(c, dict):
            continue
        if c.get("phase", "default") == task.phase and c.get("command") == task.command:
            consumed_indices.add(idx)
            return c
    return None


def _apply_saved_command_status(task: CommandTask, matching: dict | None) -> None:
    """Overlays saved execution status, exit code, and duration onto a task."""
    if matching is not None:
        raw_st = matching.get("status", BuildStatus.PENDING.value)
        try:
            task.status = BuildStatus(raw_st)
        except ValueError:
            task.status = BuildStatus.PENDING
        task.exit_code = matching.get("exit_code")
        task.duration = matching.get("duration")
    else:
        task.status = BuildStatus.PENDING
        task.exit_code = None
        task.duration = None


def _restore_job_command_tasks(job: Job, saved_cmds: list[dict]) -> list[CommandTask]:
    """Reconstructs and overlays saved command statuses onto the job's command tasks
    using strict command identity (phase, command).

    Commands are matched by (phase, command). When multiple identical commands
    exist within the same phase, they are matched sequentially. Any command
    that cannot be matched unambiguously retains BuildStatus.PENDING.
    """
    default_tasks = build_job_command_tasks(job)
    if not saved_cmds:
        return default_tasks

    consumed_indices: set[int] = set()
    for task in default_tasks:
        matching = _find_matching_saved_command(task, saved_cmds, consumed_indices)
        _apply_saved_command_status(task, matching)
    return default_tasks


def _print_dry_run_job_metadata(job: Job) -> None:
    """Prints standard CWD, environment, retry, and timeout metadata for a job."""
    print(f"  CWD: {job.cwd}")
    env_str = ", ".join(f"{k}={v}" for k, v in job.env.items()) if job.env else "None"
    print(f"  Environment: {env_str}")
    if job.retries > 0:
        print(f"  Retries: {job.retries} (delay: {job.retry_delay_seconds}s)")
    if job.command_timeout_minutes is not None:
        print(f"  Timeout: {job.command_timeout_minutes}m")


def _print_dry_run_resume_commands(tasks: list[CommandTask]) -> None:
    """Prints command tasks with [DONE], [RESUME], or [PENDING] tags."""
    print("  Commands:")
    first_incomplete = True

    for t in tasks:
        dur_str = ""
        if t.status == BuildStatus.DONE:
            tag = "[DONE]"
            dur_str = f" (took {t.duration:.1f}s)" if t.duration is not None else ""
        elif first_incomplete:
            tag = "[RESUME]"
            first_incomplete = False
        else:
            tag = "[PENDING]"

        phase_tag = f"({t.phase})  " if t.phase != "default" else ""
        print(f"    {tag:<10}{phase_tag}{t.command}{dur_str}")


def _print_dry_run_standard_commands(job: Job) -> None:
    """Prints command list or phases for a normal dry-run execution."""
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

        if resume == "latest" and saved_summaries is not None:
            job_info = saved_summaries.get(job.name, {})
            saved_cmds = job_info.get("commands", [])
            tasks = _restore_job_command_tasks(job, saved_cmds)
            done_count = sum(1 for t in tasks if t.status == BuildStatus.DONE)
            total_count = len(tasks)
            if done_count > 0:
                print(f"Job: {job.name} [RESUMING - {done_count} of {total_count} commands completed]")
            else:
                print(f"Job: {job.name}")

            _print_dry_run_job_metadata(job)
            _print_dry_run_resume_commands(tasks)
            print()
            continue

        print(f"Job: {job.name}")
        _print_dry_run_job_metadata(job)
        _print_dry_run_standard_commands(job)
        print()


def _generate_job_script(
    commands: list[str],
    tasks: list[CommandTask] | None,
    progress_path: Path | None,
    is_win: bool,
) -> str:
    """Generates the shell or batch script content with progress event emissions."""
    lines: list[str] = []
    if is_win:
        lines.append("@echo off\n")
        if tasks and progress_path:
            for i, cmd in enumerate(commands):
                lines.append(f'>>"{progress_path}" echo START:{i}\n')
                lines.append(f"{cmd}\n")
                lines.append("if %ERRORLEVEL% neq 0 (\n")
                lines.append(f'    >>"{progress_path}" echo FAIL:{i}:%ERRORLEVEL%\n')
                lines.append("    exit /b %ERRORLEVEL%\n")
                lines.append(")\n")
                lines.append(f'>>"{progress_path}" echo DONE:{i}:0\n')
        else:
            for cmd in commands:
                lines.append(f"{cmd}\n")
                lines.append("if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%\n")
    else:
        lines.append("#!/bin/sh\n")
        if tasks and progress_path:
            lines.append("__lbs_current=0\n")
            lines.append(
                f'trap \'__lbs_rc=$?; if [ $__lbs_rc -ne 0 ]; then echo "FAIL:${{__lbs_current}}:$__lbs_rc" >> "{progress_path}"; fi\' EXIT\n'
            )
            lines.append("set -e\n")
            for i, cmd in enumerate(commands):
                lines.append(f"__lbs_current={i}\n")
                lines.append(f'echo "START:{i}" >> "{progress_path}"\n')
                lines.append(f"{cmd}\n")
                lines.append(f'echo "DONE:{i}:0" >> "{progress_path}"\n')
            lines.append("trap - EXIT\n")
        else:
            lines.append("set -e\n")
            for cmd in commands:
                lines.append(f"{cmd}\n")
    return "".join(lines)


class _JobProgressMonitor:
    """Monitors per-command progress in the background and updates tasks idempotently."""

    def __init__(
        self,
        tasks: list[CommandTask],
        progress_path: Path,
        on_status_change=None,
    ) -> None:
        self.tasks = tasks
        self.progress_path = progress_path
        self.on_status_change = on_status_change
        self.stop_event = threading.Event()
        self.task_start_times: dict[int, float] = {}
        self.last_pos = 0
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop_and_drain(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1.0)
        self._drain()

    def _drain(self) -> None:
        if self.progress_path.is_file():
            try:
                with open(self.progress_path, "r", encoding="utf-8", errors="replace") as pf:
                    pf.seek(self.last_pos)
                    lines = pf.readlines()
                    self.last_pos = pf.tell()
                    for line in lines:
                        self.apply_line(line)
            except Exception:
                pass

    def _monitor_loop(self) -> None:
        while not self.stop_event.is_set():
            self._drain()
            self.stop_event.wait(0.05)

    def apply_line(self, raw_line: str) -> None:
        line = raw_line.strip()
        if not line:
            return
        parts = line.split(":")
        if len(parts) < 2:
            return
        action = parts[0]
        try:
            cmd_idx = int(parts[1])
        except ValueError:
            return
        if not (0 <= cmd_idx < len(self.tasks)):
            return

        t = self.tasks[cmd_idx]
        # Idempotency guard: ignore replayed events for tasks that already reached a terminal state
        if t.status in (BuildStatus.DONE, BuildStatus.FAILED):
            return

        if action == "START":
            t.status = BuildStatus.RUNNING
            if cmd_idx not in self.task_start_times:
                self.task_start_times[cmd_idx] = time.perf_counter()
            if self.on_status_change:
                self.on_status_change()
        elif action == "DONE":
            t.status = BuildStatus.DONE
            t.exit_code = 0
            if cmd_idx in self.task_start_times and t.duration is None:
                t.duration = round(time.perf_counter() - self.task_start_times[cmd_idx], 4)
            if self.on_status_change:
                self.on_status_change()
        elif action == "FAIL":
            t.status = BuildStatus.FAILED
            exit_code = 1
            if len(parts) > 2:
                try:
                    exit_code = int(parts[2])
                except ValueError:
                    exit_code = 1
            t.exit_code = exit_code
            if cmd_idx in self.task_start_times and t.duration is None:
                t.duration = round(time.perf_counter() - self.task_start_times[cmd_idx], 4)
            if self.on_status_change:
                self.on_status_change()


def _reconcile_attempt_failure(
    tasks: list[CommandTask],
    exit_code: int | None,
    task_start_times: dict[int, float],
    on_status_change=None,
) -> None:
    """Reconciles RUNNING or unstarted tasks to FAILED when the job execution script exits non-zero."""
    for idx, t in enumerate(tasks):
        if t.status == BuildStatus.RUNNING:
            t.status = BuildStatus.FAILED
            t.exit_code = exit_code if exit_code is not None else 1
            if idx in task_start_times and t.duration is None:
                t.duration = round(time.perf_counter() - task_start_times[idx], 4)
    if not any(t.status == BuildStatus.FAILED for t in tasks):
        for idx, t in enumerate(tasks):
            if t.status != BuildStatus.DONE:
                t.status = BuildStatus.FAILED
                t.exit_code = exit_code if exit_code is not None else 1
                if idx in task_start_times and t.duration is None:
                    t.duration = round(time.perf_counter() - task_start_times[idx], 4)
                break
    if on_status_change:
        on_status_change()


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

        is_win = sys.platform == "win32"
        suffix = ".bat" if is_win else ".sh"
        fd, temp_script_path_str = tempfile.mkstemp(suffix=suffix, prefix="lbs_job_")
        temp_script_path = Path(temp_script_path_str)

        progress_path = None
        if tasks:
            prog_fd, prog_path_str = tempfile.mkstemp(prefix="lbs_prog_", suffix=".log")
            os.close(prog_fd)
            progress_path = Path(prog_path_str)

        monitor: _JobProgressMonitor | None = None
        try:
            script_content = _generate_job_script(commands, tasks, progress_path, is_win)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(script_content)

            if tasks and progress_path:
                monitor = _JobProgressMonitor(tasks, progress_path, on_status_change)
                monitor.start()

            executor = JobExecutor(verbose=verbose)
            run_cmd = f'"{temp_script_path.resolve()}"' if is_win else f'sh "{temp_script_path.resolve()}"'
            timeout_sec = job.command_timeout_minutes * 60 if job.command_timeout_minutes is not None else None

            result = executor.run_command(
                run_cmd,
                cwd=job.cwd,
                env=job.env,
                log_file=job_log,
                timeout=timeout_sec,
            )

            if monitor:
                monitor.stop_and_drain()

            if not result.success:
                if tasks and monitor:
                    _reconcile_attempt_failure(tasks, result.exit_code, monitor.task_start_times, on_status_change)

                status_label = "ATTEMPT FAILED" if attempt < total_attempts else "FAILED"
                phase_label = f" (phase '{phase_name}')" if phase_name and phase_name != "default" else ""
                if result.error_message:
                    log_to_job(f"Process execution error: {result.error_message}")
                    log_to_session(f"Job {job.name}{phase_label}: {status_label} (Command failed: {result.error_message})")
                else:
                    log_to_job(f"Command failed with exit code {result.exit_code}")
                    log_to_session(f"Job {job.name}{phase_label}: {status_label} (Command failed with exit code {result.exit_code})")
                job_success = False
            else:
                log_to_job("Command succeeded")
        finally:
            if monitor:
                monitor.stop_and_drain()
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
                       if s["status"] in ("FAILED", "INTERRUPTED"))
    skipped_count = sum(1 for s in job_summaries.values()
                        if s["status"] in ("SKIPPED", "PENDING"))

    total_seconds = int(elapsed_time)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    duration_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    summary_counts = [
        "Run Summary",
        "-----------",
        f"Passed: {passed_count}",
        f"Failed: {failed_count}",
        f"Skipped: {skipped_count}",
        f"Duration: {duration_str}",
        "",
    ]
    summary_lines.extend(summary_counts)

    summary_text = "\n".join(summary_lines)
    return summary_text, duration_str, passed_count, failed_count, skipped_count


def _resolve_execution_filters(
    config: Config,
    job_filter: list[str] | str | None,
    phase_filter: list[str] | str | None,
) -> tuple[set[str], list[str]]:
    """Validates job and phase filters and resolves (jobs_to_run, phases_to_run)."""
    if job_filter is None:
        filter_list = []
    elif isinstance(job_filter, str):
        filter_list = [job_filter]
    else:
        filter_list = list(job_filter)

    if filter_list:
        filter_set = set(filter_list)
        existing_names = {job.name for job in config.jobs}
        invalid_names = filter_set - existing_names
        if invalid_names:
            raise ValueError(
                f"Job filter contains invalid job names: {', '.join(sorted(invalid_names))}"
            )
        jobs_to_run = {job.name for job in config.jobs if job.name in filter_set}
    else:
        jobs_to_run = {job.name for job in config.jobs}

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

    return jobs_to_run, phases_to_run


def _init_job_states(
    config: Config,
    jobs_to_run: set[str],
    resume: str | None,
    saved_summaries: dict,
    succeeded_jobs: set[str],
) -> tuple[dict, dict, dict, dict[str, list[CommandTask]]]:
    """Initializes job summaries, durations, phase results, and command tasks."""
    job_summaries = {}
    job_durations = {}
    job_phase_results = {}
    job_command_tasks: dict[str, list[CommandTask]] = {}

    for job in config.jobs:
        default_tasks = build_job_command_tasks(job)
        if resume == "latest":
            job_info = saved_summaries.get(job.name, {})
            saved_cmds = job_info.get("commands", [])
            if saved_cmds:
                job_command_tasks[job.name] = _restore_job_command_tasks(job, saved_cmds)
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

    return job_summaries, job_durations, job_phase_results, job_command_tasks


def _build_execution_tasks(
    config: Config,
    jobs_to_run: set[str],
    phases_to_run: list[str],
    mode: str,
) -> list[tuple[Job, str]]:
    """Builds the ordered sequence of (job, phase_name) pairs to execute."""
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
    return execution_tasks


def _update_job_phase_status(
    job: Job,
    phases_to_run: list[str],
    job_phase_results: dict,
    job_command_tasks: dict,
    job_durations: dict,
    job_summaries: dict,
) -> None:
    """Updates the summary and build status of a job based on its completed target phases."""
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
    elif all_target_succeeded and len(job_phase_results[job.name]) == len(target_phases):
        job_summaries[job.name]["build_status"] = BuildStatus.DONE.value
        job_summaries[job.name]["status"] = "SUCCESS"
    else:
        b_st = compute_build_status(job_command_tasks[job.name], job.build_it)
        job_summaries[job.name]["build_status"] = b_st.value
        job_summaries[job.name]["status"] = "SUCCESS" if b_st == BuildStatus.DONE else b_st.value
    job_summaries[job.name]["duration"] = job_durations[job.name]


def _resolve_succeeded_jobs_on_resume(
    jobs: list[Job],
    saved_summaries: dict,
) -> set[str]:
    """Identifies which jobs in the configuration are already fully completed."""
    succeeded = set()
    for job in jobs:
        if job.name not in saved_summaries:
            continue
        info = saved_summaries[job.name]
        if not isinstance(info, dict):
            continue
        saved_cmds = info.get("commands", [])
        if saved_cmds:
            restored = _restore_job_command_tasks(job, saved_cmds)
            if restored and all(t.status == BuildStatus.DONE for t in restored):
                succeeded.add(job.name)
        else:
            if (
                info.get("status") == "SUCCESS"
                or info.get("build_status") == BuildStatus.DONE.value
            ):
                succeeded.add(job.name)
    return succeeded


def _check_and_warn_config_drift(
    saved_config_hash: str | None,
    current_config_hash: str,
) -> None:
    """Emits a warning to stderr if configuration drifted since the last session."""
    if saved_config_hash is not None and saved_config_hash != current_config_hash:
        print(
            "Warning: Configuration file has changed since the last session. "
            "Tasks will be matched strictly by command identity.",
            file=sys.stderr,
        )


def _filter_phase_commands_to_run(
    job: Job,
    phase_name: str,
    job_command_tasks: dict[str, list[CommandTask]],
    job_summaries: dict,
    job_phase_results: dict,
    aborted: bool,
    resume: str | None,
) -> list[CommandTask] | None:
    """Evaluates task eligibility for execution, reconciling aborted/completed states.
    Returns the list of CommandTasks to run, or None if the phase should be skipped.
    """
    is_job_done = (
        job_summaries[job.name].get("status") == "SUCCESS"
        or job_summaries[job.name].get("build_status") == BuildStatus.DONE.value
    )
    if is_job_done and resume == "latest":
        return None

    if not job.build_it:
        return None

    if aborted:
        if job_summaries[job.name]["status"] == "PENDING":
            job_summaries[job.name]["status"] = "SKIPPED"
            job_summaries[job.name]["build_status"] = BuildStatus.SKIPPED.value
            for t in job_command_tasks[job.name]:
                if t.status == BuildStatus.PENDING:
                    t.status = BuildStatus.SKIPPED
        return None

    phase_tasks = [t for t in job_command_tasks[job.name] if t.phase == phase_name]
    if resume == "latest" and phase_tasks and all(t.status == BuildStatus.DONE for t in phase_tasks):
        job_phase_results[job.name][phase_name] = True
        return None

    cmds_to_run = (
        [t for t in phase_tasks if t.status != BuildStatus.DONE]
        if resume == "latest"
        else phase_tasks
    )
    if not cmds_to_run:
        job_phase_results[job.name][phase_name] = True
        return None

    return cmds_to_run


def _execute_phase_run(
    job: Job,
    phase_name: str,
    cmds_to_run_tasks: list[CommandTask],
    job_command_tasks: dict[str, list[CommandTask]],
    job_summaries: dict,
    job_durations: dict,
    job_phase_results: dict,
    job_failed: dict,
    status_path: Path,
    config_path: str | Path | None,
    session_date: str,
    current_config_hash: str,
    verbose_mode: bool,
    log_dir: Path,
    log_to_session,
    stop_on_failure: bool,
    phases_to_run: set[str],
) -> tuple[bool, bool]:
    """Runs a single phase execution attempt and persists state.
    Returns (success: bool, should_abort: bool).
    """
    phase_display = f" (phase: {phase_name})" if phase_name != "default" else ""
    log_to_session(f"Starting job: {job.name}{phase_display} (cwd: {job.cwd})")

    def status_cb():
        b_st = compute_build_status(job_command_tasks[job.name], job.build_it)
        job_summaries[job.name]["build_status"] = b_st.value
        job_summaries[job.name]["status"] = "SUCCESS" if b_st == BuildStatus.DONE else b_st.value
        _save_status(status_path, config_path, session_date, job_summaries, config_hash=current_config_hash)

    cmds_to_run_tasks[0].status = BuildStatus.RUNNING
    job_summaries[job.name]["build_status"] = BuildStatus.RUNNING.value
    job_summaries[job.name]["status"] = "RUNNING"
    _save_status(status_path, config_path, session_date, job_summaries, config_hash=current_config_hash)

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

    should_abort = False
    if p_success:
        log_to_session(f"Job {job.name}{phase_display}: SUCCESS (took {p_duration:.2f}s)")
    else:
        job_failed[job.name] = True
        log_to_session(f"Job {job.name}{phase_display}: FAILED (took {p_duration:.2f}s)")
        if stop_on_failure:
            log_to_session("Aborting execution of subsequent jobs (stop_on_failure is enabled)")
            should_abort = True

    _update_job_phase_status(
        job=job,
        phases_to_run=phases_to_run,
        job_phase_results=job_phase_results,
        job_command_tasks=job_command_tasks,
        job_durations=job_durations,
        job_summaries=job_summaries,
    )
    _save_status(status_path, config_path, session_date, job_summaries, config_hash=current_config_hash)
    return p_success, should_abort


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
        jobs_to_run, phases_to_run = _resolve_execution_filters(config, job_filter, phase_filter)

        # Resolve resume status if configured
        status_path = resolve_status_path(config.settings.log_dir, config_path)
        succeeded_jobs = set()
        session_date = None
        saved_summaries = {}
        saved_config_hash = None
        current_config_hash = compute_config_hash(config)

        if resume == "latest":
            session_date, saved_summaries = _parse_and_validate_resume_status(
                status_path)
            saved_config_hash = getattr(saved_summaries, "config_hash", None)
            _check_and_warn_config_drift(saved_config_hash, current_config_hash)
            succeeded_jobs = _resolve_succeeded_jobs_on_resume(config.jobs, saved_summaries)

            if all(name in succeeded_jobs for name in jobs_to_run):
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

            job_summaries, job_durations, job_phase_results, job_command_tasks = _init_job_states(
                config=config,
                jobs_to_run=jobs_to_run,
                resume=resume,
                saved_summaries=saved_summaries,
                succeeded_jobs=succeeded_jobs,
            )

            job_failed = {}
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
                if saved_config_hash is not None and saved_config_hash != current_config_hash:
                    log_to_session(
                        "Warning: Configuration file has changed since the last session. "
                        "Tasks will be matched strictly by command identity."
                    )
            else:
                log_to_session("--- Session started ---")

            log_to_session(
                f"Settings: stop_on_failure={config.settings.stop_on_failure}, log_dir={config.settings.log_dir}"
            )

            # Save initial state if not resuming
            if resume != "latest":
                _save_status(status_path, config_path, session_date,
                             job_summaries, config_hash=current_config_hash)

            verbose_mode = getattr(config.settings, "verbose", True)
            if getattr(config.settings, "quiet", False):
                verbose_mode = False

            for job in config.jobs:
                if job.name in jobs_to_run and not job.build_it:
                    log_to_session(f"Job {job.name} is disabled. Skipping.")

            execution_tasks = _build_execution_tasks(config, jobs_to_run, phases_to_run, mode)

            current_phase_header = None
            active_job = None
            try:
                for job, phase_name in execution_tasks:
                    cmds_to_run_tasks = _filter_phase_commands_to_run(
                        job=job,
                        phase_name=phase_name,
                        job_command_tasks=job_command_tasks,
                        job_summaries=job_summaries,
                        job_phase_results=job_phase_results,
                        aborted=aborted,
                        resume=resume,
                    )
                    if cmds_to_run_tasks is None:
                        continue

                    if mode == "phased" and current_phase_header != phase_name and phase_name != "default":
                        current_phase_header = phase_name
                        log_to_session(f"--- Starting Phase: {phase_name} ---")

                    active_job = job
                    p_success, should_abort = _execute_phase_run(
                        job=job,
                        phase_name=phase_name,
                        cmds_to_run_tasks=cmds_to_run_tasks,
                        job_command_tasks=job_command_tasks,
                        job_summaries=job_summaries,
                        job_durations=job_durations,
                        job_phase_results=job_phase_results,
                        job_failed=job_failed,
                        status_path=status_path,
                        config_path=config_path,
                        session_date=session_date,
                        current_config_hash=current_config_hash,
                        verbose_mode=verbose_mode,
                        log_dir=log_dir,
                        log_to_session=log_to_session,
                        stop_on_failure=config.settings.stop_on_failure,
                        phases_to_run=phases_to_run,
                    )
                    active_job = None

                    if not p_success:
                        overall_success = False
                    if should_abort:
                        aborted = True

                # Unconditional save to disk after execution tasks complete
                _save_status(
                    status_path,
                    config_path,
                    session_date,
                    job_summaries,
                    config_hash=current_config_hash,
                )

            except KeyboardInterrupt:
                log_to_session("--- Session interrupted by user (Ctrl+C) ---")
                overall_success = False
                if active_job is not None:
                    job_failed[active_job.name] = True
                    for t in job_command_tasks.get(active_job.name, []):
                        if t.status == BuildStatus.RUNNING:
                            t.status = BuildStatus.FAILED
                            t.exit_code = 130
                    job_summaries[active_job.name]["status"] = "INTERRUPTED"
                    job_summaries[active_job.name]["build_status"] = BuildStatus.FAILED.value

                for rem_job, _ in execution_tasks:
                    if job_summaries[rem_job.name]["status"] == "PENDING":
                        job_summaries[rem_job.name]["status"] = "SKIPPED"
                        job_summaries[rem_job.name]["build_status"] = BuildStatus.SKIPPED.value
                        for t in job_command_tasks.get(rem_job.name, []):
                            if t.status == BuildStatus.PENDING:
                                t.status = BuildStatus.SKIPPED

                _save_status(
                    status_path,
                    config_path,
                    session_date,
                    job_summaries,
                    config_hash=current_config_hash,
                )

                passed_cnt = sum(1 for s in job_summaries.values() if s.get("status") == "SUCCESS")
                interrupted_cnt = sum(1 for s in job_summaries.values() if s.get("status") == "INTERRUPTED")
                pending_cnt = sum(1 for s in job_summaries.values() if s.get("status") in ("PENDING", "SKIPPED"))
                cfg_display = str(config_path) if config_path else "<config>"

                print(
                    f"\n[LBS] Run interrupted by user (Ctrl+C). "
                    f"{passed_cnt} completed, {interrupted_cnt} interrupted, {pending_cnt} pending/skipped.\n"
                    f"To resume, run: lbs run {cfg_display} --resume latest",
                    file=sys.stderr,
                )
                raise

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
