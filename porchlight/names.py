"""Every name porchlight creates, from its own identifier and a project's name.

Nothing here belongs to one Mac or to one repository. A project's name has lowercase
letters, digits and hyphens, and a session's short id has no hyphen, so a name that ends
in "<project>-<short id>" never belongs to two projects.

    state      ~/Library/Application Support/<tool>/projects/<project>/
    logs       ~/Library/Logs/<tool>/<project>.log
    variables  <TOOL>_STATE_DIR, <TOOL>_LOG_DIR, <TOOL>_TRANSCRIPTS_DIR, <TOOL>_TMUX_SERVER,
               <TOOL>_WARP_TAB_CONFIGS, and <TOOL>_CLAUDE, <TOOL>_TMUX, <TOOL>_GIT for a tool
"""

import os
import re
from pathlib import Path

TOOL = "porchlight"
SHORT = 8  # how much of a session's id a name carries
SERVER_SESSION = "cse_"  # how the id of a session the server starts begins


def command(*words):
    """A command of the tool as a person types it."""
    return " ".join((TOOL,) + words)


def no_project():
    """What a command says when the configuration has no project."""
    return "No project is configured. Add one with: " + command("setup")


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
