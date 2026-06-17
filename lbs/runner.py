# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.runner – Sequential job execution and logging.
"""

import datetime
import json
import os
from pathlib import Path
import re
import tempfile
import time
from lbs.config import Config
from lbs.utils.executor import JobExecutor
from lbs.utils.lock import FileLock


def _save_state(state_path: Path, config_file: str | Path | None,
                session_date: str, job_summaries: dict) -> None:
    """Save the current execution state atomically to JSON."""
    serializable_jobs = {}
    for name, info in job_summaries.items():
        serializable_jobs[name] = {
            "status": info.get("status"),
            "duration": info.get("duration")
        }

    data = {
        "config_file": str(config_file) if config_file is not None else None,
        "session_date": session_date,
        "jobs": serializable_jobs
    }

    state_path.parent.mkdir(parents=True, exist_ok=True)

    temp_fd, temp_path = tempfile.mkstemp(dir=str(state_path.parent),
                                          prefix="lbs_state_",
                                          suffix=".tmp")
    try:
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, str(state_path))
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise


class Scheduler:
    """Orchestrates sequential execution of job queues, filtering, and logging."""

    @staticmethod
    def run(
        config: Config,
        job_filter: list[str] | str | None = None,
        dry_run: bool = False,
        resume: str | None = None,
        config_path: str | Path | None = None,
    ) -> bool:
        """
        Main sequential execution loop for LBS jobs.
        
        Creates the configured log directory, manages the session and job-specific
        log files, runs commands sequentially under each job with environment overlays,
        tracks durations, and returns True if all executed jobs succeeded, or False if any failed.
        
        If job_filter is specified, only executes jobs with names in the filter.
        Raises ValueError if job_filter contains any invalid job names.
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

        # Resolve resume state if configured
        state_path = Path(config.settings.log_dir) / "lbs_state.json"
        succeeded_jobs = set()
        session_date = None
        saved_summaries = {}

        if resume == "latest":
            if not state_path.is_file():
                raise ValueError("No active session state found to resume.")
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    state_data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                raise ValueError(f"Failed to load session state: {e}") from e

            if not isinstance(state_data, dict):
                raise ValueError(
                    "Failed to load session state: state file content is not a JSON object"
                )

            saved_summaries = state_data.get("jobs")
            if not isinstance(saved_summaries, dict):
                raise ValueError(
                    "Failed to load session state: 'jobs' field is missing or not a JSON object"
                )

            session_date = state_data.get("session_date")
            if not isinstance(session_date, str):
                raise ValueError(
                    "Failed to load session state: 'session_date' field is missing or not a string"
                )

            if not re.match(r"^\d{4}-\d{2}-\d{2}$", session_date):
                raise ValueError(
                    f"Failed to load session state: invalid session_date format '{session_date}'"
                )

            succeeded_jobs = {
                name
                for name, info in saved_summaries.items()
                if isinstance(info, dict) and info.get("status") == "SUCCESS"
            }

            # If all selected jobs are already succeeded:
            selected_succeeded = all(
                isinstance(saved_summaries.get(name), dict)
                and saved_summaries[name].get("status") == "SUCCESS"
                for name in jobs_to_run
            )
            if selected_succeeded:
                print(
                    "All selected jobs in the previous session completed successfully. Nothing to resume."
                )
                return True

        if dry_run:
            print("Dry-Run Execution Plan")
            print("======================")
            print(f"Log Directory: {config.settings.log_dir}")
            if resume == "latest":
                print("Resuming Session from latest state")
            print()
            for job in config.jobs:
                if job.name not in jobs_to_run:
                    continue
                if job.name in succeeded_jobs:
                    print(f"Job: {job.name} [ALREADY SUCCEEDED]")
                    continue
                print(f"Job: {job.name}")
                print(f"  CWD: {job.cwd}")
                env_str = (", ".join(
                    f"{k}={v}"
                    for k, v in job.env.items()) if job.env else "None")
                print(f"  Environment: {env_str}")
                if job.retries > 0:
                    print(
                        f"  Retries: {job.retries} (delay: {job.retry_delay_seconds}s)"
                    )
                if job.command_timeout_minutes is not None:
                    print(f"  Timeout: {job.command_timeout_minutes}m")
                print("  Commands:")
                for cmd in job.commands:
                    print(f"    - {cmd}")
                print()
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
            for job in config.jobs:
                if resume == "latest" and job.name in succeeded_jobs:
                    job_info = saved_summaries.get(job.name, {})
                    job_summaries[job.name] = {
                        "status": "SUCCESS",
                        "duration": job_info.get("duration")
                    }
                else:
                    job_summaries[job.name] = {
                        "status":
                        "PENDING" if job.name in jobs_to_run else "SKIPPED",
                        "duration": None
                    }

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
                _save_state(state_path, config_path, session_date,
                            job_summaries)

            for job in config.jobs:
                if job.name not in jobs_to_run:
                    # Not selected by the job filter, leave as initialized
                    continue

                if job_summaries[job.name]["status"] == "SUCCESS":
                    # Already succeeded in previous run of this session! Skip it.
                    continue

                if aborted:
                    job_summaries[job.name] = {
                        "status": "SKIPPED",
                        "duration": None
                    }
                    _save_state(state_path, config_path, session_date,
                                job_summaries)
                    continue

                log_to_session(f"Starting job: {job.name} (cwd: {job.cwd})")
                job_log_path = log_dir / f"{session_date}_{job.name}.log"

                # Mark as PENDING during execution
                job_summaries[job.name] = {
                    "status": "PENDING",
                    "duration": None
                }
                _save_state(state_path, config_path, session_date,
                            job_summaries)

                job_success = False
                job_duration = 0.0
                total_attempts = 1 + job.retries

                for attempt in range(1, total_attempts + 1):
                    job_start_time = time.perf_counter()
                    job_success = True

                    # Open job log in append mode, with line buffering or explicit flushing
                    with open(job_log_path, "a", encoding="utf-8") as job_log:

                        def log_to_job(msg: str) -> None:
                            timestamp = datetime.datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S")
                            job_log.write(f"[{timestamp}] {msg}\n")
                            job_log.flush()

                        if attempt > 1:
                            log_to_job(
                                f"--- Retry Attempt {attempt - 1} / {job.retries} ---"
                            )
                        else:
                            log_to_job(f"Job '{job.name}' started")
                            log_to_job(f"CWD: {job.cwd}")
                            log_to_job(f"Environment overlays: {job.env}")

                        # Initialize executor for this job execution
                        verbose_mode = getattr(config.settings, "verbose",
                                               False)
                        executor = JobExecutor(verbose=verbose_mode)

                        # Sequentially run commands
                        for cmd in job.commands:
                            log_to_job(f"Executing command: {cmd}")

                            # Run command via JobExecutor
                            timeout_sec = (job.command_timeout_minutes *
                                           60 if job.command_timeout_minutes
                                           is not None else None)
                            result = executor.run_command(cmd,
                                                          cwd=job.cwd,
                                                          env=job.env,
                                                          log_file=job_log,
                                                          timeout=timeout_sec)

                            if not result.success:
                                status_label = "ATTEMPT FAILED" if attempt < total_attempts else "FAILED"
                                if result.error_message:
                                    log_to_job(
                                        f"Process execution error: {result.error_message}"
                                    )
                                    log_to_session(
                                        f"Job {job.name}: {status_label} (Command '{cmd}' failed: {result.error_message})"
                                    )
                                else:
                                    log_to_job(
                                        f"Command failed with exit code {result.exit_code}"
                                    )
                                    log_to_session(
                                        f"Job {job.name}: {status_label} (Command '{cmd}' failed with exit code {result.exit_code})"
                                    )
                                job_success = False
                                break
                            else:
                                log_to_job("Command succeeded")

                    # Calculate duration for this attempt, adding to total execution duration
                    job_duration += time.perf_counter() - job_start_time

                    if job_success:
                        break
                    else:
                        if attempt < total_attempts:
                            log_to_session(
                                f"Job {job.name} failed. Retrying in {job.retry_delay_seconds} seconds (attempt {attempt}/{job.retries})..."
                            )
                            time.sleep(job.retry_delay_seconds)

                if job_success:
                    log_to_session(
                        f"Job {job.name}: SUCCESS (took {job_duration:.2f}s)")
                    job_summaries[job.name] = {
                        "status": "SUCCESS",
                        "duration": job_duration
                    }
                else:
                    overall_success = False
                    job_summaries[job.name] = {
                        "status": "FAILED",
                        "duration": job_duration
                    }

                    if config.settings.stop_on_failure:
                        log_to_session(
                            "Aborting execution of subsequent jobs (stop_on_failure is enabled)"
                        )
                        aborted = True

                _save_state(state_path, config_path, session_date,
                            job_summaries)

            summary_lines = [
                "",
                "=" * 50,
                "              LBS Session Summary",
                "=" * 50,
            ]
            for name, summary in job_summaries.items():
                status = summary["status"]
                dur = summary["duration"]
                dur_str = f"{dur:.2f}s" if dur is not None else "-"
                summary_lines.append(
                    f"Job: {name:<20} ->  {status:<10} ({dur_str})")
            summary_lines.append("=" * 50)

            session_status = "SUCCESS" if overall_success else "FAILED"
            summary_lines.append(f"Session completed: {session_status}")
            summary_lines.append("")

            # Count job statuses for the final summary
            passed_count = sum(1 for s in job_summaries.values()
                               if s["status"] == "SUCCESS")
            failed_count = sum(1 for s in job_summaries.values()
                               if s["status"] == "FAILED")
            skipped_count = sum(1 for s in job_summaries.values()
                                if s["status"] in ("SKIPPED", "PENDING"))

            # Format elapsed duration to HH:MM:SS
            elapsed_time = time.perf_counter() - session_start_time
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
