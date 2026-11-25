"""A tmux server of its own, where sessions run with no terminal showing them.

Every command names the server (`tmux -L <server> -f <configuration>`), so nothing here
reaches a tmux the user runs. A session starts through a login shell with a clean
environment, as a terminal tab would start it.
"""

import os
import shlex
import subprocess
from pathlib import Path

SHELL = "/bin/zsh"
KEPT = ("HOME", "USER", "LOGNAME", "TMPDIR", "SSH_AUTH_SOCK", "__CF_USER_TEXT_ENCODING")


def packaged_config():
    """The configuration of the server, a data file of the package."""
    return Path(__file__).resolve().parent.parent / "data" / "tmux.conf"


def clean_environment(environ, path):
    """The environment of the server: the login shell it runs adds the user's own.

    Nothing of the process that calls this may leak into the sessions, such as the
    variables of a Claude Code session that asks for another to be opened.
    """
    environment = {name: environ[name] for name in KEPT if name in environ}
    language = environ.get("LANG", "")
    environment.update(
        SHELL=SHELL,
        PATH=path,
        LANG=language if language.upper().endswith("UTF-8") else "en_US.UTF-8",
    )
    return environment


class Tmux:
    """`tool` is where tmux is, `server` its socket name, `path` the PATH of the server."""

    def __init__(self, tool, server, config, path, run=None, environ=None):
        self.tool = tool
        self.server = server
        self.config = str(config)
        self.path = path
        self.runner = run or subprocess.run
        self.environ = os.environ if environ is None else environ

    def words(self, *arguments):
        return [self.tool, "-L", self.server, "-f", self.config] + list(arguments)

    def new_session(self, name, directory, command):
        """What starts a session nobody sees: a command in a detached session, run by a
        login shell because a background service has next to no environment."""
        return self.words(
            "-u", "new-session", "-d", "-s", name, "-x", "200", "-y", "50", "-c", str(directory),
            "%s -lic %s" % (SHELL, shlex.quote(command)),
        )  # fmt: skip

    def attach(self, name):
        """What shows a session in a terminal: a tmux client on that session and no other."""
        # Quoted by hand: zsh takes a word that starts with = for a command to look up,
        # and shlex.quote leaves such a word as it is.
        return "%s -L %s -u attach-session -t '=%s'" % (shlex.quote(self.tool), shlex.quote(self.server), name)

    def attach_command(self, name):
        """What a tab runs to show a session: the tab closes when the client ends."""
        return "exec " + self.attach(name)

    def environment(self):
        return clean_environment(self.environ, self.path)

    def execute(self, words):
        return self.runner(words, capture_output=True, text=True, timeout=30, env=self.environment())

    def run(self, *arguments):
        return self.execute(self.words(*arguments))

    def start(self, name, directory, command):
        return self.execute(self.new_session(name, directory, command))

    def attached(self, name):
        """Whether some tab shows a session."""
        clients = self.run("list-clients", "-t", "=" + name, "-F", "#{client_pid}")
        return clients.returncode == 0 and bool(clients.stdout.strip())

    def pane_text(self, name):
        """What a session shows in its window, as text, wrapped lines joined; None when it
        cannot be read: no such session, no tmux, or tmux does not answer. Only read: no key
        reaches the session."""
        try:
            captured = self.run("capture-pane", "-p", "-J", "-t", "=" + name + ":")
        except (OSError, subprocess.SubprocessError):
            return None
        return captured.stdout if captured.returncode == 0 else None

    def kill_session(self, name):
        return self.run("kill-session", "-t", "=" + name)

    def end_with_its_tab(self, name):
        """From here on the session lives as long as its tab, like one without tmux."""
        return self.run("set-option", "-t", "=" + name + ":", "destroy-unattached", "on")
