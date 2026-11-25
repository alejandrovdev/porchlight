"""The background agents: what launchd starts at login and keeps running.

    wanted(configuration, mac)      the agents a configuration asks for
    decide(agents, found, loaded)   what to do with each, decided and nothing else
    apply(configuration, mac, out)  make launchd match the configuration
    start(mac, out), stop(mac, out) load what is installed, unload the service
    uninstall(configuration, mac, out)   let go of everything

One agent, the service, keeps the sessions of every project (`porchlight run`); it exists
exactly while the configuration has a project. Each project with the `server` feature has
an agent of its own (`porchlight server <project> --permission-mode <mode>`). The server runs
in the configuration's mode; the one its definition names makes a new mode a change.

A server that runs is never stopped, restarted or removed unless asked with `servers`: the
app cannot start again the sessions that would end with it. `apply` takes `servers` as True
or False for every server, or as the projects (or labels) whose server it may change. Whatever else changes around
it, it is left as it is and said. A folder is served by one server: none is loaded into a
folder that a server left running serves.

An agent is this install's when its label is the service's or a server's (`names`) and its
file is one the tool writes: it runs the tool, with `run` or `server <project>`. A file under
one of those labels that runs anything else is never read further, loaded or removed, and a
loaded label without a file is known by its name. Nothing else in the folder is touched.

launchd's list may be another session's, so an agent counts as loaded when the list has it
or launchd, asked about its label, says it has it; and as gone only when launchd says it
does not know it. When launchd cannot say, nothing is changed. None of this runs as root,
whose agents are not the person's.
"""

import os
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
FOREIGN = "foreign"  # a file under one of the tool's labels that the tool did not write
CHANGED, UNWANTED = "changed", "unwanted"  # why a server was left as it is

TOOLS = ("claude", "git", "tmux")  # what the agents start, whose folders their PATH has
SERVER_THROTTLE = 30  # the seconds between two starts of a server that keeps ending
UNLOAD_PATIENCE = 10  # the seconds an agent is given to be gone once asked
STATE_KINDS = (ready_sessions.STATE, view_tabs.STATE, resume_list.STATE)
UNWRITABLE = (OSError, ValueError, TypeError, OverflowError)  # what writing a definition raises
Named = namedtuple("Named", "name")  # a project of which only the name is known

WHY_SERVERS_STAY = "because the app cannot start its sessions again."
AS_ROOT = "Run this as the person who is logged in, without sudo: root has other agents. Nothing was changed."
NOT_UNLOADED = "could not be unloaded, so it was left as it is"
NOT_TOLD = "launchd could not say whether it was unloaded, so it was left as it is"
KEPT_SERVERS_RUN = (
    "No ready session and no session in use is running. A server left running keeps the sessions it started."
)


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
    """The agents a configuration asks for: the service first, then each server. Every path
    is absolute: launchd starts them from no folder of this process's."""
    if not configuration.projects:
        return []
    environ = mac.environ
    words, environment = mac.own_command()
    environment = dict(environment, PATH=search_path(mac))
    service = launchd.definition(
        names.service_label(environ),
        words + ["run"],
        environment,
        os.path.abspath(names.service_log(environ)),
        outlived=True,  # the sessions and the tabs it started survive its restart
    )
    found = [Agent(service["Label"], SERVICE, service)]
    for project in configuration.projects:
        if project.has("server"):
            server = launchd.definition(
                names.server_label(project.name, environ),
                # The mode is part of the definition, so that a new one is a change `apply` sees.
                words + [names.SERVER_AGENT, project.name, names.SERVER_MODE, project.permission_mode],
                environment,
                os.path.abspath(names.server_log(project, environ)),
                directory=names.repository(project),
                throttle=SERVER_THROTTLE,
            )
            found.append(Agent(server["Label"], SERVER, server, project.name))
    return found


def allowed(servers, agent):
    """Whether a running server may be restarted or removed: `servers` is True or False for
    every server, or names the projects (or the labels) whose server may be."""
    if servers is None or isinstance(servers, bool):
        return bool(servers)
    return agent.project in servers or agent.label in servers


