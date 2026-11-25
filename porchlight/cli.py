"""The command line: `porchlight <command>`.

    status                     the sessions of every project
    reopen [name]              open a closed session again; without a name, list them
    doctor                     check what each project needs on this Mac
    view <project> <session>   follow a session the server started, read-only
    resume-list [sync]         the copies that /resume lists
    apply [--servers]          make the background agents match the configuration
    start, stop [--servers]    load the agents that are installed, unload the service
    uninstall [--servers] [--purge]   remove the agents and let go of the free sessions
    run [--once]               the service: keep the sessions of every project
    server <project>           a project's server (what its background agent runs)

Every command reads the configuration file (`--config <file>`, else the default one) and
exits with 0 when it did what was asked, 1 when it refused or something needs attention,
2 when the command line is wrong, or when `PORCHLIGHT_LABEL` is no reverse domain name.
`run`, `start`, `stop` and `uninstall` work with a file that does not parse: the service
waits for it, `start` and `stop` only load and unload what is installed, and `uninstall`
finds the agents by their labels. `apply` refuses a file named with `--config` that is not
there; the default file absent means no project.
This file only reads the command line and prints: what a command does is in the module it
calls.
"""

import argparse
import os
import sys
from pathlib import Path

from . import __version__, agents, config, doctor, names, passes, service
from .atoms import logs, tools
from .features import live_view, ready_sessions, resume_list
from .features import server as project_server
from .mac import Mac


def server_session(text):
    if not live_view.SESSION.fullmatch(text):
        raise argparse.ArgumentTypeError("%r is not the id of a session the server started (cse_...)" % text)
    return text


def project_named(configuration, name, out):
    """A project of the configuration; None, and said, when it has none by that name."""
    project = configuration.project(name)
    if project is None:
        known = ", ".join(project.name for project in configuration.projects) or "none"
        out('No project "%s" in the configuration. Its projects: %s' % (name, known))
    return project


def status(chosen, configuration, mac, out):
    return passes.status(configuration, mac, out)


def reopen(chosen, configuration, mac, out):
    text = " ".join(chosen.name)
    if chosen.project is None:
        return ready_sessions.reopen_anywhere(configuration, text, mac, out)
    project = project_named(configuration, chosen.project, out)
    return 1 if project is None else ready_sessions.reopen(project, text, mac, out)


def check(chosen, configuration, mac, out):
    return doctor.report(configuration, mac, out)


def view(chosen, configuration, mac, out):
    project = project_named(configuration, chosen.project, out)
    return 1 if project is None else live_view.view(project, chosen.session, mac, out)


def copies(chosen, configuration, mac, out):
    return resume_list.report(configuration, mac, out, sync_first=chosen.action == "sync")


def apply(chosen, configuration, mac, out):
    return agents.apply(configuration, mac, out, servers=chosen.servers)


def serve_project(chosen, configuration, mac, out):
    project = project_named(configuration, chosen.project, out)
    if project is None:
        return 1
    if not project.has("server"):
        out('The project "%s" does not have the server feature: it has no server to run.' % project.name)
        return 1
    project_server.run(project, mac)  # this process is the server from here on
    return 0


# What follows needs no configuration that parses: (chosen, the file, the Mac or None, out).


def start(chosen, path, mac, out):
    return agents.start(mac or Mac(config_file=path), out)


def stop(chosen, path, mac, out):
    return agents.stop(mac or Mac(config_file=path), out, servers=chosen.servers)


def uninstall(chosen, path, mac, out):
    """Uninstall with the configuration, or without it when it cannot be read: the agents
    are then found by their labels and the free sessions in the folders of the state."""
    configuration = load(path, out)
    readable = configuration is not None
    if not readable:
        out(
            "The file could not be read: the agents are found by their labels, and the free sessions in the "
            "folders of the state."
        )
        configuration = config.Config()
    try:
        if mac is None:
            mac = Mac.of(configuration, config_file=path) if readable else Mac(config_file=path)
        return agents.uninstall(
            configuration, mac, out, servers=chosen.servers, purge=chosen.purge, config_file=path, readable=readable
        )
    except tools.ToolNotFound as error:
        out("%s. See what is missing with: %s" % (error, names.command("doctor")))
        return 1


def run_service(chosen, path, mac, out):
    def say(line):
        out(logs.dated(line))
        sys.stdout.flush()  # a log that is a file is read while the service runs

    def mac_for(configuration):
        return mac or Mac.of(configuration, config_file=path)

    lock = names.service_lock(mac.environ if mac else None)
    return service.run(path, mac_for, say, lock, once=chosen.once)


