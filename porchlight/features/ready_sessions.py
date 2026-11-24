"""Sessions with Claude Code's own interface, always one ready, shown in a tab while in use.

A session the Remote Control server starts has no terminal, and the app cannot start it
again once it is archived. These sessions are the other kind: Claude Code's interactive
interface with Remote Control on, so the Claude mobile app drives the same conversation a
terminal tab shows.

    reconcile(project, mac)      keep one free session ready, open the tab of a session
                                 that is now in use, stop a session the app archived, tidy
                                 what ended
    status(project, mac)         print the sessions and their state
    reopen(project, text, mac)   open a closed session again in a new tab, back online in
                                 the app; without a name, list the closed ones

One free session always waits, in its own worktree, named `<prefix>-...` in the app. It
waits hidden: it runs in a detached session of the tool's own tmux server, so no tab stays
open for it. The user starts work by writing in it from the app; it then counts as used, a
tab opens attached to it, and another free one is prepared. Closing that tab ends the
session, as it would without tmux. Archiving a session in the app ends its process, which
closes its tab. Unarchiving it in the app reaches nothing on the Mac, so a session comes
back with `reopen`, which a session runs when the user asks it to; a reopened session runs
in its tab directly, without tmux.

Only sessions in this project's own state are ever stopped or tidied; a session someone
started by hand is never touched. A worktree is removed only when it is clean and its HEAD
is on the base branch; otherwise it is unlocked and left.
"""

import calendar
import json
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from .. import names, session_settings
from ..atoms import processes, transcripts, worktrees

STATE = "ready-sessions"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# What Claude Code writes in the transcript when the app ends or archives the session.
ARCHIVED = "Remote Control disconnected — this session was ended or archived from another device or app"
CLOSED = ("archived", "closed")
FORGET_AFTER = 30 * 86400
SHOW_ATTEMPTS = 3


def note():
    """What a session is told, beside its system prompt, about reopening another."""
    return (
        "This session runs on the user's Mac and is driven from the Claude mobile app. "
        "When the user asks to reopen a session (for example: reopen <name>) or to list the closed "
        "ones, run this with Bash and report what it prints: %s reopen <name>. Without a name it "
        "lists the closed sessions; when the name matches none or several, pick the id from that "
        "list and run it again with the id. It opens the session in a new tab and puts it back "
        "online in the app." % names.TOOL
    )


def new_summary():
    return {"prompt": "", "title": "", "cse": "", "ended_at": 0.0}


def running(ps_text):
    """The Claude Code processes with Remote Control and a known session id: {id: pid}."""
    found = {}
    for pid, program, arguments in processes.rows(ps_text):
        if Path(program).name != "claude":
            continue
        if "--remote-control" not in arguments or "--print" in arguments or "--sdk-url" in arguments:
            continue
        for index, argument in enumerate(arguments[:-1]):
            if argument in ("--session-id", "--resume") and UUID.fullmatch(arguments[index + 1]):
                found[arguments[index + 1]] = pid
                break
    return found


