# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.runner – Sequential job execution and logging.
"""

import datetime
import time
from pathlib import Path
from lbs.config import Config
from lbs.utils.executor import JobExecutor
from lbs.utils.lock import FileLock


class Scheduler:
    """Orchestrates sequential execution of job queues, filtering, and logging."""

    @staticmethod
    def run(config: Config, job_filter: list[str] | str | None = None) -> bool:
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

        # Initialize filesystem logs
        log_dir = Path(config.settings.log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        lock_path = log_dir / "lbs.lock"
        with FileLock(lock_path):
            session_date = datetime.datetime.now().strftime("%Y-%m-%d")
            session_log_path = log_dir / f"{session_date}_session.log"

            # Track execution details for summary
            # Format: {job_name: {"status": "SUCCESS" | "FAILED" | "SKIPPED", "duration": float | None}}
            job_summaries = {
                job.name: {
                    "status": "SKIPPED",
                    "duration": None
                }
                for job in config.jobs
            }

            overall_success = True
            aborted = False

            def log_to_session(msg: str) -> None:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                formatted_msg = f"[{timestamp}] {msg}\n"
                with open(session_log_path, "a", encoding="utf-8") as f:
                    f.write(formatted_msg)

            log_to_session("--- Session started ---")
            log_to_session(
                f"Settings: stop_on_failure={config.settings.stop_on_failure}, log_dir={config.settings.log_dir}"
            )

            for job in config.jobs:
                if job.name not in jobs_to_run:
                    # Not selected by the job filter, leave as SKIPPED
                    continue

                if aborted:
                    job_summaries[job.name] = {
                        "status": "SKIPPED",
                        "duration": None
                    }
                    continue

                log_to_session(f"Starting job: {job.name} (cwd: {job.cwd})")
                job_log_path = log_dir / f"{session_date}_{job.name}.log"

                job_start_time = time.perf_counter()
                job_success = True

                # Open job log in append mode, with line buffering or explicit flushing
                with open(job_log_path, "a", encoding="utf-8") as job_log:

                    def log_to_job(msg: str) -> None:
                        timestamp = datetime.datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S")
                        job_log.write(f"[{timestamp}] {msg}\n")
                        job_log.flush()

                    log_to_job(f"Job '{job.name}' started")
                    log_to_job(f"CWD: {job.cwd}")
                    log_to_job(f"Environment overlays: {job.env}")

                    # Initialize executor for this job execution
                    verbose_mode = getattr(config.settings, "verbose", False)
                    executor = JobExecutor(verbose=verbose_mode)

                    # Sequentially run commands
                    for cmd in job.commands:
                        log_to_job(f"Executing command: {cmd}")

                        # Run command via JobExecutor
                        result = executor.run_command(cmd,
                                                      cwd=job.cwd,
                                                      env=job.env,
                                                      log_file=job_log)

                        if not result.success:
                            if result.error_message:
                                log_to_job(
                                    f"Process execution error: {result.error_message}"
                                )
                                log_to_session(
                                    f"Job {job.name}: FAILED (Error launching command '{cmd}': {result.error_message})"
                                )
                            else:
                                log_to_job(
                                    f"Command failed with exit code {result.exit_code}"
                                )
                                log_to_session(
                                    f"Job {job.name}: FAILED (Command '{cmd}' failed with exit code {result.exit_code})"
                                )
                            job_success = False
                            break
                        else:
                            log_to_job("Command succeeded")

                # Calculate duration
                job_duration = time.perf_counter() - job_start_time

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
            passed_count = sum(
                1 for s in job_summaries.values() if s["status"] == "SUCCESS"
            )
            failed_count = sum(
                1 for s in job_summaries.values() if s["status"] == "FAILED"
            )
            skipped_count = sum(
                1 for s in job_summaries.values() if s["status"] == "SKIPPED"
            )

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

            return overall_success


def run_scheduler(config: Config) -> bool:
    """
    Deprecated: use Scheduler.run(config) instead.
    Main sequential execution loop for LBS jobs.
    """
    return Scheduler.run(config)
