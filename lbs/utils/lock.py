# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.utils.lock – Cross-platform file lock for preventing concurrent execution.
"""

import errno
import sys
from pathlib import Path


class LockError(Exception):
    """Raised when the file lock cannot be acquired."""
    pass


class FileLock:
    """
    Cross-platform non-blocking file lock.
    Uses fcntl.flock on POSIX and msvcrt.locking on Windows.
    """

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.fd = None

    def __enter__(self):
        # Open lock file in write mode
        self.fd = open(self.lock_path, "w", encoding="utf-8")
        try:
            if sys.platform == "win32":
                import msvcrt
                # Seek to start and lock 1 byte in non-blocking write mode
                self.fd.seek(0)
                msvcrt.locking(self.fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                # Acquire non-blocking exclusive lock
                fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as e:
            # Clean up the file handle
            try:
                self.fd.close()
            except Exception:
                pass
            self.fd = None

            # Only translate expected lock contention errors
            contention_errnos = {
                errno.EACCES,      # Windows lock violation
                errno.EDEADLK,     # Windows deadlock
                errno.EAGAIN,      # POSIX flock conflict
                errno.EWOULDBLOCK, # POSIX flock conflict
            }
            if isinstance(e, OSError) and e.errno in contention_errnos:
                raise LockError(
                    "Another Local Builds Scheduler instance is already running."
                ) from e
            raise
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.fd:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    self.fd.seek(0)
                    msvcrt.locking(self.fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            finally:
                try:
                    self.fd.close()
                except Exception:
                    pass
                self.fd = None
