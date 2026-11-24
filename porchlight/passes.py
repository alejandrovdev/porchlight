"""One pass over a project: what runs every few seconds and when a worktree appears or goes.

    run(project, mac)      the tabs of server sessions, the ready sessions, the copies
    status(project, mac)   print the project's sessions of both kinds

Each part of a pass runs by itself: one that fails is logged and the next still runs, and
the next pass tries again.
"""

from .features import ready_sessions, resume_list, view_tabs

STEPS = (
    ("view tabs", view_tabs.reconcile),
    ("ready sessions", ready_sessions.reconcile),
    ("resume list", resume_list.sync),
)


def run(project, mac, steps=STEPS):
    for name, step in steps:
        try:
            step(project, mac)
        except Exception as error:  # the next pass tries again
            mac.log(project, "%s failed: %r" % (name, error))


def status(project, mac, out=print):
    out("Ready sessions, with Claude Code's interface:")
    ready_sessions.status(project, mac, out)
    out("Sessions the server started, with a read-only view:")
    view_tabs.status(project, mac, out)
