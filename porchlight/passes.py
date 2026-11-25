"""One pass: what the service runs when something changed and every few seconds.

    run(configuration, mac)        every project of the configuration, one after another
    run_project(project, mac)      the tabs of server sessions, the ready sessions, the copies,
                                   the worktrees of the server's sessions that ended
    watched(configuration, mac)    the files and folders whose change calls for a pass
    status(configuration, mac)     print the sessions of every project, under its name
    project_status(project, mac)   print one project's sessions, of the kinds it has

Each project runs by itself: one whose folder is missing, or that fails, is logged and the
next still runs. A project the configuration no longer has gets its free session ended, as
when its feature is turned off. Each part of a project's pass runs by itself too: one that fails is
logged and the next still runs, and the next pass tries again.

A part does nothing for a project that does not have its feature, so a pass asks nothing
of a project beyond what its features need: no terminal, no tmux and no server.
"""

from . import config, names
from .features import ready_sessions, resume_list, server, view_tabs

STEPS = (
    ("view tabs", view_tabs.reconcile),
    ("ready sessions", ready_sessions.reconcile),
    ("resume list", resume_list.sync),
    ("server worktrees", server.tidy_worktrees),
)


def run_project(project, mac, steps=STEPS):
    if not names.repository(project).is_dir():
        mac.log(project, "skipped: the folder %s is missing" % project.directory)
        return
    for name, step in steps:
        try:
            step(project, mac)
        except Exception as error:  # the next pass tries again
            mac.log(project, "%s failed: %r" % (name, error))


def run(configuration, mac, steps=STEPS):
    for project in configuration.projects:
        try:
            run_project(project, mac, steps)
        except Exception as error:  # one project never stops the others
            mac.log(project, "the pass failed: %r" % (error,))
    let_go_of_removed(configuration, mac)


def let_go_of_removed(configuration, mac):
    """End the free session of each project the configuration no longer has, the way a
    feature turned off ends it: only a session in the tool's own state, and only while its
    process runs. A project of the state that holds no free session is not even looked at."""
    configured = {project.name for project in configuration.projects}
    for name in mac.recorded_projects():
        if name in configured:
            continue
        try:
            project = ready_sessions.left_behind(name, mac)
            if project is not None:
                ready_sessions.let_go(project, mac)
        except Exception as error:  # one project never stops the others
            mac.log(config.Project(name, "", "", ()), "letting go of its free session failed: %r" % (error,))


def watched(configuration, mac):
    """What to watch so that a pass comes as soon as it is needed, not at the next interval:
    the folder where a new session's transcripts appear, and what each project's sessions
    write. The process list cannot be watched: that is what the interval is for."""
    paths = [mac.transcripts]
    for project in configuration.projects:
        try:
            paths += ready_sessions.watched(project, mac)
        except Exception as error:  # one project never hides the others
            mac.log(project, "what to watch could not be read: %r" % (error,))
    return paths


def project_status(project, mac, out=print):
    """A project's ready sessions when it has them, or still holds one from before they were
    turned off, and the server's only when the project has the server."""

    def below(line):
        out("  " + line)

    ready = project.has("ready-session") or ready_sessions.held(project, mac)
    if ready:
        out("Ready sessions, with Claude Code's interface:")
        ready_sessions.status(project, mac, below)
    if not ready and not project.has("server"):
        out("No feature that starts sessions is on.")
    if project.has("server"):
        out("Sessions the server started, with a read-only view:")
        view_tabs.status(project, mac, below)


def status(configuration, mac, out=print):
    """Every project's sessions under a heading with its name. 0 when all could be shown,
    1 when a project needs attention: its folder is missing or its sessions cannot be read."""
    if not configuration.projects:
        out(names.no_project())
        return 0
    code = 0
    for index, project in enumerate(configuration.projects):
        if index:
            out("")
        out(project.name)

        def below(line):
            out("  " + line)

        if not names.repository(project).is_dir():
            below("The folder %s is missing." % project.directory)
            code = 1
        try:
            project_status(project, mac, below)
        except Exception as error:  # one project never hides the others
            below("Its sessions cannot be read: %s" % (error,))
            code = 1
    return code
