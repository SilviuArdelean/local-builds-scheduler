# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0

"""
lbs.cli – Command-line interface for the Local Builds Scheduler.

Entry point: lbs.cli:main
"""

import argparse

from lbs import __version__


def cmd_run(args: argparse.Namespace) -> None:
    """Handle the 'lbs run <config>' subcommand."""
    print("not implemented")


def cmd_validate(args: argparse.Namespace) -> None:
    """Handle the 'lbs validate <config>' subcommand."""
    print("not implemented")


def cmd_list(args: argparse.Namespace) -> None:
    """Handle the 'lbs list <config>' subcommand."""
    print("not implemented")


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="lbs",
        description="Local Builds Scheduler – run local build jobs sequentially.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"lbs {__version__}",
    )

    subparsers = parser.add_subparsers(title="commands", dest="command")
    subparsers.required = True

    # lbs run <config>
    run_parser = subparsers.add_parser("run", help="Run all jobs defined in a config file.")
    run_parser.add_argument("config", help="Path to the YAML config file.")
    run_parser.set_defaults(func=cmd_run)

    # lbs validate <config>
    val_parser = subparsers.add_parser("validate", help="Validate a config file.")
    val_parser.add_argument("config", help="Path to the YAML config file.")
    val_parser.set_defaults(func=cmd_validate)

    # lbs list <config>
    list_parser = subparsers.add_parser("list", help="List jobs defined in a config file.")
    list_parser.add_argument("config", help="Path to the YAML config file.")
    list_parser.set_defaults(func=cmd_list)

    return parser


def main() -> None:
    """Main entry point for the lbs CLI."""
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
