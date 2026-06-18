# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.utils.executor – Command execution engine with live output streaming and metadata capture.
"""

from dataclasses import dataclass
import datetime
import os
import queue
import shlex
import signal
import subprocess
import sys
import threading
import time


def _terminate_process(process: subprocess.Popen) -> None:
    """Safely terminates a process group or session in a platform-sensitive manner."""
    if sys.platform == "win32":
        try:
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
    else:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _format_timeout(timeout: float) -> str:
    """Formats a timeout float value to string by stripping trailing
    zeros and decimal points.
    """
    return f"{timeout:.6f}".rstrip("0").rstrip(".")


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
        timeout: float | None = None,
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

            # Spawn subprocess in process group/session for platform-appropriate group termination
            popen_kwargs = {
                "shell": shell,
                "cwd": cwd,
                "env": merged_env,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
            }
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            else:
                popen_kwargs["start_new_session"] = True

            process = subprocess.Popen(popen_cmd, **popen_kwargs)

            # Stream output live using a bounded queue of max size 1000 for backpressure
            if process.stdout:
                q = queue.Queue(maxsize=1000)

                def enqueue_output(out, queue_obj):
                    try:
                        for line in iter(out.readline, b""):
                            queue_obj.put(line)
                    finally:
                        out.close()
                        queue_obj.put(None)

                reader_thread = threading.Thread(
                    target=enqueue_output,
                    args=(process.stdout, q),
                    daemon=True,
                )
                reader_thread.start()

                deadline = (t_start + timeout) if timeout is not None else None
                timed_out = False

                while True:
                    time_left = (
                        deadline -
                        time.perf_counter()) if deadline is not None else None
                    if deadline is not None and time_left <= 0:
                        if process.poll() is not None:
                            timed_out = False
                        else:
                            timed_out = True
                        break

                    try:
                        get_timeout = max(
                            0, time_left) if time_left is not None else None
                        line_bytes = q.get(timeout=get_timeout)
                    except queue.Empty:
                        if process.poll() is not None:
                            timed_out = False
                        else:
                            timed_out = True
                        break

                    if line_bytes is None:
                        break

                    decoded_line = line_bytes.decode("utf-8", errors="replace")

                    if log_file:
                        log_file.write(decoded_line)
                        log_file.flush()

                    if self.verbose:
                        sys.stdout.write(decoded_line)
                        sys.stdout.flush()

                if timed_out:
                    _terminate_process(process)
                    process.wait()

                    # Drain bounded queue so reader thread is not blocked on queue.put
                    while True:
                        try:
                            line_bytes = q.get(timeout=0.5)
                        except queue.Empty:
                            break
                        if line_bytes is None:
                            break

                    formatted_timeout = _format_timeout(timeout)
                    error_message = f"Command timed out after {formatted_timeout} seconds"
                    if log_file:
                        log_file.write(f"[ERROR] {error_message}\n")
                        log_file.flush()
                    if self.verbose:
                        print(f"[ERROR] {error_message}", file=sys.stderr)
                    exit_code = None
                    success = False
                else:
                    # Drain any remaining lines from the queue until the sentinel
                    while True:
                        try:
                            line_bytes = q.get(timeout=0.5)
                        except queue.Empty:
                            break
                        if line_bytes is None:
                            break

                        decoded_line = line_bytes.decode("utf-8",
                                                         errors="replace")
                        if log_file:
                            log_file.write(decoded_line)
                            log_file.flush()
                        if self.verbose:
                            sys.stdout.write(decoded_line)
                            sys.stdout.flush()

                    process.wait()
                    exit_code = process.returncode
                    success = (exit_code == 0)
            else:
                if timeout is not None:
                    try:
                        exit_code = process.wait(timeout=timeout)
                        success = (exit_code == 0)
                    except subprocess.TimeoutExpired:
                        _terminate_process(process)
                        process.wait()
                        formatted_timeout = _format_timeout(timeout)
                        error_message = f"Command timed out after {formatted_timeout} seconds"
                        if log_file:
                            log_file.write(f"[ERROR] {error_message}\n")
                            log_file.flush()
                        if self.verbose:
                            print(f"[ERROR] {error_message}", file=sys.stderr)
                        exit_code = None
                        success = False
                else:
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
