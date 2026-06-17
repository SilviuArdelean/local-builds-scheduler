# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.cli – Command-line interface for the Local Builds Scheduler.

Entry point: lbs.cli:main
"""

import argparse
import sys

from lbs import __version__, Scheduler
from lbs.config import load_config, ConfigError
from lbs.utils.lock import LockError


def cmd_run(args: argparse.Namespace) -> None:
    """Handle the 'lbs run <config>' subcommand."""
    try:
        config = load_config(args.config)
        if args.verbose:
            config.settings.verbose = True
        success = Scheduler.run(
            config,
            job_filter=args.job,
            dry_run=getattr(args, "dry_run", False),
            resume=getattr(args, "resume", None),
            config_path=args.config,
        )
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
        load_config(args.config)
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
