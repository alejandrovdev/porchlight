"""The terminal's tab opener: what porchlight asks of a terminal app, and the answers of
Warp and of Terminal, the terminal macOS comes with.

A terminal is asked three things only: whether its app is installed, whether it runs, and
to open a tab that runs one command. Nothing here starts the app; whoever opens a tab asks
`runs` first.
"""

import json
import shlex
import subprocess
import time
import unicodedata
from pathlib import Path


class Terminal:
    """What a terminal app must do for porchlight."""

    name = ""  # as the configuration file names it
    title = ""  # as a person names it

    def installed(self):
        """Whether the app is on this Mac. Nothing is started to find out."""
        raise NotImplementedError

    def runs(self, ps_text):
        """Whether the app is running, from the process list."""
        raise NotImplementedError

    def open_tab(self, name, title, directory, command, started, attempts=1, patience=25.0):
        """Open a tab that runs a command in a folder.

        `started` tells whether the command is running; it is asked for `patience` seconds
        after each of the `attempts`. Returns what it found, or 0. Raises OSError or
        subprocess.SubprocessError when the tab cannot be asked for.
        """
        raise NotImplementedError


def without_controls(text):
    """Text without control characters: TOML refuses some of them unescaped (DEL), and
    none of them belongs in a tab's title."""
    return "".join(character for character in text if unicodedata.category(character) != "Cc")


def tab_config(name, title, directory, command):
    """A Warp tab configuration with one terminal that runs one command. The title comes
    from text typed on the phone: it loses its control characters."""

    def quoted(text):
        # A JSON string is a valid TOML basic string once DEL, which JSON leaves as it is
        # and TOML refuses, is escaped too.
        return json.dumps(text, ensure_ascii=False).replace("\x7f", "\\u007f")

    title = without_controls(title)

    return (
        "name = %s\ntitle = %s\n\n"
        '[[panes]]\nid = "main"\ntype = "terminal"\ndirectory = %s\ncommands = [%s]\n'
    ) % (quoted(name), quoted(title), quoted(directory), quoted(command))


class Warp(Terminal):
    """Warp offers no way to list or close its tabs, so a tab closes only because the
    program it runs ends. A tab opens from a configuration file, read through a link."""

    name = "warp"
    title = "Warp"
    APP = "Warp.app"
    PROCESS = "/" + APP + "/Contents/MacOS/stable"
    SETTLE = 1.5  # Warp reads a new configuration a moment after it is written

    def __init__(self, configs=None, run=subprocess.run, clock=time.time, sleep=time.sleep, applications=None):
        self.configs = Path(configs) if configs else Path.home() / ".warp" / "tab_configs"
        self.run = run
        self.clock = clock
        self.sleep = sleep
        # Where a Mac keeps its apps: everyone's, then the user's own.
        self.applications = applications or (Path("/Applications"), Path.home() / "Applications")

    def installed(self):
        return any((Path(folder) / self.APP).is_dir() for folder in self.applications)

    def runs(self, ps_text):
        return any(self.PROCESS in line for line in ps_text.splitlines())

    def open_tab(self, name, title, directory, command, started, attempts=1, patience=25.0):
        config = self.configs / (name + ".toml")
        try:
            self.configs.mkdir(parents=True, exist_ok=True)
            config.write_text(tab_config(name, title, str(directory), command), encoding="utf8")
            for _ in range(attempts):
                self.sleep(self.SETTLE)
                self.run(["/usr/bin/open", "-g", "warp://tab_config/" + name], timeout=15)
                deadline = self.clock() + patience
                while self.clock() < deadline:
                    found = started()
                    if found:
                        return found
                    self.sleep(0.5)
            return 0
        finally:
            try:
                config.unlink()
            except OSError:
                pass


class AppleTerminal(Terminal):
    """Terminal, the app macOS comes with. Each tab is a new window, opened through
    AppleScript's `do script`: the window's shell runs `cd <folder> && <command>`, and with
    a command that starts with `exec` the session is the window's shell, so the window
    ends with it (closing it is the profile's "When the shell exits" setting).

    Titles come from text typed on the phone: every value reaches AppleScript as an item
    of `argv` on osascript's command line, never inside the script's text."""

    name = "apple-terminal"
    title = "Terminal"
    APP = "Terminal.app"
    PROCESS = "/" + APP + "/Contents/MacOS/Terminal"
    SCRIPT = (
        "on run argv\n"
        '  tell application "Terminal"\n'
        "    set opened to do script (item 1 of argv)\n"
        "    set custom title of opened to (item 2 of argv)\n"
        "  end tell\n"
        "end run"
    )

    def __init__(self, run=subprocess.run, clock=time.time, sleep=time.sleep, applications=None):
        self.run = run
        self.clock = clock
        self.sleep = sleep
        self.applications = tuple(applications or (Path("/System/Applications/Utilities"),))

    def installed(self):
        return any((Path(folder) / self.APP).is_dir() for folder in self.applications)

    def runs(self, ps_text):
        return any(self.PROCESS in line for line in ps_text.splitlines())

    def open_tab(self, name, title, directory, command, started, attempts=1, patience=25.0):
        shell = "cd -- %s && %s" % (shlex.quote(str(directory)), command)
        if "\0" in shell:
            raise OSError("Terminal opened no window: the folder or the command holds a NUL byte")
        # `--` ends osascript's options: a value that starts with "-" stays an argument. A NUL
        # cannot be part of an argument, and a title loses nothing without it.
        words = ["/usr/bin/osascript", "-e", self.SCRIPT, "--", shell, title.replace("\0", "")]
        for _ in range(attempts):
            done = self.run(words, capture_output=True, text=True, timeout=15)
            if done.returncode != 0:
                said = (done.stderr or "").strip().splitlines()
                raise subprocess.SubprocessError("Terminal opened no window: %s" % (said[-1] if said else done.returncode))
            deadline = self.clock() + patience
            while self.clock() < deadline:
                found = started()
                if found:
                    return found
                self.sleep(0.5)
        return 0


TERMINALS = {Warp.name: Warp, AppleTerminal.name: AppleTerminal}


def named(name, **options):
    """The opener of the terminal a configuration names; None when it names none."""
    return TERMINALS[name](**options) if name else None
