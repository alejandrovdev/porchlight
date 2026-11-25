"""The Mac as the features see it: the atoms, gathered and named for one install.

A feature receives a project and a `Mac` and asks the Mac for everything it touches: the
process list, git, tmux, the terminal, the clock, the state and the log. Tools are looked
for when first needed, so a project that uses no hidden session needs no tmux. A test
passes a Mac whose parts are stand-ins.
"""

import os
import time
from functools import cached_property
from pathlib import Path

from . import names
from .atoms import invocation, logs, processes, terminal, tmux, tools, transcripts, worktrees
from .atoms.state import Store


class Mac:
    def __init__(self, terminal=None, environ=None):
        self.terminal = terminal  # None: no tab ever opens
        self.environ = os.environ if environ is None else environ

    @classmethod
    def of(cls, configuration, environ=None):
        """The Mac of a configuration: its terminal, the environment's folders and tools."""
        environ = os.environ if environ is None else environ
        options = {}
        if names.chosen("warp_tab_configs", environ):
            options["configs"] = names.chosen("warp_tab_configs", environ)
        return cls(terminal.named(configuration.terminal, **options), environ)

    def tool(self, name):
        return tools.need(name, override=names.chosen(name, self.environ), path=self.environ.get("PATH"))

    @cached_property
    def claude(self):
        return self.tool("claude")

    @cached_property
    def git(self):
        return worktrees.Git(self.tool("git"))

    @cached_property
    def tmux(self):
        return tmux.Tmux(
            self.tool("tmux"),
            names.tmux_server(self.environ),
            tmux.packaged_config(),
            tools.search_path(),
            environ=self.environ,
        )

    @cached_property
    def porchlight(self):
        """The command that runs porchlight, as a shell reads it: what a tab runs and what
        a session is told to run. The installed command, else this very copy."""
        return invocation.shell(*invocation.words(names.TOOL, path=self.environ.get("PATH")))

    @property
    def transcripts(self):
        """Where Claude Code keeps the sessions of every working directory."""
        return Path(names.chosen("transcripts_dir", self.environ) or transcripts.default_root())

    def processes(self):
        return processes.listing()

    def command_of(self, pid):
        return processes.command_of(pid)

    def output(self, words):
        """What a command prints, such as a tool's help; None when it cannot be run."""
        return processes.output(words)

    def terminate(self, pid):
        processes.terminate(pid)

    def clock(self):
        return time.time()

    def sleep(self, seconds):
        time.sleep(seconds)

    def wait_for(self, check, seconds):
        """What `check` finds within some seconds, asked twice a second; 0 when nothing."""
        deadline = self.clock() + seconds
        while self.clock() < deadline:
            found = check()
            if found:
                return found
            self.sleep(0.5)
        return 0

    def store(self, project, kind):
        return Store(names.state_file(project, kind, self.environ))

    def settings(self, project):
        return names.settings_file(project, self.environ)

    def log(self, project, message):
        logs.write(names.log_file(project, self.environ), message)
