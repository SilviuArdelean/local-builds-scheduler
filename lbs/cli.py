# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.cli – Command-line interface for the Local Builds Scheduler.

Entry point: lbs.cli:main
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from lbs import __version__, Scheduler, clean_session_state
from lbs.config import load_config, resolve_status_path, Config, ConfigError
from lbs.utils.lock import FileLock, LockError


def _cancel_os_shutdown(abort_cmd: list[str]) -> None:
    """Cancels a previously scheduled OS shutdown."""
    try:
        subprocess.run(abort_cmd, check=True, capture_output=True, text=True)
        print("[LBS] System shutdown cancelled by user (Ctrl+C).")
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() if e.stderr else str(e)
        print(
            f"Failed to cancel system shutdown (exit code {e.returncode}): {err_msg}",
            file=sys.stderr,
        )
    except Exception as e:
        print(f"Failed to cancel system shutdown: {e}", file=sys.stderr)


def trigger_os_shutdown(
    passed_count: int | None = None,
    failed_count: int | None = None,
    interactive: bool | None = None,
    countdown_seconds: int = 60,
) -> None:
    """
    Schedules an OS shutdown with a 1-minute (60-second) warning and optional live
    Ctrl+C terminal countdown.
    On Windows: calls shutdown /s /t 60 (60 second delay, abort via shutdown /a).
    On POSIX (Linux/macOS): calls shutdown -h +1 (1 minute delay, abort via shutdown -c).
    """
    try:
        stats_suffix = (
            f" ({passed_count} passed, {failed_count} failed)"
            if passed_count is not None and failed_count is not None
            else ""
        )
        if sys.platform == "win32":
            cmd = ["shutdown", "/s", "/t", "60"]
            abort_cmd = ["shutdown", "/a"]
            abort_cmd_str = "shutdown /a"
            warning_msg = f"\n[WARNING] System will shut down in 60 seconds{stats_suffix}."
        else:
            cmd = ["shutdown", "-h", "+1"]
            abort_cmd = ["shutdown", "-c"]
            abort_cmd_str = "shutdown -c"
            warning_msg = f"\n[WARNING] System will shut down in 1 minute{stats_suffix}."

        abort_msg = (
            f"Press Ctrl+C now to cancel the shutdown "
            f"(or run '{abort_cmd_str}' in another terminal)..."
        )

        # Run the command first. If check=True raises CalledProcessError,
        # we do not output the success/warning messages.
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(warning_msg)
        print(abort_msg)
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.strip() if e.stderr else str(e)
        print(
            f"Failed to initiate system shutdown (exit code {e.returncode}): {err_msg}",
            file=sys.stderr,
        )
        return
    except Exception as e:
        print(f"Failed to initiate system shutdown: {e}", file=sys.stderr)
        return

    is_interactive = (
        interactive
        if interactive is not None
        else getattr(sys.stdout, "isatty", lambda: False)()
    )
    if is_interactive and countdown_seconds > 0:
        try:
            for remaining in range(countdown_seconds, 0, -1):
                sys.stdout.write(f"\rCountdown: {remaining}s remaining...   ")
                sys.stdout.flush()
                time.sleep(1)
            sys.stdout.write("\rCountdown: 0s remaining. Shutting down...\n")
            sys.stdout.flush()
        except KeyboardInterrupt:
            sys.stdout.write("\n")
            sys.stdout.flush()
            _cancel_os_shutdown(abort_cmd)


def _get_enabled_jobs_completion_counts(
    config: Config,
    config_path: str,
    allow_aborted_on_failure: bool = True,
) -> tuple[int, int, int] | None:
    """Returns (passed_count, failed_count, unfinished_count) for all enabled jobs.

    An enabled job is considered finished (attempted) if its persisted status is
    SUCCESS (with no remaining PENDING commands from phase filtering) or FAILED.
    When stop_on_failure is enabled and allow_aborted_on_failure is True, jobs
    marked ABORTED or PARTIAL due to an earlier job's failure in the queue are
    not counted as unexecuted filter omissions.
    Returns None if the status file cannot be read, so callers can stay safe.
    """
    status_path = resolve_status_path(config.settings.log_dir, config_path)
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            saved_jobs = json.load(f).get("jobs", {})
    except (OSError, ValueError, AttributeError):
        return None

    passed = 0
    failed = 0
    aborted_by_failure = 0
    unfinished = 0
    for job in config.jobs:
        if not job.build_it:
            continue
        info = saved_jobs.get(job.name)
        if not isinstance(info, dict):
            unfinished += 1
            continue
        status = info.get("status")
        cmds = info.get("commands", [])
        has_pending_cmds = (
            status == "SUCCESS"
            and isinstance(cmds, list)
            and any(isinstance(c, dict) and c.get("status") == "PENDING" for c in cmds)
        )
        if status == "SUCCESS" and not has_pending_cmds:
            passed += 1
        elif status == "FAILED":
            failed += 1
        elif status in ("ABORTED", "PARTIAL"):
            aborted_by_failure += 1
        else:
            unfinished += 1

    if aborted_by_failure > 0:
        if not (allow_aborted_on_failure and config.settings.stop_on_failure and failed > 0):
            unfinished += aborted_by_failure

    return passed, failed, unfinished


