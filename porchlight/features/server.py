"""The Remote Control server of a project: what lets the Claude mobile app create and
archive sessions on the Mac. Each session gets its own git worktree and runs with the
user's own Claude Code configuration.

    run(project, mac)              become the server (what a background service runs)
    tidy_worktrees(project, mac)   remove the worktrees of its sessions that ended, when
                                   nothing in them would be lost, then their branches when
                                   their commits are on the base branch; prints nothing

The server's sessions have no terminal and the app cannot start one again once it is
archived: `view_tabs` shows each in a read-only tab and `resume_list` keeps a copy that
`/resume` lists.

Never run two servers for the same repository at once: whatever starts `run` keeps it to
one. And never change the settings file while the server runs (see `session_settings`):
a change waits and `run` installs it the next time the server starts.

Keeping the Mac awake is not the server's: see `keep_awake`.

The server leaves a session's worktree, `.claude/worktrees/bridge-<session>`, behind when
the session ends. A pass removes it by the rule of a ready session's worktree
(`ready_sessions.tidy_worktree`): only once no process runs its session and the worktree
and its transcript have been quiet for a while, only when git lists it as a worktree of the
repository, and only when it is clean, its HEAD is on the base branch and no file
`.worktreeinclude` lists was changed in it; otherwise it is
left, unlocked, and the project's log says why. A locked worktree is looked at only when
Claude Code locked it (its reason starts with "claude ") and no process the reason names
runs; any other lock leaves it as it is, still locked. Each worktree is checked once after
its session ends, and again when something in it or in the repository's branches changed,
or when the process that held its lock ended; the log says why a worktree is left only when
that reason is new. A folder of another name, a link, and anything unclear (a git error)
are left alone.

Once a worktree is removed, its branch goes too (`git branch -d`, never `-D`), only when it
is the branch Claude Code made for that session (`worktree-bridge-<session>`), the worktree
had it checked out, no other worktree has it checked out, and every commit of it is on the
base branch. Otherwise the branch stays and the log says why, once: the branch is looked at
only when its worktree is removed. Any other branch is never touched.
"""

import os
import re
from pathlib import Path

from .. import names, session_settings
from ..atoms import processes, tools, transcripts, worktrees
from . import live_view, ready_sessions

WORKTREES = "server-worktrees"  # the state: each worktree checked, and how it looked then
QUIET = 600  # seconds a worktree and its transcript stay unchanged before its session counts as ended
BRIDGE = re.compile(re.escape(worktrees.SERVER_PREFIX) + live_view.SESSION.pattern)
CLAUDE_LOCK = "claude "  # how Claude Code's own lock reasons start: "claude agent agent-<id> (pid N start ...)"
LOCK_PID = re.compile(r"\bpid (\d+)")


def command(project, claude, settings):
    return [
        claude,
        "remote-control",
        "--spawn",
        "worktree",
        "--permission-mode",
        project.permission_mode,
        "--settings",
        str(settings),
        "--no-create-session-in-dir",
    ]


def environment(environ):
    """The environment of the server and its sessions. A background service starts with
    a minimal PATH: Homebrew's folders come first, then whatever was there."""
    return dict(environ, PATH=tools.search_path(environ.get("PATH", "")))


def run(project, mac, execute=None, chdir=None):
    """Start the server in the project's folder; this process becomes the server."""
    claude = mac.claude
    settings = mac.settings(project)
    mac.make_state_root()  # the server may be the first to write in it
    session_settings.stage(project, settings)
    session_settings.install_pending(settings)  # no server runs yet: what waited goes in now
    (chdir or os.chdir)(names.repository(project))
    (execute or os.execve)(claude, command(project, claude, settings), environment(mac.environ))


def bridge_folders(repository):
    """The folders the server made for its sessions: {name: path}. Never a link."""
    found = {}
    for path in worktrees.folder(repository).glob(worktrees.SERVER_PREFIX + "*"):
        if BRIDGE.fullmatch(path.name) and not path.is_symlink() and path.is_dir():
            found[path.name] = path
    return found


def quiet(path, mac):
    """Whether a worktree was made, and its session's transcript last written, QUIET seconds
    ago or more: a session that is starting has its worktree before its process shows."""
    try:
        times = [path.stat().st_birthtime]
        for transcript in transcripts.folder(mac.transcripts, path).glob("*.jsonl"):
            times.append(transcript.stat().st_mtime)
    except (OSError, AttributeError):
        return False
    return mac.clock() - max(times) >= QUIET


