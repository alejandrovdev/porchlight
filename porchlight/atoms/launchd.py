"""launchd's agents of the person who is logged in: what starts a program at login and keeps
it running.

    definition(label, words, environment, log)   what launchd is told about one agent
    file(folder, label), read, write, remove     the property list that holds it
    labels(folder)                               the agents that have a file in a folder
    Launchd().loaded()                           the labels launchd has loaded
    Launchd().load(path), .unload(label)         start one from its file, stop one

An agent is loaded from a file and from then on known by its label. Unloading one stops its
program; the file stays until it is removed, and launchd loads it again at the next login.
"""

import os
import plistlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

LAUNCHCTL = "/bin/launchctl"
SUFFIX = ".plist"


class Unavailable(Exception):
    """launchd could not be asked what it has loaded."""


def default_folder():
    """Where a person's own agents are kept."""
    return Path.home() / "Library" / "LaunchAgents"


def definition(label, words, environment, log, directory=None, outlived=False, throttle=None):
    """An agent that starts at login and is started again whenever it ends.

    `outlived`: what the program started is left running when the agent stops, instead of
    being ended with it. `throttle`: the seconds launchd waits between two starts.
    """
    told = {
        "Label": label,
        "ProgramArguments": [str(word) for word in words],
        "EnvironmentVariables": {name: str(value) for name, value in environment.items()},
        "RunAtLoad": True,
        "KeepAlive": True,
        # As an app: what it starts is worked in by a person, and must not be slowed down.
        "ProcessType": "Interactive",
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
    }
    if directory is not None:
        told["WorkingDirectory"] = str(directory)
    if outlived:
        told["AbandonProcessGroup"] = True
    if throttle is not None:
        told["ThrottleInterval"] = int(throttle)
    return told


def file(folder, label):
    return Path(folder) / (label + SUFFIX)


def read(path):
    """The definition in a file; None when there is none or it cannot be read."""
    try:
        with open(path, "rb") as handle:
            told = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    return told if isinstance(told, dict) else None


def write(path, told):
    """Write a definition, replacing the file in one step."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_name(path.name + ".writing")
    draft.write_bytes(plistlib.dumps(told, fmt=plistlib.FMT_XML, sort_keys=True))
    os.replace(draft, path)


def remove(path):
    try:
        Path(path).unlink()
    except FileNotFoundError:
        pass


def labels(folder):
    """The labels that have a file in a folder, by name."""
    try:
        entries = sorted(Path(folder).iterdir())
    except OSError:
        return []
    return [entry.name[: -len(SUFFIX)] for entry in entries if entry.name.endswith(SUFFIX) and entry.is_file()]


class Launchd:
    """`run` stands in for subprocess.run, and `uid` for who is logged in."""

    def __init__(self, run=subprocess.run, uid=os.getuid):
        self.run = run
        self.uid = uid

    def domain(self):
        """Where a person's own agents live: their graphical session."""
        return "gui/%d" % self.uid()

    def ask(self, *words):
        try:
            return self.run([LAUNCHCTL] + list(words), capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as error:
            return SimpleNamespace(returncode=1, stdout="", stderr=repr(error))

    def loaded(self):
        """Every label launchd has loaded for this person. Raises Unavailable when it cannot tell."""
        answer = self.ask("list")
        if answer.returncode != 0:
            raise Unavailable(answer.stderr.strip() or "launchctl list failed")
        found = set()
        for line in answer.stdout.splitlines()[1:]:  # after the heading: pid, last status, label
            columns = line.split("\t")
            if len(columns) == 3 and columns[2]:
                found.add(columns[2])
        return found

    def is_loaded(self, label):
        return self.ask("print", "%s/%s" % (self.domain(), label)).returncode == 0

    def load(self, path):
        return self.ask("bootstrap", self.domain(), str(path))

    def unload(self, label):
        return self.ask("bootout", "%s/%s" % (self.domain(), label))
