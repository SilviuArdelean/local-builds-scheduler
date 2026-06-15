# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Unit tests for the command executor module (lbs.executor).
"""

import datetime
import io
import os
import sys
from unittest.mock import patch
from lbs.utils.executor import JobExecutor, CommandResult


def test_executor_success(tmp_path):
    """Verify a successful command execution and metadata capture."""
    executor = JobExecutor(verbose=False)
    log_file = io.StringIO()
    
    # Run a simple python echo script
    py_cmd = f'"{sys.executable}" -c "print(\'exec-success-out\')"'
    
    start_run = datetime.datetime.now()
    result = executor.run_command(py_cmd, cwd=str(tmp_path), log_file=log_file)
    end_run = datetime.datetime.now()
    
    assert result.success is True
    assert result.exit_code == 0
    assert result.command == py_cmd
    assert result.error_message is None
    
    # Assert timestamps are captured
    assert start_run <= result.start_time <= end_run
    assert start_run <= result.end_time <= end_run
    assert result.duration >= 0
    
    # Assert logs are written
    log_content = log_file.getvalue()
    assert "exec-success-out" in log_content


def test_executor_verbose_mirroring(tmp_path, capsys):
    """Verify that verbose mode correctly mirrors output to stdout, and non-verbose does not."""
    py_cmd = f'"{sys.executable}" -c "print(\'mirror-me\')"'
    
    # Case 1: verbose=False (should not mirror to console)
    executor_quiet = JobExecutor(verbose=False)
    log_file_quiet = io.StringIO()
    executor_quiet.run_command(py_cmd, cwd=str(tmp_path), log_file=log_file_quiet)
    
    captured_quiet = capsys.readouterr()
    assert "mirror-me" not in captured_quiet.out
    assert "mirror-me" in log_file_quiet.getvalue()
    
    # Case 2: verbose=True (should mirror to console)
    executor_verbose = JobExecutor(verbose=True)
    log_file_verbose = io.StringIO()
    executor_verbose.run_command(py_cmd, cwd=str(tmp_path), log_file=log_file_verbose)
    
    captured_verbose = capsys.readouterr()
    assert "mirror-me" in captured_verbose.out
    assert "mirror-me" in log_file_verbose.getvalue()


def test_executor_command_failure(tmp_path):
    """Verify metadata when a command exits with a non-zero code."""
    executor = JobExecutor(verbose=False)
    log_file = io.StringIO()
    
    py_cmd = f'"{sys.executable}" -c "import sys; sys.exit(99)"'
    
    result = executor.run_command(py_cmd, cwd=str(tmp_path), log_file=log_file)
    
    assert result.success is False
    assert result.exit_code == 99
    assert result.error_message is None
    assert result.duration >= 0


def test_executor_missing_cwd(tmp_path):
    """Verify error handling when the cwd directory does not exist."""
    executor = JobExecutor(verbose=False)
    log_file = io.StringIO()
    
    missing_dir = tmp_path / "does_not_exist_folder"
    py_cmd = f'"{sys.executable}" -c "print(1)"'
    
    result = executor.run_command(py_cmd, cwd=str(missing_dir), log_file=log_file)
    
    assert result.success is False
    assert result.exit_code is None
    assert result.error_message is not None
    assert "Working directory does not exist" in result.error_message
    
    log_content = log_file.getvalue()
    assert "[ERROR] Working directory does not exist" in log_content


def test_executor_shell_launch_failure(tmp_path):
    """Verify error handling when subprocess.Popen fails with OSError."""
    executor = JobExecutor(verbose=False)
    log_file = io.StringIO()
    
    py_cmd = f'"{sys.executable}" -c "print(1)"'
    
    with patch("subprocess.Popen", side_effect=OSError("Mocked OS failure")):
        result = executor.run_command(py_cmd, cwd=str(tmp_path), log_file=log_file)
        
    assert result.success is False
    assert result.exit_code is None
    assert result.error_message is not None
    assert "Failed to launch shell command: Mocked OS failure" in result.error_message
    
    log_content = log_file.getvalue()
    assert "[ERROR] Failed to launch shell command" in log_content


def test_executor_shell_false(tmp_path):
    """Verify execution with shell=False uses shlex.split and executes safely."""
    executor = JobExecutor(verbose=False)
    log_file = io.StringIO()
    
    py_cmd = f'"{sys.executable}" -c "print(\'no-shell-worked\')"'
    
    result = executor.run_command(py_cmd, cwd=str(tmp_path), log_file=log_file, shell=False)
    
    assert result.success is True
    assert result.exit_code == 0
    assert "no-shell-worked" in log_file.getvalue()