def decide(agents, found, loaded, servers=False):
    """What to do with each agent, in the order given: a list of actions.

    `found` is the definition in each agent's file, by label (None for a file that cannot
    be read), `loaded` the labels launchd has, and `servers` which running servers may be
    restarted or removed (`allowed`). An agent that is not wanted, has no file and is not
    loaded gets no action.
    """
    actions = []
    for agent in agents:
        is_loaded = agent.label in loaded
        protected = agent.kind == SERVER and is_loaded and not allowed(servers, agent)
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


def refused(mac, out):
    """Whether this command may change launchd or delete files here: 0 when it may; 2, and
    said, for labels that are no reverse domain name; 1, and said, for root."""
    problem = names.label_problem(mac.environ)
    if problem:
        out(problem + ". Nothing was changed.")
        return 2
    if mac.launchd.uid() == 0:
        out(AS_ROOT)
        return 1
    return 0


def runs_the_tool(label, told, environ=None):
    """Whether a definition is one this tool writes for one of its labels: its arguments
    end with `run` for the service and with `server <project>` for that project's server,
    followed or not by `--permission-mode <mode>` (earlier versions left it out), and name
    the tool before that."""
    words = told.get("ProgramArguments") if isinstance(told, dict) else None
    if not isinstance(words, list) or not all(isinstance(word, str) for word in words):
        return False
    project = names.served(label, environ)
    if project and len(words) > 2 and words[-2] == names.SERVER_MODE:
        words = words[:-2]
    ending = [names.SERVER_AGENT, project] if project else ["run"]
    if len(words) <= len(ending) or words[-len(ending) :] != ending:
        return False
    return any(os.path.basename(word) == names.TOOL for word in words[: -len(ending)])


def own_files(mac):
    """The files in the agents' folder under this install's labels: (the definitions of
    those the tool wrote, by label; the labels of those it did not write)."""
    mine, foreign = {}, set()
    for label in launchd.labels(mac.launch_agents):
        if names.own_label(label, mac.environ):
            told = launchd.read(launchd.file(mac.launch_agents, label))
            if runs_the_tool(label, told, mac.environ):
                mine[label] = told
            else:
                foreign.add(label)
    return mine, foreign


def installed(mac, loaded=(), files=None):
    """The agents of this install that have a file the tool wrote, or that are loaded under
    one of its labels and have no file, as not wanted: the service first, then the servers
    by project. `files` is what `own_files` found; else it is looked for."""
    environ = mac.environ
    mine, foreign = own_files(mac) if files is None else files
    labels = set(mine) | {label for label in loaded if names.own_label(label, environ) and label not in foreign}
    found = []
    for label in sorted(labels):
        project = names.served(label, environ)
        found.append(Agent(label, SERVER if project else SERVICE, None, project))
    return sorted(found, key=lambda agent: agent.kind == SERVER)


def what_is_loaded(mac, out, mine=None):
    """The labels launchd has loaded: those its list has, and each of this install's with a
    file of the tool's that launchd, asked by its label, says it has. None, and said, when
    launchd cannot tell, of all of them or of one the list leaves out."""
    try:
        listed = mac.launchd.loaded()
    except launchd.Unavailable as error:
        out("launchd could not say what is loaded (%s). Nothing was changed." % error)
        return None
    if mine is None:
        mine, _ = own_files(mac)
    loaded, untold = set(listed), []
    for label in sorted(mine):
        said = mac.launchd.state(label)
        if said == launchd.LOADED:
            loaded.add(label)
        elif said == launchd.UNKNOWN and label not in listed:
            untold.append(label)
    if untold:
        out(
            "launchd could not say whether %s %s loaded. Nothing was changed."
            % (", ".join(untold), "is" if len(untold) == 1 else "are")
        )
        return None
    return loaded


def failure(answer):
    lines = (answer.stderr or "").strip().splitlines()
    return lines[-1] if lines else "launchctl ended with %d" % answer.returncode


