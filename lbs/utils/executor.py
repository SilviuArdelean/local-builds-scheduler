# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.utils.executor – Command execution engine with live output streaming and metadata capture.
"""

from dataclasses import dataclass
import datetime
import os
import shlex
import subprocess
import sys
import time


@dataclass
class CommandResult:
    """Detailed result of a single command execution."""
    command: str
    exit_code: int | None
    start_time: datetime.datetime
    end_time: datetime.datetime
    duration: float
    success: bool
    error_message: str | None = None


class JobExecutor:
    """Executes build commands sequentially, streams live output, and captures metadata."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def run_command(
        self,
        cmd: str,
        cwd: str,
        env: dict[str, str] | None = None,
        log_file=None,
        shell: bool = True,
    ) -> CommandResult:
        """
        Execute a shell or direct command inside cwd with environment overlays.
        Streams stdout/stderr live to log_file and console (if verbose).
        Handles process start exceptions cleanly.

        Security Tradeoff Note:
        By default, shell=True is enabled to support shell builtins, batch files,
        command chaining (e.g. &&), and pipelines in developer workflows.
        If executing untrusted input, set shell=False to prevent shell injection.
        """
        start_time = datetime.datetime.now()
        t_start = time.perf_counter()

        # Prepare merged environment
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        exit_code = None
        success = False
        error_message = None

        try:
            if not os.path.isdir(cwd):
                raise FileNotFoundError(
                    f"Working directory does not exist: {cwd}")

            # If shell execution is disabled, split command string into arguments list
            popen_cmd = shlex.split(cmd) if not shell else cmd

            # Spawn subprocess
            process = subprocess.Popen(
                popen_cmd,
                shell=shell,
                cwd=cwd,
                env=merged_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )

            # Stream output live
            if process.stdout:
                for line in iter(process.stdout.readline, b""):
                    decoded_line = line.decode("utf-8", errors="replace")

                    if log_file:
                        log_file.write(decoded_line)
                        log_file.flush()

                    if self.verbose:
                        sys.stdout.write(decoded_line)
                        sys.stdout.flush()

            process.wait()
            exit_code = process.returncode
            success = (exit_code == 0)

        except FileNotFoundError as e:
            error_message = str(e)
            if log_file:
                log_file.write(f"[ERROR] {error_message}\n")
                log_file.flush()
            if self.verbose:
                print(f"[ERROR] {error_message}", file=sys.stderr)

        except OSError as e:
            error_message = f"Failed to launch shell command: {e}"
            if log_file:
                log_file.write(f"[ERROR] {error_message}\n")
                log_file.flush()
            if self.verbose:
                print(f"[ERROR] {error_message}", file=sys.stderr)

        except Exception as e:
            error_message = f"Unexpected execution error: {e}"
            if log_file:
                log_file.write(f"[ERROR] {error_message}\n")
                log_file.flush()
            if self.verbose:
                print(f"[ERROR] {error_message}", file=sys.stderr)

        t_end = time.perf_counter()
        end_time = datetime.datetime.now()
        duration = t_end - t_start

        return CommandResult(command=cmd,
                             exit_code=exit_code,
                             start_time=start_time,
                             end_time=end_time,
                             duration=duration,
                             success=success,
                             error_message=error_message)
