# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit and integration tests for the single-instance locking mechanism (lbs.utils.lock).
"""

import sys
import subprocess
import yaml
from lbs.utils.lock import FileLock


def test_lock_prevents_double_runs(tmp_path):
    """Verify that a second concurrent instance is blocked by the lock and exits with code 2."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    lock_path = log_dir / "lbs.lock"

    config_file = tmp_path / "config.yaml"
    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [{
            "name":
            "job-1",
            "cwd":
            str(tmp_path),
            "commands":
            [f'"{sys.executable}" -c "import time; time.sleep(1)"']
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    # Acquire lock in test process
    with FileLock(lock_path):
        # Spawning second concurrent instance
        result = subprocess.run(
            [sys.executable, "-m", "lbs", "run",
             str(config_file)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 2
        assert "Another Local Builds Scheduler instance is already running." in result.stderr


def test_lock_released_allows_subsequent_runs(tmp_path):
    """Verify that after the first instance terminates, the lock is released and subsequent runs can succeed."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    config_file = tmp_path / "config.yaml"
    config_data = {
        "settings": {
            "log_dir": str(log_dir)
        },
        "jobs": [{
            "name": "job-1",
            "cwd": str(tmp_path),
            "commands": ["echo 1"]
        }]
    }
    config_file.write_text(yaml.safe_dump(config_data), encoding="utf-8")

    # First execution run
    result1 = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result1.returncode == 0

    # Second execution run (sequential) should work fine
    result2 = subprocess.run(
        [sys.executable, "-m", "lbs", "run",
         str(config_file)],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result2.returncode == 0
