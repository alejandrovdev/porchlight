"""Stand-ins for what porchlight touches on a Mac: processes, git, tmux, the terminal, the clock.

No test starts a program, opens a tab or signals a process: everything a feature would ask
of the Mac goes to one of these, which records it and answers what the test told it to.
"""

import plistlib
from pathlib import Path
from types import SimpleNamespace

from porchlight import config, names
from porchlight.atoms import launchd, terminal, tmux, tools, worktrees
from porchlight.mac import Mac

TMUX_SERVER = "porchlight-test"
LABEL = "test.porchlight.unit"  # how the label of every agent of a test starts


def project(name="shop", path="/srv/shop", mode="plan", base=None, prefix=None, features=None):
    return config.Project(
        name, path, mode, tuple(config.FEATURES) if features is None else features, base, prefix or name
    )


def result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class Runner:
    """Stands in for subprocess.run: records each command and answers as told.

    `answers` takes the words of a command and returns a result, or None for a plain success.
    """

    def __init__(self, answers=None):
        self.calls = []
        self.options = []
        self.answers = answers or (lambda words: None)

    def __call__(self, words, **options):
        self.calls.append(list(words))
        self.options.append(options)
        answer = self.answers(list(words))
        if isinstance(answer, Exception):
            raise answer
        return answer if answer is not None else result()

    def having(self, *words):
        """The recorded commands that hold these words, in this order and next to each other."""
        return [
            call
            for call in self.calls
            if any(tuple(call[index : index + len(words)]) == words for index in range(len(call)))
        ]


class Terminal(terminal.Terminal):
    """A terminal that opens no tab: it records what it was asked."""

    name = "standin"
    title = "Stand-in"

    def __init__(self, running=True, opens=True, error=None, installed=True):
        self.is_installed = installed
        self.running = running
        self.opens = opens
        self.error = error
        self.tabs = []
        self.asked = 0  # how many times it was looked for
        self.on_open = None  # what a real tab would change, such as the process list

    def installed(self):
        return self.is_installed

    def runs(self, ps_text):
        self.asked += 1
        return self.running

    def open_tab(self, name, title, directory, command, started, attempts=1, patience=25.0):
        self.tabs.append(
            SimpleNamespace(
                name=name, title=title, directory=directory, command=command, attempts=attempts, patience=patience
            )
        )
        if self.error:
            raise self.error
        if not self.opens:
            return 0
        if self.on_open:
            self.on_open(self.tabs[-1])
        return started()


class Launchctl:
    """Stands in for launchctl, as subprocess.run would run it: it keeps what is loaded,
    records what it was asked and loads nothing."""

    def __init__(self):
        self.loaded = set()
        self.others = {"com.example.other"}  # what someone else loaded
        self.definitions = {}  # label: the definition it was last loaded from
        self.calls = []
        self.lists = True  # whether it can say what is loaded
        self.refused = set()  # the labels it fails to load
        self.stuck = set()  # the labels it fails to unload
        self.on_unload = None  # what unloading an agent changes, such as the process list

    def __call__(self, words, **options):
        self.calls.append(list(words))
        verb = words[1]
        if verb == "list":
            if not self.lists:
                return result(1, stderr="Could not contact launchd")
            rows = "".join("-\t0\t%s\n" % label for label in sorted(self.loaded | self.others))
            return result(stdout="PID\tStatus\tLabel\n" + rows)
        if verb == "print":
            return result(0 if words[2].split("/", 2)[2] in self.loaded else 113)
        if verb == "bootstrap":
            with open(words[3], "rb") as handle:
                told = plistlib.load(handle)
            if told["Label"] in self.refused:
                return result(5, stderr="Bootstrap failed: 5: Input/output error\n")
            if told["Label"] in self.loaded:
                return result(37, stderr="Bootstrap failed: 37: Operation already in progress\n")
            self.loaded.add(told["Label"])
            self.definitions[told["Label"]] = told
            return result()
        if verb == "bootout":
            label = words[2].split("/", 2)[2]
            if label not in self.loaded:
                return result(3, stderr="Boot-out failed: 3: No such process\n")
            if label in self.stuck:
                return result(36, stderr="Boot-out failed: 36: Operation now in progress\n")
            self.loaded.discard(label)
            if self.on_unload:
                self.on_unload(label)
            return result()
        raise AssertionError("launchctl was asked something the tool never asks: %r" % (words,))

    def did(self):
        """What it was asked to change, in order: ("load" or "unload", the label or the file's name)."""
        changes = []
        for words in self.calls:
            if words[1] == "bootstrap":
                changes.append(("load", Path(words[3]).name[: -len(".plist")]))
            elif words[1] == "bootout":
                changes.append(("unload", words[2].split("/", 2)[2]))
        return changes


