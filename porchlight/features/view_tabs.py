"""One terminal tab for each session the Remote Control server started.

The server runs each session as a process with no terminal. This opens a tab that shows
the session's conversation as it grows (`live_view`), once per session; the view ends by
itself when the session is archived, which closes the tab.

    reconcile(project, mac)   open the missing tabs; prints nothing
    status(project, mac)      print the live server sessions and their tabs

A tab the user closes is not opened again. A tab closes only because the program it runs
ends. Unarchiving a session in the app does not start it again on the Mac, so it opens no
tab. The terminal is never started: the tabs open at a later pass, once it runs.

A project without `live-view` gets no tab and nothing is kept for it.
"""

import subprocess
from pathlib import Path

from .. import names
from ..atoms import processes, transcripts, worktrees
from . import live_view

STATE = "view-tabs"
MAX_ATTEMPTS = 3


def runs_the_tool(words, index):
    """Whether the word at `index` of a process's command is the tool being run: its
    installed command, by its path, or its module after an interpreter's `-m`."""
    word = words[index]
    if "/" in word:
        return Path(word).name == names.TOOL
    return (
        word == names.TOOL
        and index >= 2
        and words[index - 1] == "-m"
        and Path(words[index - 2]).name.lower().startswith("python")
    )


def views(ps_text):
    """The sessions whose view is running in some tab."""
    viewing = set()
    for _, program, arguments in processes.rows(ps_text):
        words = [program] + arguments
        for index in range(len(words) - 3):
            if (
                words[index + 1] == live_view.COMMAND
                and live_view.SESSION.fullmatch(words[index + 3])
                and runs_the_tool(words, index)
            ):
                viewing.add(words[index + 3])
    return viewing


def step(live, viewing, state, open_tab):
    """Open the tab of each live session that never had one; return the new state."""
    new = {}
    for session in sorted(live):
        known = dict(state.get(session) or {"opened": False, "attempts": 0})
        if session in viewing:
            known["opened"] = True
        elif not known["opened"] and known["attempts"] < MAX_ATTEMPTS:
            known["attempts"] += 1
            known["opened"] = bool(open_tab(session))
        new[session] = known
    return new


def tab_title(project, prompt, session):
    text = " ".join(prompt.split())
    if not text:
        return names.tab_title(project, session[-6:])
    return names.tab_title(project, text if len(text) <= 40 else text[:39] + "…")


def first_prompt(project, session, mac, wait=8.0):
    """What the user first wrote in a session; waits a little for a new one to have it."""
    deadline = mac.clock() + wait
    while True:
        path = live_view.transcript(project, session, mac)
        if path is not None:
            with open(path, "rb") as handle:
                for entry in transcripts.entries(handle.readlines()[:200]):
                    content = entry.get("content")
                    if entry.get("type") == "queue-operation" and isinstance(content, str):
                        return content
        if mac.clock() >= deadline:
            return ""
        mac.sleep(1)


def open_tab(project, session, mac, wait=8.0):
    """Open a tab that runs the view of a session; True once the view is running."""
    title = tab_title(project, first_prompt(project, session, mac, wait), session)
    try:
        opened = mac.terminal.open_tab(
            names.view_tab(project, session),
            title,
            str(Path.home()),
            live_view.command(project, session, mac.porchlight),
            lambda: session in views(mac.processes()),
            attempts=2,
            patience=8,
        )
    except (OSError, subprocess.SubprocessError) as error:
        mac.log(project, "failed to open a tab for %s: %r" % (session, error))
        return False
    mac.log(project, "opened a tab for %s (%s)" % (session, title) if opened else "no tab opened for %s" % session)
    return bool(opened)


def starting(project, live, mac):
    """Whether a server session's worktree was just created and its process is not up yet."""
    pattern = worktrees.SERVER_PREFIX + names.SERVER_SESSION + "*"
    for folder in worktrees.folder(names.repository(project)).glob(pattern):
        session = folder.name[len(worktrees.SERVER_PREFIX) :]
        try:
            age = mac.clock() - folder.stat().st_birthtime
        except (OSError, AttributeError):
            continue
        if session not in live and age < 60:
            return True
    return False


def reconcile(project, mac, wait=8.0):
    if not project.has("live-view"):
        return
    store = mac.store(project, STATE)
    folder = worktrees.folder(names.repository(project))
    with store.locked():
        deadline = mac.clock() + 45
        while True:
            ps_text = mac.processes()
            live = live_view.live_sessions(ps_text, folder)
            if not starting(project, live, mac) or mac.clock() > deadline:
                break
            mac.sleep(2)
        state = store.load({})
        if mac.terminal is not None and mac.terminal.runs(ps_text):
            new = step(live, views(ps_text), state, lambda session: open_tab(project, session, mac, wait))
        else:  # never start the terminal: the tabs open at a later pass, once it runs
            new = {session: state[session] for session in state if session in live}
        if new != state:
            store.save(new)


def status(project, mac, out=print):
    ps_text = mac.processes()
    live = live_view.live_sessions(ps_text, worktrees.folder(names.repository(project)))
    viewing = views(ps_text)
    state = mac.store(project, STATE).load({})
    if not live:
        out("No session the server started is running.")
        return
    for session, pid in sorted(live.items()):
        if session in viewing:
            tab = "tab open"
        elif (state.get(session) or {}).get("opened"):
            tab = "tab closed by the user"
        else:
            tab = "no tab yet"
        title = tab_title(project, first_prompt(project, session, mac, 0), session)
        out("%s  pid %-6d %-22s %s" % (session, pid, tab, title))
