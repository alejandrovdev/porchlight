"""The background agents: what launchd starts at login and keeps running.

    wanted(configuration, mac)      the agents a configuration asks for
    decide(agents, found, loaded)   what to do with each, decided and nothing else
    apply(configuration, mac, out)  make launchd match the configuration
    start(mac, out), stop(mac, out) load what is installed, unload the service
    uninstall(configuration, mac, out)   let go of everything

One agent, the service, keeps the sessions of every project (`porchlight run`); it exists
exactly while the configuration has a project. Each project with the `server` feature has
an agent of its own (`porchlight server <project>`).

A server that runs is never stopped, restarted or removed unless asked with `servers`: the
app cannot start again the sessions that would end with it. Whatever else changes around
it, it is left as it is and said.

An agent is this install's when its label is the service's or a server's (`names`), never
because it merely starts the same way: nothing else in the folder is read, loaded or
removed.
"""

import os
import re
import subprocess
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import names, session_settings
from .atoms import launchd, state, tools
from .atoms.state import Store
from .features import live_view, ready_sessions, resume_list, view_tabs

SERVICE, SERVER = "service", "server"
LOAD, KEEP, RESTART, LEAVE, REMOVE = "load", "keep", "restart", "leave", "remove"
CHANGED, UNWANTED = "changed", "unwanted"  # why a server was left as it is

TOOLS = ("claude", "git", "tmux")  # what the agents start, whose folders their PATH has
SERVER_THROTTLE = 30  # the seconds between two starts of a server that keeps ending
UNLOAD_PATIENCE = 10  # the seconds an agent is given to be gone once asked
STATE_KINDS = (ready_sessions.STATE, view_tabs.STATE, resume_list.STATE)
PROJECT_NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
Named = namedtuple("Named", "name")  # a project of which only the name is known

WHY_SERVERS_STAY = "because the app cannot start its sessions again."


@dataclass(frozen=True)
class Agent:
    label: str
    kind: str  # SERVICE or SERVER
    definition: Optional[dict] = None  # what launchd is told; None when it is not wanted
    project: Optional[str] = None  # the project a server is of


@dataclass(frozen=True)
class Action:
    agent: Agent
    verb: str
    why: str = ""


def search_path(mac):
    """The PATH of an agent: the folders of the tools found, Homebrew's and the system's.
    launchd starts an agent with the system's alone."""
    folders = []
    for name in TOOLS:
        try:
            folders.append(os.path.dirname(mac.tool(name)))
        except tools.ToolNotFound:
            pass
    folders += tools.homebrew_folders() + tools.SYSTEM_FOLDERS
    return ":".join(dict.fromkeys(folder for folder in folders if folder))


def wanted(configuration, mac):
    """The agents a configuration asks for: the service first, then each server."""
    if not configuration.projects:
        return []
    environ = mac.environ
    words, environment = mac.own_command()
    environment = dict(environment, PATH=search_path(mac))
    service = launchd.definition(
        names.service_label(environ),
        words + ["run"],
        environment,
        names.service_log(environ),
        outlived=True,  # the sessions and the tabs it started survive its restart
    )
    found = [Agent(service["Label"], SERVICE, service)]
    for project in configuration.projects:
        if project.has("server"):
            server = launchd.definition(
                names.server_label(project.name, environ),
                words + [names.SERVER_AGENT, project.name],
                environment,
                names.server_log(project, environ),
                directory=names.repository(project),
                throttle=SERVER_THROTTLE,
            )
            found.append(Agent(server["Label"], SERVER, server, project.name))
    return found


def decide(agents, found, loaded, servers=False):
    """What to do with each agent, in the order given: a list of actions.

    `found` is the definition in each agent's file, by label (None for a file that cannot
    be read), `loaded` the labels launchd has, and `servers` whether a running server may
    be restarted or removed. An agent that is not wanted, has no file and is not loaded
    gets no action.
    """
    actions = []
    for agent in agents:
        is_loaded = agent.label in loaded
        protected = agent.kind == SERVER and is_loaded and not servers
        if agent.definition is not None:
            if not is_loaded:
                action = Action(agent, LOAD)
            elif found.get(agent.label) == agent.definition:
                action = Action(agent, KEEP)
            elif protected:
                action = Action(agent, LEAVE, CHANGED)
            else:
                action = Action(agent, RESTART)
        elif protected:
            action = Action(agent, LEAVE, UNWANTED)
        elif is_loaded or agent.label in found:
            action = Action(agent, REMOVE)
        else:
            continue
        actions.append(action)
    return actions


