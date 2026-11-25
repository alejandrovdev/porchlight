"""A log file: dated lines, appended. Writing one never fails its caller.

A message that repeats the log's last one is not written again: what happens on every pass
(a folder that is missing, a tool that is not installed) takes one line until it changes.
"""

import os
import re
import time
from pathlib import Path

STAMP = "%Y-%m-%d %H:%M:%S "
STAMPED = re.compile(rb"(?:\A|\n)\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \Z")
STAMP_BYTES = 20


def ends_with(path, message):
    """Whether the last thing a log says is this very message."""
    wanted = (message + "\n").encode("utf8")
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            # The message, its date and the end of the line before it.
            handle.seek(max(0, handle.tell() - len(wanted) - STAMP_BYTES - 1))
            tail = handle.read()
    except OSError:
        return False
    return tail.endswith(wanted) and STAMPED.search(tail[: -len(wanted)]) is not None


def write(path, message):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        if ends_with(path, message):
            return
        with open(path, "a", encoding="utf8") as handle:
            handle.write(time.strftime(STAMP) + message + "\n")
    except OSError:
        pass
