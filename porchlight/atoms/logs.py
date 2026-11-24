"""A log file: dated lines, appended. Writing one never fails its caller."""

import time
from pathlib import Path


def write(path, message):
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf8") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")
    except OSError:
        pass