def _count_unfinished_enabled_jobs(
    config: Config,
    config_path: str,
    allow_aborted_on_failure: bool = True,
) -> int | None:
    """Counts enabled jobs that remain unexecuted or skipped.

    Returns None if the status file cannot be read, so callers can stay safe.
    """
    counts = _get_enabled_jobs_completion_counts(
        config,
        config_path,
        allow_aborted_on_failure=allow_aborted_on_failure,
    )
    if counts is None:
        return None
    return counts[2]


def _should_trigger_shutdown(
    config: Config,
    config_path: str,
    allow_aborted_on_failure: bool = True,
) -> bool:
    """Returns True only if all enabled jobs were attempted (or halted by stop_on_failure); otherwise warns on stderr."""
    unfinished = _count_unfinished_enabled_jobs(
        config,
        config_path,
        allow_aborted_on_failure=allow_aborted_on_failure,
    )
    if unfinished is None:
        print(
            "[WARNING] System shutdown cancelled: could not verify the "
            "status of all jobs in the configuration.",
            file=sys.stderr,
        )
        return False
    if unfinished > 0:
        noun = "job" if unfinished == 1 else "jobs"
        verb = "remains" if unfinished == 1 else "remain"
        print(
            f"[WARNING] System shutdown cancelled: {unfinished} {noun} in the "
            f"configuration {verb} unexecuted or skipped.\n"
            "To power off only after all jobs finish, run without job filters.",
            file=sys.stderr,
        )
        return False
    return True


def cmd_run(args: argparse.Namespace) -> None:
    """Handle the 'lbs run <config>' subcommand."""
    try:
        load_kwargs = {
            "notifications_path": getattr(args, "notifications_config", None),
        }
        if getattr(args, "job", None):
            load_kwargs["job_filter"] = args.job
        config = load_config(args.config, **load_kwargs)
        if config is not None:
            if not getattr(args, "notifications", False):
                config.settings.notifications.on_success = False
                config.settings.notifications.on_failure = False
        if getattr(args, "quiet", False):
            config.settings.quiet = True
            config.settings.verbose = False
        success = Scheduler.run(
            config,
            job_filter=args.job,
            phase_filter=getattr(args, "phase", None),
            dry_run=getattr(args, "dry_run", False),
            resume=getattr(args, "resume", None),
            config_path=args.config,
            mode=getattr(args, "mode", "phased"),
            fresh=getattr(args, "fresh", False),
        )
        if getattr(args, "shutdown", False):
            has_filter = bool(getattr(args, "job", None) or getattr(args, "phase", None))
            if getattr(args, "dry_run", False):
                print("Dry run: skipping the requested system shutdown.")
            elif _should_trigger_shutdown(
                config,
                args.config,
                allow_aborted_on_failure=not has_filter,
            ):
                counts = _get_enabled_jobs_completion_counts(
                    config,
                    args.config,
                    allow_aborted_on_failure=not has_filter,
                )
                passed_cnt = counts[0] if counts else None
                failed_cnt = counts[1] if counts else None
                trigger_os_shutdown(passed_count=passed_cnt, failed_count=failed_cnt)
        sys.exit(0 if success else 1)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except ValueError as e:
        if (getattr(args, "job", None) or getattr(args, "phase", None)
                or getattr(args, "resume", None)
                or getattr(args, "fresh", False)):
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)
        raise
    except LockError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)


