"""The Mac as the features see it: the atoms, gathered and named for one install.

A feature receives a project and a `Mac` and asks the Mac for everything it touches: the
process list, git, tmux, the terminal, the clock, the state and the log. Tools are looked
for when first needed, so a project that uses no hidden session needs no tmux. A test
passes a Mac whose parts are stand-ins.
"""

import os
import subprocess
import time
from functools import cached_property
from pathlib import Path

from . import names
from .atoms import invocation, launchd, logs, processes, state, terminal, tmux, tools, transcripts, worktrees
from .atoms.state import Store


class Mac:
    def __init__(self, terminal=None, environ=None, config_file=None):
        self.terminal = terminal  # None: no tab ever opens
        self.environ = os.environ if environ is None else environ
        self.config_file = config_file  # the configuration file in use; None: whatever the environment says

    @classmethod
    def of(cls, configuration, environ=None, config_file=None):
        """The Mac of a configuration: its terminal, the environment's folders and tools."""
        environ = os.environ if environ is None else environ
        options = {}
        if configuration.terminal == terminal.Warp.name and names.chosen("warp_tab_configs", environ):
            options["configs"] = names.chosen("warp_tab_configs", environ)
        return cls(terminal.named(configuration.terminal, **options), environ, config_file)

    def tool(self, name):
        return tools.need(name, override=names.chosen(name, self.environ), path=self.environ.get("PATH"))

    def terminal_app(self, name):
        """The opener of a terminal app porchlight supports, to ask whether it is installed."""
        return terminal.named(name)

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

    def own_command(self):
        """What runs porchlight as this process does: (its words, the environment they
        need). The installed command, else this very copy; and what makes it read the
        configuration file and the folders this process reads."""
        words, environment = invocation.words(names.TOOL, path=self.environ.get("PATH"))
        return words, dict(environment, **names.carried(self.environ, self.config_file))

    @cached_property
    def porchlight(self):
        """The command that runs porchlight, as a shell reads it: what a tab runs and what
        a session is told to run."""
        return invocation.shell(*self.own_command())

    @cached_property
    def launchd(self):
        return launchd.Launchd()

    @property
    def launch_agents(self):
        """The folder that keeps the definitions of the background agents."""
        return names.launch_agents(self.environ)

    @property
    def transcripts(self):
        """Where Claude Code keeps the sessions of every working directory."""
        return Path(names.chosen("transcripts_dir", self.environ) or transcripts.default_root())

    def processes(self):
        return processes.listing()

    def command_of(self, pid):
        return processes.command_of(pid)

    def output(self, words, any_exit=False):
        """What a command prints, such as a tool's help; None when it cannot be run, or when
        it fails unless `any_exit`."""
        return processes.output(words, any_exit=any_exit)

    def terminate(self, pid):
        processes.terminate(pid)

    def pid(self):
        return os.getpid()

    def spawn(self, words):
        """Start a program beside this one, with nothing to read and nowhere to print."""
        nowhere = subprocess.DEVNULL
        return subprocess.Popen(list(words), stdin=nowhere, stdout=nowhere, stderr=nowhere)

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

    def make_state_root(self):
        """The tool's state folder, made and marked as the tool's when it is not there: a
        purge deletes only in a folder the tool made."""
        return state.claim(names.state_root(self.environ), names.MARKER)

    def make_log_root(self):
        """The tool's log folder, made and marked as the tool's when it is not there."""
        return state.claim(names.log_root(self.environ), names.MARKER)

    def recorded_projects(self):
        """The name of every project that has a folder in the tool's state, configured or not."""
        try:
            entries = sorted((names.state_root(self.environ) / "projects").iterdir())
        except OSError:
            return []
        return [entry.name for entry in entries if entry.is_dir() and names.PROJECT_NAME.fullmatch(entry.name)]

    def store(self, project, kind):
        return Store(names.state_file(project, kind, self.environ), prepare=self.make_state_root)

    def settings(self, project):
        return names.settings_file(project, self.environ)

    def log(self, project, message):
        try:
            self.make_log_root()
        except OSError:
            pass  # writing a log never fails its caller
        logs.write(names.log_file(project, self.environ), message)