class Child:
    """A program started beside this one: it runs until it is ended."""

    def __init__(self, words):
        self.words = list(words)
        self.ended = False  # by whoever started it
        self.exited = None  # by itself: its exit code

    def poll(self):
        return 0 if self.ended else self.exited

    def terminate(self):
        self.ended = True

    def wait(self, timeout=None):
        return self.poll()


class StandInMac(Mac):
    """The Mac of a test: scratch folders, a clock that only moves when asked to wait."""

    def __init__(self, root, terminal=None, ps=""):
        root = Path(root)
        super().__init__(
            terminal,
            {
                "PORCHLIGHT_STATE_DIR": str(root / "state"),
                "PORCHLIGHT_LOG_DIR": str(root / "logs"),
                "PORCHLIGHT_TRANSCRIPTS_DIR": str(root / "transcripts"),
                "PORCHLIGHT_TMUX_SERVER": TMUX_SERVER,
                "PORCHLIGHT_LAUNCH_AGENTS_DIR": str(root / "agents"),
                "PORCHLIGHT_LABEL": LABEL,
            },
        )
        self.launchctl = Launchctl()
        self.launchd = launchd.Launchd(run=self.launchctl, uid=lambda: 501)
        self.ps = ps  # the process list, or what returns it
        self.now = 1_000_000.0
        self.terminated = []
        self.spawned = []  # the programs started beside this one, each a Child
        self.spawn_error = None
        self.commands = {}  # pid: its command, for command_of
        self.git_runner = Runner()
        self.tmux_runner = Runner()
        self.found = {name: "/tools/" + name for name in ("claude", "git", "tmux")}  # the tools installed
        self.outputs = {}  # what a command prints, by its words joined with spaces
        self.asked = []  # the commands whose output was read
        self.claude = "/tools/claude"
        self.porchlight = "/tools/porchlight"
        self.git = worktrees.Git("/tools/git", run=self.git_runner)
        self.tmux = tmux.Tmux(
            "/tools/tmux", TMUX_SERVER, "/package/tmux.conf", "/tools:/usr/bin", run=self.tmux_runner, environ={}
        )

    def tool(self, name):
        if name not in self.found:
            raise tools.ToolNotFound(name)
        return self.found[name]

    def own_command(self):
        return ["/tools/porchlight"], names.carried(self.environ, self.config_file)

    def output(self, words):
        self.asked.append(list(words))
        return self.outputs.get(" ".join(words))

    def processes(self):
        return self.ps() if callable(self.ps) else self.ps

    def command_of(self, pid):
        return self.commands.get(pid, "")

    def terminate(self, pid):
        self.terminated.append(pid)

    def pid(self):
        return 4242

    def spawn(self, words):
        if self.spawn_error:
            raise self.spawn_error
        self.spawned.append(Child(words))
        return self.spawned[-1]

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def log_text(self, project):
        try:
            return (Path(self.environ["PORCHLIGHT_LOG_DIR"]) / (project.name + ".log")).read_text(encoding="utf8")
        except OSError:
            return ""