def load(agent, mac):
    """Load an agent from its file; what went wrong, or nothing."""
    path = launchd.file(mac.launch_agents, agent.label)
    try:
        if agent.definition is not None and launchd.read(path) != agent.definition:
            launchd.write(path, agent.definition)
        mac.make_log_root()  # launchd makes no folder for a log
    except UNWRITABLE as error:
        return "could not be written: %s" % error
    answer = mac.launchd.load(path)
    if answer.returncode != 0:
        mac.sleep(1)  # launchd may still be letting go of the one it had
        answer = mac.launchd.load(path)
    return "" if answer.returncode == 0 else "could not be loaded: %s" % failure(answer)


def unload(label, mac):
    """Stop an agent and wait until launchd says it does not know it any more: nothing when
    it does, else what to say about the agent, which was left as it is."""
    mac.launchd.unload(label)
    said = []

    def gone():
        said.append(mac.launchd.state(label))
        return said[-1] == launchd.GONE

    if mac.wait_for(gone, UNLOAD_PATIENCE):
        return ""
    return NOT_TOLD if said and said[-1] == launchd.UNKNOWN else NOT_UNLOADED


def perform(action, loaded, mac):
    """Do one action: (what to say about the agent, whether it went well)."""
    agent = action.agent
    path = launchd.file(mac.launch_agents, agent.label)
    if action.verb == FOREIGN:
        return "left as it is: the file %s was not written by %s. Move it away, and run this again." % (
            path,
            names.TOOL,
        ), False
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
        problem = unload(agent.label, mac) or load(agent, mac)
        return problem or "restarted with its new definition", not problem
    was_loaded = agent.label in loaded
    if was_loaded:
        problem = unload(agent.label, mac)
        if problem:
            return problem, False
    launchd.remove(path)
    return ("unloaded and removed" if was_loaded else "removed"), True


def folder_of(told):
    """The folder a server's definition runs in; None when it says none."""
    directory = told.get("WorkingDirectory") if isinstance(told, dict) else None
    return directory if isinstance(directory, str) and directory else None


def holders(action, actions, found, loaded):
    """The actions of the other servers launchd has loaded that may serve the folder a
    server would be loaded into: (the action, the folder its file says it runs in, or None
    when no file says)."""
    folder = folder_of(action.agent.definition)
    for other in actions:
        if other is action or other.agent.kind != SERVER or other.agent.label not in loaded:
            continue
        theirs = folder_of(found.get(other.agent.label))
        if theirs is None or folder is None or os.path.realpath(theirs) == os.path.realpath(folder):
            yield other, theirs


def held(action, actions, found, loaded, done, mac, out, servers):
    """Why a server may not be loaded into its folder, or nothing. A server that runs in
    that folder and is to be removed is removed first; one that is left running, or that
    did not unload, holds the folder."""
    for other, theirs in holders(action, actions, found, loaded):
        label = other.agent.label
        if other.verb == REMOVE and label not in done:
            said, done[label] = perform(other, loaded, mac)
            out("%s: %s" % (label, said))
        if other.verb == REMOVE and done[label]:
            continue  # gone: it serves nothing
        refused_as = "not loaded" if action.verb == LOAD else "not restarted"
        if other.verb == LEAVE and not allowed(servers, other.agent):
            hint = "; %s replaces it" % names.command("apply", "--servers")
            if theirs is None:
                return "%s: %s is left running and its folder is not known%s" % (refused_as, label, hint)
            return "%s: %s is left running in the same folder, %s%s" % (refused_as, label, theirs, hint)
        if theirs is None:
            return "%s: %s still runs and its folder is not known" % (refused_as, label)
        return "%s: %s still runs in the same folder, %s" % (refused_as, label, theirs)
    return ""