def cmd_validate(args: argparse.Namespace) -> None:
    """Handle the 'lbs validate <config>' subcommand."""
    try:
        load_config(args.config,
                    notifications_path=getattr(args, "notifications_config",
                                               None))
        print("Configuration is valid.")
        sys.exit(0)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_list(args: argparse.Namespace) -> None:
    """Handle the 'lbs list <config>' subcommand."""
    try:
        config = load_config(args.config, check_cwd=False)
        for job in config.jobs:
            print(job.name)
        sys.exit(0)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_clean(args: argparse.Namespace) -> None:
    """Handle the 'lbs clean <config>' subcommand."""
    try:
        config = load_config(args.config, check_cwd=False)
        log_dir = config.settings.log_dir
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    log_path = Path(log_dir)
    lock_path = log_path / "lbs.lock"
    try:
        if log_path.is_dir():
            with FileLock(lock_path):
                cleaned = clean_session_state(
                    config_file=args.config, log_dir=log_dir)
        else:
            cleaned = clean_session_state(
                config_file=args.config, log_dir=log_dir)
    except LockError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    if cleaned:
        print(f"Cleared saved session state for {args.config}.")
    else:
        print(f"No saved session state found for {args.config}. Nothing to clean.")
    sys.exit(0)


def cmd_status(args: argparse.Namespace) -> None:
    """Handle the 'lbs status <config>' subcommand."""
    try:
        config = load_config(args.config, check_cwd=False)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        output, exit_code = Scheduler.status(
            config_path=args.config,
            config=config,
            as_json=args.json,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    print(output)
    sys.exit(exit_code)


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="lbs",
        description=
        "Local Builds Scheduler – run local build jobs sequentially.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"lbs {__version__}",
    )

    subparsers = parser.add_subparsers(title="commands", dest="command")
    subparsers.required = True

    # lbs run <config>
    run_parser = subparsers.add_parser(
        "run", help="Run all jobs defined in a config file.")
    run_parser.add_argument("config", help="Path to the YAML config file.")
    run_parser.add_argument(
        "-n",
        "--notifications-config",
        help="Path to the separate YAML notifications config file.",
    )
    run_parser.add_argument(
        "--notifications",
        action="store_true",
        help="Enable notifications for this run.",
    )
    run_parser.add_argument(
        "--shutdown",
        action="store_true",
        help="Shut down the system (with a 60-second warning countdown) after the "
        "session finishes (including on job failure or stop_on_failure abort). "
        "Skipped if any enabled job in the config remains unexecuted or skipped "
        "(e.g. with -j or -p), on Ctrl+C interruption, and on --dry-run.",
    )
    run_parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress live command output streaming to terminal. Full logs are still recorded to disk.",
    )
    run_parser.add_argument(
        "-j",
        "--job",
        action="append",
        help="Run specific job(s) by name. Can be specified multiple times.",
    )
    run_parser.add_argument(
        "-p",
        "--phase",
        action="append",
        help="Run specific phase(s) by name. Can be specified multiple times.",
    )
    run_parser.add_argument(
        "--mode",
        choices=["phased", "sequential"],
        default="phased",
        help="Execution strategy across jobs: 'phased' (runs phase by phase across active jobs) or 'sequential' (runs job by job).",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the execution plan without running commands.",
    )
    resume_group = run_parser.add_mutually_exclusive_group()
    resume_group.add_argument(
        "--resume",
        choices=["latest"],
        help=
        "Resume a failed or interrupted session. Currently supports 'latest'.",
    )
    resume_group.add_argument(
        "--fresh",
        "--ignore-saved-state",
        dest="fresh",
        action="store_true",
        help=
        "Discard any existing saved session state and start all jobs from the beginning.",
    )
    run_parser.set_defaults(func=cmd_run)

    # lbs validate <config>
    val_parser = subparsers.add_parser("validate",
                                       help="Validate a config file.")
    val_parser.add_argument("config", help="Path to the YAML config file.")
    val_parser.add_argument(
        "-n",
        "--notifications-config",
        help="Path to the separate YAML notifications config file.",
    )
    val_parser.set_defaults(func=cmd_validate)

    # lbs list <config>
    list_parser = subparsers.add_parser(
        "list", help="List jobs defined in a config file.")
    list_parser.add_argument("config", help="Path to the YAML config file.")
    list_parser.set_defaults(func=cmd_list)

    # lbs clean <config>
    clean_parser = subparsers.add_parser(
        "clean",
        help="Clean saved session state and temporary files for a config.",
    )
    clean_parser.add_argument("config", help="Path to the YAML config file.")
    clean_parser.set_defaults(func=cmd_clean)

    # lbs status <config>
    status_parser = subparsers.add_parser(
        "status",
        help="Inspect saved session status for a config without executing.",
    )
    status_parser.add_argument("config", help="Path to the YAML config file.")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output status data as JSON instead of human-readable text.",
    )
    status_parser.set_defaults(func=cmd_status)

    return parser


def main() -> None:
    """Main entry point for the lbs CLI."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