def installed(mac, loaded=()):
    """The agents of this install that have a file or are loaded, as not wanted: the
    service first, then the servers by project."""
    environ = mac.environ
    labels = set(launchd.labels(mac.launch_agents)) | set(loaded)
    found = []
    for label in sorted(label for label in labels if names.own_label(label, environ)):
        project = names.served(label, environ)
        found.append(Agent(label, SERVER if project else SERVICE, None, project))
    return sorted(found, key=lambda agent: agent.kind == SERVER)


def what_is_loaded(mac, out):
    """The labels launchd has loaded; None, and said, when it cannot tell."""
    try:
        return mac.launchd.loaded()
    except launchd.Unavailable as error:
        out("launchd could not say what is loaded (%s). Nothing was changed." % error)
        return None


def failure(answer):
    lines = (answer.stderr or "").strip().splitlines()
    return lines[-1] if lines else "launchctl ended with %d" % answer.returncode


def load(agent, mac):
    """Load an agent from its file; what went wrong, or nothing."""
    path = launchd.file(mac.launch_agents, agent.label)
    try:
        if agent.definition is not None and launchd.read(path) != agent.definition:
            launchd.write(path, agent.definition)
        names.log_root(mac.environ).mkdir(parents=True, exist_ok=True)  # launchd makes no folder for a log
    except OSError as error:
        return "could not be written: %s" % error
    answer = mac.launchd.load(path)
    if answer.returncode != 0:
        mac.sleep(1)  # launchd may still be letting go of the one it had
        answer = mac.launchd.load(path)
    return "" if answer.returncode == 0 else "could not be loaded: %s" % failure(answer)


def unload(label, mac):
    """Stop an agent and wait until launchd let go of it; whether it did."""
    mac.launchd.unload(label)
    return bool(mac.wait_for(lambda: not mac.launchd.is_loaded(label), UNLOAD_PATIENCE))


NOT_UNLOADED = "could not be unloaded, so it was left as it is"


def perform(action, loaded, mac):
    """Do one action: (what to say about the agent, whether it went well)."""
    agent = action.agent
    path = launchd.file(mac.launch_agents, agent.label)
    if action.verb == KEEP:
        return "already loaded, nothing changed", True
    if action.verb == LEAVE:
        if action.why == CHANGED:
            return "left running as it is, though its definition changed", True
        return "left running, though the configuration no longer has it", True
    if action.verb == LOAD:
        problem = load(agent, mac)
        return problem or "loaded", not problem
    if action.verb == RESTART:
        if not unload(agent.label, mac):
            return NOT_UNLOADED, False
        problem = load(agent, mac)
        return problem or "restarted with its new definition", not problem
    was_loaded = agent.label in loaded
    if was_loaded and not unload(agent.label, mac):
        return NOT_UNLOADED, False
    launchd.remove(path)
    return ("unloaded and removed" if was_loaded else "removed"), True


def apply(configuration, mac, out=print, servers=False):
    """Make launchd match the configuration, one line per agent. 0 unless something failed."""
    loaded = what_is_loaded(mac, out)
    if loaded is None:
        return 1
    asked = wanted(configuration, mac)
    labels = {agent.label for agent in asked}
    others = [agent for agent in installed(mac, loaded) if agent.label not in labels]
    files = set(launchd.labels(mac.launch_agents))
    found = {
        agent.label: launchd.read(launchd.file(mac.launch_agents, agent.label))
        for agent in asked + others
        if agent.label in files
    }
    code = 0
    left = []
    actions = decide(asked + others, found, loaded, servers)
    for action in actions:
        said, well = perform(action, loaded, mac)
        out("%s: %s" % (action.agent.label, said))
        code = code if well else 1
        if action.verb == LEAVE:
            left.append(action.agent.project)
    still_served = {agent.project for agent in asked + others if agent.kind == SERVER and agent.label in loaded}
    still_served -= {action.agent.project for action in actions if action.verb == REMOVE}
    for project in configuration.projects:
        # A running server refuses a settings file that changed: its own start installs it.
        if not project.has("server") and project.name not in still_served:
            try:
                if session_settings.bring_up_to_date(project, mac.settings(project)):
                    out("%s: installed the session settings that waited" % project.name)
            except OSError as error:
                out("%s: its session settings could not be installed: %s" % (project.name, error))
                code = 1
    if left:
        out(
            "A running server is restarted or removed only when asked, %s To include them (%s): %s"
            % (WHY_SERVERS_STAY, ", ".join(left), names.command("apply", "--servers"))
        )
    if not actions and not configuration.projects:
        out(names.no_project())
    out("Check with: %s, %s" % (names.command("status"), names.command("doctor")))
    return code


