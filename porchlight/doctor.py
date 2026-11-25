"""What each project needs on this Mac, checked: the folder, the tools, the terminal, the
base branch and the permission mode.

    checks(project, mac)         the checks of one project, in the order they are printed
    report(configuration, mac)   print one line per check, under each project's name

A project is asked only for what its features need: one without `ready-session` needs no
tmux and no base branch, one without `tabs` no terminal. Nothing is changed and nothing is
started; the only program that runs is `claude --help`, to read the permission modes the
installed Claude Code accepts.
"""

import re
from dataclasses import dataclass

from . import config, names
from .atoms import tools, worktrees
from .features import ready_sessions

OK, MISSING, PROBLEM, UNKNOWN = "ok", "missing", "problem", "unknown"
TERMINAL = "terminal"  # as `config.tools` names it
LABELS = {"claude": "Claude Code (claude)"}
INSTALL = {
    "claude": "Claude Code is installed separately: install it, and have `claude` in PATH",
    "git": "install it with: brew install git",
    "tmux": "install it with: brew install tmux",
}
MODE_OPTION = "--permission-mode"


@dataclass(frozen=True)
class Check:
    state: str  # OK, MISSING, PROBLEM or UNKNOWN
    what: str
    advice: str = ""  # what to do about it

    @property
    def failed(self):
        """Whether it needs the person: what could not be found out does not."""
        return self.state in (MISSING, PROBLEM)

    def line(self):
        return "%-7s  %s" % (self.state, self.what + (": " + self.advice if self.advice else ""))


def permission_modes(help_text):
    """The permission modes a `claude --help` text lists; None when it does not say."""
    option = re.search(r"^([ \t]*)(?:-\w, )?%s\b" % re.escape(MODE_OPTION), help_text or "", re.M)
    if option is None:
        return None
    described = help_text[option.end() :]
    following = re.search(r"^%s-" % re.escape(option.group(1)), described, re.M)  # the next option
    if following:
        described = described[: following.start()]
    choices = re.search(r"\(choices:([^)]*)\)", described)
    modes = tuple(re.findall(r"[A-Za-z][A-Za-z-]*", choices.group(1))) if choices else ()
    return modes or None


def installed_modes(claude, mac):
    return permission_modes(mac.output([claude, "--help"]))


def tool_check(name, mac, found):
    label = LABELS.get(name, name)
    try:
        found[name] = mac.tool(name)
    except tools.ToolNotFound:
        return Check(MISSING, label, INSTALL[name])
    return Check(OK, "%s at %s" % (label, found[name]))


def terminal_check(mac):
    terminal = mac.terminal
    if terminal is None:
        return Check(PROBLEM, TERMINAL, "set `terminal` in the configuration: tabs open in it")
    if not terminal.installed():
        advice = "install the %s app, or turn off `tabs` for this project" % terminal.title
        return Check(MISSING, terminal.title, advice)
    return Check(OK, "%s, the terminal its tabs open in" % terminal.title)


def mode_check(project, modes):
    what = 'permission mode "%s"' % project.permission_mode
    if modes is None:
        return Check(UNKNOWN, what, "the modes `claude --help` lists could not be read")
    if project.permission_mode not in modes:
        return Check(PROBLEM, what, "claude lists: %s; correct `permission_mode` of the project" % ", ".join(modes))
    return Check(OK, what)


def checks(project, mac, modes=installed_modes):
    """What a project's features need, each checked. `modes(claude, mac)` gives the
    permission modes the installed Claude Code lists."""
    found = {}
    folder = project.directory
    there = folder.is_dir()
    if there:
        results = [Check(OK, "folder %s" % folder)]
    else:
        advice = "create it, or correct `path` of the project in the configuration"
        results = [Check(MISSING, "folder %s" % folder, advice)]
    for name in config.tools(project.features):
        results.append(terminal_check(mac) if name == TERMINAL else tool_check(name, mac, found))
    if there and "git" in found:
        if not worktrees.is_repository(mac.git, names.repository(project)):
            advice = "%s is not one: run `git init` in it, or correct `path`" % folder
            results.append(Check(PROBLEM, "git repository", advice))
        else:
            results.append(Check(OK, "git repository"))
            if project.has("ready-session"):  # what makes a worktree, and so needs where to start it
                base = ready_sessions.base_branch(project, mac)
                if base:
                    results.append(Check(OK, "base branch %s" % base))
                else:
                    advice = "none could be determined: set `base` for the project in the configuration"
                    results.append(Check(PROBLEM, "base branch", advice))
    if "claude" in found:
        results.append(mode_check(project, modes(found["claude"], mac)))
    return results


def report(configuration, mac, out=print):
    """Print every project's checks; 0 when none failed, 1 otherwise."""
    if not configuration.projects:
        out(names.no_project())
        return 0
    known = {}

    def modes(claude, mac):
        """Asked of each installed Claude Code once, however many projects use it."""
        if claude not in known:
            known[claude] = installed_modes(claude, mac)
        return known[claude]

    failed = False
    for index, project in enumerate(configuration.projects):
        if index:
            out("")
        out(project.name)
        try:
            results = checks(project, mac, modes)
        except Exception as error:  # one project never hides the others
            results = [Check(PROBLEM, "its checks could not run", repr(error))]
        for check in results:
            out("  " + check.line())
            failed = failed or check.failed
    return 1 if failed else 0
