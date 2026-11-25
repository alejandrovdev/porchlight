"""Make the sessions created from the Claude mobile app show up in `/resume`.

Claude Code's `/resume` list leaves out every session that did not start in a terminal,
and the Remote Control server's sessions are among them. This keeps, for each of those
sessions, a copy in the repository's own session folder that `/resume` does list. The
copy is a separate session: continuing it in the terminal does not reach the phone, and
the phone's session is never changed.

    sync(project, mac)          bring the copies up to date; prints nothing
    list_copies(project, mac)   print each copy and the command that resumes it
    report(configuration, mac)  the same list for every project that keeps copies

A copy that was continued in the terminal is never overwritten: what the phone adds
afterwards goes to a new copy.

A project without `resume-list` gets no copy; the ones written before stay where they are.
"""

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

from .. import names
from ..atoms import transcripts, worktrees

STATE = "resume-list"
SERVER_ORIGIN = b'"entrypoint":"sdk-cli"'
TERMINAL_ORIGIN = b'"entrypoint":"cli"'


def main_folder(project, mac):
    """Where Claude Code keeps the sessions started in the repository itself."""
    return transcripts.folder(mac.transcripts, names.repository(project))


def server_transcripts(project, mac):
    """The transcripts of the sessions the server started in this repository's worktrees."""
    worktree = worktrees.of_server_session(names.repository(project), names.SERVER_SESSION)
    for folder in sorted(Path(mac.transcripts).glob(transcripts.folder_name(worktree) + "*")):
        yield from transcripts.server_transcripts(folder)


def copy_id(project, source_id, generation):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, names.copy_name(project, source_id, generation)))


def write_copy(folder, source, data, target_id):
    """Write the copy whole, under its own id and as a terminal session."""
    body = data.replace(
        b'"sessionId":"%s"' % source.stem.encode(), b'"sessionId":"%s"' % target_id.encode()
    ).replace(SERVER_ORIGIN, TERMINAL_ORIGIN)
    target = folder / (target_id + ".jsonl")
    draft = folder / (target_id + ".syncing")
    draft.write_bytes(body)
    source_stat = source.stat()
    os.utime(draft, ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns))
    os.replace(draft, target)
    written = target.stat()
    return {"copy_size": written.st_size, "copy_mtime_ns": written.st_mtime_ns}


def sync_one(project, source, state, mac):
    folder = main_folder(project, mac)
    data = transcripts.complete_lines(source)
    first_origin = re.search(rb'"entrypoint":"[^"]*"', data)
    if first_origin is None or first_origin.group(0) != SERVER_ORIGIN:
        return
    known = state.get(source.stem)
    if known is not None and known["source_bytes"] == len(data):
        return

    generation = 1 if known is None else known["generation"]
    action = "created"
    if known is not None:
        target = folder / (known["copy"] + ".jsonl")
        if target.exists():
            current = target.stat()
            untouched = current.st_size == known["copy_size"] and current.st_mtime_ns == known["copy_mtime_ns"]
            if untouched:
                action = "updated"
            else:
                generation += 1
                action = "created (the previous copy was continued in the terminal)"

    target_id = copy_id(project, source.stem, generation)
    written = write_copy(folder, source, data, target_id)
    state[source.stem] = dict(
        written,
        generation=generation,
        copy=target_id,
        source_bytes=len(data),
        source=str(source),
    )
    mac.log(project, "%s the copy %s from %s" % (action, target_id, source.parent.name[-34:]))


def sync(project, mac):
    if not project.has("resume-list") or not main_folder(project, mac).is_dir():
        return
    store = mac.store(project, STATE)
    with store.locked():
        state = store.load({})
        before = json.dumps(state, sort_keys=True)
        for source in server_transcripts(project, mac):
            try:
                sync_one(project, source, state, mac)
            except Exception as error:  # one bad transcript must not stop the others
                mac.log(project, "failed %s: %r" % (source.name, error))
        if json.dumps(state, sort_keys=True) != before:
            store.save(state)


def describe(source):
    """The first prompt and the working directory a server session recorded."""
    prompt, cwd = "", ""
    with open(source, "rb") as handle:
        for entry in transcripts.entries(handle.readlines()[:400]):
            if not cwd and isinstance(entry.get("cwd"), str):
                cwd = entry["cwd"]
            if not prompt and entry.get("type") == "queue-operation":
                content = entry.get("content")
                if isinstance(content, str):
                    prompt = content
            if not prompt and entry.get("type") == "last-prompt":
                prompt = str(entry.get("lastPrompt") or "")
            if prompt and cwd:
                break
    return " ".join(prompt.split()), cwd


def running_commands(mac):
    try:
        return mac.processes()
    except (OSError, subprocess.SubprocessError):
        return ""


CAUTION = (
    "Each copy is its own session: continuing it does not reach the phone.",
    "For one that is live on the phone, archive it there first or expect two",
    "agents in the same worktree.",
)


def list_copies(project, mac, out=print, caution=True):
    """Print a project's copies; True when it has some. `caution` adds what to know
    before resuming one."""
    folder = main_folder(project, mac)
    state = mac.store(project, STATE).load({})
    rows = []
    for known in state.values():
        source = Path(known.get("source", ""))
        copy = folder / (known["copy"] + ".jsonl")
        if not source.is_file() or not copy.is_file():
            continue
        prompt, cwd = describe(source)
        rows.append((source.stat().st_mtime, known["copy"], prompt, cwd))
    if not rows:
        out("No session created from the phone has a copy yet.")
        return False
    commands = running_commands(mac)
    for modified, target_id, prompt, cwd in sorted(rows, reverse=True):
        session = Path(cwd).name.replace(worktrees.SERVER_PREFIX, "", 1)
        if cwd and ("--session-id %s " % session) in commands:
            status = "live on the phone"
        elif cwd and Path(cwd).is_dir():
            status = "worktree kept"
        else:
            status = "worktree removed"
        resume = "claude --resume " + target_id
        if status != "worktree removed":
            resume = "cd '%s' && %s" % (cwd, resume)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(modified))
        out("%s  %-17s  %s" % (when, status, prompt[:90] or "(no prompt)"))
        out("    " + resume)
    if caution:
        out("")
        for line in CAUTION:
            out(line)
    return True


def report(configuration, mac, out=print, sync_first=False):
    """Print the copies of every project that keeps them, each under its project's name;
    `sync_first` brings them up to date before. 0 when every project could be read."""
    projects = [project for project in configuration.projects if project.has("resume-list")]
    if not projects:
        out('No project has the feature "resume-list". Nothing to list.')
        return 1
    code, listed = 0, False
    for index, project in enumerate(projects):
        if index:
            out("")
        out(project.name)
        try:
            if sync_first:
                sync(project, mac)
            listed = list_copies(project, mac, lambda line: out("  " + line if line else ""), caution=False) or listed
        except Exception as error:  # one project never hides the others
            mac.log(project, "resume list failed: %r" % (error,))
            out("  Could not read its copies: %r" % (error,))
            code = 1
    if listed:
        out("")
        for line in CAUTION:
            out(line)
    return code
