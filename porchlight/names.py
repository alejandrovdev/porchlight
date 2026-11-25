"""Every name porchlight creates, from its own identifier and a project's name.

Nothing here belongs to one Mac or to one repository. A project's name has lowercase
letters, digits and hyphens, and a session's short id has no hyphen, so a name that ends
in "<project>-<short id>" never belongs to two projects.

    state      ~/Library/Application Support/<tool>/projects/<project>/
    logs       ~/Library/Logs/<tool>/<project>.log
    agents     <label>.plist and <label>.server.<project>.plist in ~/Library/LaunchAgents
    variables  <TOOL>_STATE_DIR, <TOOL>_LOG_DIR, <TOOL>_TRANSCRIPTS_DIR, <TOOL>_TMUX_SERVER,
               <TOOL>_WARP_TAB_CONFIGS, <TOOL>_LABEL, <TOOL>_LAUNCH_AGENTS_DIR, <TOOL>_CONFIG,
               and <TOOL>_CLAUDE, <TOOL>_TMUX, <TOOL>_GIT for a tool
"""

import os
import re
from pathlib import Path

TOOL = "porchlight"
LABEL = "io.github.alejandrovdev." + TOOL  # the address the tool is published at, reversed
SERVER_AGENT = "server"  # what a label says between the tool's own and a project's name
SERVER_MODE = "--permission-mode"  # what a server's agent names the mode it runs in with
SHORT = 8  # how much of a session's id a name carries
SERVER_SESSION = "cse_"  # how the id of a session the server starts begins
MARKER = "." + TOOL  # the file in a folder the tool made: only there does a purge delete
PROJECT_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
LABEL_SHAPE = re.compile(r"[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+")  # a reverse domain name
# The variables that name a folder or a file: what someone else is handed is made absolute.
PLACES = ("state_dir", "log_dir", "transcripts_dir", "launch_agents_dir", "warp_tab_configs", "config")


def command(*words):
    """A command of the tool as a person types it."""
    return " ".join((TOOL,) + words)


def no_project():
    """What a command says when the configuration has no project."""
    return "No project is configured. Add one from its folder with: " + command("init")


def variable(name):
    """The environment variable that moves a folder or names a tool."""
    return "%s_%s" % (TOOL.upper(), name.upper())


def chosen(name, environ=None):
    """What the environment says for a variable; empty when it says nothing."""
    return (os.environ if environ is None else environ).get(variable(name), "")


def state_root(environ=None):
    return Path(chosen("state_dir", environ) or Path.home() / "Library" / "Application Support" / TOOL)


def log_root(environ=None):
    return Path(chosen("log_dir", environ) or Path.home() / "Library" / "Logs" / TOOL)


def project_state(project, environ=None):
    return state_root(environ) / "projects" / project.name


def state_file(project, kind, environ=None):
    return project_state(project, environ) / (kind + ".json")


def settings_file(project, environ=None):
    """The Claude Code settings a project's sessions start with."""
    return project_state(project, environ) / "settings.json"


def log_file(project, environ=None):
    return log_root(environ) / (project.name + ".log")


def repository(project):
    """A project's folder as a process started in it sees it: with no symbolic link."""
    return Path(os.path.realpath(project.directory))


def tmux_server(environ=None):
    """The tmux server of the hidden sessions: the tool's own, apart from the user's."""
    return chosen("tmux_server", environ) or TOOL


def short(session):
    return session[:SHORT]


def tmux_session(project, session):
    return "%s-%s" % (project.name, short(session))


def worktree(project, session):
    """The folder of a ready session's worktree, inside the repository's worktrees."""
    return "%s-%s-%s" % (TOOL, project.name, short(session))


def branch(project, session):
    return "%s-%s-%s" % (TOOL, project.name, short(session))


def owns_branch(project, name):
    """Whether a branch was made for one of this project's ready sessions."""
    return re.fullmatch(re.escape("%s-%s-" % (TOOL, project.name)) + "[0-9a-f]{%d}" % SHORT, name or "") is not None


def lock_reason(project, session):
    return "%s %s session %s" % (TOOL, project.name, short(session))


