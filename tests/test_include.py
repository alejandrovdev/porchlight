"""Tests of copying the files a repository's .worktreeinclude lists into a new worktree,
and of finding the copies removing it would lose, against a scratch repository and the
real git."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from porchlight.atoms import include, worktrees

GIT = shutil.which("git")
# Only the scratch repository's own configuration counts: no global ignore file of the Mac.
QUIET_GIT = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def run_git(directory, *arguments):
    subprocess.run(
        [GIT, "-C", str(directory), "-c", "user.name=Test", "-c", "user.email=test@example.com", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


@unittest.skipUnless(GIT, "git is not installed")
class Repository(unittest.TestCase):
    """A scratch repository with one worktree of it."""

    def setUp(self):
        environment = mock.patch.dict(os.environ, QUIET_GIT)
        environment.start()
        self.addCleanup(environment.stop)
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(os.path.realpath(self.scratch.name))
        self.repository = self.root / "shop"
        self.repository.mkdir()
        run_git(self.repository, "init", "-q", "-b", "main")
        self.write(".gitignore", ".env\nlocal/\n.claude/worktrees/\nlink.env\nout/\n")
        self.write("tracked.env", "committed\n")
        run_git(self.repository, "add", "-A")
        run_git(self.repository, "commit", "-q", "-m", "start")
        self.worktree = self.repository / ".claude" / "worktrees" / "shop-1"
        run_git(self.repository, "worktree", "add", "-q", "-b", "shop-1", str(self.worktree), "main")
        self.asked = []
        real = worktrees.Git(GIT)
        self.git = lambda directory, *arguments: self.asked.append(arguments) or real(directory, *arguments)

    def write(self, relative, text, root=None):
        path = (root or self.repository) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf8")
        return path

    def include(self, *patterns):
        self.write(include.FILE, "".join(pattern + "\n" for pattern in patterns))


class Copy(Repository):
    def test_without_a_worktreeinclude_nothing_is_copied_and_git_is_not_asked(self):
        self.write(".env", "secret\n")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied([], []))
        self.assertEqual(self.asked, [])
        self.assertFalse((self.worktree / ".env").exists())

    def test_a_listed_file_git_ignores_is_copied(self):
        self.write(".env", "secret\n")
        self.include(".env")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied([".env"], []))
        self.assertEqual((self.worktree / ".env").read_text(encoding="utf8"), "secret\n")

    def test_a_copy_is_closed_to_others_while_written_and_then_takes_the_original_mode(self):
        source = self.write(".env", "secret\n")
        source.chmod(0o640)
        self.include(".env")
        while_written = []
        real = shutil.copyfileobj

        def watching(read, written, *arguments):
            while_written.append(os.fstat(written.fileno()).st_mode & 0o777)
            return real(read, written, *arguments)

        with mock.patch.object(include.shutil, "copyfileobj", watching):
            copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied([".env"], []))
        self.assertEqual(while_written, [0o600], "nobody else can read it while it is written")
        self.assertEqual((self.worktree / ".env").stat().st_mode & 0o777, 0o640)
        self.assertEqual((self.worktree / ".env").read_text(encoding="utf8"), "secret\n")

    def test_a_copy_that_breaks_while_written_leaves_nothing_behind(self):
        self.write(".env", "secret\n")
        self.include(".env")

        with mock.patch.object(include.shutil, "copyfileobj", side_effect=OSError("disk full")):
            copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied.files, [])
        self.assertEqual([path for path, _ in copied.failures], [".env"])
        self.assertFalse((self.worktree / ".env").exists())

    def test_a_listed_file_git_does_not_ignore_is_not_copied(self):
        self.write("notes.env", "untracked, not ignored\n")
        self.include("notes.env")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied([], []))
        self.assertFalse((self.worktree / "notes.env").exists())

    def test_a_listed_tracked_file_is_not_copied(self):
        self.write("tracked.env", "changed in the main checkout\n")
        self.include("tracked.env", "*.env")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied([], []))
        self.assertEqual((self.worktree / "tracked.env").read_text(encoding="utf8"), "committed\n")

    def test_a_symbolic_link_is_skipped(self):
        self.write(".env", "secret\n")
        (self.repository / "link.env").symlink_to(".env")
        self.include(".env", "link.env")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied([".env"], []))
        self.assertFalse(os.path.lexists(self.worktree / "link.env"))

    def test_a_file_that_would_land_outside_the_worktree_is_refused(self):
        self.write("out/key", "secret\n")
        self.write("out/deep/key", "secret\n")
        outside = self.root / "outside"
        outside.mkdir()
        (self.worktree / "out").symlink_to(outside)  # the worktree's folder leads elsewhere
        self.include("out/")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied.files, [])
        self.assertEqual([path for path, _ in copied.failures], ["out/deep/key", "out/key"])
        self.assertTrue(all("outside the worktree" in why for _, why in copied.failures))
        self.assertEqual(list(outside.iterdir()), [], "not even a folder is made there")

    def test_nothing_under_the_worktrees_folder_is_copied(self):
        self.write(".env", "secret\n")
        self.write(".env", "another worktree's\n", root=self.worktree)
        self.write(".claude/worktrees/leftover/.env", "a leftover folder's\n")
        target = self.repository / ".claude" / "worktrees" / "shop-2"
        run_git(self.repository, "worktree", "add", "-q", "-b", "shop-2", str(target), "main")
        self.include(".env", ".claude/", ".claude/worktrees/")

        copied = include.copy(self.git, self.repository, target)

        self.assertEqual(copied, include.Copied([".env"], []))
        self.assertFalse((target / ".claude").exists())

    def test_a_folder_pattern_copies_the_ignored_files_in_it_making_its_folders(self):
        self.write("local/key", "k\n")
        self.write("local/deep/settings.json", "{}\n")
        self.include("local/")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied(["local/deep/settings.json", "local/key"], []))
        self.assertEqual((self.worktree / "local" / "key").read_text(encoding="utf8"), "k\n")
        self.assertEqual((self.worktree / "local" / "deep" / "settings.json").read_text(encoding="utf8"), "{}\n")

    def test_a_file_already_in_the_worktree_is_left_alone(self):
        self.write(".env", "the main checkout's\n")
        self.write(".env", "the worktree's own\n", root=self.worktree)
        self.include(".env")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied, include.Copied([], []))
        self.assertEqual((self.worktree / ".env").read_text(encoding="utf8"), "the worktree's own\n")

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_a_file_that_cannot_be_copied_is_reported_and_the_others_are_copied(self):
        unreadable = self.write("local/a", "a\n")
        self.write("local/b", "b\n")
        unreadable.chmod(0)
        self.addCleanup(unreadable.chmod, 0o644)
        self.include("local/")

        copied = include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(copied.files, ["local/b"])
        self.assertEqual([path for path, _ in copied.failures], ["local/a"])
        self.assertEqual((self.worktree / "local" / "b").read_text(encoding="utf8"), "b\n")

    def test_git_that_fails_is_reported(self):
        self.include(".env")
        failing = lambda directory, *arguments: subprocess.CompletedProcess(arguments, 128, "", "fatal: broken\n")

        copied = include.copy(failing, self.repository, self.worktree)

        self.assertEqual(copied.files, [])
        self.assertEqual(copied.failures, [("", "fatal: broken")])



class Unsaved(Repository):
    """The listed files of a worktree that the repository does not have as they are."""

    def test_copies_as_they_were_lose_nothing_and_without_a_worktreeinclude_git_is_not_asked(self):
        self.write(".env", "secret\n")
        self.assertEqual(include.unsaved(self.git, self.repository, self.worktree), [])
        self.assertEqual(self.asked, [])

        self.include(".env", "local/")
        self.write("local/a", "a\n")
        include.copy(self.git, self.repository, self.worktree)

        self.assertEqual(include.unsaved(self.git, self.repository, self.worktree), [])

    def test_a_changed_copy_and_a_listed_file_only_the_worktree_has_are_named_in_order(self):
        self.write(".env", "secret\n")
        self.include(".env", "local/")
        include.copy(self.git, self.repository, self.worktree)
        self.write(".env", "secret, changed\n", self.worktree)
        self.write("local/new", "made here\n", self.worktree)
        self.write("out/app.js", "built\n", self.worktree)  # ignored, but not listed

        self.assertEqual(include.unsaved(self.git, self.repository, self.worktree), [".env", "local/new"])

    def test_a_copy_whose_original_is_gone_is_named(self):
        self.write(".env", "secret\n")
        self.include(".env")
        include.copy(self.git, self.repository, self.worktree)
        (self.repository / ".env").unlink()

        self.assertEqual(include.unsaved(self.git, self.repository, self.worktree), [".env"])

    def test_a_link_counts_as_the_same_only_when_it_points_where_the_repositorys_does(self):
        self.include("link.env")
        os.symlink("/etc/hosts", self.repository / "link.env")
        os.symlink("/etc/hosts", self.worktree / "link.env")
        self.assertEqual(include.unsaved(self.git, self.repository, self.worktree), [])

        (self.worktree / "link.env").unlink()
        os.symlink("/etc/passwd", self.worktree / "link.env")
        self.assertEqual(include.unsaved(self.git, self.repository, self.worktree), ["link.env"])

    def test_git_that_fails_raises(self):
        self.include(".env")
        failing = lambda directory, *arguments: subprocess.CompletedProcess(arguments, 128, "", "fatal: broken\n")

        with self.assertRaisesRegex(OSError, "fatal: broken"):
            include.unsaved(failing, self.repository, self.worktree)


if __name__ == "__main__":
    unittest.main()