def seconds(timestamp):
    try:
        return float(calendar.timegm(time.strptime(str(timestamp)[:19], "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        return 0.0


def prompt_text(entry):
    """What the user wrote in a transcript entry, on one line; empty for anything else."""
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isSidechain"):
        return ""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        content = " ".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    if not isinstance(content, str) or content.lstrip().startswith("<"):
        return ""
    return " ".join(content.split())[:200]


def summarize(entries):
    """What a stretch of transcript says about its session.

    The first prompt, the title (the user's own over a generated one), the session it is
    in the app, and when the app last ended or archived it.
    """
    summary = new_summary()
    generated = ""
    for entry in entries:
        kind = entry.get("type")
        if kind == "user":
            summary["prompt"] = summary["prompt"] or prompt_text(entry)
        elif kind == "custom-title":
            summary["title"] = " ".join(str(entry.get("customTitle") or "").split())
        elif kind == "ai-title":
            generated = " ".join(str(entry.get("aiTitle") or "").split())
        elif kind == "bridge-session":
            summary["cse"] = str(entry.get("bridgeSessionId") or "") or summary["cse"]
        elif kind == "system" and str(entry.get("content") or "").startswith(ARCHIVED):
            summary["ended_at"] = max(summary["ended_at"], seconds(entry.get("timestamp")))
    summary["title"] = summary["title"] or generated
    return summary


def plan(sessions, live, summaries, create, now, tabs=True):
    """Decide what to do with the known sessions: (the new records, the actions).

    Actions: ("stop", id) ends the process of a session the app archived, ("tidy", id)
    cleans up after a session that ended, ("discard", record) drops a free session
    nobody used, ("create",) prepares a free session, ("show", id) opens the tab of a
    hidden session that is now in use, asked only while tabs can open.
    """
    new = {}
    actions = []
    for session in sorted(sessions):
        record = dict(sessions[session])
        summary = summaries.get(session) or new_summary()
        record["prompt"] = record["prompt"] or summary["prompt"]
        record["title"] = summary["title"] or record["title"]
        record["cse"] = summary["cse"] or record["cse"]
        state = record["state"]
        archived = summary["ended_at"] > record["started"]
        if state == "free" and record["prompt"]:
            state = "used"
        if session in live:
            if state == "closed" or (state == "archived" and record["tidied"]):
                # Someone opened it again by hand, in a terminal.
                state = "used"
                record["tidied"] = False
                record["started"] = now
            elif archived or state == "archived":
                actions.append(("stop", session))
                if state != "free":  # an archived free session is discarded once it ends
                    state = "archived"
            if state == "used" and tabs and not record.get("shown", True):
                actions.append(("show", session))
        elif state == "free":
            actions.append(("discard", record))
            continue
        else:
            if state == "used":
                state = "archived" if archived else "closed"
            if not record["tidied"]:
                record["tidied"] = True
                actions.append(("tidy", session))
            elif now - record["changed"] > FORGET_AFTER:
                continue
        if state != record["state"]:
            record["state"] = state
            record["changed"] = now
        new[session] = record
    if create and not any(record["state"] == "free" for record in new.values()):
        actions.append(("create",))
    return new, actions


def match(sessions, text):
    """The closed sessions a name refers to, the latest first; all of them without a name."""
    needle = " ".join(text.split()).casefold()
    closed = sorted(
        (session for session, record in sessions.items() if record["state"] in CLOSED),
        key=lambda session: (-sessions[session]["changed"], session),
    )
    if not needle:
        return closed
    exact = [
        session
        for session in closed
        if needle in (sessions[session]["title"].casefold(), sessions[session]["prompt"].casefold(), session)
    ]
    if exact:
        return exact
    return [
        session
        for session in closed
        if needle
        in " ".join(
            (session, sessions[session]["title"], sessions[session]["prompt"], sessions[session]["cse"])
        ).casefold()
    ]


def command_line(project, session, resume, claude, settings):
    """What a tab runs: Claude Code with Remote Control, on a new or a known conversation."""
    words = [
        claude,
        "--resume" if resume else "--session-id",
        session,
        "--permission-mode",
        project.permission_mode,
        "--settings",
        str(settings),
        "--append-system-prompt",
        note(),
        "--remote-control-session-name-prefix",
        project.prefix,
        "--remote-control",  # last: a word after it would be the session's name
    ]
    return "exec " + " ".join(shlex.quote(word) for word in words)


def hidden_start(project, session, worktree, tmux, claude, settings):
    """What starts a session nobody sees: Claude Code in a detached tmux session."""
    return tmux.new_session(
        names.tmux_session(project, session), worktree, command_line(project, session, False, claude, settings)
    )


def label(record, session):
    return record["title"] or record["prompt"] or names.short(session)


def tab_title(project, record, session):
    return names.tab_title(project, label(record, session)[:40])


def describe(session, record):
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(record["changed"]))
    return "%s  %-8s %s  %s" % (names.short(session), record["state"], when, label(record, session))


# What follows touches the Mac, through the `mac` it is given: processes, git, tmux, the
# terminal and the state file.


def transcript(session, record, mac):
    return transcripts.folder(mac.transcripts, record["worktree"]) / (session + ".jsonl")


def base_branch(project, mac):
    """Where a new worktree starts and what a finished one must be on: the project's own
    choice, else the default branch git recorded for the repository; None when neither."""
    return project.base or worktrees.default_base(mac.git, names.repository(project))


def add_worktree(project, record, session, mac):
    """Make sure the session's worktree exists and is locked; True when it is there."""
    repository = names.repository(project)
    path = record["worktree"]
    branch = record["branch"]
    reason = names.lock_reason(project, session)
    if Path(path).is_dir():
        worktrees.lock(mac.git, repository, path, reason)  # fails when it is locked already
        return True
    if branch and worktrees.branch_exists(mac.git, repository, branch):
        if worktrees.add(mac.git, repository, path, reason, branch).returncode == 0:
            return True
        result = worktrees.add(mac.git, repository, path, reason, branch, "--detach")  # checked out elsewhere
    else:
        base = base_branch(project, mac)
        if base is None:
            mac.log(
                project,
                "no worktree for %s: the repository states no default branch; set `base` for the project"
                % names.short(session),
            )
            return False
        if names.owns_branch(project, branch):
            result = worktrees.add(mac.git, repository, path, reason, base, "-b", branch)
        else:
            result = worktrees.add(mac.git, repository, path, reason, base, "--detach")
    if result.returncode != 0:
        mac.log(project, "no worktree for %s: %s" % (names.short(session), result.stderr.strip()[:300]))
    return result.returncode == 0


def tidy(project, record, mac):
    """Remove the worktree of a session that ended when nothing in it would be lost."""
    repository = names.repository(project)
    path = record["worktree"]
    name = Path(path).name
    if not Path(path).is_dir():
        return
    record["branch"] = worktrees.current_branch(mac.git, path)
    clean = worktrees.is_clean(mac.git, path)
    base = base_branch(project, mac)
    merged = base is not None and worktrees.is_merged(mac.git, path, base)
    worktrees.unlock(mac.git, repository, path)
    if not (clean and merged):
        if base is None:
            why = "the repository states no default branch"
        else:
            why = "it has changes" if merged else "its commits are not on %s" % base
        mac.log(project, "kept the worktree %s (%s)" % (name, why))
        return
    removed = worktrees.remove(mac.git, repository, path)
    if removed.returncode != 0:
        mac.log(project, "could not remove the worktree %s: %s" % (name, removed.stderr.strip()[:300]))
        return
    if names.owns_branch(project, record["branch"]):
        worktrees.delete_branch(mac.git, repository, record["branch"])
    mac.log(project, "removed the worktree %s" % name)


def stop(project, session, pid, mac):
    """End the process of a session, which closes its tab."""
    if running(mac.processes()).get(session) != pid:
        return
    try:
        mac.terminate(pid)
        mac.log(project, "stopped %s (pid %d): archived from the app" % (names.short(session), pid))
    except OSError as error:
        mac.log(project, "could not stop %s (pid %d): %r" % (names.short(session), pid, error))


def session_runs(session, mac):
    return running(mac.processes()).get(session, 0)


def terminal_runs(ps_text, mac):
    """Whether a tab can open. The terminal is never started: tabs wait for it."""
    return mac.terminal is not None and mac.terminal.runs(ps_text)


def open_tab(project, session, title, directory, command, check, mac):
    """Open a tab that runs a command; what `check` finds once it runs, else 0."""
    try:
        return mac.terminal.open_tab(names.ready_tab(project, session), title, directory, command, check, patience=25)
    except (OSError, subprocess.SubprocessError) as error:
        mac.log(project, "failed to open a tab for %s: %r" % (names.short(session), error))
        return 0


def show(project, session, record, mac):
    """Open the tab of a hidden session that is now in use."""
    name = record["tmux"]
    title = tab_title(project, record, session)
    command = mac.tmux.attach_command(name)
    if open_tab(project, session, title, record["worktree"], command, lambda: mac.tmux.attached(name), mac):
        # From here on the session lives as long as its tab, like one without tmux.
        mac.tmux.end_with_its_tab(name)
        record["shown"] = True
        mac.log(project, "opened the tab of %s (%s)" % (names.short(session), label(record, session)))
        return
    record["show_failures"] = record.get("show_failures", 0) + 1
    if record["show_failures"] >= SHOW_ATTEMPTS:
        record["shown"] = True  # it keeps running without a tab, driven from the app
    mac.log(project, "no tab opened for %s (attempt %d)" % (names.short(session), record["show_failures"]))


def create(project, state, mac):
    """Prepare a free session: a worktree and Claude Code running hidden in it."""
    # Found and written before anything is made: a missing tool or a settings file that
    # cannot be written must leave no worktree behind.
    tmux, claude = mac.tmux, mac.claude
    settings = mac.settings(project)
    session_settings.stage(project, settings)
    session = str(uuid.uuid4())
    record = {
        "state": "free",
        "started": mac.clock(),
        "changed": mac.clock(),
        "worktree": str(worktrees.folder(names.repository(project)) / names.worktree(project, session)),
        "branch": names.branch(project, session),
        "prompt": "",
        "title": "",
        "cse": "",
        "tidied": False,
        "shown": False,
        "tmux": names.tmux_session(project, session),
    }
    started = 0
    if add_worktree(project, record, session, mac):
        try:
            launched = tmux.execute(hidden_start(project, session, record["worktree"], tmux, claude, settings))
            if launched.returncode == 0:
                started = mac.wait_for(lambda: session_runs(session, mac), 25)
            else:
                mac.log(project, "tmux did not start %s: %s" % (names.short(session), launched.stderr.strip()[:300]))
        except (OSError, subprocess.SubprocessError) as error:
            mac.log(project, "tmux did not start %s: %r" % (names.short(session), error))
    if not started:
        tmux.kill_session(record["tmux"])
        tidy(project, record, mac)
        state["failures"] += 1
        state["retry_after"] = mac.clock() + min(3600, 60 * 2 ** state["failures"])
        mac.log(project, "no free session started (%d in a row)" % state["failures"])
        return
    record["started"] = record["changed"] = mac.clock()
    state["sessions"][session] = record
    state["failures"] = 0
    mac.log(project, "prepared the free session %s" % names.short(session))


def load_state(store):
    state = {"sessions": {}, "read": {}, "failures": 0, "retry_after": 0}
    state.update(store.load({}))
    return state


def save_state(store, state):
    state["read"] = {session: offset for session, offset in state["read"].items() if session in state["sessions"]}
    store.save(state)


def reconcile(project, mac):
    store = mac.store(project, STATE)
    with store.locked():
        state = load_state(store)
        for _ in range(4):  # an action changes what the next pass sees
            before = json.dumps(state, sort_keys=True)
            ps_text = mac.processes()
            live = running(ps_text)
            summaries = {}
            for session, record in state["sessions"].items():
                if session in live or not record["tidied"]:
                    entries, state["read"][session] = transcripts.read_new(
                        transcript(session, record, mac), state["read"].get(session, 0)
                    )
                    summaries[session] = summarize(entries)
            may_create = mac.clock() >= state["retry_after"]
            # Never start the terminal: a session in use gets its tab once the terminal runs.
            state["sessions"], actions = plan(
                state["sessions"], live, summaries, may_create, mac.clock(), terminal_runs(ps_text, mac)
            )
            for action in actions:
                if action[0] == "stop":
                    stop(project, action[1], live[action[1]], mac)
                elif action[0] == "tidy":
                    tidy(project, state["sessions"][action[1]], mac)
                elif action[0] == "discard":
                    tidy(project, action[1], mac)
                elif action[0] == "create":
                    create(project, state, mac)
                elif action[0] == "show":
                    show(project, action[1], state["sessions"][action[1]], mac)
            if json.dumps(state, sort_keys=True) != before:
                save_state(store, state)
            if not actions:
                break
            mac.sleep(2)


def status(project, mac, out=print):
    state = load_state(mac.store(project, STATE))
    live = running(mac.processes())
    if not state["sessions"]:
        out("No session with Claude Code's interface yet.")
        return
    for session in sorted(state["sessions"], key=lambda key: -state["sessions"][key]["changed"]):
        record = state["sessions"][session]
        if session in live:
            where = "pid %d, %s" % (live[session], record["cse"] or "not in the app yet")
            where += "" if record.get("shown", True) else ", hidden"
        else:
            where = "not running"
        out("%s  (%s)" % (describe(session, record), where))


def reopen(project, text, mac, out=print):
    """Open a closed session again; 0 when it is open or the list was asked for."""
    store = mac.store(project, STATE)
    with store.locked():
        state = load_state(store)
        sessions = state["sessions"]
        found = match(sessions, text)
        if not text.strip() or len(found) != 1:
            listed = found or match(sessions, "")
            if not text.strip():
                out("Closed sessions:" if listed else "No closed session.")
            elif found:
                out('Several closed sessions match "%s"; run it again with the id of one:' % text)
            else:
                out('No closed session matches "%s".%s' % (text, " The closed ones:" if listed else ""))
            for session in listed:
                out("  " + describe(session, sessions[session]))
            return 0 if not text.strip() else 1
        session = found[0]
        record = sessions[session]
        if mac.terminal is None:
            out("No terminal is set up for tabs. Nothing was reopened.")
            return 1
        if not mac.terminal.runs(mac.processes()):
            out("%s is not running on the Mac, so no tab can open. Nothing was reopened." % mac.terminal.title)
            return 1
        claude, settings = mac.claude, mac.settings(project)
        if not add_worktree(project, record, session, mac):
            out("Could not prepare the worktree %s. Nothing was reopened." % record["worktree"])
            return 1
        session_settings.stage(project, settings)
        title = tab_title(project, record, session)
        command = command_line(project, session, True, claude, settings)
        if not open_tab(project, session, title, record["worktree"], command, lambda: session_runs(session, mac), mac):
            out("The tab did not start. Nothing was reopened.")
            return 1
        record.update(state="used", started=mac.clock(), changed=mac.clock(), tidied=False, shown=True, tmux="")
        save_state(store, state)
        mac.log(project, "reopened %s (%s)" % (names.short(session), label(record, session)))
        out(
            'Reopened "%s" in a new tab on the Mac. It comes back online in the Claude app, as the '
            "same session, within a few seconds." % label(record, session)
        )
        return 0