def admin_folder(path):
    """The folder where git keeps a worktree's HEAD and index, as its `.git` file names it;
    None when it names none."""
    try:
        text = (path / ".git").read_text(encoding="utf8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("gitdir: "):
        return None
    return path / text[len("gitdir: ") :].strip()


def stamps(paths):
    """The time and size of each path, as JSON keeps them; None for one that is not there."""
    seen = []
    for path in paths:
        try:
            stat = path.stat()
            seen.append([str(path), stat.st_mtime_ns, stat.st_size])
        except OSError:
            seen.append([str(path), None, None])
    return seen


def branches_look(repository):
    """What a commit or a merge on any branch rewrites in the repository, git not asked:
    `packed-refs`, the reference table, and each folder of `refs/heads` and `refs/remotes`."""
    common = repository / ".git"
    paths = [common / "packed-refs", common / "reftable"]
    for top in (common / "refs" / "heads", common / "refs" / "remotes"):
        paths.append(top)
        for folder, children, _ in os.walk(top):
            children.sort()
            paths += [Path(folder) / child for child in children]
    return stamps(paths)


def worktree_look(path):
    """What a change in a worktree rewrites: the folder itself (a file added or removed at
    its top), and its HEAD and index (a commit, a checkout, a change staged or dropped)."""
    admin = admin_folder(path)
    return stamps([path] + ([] if admin is None else [admin / "HEAD", admin / "index"]))


def listed_worktrees(mac, repository):
    """The folders git lists as worktrees of the repository, each with its lock: None when it
    is not locked, else the lock's reason ("" for none). None when git cannot tell."""
    answer = mac.git(repository, "worktree", "list", "--porcelain")
    if answer.returncode != 0:
        return None
    found = {}
    folder = None
    for line in answer.stdout.splitlines():
        if line.startswith("worktree "):
            folder = os.path.realpath(line[len("worktree ") :])
            found[folder] = None
        elif folder is not None and (line == "locked" or line.startswith("locked ")):
            found[folder] = line[len("locked ") :]
    return found


def lock_holders(lock, pids):
    """What keeps a worktree locked, of the pids that run: None when nothing does (it is not
    locked, or Claude Code locked it and no process its reason names runs); otherwise the
    pids that hold it, [] for a lock that is not Claude Code's."""
    if lock is None:
        return None
    if not lock.startswith(CLAUDE_LOCK):
        return []
    holders = sorted({int(pid) for pid in LOCK_PID.findall(lock)} & pids)
    return holders or None


def tidy_branch(project, name, branch, mac):
    """Delete the branch of an ended session whose worktree `name` was just removed, when it
    is that session's own, no worktree has it checked out and all its commits are on the
    base branch; `git branch -d` only. Otherwise leave it and say why; a git error says
    nothing. `branch` is the one the worktree had checked out."""
    if not branch or branch != worktrees.branch_of(name):
        return  # not one porchlight can tell is that session's
    repository = names.repository(project)
    base = ready_sessions.base_branch(project, mac)
    holders = worktrees.checked_out(mac.git, repository) if base is not None else None
    if holders is None:
        return
    which = "the branch %s of the ended server session %s" % (branch, name[len(worktrees.SERVER_PREFIX) :])
    if branch in holders:
        mac.log(project, "kept %s: the worktree %s has it checked out" % (which, holders[branch]))
        return
    on_base = worktrees.is_on(mac.git, repository, branch, base)
    if on_base is False:
        mac.log(project, "kept %s: it has commits that are not on %s" % (which, base))
    if not on_base:
        return
    deleted = worktrees.delete_merged_branch(mac.git, repository, branch)
    if deleted.returncode != 0:
        why = (deleted.stderr.strip().splitlines() or [""])[0]  # git's first line; the hints after it name -D
        mac.log(project, "could not delete %s: %s" % (which, why[:300]))
    else:
        mac.log(project, "deleted %s: its commits are on %s" % (which, base))


def tidy_worktrees(project, mac):
    """Remove the worktrees of the server's sessions that ended, when nothing in them would
    be lost; leave the others, saying why once. A project without `server` is not looked at."""
    if not project.has("server"):
        return
    repository = names.repository(project)
    found = bridge_folders(repository)
    store = mac.store(project, WORKTREES)
    if not found and not store.path.exists():
        return
    ps_text = mac.processes() if found else ""
    running = live_view.server_processes(ps_text)
    ended = [path for name, path in found.items() if name[len(worktrees.SERVER_PREFIX) :] not in running]
    if not store.path.exists() and not any(quiet(path, mac) for path in ended):
        return  # nothing to check yet: nothing is kept
    pids = {pid for pid, _, _ in processes.rows(ps_text)}
    with store.locked():
        state = store.load({})
        new = {name: state[name] for name in state if name in found}
        branches = branches_look(repository) if found else []
        due = []
        for name, path in sorted(found.items()):
            seen = new.get(name) or {}
            if name[len(worktrees.SERVER_PREFIX) :] in running:
                new.pop(name, None)  # checked again once it ends; what was said of it stays
                if seen.get("said"):
                    new[name] = {"said": seen["said"]}
            elif quiet(path, mac) and (
                seen.get("looks") != worktree_look(path) + branches
                or (seen.get("waits_for") and not set(seen["waits_for"]) & pids)  # its lock's process ended
            ):
                due.append((name, path))
        listed = listed_worktrees(mac, repository) if due else None
        for name, path in due if listed is not None else ():  # git could not tell: the next pass asks again
            real = os.path.realpath(path)
            said = None  # why it is left
            waits_for = lock_holders(listed.get(real), pids)  # the processes whose lock holds it
            if real not in listed or real == str(repository):
                said = "left %s: git does not list it as a worktree" % name
                outcome = "not listed"
            elif waits_for is not None:
                said = "left %s: it is locked" % name + (" (%s)" % listed[real] if listed[real] else "")
                outcome = "locked"
            else:
                lines = []
                tidied = ready_sessions.tidy_worktree(project, path, mac, log=lines.append)
                outcome = "gone" if tidied is None else tidied[0]
                if outcome == "removed":
                    for line in lines:
                        mac.log(project, line)
                    tidy_branch(project, name, tidied[1], mac)
                elif lines:
                    said = lines[-1]
            if path.is_dir():
                if said is not None and said != (new.get(name) or {}).get("said"):
                    mac.log(project, said)  # a reason already logged is not said again
                new[name] = {"outcome": outcome, "looks": worktree_look(path) + branches_look(repository), "said": said}
                if waits_for:
                    new[name]["waits_for"] = waits_for
            else:
                new.pop(name, None)
        if new != state:
            store.save(new)
