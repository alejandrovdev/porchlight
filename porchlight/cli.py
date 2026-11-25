"""The command line: `porchlight <command>`.

    status                     the sessions of every project
    reopen [name]              open a closed session again; without a name, list them
    doctor                     check what each project needs on this Mac
    view <project> <session>   follow a session the server started, read-only
    resume-list [sync]         the copies that /resume lists

Every command reads the configuration file (`--config <file>`, else the default one) and
exits with 0 when it did what was asked, 1 when it refused or something needs attention,
2 when the command line is wrong. This file only reads the command line and prints: what
a command does is in the module it calls.
"""

import argparse
import sys

from . import __version__, config, doctor, names, passes
from .atoms import tools
from .features import live_view, ready_sessions, resume_list
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

    def command(name, run, summary):
        added = commands.add_parser(name, parents=[common], help=summary, description=summary)
        added.set_defaults(run=run)
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
    return top


def load(path, out):
    """The configuration in a file; None, with what is wrong printed, when it cannot be used."""
    try:
        return config.load(path)
    except config.ConfigError as error:
        out("The configuration %s has problems:" % path)
        for key, message in error.problems:
            out("%s: %s" % (key, message) if key else message)
    except (OSError, UnicodeDecodeError) as error:
        out("The configuration %s cannot be read: %s" % (path, error))
    return None


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
    path = getattr(chosen, "config", None) or config.default_path()
    configuration = load(path, out)
    if configuration is None:
        return 1
    try:
        return chosen.run(chosen, configuration, mac or Mac.of(configuration), out)
    except tools.ToolNotFound as error:
        out("%s. See what is missing with: %s" % (error, names.command("doctor")))
        return 1
