# Local Builds Scheduler
# Copyright 2026 Silviu Ardelean
# SPDX-License-Identifier: Apache-2.0
"""
lbs.utils.sanitizer – Console and log output sanitization for child process streams.
"""

from __future__ import annotations

import re

# Matches ANSI/VT100 escape sequences:
# 1. OSC / DCS / SOS / PM / APC string sequences terminated by BEL (\x07), ST (\x1b\\), or end-of-line
# 2. CSI sequences: ESC [ <parameter bytes 0x30-0x3F>* <intermediate bytes 0x20-0x2F>* <final byte 0x40-0x7E>
# 3. Two-byte / intermediate ESC sequences (e.g. ESC 7, ESC 8, ESC ( B, ESC M) and stray bare ESC
_ESC_SEQUENCE_RE = re.compile(
    r"\x1b[\]PX^_][^\x07\x1b\r\n]*(?:\x07|\x1b\\)?"
    r"|\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b[ -/]*[0-~]"
    r"|\x1b"
)

# Matches C0 control characters (0x00-0x1F) and DEL (0x7F),
# excluding backspace (\x08), tab (\x09), and newline (\x0a).
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x07\x0b-\x1f\x7f]")

# Matches one or more carriage returns immediately followed by a newline.
_CR_LF_RE = re.compile(r"\r+\n")


def _apply_backspaces_in_line(line: str) -> str:
    """Applies '\\b' (0x08) as an erase of the previous character within a single line."""
    if "\x08" not in line:
        return line
    buf: list[str] = []
    for ch in line:
        if ch == "\x08":
            if buf:
                buf.pop()
        else:
            buf.append(ch)
    return "".join(buf)


def sanitize_console_output(text: str) -> str:
    """Sanitizes child process output before writing to the console or log file.

    - Strips ANSI/VT100 ESC sequences (CSI, OSC, DEC save/restore, etc.).
    - Normalizes '\\r\\n' (and '\\r+\\n') to '\\n', and converts bare '\\r' to '\\n'
      so carriage-return progress updates do not overwrite earlier text on the row.
    - Drops C0 control characters and DEL (0x7F) except '\\n' and '\\t'.
    - Resolves '\\b' within each line by erasing the preceding character on that line
      (collapsing Clink's 'C\\bL\\bI\\bN\\bK\\b \\b' AutoRun sequences cleanly).
    """
    if not text:
        return ""

    # 1. Strip ESC sequences first so backspaces following ANSI codes apply to visible text
    cleaned = _ESC_SEQUENCE_RE.sub("", text)

    # 2. Normalize CRLF variations and bare CRs to '\n'
    if "\r" in cleaned:
        cleaned = _CR_LF_RE.sub("\n", cleaned)
        cleaned = cleaned.replace("\r", "\n")

    # 3. Strip remaining non-printable C0 controls (except \b, \t, \n) and DEL
    cleaned = _CONTROL_CHARS_RE.sub("", cleaned)

    # 4. Resolve backspaces per line so '\b' never erases across line boundaries
    if "\x08" in cleaned:
        lines = cleaned.split("\n")
        cleaned = "\n".join(_apply_backspaces_in_line(line) for line in lines)

    return cleaned

