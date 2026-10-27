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

from lbs import __version__, Scheduler, clean_session_state
from lbs.config import load_config, resolve_status_path, Config, ConfigError
from lbs.utils.lock import FileLock, LockError


def trigger_os_shutdown() -> None:
    """
    Schedules an OS shutdown.
    On Windows: calls shutdown /s /t 60 (60 second delay, abort via shutdown /a).
    On POSIX (Linux/macOS): calls shutdown -h +1 (1 minute delay, abort via shutdown -c).
    """
    try:
        if sys.platform == "win32":
            cmd = ["shutdown", "/s", "/t", "60"]
            warning_msg = "\n[WARNING] System shutdown scheduled in 60 seconds."
            abort_msg = "To abort the shutdown, run: shutdown /a"
        else:
            cmd = ["shutdown", "-h", "+1"]
            warning_msg = "\n[WARNING] System shutdown scheduled in 1 minute."
            abort_msg = "To abort the shutdown, run: shutdown -c"

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
    except Exception as e:
        print(f"Failed to initiate system shutdown: {e}", file=sys.stderr)


def _count_unfinished_enabled_jobs(config: Config, config_path: str) -> int | None:
    """Counts enabled jobs whose persisted status is not SUCCESS.

    Returns None if the status file cannot be read, so callers can stay safe.
    """
    status_path = resolve_status_path(config.settings.log_dir, config_path)
    try:
        with open(status_path, "r", encoding="utf-8") as f:
            saved_jobs = json.load(f).get("jobs", {})
    except (OSError, ValueError, AttributeError):
        return None

    unfinished = 0
    for job in config.jobs:
        if not job.build_it:
            continue
        info = saved_jobs.get(job.name)
        if not isinstance(info, dict) or info.get("status") != "SUCCESS":
            unfinished += 1
    return unfinished


def _should_trigger_shutdown(config: Config, config_path: str) -> bool:
    """Returns True only if all enabled jobs completed; otherwise warns on stderr."""
    unfinished = _count_unfinished_enabled_jobs(config, config_path)
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
        config = load_config(args.config,
                             notifications_path=getattr(
                                 args, "notifications_config", None))
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
            if getattr(args, "dry_run", False):
                print("Dry run: skipping the requested system shutdown.")
            elif not success:
                print(
                    "Session failed: skipping the requested system shutdown so "
                    "the machine stays available for diagnosis.",
                    file=sys.stderr,
                )
            elif _should_trigger_shutdown(config, args.config):
                trigger_os_shutdown()
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
        config = load_config(args.config)
        for job in config.jobs:
            print(job.name)
        sys.exit(0)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_clean(args: argparse.Namespace) -> None:
    """Handle the 'lbs clean <config>' subcommand."""
    try:
        config = load_config(args.config)
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
        help="Shut down the system after all jobs complete successfully. "
        "Skipped if any job fails, if any enabled job in the config remains "
        "unexecuted or skipped (e.g. with -j), and on --dry-run.",
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

    return parser


def main() -> None:
    """Main entry point for the lbs CLI."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
