"""The Claude Code settings file a project's sessions start with (`--settings <file>`).

The Remote Control server records the file's checksum when it starts and refuses every
new session once the file differs. So a change is never written over the file: it waits
beside it, as `settings.json.next`, and is installed the next time the server starts.

The file carries the project's permission mode and nothing else: every other setting is
the person's own, in their Claude Code settings.
"""

import json
import os
from pathlib import Path


def content(project):
    return {"permissions": {"defaultMode": project.permission_mode}}


def text(project):
    return json.dumps(content(project), indent=2) + "\n"


def waiting(path):
    return Path(str(path) + ".next")


def stage(project, path):
    """Make the file say what the project asks: in place when it is new, waiting otherwise."""
    path = Path(path)
    wanted = text(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = path.read_text(encoding="utf8")
    except OSError:
        current = None
    if current is None:
        draft = Path(str(path) + ".writing")
        draft.write_text(wanted, encoding="utf8")
        os.replace(draft, path)
    elif current == wanted:
        try:
            waiting(path).unlink()
        except OSError:
            pass
    else:
        waiting(path).write_text(wanted, encoding="utf8")


def install_pending(path):
    """Install a change that waits; True when one did. Only for when no server runs."""
    try:
        os.replace(waiting(path), path)
    except OSError:
        return False
    return True


def bring_up_to_date(project, path):
    """Make a file that exists say what the project asks, at once; True when it changed.
    Only for when no server runs. A project that has no file yet gets none: its first
    session writes it."""
    if not Path(path).exists():
        return False
    stage(project, path)
    return install_pending(path)
