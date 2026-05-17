# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0

"""
Smoke test: verify the CLI entry point is reachable and responds correctly to --help.
"""

import subprocess
import sys


def test_help_exits_cleanly():
    """Running 'python -m lbs --help' should exit with code 0."""
    result = subprocess.run(
        [sys.executable, "-m", "lbs", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_help_mentions_lbs():
    """The --help output should contain the program name 'lbs'."""
    result = subprocess.run(
        [sys.executable, "-m", "lbs", "--help"],
        capture_output=True,
        text=True,
    )
    assert "lbs" in result.stdout


def test_help_lists_subcommands():
    """The --help output should mention all three subcommands."""
    result = subprocess.run(
        [sys.executable, "-m", "lbs", "--help"],
        capture_output=True,
        text=True,
    )
    assert "run" in result.stdout
    assert "validate" in result.stdout
    assert "list" in result.stdout
