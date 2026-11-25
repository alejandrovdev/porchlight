"""Sessions with Claude Code's own interface, always one ready, shown in a tab while in use.

A session the Remote Control server starts has no terminal, and the app cannot start it
again once it is archived. These sessions are the other kind: Claude Code's interactive
interface with Remote Control on, so the Claude mobile app drives the same conversation a
terminal tab shows.

    reconcile(project, mac)      keep one free session ready, open the tab of a session
                                 that is now in use, stop a session the app archived, tidy
                                 what ended
    status(project, mac)         print the sessions and their state, and the back-off a
                                 failed free session waits out
    waiting_for_trust(project, mac)
                                 the running sessions that wait on Claude Code's workspace
                                 trust question
    retry(project, mac)          clear that back-off, so the service's next pass tries
    held(project, mac)           whether the state holds a session at all
    reopen(project, text, mac)   open a closed session again, back online in the app: in a
                                 new tab, or hidden for a project without tabs; without a
                                 name, list the closed ones
    reopen_anywhere(configuration, text, mac)
                                 the same, among the closed sessions of every project
    let_go(project, mac)         end the free session, as turning the feature off does
    left_behind(name, mac)       a project the configuration no longer has, whose free
                                 session `let_go` ends

One free session always waits, in its own worktree, named `<prefix>-...` in the app. It
waits hidden: it runs in a detached session of the tool's own tmux server, so no tab stays
open for it. The user starts work by writing in it from the app; it then counts as used, a
tab opens attached to it, and another free one is prepared. Closing that tab ends the
session, as it would without tmux. Archiving a session in the app ends its process, which
closes its tab. Unarchiving it in the app reaches nothing on the Mac, so a session comes
back with `reopen`, which a session runs when the user asks it to; a reopened session runs
in its tab directly, without tmux, and in a project without tabs it runs hidden, in tmux,
as a ready session does.

A new worktree gets the files the repository's `.worktreeinclude` lists, as Claude Code's
own worktrees do, before its session starts; a file that cannot be copied is logged.

Only sessions in this project's own state are ever stopped or tidied; a session someone
started by hand is never touched. A worktree is removed only when it is clean and its HEAD
is on the base branch; otherwise it is unlocked and left.

Three features of a project decide what happens here. Without `ready-session` no free
session is prepared, and one that still waits from before is ended and discarded; a session
in use is followed until it ends, so the app still archives it and its worktree is still
tidied. Without `tabs` a session in use gets no tab and the terminal is never looked for:
it keeps running hidden, and `status` prints the command that attaches to it; a session
that is reopened comes back hidden too, and `reopen` prints that command. Without `reopen`
a session is told nothing about reopening and `reopen` refuses. With `tabs`, a session whose
tab failed to open three times keeps running hidden, and `status` prints that command too.

A free session that fails to start is tried again later: two minutes after the first
failure, twice as long after each next one, at most an hour. `status` says when the next
try comes, and `retry` clears the wait. Writing the state does not wake the service: the
cleared project is tried at the service's next pass, which comes at its interval.

Claude Code asks, the first time it runs in a folder nobody trusted yet, whether the person
trusts it, and waits there: such a session never reaches the app. A running session that is
not in the app yet has its pane read through tmux (read only: no key is sent, the question
is never answered for the person, and none of Claude Code's own files is written). When it
shows the question, `status` says so and prints the command that attaches to it, tabs or
not, and the service logs it once for that session. A pane that cannot be read is not known.
"""

import calendar
import dataclasses
import json
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path

from .. import config, names, session_settings
from ..atoms import include, processes, tools, transcripts, worktrees

STATE = "ready-sessions"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
# What Claude Code writes in the transcript when the app ends or archives the session.
ARCHIVED = "Remote Control disconnected — this session was ended or archived from another device or app"
CLOSED = ("archived", "closed")
FORGET_AFTER = 30 * 86400
SHOW_ATTEMPTS = 3
ORIGIN = "origin"  # the remote whose default branch a worktree starts from
NO_BASE = "no base branch is known"
# Words of Claude Code's workspace trust question, any of which tells it is asked: its
# question ("Is this a project you created or one you trust?"), its answer ("Yes, I trust
# this folder") and an earlier wording ("Do you trust the files in this folder?").
TRUST_WORDS = ("one you trust", "trust this folder", "trust the files in this folder")
WAITS_FOR_TRUST = "waiting for you to trust the folder"