def ready_tab(project, session):
    """The tab configuration of a ready session. The underscores keep the kind apart
    from the project's name, which has none, so no other name of any project equals it."""
    return "%s_ready_%s-%s" % (TOOL, project.name, short(session))


def view_tab(project, session):
    """The tab configuration of the view of a session the server started."""
    return "%s_view_%s-%s" % (TOOL, project.name, session.removeprefix(SERVER_SESSION))


def tab_title(project, text):
    return "%s · %s" % (project.prefix, text)


def copy_name(project, source_id, generation):
    """What the id of a copy for `/resume` is derived from."""
    name = "%s:%s:resume-copy:%s" % (TOOL, project.name, source_id)
    return name if generation <= 1 else "%s:%d" % (name, generation)


def label_prefix(environ=None):
    """How the label of every background agent starts. A variable replaces it, so that a
    rehearsal's agents are never taken for those of the real install."""
    return chosen("label", environ) or LABEL


def service_label(environ=None):
    """The agent that keeps the sessions of every project."""
    return label_prefix(environ)


def server_label(project_name, environ=None):
    """The agent that runs one project's server."""
    return "%s.%s.%s" % (label_prefix(environ), SERVER_AGENT, project_name)


def label_problem(environ=None):
    """What is wrong with the start of the labels a variable chooses; empty when nothing is.
    The labels name files in the agents' folder, so only a reverse domain name will do."""
    chosen_label = chosen("label", environ)
    if not chosen_label or LABEL_SHAPE.fullmatch(chosen_label):
        return ""
    return (
        "%s must be a reverse domain name such as com.example.%s (letters, digits and hyphens, in parts "
        "joined by dots), not %r" % (variable("label"), TOOL, chosen_label)
    )


def served(label, environ=None):
    """The project a label is the server of; None for any other label."""
    start = "%s.%s." % (label_prefix(environ), SERVER_AGENT)
    name = label[len(start) :] if label.startswith(start) else ""
    return name if PROJECT_NAME.fullmatch(name) else None


def own_label(label, environ=None):
    """Whether a label is one this install gives: the service's or a server's, and nothing
    else that merely starts the same way."""
    return label == service_label(environ) or served(label, environ) is not None


def launch_agents(environ=None):
    """The folder that keeps the agents' definitions."""
    return Path(chosen("launch_agents_dir", environ) or Path.home() / "Library" / "LaunchAgents")


def service_log(environ=None):
    """What the service prints. A project's name has no dot, so this is no project's log."""
    return log_root(environ) / "agent.service.log"


def server_log(project, environ=None):
    """What a project's server prints."""
    return log_root(environ) / ("agent.%s.%s.log" % (SERVER_AGENT, project.name))


LOG_NAME = re.compile(r"(?:agent\.%s\.)?(?:%s)\.log" % (re.escape(SERVER_AGENT), PROJECT_NAME.pattern))


def is_log(name):
    """Whether a file name is one the tool gives a log in its log folder: the service's, or
    a project's or its server's, whatever project it was for, configured or not."""
    return name == service_log({}).name or LOG_NAME.fullmatch(name) is not None


def service_lock(environ=None):
    """What the running service holds, so that there is only one."""
    return state_root(environ) / "service.lock"


def default_config():
    """The configuration file of an install that moved nothing."""
    return Path.home() / "Library" / "Application Support" / TOOL / "config.toml"


def carried(environ=None, config_file=None):
    """What a command the tool hands to someone else needs in its environment to read what
    this process reads: every variable of the tool, and the configuration file in use when
    it is not the default one. A tab, a session and a background agent start with none of
    this process's environment. A folder or a file named from where this process runs is
    handed as an absolute path: who receives it runs elsewhere."""
    environ = os.environ if environ is None else environ
    start = variable("")
    places = {variable(name) for name in PLACES}
    found = {
        name: os.path.abspath(value) if name in places else value
        for name, value in environ.items()
        if name.startswith(start) and value
    }
    if config_file is not None:
        file = os.path.abspath(config_file)
        if Path(file) == default_config():
            found.pop(variable("config"), None)
        else:
            found[variable("config")] = file
    return found
