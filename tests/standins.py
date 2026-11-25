"""Stand-ins for what porchlight touches on a Mac: processes, git, tmux, the terminal, the clock.

No test starts a program, opens a tab or signals a process: everything a feature would ask
of the Mac goes to one of these, which records it and answers what the test told it to.
"""

from pathlib import Path
from types import SimpleNamespace

from porchlight import config
from porchlight.atoms import terminal, tmux, worktrees
from porchlight.mac import Mac

TMUX_SERVER = "porchlight-test"


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

    def __init__(self, running=True, opens=True, error=None):
        self.running = running
        self.opens = opens
        self.error = error
        self.tabs = []
        self.asked = 0  # how many times it was looked for
        self.on_open = None  # what a real tab would change, such as the process list

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
            },
        )
        self.ps = ps  # the process list, or what returns it
        self.now = 1_000_000.0
        self.terminated = []
        self.commands = {}  # pid: its command, for command_of
        self.git_runner = Runner()
        self.tmux_runner = Runner()
        self.claude = "/tools/claude"
        self.python = "/tools/python3"
        self.git = worktrees.Git("/tools/git", run=self.git_runner)
        self.tmux = tmux.Tmux(
            "/tools/tmux", TMUX_SERVER, "/package/tmux.conf", "/tools:/usr/bin", run=self.tmux_runner, environ={}
        )

    def processes(self):
        return self.ps() if callable(self.ps) else self.ps

    def command_of(self, pid):
        return self.commands.get(pid, "")

    def terminate(self, pid):
        self.terminated.append(pid)

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def log_text(self, project):
        try:
            return (Path(self.environ["PORCHLIGHT_LOG_DIR"]) / (project.name + ".log")).read_text(encoding="utf8")
        except OSError:
            return ""
