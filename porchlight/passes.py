"""One pass: what runs every few seconds and when a worktree appears or goes.

    run(configuration, mac)        every project of the configuration, one after another
    run_project(project, mac)      the tabs of server sessions, the ready sessions, the copies
    status(configuration, mac)     print the sessions of every project, under its name
    project_status(project, mac)   print one project's sessions, of the kinds it has

Each project runs by itself: one whose folder is missing, or that fails, is logged and the
next still runs. Each part of a project's pass runs by itself too: one that fails is
logged and the next still runs, and the next pass tries again.

A part does nothing for a project that does not have its feature, so a pass asks nothing
of a project beyond what its features need: no terminal, no tmux and no server.
"""

from . import names
from .features import ready_sessions, resume_list, view_tabs

STEPS = (
    ("view tabs", view_tabs.reconcile),
    ("ready sessions", ready_sessions.reconcile),
    ("resume list", resume_list.sync),
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


def project_status(project, mac, out=print):
    """A project's ready sessions, and the server's only when the project has the server."""

    def below(line):
        out("  " + line)

    out("Ready sessions, with Claude Code's interface:")
    ready_sessions.status(project, mac, below)
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
