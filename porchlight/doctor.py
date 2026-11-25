"""What this Mac and each project need, checked: whether Claude Code is signed in and the
login agents are loaded; then, for each project, the folder, the tools, the terminal, the
base branch, the permission mode and its server's agent.

    checks(project, mac)         the checks of one project's features, in the order they are printed
    report(configuration, mac)   print one line per check: this Mac's, then each project's under its name
    prerequisites(mac)           what any project may need: the tools and each terminal app
    listed_modes(mac)            the permission modes the installed Claude Code lists

A project is asked only for what its features need: one without `ready-session` needs no
tmux and no base branch, one without `tabs` no terminal. Nothing is changed and nothing is
started. The programs that run only answer: `claude --help`, to read the permission modes
the installed Claude Code accepts; `claude auth status --json`, of which only whether
someone is signed in is read (no account detail is printed or kept, and no credential is
read); and launchctl, asked what is loaded.
"""

import json
import re
from dataclasses import dataclass

from . import agents, config, names
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
THIS_MAC = "This Mac"  # the heading of the checks that are no project's
SIGN_IN = "Claude Code sign-in"
SIGN_IN_ASKED = ("auth", "status", "--json")  # it exits 1 when no one is signed in


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


def app_check(app):
    """Whether a terminal app porchlight supports is installed."""
    if not app.installed():
        return Check(MISSING, app.title, "install the %s app for the `tabs` feature, or leave that feature off" % app.title)
    return Check(OK, "%s, a terminal tabs can open in" % app.title)


def prerequisites(mac):
    """What the features may need on this Mac, checked: every tool, then every terminal app
    porchlight supports. Nothing is installed."""
    found = {}
    tools_needed = [name for name in config.TOOLS if name != TERMINAL]
    results = [tool_check(name, mac, found) for name in tools_needed]
    return results + [app_check(mac.terminal_app(name)) for name in config.TERMINALS]


def listed_modes(mac):
    """The permission modes the installed Claude Code lists; None when it is not installed
    or its help does not say."""
    try:
        claude = mac.tool("claude")
    except tools.ToolNotFound:
        return None
    return installed_modes(claude, mac)


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


def signed_in(text):
    """What `claude auth status --json` says of the sign-in: True, False, or None when it does
    not say. Nothing else of the answer is kept."""
    try:
        answer = json.loads(text) if text else None
    except ValueError:
        return None
    said = answer.get("loggedIn") if isinstance(answer, dict) else None
    return said if isinstance(said, bool) else None


def sign_in_check(claude, mac):
    said = signed_in(mac.output([claude] + list(SIGN_IN_ASKED), any_exit=True))
    if said is None:
        return Check(UNKNOWN, SIGN_IN, "`claude auth status` could not say")
    if not said:
        return Check(PROBLEM, SIGN_IN, "no one is signed in: run `claude auth login`")
    return Check(OK, SIGN_IN)


def known_agents(mac):
    """What the agents' folder and launchd say of this install's agents: (the definitions
    of those the tool wrote, by label; the labels of files it did not write; the labels
    loaded, or None when launchd cannot tell). Only asked: nothing is loaded or written."""
    mine, foreign = agents.own_files(mac)
    return mine, foreign, agents.what_is_loaded(mac, lambda said: None, mine)


def agent_check(kind, label, known):
    """Whether one login agent is in place: its file, then whether launchd has it loaded."""
    mine, foreign, loaded = known
    what = "%s agent %s" % (kind, label)
    if label in foreign:
        advice = "its file was not written by %s: move it away, then run `%s`" % (names.TOOL, names.command("apply"))
        return Check(PROBLEM, what, advice)
    if label not in mine:
        return Check(PROBLEM, what, "its file is missing: run `%s`" % names.command("apply"))
    if loaded is None:
        return Check(UNKNOWN, what, "launchd could not say whether it is loaded")
    if label not in loaded:
        return Check(PROBLEM, what, "not loaded: run `%s`" % names.command("start"))
    return Check(OK, what)


def mac_checks(configuration, mac, known):
    """What any project needs of this Mac: Claude Code signed in (when it is installed: when
    it is not, the projects' checks say so) and, while there is a project, the service's
    agent. `known()` gives what `known_agents` says."""
    results = []
    try:
        results.append(sign_in_check(mac.tool("claude"), mac))
    except tools.ToolNotFound:
        pass
    if configuration.projects:
        results.append(agent_check(agents.SERVICE, names.service_label(mac.environ), known()))
    return results


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
    """Print this Mac's checks, then every project's; 0 when none failed, 1 otherwise."""
    known, agents_said = {}, []

    def modes(claude, mac):
        """Asked of each installed Claude Code once, however many projects use it."""
        if claude not in known:
            known[claude] = installed_modes(claude, mac)
        return known[claude]

    def agents_known():
        """Asked of the agents' folder and launchd once, for the service and every server."""
        if not agents_said:
            agents_said.append(known_agents(mac))
        return agents_said[0]

    def project_checks(project):
        results = checks(project, mac, modes)
        if project.has("server"):
            results.append(agent_check(agents.SERVER, names.server_label(project.name, mac.environ), agents_known()))
        return results

    sections = [(THIS_MAC, lambda: mac_checks(configuration, mac, agents_known))]
    sections += [(project.name, lambda project=project: project_checks(project)) for project in configuration.projects]
    failed = printed = False
    for heading, find in sections:
        try:
            results = find()
        except Exception as error:  # one project never hides the others
            results = [Check(PROBLEM, "its checks could not run", repr(error))]
        if not results:
            continue
        if printed:
            out("")
        out(heading)
        printed = True
        for check in results:
            out("  " + check.line())
            failed = failed or check.failed
    if not configuration.projects:
        if printed:
            out("")
        out(names.no_project())
    return 1 if failed else 0
