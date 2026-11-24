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
"""

import os
import subprocess

from .. import names, session_settings
from ..atoms import tools

CAFFEINATE = "/usr/bin/caffeinate"


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


def keep_awake_command(pid):
    """Keep the Mac awake while a process runs, on AC power only (-s). The display still
    sleeps, and on battery the Mac sleeps as usual. It ends when that process does."""
    return [CAFFEINATE, "-s", "-w", str(pid)]


def environment(environ):
    """The environment of the server and its sessions. A background service starts with
    a minimal PATH: Homebrew's folders come first, then whatever was there."""
    return dict(environ, PATH=tools.search_path(environ.get("PATH", "")))


def run(project, mac, keep_awake=True, execute=os.execve, spawn=subprocess.Popen, chdir=os.chdir, pid=os.getpid):
    """Start the server in the project's folder; this process becomes the server."""
    claude = mac.claude
    settings = mac.settings(project)
    session_settings.stage(project, settings)
    session_settings.install_pending(settings)  # no server runs yet: what waited goes in now
    chdir(names.repository(project))
    if keep_awake:
        try:
            spawn(keep_awake_command(pid()))
        except OSError as error:
            mac.log(project, "could not keep the Mac awake: %r" % (error,))
    execute(claude, command(project, claude, settings), environment(mac.environ))
