"""Git worktrees: where a repository keeps them, and adding, locking and removing one."""

import subprocess
from pathlib import Path

FOLDER = (".claude", "worktrees")  # where Claude Code keeps a repository's worktrees
SERVER_PREFIX = "bridge-"  # the Remote Control server names a session's worktree bridge-<session>


class Git:
    """Runs git in a folder. `tool` is where git is; `run` stands in for subprocess.run."""

    def __init__(self, tool, run=subprocess.run):
        self.tool = tool
        self.run = run

    def __call__(self, directory, *arguments):
        return self.run(
            [self.tool, "-C", str(directory)] + list(arguments), capture_output=True, text=True, timeout=180
        )


def folder(repository):
    return Path(repository).joinpath(*FOLDER)


def of_server_session(repository, session):
    return folder(repository) / (SERVER_PREFIX + session)


def is_repository(git, directory):
    """Whether a folder is a checkout of a git repository."""
    answer = git(directory, "rev-parse", "--is-inside-work-tree")
    return answer.returncode == 0 and answer.stdout.strip() == "true"


def top_level(git, directory):
    """The top folder of the repository a folder is in, as git names it; None when the
    folder is in none."""
    answer = git(directory, "rev-parse", "--show-toplevel")
    found = answer.stdout.strip() if answer.returncode == 0 else ""
    return Path(found) if found else None


def default_base(git, repository):
    """The default branch of the repository's origin, as git recorded it; None when it did not."""
    answer = git(repository, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    name = answer.stdout.strip()
    return name if answer.returncode == 0 and name else None


def has_remote(git, repository, name):
    return git(repository, "remote", "get-url", name).returncode == 0


def branch_exists(git, repository, branch):
    return git(repository, "rev-parse", "--verify", "--quiet", "refs/heads/" + branch).returncode == 0


def add(git, repository, path, reason, commit, *options):
    """Add a locked worktree on a commit or a branch; `options` such as "-b", name or "--detach"."""
    return git(repository, "worktree", "add", "--lock", "--reason", reason, *options, str(path), commit)


def lock(git, repository, path, reason):
    return git(repository, "worktree", "lock", "--reason", reason, str(path))


def unlock(git, repository, path):
    return git(repository, "worktree", "unlock", str(path))


def remove(git, repository, path):
    return git(repository, "worktree", "remove", str(path))


def delete_branch(git, repository, branch):
    return git(repository, "branch", "-D", branch)


def current_branch(git, path):
    return git(path, "branch", "--show-current").stdout.strip()


def is_clean(git, path):
    status = git(path, "status", "--porcelain")
    return status.returncode == 0 and not status.stdout.strip()


def is_merged(git, path, base):
    """Whether everything committed in a worktree is already on a branch."""
    return git(path, "merge-base", "--is-ancestor", "HEAD", base).returncode == 0
