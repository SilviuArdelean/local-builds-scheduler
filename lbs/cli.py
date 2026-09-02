# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.cli – Command-line interface for the Local Builds Scheduler.

Entry point: lbs.cli:main
"""

import argparse
import subprocess
import sys

from lbs import __version__, Scheduler
from lbs.config import load_config, ConfigError
from lbs.utils.lock import LockError


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
        if args.verbose:
            config.settings.verbose = True
        success = Scheduler.run(
            config,
            job_filter=args.job,
            dry_run=getattr(args, "dry_run", False),
            resume=getattr(args, "resume", None),
            config_path=args.config,
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
            else:
                trigger_os_shutdown()
        sys.exit(0 if success else 1)
    except ConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except ValueError as e:
        if getattr(args, "job", None) or getattr(args, "resume", None):
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(2)
        raise
    except LockError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


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
        "Skipped if any job fails, and on --dry-run.",
    )
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Mirror execution output directly to standard output.",
    )
    run_parser.add_argument(
        "-j",
        "--job",
        action="append",
        help="Run specific job(s) by name. Can be specified multiple times.",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the execution plan without running commands.",
    )
    run_parser.add_argument(
        "--resume",
        choices=["latest"],
        help=
        "Resume a failed or interrupted session. Currently supports 'latest'.",
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

    return parser


def main() -> None:
    """Main entry point for the lbs CLI."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
