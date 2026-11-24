"""The processes of the Mac: the list, its lines, one process's command, ending one."""

import os
import signal
import subprocess

PS = "/bin/ps"


def listing(run=subprocess.run):
    """Every process as "<pid> <command>", one per line."""
    return run([PS, "-axo", "pid=,command="], capture_output=True, text=True, timeout=15).stdout


def rows(ps_text):
    """The processes of a list: (pid, program, arguments)."""
    for line in ps_text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            yield int(parts[0]), parts[1], parts[2:]


def command_of(pid, run=subprocess.run):
    """The command of one process, empty once it ended; None when ps cannot tell."""
    try:
        return run([PS, "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def terminate(pid):
    os.kill(pid, signal.SIGTERM)
