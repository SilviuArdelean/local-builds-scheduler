# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
Pytest configuration and environment workarounds for Windows / Python 3.14+.
"""

import os
import sys

if sys.platform == "win32":
    # Python 3.14 on Windows restricts DACL when mode=0o700 is passed to os.mkdir,
    # causing subsequent os.scandir calls by pytest's tmp_path cleanup to fail with PermissionError.
    _orig_mkdir = os.mkdir

    def _safe_mkdir(path, mode=0o777, *args, **kwargs):
        if mode == 0o700:
            mode = 0o777
        return _orig_mkdir(path, mode, *args, **kwargs)

    os.mkdir = _safe_mkdir