def start(mac, out=print):
    """Load every agent of this install that has a file and is not loaded."""
    loaded = what_is_loaded(mac, out)
    if loaded is None:
        return 1
    files = set(launchd.labels(mac.launch_agents))
    agents = [agent for agent in installed(mac) if agent.label in files]
    if not agents:
        out("No agent is installed. Install them with: %s" % names.command("apply"))
        return 1
    code = 0
    for agent in agents:
        if agent.label in loaded:
            out("%s: already loaded" % agent.label)
            continue
        problem = load(agent, mac)
        out("%s: %s" % (agent.label, problem or "loaded"))
        code = 1 if problem else code
    return code


def stop(mac, out=print, servers=False):
    """Unload the service, and the servers only when asked. The files stay, so `start`
    and the next login load them again; the sessions that run keep running."""
    loaded = what_is_loaded(mac, out)
    if loaded is None:
        return 1
    code = 0
    running = [agent for agent in installed(mac, loaded) if agent.label in loaded]
    service = names.service_label(mac.environ)
    if service not in loaded:
        out("%s: not loaded" % service)
    ended = False
    for agent in running:
        if agent.kind == SERVER and not servers:
            continue
        if unload(agent.label, mac):
            out("%s: unloaded" % agent.label)
            ended = ended or agent.kind == SERVER
        else:
            out("%s: %s" % (agent.label, NOT_UNLOADED))
            code = 1
    kept = [agent.project for agent in running if agent.kind == SERVER and not servers]
    if kept:
        out("The servers keep running (%s); %s unloads them too." % (", ".join(kept), names.command("stop", "--servers")))
    again = "Start again with: %s" % names.command("start")
    if ended:
        out("Sessions already running keep running, except those a server started: they ended with it. " + again)
    else:
        out("Sessions already running keep running. " + again)
    return code


def state_folders(mac):
    """The name of every project that has a folder in the tool's state."""
    try:
        entries = sorted((names.state_root(mac.environ) / "projects").iterdir())
    except OSError:
        return []
    return [entry.name for entry in entries if entry.is_dir() and PROJECT_NAME.fullmatch(entry.name)]


def still_running(mac):
    """The sessions in the tool's state whose process runs, of whatever project, configured
    or not: (how many are in use, how many wait for a first prompt)."""
    ps_text = mac.processes()
    ready, served = ready_sessions.running(ps_text), live_view.server_processes(ps_text)
    used = waiting = 0
    for name in state_folders(mac):
        project = Named(name)
        sessions = mac.store(project, ready_sessions.STATE).load({}).get("sessions")
        for session, record in (sessions if isinstance(sessions, dict) else {}).items():
            if session in ready:
                if isinstance(record, dict) and record.get("state") == "free":
                    waiting += 1
                else:
                    used += 1
        used += len(set(mac.store(project, view_tabs.STATE).load({})) & set(served))
    return used, waiting


def counted(number, one, many):
    return "%d %s" % (number, one if number == 1 else many)


def let_go_of_sessions(configuration, mac, out):
    """End the free session of every project; whether all went well."""
    well = True
    for project in configuration.projects:
        if not names.repository(project).is_dir():
            continue  # nothing can be tidied in a folder that is gone
        try:
            ended, left = ready_sessions.let_go(project, mac)
        except Exception as error:  # one project never stops the others
            out("%s: its free session could not be ended: %r" % (project.name, error))
            well = False
            continue
        if ended:
            out("%s: ended %s it held" % (project.name, "the free session" if ended == 1 else "the %d free sessions" % ended))
        if left:
            out("%s: the free session it holds did not end" % project.name)
            well = False
    return well