def apply(configuration, mac, out=print, servers=False):
    """Make launchd match the configuration, one line per agent. 0 unless something failed
    or was refused. `servers`: which running servers may be restarted or removed, True or
    False for all of them, or the projects (or labels) named."""
    code = refused(mac, out)
    if code:
        return code
    mine, foreign = own_files(mac)
    loaded = what_is_loaded(mac, out, mine)
    if loaded is None:
        return 1
    asked = wanted(configuration, mac)
    labels = {agent.label for agent in asked}
    others = [agent for agent in installed(mac, loaded, (mine, foreign)) if agent.label not in labels]
    actions = []
    for agent in asked + others:
        if agent.label in foreign:
            actions.append(Action(agent, FOREIGN))
        else:
            actions += decide([agent], mine, loaded, servers)
    done = {}  # the label of each agent acted on: whether that went well
    left = []
    for action in actions:
        label = action.agent.label
        if label in done:
            continue  # removed early, to free its folder
        if action.verb in (LOAD, RESTART) and action.agent.kind == SERVER:
            problem = held(action, actions, mine, loaded, done, mac, out, servers)
            if problem:
                out("%s: %s" % (label, problem))
                code = 1
                continue
        said, done[label] = perform(action, loaded, mac)
        out("%s: %s" % (label, said))
        code = code if done[label] else 1
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
    code = refused(mac, out)
    if code:
        return code
    files = own_files(mac)
    loaded = what_is_loaded(mac, out, files[0])
    if loaded is None:
        return 1
    agents = installed(mac, (), files)
    if not agents:
        out("No agent is installed. Install them with: %s" % names.command("apply"))
        return 1
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
    code = refused(mac, out)
    if code:
        return code
    files = own_files(mac)
    loaded = what_is_loaded(mac, out, files[0])
    if loaded is None:
        return 1
    running = [agent for agent in installed(mac, loaded, files) if agent.label in loaded]
    service = names.service_label(mac.environ)
    if service not in {agent.label for agent in running}:
        out("%s: not loaded" % service)
    ended = False
    for agent in running:
        if agent.kind == SERVER and not servers:
            continue
        problem = unload(agent.label, mac)
        if problem:
            out("%s: %s" % (agent.label, problem))
            code = 1
        else:
            out("%s: unloaded" % agent.label)
            ended = ended or agent.kind == SERVER
    kept = [agent.project for agent in running if agent.kind == SERVER and not servers]
    if kept:
        out("The servers keep running (%s); %s unloads them too." % (", ".join(kept), names.command("stop", "--servers")))
    again = "Start again with: %s" % names.command("start")
    if ended:
        out("Sessions already running keep running, except those a server started: they ended with it. " + again)
    else:
        out("Sessions already running keep running. " + again)
    return code


def still_running(mac):
    """The sessions in the tool's state whose process runs, of whatever project, configured
    or not: (how many are in use, how many wait for a first prompt)."""
    ps_text = mac.processes()
    ready, served = ready_sessions.running(ps_text), live_view.server_processes(ps_text)
    used = waiting = 0
    for name in mac.recorded_projects():
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


def spoken(things):
    """Things in a sentence: "a", "a and b", "a, b and c"."""
    return things[0] if len(things) == 1 else "%s and %s" % (", ".join(things[:-1]), things[-1])


def let_go_of(project, mac, out):
    """End the free session a project holds, as a feature turned off ends it, and say so;
    whether it went well. `project` may be only the name of one the configuration no longer
    has: its folder is then the one the tool's state knows."""
    name = getattr(project, "name", project)
    try:
        if isinstance(project, str):
            project = ready_sessions.left_behind(project, mac)
            if project is None:
                return True  # no free session, or none whose folder is still there
        if not names.repository(project).is_dir():
            return True  # nothing can be tidied in a folder that is gone
        ended, left = ready_sessions.let_go(project, mac)
    except Exception as error:  # one project never stops the others
        out("%s: its free session could not be ended: %r" % (name, error))
        return False
    if ended:
        out("%s: ended %s it held" % (name, "the free session" if ended == 1 else "the %d free sessions" % ended))
    if left:
        out("%s: the free session it holds did not end" % name)
        return False
    return True


