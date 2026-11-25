"""Files a repository lists in .worktreeinclude, copied into a new worktree of it.

Claude Code does this for the worktrees it creates: `.worktreeinclude`, at the top of the
repository, holds patterns in `.gitignore` syntax. A file is copied when git ignores it and
a pattern matches it; tracked files are in the worktree already. Git decides both. Symbolic
links are skipped, nothing is copied from another worktree in `.claude/worktrees/`, a file
the worktree already has is left alone, and nothing is written outside the worktree.

    copy(git, repository, worktree)   Copied(files, failures), each path relative
"""

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

FILE = ".worktreeinclude"
WORKTREES = ".claude/worktrees/"  # where the worktrees of a repository live, never copied


@dataclass
class Copied:
    files: list = field(default_factory=list)  # the paths copied
    failures: list = field(default_factory=list)  # (path, why) of each one not copied; "" for the listing


def ignored(git, repository, *exclude):
    """The untracked files git ignores with these exclude options, as relative paths."""
    answer = git(repository, "ls-files", "-z", "--others", "--ignored", *exclude)
    if answer.returncode != 0:
        raise OSError(answer.stderr.strip()[:300] or "git ls-files failed")
    return {path for path in answer.stdout.split("\0") if path}


def listed(git, repository):
    """The files to copy: ignored by git and matched by .worktreeinclude, in order."""
    repository = Path(repository)
    patterns = ignored(git, repository, "--exclude-from=" + str(repository / FILE))
    paths = ignored(git, repository, "--exclude-standard") & patterns
    # Another worktree shows as one folder entry; a leftover folder there shows its files.
    return sorted(path for path in paths if not path.startswith(WORKTREES))


def inside(path, root):
    return path == root or path.startswith(root + os.sep)


def place(source, target, root):
    """Copy one file; True when copied, False when the worktree has it already."""
    if os.path.islink(source) or not os.path.isfile(source):
        return False
    # The deepest folder that exists already must lie in the worktree, or making the rest
    # would follow a link out of it.
    existing = os.path.dirname(target)
    while not os.path.lexists(existing):
        existing = os.path.dirname(existing)
    if not inside(os.path.realpath(existing), root):
        raise OSError("it would be written outside the worktree")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not inside(os.path.realpath(os.path.dirname(target)), root):
        raise OSError("it would be written outside the worktree")
    if os.path.lexists(target):
        return False
    # Made new, closed to others while it is written (these files are often secrets), then
    # given the original's mode; a file that appeared meanwhile is left alone.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with open(source, "rb") as read:  # unreadable: nothing is made
        mode = stat.S_IMODE(os.fstat(read.fileno()).st_mode)
        try:
            descriptor = os.open(target, flags, 0o600)
        except FileExistsError:
            return False
        try:
            with os.fdopen(descriptor, "wb") as written:
                shutil.copyfileobj(read, written)
                os.fchmod(written.fileno(), mode)
        except BaseException:
            os.unlink(target)  # no half-written copy is left
            raise
    return True


def copy(git, repository, worktree):
    """Copy what .worktreeinclude lists into a new worktree. Never raises for a file."""
    copied = Copied()
    repository = os.path.realpath(repository)
    if not os.path.isfile(os.path.join(repository, FILE)):
        return copied
    try:
        paths = listed(git, repository)
    except (OSError, subprocess.SubprocessError) as error:
        copied.failures.append(("", str(error)))
        return copied
    root = os.path.realpath(worktree)
    for path in paths:
        source = os.path.join(repository, path)
        try:
            if not inside(os.path.realpath(os.path.dirname(source)), repository):
                continue  # read through a link that leaves the repository
            if place(source, os.path.join(root, path), root):
                copied.files.append(path)
        except OSError as error:
            copied.failures.append((path, error.strerror or str(error)))
    return copied
