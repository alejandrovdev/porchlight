"""What this Mac and each project need, checked: whether Claude Code is signed in and recent
enough, and the login agents are loaded; then, for each project, the folder, the tools, the terminal, the
base branch, the permission mode, the ready sessions that wait on Claude Code's workspace trust
question and its server's agent.

    checks(project, mac)         the checks of one project's features, in the order they are printed
    report(configuration, mac)   print one line per check: this Mac's, then each project's under its name
    prerequisites(mac)           what any project may need: the tools and each terminal app
    installable(checks)          the missing ones Homebrew installs
    homebrew(mac)                where Homebrew's `brew` is, or None
    listed_modes(mac)            the permission modes the installed Claude Code lists

A project is asked only for what its features need: one without `ready-session` needs no
tmux and no base branch, one without `tabs` no terminal. Nothing is changed and nothing is
started. The programs that run only answer: `claude --help`, to read the permission modes
the installed Claude Code accepts; `claude auth status --json`, of which only whether
someone is signed in is read (no account detail is printed or kept, and no credential is
read); `claude --version`; launchctl, asked what is loaded; and tmux, asked what a running
session that is not in the app yet shows (no key is sent to it).
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
# What Homebrew installs each prerequisite with: the words after `brew`.
BREW = {
    "claude": ("install", "--cask", "claude-code"),
    "git": ("install", "git"),
    "tmux": ("install", "tmux"),
    "warp": ("install", "--cask", "warp"),
}
INSTALL = {
    "claude": "install it with: brew install --cask claude-code, then sign in by running `claude`",
    "git": "install it with: brew install git",
    "tmux": "install it with: brew install tmux",
}
MODE_OPTION = "--permission-mode"
THIS_MAC = "This Mac"  # the heading of the checks that are no project's
SIGN_IN = "Claude Code sign-in"
SIGN_IN_ASKED = ("auth", "status", "--json")  # it exits 1 when no one is signed in
VERSION = "Claude Code version"
OLDEST = (2, 1, 92)  # the oldest Claude Code known to have every option porchlight uses
RECOMMENDED = (2, 1, 327)  # it stops a server in worktree mode without deleting its sessions' ignored files


@dataclass(frozen=True)
class Check:
    state: str  # OK, MISSING, PROBLEM or UNKNOWN
    what: str
    advice: str = ""  # what to do about it
    install: tuple = ()  # when it is missing and Homebrew has it: the words after `brew` that install it

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
        return Check(MISSING, label, INSTALL[name], BREW.get(name, ()))
    return Check(OK, "%s at %s" % (label, found[name]))


def app_check(app):
    """Whether a terminal app porchlight supports is installed."""
    if not app.installed():
        words = BREW.get(app.name, ())
        how = " with: %s" % " ".join(("brew",) + words) if words else ""
        advice = "install the %s app for the `tabs` feature%s, or leave that feature off" % (app.title, how)
        return Check(MISSING, app.title, advice, words)
    return Check(OK, "%s, a terminal tabs can open in" % app.title)


def prerequisites(mac):
    """What the features may need on this Mac, checked: every tool, then every terminal app
    porchlight supports. Nothing is installed."""
    found = {}
    tools_needed = [name for name in config.TOOLS if name != TERMINAL]
    results = [tool_check(name, mac, found) for name in tools_needed]
    return results + [app_check(mac.terminal_app(name)) for name in config.TERMINALS]


def installable(checks):
    """The checks of what is missing that Homebrew installs, in their order."""
    return [check for check in checks if check.failed and check.install]


def brew_command(check):
    """The command that installs what a check found missing, as the person would type it."""
    return " ".join(("brew",) + check.install)


def homebrew(mac):
    """Where Homebrew's `brew` is, found the way the other tools are; None when it is not."""
    try:
        return mac.tool("brew")
    except tools.ToolNotFound:
        return None


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


def claude_version(text):
    """The version `claude --version` prints first (`2.1.326 (Claude Code)`), as numbers to
    compare; None when the answer is not one."""
    found = re.match(r"(\d+)\.(\d+)\.(\d+)(?![\w.-])", (text or "").strip())
    return tuple(int(number) for number in found.groups()) if found else None


def dotted(version):
    return ".".join(str(number) for number in version)


def version_check(claude, mac):
    """Whether the installed Claude Code is recent enough; unknown when it cannot say."""
    version = claude_version(mac.output([claude, "--version"]))
    if version is None:
        return Check(UNKNOWN, VERSION, "`claude --version` could not say")
    what = "%s %s" % (VERSION, dotted(version))
    if version < OLDEST:
        advice = (
            "%s needs %s or later: update it with `brew upgrade --cask claude-code` if Homebrew installed it, "
            "or with `claude update` if it is a native install" % (names.TOOL, dotted(OLDEST))
        )
        return Check(PROBLEM, what, advice)
    if version < RECOMMENDED:
        advice = "%s or later is recommended: it stops a server in worktree mode without deleting its sessions' ignored files"
        return Check(OK, what, advice % dotted(RECOMMENDED))
    return Check(OK, what)


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
    """What any project needs of this Mac: Claude Code signed in and recent enough (when it
    is installed: when it is not, the projects' checks say so) and, while there is a
    project, the service's agent. `known()` gives what `known_agents` says."""
    results = []
    try:
        claude = mac.tool("claude")
    except tools.ToolNotFound:
        pass
    else:
        results += [sign_in_check(claude, mac), version_check(claude, mac)]
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
                    if worktrees.has_remote(mac.git, names.repository(project), ready_sessions.ORIGIN):
                        advice += ", or run `git remote set-head origin --auto` in the repository"
                    results.append(Check(PROBLEM, "base branch", advice))
    if "claude" in found:
        results.append(mode_check(project, modes(found["claude"], mac)))
    results += trust_checks(project, mac)
    return results


def trust_checks(project, mac):
    """A problem when ready sessions wait on Claude Code's workspace trust question; nothing
    when none does, or when what they show cannot be read."""
    waiting = [names.short(session) for session in ready_sessions.waiting_for_trust(project, mac)]
    if not waiting:
        return []
    if len(waiting) == 1:
        what, where = "ready session %s waits" % waiting[0], "that session"
    else:
        what, where = "ready sessions %s wait" % ", ".join(waiting), "each of those sessions"
    attach = "attach with the command `%s` prints" % names.command("status")
    return [Check(PROBLEM, what + " for you to trust the folder", ready_sessions.trust_advice(project, attach, where))]


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