def parser():
    # Every command takes --config, before or after its name; the one given last wins.
    common = argparse.ArgumentParser(add_help=False)
    where = "the configuration file (default: %s)" % config.default_path()
    common.add_argument("--config", metavar="<file>", default=argparse.SUPPRESS, help=where)
    top = argparse.ArgumentParser(
        prog=names.TOOL,
        parents=[common],
        description="Sessions of Claude Code on this Mac, driven from the Claude mobile app.",
    )
    top.add_argument("--version", action="store_true", help="print the version and exit")
    commands = top.add_subparsers(dest="command", metavar="<command>")

    def command(name, run, summary, configured=True):
        added = commands.add_parser(name, parents=[common], help=summary, description=summary)
        added.set_defaults(run=run, configured=configured)
        return added

    def with_servers(added, what):
        added.add_argument("--servers", action="store_true", help=what)
        return added

    command("status", status, "Print the sessions of every project.")
    reopening = command(
        "reopen", reopen, "Open a closed session again, back online in the app. Without a name, list the closed ones."
    )
    reopening.add_argument("name", nargs="*", help="the session's title, its first prompt, part of either, or its id")
    reopening.add_argument("--project", metavar="<name>", help="look in this project only")
    command("doctor", check, "Check what each project needs on this Mac, and say what to do about what is missing.")
    viewing = command(live_view.COMMAND, view, "Follow a session the server started, read-only.")
    viewing.add_argument("project", help="the project's name in the configuration")
    viewing.add_argument("session", type=server_session, help="the session's id, cse_...")
    listing = command("resume-list", copies, "List the copies of the server's sessions that /resume shows.")
    listing.add_argument("action", nargs="?", choices=("sync",), help="bring the copies up to date first")
    applying = with_servers(
        command(
            "apply",
            apply,
            "Make the background agents match the configuration. A server that runs is left as it is.",
        ),
        "also restart the running servers that changed and remove those no longer wanted; their sessions end",
    )
    # A file named and not there is a mistake: it would remove every agent as if no project were configured.
    applying.set_defaults(named_file_must_exist=True)
    command("start", start, "Load every installed agent that is not loaded.", configured=False)
    with_servers(
        command(
            "stop",
            stop,
            "Unload the service until `start` or the next login. Sessions already running keep running.",
            configured=False,
        ),
        "also unload the servers; the sessions they started end",
    )
    removing = with_servers(
        command(
            "uninstall",
            uninstall,
            "Remove the agents and end the free sessions. Sessions in use keep running; "
            "the configuration, the state and the logs stay.",
            configured=False,
        ),
        "also remove the servers that run; the sessions they started end",
    )
    removing.add_argument(
        "--purge",
        action="store_true",
        help="also remove the configuration, the state and the logs; refused while a session still runs",
    )
    running = command(
        "run",
        run_service,
        "The service: keep the sessions of every project until stopped. One at a time.",
        configured=False,
    )
    running.add_argument("--once", action="store_true", help="make one pass and exit")
    serving = command(
        names.SERVER_AGENT, serve_project, "Become a project's server: what its background agent runs."
    )
    serving.add_argument("project", help="the project's name in the configuration")
    # apply, start, stop and uninstall refuse root themselves (`agents`); these delete files too.
    for deleting in (running, serving):
        deleting.set_defaults(not_as_root=True)
    return top


def load(path, out):
    """The configuration in a file; None, with what is wrong printed, when it cannot be used."""
    configuration, problems = service.read(path)
    for line in problems:
        out(line)
    return configuration


def main(arguments, mac=None, out=print):
    """Run one command; its exit code. `mac` stands in for the Mac and `out` for print."""
    reading = parser()
    try:
        chosen = reading.parse_args(arguments)
    except SystemExit as stop:  # argparse printed the help (0), or what is wrong with the command line (2)
        return stop.code or 0
    if chosen.version:
        out("%s %s" % (names.TOOL, __version__))
        return 0
    if chosen.command is None:
        reading.print_usage(sys.stderr)
        sys.stderr.write("%s: error: name a command\n" % names.TOOL)
        return 2
    problem = names.label_problem(mac.environ if mac else os.environ)
    if problem:  # every label, file and agent of the tool is named from it
        reading.print_usage(sys.stderr)
        sys.stderr.write("%s: error: %s\n" % (names.TOOL, problem))
        return 2
    if getattr(chosen, "not_as_root", False) and (mac.launchd.uid() if mac else os.getuid()) == 0:
        out(agents.AS_ROOT)  # they tidy worktrees and settings files of the person's
        return 1
    named = getattr(chosen, "config", None)
    if named and getattr(chosen, "named_file_must_exist", False) and not Path(named).exists():
        out("The configuration file %s does not exist. Nothing was changed." % named)
        return 1
    path = named or config.default_path()
    if not chosen.configured:
        return chosen.run(chosen, path, mac, out)
    configuration = load(path, out)
    if configuration is None:
        return 1
    chosen.config_file = path
    try:
        # What the Mac hands to a tab, a session or an agent reads this very file.
        return chosen.run(chosen, configuration, mac or Mac.of(configuration, config_file=path), out)
    except tools.ToolNotFound as error:
        out("%s. See what is missing with: %s" % (error, names.command("doctor")))
        return 1
