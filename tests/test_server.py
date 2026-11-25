"""Tests of starting the Remote Control server of a project and of one pass over a
project (`test_passes` has the pass over a whole configuration). Nothing is started: the
program that would replace this one is a stand-in."""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from porchlight import names, passes, session_settings
from porchlight.features import server
from tests import standins


class Server(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        (root / "shop").mkdir()
        self.project = standins.project("shop", str(root / "shop"), mode="plan")
        self.mac = standins.StandInMac(root)
        self.mac.environ["PATH"] = "/custom/bin"
        self.done = []

    def tearDown(self):
        self.scratch.cleanup()

    def run_server(self, **options):
        server.run(
            self.project,
            self.mac,
            execute=lambda program, words, environment: self.done.append(("exec", program, words, environment)),
            chdir=lambda folder: self.done.append(("cd", str(folder))),
            **options,
        )

    def test_the_server_gives_each_session_a_worktree_with_the_projects_mode(self):
        self.assertEqual(
            server.command(self.project, "/tools/claude", "/state/settings.json"),
            [
                "/tools/claude", "remote-control", "--spawn", "worktree", "--permission-mode", "plan",
                "--settings", "/state/settings.json", "--no-create-session-in-dir",
            ],
        )  # fmt: skip

    def test_starts_in_the_projects_folder_and_becomes_the_server(self):
        self.run_server()

        settings = self.mac.settings(self.project)
        self.assertEqual([step[0] for step in self.done], ["cd", "exec"])
        self.assertEqual(self.done[0][1], str(names.repository(self.project)))
        self.assertEqual(self.done[1][1:3], ("/tools/claude", server.command(self.project, "/tools/claude", settings)))
        self.assertEqual(json.loads(settings.read_text())["permissions"]["defaultMode"], "plan")

    def test_its_sessions_find_homebrew_whatever_started_it(self):
        self.run_server()

        folders = self.done[-1][3]["PATH"].split(":")
        self.assertEqual(folders[:2], ["/opt/homebrew/bin", "/usr/local/bin"])
        self.assertIn("/usr/bin", folders)
        self.assertEqual(folders[-1], "/custom/bin")

    def test_starts_nothing_beside_the_server_whatever_the_projects_features(self):
        self.assertTrue(self.project.has("keep-awake"), "keeping the Mac awake is the service's, not the server's")

        self.run_server()

        self.assertEqual([step[0] for step in self.done], ["cd", "exec"])
        self.assertEqual(self.mac.spawned, [])

    def test_what_replaces_this_process_is_looked_for_when_the_server_starts(self):
        with mock.patch.object(server.os, "execve") as execve, mock.patch.object(server.os, "chdir") as chdir:
            server.run(self.project, self.mac)

        chdir.assert_called_once_with(names.repository(self.project))
        self.assertEqual(execve.call_args.args[0], "/tools/claude")

    def test_installs_the_settings_that_waited_for_a_restart(self):
        settings = self.mac.settings(self.project)
        session_settings.stage(standins.project("shop", self.project.path, mode="acceptEdits"), settings)

        self.run_server()

        self.assertEqual(json.loads(settings.read_text())["permissions"]["defaultMode"], "plan")
        self.assertFalse(session_settings.waiting(settings).exists())


class Pass(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.project = standins.project("shop", self.scratch.name)
        self.mac = standins.StandInMac(self.scratch.name)
        self.ran = []

    def tearDown(self):
        self.scratch.cleanup()

    def step(self, name, error=None):
        def run(project, mac):
            self.ran.append((name, project.name))
            if error:
                raise error

        return (name, run)

    def test_one_part_that_fails_is_logged_and_does_not_stop_the_others(self):
        steps = (self.step("first"), self.step("second", RuntimeError("broken")), self.step("third"))

        passes.run_project(self.project, self.mac, steps)

        self.assertEqual(self.ran, [("first", "shop"), ("second", "shop"), ("third", "shop")])
        self.assertIn("second failed: RuntimeError('broken')", self.mac.log_text(self.project))

    def test_a_pass_keeps_the_tabs_then_the_ready_sessions_then_the_copies_then_the_servers_worktrees(self):
        self.assertEqual([name for name, _ in passes.STEPS], ["view tabs", "ready sessions", "resume list", "server worktrees"])

    def test_the_status_of_a_project_names_both_kinds_of_session(self):
        printed = []

        passes.project_status(self.project, self.mac, out=printed.append)

        self.assertEqual(
            printed,
            [
                "Ready sessions, with Claude Code's interface:",
                "  No session with Claude Code's interface yet.",
                "Sessions the server started, with a read-only view:",
                "  No session the server started is running.",
            ],
        )

    def test_the_status_of_a_project_without_the_server_names_its_ready_sessions_only(self):
        project = standins.project("shop", self.project.path, features=("ready-session",))
        printed = []

        passes.project_status(project, self.mac, out=printed.append)

        self.assertEqual(
            printed, ["Ready sessions, with Claude Code's interface:", "  No session with Claude Code's interface yet."]
        )


CLAUDE = "/usr/local/Caskroom/claude-code/2.1.325/claude"
ENDED = "cse_01AAA"
RUNNING = "cse_01BBB"


def server_child(pid, session):
    """A session the server runs, as the process list shows it."""
    return (
        f"{pid} {CLAUDE} --print --sdk-url wss://example.invalid/x --session-id {session} "
        "--input-format stream-json --output-format stream-json\n"
    )


class BridgeWorktrees(unittest.TestCase):
    """The worktrees the server leaves behind, `.claude/worktrees/bridge-cse_...`, tidied by
    a pass once their session no longer runs, by the rule of a ready session's worktree."""

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        (root / "shop").mkdir()
        self.project = standins.project("shop", str(root / "shop"), features=("server",))
        self.repository = names.repository(self.project)
        self.mac = standins.StandInMac(root)
        self.mac.now = time.time() + 3600  # the folders below were made an hour ago
        self.listed = None  # the folders git lists as worktrees; None: every bridge folder
        self.status = ""  # what `git status --porcelain` prints in a worktree
        self.on_base = True
        self.locks = {}  # folder: the reason of its lock, as `git worktree lock --reason` took it
        self.current = {}  # worktree name: the branch it is on; else worktree-<name>, as Claude Code names it
        self.branch_on_base = 0  # what `git merge-base --is-ancestor <branch> <base>` returns
        self.checkouts = {}  # other worktrees: folder: the branch it has checked out
        self.deleted = 0  # what `git branch -d` returns
        self.mac.git_runner.answers = self.git

    def tearDown(self):
        self.scratch.cleanup()

    def bridge(self, session=ENDED, name=None):
        path = self.repository / ".claude" / "worktrees" / (name or "bridge-" + session)
        path.mkdir(parents=True)
        return path

    def git(self, words):
        asked = words[3:]
        if asked[:2] == ["worktree", "list"]:
            if self.listed is None:
                folders = sorted((self.repository / ".claude" / "worktrees").glob("bridge-*"))
            else:
                folders = self.listed
            blocks = ["worktree %s\nHEAD 1234\nbranch refs/heads/main\n" % self.repository]
            for f in folders:
                block = "worktree %s\nHEAD 1234\nbranch refs/heads/worktree-%s\n" % (f, f.name)
                if f in self.locks:
                    block += ("locked %s" % self.locks[f]).rstrip() + "\n"
                blocks.append(block)
            for f, branch in self.checkouts.items():
                blocks.append("worktree %s\nHEAD 1234\nbranch refs/heads/%s\n" % (f, branch))
            return standins.result(stdout="\n".join(blocks) + "\n")
        if asked[:1] == ["symbolic-ref"]:
            return standins.result(stdout="origin/main\n")
        if asked[:1] == ["status"]:
            return standins.result(stdout=self.status)
        if asked[:1] == ["merge-base"] and asked[2] != "HEAD":
            return standins.result(self.branch_on_base)
        if asked[:1] == ["merge-base"]:
            return standins.result(0 if self.on_base else 1)
        if asked[:2] == ["branch", "--show-current"]:
            name = Path(words[2]).name
            return standins.result(stdout="%s\n" % self.current.get(name, "worktree-" + name))
        if asked[:2] == ["branch", "-d"]:
            stderr = "error: the branch '%s' is not fully merged\nhint: If you are sure...\n" % asked[2]
            stderr = stderr if self.deleted else ""
            return standins.result(self.deleted, stderr=stderr)
        if asked[:2] == ["worktree", "remove"]:
            shutil.rmtree(asked[2])
        return None

    def asked(self, *words):
        return self.mac.git_runner.having(*words)

    def tidy(self, times=1):
        for _ in range(times):
            passes.run_project(self.project, self.mac)

    def new_branch(self, name):
        """A branch made in the repository, as `git branch <name> main` writes it."""
        heads = self.repository / ".git" / "refs" / "heads"
        heads.mkdir(parents=True, exist_ok=True)
        (heads / name).write_text("1234\n")
        later = heads.stat().st_mtime + 5
        os.utime(heads, (later, later))  # however fast the test runs, the folder changed

    def something_else_is_logged(self):
        """Another line in the project's log: the log itself skips only a repeat of its last line."""
        self.mac.log(self.project, "opened the tab of aaaaaaaa (Fix)")

    def log_count(self, line):
        return self.mac.log_text(self.project).count(line)

    def test_an_ended_clean_worktree_on_the_base_is_removed(self):
        worktree = self.bridge()

        self.tidy()

        self.assertFalse(worktree.exists())
        self.assertEqual([call[-1] for call in self.asked("worktree", "remove")], [str(worktree)])
        self.assertEqual(self.asked("merge-base")[0][-3:], ["--is-ancestor", "HEAD", "origin/main"])
        self.assertEqual(self.asked("branch", "-D"), [], "a branch porchlight did not make is never deleted")
        self.assertIn("removed the worktree bridge-%s" % ENDED, self.mac.log_text(self.project))
        self.assertEqual(self.mac.store(self.project, server.WORKTREES).load({}), {})

    def test_an_ended_worktree_that_would_lose_something_is_unlocked_left_and_logged_once(self):
        cases = (
            (" M page.html\n", True, "it has changes"),
            ("?? notes.txt\n", True, "it has changes"),
            ("", False, "its commits are not on origin/main"),
        )
        for status, on_base, why in cases:
            with self.subTest(why=why, status=status):
                self.tearDown()  # each case in a repository of its own
                self.setUp()
                worktree = self.bridge()
                self.status, self.on_base = status, on_base

                self.tidy(times=3)

                self.assertTrue(worktree.is_dir())
                self.assertEqual(self.asked("worktree", "remove"), [])
                self.assertEqual([call[-1] for call in self.asked("worktree", "unlock")], [str(worktree)])
                line = "kept the worktree bridge-%s (%s)" % (ENDED, why)
                self.assertEqual(self.mac.log_text(self.project).count(line), 1)
                self.assertEqual(len(self.asked("status")), 1, "checked once, not at every pass")

    def test_a_worktree_whose_session_runs_is_untouched(self):
        worktree = self.bridge(RUNNING)
        self.mac.ps = server_child(101, RUNNING)

        self.tidy()

        self.assertTrue(worktree.is_dir())
        self.assertEqual(self.mac.git_runner.calls, [])

    def test_a_worktree_just_made_is_untouched_while_its_session_starts(self):
        worktree = self.bridge()
        self.mac.now = time.time()

        self.tidy()

        self.assertTrue(worktree.is_dir())
        self.assertEqual(self.mac.git_runner.calls, [])

    def test_a_folder_git_does_not_list_as_a_worktree_is_untouched_and_logged_once(self):
        worktree = self.bridge()
        self.listed = []

        self.tidy(times=3)

        self.assertTrue(worktree.is_dir())
        self.assertEqual(len(self.asked("worktree", "list")), 1)
        self.assertEqual(len(self.mac.git_runner.calls), 1, "nothing but the list is asked")
        line = "left bridge-%s: git does not list it as a worktree" % ENDED
        self.assertEqual(self.mac.log_text(self.project).count(line), 1)

    def test_folders_of_other_names_and_the_main_checkout_are_untouched(self):
        others = [self.bridge(name=name) for name in ("feature-x", "bridge-other", "porchlight-shop-aaaaaaaa")]
        link = self.repository / ".claude" / "worktrees" / ("bridge-" + ENDED)
        link.symlink_to(self.repository)  # a link to the main checkout under a session's name

        self.tidy()

        self.assertTrue(all(folder.is_dir() for folder in others))
        self.assertTrue(link.is_symlink() and self.repository.is_dir())
        self.assertEqual(self.mac.git_runner.calls, [])

    def test_a_git_error_leaves_everything_and_the_next_pass_tries_again(self):
        worktree = self.bridge()
        self.mac.git_runner.answers = lambda words: standins.result(128, stderr="fatal: not a git repository")

        self.tidy(times=2)

        self.assertTrue(worktree.is_dir())
        self.assertEqual(len(self.asked("worktree", "list")), 2)
        self.assertEqual(self.asked("status"), [])
        self.assertEqual(self.asked("worktree", "remove"), [])

    def test_a_project_without_the_server_is_untouched(self):
        worktree = self.bridge()
        self.project = standins.project("shop", self.project.path, features=("keep-awake",))

        self.tidy()

        self.assertTrue(worktree.is_dir())
        self.assertEqual(self.mac.git_runner.calls, [])
        self.assertFalse(self.mac.store(self.project, server.WORKTREES).path.exists())

    def test_a_kept_worktree_is_checked_again_once_something_in_it_changed(self):
        worktree = self.bridge()
        self.status = "?? notes.txt\n"
        self.tidy(times=2)
        (worktree / "notes.txt").write_text("done\n")  # the user tidies it by hand: the folder changes
        self.status = ""

        self.tidy()

        self.assertFalse(worktree.exists())
        self.assertEqual(len(self.asked("status")), 2)
        self.assertEqual(self.mac.store(self.project, server.WORKTREES).load(None), {}, "nothing is kept of it")

    def test_a_session_that_runs_again_is_checked_again_once_it_ends(self):
        worktree = self.bridge()
        self.status = "?? notes.txt\n"
        self.tidy()
        self.mac.ps = server_child(101, ENDED)
        self.tidy()
        self.mac.ps = ""
        self.status = ""

        self.tidy()

        self.assertFalse(worktree.exists())
        self.assertEqual(len(self.asked("status")), 2)

    def test_a_new_branch_checks_a_kept_worktree_again_without_saying_why_again(self):
        worktree = self.bridge()
        self.status = "?? notes.txt\n"
        self.new_branch("main")
        self.tidy(times=2)
        self.something_else_is_logged()

        self.new_branch("unrelated-branch")
        self.tidy()

        self.assertTrue(worktree.is_dir())
        self.assertEqual(len(self.asked("status")), 2, "checked again: its commits may have reached the base")
        self.assertEqual(self.log_count("kept the worktree bridge-%s (it has changes)" % ENDED), 1)
        self.assertEqual(self.log_count("bridge-%s" % ENDED), 1, "nothing else is said of it")
        kept = self.mac.store(self.project, server.WORKTREES).load({})
        self.assertEqual(kept["bridge-" + ENDED]["said"], "kept the worktree bridge-%s (it has changes)" % ENDED)

    def test_a_new_reason_to_keep_a_worktree_is_said(self):
        worktree = self.bridge()
        self.status = "?? notes.txt\n"
        self.tidy()
        self.status, self.on_base = "", False
        (worktree / "x").write_text("")  # something in it changed
        (worktree / "x").unlink()
        later = worktree.stat().st_mtime + 5
        os.utime(worktree, (later, later))

        self.tidy(times=2)

        self.assertEqual(self.log_count("kept the worktree bridge-%s (it has changes)" % ENDED), 1)
        self.assertEqual(self.log_count("kept the worktree bridge-%s (its commits are not on origin/main)" % ENDED), 1)

    def test_a_new_branch_does_not_say_again_that_git_does_not_list_a_folder(self):
        worktree = self.bridge()
        self.listed = []
        self.tidy()
        self.something_else_is_logged()

        self.new_branch("unrelated-branch")
        self.tidy()

        self.assertTrue(worktree.is_dir())
        self.assertEqual(len(self.asked("worktree", "list")), 2)
        self.assertEqual(self.log_count("left bridge-%s: git does not list it as a worktree" % ENDED), 1)

    def test_a_worktree_locked_by_anything_but_claude_code_is_left_locked_and_logged_once(self):
        for reason, said in (
            ("someone keeps it", " (someone keeps it)"),
            ("porchlight shop session aaaaaaaa", " (porchlight shop session aaaaaaaa)"),
            ("claudette (pid 1)", " (claudette (pid 1))"),
            ("", ""),
        ):
            with self.subTest(reason=reason):
                self.tearDown()
                self.setUp()
                worktree = self.bridge()
                self.locks[worktree] = reason

                self.tidy(times=2)
                self.something_else_is_logged()
                self.new_branch("unrelated-branch")
                self.tidy()

                self.assertTrue(worktree.is_dir())
                self.assertEqual(self.asked("worktree", "unlock"), [], "never unlocked")
                self.assertEqual(self.asked("worktree", "remove"), [])
                self.assertEqual(self.asked("status"), [], "nothing is asked of a worktree someone holds")
                self.assertEqual(self.log_count("left bridge-%s: it is locked%s\n" % (ENDED, said)), 1)
                self.assertEqual(self.log_count("bridge-%s" % ENDED), 1)

    def test_a_clean_worktree_on_the_base_locked_by_a_claude_code_process_that_ended_is_removed(self):
        worktree = self.bridge()
        self.locks[worktree] = "claude agent agent-a1b2c3 (pid 4242 start Wed Nov 25 10:00:00 2026)"
        self.mac.ps = "4243 /usr/bin/other\n"

        self.tidy()

        self.assertFalse(worktree.exists())
        self.assertEqual([call[-1] for call in self.asked("worktree", "unlock")], [str(worktree)])
        self.assertEqual([call[-1] for call in self.asked("worktree", "remove")], [str(worktree)])
        self.assertIn("removed the worktree bridge-%s" % ENDED, self.mac.log_text(self.project))

    def test_a_worktree_locked_by_a_claude_code_process_that_runs_is_left_until_it_ends(self):
        worktree = self.bridge()
        reason = "claude agent agent-a1b2c3 (pid 4242 start Wed Nov 25 10:00:00 2026)"
        self.locks[worktree] = reason
        self.mac.ps = "4242 /usr/local/bin/claude --agent\n"

        self.something_else_is_logged()
        self.new_branch("unrelated-branch")
        self.tidy()

        self.assertTrue(worktree.is_dir())
        self.assertEqual(self.asked("worktree", "unlock"), [])
        self.assertEqual(self.asked("worktree", "remove"), [])
        self.assertEqual(self.log_count("left bridge-%s: it is locked (%s)\n" % (ENDED, reason)), 1)

        self.mac.ps = ""  # the process that held it ended, nothing else changed
        self.tidy()

        self.assertFalse(worktree.exists())
        self.assertEqual([call[-1] for call in self.asked("worktree", "unlock")], [str(worktree)])

    BRANCH = "worktree-bridge-" + ENDED  # the branch the server's session made, as Claude Code names it

    def branch_lines(self):
        """The log's lines about a branch, without their time."""
        lines = self.mac.log_text(self.project).splitlines()
        return [line.split(" ", 2)[2] for line in lines if "branch" in line]

    def test_once_its_worktree_is_removed_a_session_branch_whose_commits_are_on_the_base_is_deleted(self):
        worktree = self.bridge()

        self.tidy(times=3)

        self.assertFalse(worktree.exists())
        self.assertEqual(
            [call[1:] for call in self.asked("merge-base", "--is-ancestor", self.BRANCH)],
            [["-C", str(self.repository), "merge-base", "--is-ancestor", self.BRANCH, "origin/main"]],
        )
        self.assertEqual(
            [call[1:] for call in self.asked("branch", "-d")], [["-C", str(self.repository), "branch", "-d", self.BRANCH]]
        )
        self.assertEqual(self.asked("branch", "-D"), [], "never forced")
        removed = "removed the worktree bridge-%s" % ENDED
        deleted = "deleted the branch %s of the ended server session %s: its commits are on origin/main" % (
            self.BRANCH,
            ENDED,
        )
        log = self.mac.log_text(self.project)
        self.assertEqual(log.count(deleted), 1)
        self.assertLess(log.index(removed), log.index(deleted), "the worktree goes first")
        self.assertEqual(self.mac.store(self.project, server.WORKTREES).load({}), {})

    def test_a_session_branch_with_commits_of_its_own_is_kept_and_logged_once(self):
        worktree = self.bridge()
        self.branch_on_base = 1

        self.tidy(times=3)
        self.something_else_is_logged()
        self.new_branch("unrelated-branch")
        self.tidy()

        self.assertFalse(worktree.exists(), "the worktree is removed as before")
        self.assertEqual(self.asked("branch", "-d"), [])
        self.assertEqual(self.asked("branch", "-D"), [])
        line = "kept the branch %s of the ended server session %s: it has commits that are not on origin/main" % (
            self.BRANCH,
            ENDED,
        )
        self.assertEqual(self.log_count(line), 1)
        self.assertEqual(self.branch_lines(), [line])

    def test_a_session_branch_another_worktree_has_checked_out_is_kept(self):
        worktree = self.bridge()
        other = self.repository / ".claude" / "worktrees" / "by-hand"
        self.checkouts[other] = self.BRANCH

        self.tidy(times=3)

        self.assertFalse(worktree.exists())
        self.assertEqual(self.asked("branch", "-d"), [])
        self.assertEqual(self.asked("branch", "-D"), [])
        self.assertEqual(self.asked("merge-base", "--is-ancestor", self.BRANCH), [], "not asked of a branch in use")
        line = "kept the branch %s of the ended server session %s: the worktree %s has it checked out" % (
            self.BRANCH,
            ENDED,
            other,
        )
        self.assertEqual(self.log_count(line), 1)
        self.assertEqual(self.branch_lines(), [line])

    def test_a_branch_that_is_not_the_sessions_own_is_never_deleted(self):
        for branch in ("feature-x", "worktree-bridge-cse_01ZZZ", "worktree-bridge-" + ENDED + "-2", "main", ""):
            with self.subTest(branch=branch):
                self.tearDown()
                self.setUp()
                worktree = self.bridge()
                self.current["bridge-" + ENDED] = branch

                self.tidy(times=2)

                self.assertFalse(worktree.exists(), "the worktree is removed as before")
                self.assertEqual(self.asked("branch", "-d"), [])
                self.assertEqual(self.asked("branch", "-D"), [])
                self.assertEqual(self.asked("merge-base", "--is-ancestor", "HEAD"), self.asked("merge-base"))
                self.assertEqual(self.branch_lines(), [])

    def test_the_merged_branch_rule_leaves_a_ready_sessions_branch_to_the_shared_tidy(self):
        worktree = self.bridge()
        self.current["bridge-" + ENDED] = names.branch(self.project, "aaaaaaaa-1111-2222-3333-444444444444")

        self.tidy()

        self.assertFalse(worktree.exists())
        self.assertEqual(self.asked("branch", "-d"), [])
        self.assertEqual(self.asked("merge-base"), self.asked("merge-base", "--is-ancestor", "HEAD"))
        self.assertEqual(self.branch_lines(), [])

    def test_anything_unclear_about_a_session_branch_leaves_it_and_says_nothing(self):
        for case in ("the worktree list fails", "the ancestry check fails"):
            with self.subTest(case=case):
                self.tearDown()
                self.setUp()
                worktree = self.bridge()
                lists = []
                answer = self.git

                def git(words):
                    if words[3:5] == ["worktree", "list"]:
                        lists.append(words)
                        if case == "the worktree list fails" and len(lists) > 1:
                            return standins.result(128, stderr="fatal: oops\n")
                    return answer(words)

                self.mac.git_runner.answers = git
                if case == "the ancestry check fails":
                    self.branch_on_base = 128

                self.tidy(times=2)

                self.assertFalse(worktree.exists())
                self.assertEqual(self.asked("branch", "-d"), [])
                self.assertEqual(self.asked("branch", "-D"), [])
                self.assertEqual(self.branch_lines(), [])

    def test_a_session_branch_git_refuses_to_delete_is_kept_and_said_once(self):
        worktree = self.bridge()
        self.deleted = 1

        self.tidy(times=3)

        self.assertFalse(worktree.exists())
        self.assertEqual(len(self.asked("branch", "-d")), 1)
        self.assertEqual(self.asked("branch", "-D"), [], "never forced")
        line = "could not delete the branch %s of the ended server session %s: error: the branch '%s' is not fully merged" % (
            self.BRANCH,
            ENDED,
            self.BRANCH,
        )
        self.assertEqual(self.log_count(line), 1)
        self.assertEqual(self.branch_lines(), [line])
        self.assertNotIn("hint:", self.mac.log_text(self.project), "git's refusal is said in one line")

if __name__ == "__main__":
    unittest.main()