def let_go_of_sessions(configuration, mac, out):
    """End the free session of every project of the configuration, and of every project
    the tool's state still holds that the configuration no longer has; whether all went well."""
    well = True
    configured = {project.name for project in configuration.projects}
    removed = [name for name in mac.recorded_projects() if name not in configured]
    for project in list(configuration.projects) + removed:
        well = let_go_of(project, mac, out) and well
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


def made_here(root, out):
    """Whether a purge may delete in one of the tool's folders: it is not there, or the
    tool made it and marked it. Said when not."""
    if not Path(root).exists() or state.claimed(root, names.MARKER):
        return True
    out("%s was left as it is: %s did not make that folder." % (root, names.TOOL))
    return False


def forget_state(project, environ):
    """Remove the files the tool keeps for one project in its state, one by one, and the
    project's folder there once it is empty. Whoever calls it checked that the tool made
    the state folder (`made_here`)."""
    for kind in STATE_KINDS:
        store = Store(names.state_file(project, kind, environ))
        for file in (store.path, store.lock_path, store.path.with_suffix(".writing")):
            forget(file)
    settings = names.settings_file(project, environ)
    for file in (settings, session_settings.waiting(settings), Path(str(settings) + ".writing")):
        forget(file)
    empty(names.project_state(project, environ))


def erase(configuration, mac, out, config_file=None, readable=True):
    """Remove the configuration, the state and the logs, and say what was removed; whether
    all of it was. Only the files this tool makes, one by one, and each folder only once it
    is empty; and only in a state or log folder the tool made: a variable may have pointed
    it at one that holds something else, which is left whole. The configuration file is the
    one given by whoever read it, none is looked for when none is given, and one that could
    not be read is kept: it may be a file named by mistake."""
    environ = mac.environ
    removed, well = [], True
    if readable:
        if config_file is not None:
            forget(config_file)
        removed.append("the configuration")
    elif config_file is not None and Path(config_file).exists():
        out("The configuration file %s was kept: it could not be read." % config_file)
        well = False
    known = {project.name for project in configuration.projects} | set(mac.recorded_projects())
    projects = [Named(name) for name in sorted(known)]
    if made_here(names.state_root(environ), out):
        for project in projects:
            forget_state(project, environ)
        empty(names.state_root(environ) / "projects")
        forget(names.service_lock(environ))
        state.release(names.state_root(environ), names.MARKER)
        removed.append("the state")
    else:
        well = False
    if made_here(names.log_root(environ), out):
        for project in projects:
            forget(names.log_file(project, environ))
            forget(names.server_log(project, environ))
        forget(names.service_log(environ))
        state.release(names.log_root(environ), names.MARKER)
        removed.append("the logs")
    else:
        well = False
    out("Removed %s." % spoken(removed) if removed else "Nothing was removed.")
    return well


def uninstall(configuration, mac, out=print, servers=False, purge=False, config_file=None, readable=True):
    """Unload and remove the agents, end the free sessions of every project the tool's state
    holds, configured or not, and with `purge` remove the configuration (`config_file`, else
    the file the Mac was given), the state and the logs. `readable` is whether the
    configuration could be read: when not, `configuration` has no project, the agents are
    found by their labels and the configuration file is kept. 0 when nothing of the tool is
    left running except sessions in use."""
    code = refused(mac, out)
    if code:
        return code
    files = own_files(mac)
    loaded = what_is_loaded(mac, out, files[0])
    if loaded is None:
        return 1
    kept = []
    agents = installed(mac, loaded, files)
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
    mac.make_state_root()
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
    if waiting:
        out(
            "%s could not be ended and still %s."
            % (counted(waiting, "free session", "free sessions"), "runs" if waiting == 1 else "run")
        )
        code = 1
    if not used and not waiting:
        # What the state counts: a server left running may still run the sessions it started.
        out(KEPT_SERVERS_RUN if kept else "No session is running.")
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
    elif not erase(configuration, mac, out, config_file or mac.config_file, readable):
        code = 1
    return code