def forget(path):
    try:
        Path(path).unlink()
    except OSError:
        pass


def empty(folder):
    """Remove a folder that holds nothing; whatever a person put in it keeps it."""
    try:
        Path(folder).rmdir()
    except OSError:
        pass


def erase(configuration, mac, config_file=None):
    """Remove the configuration, the state and the logs: the files this tool makes, one by
    one, and each folder only once it is empty. Never a whole folder: a variable may have
    pointed it at one that holds something else. The configuration file is the one given
    by whoever read it, and none is looked for when none is given."""
    environ = mac.environ
    if config_file is not None:
        forget(config_file)
    for name in sorted({project.name for project in configuration.projects} | set(state_folders(mac))):
        project = Named(name)
        for kind in STATE_KINDS:
            store = Store(names.state_file(project, kind, environ))
            for file in (store.path, store.lock_path, store.path.with_suffix(".writing")):
                forget(file)
        settings = names.settings_file(project, environ)
        for file in (settings, session_settings.waiting(settings), Path(str(settings) + ".writing")):
            forget(file)
        empty(names.project_state(project, environ))
        forget(names.log_file(project, environ))
        forget(names.server_log(project, environ))
    empty(names.state_root(environ) / "projects")
    forget(names.service_lock(environ))
    empty(names.state_root(environ))
    forget(names.service_log(environ))
    empty(names.log_root(environ))


def uninstall(configuration, mac, out=print, servers=False, purge=False, config_file=None):
    """Unload and remove the agents, end the free sessions, and with `purge` remove
    the configuration (`config_file`, else the file the Mac was given), the state and the
    logs. 0 when nothing of the tool is left running except sessions in use."""
    loaded = what_is_loaded(mac, out)
    if loaded is None:
        return 1
    code = 0
    kept = []
    agents = installed(mac, loaded)
    for agent in agents:
        is_loaded = agent.label in loaded
        if agent.kind == SERVER and is_loaded and not servers:
            out("%s: left running" % agent.label)
            kept.append(agent.project)
            continue
        said, well = perform(Action(agent, REMOVE), loaded, mac)
        out("%s: %s" % (agent.label, said))
        code = code if well else 1
    if not agents:
        out("No agent was installed.")
    if code:
        out("Nothing else was done: run this again once every agent is unloaded.")
        return 1
    # Hold what a service holds: none may run, or it would prepare the sessions let go of here.
    lock = mac.wait_for(lambda: state.exclusive(names.service_lock(mac.environ)), 5)
    if not lock:
        out("A %s that launchd did not start is still running: end it, and run this again." % names.command("run"))
        return 1
    with lock:
        if not let_go_of_sessions(configuration, mac, out):
            code = 1
        try:
            used, waiting = still_running(mac)
        except (OSError, subprocess.SubprocessError) as error:
            out("The process list could not be read (%r), so nothing more was done." % (error,))
            return 1
    if used:
        out("%s in use %s running." % (counted(used, "session", "sessions"), "keeps" if used == 1 else "keep"))
    else:
        out("No session is running.")
    if kept:
        out(
            "A running server is removed only when asked, %s To remove them (%s): %s"
            % (WHY_SERVERS_STAY, ", ".join(kept), names.command("uninstall", "--servers"))
        )
        code = 1
    again = names.command("uninstall", "--purge")
    if not purge:
        out("The configuration, the state and the logs were kept; %s removes them." % again)
    elif kept:
        out("Nothing was purged: a server that is left running still reads the configuration and the state.")
    elif used or waiting:
        running = used + waiting
        out(
            "Nothing was purged: %s still %s. Archive it in the app, or close its tab, and run this again."
            % (counted(running, "session", "sessions"), "runs" if running == 1 else "run")
        )
        code = 1
    else:
        erase(configuration, mac, config_file or mac.config_file)
        out("Removed the configuration, the state and the logs.")
    return code
