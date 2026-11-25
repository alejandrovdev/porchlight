"""The Remote Control server of a project: what lets the Claude mobile app create and
archive sessions on the Mac. Each session gets its own git worktree and runs with the
user's own Claude Code configuration.

    run(project, mac)   become the server (what a background service runs)

The server's sessions have no terminal and the app cannot start one again once it is
archived: `view_tabs` shows each in a read-only tab and `resume_list` keeps a copy that
`/resume` lists.

Never run two servers for the same repository at once: whatever starts `run` keeps it to
one. And never change the settings file while the server runs (see `session_settings`):
a change waits and `run` installs it the next time the server starts.

Keeping the Mac awake is not the server's: see `keep_awake`.
"""

import os

from .. import names, session_settings
from ..atoms import tools


def command(project, claude, settings):
    return [
        claude,
        "remote-control",
        "--spawn",
        "worktree",
        "--permission-mode",
        project.permission_mode,
        "--settings",
        str(settings),
        "--no-create-session-in-dir",
    ]


def environment(environ):
    """The environment of the server and its sessions. A background service starts with
    a minimal PATH: Homebrew's folders come first, then whatever was there."""
    return dict(environ, PATH=tools.search_path(environ.get("PATH", "")))


def run(project, mac, execute=None, chdir=None):
    """Start the server in the project's folder; this process becomes the server."""
    claude = mac.claude
    settings = mac.settings(project)
    session_settings.stage(project, settings)
    session_settings.install_pending(settings)  # no server runs yet: what waited goes in now
    (chdir or os.chdir)(names.repository(project))
    (execute or os.execve)(claude, command(project, claude, settings), environment(mac.environ))