def note(porchlight="", tabs=True):
    """What a session is told, beside its system prompt: where it runs and, when the
    project reopens sessions, how to reopen another. `porchlight` is the command that runs
    the tool, as a shell reads it; without it nothing is said of reopening."""
    where = "This session runs on the user's Mac and is driven from the Claude mobile app."
    if not porchlight:
        return where
    how = "opens the session in a new tab" if tabs else "starts the session again on the Mac, out of sight,"
    return (
        where + " "
        "When the user asks to reopen a session (for example: reopen <name>) or to list the closed "
        "ones, run this with Bash and report what it prints: %s reopen <name>. Without a name it "
        "lists the closed sessions; when the name matches none or several, pick the id from that "
        "list and run it again with the id. It %s and puts it back online in the app." % (porchlight, how)
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


def plan(sessions, live, summaries, create, now, tabs=True, ready=True):
    """Decide what to do with the known sessions: (the new records, the actions).

    Actions: ("stop", id) ends the process of a session the app archived, ("tidy", id)
    cleans up after a session that ended, ("discard", record) drops a free session
    nobody used, ("create",) prepares a free session, ("show", id) opens the tab of a
    hidden session that is now in use, asked only while tabs can open.

    `ready` is whether a free session is kept waiting. When it is not, none is prepared
    and ("release", id) ends the one that still waits; once it ended it is discarded like
    any other. A session in use is followed to its end either way.
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
            elif state == "free" and not ready:
                actions.append(("release", session))
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
    if ready and create and not any(record["state"] == "free" for record in new.values()):
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


def command_line(project, session, resume, claude, settings, porchlight):
    """What a tab runs: Claude Code with Remote Control, on a new or a known conversation.
    `porchlight` is the command that runs the tool, for what the session is told."""
    words = [
        claude,
        "--resume" if resume else "--session-id",
        session,
        "--permission-mode",
        project.permission_mode,
        "--settings",
        str(settings),
        "--append-system-prompt",
        note(porchlight if project.has("reopen") else "", project.has("tabs")),
        "--remote-control-session-name-prefix",
        project.prefix,
        "--remote-control",  # last: a word after it would be the session's name
    ]
    return "exec " + " ".join(shlex.quote(word) for word in words)


def hidden_start(project, session, worktree, tmux, claude, settings, porchlight, resume=False):
    """What starts a session nobody sees: Claude Code in a detached tmux session, on a new
    conversation or, to reopen one, on a known conversation."""
    return tmux.new_session(
        names.tmux_session(project, session),
        worktree,
        command_line(project, session, resume, claude, settings, porchlight),
    )


def label(record, session):
    return record["title"] or record["prompt"] or names.short(session)


def tab_title(project, record, session):
    return names.tab_title(project, label(record, session)[:40])


def describe(session, record):
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(record["changed"]))
    return "%s  %-8s %s  %s" % (names.short(session), record["state"], when, label(record, session))


def asks_for_trust(text):
    """Whether a pane's text shows Claude Code's workspace trust question, whatever its
    case and however its lines break."""
    said = " ".join((text or "").split()).casefold()
    return any(words in said for words in TRUST_WORDS)


def trust_advice(project, attach, where="that session"):
    """What to do about a session that waits on the trust question; `attach` says where the
    command that attaches to it is."""
    return (
        'answer "Yes, I trust this folder" in %s (%s), and run `claude` once in %s and trust it '
        "so the next sessions do not ask" % (where, attach, names.repository(project))
    )


def given_up(record):
    """Whether no tab will open for a session: its tab failed too often while it stayed in
    tmux (a reopened one runs in its tab, without tmux)."""
    return bool(record.get("tmux")) and record.get("show_failures", 0) >= SHOW_ATTEMPTS


def hidden(record):
    """Whether a running session has no tab: its tab was not opened yet, or was given up on."""
    return not record.get("shown", True) or given_up(record)


def offer(text, found, closed, out):
    """Say why no session is reopened and list the candidates: those a name matched, else
    every closed one. Both come as lines ready to print. 0 when the list was asked for."""
    listed = found or closed
    if not text.strip():
        out("Closed sessions:" if listed else "No closed session.")
    elif found:
        out('Several closed sessions match "%s"; run it again with the id of one:' % text)
    else:
        out('No closed session matches "%s".%s' % (text, " The closed ones:" if listed else ""))
    for line in listed:
        out("  " + line)
    return 0 if not text.strip() else 1


# What follows touches the Mac, through the `mac` it is given: processes, git, tmux, the
# terminal and the state file.


def transcript(session, record, mac):
    return transcripts.folder(mac.transcripts, record["worktree"]) / (session + ".jsonl")


def base_branch(project, mac):
    """Where a new worktree starts and what a finished one must be on. The project's own
    choice; else the default branch git recorded for the repository's origin; else, for a
    repository that has no origin, the branch its main checkout is on. None when all fail."""
    if project.base:
        return project.base
    repository = names.repository(project)
    stated = worktrees.default_base(mac.git, repository)
    if stated or worktrees.has_remote(mac.git, repository, ORIGIN):
        return stated  # an origin that states no default branch is not replaced by a guess
    return worktrees.current_branch(mac.git, repository) or None


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
        result = worktrees.add(mac.git, repository, path, reason, branch)
        if result.returncode != 0:
            result = worktrees.add(mac.git, repository, path, reason, branch, "--detach")  # checked out elsewhere
    else:
        base = base_branch(project, mac)
        if base is None:
            mac.log(project, "no worktree for %s: %s; set `base` for the project" % (names.short(session), NO_BASE))
            return False
        if names.owns_branch(project, branch):
            result = worktrees.add(mac.git, repository, path, reason, base, "-b", branch)
        else:
            result = worktrees.add(mac.git, repository, path, reason, base, "--detach")
    if result.returncode != 0:
        mac.log(project, "no worktree for %s: %s" % (names.short(session), result.stderr.strip()[:300]))
        return False
    copy_included(project, session, path, mac)
    return True


def files(count):
    return "%d file%s" % (count, "" if count == 1 else "s")


def copy_included(project, session, path, mac):
    """Copy into a new worktree the files its repository's .worktreeinclude lists; a copy
    that fails is logged, and the session starts all the same."""
    copied = include.copy(mac.git, names.repository(project), path)
    where = "listed in %s into the worktree of %s" % (include.FILE, names.short(session))
    if copied.files:
        mac.log(project, "copied %s %s" % (files(len(copied.files)), where))
    if copied.failures:
        why = "; ".join("%s: %s" % (failed, reason) if failed else reason for failed, reason in copied.failures)
        mac.log(project, "could not copy %s %s: %s" % (files(len(copied.failures)), where, why[:300]))


def tidy(project, record, mac):
    """Remove the worktree of a session that ended when nothing in it would be lost."""
    tidied = tidy_worktree(project, record["worktree"], mac)
    if tidied is not None:
        record["branch"] = tidied[1]


def tidy_worktree(project, path, mac, log=None):
    """Remove a worktree of the project's repository whose session ended, when nothing in it
    would be lost: it is clean and its HEAD is on the base branch. Otherwise unlock it,
    leave it and say why in the project's log, or to `log` when one is given. Its branch is
    deleted only when it was made for a ready session. (what happened, its branch):
    "removed", "kept" or "failed"; None when the folder is not there."""
    say = log or (lambda line: mac.log(project, line))
    repository = names.repository(project)
    name = Path(path).name
    if not Path(path).is_dir():
        return None
    branch = worktrees.current_branch(mac.git, path)
    clean = worktrees.is_clean(mac.git, path)
    base = base_branch(project, mac)
    merged = base is not None and worktrees.is_merged(mac.git, path, base)
    worktrees.unlock(mac.git, repository, path)
    if not (clean and merged):
        if base is None:
            why = NO_BASE
        else:
            why = "it has changes" if merged else "its commits are not on %s" % base
        say("kept the worktree %s (%s)" % (name, why))
        return "kept", branch
    removed = worktrees.remove(mac.git, repository, path)
    if removed.returncode != 0:
        say("could not remove the worktree %s: %s" % (name, removed.stderr.strip()[:300]))
        return "failed", branch
    if names.owns_branch(project, branch):
        worktrees.delete_branch(mac.git, repository, branch)
    say("removed the worktree %s" % name)
    return "removed", branch


def stop(project, session, pid, mac, why="archived from the app"):
    """End the process of a session, which closes its tab or its hidden tmux session."""
    if running(mac.processes()).get(session) != pid:
        return
    try:
        mac.terminate(pid)
        mac.log(project, "stopped %s (pid %d): %s" % (names.short(session), pid, why))
    except OSError as error:
        mac.log(project, "could not stop %s (pid %d): %r" % (names.short(session), pid, error))


def pane_text(name, mac):
    """What a tmux session shows; None when it cannot be read, tmux missing included."""
    try:
        return mac.tmux.pane_text(name)
    except tools.ToolNotFound:
        return None


def trusting(state, live, mac):
    """The sessions of a state whose pane shows the trust question: only those that run in
    tmux and are not in the app yet are read. A pane that cannot be read is left out."""
    return {
        session
        for session, record in state["sessions"].items()
        if session in live
        and not record["cse"]
        and record.get("tmux")
        and asks_for_trust(pane_text(record["tmux"], mac))
    }


def notice_trust(project, state, live, mac):
    """Log each session the first time it is seen waiting on the trust question; True when
    the state changed."""
    noticed = False
    for session in sorted(trusting(state, live, mac)):
        record = state["sessions"][session]
        if record.get("trust_logged"):
            continue
        record["trust_logged"] = True
        noticed = True
        attach = "`%s` prints the command that attaches to it" % names.command("status")
        advice = trust_advice(project, attach)
        mac.log(project, "%s waits for you to trust the folder: %s" % (names.short(session), advice))
    return noticed


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


def start_hidden(project, session, words, mac):
    """Run what starts a session in tmux; the pid of the session once it runs, else 0."""
    try:
        launched = mac.tmux.execute(words)
        if launched.returncode == 0:
            return mac.wait_for(lambda: session_runs(session, mac), 25)
        mac.log(project, "tmux did not start %s: %s" % (names.short(session), launched.stderr.strip()[:300]))
    except (OSError, subprocess.SubprocessError) as error:
        mac.log(project, "tmux did not start %s: %r" % (names.short(session), error))
    return 0


def create(project, state, mac):
    """Prepare a free session: a worktree and Claude Code running hidden in it."""
    # Found and written before anything is made: a missing tool or a settings file that
    # cannot be written must leave no worktree behind.
    tmux, claude, porchlight = mac.tmux, mac.claude, mac.porchlight
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
        words = hidden_start(project, session, record["worktree"], tmux, claude, settings, porchlight)
        started = start_hidden(project, session, words, mac)
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


def watched(project, mac):
    """What tells at once that a session of this project needs a pass: the transcript of
    each session that waits or is in use, where its first prompt and the app's archive
    are written, and the folder that transcript appears in."""
    paths = []
    for session, record in sorted(load_state(mac.store(project, STATE))["sessions"].items()):
        if record["state"] in ("free", "used"):
            file = transcript(session, record, mac)
            paths += [file, file.parent]
    return paths


def reconcile(project, mac):
    ready, tabs = project.has("ready-session"), project.has("tabs")
    store = mac.store(project, STATE)
    if not ready and not store.path.exists():
        return  # the feature is off and holds nothing
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
            may_create = ready and mac.clock() >= state["retry_after"]
            # Never start the terminal: a session in use gets its tab once the terminal runs.
            # A project without tabs does not even look for it.
            may_show = tabs and terminal_runs(ps_text, mac)
            state["sessions"], actions = plan(
                state["sessions"], live, summaries, may_create, mac.clock(), may_show, ready
            )
            for action in actions:
                if action[0] == "stop":
                    stop(project, action[1], live[action[1]], mac)
                elif action[0] == "release":
                    stop(project, action[1], live[action[1]], mac, "the ready session is turned off")
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
        if notice_trust(project, state, live, mac):
            save_state(store, state)


def free(store):
    return {session for session, record in load_state(store)["sessions"].items() if record["state"] == "free"}


def let_go(project, mac):
    """End the free session a project holds, the way turning the feature off does, and
    prepare or show no other: (how many it let go of, how many did not end)."""
    store = mac.store(project, STATE)
    before = free(store)
    kept = tuple(feature for feature in project.features if feature not in ("ready-session", "tabs"))
    reconcile(dataclasses.replace(project, features=kept), mac)
    left = free(store) & before
    return len(before - left), len(left)


def left_behind(name, mac):
    """A project the configuration no longer has, as the tool's state still knows it: a
    project without features, in the folder its free sessions were made in, which `let_go`
    takes. None when the state holds no free session of it, or when their worktrees do not
    name one folder that is still there: nothing can be tidied in a folder that is gone."""
    known = config.Project(name, "", "", ())
    sessions = load_state(mac.store(known, STATE)).get("sessions")
    folders = set()
    for session, record in (sessions if isinstance(sessions, dict) else {}).items():
        if not isinstance(record, dict) or record.get("state") != "free":
            continue
        worktree = Path(str(record.get("worktree") or ""))
        if worktree.name != names.worktree(known, session) or worktree.parent.parts[-2:] != worktrees.FOLDER:
            return None  # not where this tool makes a worktree: it tells no folder
        folders.add(worktree.parent.parent.parent)
    if len(folders) != 1:
        return None
    (folder,) = folders
    return config.Project(name, str(folder), "", ()) if folder.is_dir() else None


def held(project, mac):
    """Whether the project's state holds a session, whatever its state."""
    return bool(load_state(mac.store(project, STATE))["sessions"])


def backing_off(project, state, mac):
    """Whether the free session waits out a back-off: a failure set the next try later."""
    return project.has("ready-session") and state["failures"] > 0 and mac.clock() < state["retry_after"]


def status(project, mac, out=print):
    state = load_state(mac.store(project, STATE))
    print_sessions(project, state, mac, out)
    if backing_off(project, state, mac):
        failures = state["failures"]
        out(
            "No free session for now: %s. The next one is at %s; to try now: %s"
            % (
                "1 attempt failed" if failures == 1 else "%d attempts in a row failed" % failures,
                time.strftime("%Y-%m-%d %H:%M", time.localtime(state["retry_after"])),
                names.command("retry", "--project", project.name),
            )
        )


def print_sessions(project, state, mac, out):
    live = running(mac.processes())
    if not state["sessions"]:
        out("No session with Claude Code's interface yet.")
        return
    waiting = trusting(state, live, mac)
    for session in sorted(state["sessions"], key=lambda key: -state["sessions"][key]["changed"]):
        record = state["sessions"][session]
        if session in live:
            app = WAITS_FOR_TRUST if session in waiting else record["cse"] or "not in the app yet"
            where = "pid %d, %s" % (live[session], app)
            where += ", hidden" if hidden(record) else ""
        else:
            where = "not running"
        out("%s  (%s)" % (describe(session, record), where))
        no_tab_will_open = not project.has("tabs") or given_up(record)
        if session in waiting or (session in live and hidden(record) and record.get("tmux") and no_tab_will_open):
            out("    " + mac.tmux.attach(record["tmux"]))  # how to see it, and to answer the question


def waiting_for_trust(project, mac):
    """The running sessions of a project that wait on Claude Code's workspace trust
    question, in order. Only read: nothing is answered and the state is not written."""
    state = load_state(mac.store(project, STATE))
    if not state["sessions"]:
        return []
    return sorted(trusting(state, running(mac.processes()), mac))


def retry(project, mac, out, within):
    """Clear the back-off of a project's free session, so that the service's next pass, in
    `within` seconds at most, tries to prepare it; True when there was one. No session is
    started here, and a project with no state gets no file."""
    store = mac.store(project, STATE)
    if store.path.exists():
        with store.locked():
            state = load_state(store)
            failures = state["failures"]
            if failures > 0 or state["retry_after"] > mac.clock():
                state["failures"] = state["retry_after"] = 0
                save_state(store, state)
                mac.log(project, "the back-off is cleared by hand (%d failed in a row)" % failures)
                out(
                    "%s: the back-off is cleared (%s had failed). The service tries again at its next pass, "
                    "within %d seconds." % (project.name, "1 attempt" if failures == 1 else "%d attempts" % failures, within)
                )
                return True
    out("%s: no back-off; nothing to clear." % project.name)
    return False


def reopen_hidden(project, session, record, mac, out):
    """Resume a closed session with no tab, in tmux, as a ready session starts; True when
    it runs. The record then says it is in use and hidden; saving it is the caller's."""
    # Found and written before anything is made, as for a new session.
    tmux, claude, porchlight = mac.tmux, mac.claude, mac.porchlight
    settings = mac.settings(project)
    session_settings.stage(project, settings)
    name = names.tmux_session(project, session)
    if not add_worktree(project, record, session, mac):
        out("Could not prepare the worktree %s. Nothing was reopened." % record["worktree"])
        return False
    words = hidden_start(project, session, record["worktree"], tmux, claude, settings, porchlight, resume=True)
    if not start_hidden(project, session, words, mac):
        tmux.kill_session(name)
        tidy(project, record, mac)  # the worktree goes back to how a closed session leaves it
        out("The session did not start in tmux. Nothing was reopened.")
        return False
    record.update(state="used", started=mac.clock(), changed=mac.clock(), tidied=False, shown=False, tmux=name)
    record.pop("show_failures", None)
    mac.log(project, "reopened %s (%s), hidden" % (names.short(session), label(record, session)))
    out(
        'Reopened "%s" (project %s), hidden: this project opens no tabs. It comes back online in the '
        "Claude app, as the same session, within a few seconds. To see it on the Mac, run:"
        % (label(record, session), project.name)
    )
    out("    " + tmux.attach(name))
    return True


def reopen(project, text, mac, out=print):
    """Open a closed session of a project again; 0 when it is open or the list was asked for."""
    if not project.has("reopen"):
        out('The project "%s" does not have the feature "reopen". Nothing was reopened.' % project.name)
        return 1
    store = mac.store(project, STATE)
    with store.locked():
        state = load_state(store)
        sessions = state["sessions"]
        found = match(sessions, text)
        if not text.strip() or len(found) != 1:
            lines = {session: describe(session, sessions[session]) for session in match(sessions, "")}
            return offer(text, [lines[session] for session in found], list(lines.values()), out)
        session = found[0]
        record = sessions[session]
        if not project.has("tabs"):
            if not reopen_hidden(project, session, record, mac, out):
                return 1
            save_state(store, state)
            return 0
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
        command = command_line(project, session, True, claude, settings, mac.porchlight)
        if not open_tab(project, session, title, record["worktree"], command, lambda: session_runs(session, mac), mac):
            out("The tab did not start. Nothing was reopened.")
            return 1
        record.update(state="used", started=mac.clock(), changed=mac.clock(), tidied=False, shown=True, tmux="")
        save_state(store, state)
        mac.log(project, "reopened %s (%s)" % (names.short(session), label(record, session)))
        out(
            'Reopened "%s" (project %s) in a new tab on the Mac. It comes back online in the Claude app, '
            "as the same session, within a few seconds." % (label(record, session), project.name)
        )
        return 0


def reopen_anywhere(configuration, text, mac, out=print):
    """Open a closed session again, looked for in every project that reopens sessions.

    Exactly one match is reopened, in its own project. With none or several, or without a
    name, the candidates are listed, each with the project it belongs to. 0 when a session
    is open again or the list was asked for.
    """
    projects = [project for project in configuration.projects if project.has("reopen")]
    if not projects:
        out('No project has the feature "reopen". Nothing was reopened.')
        return 1
    found, closed = [], []
    for project in projects:
        sessions = load_state(mac.store(project, STATE))["sessions"]
        matching = match(sessions, text)
        for session in match(sessions, ""):
            candidate = (-sessions[session]["changed"], project.name, session, sessions[session])
            closed.append(candidate)
            if session in matching:
                found.append(candidate)
    if text.strip() and len(found) == 1:
        _, name, session, _ = found[0]
        # Asked of its project by its whole id, which is read again there, under the lock.
        return reopen(configuration.project(name), session, mac, out)
    width = max((len(name) for _, name, _, _ in closed), default=0)

    def lines(candidates):
        """Each candidate with its project, the latest first."""
        return [
            "%-*s  %s" % (width, name, describe(session, record))
            for _, name, session, record in sorted(candidates, key=lambda candidate: candidate[:3])
        ]

    return offer(text, lines(found), lines(closed), out)
