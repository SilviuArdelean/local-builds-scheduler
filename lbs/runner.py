# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.runner – Sequential job execution and logging.
"""

import datetime
import os
import subprocess
import time
from pathlib import Path
from lbs.config import Config


def run_scheduler(config: Config) -> bool:
    """
    Main sequential execution loop for LBS jobs.
    
    Creates the configured log directory, manages the session and job-specific
    log files, runs commands sequentially under each job with environment overlays,
    tracks durations, and returns True if all executed jobs succeeded, or False if any failed.
    """

    log_dir = Path(config.settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

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
        if aborted:
            job_summaries[job.name] = {"status": "SKIPPED", "duration": None}
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

            # Merge environments
            env = os.environ.copy()
            env.update(job.env)

            # Sequentially run commands
            for cmd in job.commands:
                log_to_job(f"Executing command: {cmd}")

                try:
                    # Run subprocess with output redirected directly to the log file stream
                    process = subprocess.Popen(cmd,
                                               shell=True,
                                               cwd=job.cwd,
                                               env=env,
                                               stdout=job_log,
                                               stderr=subprocess.STDOUT)
                    process.wait()

                    if process.returncode != 0:
                        log_to_job(
                            f"Command failed with exit code {process.returncode}"
                        )
                        log_to_session(
                            f"Job {job.name}: FAILED (Command '{cmd}' failed with exit code {process.returncode})"
                        )
                        job_success = False
                        break
                    else:
                        log_to_job("Command succeeded")

                except Exception as e:
                    log_to_job(f"Process execution error: {e}")
                    log_to_session(
                        f"Job {job.name}: FAILED (Error launching command '{cmd}': {e})"
                    )
                    job_success = False
                    break

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
        summary_lines.append(f"Job: {name:<20} ->  {status:<10} ({dur_str})")
    summary_lines.append("=" * 50)

    session_status = "SUCCESS" if overall_success else "FAILED"
    summary_lines.append(f"Session completed: {session_status}")
    summary_lines.append("")

    summary_text = "\n".join(summary_lines)

    print(summary_text)

    with open(session_log_path, "a", encoding="utf-8") as f:
        f.write(summary_text)

    log_to_session(f"--- Session ended (status: {session_status}) ---")

    return overall_success
