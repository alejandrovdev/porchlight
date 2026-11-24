"""Claude Code's transcripts: where a working directory's sessions are kept and how to
read one while its session is still writing it."""

import json
import os
import re
from pathlib import Path

# The Remote Control server gives its sessions a version 5 id. A run such a session starts
# itself in its worktree (`claude -p`) leaves a transcript with a version 4 id beside it.
SERVER_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}")


def default_root():
    return Path.home() / ".claude" / "projects"


def folder_name(path):
    """The name Claude Code gives the session folder of a working directory."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def folder(root, directory):
    return Path(root) / folder_name(directory)


def entries(lines):
    """The transcript entries among some lines; what is not an entry is skipped."""
    found = []
    for raw in lines:
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if isinstance(entry, dict):
            found.append(entry)
    return found


def read_new(path, offset):
    """The finished transcript lines written after `offset`: (entries, the new offset)."""
    try:
        with open(path, "rb") as handle:
            if os.fstat(handle.fileno()).st_size < offset:
                offset = 0
            handle.seek(offset)
            data = handle.read()
    except OSError:
        return [], offset
    end = data.rfind(b"\n") + 1
    return entries(data[:end].splitlines()), offset + end


def complete_lines(path):
    """The transcript up to its last finished line: the session may be writing one."""
    data = Path(path).read_bytes()
    return data[: data.rfind(b"\n") + 1]


def finished_lines(data):
    """Split what was read into its finished lines and the unfinished rest."""
    *lines, rest = data.split(b"\n")
    return lines, rest


def server_transcripts(session_folder):
    """The transcripts of server sessions in one folder, by name."""
    return [path for path in sorted(Path(session_folder).glob("*.jsonl")) if SERVER_ID.fullmatch(path.stem)]


def server_transcript(session_folder):
    """The transcript of the server session of a folder, or None while it has none."""
    found = sorted(server_transcripts(session_folder), key=lambda path: path.stat().st_mtime)
    return found[-1] if found else None
