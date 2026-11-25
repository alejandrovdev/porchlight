"""Tests of what the ready sessions do on the Mac, against stand-ins: git, tmux, the
terminal, the process list and the clock answer what each test tells them to."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from porchlight import config, names
from porchlight.atoms import tools, worktrees
from porchlight.features import ready_sessions
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
Z = "ffffffff-ffff-4fff-8fff-ffffffffffff"
ARCHIVED = {
    "type": "system",
    "content": ready_sessions.ARCHIVED + " (code 4090)",
    "timestamp": "2026-11-24T22:23:14.266Z",
}
ARCHIVED_AT = 1795558994.0


def answering(**replies):
    """Answers git by its command: status=..., merge_base=..., add=... (a worktree's)."""

    def answer(words):
        for word, reply in replies.items():
            if word.replace("_", "-") in words[3:5]:
                return reply(words) if callable(reply) else reply
        return None

    return answer


def subcommands(runner):
    """What git was asked, without the tool and the folder: "worktree add", "status"..."""
    return [" ".join(call[3:5] if call[3] == "worktree" else call[3:4]) for call in runner.calls]


class OnTheMac(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        (root / "shop").mkdir()
        self.project = standins.project("shop", str(root / "shop"), mode="plan", prefix="Shop")
        self.repository = names.repository(self.project)
        self.terminal = standins.Terminal()
        self.mac = standins.StandInMac(root, self.terminal)
        self.printed = []

    def tearDown(self):
        self.scratch.cleanup()

    def git(self, **replies):
        self.mac.git_runner.answers = answering(**replies)

    def having(self, *features):
        """The project with these features only."""
        return standins.project("shop", self.project.path, mode="plan", prefix="Shop", features=features)

    def another(self, name, prefix, mode="acceptEdits", features=None):
        (Path(self.scratch.name) / name).mkdir()
        return standins.project(name, str(Path(self.scratch.name) / name), mode=mode, prefix=prefix, features=features)

    def running_until_ended(self, ps_text):
        """A process list that loses each process once it was ended."""
        self.mac.ps = lambda: "".join(
            line + "\n" for line in ps_text.splitlines() if int(line.split()[0]) not in self.mac.terminated
        )

    def worktree(self, session=A, make=True, project=None):
        project = project or self.project
        path = names.repository(project) / ".claude" / "worktrees" / names.worktree(project, session)
        if make:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def record(self, state="used", session=A, project=None, **extra):
        record = {
            "state": state,
            "started": self.mac.now,
            "changed": self.mac.now,
            "worktree": str(self.worktree(session, make=False, project=project)),
            "branch": names.branch(project or self.project, session),
            "prompt": "",
            "title": "",
            "cse": "",
            "tidied": False,
            "shown": True,
            "tmux": "",
        }
        record.update(extra)
        return record

    def save(self, sessions, project=None, **extra):
        state = dict({"sessions": sessions, "read": {}, "failures": 0, "retry_after": 0}, **extra)
        self.mac.store(project or self.project, ready_sessions.STATE).save(state)

    def saved(self, project=None):
        return self.mac.store(project or self.project, ready_sessions.STATE).load({})

    def transcript(self, session, record, *entries):
        path = self.mac.transcripts / re.sub(r"[^A-Za-z0-9]", "-", record["worktree"]) / (session + ".jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf8")

    def claude_starts(self, pid=501):
        """Make tmux's new session show up in the process list, as Claude Code would."""

        def answer(words):
            if "new-session" in words:
                session = re.search(r"--session-id (\S+)", words[-1]).group(1)
                self.mac.ps += f"{pid} claude --session-id {session} --remote-control\n"

        self.mac.tmux_runner.answers = answer


class Note(unittest.TestCase):
    def test_says_in_english_how_to_reopen_and_names_the_command_it_is_given(self):
        note = ready_sessions.note("/tools/porchlight")

        self.assertIn("run this with Bash and report what it prints: /tools/porchlight reopen <name>.", note)
        self.assertIn("It opens the session in a new tab", note)
        self.assertNotIn(".sh", note)

    def test_the_command_is_the_one_the_tool_names_itself_by_whole(self):
        fallback = "/usr/bin/env 'PYTHONPATH=/its own/folder' /some/python3 -m porchlight"

        self.assertIn(fallback + " reopen <name>.", ready_sessions.note(fallback))

    def test_without_tabs_the_note_promises_no_tab(self):
        note = ready_sessions.note("/tools/porchlight", tabs=False)

        self.assertIn("/tools/porchlight reopen <name>.", note)
        self.assertNotIn("tab", note)
        self.assertIn("online in the app", note)

    def test_every_session_is_told_how(self):
        project = standins.project("blog", "/srv/blog", mode="acceptEdits", prefix="Blog")

        command = ready_sessions.command_line(
            project, A, False, "/tools/claude", "/state/settings.json", "/tools/porchlight"
        )

        self.assertIn("/tools/porchlight reopen <name>", command)
        self.assertIn(" --permission-mode acceptEdits ", command, "the mode is the project's")
        self.assertIn(" --remote-control-session-name-prefix Blog ", command, "the prefix is the project's")
        self.assertIn(" --settings /state/settings.json ", command)

    def test_without_reopen_the_note_says_nothing_of_reopening(self):
        note = ready_sessions.note()

        self.assertNotIn("reopen", note.lower())
        self.assertIn("driven from the Claude mobile app", note)

    def test_a_project_without_reopen_tells_its_sessions_nothing_of_it(self):
        project = standins.project("blog", "/srv/blog", features=("ready-session", "tabs"))

        command = ready_sessions.command_line(
            project, A, False, "/tools/claude", "/state/settings.json", "/tools/porchlight"
        )

        self.assertNotIn("reopen", command.lower())
        self.assertNotIn("/tools/porchlight", command)
        self.assertIn(" --append-system-prompt ", command, "it is still told where it runs")


class BaseBranch(OnTheMac):
    def test_a_new_worktree_starts_from_the_default_branch_git_states(self):
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        record = self.record("free")

        self.assertTrue(ready_sessions.add_worktree(self.project, record, A, self.mac))

        (added,) = self.mac.git_runner.having("worktree", "add")
        self.assertEqual(
            added[3:],
            ["worktree", "add", "--lock", "--reason", "porchlight shop session aaaaaaaa",
             "-b", "porchlight-shop-aaaaaaaa", record["worktree"], "origin/trunk"],
        )  # fmt: skip
        self.assertEqual(added[2], str(self.repository), "asked of the project's own repository")

    def test_the_base_the_project_states_wins_and_git_is_not_asked(self):
        project = standins.project("shop", self.project.path, base="upstream/develop")
        self.git(rev_parse=standins.result(returncode=1))

        ready_sessions.add_worktree(project, self.record("free"), A, self.mac)

        self.assertEqual(self.mac.git_runner.having("worktree", "add")[0][-1], "upstream/develop")
        self.assertEqual(self.mac.git_runner.having("symbolic-ref"), [])

    def test_without_a_base_no_worktree_is_made_and_the_log_says_why(self):
        self.git(symbolic_ref=standins.result(returncode=1), rev_parse=standins.result(returncode=1))

        self.assertFalse(ready_sessions.add_worktree(self.project, self.record("free"), A, self.mac))

        self.assertEqual(self.mac.git_runner.having("worktree", "add"), [])
        self.assertIn("base", self.mac.log_text(self.project))

    def test_without_an_origin_a_new_worktree_starts_from_the_branch_of_the_main_checkout(self):
        self.git(
            symbolic_ref=standins.result(returncode=1),
            remote=standins.result(returncode=2, stderr="error: No such remote 'origin'"),
            branch=standins.result(stdout="trunk\n"),
            rev_parse=standins.result(returncode=1),
        )
        record = self.record("free")

        self.assertTrue(ready_sessions.add_worktree(self.project, record, A, self.mac))

        (added,) = self.mac.git_runner.having("worktree", "add")
        self.assertEqual(added[-4:], ["-b", "porchlight-shop-aaaaaaaa", record["worktree"], "trunk"])
        (asked,) = self.mac.git_runner.having("branch", "--show-current")
        self.assertEqual(asked[2], str(self.repository), "the branch of the main checkout")

    def test_an_origin_that_states_no_default_branch_is_not_replaced_by_a_guess(self):
        # `remote get-url origin` succeeds: the repository has an origin.
        self.git(
            symbolic_ref=standins.result(returncode=1),
            branch=standins.result(stdout="trunk\n"),
            rev_parse=standins.result(returncode=1),
        )

        self.assertFalse(ready_sessions.add_worktree(self.project, self.record("free"), A, self.mac))

        self.assertEqual(len(self.mac.git_runner.having("remote", "get-url", "origin")), 1)
        self.assertEqual(self.mac.git_runner.having("worktree", "add"), [])
        self.assertIn("base", self.mac.log_text(self.project))

    def test_without_an_origin_and_on_no_branch_no_worktree_is_made(self):
        self.git(
            symbolic_ref=standins.result(returncode=1),
            remote=standins.result(returncode=2),
            branch=standins.result(stdout=""),  # the main checkout is on a commit, not on a branch
            rev_parse=standins.result(returncode=1),
        )

        self.assertFalse(ready_sessions.add_worktree(self.project, self.record("free"), A, self.mac))

        self.assertEqual(len(self.mac.git_runner.having("symbolic-ref")), 1)
        self.assertEqual(len(self.mac.git_runner.having("branch", "--show-current")), 1, "all three were tried")
        self.assertEqual(self.mac.git_runner.having("worktree", "add"), [])
        self.assertIn("base", self.mac.log_text(self.project))

    def test_a_branch_that_still_exists_is_checked_out_again(self):
        record = self.record("closed", branch="fix-header")

        self.assertTrue(ready_sessions.add_worktree(self.project, record, A, self.mac))

        (added,) = self.mac.git_runner.having("worktree", "add")
        self.assertEqual(added[-2:], [record["worktree"], "fix-header"])
        self.assertNotIn("-b", added)

    def test_a_branch_checked_out_elsewhere_is_opened_detached(self):
        attempts = []

        def add(words):
            attempts.append(words)
            return standins.result(returncode=0 if "--detach" in words else 128)

        self.git(add=add)

        self.assertTrue(ready_sessions.add_worktree(self.project, self.record("closed", branch="main"), A, self.mac))

        self.assertEqual(["--detach" in words for words in attempts], [False, True])

    def test_a_worktree_that_is_still_there_is_locked_again_and_kept(self):
        self.worktree()

        self.assertTrue(ready_sessions.add_worktree(self.project, self.record("closed"), A, self.mac))

        self.assertEqual(subcommands(self.mac.git_runner), ["worktree lock"])


class Tidy(OnTheMac):
    def test_removes_a_clean_worktree_whose_commits_are_on_the_base(self):
        self.worktree()
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), branch=standins.result(stdout="porchlight-shop-aaaaaaaa\n"))
        record = self.record("closed")

        ready_sessions.tidy(self.project, record, self.mac)

        self.assertEqual(self.mac.git_runner.having("merge-base")[0][-3:], ["--is-ancestor", "HEAD", "origin/trunk"])
        self.assertEqual(self.mac.git_runner.having("worktree", "remove")[0][-1], record["worktree"])
        self.assertEqual(self.mac.git_runner.having("branch", "-D")[0][-1], "porchlight-shop-aaaaaaaa")

    def test_a_worktree_with_uncommitted_work_is_unlocked_and_left(self):
        self.worktree()
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), status=standins.result(stdout=" M page.html\n"))

        ready_sessions.tidy(self.project, self.record("closed"), self.mac)

        self.assertEqual(len(self.mac.git_runner.having("worktree", "unlock")), 1)
        self.assertEqual(self.mac.git_runner.having("worktree", "remove"), [])
        self.assertEqual(self.mac.git_runner.having("branch", "-D"), [])
        self.assertIn("it has changes", self.mac.log_text(self.project))

    def test_a_worktree_with_unmerged_commits_is_unlocked_and_left(self):
        self.worktree()
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), merge_base=standins.result(returncode=1))

        ready_sessions.tidy(self.project, self.record("closed"), self.mac)

        self.assertEqual(len(self.mac.git_runner.having("worktree", "unlock")), 1)
        self.assertEqual(self.mac.git_runner.having("worktree", "remove"), [])
        self.assertIn("its commits are not on origin/trunk", self.mac.log_text(self.project))

    def test_a_worktree_is_left_when_the_base_is_unknown(self):
        self.worktree()
        self.git(symbolic_ref=standins.result(returncode=1))

        ready_sessions.tidy(self.project, self.record("closed"), self.mac)

        self.assertEqual(len(self.mac.git_runner.having("worktree", "unlock")), 1)
        self.assertEqual(self.mac.git_runner.having("worktree", "remove"), [])
        self.assertEqual(self.mac.git_runner.having("merge-base"), [], "nothing is compared with a guessed branch")

    def test_without_an_origin_a_finished_worktree_is_compared_with_the_main_checkouts_branch(self):
        self.worktree()
        self.git(
            symbolic_ref=standins.result(returncode=1),
            remote=standins.result(returncode=2),
            branch=lambda words: standins.result(
                stdout="trunk\n" if words[2] == str(self.repository) else "porchlight-shop-aaaaaaaa\n"
            ),
        )
        record = self.record("closed")

        ready_sessions.tidy(self.project, record, self.mac)

        self.assertEqual(self.mac.git_runner.having("merge-base")[0][-3:], ["--is-ancestor", "HEAD", "trunk"])
        self.assertEqual(self.mac.git_runner.having("worktree", "remove")[0][-1], record["worktree"])

    def test_never_deletes_a_branch_it_did_not_make(self):
        self.worktree()
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), branch=standins.result(stdout="fix-header\n"))
        record = self.record("closed")

        ready_sessions.tidy(self.project, record, self.mac)

        self.assertEqual(len(self.mac.git_runner.having("worktree", "remove")), 1)
        self.assertEqual(self.mac.git_runner.having("branch", "-D"), [])
        self.assertEqual(record["branch"], "fix-header", "remembered, to reopen the session on it")

    def test_does_nothing_when_the_worktree_is_gone(self):
        ready_sessions.tidy(self.project, self.record("closed"), self.mac)

        self.assertEqual(self.mac.git_runner.calls, [])


class Create(OnTheMac):
    def test_prepares_a_free_session_hidden_in_a_worktree_of_the_project(self):
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts()
        state = {"sessions": {}, "read": {}, "failures": 2, "retry_after": 0}

        ready_sessions.create(self.project, state, self.mac)

        ((session, record),) = state["sessions"].items()
        self.assertEqual(record["state"], "free")
        self.assertFalse(record["shown"])
        self.assertEqual(record["tmux"], "shop-" + session[:8])
        self.assertEqual(record["branch"], "porchlight-shop-" + session[:8])
        self.assertEqual(
            record["worktree"], str(self.repository / ".claude" / "worktrees" / ("porchlight-shop-" + session[:8]))
        )
        self.assertEqual(state["failures"], 0)
        (started,) = self.mac.tmux_runner.having("new-session")
        self.assertEqual(started[started.index("-c") + 1], record["worktree"])
        self.assertIn("--remote-control-session-name-prefix Shop", started[-1])
        self.assertEqual(self.terminal.tabs, [], "a free session waits without a tab")

    def test_without_a_worktreeinclude_git_is_asked_nothing_more_than_before(self):
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts()
        state = {"sessions": {}, "read": {}, "failures": 0, "retry_after": 0}

        ready_sessions.create(self.project, state, self.mac)

        self.assertEqual(len(state["sessions"]), 1)
        self.assertEqual(subcommands(self.mac.git_runner), ["rev-parse", "symbolic-ref", "worktree add"])
        self.assertNotIn("worktreeinclude", self.mac.log_text(self.project))

    def test_writes_the_settings_its_session_starts_with(self):
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts()

        ready_sessions.create(self.project, {"sessions": {}, "read": {}, "failures": 0, "retry_after": 0}, self.mac)

        settings = json.loads(self.mac.settings(self.project).read_text(encoding="utf8"))
        self.assertEqual(settings["permissions"]["defaultMode"], "plan")

    def test_a_session_that_did_not_start_is_cleaned_up_and_tried_later(self):
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.mac.tmux_runner.answers = lambda words: (
            standins.result(returncode=1, stderr="no server") if "new-session" in words else None
        )
        state = {"sessions": {}, "read": {}, "failures": 0, "retry_after": 0}

        ready_sessions.create(self.project, state, self.mac)

        self.assertEqual(state["sessions"], {})
        self.assertEqual(state["failures"], 1)
        self.assertEqual(state["retry_after"], self.mac.now + 120)
        self.assertEqual(len(self.mac.tmux_runner.having("kill-session")), 1)

        ready_sessions.create(self.project, state, self.mac)
        self.assertEqual(state["retry_after"], self.mac.now + 240, "each failure in a row waits twice as long")

    def test_a_missing_tool_leaves_nothing_behind(self):
        class NoTmux(standins.StandInMac):
            tmux = property(lambda self: (_ for _ in ()).throw(tools.ToolNotFound("tmux")))

            @tmux.setter
            def tmux(self, value):
                pass

        mac = NoTmux(self.scratch.name, self.terminal)

        with self.assertRaises(tools.ToolNotFound):
            ready_sessions.create(self.project, {"sessions": {}, "read": {}, "failures": 0, "retry_after": 0}, mac)

        self.assertEqual(mac.git_runner.calls, [], "no worktree is made for a session that cannot start")


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class WorktreeInclude(OnTheMac):
    """A new session's worktree gets the files .worktreeinclude lists, before it starts."""

    def setUp(self):
        super().setUp()
        environment = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        environment.start()
        self.addCleanup(environment.stop)
        self.project = standins.project("shop", self.project.path, mode="plan", base="main", prefix="Shop")
        self.repository = names.repository(self.project)
        self.real_git("init", "-q", "-b", "main")
        (self.repository / ".gitignore").write_text(".env\n.claude/worktrees/\n", encoding="utf8")
        self.real_git("add", "-A")
        self.real_git("commit", "-q", "-m", "start")
        self.mac.git = worktrees.Git(shutil.which("git"))
        self.seen_at_start = []

        def answer(words):
            if "new-session" in words:
                directory = Path(words[words.index("-c") + 1])
                self.seen_at_start.append((directory / ".env").exists())
                session = re.search(r"--session-id (\S+)", words[-1]).group(1)
                self.mac.ps += f"501 claude --session-id {session} --remote-control\n"

        self.mac.tmux_runner.answers = answer

    def real_git(self, *arguments):
        subprocess.run(
            [shutil.which("git"), "-C", str(self.repository), "-c", "user.name=Test", "-c", "user.email=t@example.com"]
            + list(arguments),
            check=True,
            capture_output=True,
        )

    def create(self):
        state = {"sessions": {}, "read": {}, "failures": 0, "retry_after": 0}
        ready_sessions.create(self.project, state, self.mac)
        return state

    def test_the_listed_files_are_copied_before_the_session_starts_and_the_log_says_so(self):
        (self.repository / ".env").write_text("secret\n", encoding="utf8")
        (self.repository / ".worktreeinclude").write_text(".env\n", encoding="utf8")

        state = self.create()

        ((session, record),) = state["sessions"].items()
        self.assertEqual((Path(record["worktree"]) / ".env").read_text(encoding="utf8"), "secret\n")
        self.assertEqual(self.seen_at_start, [True], "the file is there when the session starts")
        self.assertIn(
            "copied 1 file listed in .worktreeinclude into the worktree of %s" % names.short(session),
            self.mac.log_text(self.project),
        )

    @unittest.skipIf(os.geteuid() == 0, "root reads any file")
    def test_a_copy_that_fails_is_logged_and_the_session_still_starts(self):
        secret = self.repository / ".env"
        secret.write_text("secret\n", encoding="utf8")
        secret.chmod(0)  # the scratch folder's removal deletes it all the same
        (self.repository / ".worktreeinclude").write_text(".env\n", encoding="utf8")

        state = self.create()

        ((session, record),) = state["sessions"].items()
        self.assertEqual(record["state"], "free")
        self.assertEqual(self.seen_at_start, [False])
        self.assertEqual(state["failures"], 0)
        log = self.mac.log_text(self.project)
        self.assertIn(
            "could not copy 1 file listed in .worktreeinclude into the worktree of %s: .env:" % names.short(session),
            log,
        )
        self.assertIn("prepared the free session %s" % names.short(session), log)

    def test_a_worktree_made_again_on_its_own_branch_gets_the_listed_files_too(self):
        (self.repository / ".env").write_text("secret\n", encoding="utf8")
        (self.repository / ".worktreeinclude").write_text(".env\n", encoding="utf8")
        record = self.record("closed")
        self.real_git("branch", record["branch"], "main")  # as a session that was closed leaves it

        self.assertTrue(ready_sessions.add_worktree(self.project, record, A, self.mac))

        self.assertEqual((Path(record["worktree"]) / ".env").read_text(encoding="utf8"), "secret\n")
        self.assertIn(
            "copied 1 file listed in .worktreeinclude into the worktree of %s" % names.short(A),
            self.mac.log_text(self.project),
        )

    def test_without_a_worktreeinclude_the_session_starts_as_before(self):
        (self.repository / ".env").write_text("secret\n", encoding="utf8")

        state = self.create()

        ((session, record),) = state["sessions"].items()
        self.assertEqual(record["state"], "free")
        self.assertEqual(self.seen_at_start, [False])
        self.assertNotIn("worktreeinclude", self.mac.log_text(self.project))


class Reconcile(OnTheMac):
    def test_the_first_pass_prepares_a_free_session_and_keeps_it_in_the_projects_state(self):
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts()

        ready_sessions.reconcile(self.project, self.mac)

        state = json.loads(
            (Path(self.scratch.name) / "state" / "projects" / "shop" / "ready-sessions.json").read_text()
        )
        self.assertEqual([record["state"] for record in state["sessions"].values()], ["free"])
        self.assertEqual(len(self.mac.tmux_runner.having("new-session")), 1, "one free session, not one per pass")

    def test_stops_only_a_session_of_its_own_state_that_the_app_archived(self):
        mine, free = self.record("used"), self.record("free", B, shown=False)
        self.save({A: mine, B: free})
        self.transcript(A, mine, {"type": "user", "message": {"content": "Fix the header"}}, ARCHIVED)
        self.mac.now = ARCHIVED_AT - 100  # the session started before it was archived
        mine["started"] = self.mac.now
        self.save({A: mine, B: free})
        # Z is a session someone started by hand, with Remote Control: it is not ours.
        self.mac.ps = (
            f"301 claude --resume {A} --remote-control\n"
            f"302 claude --session-id {B} --remote-control\n"
            f"303 claude --session-id {Z} --remote-control\n"
        )

        ready_sessions.reconcile(self.project, self.mac)

        self.assertEqual(set(self.mac.terminated), {301})
        self.assertEqual(self.saved()["sessions"][A]["state"], "archived")
        self.assertNotIn(Z, self.saved()["sessions"])

    def test_does_not_stop_a_pid_that_is_no_longer_that_session(self):
        self.mac.ps = f"999 claude --session-id {A} --remote-control\n"

        ready_sessions.stop(self.project, A, 301, self.mac)

        self.assertEqual(self.mac.terminated, [])

    def test_a_session_in_use_gets_its_tab_which_then_decides_how_long_it_lives(self):
        used, free = self.record("free", shown=False, tmux="shop-aaaaaaaa"), self.record("free", B, shown=False)
        self.save({A: used, B: free})
        self.transcript(A, used, {"type": "user", "message": {"content": "Fix the header"}})
        self.mac.ps = f"301 claude --session-id {A} --remote-control\n302 claude --session-id {B} --remote-control\n"
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts(pid=503)
        self.mac.tmux_runner.answers = self.attached_after(self.mac.tmux_runner.answers)

        ready_sessions.reconcile(self.project, self.mac)

        (tab,) = self.terminal.tabs
        self.assertEqual(tab.name, "porchlight_ready_shop-aaaaaaaa")
        self.assertEqual(tab.title, "Shop · Fix the header")
        self.assertEqual(tab.directory, used["worktree"])
        self.assertEqual(tab.command, "exec /tools/tmux -L porchlight-test -u attach-session -t '=shop-aaaaaaaa'")
        self.assertEqual(
            self.mac.tmux_runner.having("set-option")[0][5:],
            ["set-option", "-t", "=shop-aaaaaaaa:", "destroy-unattached", "on"],
        )
        self.assertTrue(self.saved()["sessions"][A]["shown"])

    def attached_after(self, before):
        def answer(words):
            if "list-clients" in words:
                return standins.result(stdout="4242\n")
            return before(words)

        return answer

    def test_never_starts_the_terminal_a_session_in_use_waits_for_it(self):
        used = self.record("used", shown=False, tmux="shop-aaaaaaaa", prompt="Fix the header")
        self.save({A: used, B: self.record("free", B, shown=False)})
        self.mac.ps = f"301 claude --session-id {A} --remote-control\n302 claude --session-id {B} --remote-control\n"
        self.terminal.running = False

        ready_sessions.reconcile(self.project, self.mac)

        self.assertEqual(self.terminal.tabs, [])
        self.assertFalse(self.saved()["sessions"][A]["shown"], "its tab opens at a later pass")
        self.assertEqual(self.mac.terminated, [], "it keeps running hidden")

    def test_without_a_terminal_set_up_no_tab_is_asked_for(self):
        mac = standins.StandInMac(self.scratch.name, terminal=None)
        used = self.record("used", shown=False, tmux="shop-aaaaaaaa", prompt="Fix the header")
        mac.store(self.project, ready_sessions.STATE).save(
            {"sessions": {A: used, B: self.record("free", B, shown=False)}, "read": {}, "failures": 0, "retry_after": 0}
        )
        mac.ps = f"301 claude --session-id {A} --remote-control\n302 claude --session-id {B} --remote-control\n"

        ready_sessions.reconcile(self.project, mac)

        self.assertEqual(mac.tmux_runner.having("set-option"), [])

    def test_gives_up_on_a_tab_after_three_tries_and_the_session_keeps_running(self):
        record = self.record("used", shown=False, tmux="shop-aaaaaaaa")
        self.terminal.opens = False

        for _ in range(3):
            self.assertFalse(record["shown"])
            ready_sessions.show(self.project, A, record, self.mac)

        self.assertTrue(record["shown"], "it is driven from the app, without a tab")
        self.assertEqual(len(self.terminal.tabs), 3)
        self.assertEqual(self.mac.tmux_runner.having("set-option"), [])

    def test_a_tab_that_cannot_be_asked_for_is_logged_and_counts_as_a_try(self):
        record = self.record("used", shown=False, tmux="shop-aaaaaaaa")
        self.terminal.error = OSError("no such folder")

        ready_sessions.show(self.project, A, record, self.mac)

        self.assertEqual(record["show_failures"], 1)
        self.assertIn("failed to open a tab", self.mac.log_text(self.project))

    def test_without_ready_session_no_session_is_prepared_and_nothing_is_kept(self):
        project = self.having("server")
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts()

        ready_sessions.reconcile(project, self.mac)

        self.assertEqual(self.mac.tmux_runner.calls, [])
        self.assertEqual(self.mac.git_runner.calls, [])
        self.assertFalse((Path(self.scratch.name) / "state").exists(), "a feature that is off holds nothing")

    def test_ready_session_turned_off_ends_the_free_session_it_held_and_nothing_more(self):
        project = self.having("server")
        used = self.record("used", prompt="Fix the header", shown=False, tmux="shop-aaaaaaaa")
        free = self.record("free", B, shown=False, tmux="shop-bbbbbbbb")
        self.save({A: used, B: free})
        self.worktree(B)
        self.git(
            symbolic_ref=standins.result(stdout="origin/trunk\n"),
            branch=standins.result(stdout=free["branch"] + "\n"),
        )
        # Z is a session someone started by hand, with Remote Control: it is not ours.
        self.running_until_ended(
            f"301 claude --session-id {A} --remote-control\n"
            f"302 claude --session-id {B} --remote-control\n"
            f"303 claude --session-id {Z} --remote-control\n"
        )

        ready_sessions.reconcile(project, self.mac)

        self.assertEqual(self.mac.terminated, [302], "the free session, and only it")
        self.assertEqual(self.mac.git_runner.having("worktree", "remove")[0][-1], free["worktree"])
        self.assertEqual(self.mac.git_runner.having("branch", "-D")[0][-1], free["branch"])
        self.assertEqual(list(self.saved()["sessions"]), [A], "the session in use stays known")
        self.assertEqual(self.saved()["sessions"][A]["state"], "used")
        self.assertEqual(self.mac.tmux_runner.having("new-session"), [], "no other is prepared")
        self.assertEqual(self.terminal.tabs, [])
        self.assertIn("stopped bbbbbbbb (pid 302): the ready session is turned off", self.mac.log_text(project))

    def test_with_ready_session_off_a_session_in_use_is_still_stopped_when_archived_and_tidied(self):
        project = self.having("server")
        self.mac.now = ARCHIVED_AT - 100  # the session started before it was archived
        used = self.record("used", prompt="Fix the header")
        self.save({A: used})
        self.transcript(A, used, ARCHIVED)
        self.worktree(A)
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"))
        self.running_until_ended(f"301 claude --resume {A} --remote-control\n")

        ready_sessions.reconcile(project, self.mac)

        self.assertEqual(self.mac.terminated, [301])
        record = self.saved()["sessions"][A]
        self.assertEqual((record["state"], record["tidied"]), ("archived", True))
        self.assertEqual(self.mac.git_runner.having("worktree", "remove")[0][-1], used["worktree"])
        self.assertIn("archived from the app", self.mac.log_text(project))

    def test_without_tabs_a_session_in_use_keeps_running_hidden_and_the_terminal_is_never_looked_for(self):
        project = self.having("ready-session")
        used = self.record("used", shown=False, tmux="shop-aaaaaaaa", prompt="Fix the header")
        self.save({A: used, B: self.record("free", B, shown=False)})
        self.mac.ps = f"301 claude --session-id {A} --remote-control\n302 claude --session-id {B} --remote-control\n"

        ready_sessions.reconcile(project, self.mac)

        self.assertEqual(self.terminal.tabs, [])
        self.assertEqual(self.terminal.asked, 0, "the terminal is not looked for")
        self.assertFalse(self.saved()["sessions"][A]["shown"])
        self.assertEqual(self.mac.terminated, [], "it keeps running hidden")
        self.assertEqual(self.mac.tmux_runner.calls, [])

    def test_two_projects_keep_their_sessions_apart(self):
        (Path(self.scratch.name) / "blog").mkdir()
        blog = standins.project("blog", str(Path(self.scratch.name) / "blog"), mode="acceptEdits", prefix="Blog")
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts()

        ready_sessions.reconcile(self.project, self.mac)
        ready_sessions.reconcile(blog, self.mac)

        shop_state = self.saved()["sessions"]
        blog_state = self.mac.store(blog, ready_sessions.STATE).load({})["sessions"]
        self.assertEqual((len(shop_state), len(blog_state)), (1, 1))
        self.assertEqual(set(shop_state) & set(blog_state), set())
        (blog_record,) = blog_state.values()
        self.assertTrue(blog_record["tmux"].startswith("blog-"))
        self.assertIn(str(names.repository(blog)), blog_record["worktree"])
        started = self.mac.tmux_runner.having("new-session")
        self.assertIn("--permission-mode plan", started[0][-1])
        self.assertIn("--permission-mode acceptEdits", started[1][-1])


class Reopen(OnTheMac):
    def reopen(self, text):
        return ready_sessions.reopen(self.project, text, self.mac, out=self.printed.append)

    def test_without_a_name_lists_the_closed_sessions(self):
        self.save({A: self.record("closed", title="Header on phones", tidied=True), B: self.record("used", B)})

        self.assertEqual(self.reopen(""), 0)

        self.assertEqual(self.printed[0], "Closed sessions:")
        self.assertIn("Header on phones", self.printed[1])
        self.assertEqual(len(self.printed), 2, "a session that is open is not offered")
        self.assertEqual(self.terminal.tabs, [])

    def test_says_when_nothing_is_closed_or_nothing_matches(self):
        self.save({})
        self.assertEqual(self.reopen(""), 0)
        self.assertEqual(self.printed, ["No closed session."])

        self.assertEqual(self.reopen("header"), 1)
        self.assertEqual(self.printed[-1], 'No closed session matches "header".')

    def test_asks_for_an_id_when_several_match(self):
        self.save(
            {
                A: self.record("closed", prompt="Fix the header", tidied=True),
                B: self.record("archived", B, prompt="Fix the footer", tidied=True),
            }
        )

        self.assertEqual(self.reopen("fix"), 1)

        self.assertIn("Several closed sessions match", self.printed[0])
        self.assertEqual(len(self.printed), 3)
        self.assertEqual(self.terminal.tabs, [])

    def test_opens_the_session_again_in_a_tab_on_the_same_conversation(self):
        self.save({A: self.record("archived", title="Header on phones", tidied=True, tmux="shop-aaaaaaaa")})
        self.git(rev_parse=standins.result(returncode=0))
        self.terminal.on_open = lambda tab: setattr(self.mac, "ps", f"601 claude --resume {A} --remote-control\n")

        self.assertEqual(self.reopen("header on phones"), 0)

        (tab,) = self.terminal.tabs
        self.assertEqual(tab.name, "porchlight_ready_shop-aaaaaaaa")
        self.assertEqual(tab.title, "Shop · Header on phones")
        self.assertIn(f" --resume {A} ", tab.command)
        self.assertIn("/tools/porchlight reopen <name>", tab.command, "it is told how to reopen another")
        self.assertTrue(tab.command.endswith(" --remote-control"))
        self.assertEqual(len(self.mac.git_runner.having("worktree", "add")), 1, "its worktree comes back")
        record = self.saved()["sessions"][A]
        self.assertEqual((record["state"], record["tidied"], record["shown"], record["tmux"]), ("used", False, True, ""))
        self.assertIn('Reopened "Header on phones"', self.printed[-1])
        self.assertEqual(self.mac.tmux_runner.calls, [], "a reopened session runs in its tab, without tmux")

    def test_never_starts_the_terminal_to_reopen(self):
        self.save({A: self.record("closed", title="Header on phones", tidied=True)})
        self.terminal.running = False

        self.assertEqual(self.reopen("header"), 1)

        self.assertEqual(self.printed, ["Stand-in is not running on the Mac, so no tab can open. Nothing was reopened."])
        self.assertEqual(self.terminal.tabs, [])
        self.assertEqual(self.mac.git_runner.calls, [])
        self.assertEqual(self.saved()["sessions"][A]["state"], "closed")

    def test_says_when_the_tab_did_not_start(self):
        self.save({A: self.record("closed", title="Header on phones", tidied=True)})
        self.terminal.opens = False

        self.assertEqual(self.reopen("header"), 1)

        self.assertEqual(self.printed[-1], "The tab did not start. Nothing was reopened.")
        self.assertEqual(self.saved()["sessions"][A]["state"], "closed")

    def test_refuses_for_a_project_without_the_feature_and_names_it(self):
        project = self.having("ready-session", "tabs")
        self.save({A: self.record("closed", title="Header on phones", tidied=True)})

        self.assertEqual(ready_sessions.reopen(project, "header", self.mac, out=self.printed.append), 1)
        self.assertEqual(ready_sessions.reopen(project, "", self.mac, out=self.printed.append), 1)

        refusal = 'The project "shop" does not have the feature "reopen". Nothing was reopened.'
        self.assertEqual(self.printed, [refusal, refusal])
        self.assertEqual(self.terminal.tabs, [])
        self.assertEqual(self.saved()["sessions"][A]["state"], "closed")



class ReopenWithoutTabs(OnTheMac):
    """A project without `tabs`: the session comes back hidden, as a ready session starts."""

    ATTACH = "/tools/tmux -L porchlight-test -u attach-session -t '=shop-aaaaaaaa'"

    def setUp(self):
        super().setUp()
        self.project = self.having("ready-session", "reopen")
        self.save({A: self.record("archived", title="Header on phones", tidied=True, show_failures=3)})
        self.git(rev_parse=standins.result(returncode=0))

    def reopen(self, text):
        return ready_sessions.reopen(self.project, text, self.mac, out=self.printed.append)

    def claude_resumes(self, pid=601):
        def answer(words):
            if "new-session" in words:
                self.mac.ps = f"{pid} claude --resume {A} --remote-control\n"

        self.mac.tmux_runner.answers = answer

    def test_resumes_the_session_hidden_in_tmux_and_prints_the_command_that_attaches_to_it(self):
        self.claude_resumes()

        self.assertEqual(self.reopen("header on phones"), 0)

        (started,) = self.mac.tmux_runner.having("new-session")
        self.assertEqual(started[:3], ["/tools/tmux", "-L", "porchlight-test"], "in the tool's own tmux server")
        self.assertIn("-d", started, "detached: nobody sees it")
        self.assertEqual(started[started.index("-s") + 1], "shop-aaaaaaaa")
        self.assertEqual(started[started.index("-c") + 1], str(self.worktree(make=False)))
        self.assertIn(f" --resume {A} ", started[-1], "the same conversation")
        self.assertIn("--remote-control", started[-1])
        self.assertEqual(len(self.mac.git_runner.having("worktree", "add")), 1, "its worktree comes back")
        self.assertEqual((self.terminal.tabs, self.terminal.asked), ([], 0), "the terminal is never looked for")
        self.assertEqual(
            self.printed,
            [
                'Reopened "Header on phones" (project shop), hidden: this project opens no tabs. It comes back '
                "online in the Claude app, as the same session, within a few seconds. To see it on the Mac, run:",
                "    " + self.ATTACH,
            ],
        )
        self.assertIn("reopened aaaaaaaa (Header on phones), hidden", self.mac.log_text(self.project))

    def test_the_session_is_then_in_use_and_hidden_so_that_status_shows_how_to_attach(self):
        self.claude_resumes()
        self.reopen("header")

        record = self.saved()["sessions"][A]
        self.assertEqual(
            (record["state"], record["tidied"], record["shown"], record["tmux"]), ("used", False, False, "shop-aaaaaaaa")
        )
        self.assertNotIn("show_failures", record, "a tab given up on before does not count against it")
        self.assertEqual(record["started"], self.mac.now)
        status = []
        ready_sessions.status(self.project, self.mac, out=status.append)
        self.assertRegex(status[0], r"^aaaaaaaa  used .* Header on phones  \(pid 601, not in the app yet, hidden\)$")
        self.assertEqual(status[1], "    " + self.ATTACH)

        ready_sessions.reconcile(self.project, self.mac)
        self.assertEqual(self.mac.terminated, [], "the next pass leaves it running")
        self.assertEqual(self.saved()["sessions"][A]["state"], "used")

    def test_says_when_the_session_did_not_start_and_leaves_nothing_behind(self):
        self.assertEqual(self.reopen("header"), 1)  # tmux answers, and Claude Code never shows up

        self.assertEqual(self.printed, ["The session did not start in tmux. Nothing was reopened."])
        self.assertEqual(self.saved()["sessions"][A]["state"], "archived")
        self.assertEqual(
            [call[5:] for call in self.mac.tmux_runner.having("kill-session")],
            [["kill-session", "-t", "=shop-aaaaaaaa"]],
        )

    def test_says_what_tmux_answered_when_it_refused(self):
        self.mac.tmux_runner.answers = lambda words: (
            standins.result(returncode=1, stderr="duplicate session: shop-aaaaaaaa\n") if "new-session" in words else None
        )

        self.assertEqual(self.reopen("header"), 1)

        self.assertEqual(self.printed, ["The session did not start in tmux. Nothing was reopened."])
        self.assertIn("tmux did not start aaaaaaaa: duplicate session", self.mac.log_text(self.project))
        self.assertEqual(self.saved()["sessions"][A]["state"], "archived")

    def test_still_lists_the_closed_sessions_and_asks_when_none_or_several_match(self):
        self.assertEqual(self.reopen(""), 0)
        self.assertEqual(self.printed[0], "Closed sessions:")
        self.assertEqual(self.reopen("footer"), 1)
        self.assertEqual(self.printed[2], 'No closed session matches "footer". The closed ones:')
        self.assertEqual(self.mac.tmux_runner.calls, [])

    def test_a_project_with_tabs_still_reopens_in_a_tab(self):
        self.project = self.having("ready-session", "tabs", "reopen")
        self.terminal.on_open = lambda tab: setattr(self.mac, "ps", f"601 claude --resume {A} --remote-control\n")

        self.assertEqual(self.reopen("header"), 0)

        self.assertEqual(len(self.terminal.tabs), 1)
        self.assertEqual(self.mac.tmux_runner.calls, [])
        self.assertIn("in a new tab on the Mac", self.printed[-1])


class ReopenAnywhere(OnTheMac):
    """One search over every project that has `reopen`."""

    def setUp(self):
        super().setUp()
        self.blog = self.another("blog", "Blog")
        self.docs = self.another("docs", "Docs", features=("ready-session", "tabs"))  # without reopen
        self.configuration = config.Config("warp", (self.project, self.blog, self.docs))
        self.save({A: self.record("closed", title="Header on phones", tidied=True, changed=self.mac.now - 60)})
        self.save(
            {B: self.record("archived", B, self.blog, prompt="Fix the footer", tidied=True)}, project=self.blog
        )
        self.save({C: self.record("closed", C, self.docs, prompt="Fix the index", tidied=True)}, project=self.docs)

    def reopen(self, text, configuration=None):
        return ready_sessions.reopen_anywhere(
            configuration or self.configuration, text, self.mac, out=self.printed.append
        )

    def test_without_a_name_lists_the_closed_sessions_of_every_project_that_has_it(self):
        self.assertEqual(self.reopen(""), 0)

        self.assertEqual(self.printed[0], "Closed sessions:")
        self.assertRegex(self.printed[1], r"^  blog  bbbbbbbb  archived .* Fix the footer$")
        self.assertRegex(self.printed[2], r"^  shop  aaaaaaaa  closed .* Header on phones$")
        self.assertEqual(len(self.printed), 3, "a project without the feature is not searched")
        self.assertEqual(self.terminal.tabs, [])

    def test_reopens_the_one_session_that_matches_and_says_whose_it_is(self):
        self.git(rev_parse=standins.result(returncode=0))
        self.terminal.on_open = lambda tab: setattr(self.mac, "ps", f"601 claude --resume {B} --remote-control\n")

        self.assertEqual(self.reopen("footer"), 0)

        (tab,) = self.terminal.tabs
        self.assertEqual(tab.name, "porchlight_ready_blog-bbbbbbbb")
        self.assertEqual(tab.title, "Blog · Fix the footer")
        self.assertIn(f" --resume {B} ", tab.command)
        self.assertIn(" --permission-mode acceptEdits ", tab.command, "with its own project's mode")
        (added,) = self.mac.git_runner.having("worktree", "add")
        self.assertEqual(added[2], str(names.repository(self.blog)), "in its own project's repository")
        self.assertEqual(self.printed, [
            'Reopened "Fix the footer" (project blog) in a new tab on the Mac. It comes back online in the '
            "Claude app, as the same session, within a few seconds."
        ])  # fmt: skip
        self.assertEqual(self.saved(self.blog)["sessions"][B]["state"], "used")
        self.assertEqual(self.saved()["sessions"][A]["state"], "closed", "the other project is left as it was")

    def test_lists_the_candidates_with_their_project_when_several_match(self):
        self.assertEqual(self.reopen("e"), 1)

        self.assertEqual(self.printed[0], 'Several closed sessions match "e"; run it again with the id of one:')
        self.assertRegex(self.printed[1], r"^  blog  bbbbbbbb  ")
        self.assertRegex(self.printed[2], r"^  shop  aaaaaaaa  ")
        self.assertEqual(len(self.printed), 3)
        self.assertEqual(self.terminal.tabs, [])

        self.git(rev_parse=standins.result(returncode=0))
        self.terminal.on_open = lambda tab: setattr(self.mac, "ps", f"601 claude --resume {A} --remote-control\n")
        self.assertEqual(self.reopen("aaaaaaaa"), 0, "the id of one of them settles it")
        self.assertEqual(self.terminal.tabs[0].name, "porchlight_ready_shop-aaaaaaaa")

    def test_lists_every_closed_session_with_its_project_when_none_matches(self):
        self.assertEqual(self.reopen("index"), 1, "a session of a project without the feature is not found")

        self.assertEqual(self.printed[0], 'No closed session matches "index". The closed ones:')
        self.assertRegex(self.printed[1], r"^  blog  bbbbbbbb  ")
        self.assertRegex(self.printed[2], r"^  shop  aaaaaaaa  ")
        self.assertEqual(len(self.printed), 3)
        self.assertEqual(self.terminal.tabs, [])

    def test_refuses_when_no_project_has_the_feature_and_names_it(self):
        self.assertEqual(self.reopen("index", config.Config("warp", (self.docs,))), 1)

        self.assertEqual(self.printed, ['No project has the feature "reopen". Nothing was reopened.'])
        self.assertEqual(self.terminal.tabs, [])


class Status(OnTheMac):
    def test_prints_each_session_with_its_state(self):
        self.save(
            {
                A: self.record("used", title="Header on phones", cse="cse_01AAA", shown=False),
                B: self.record("closed", B, prompt="Fix the footer", changed=self.mac.now - 60),
            }
        )
        self.mac.ps = f"301 claude --session-id {A} --remote-control\n"

        ready_sessions.status(self.project, self.mac, out=self.printed.append)

        self.assertEqual(len(self.printed), 2)
        self.assertRegex(self.printed[0], r"^aaaaaaaa  used .* Header on phones  \(pid 301, cse_01AAA, hidden\)$")
        self.assertRegex(self.printed[1], r"^bbbbbbbb  closed .* Fix the footer  \(not running\)$")

    def test_without_tabs_prints_the_command_that_attaches_to_each_running_session_without_a_tab(self):
        project = self.having("ready-session")
        self.save(
            {
                A: self.record("used", title="Header on phones", shown=False, tmux="shop-aaaaaaaa"),
                # Its tab was given up on while tabs were on: it runs hidden all the same.
                B: self.record("used", B, shown=True, show_failures=3, tmux="shop-bbbbbbbb", changed=self.mac.now - 30),
                # Reopened in a tab after that, while tabs were on: it runs in that tab, without tmux.
                C: self.record("used", C, shown=True, show_failures=3, tmux="", changed=self.mac.now - 60),
                Z: self.record("closed", Z, shown=False, tmux="shop-ffffffff", changed=self.mac.now - 90),
            }
        )
        self.mac.ps = "".join(
            f"{pid} claude --session-id {session} --remote-control\n" for pid, session in ((301, A), (302, B), (303, C))
        )

        ready_sessions.status(project, self.mac, out=self.printed.append)

        self.assertEqual(
            [line for line in self.printed if line.startswith("    ")],
            [
                "    /tools/tmux -L porchlight-test -u attach-session -t '=shop-aaaaaaaa'",
                "    /tools/tmux -L porchlight-test -u attach-session -t '=shop-bbbbbbbb'",
            ],
        )
        self.assertRegex(self.printed[0], r"^aaaaaaaa  used .*, hidden\)$")
        self.assertEqual(self.printed[1], "    /tools/tmux -L porchlight-test -u attach-session -t '=shop-aaaaaaaa'")
        self.assertRegex(self.printed[4], r"^cccccccc  used .* \(pid 303, not in the app yet\)$")
        self.assertEqual(len(self.printed), 6)
        self.assertEqual(self.terminal.asked, 0)

    def test_with_tabs_a_hidden_session_waits_for_its_tab_and_no_command_is_printed(self):
        self.save({A: self.record("used", title="Header on phones", shown=False, tmux="shop-aaaaaaaa")})
        self.mac.ps = f"301 claude --session-id {A} --remote-control\n"

        ready_sessions.status(self.project, self.mac, out=self.printed.append)

        self.assertEqual(len(self.printed), 1)

    def test_with_tabs_a_session_whose_tab_was_given_up_on_gets_the_command_that_attaches_to_it(self):
        self.save(
            {
                A: self.record("used", title="Header on phones", shown=True, show_failures=3, tmux="shop-aaaaaaaa"),
                # Its tab opened: closing the tab ends it, so it needs no command.
                B: self.record("used", B, shown=True, tmux="shop-bbbbbbbb", changed=self.mac.now - 30),
            }
        )
        self.mac.ps = "".join(
            f"{pid} claude --session-id {session} --remote-control\n" for pid, session in ((301, A), (302, B))
        )

        ready_sessions.status(self.project, self.mac, out=self.printed.append)

        self.assertRegex(self.printed[0], r"^aaaaaaaa  used .*, hidden\)$")
        self.assertEqual(self.printed[1], "    /tools/tmux -L porchlight-test -u attach-session -t '=shop-aaaaaaaa'")
        self.assertRegex(self.printed[2], r"^bbbbbbbb  used .* \(pid 302, not in the app yet\)$")
        self.assertEqual(len(self.printed), 3)

    def test_says_when_there_is_none(self):
        ready_sessions.status(self.project, self.mac, out=self.printed.append)

        self.assertEqual(self.printed, ["No session with Claude Code's interface yet."])

    def test_says_when_the_free_session_waits_out_a_back_off_and_how_to_try_now(self):
        self.save({A: self.record("closed", title="Header on phones")}, failures=3, retry_after=self.mac.now + 480)

        ready_sessions.status(self.project, self.mac, out=self.printed.append)

        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.mac.now + 480))
        self.assertEqual(len(self.printed), 2)
        self.assertRegex(self.printed[0], r"^aaaaaaaa  closed .* Header on phones  \(not running\)$")
        self.assertEqual(
            self.printed[1],
            "No free session for now: 3 attempts in a row failed. The next one is at %s; "
            "to try now: porchlight retry --project shop" % when,
        )

        self.printed.clear()
        self.save({}, failures=1, retry_after=self.mac.now + 120)
        ready_sessions.status(self.project, self.mac, out=self.printed.append)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.mac.now + 120))
        self.assertEqual(
            self.printed,
            [
                "No session with Claude Code's interface yet.",
                "No free session for now: 1 attempt failed. The next one is at %s; "
                "to try now: porchlight retry --project shop" % when,
            ],
        )

    def test_says_nothing_of_a_back_off_that_is_over(self):
        self.save({}, failures=2, retry_after=self.mac.now)

        ready_sessions.status(self.project, self.mac, out=self.printed.append)

        self.assertEqual(self.printed, ["No session with Claude Code's interface yet."])


class Retry(OnTheMac):
    def test_a_pass_during_a_back_off_prepares_nothing_and_one_after_retry_tries_at_once(self):
        self.git(symbolic_ref=standins.result(stdout="origin/trunk\n"), rev_parse=standins.result(returncode=1))
        self.claude_starts()
        self.save({}, failures=3, retry_after=self.mac.now + 480)

        ready_sessions.reconcile(self.project, self.mac)

        self.assertEqual(self.mac.tmux_runner.having("new-session"), [], "the back-off holds")
        self.assertEqual(self.saved()["sessions"], {})

        self.assertTrue(ready_sessions.retry(self.project, self.mac, self.printed.append, within=20))

        saved = self.saved()
        self.assertEqual((saved["failures"], saved["retry_after"]), (0, 0))
        self.assertEqual(
            self.printed,
            ["shop: the back-off is cleared (3 attempts had failed). The service tries again at its next pass, "
             "within 20 seconds."],
        )  # fmt: skip
        self.assertEqual(self.mac.tmux_runner.calls, [], "retry starts nothing itself")
        self.assertIn("the back-off is cleared by hand (3 failed in a row)", self.mac.log_text(self.project))

        ready_sessions.reconcile(self.project, self.mac)

        self.assertEqual([record["state"] for record in self.saved()["sessions"].values()], ["free"])

    def test_keeps_the_sessions_and_says_when_there_is_no_back_off(self):
        self.save({A: self.record("used")}, failures=0, retry_after=self.mac.now - 600)
        before = self.saved()

        self.assertFalse(ready_sessions.retry(self.project, self.mac, self.printed.append, within=20))

        self.assertEqual(self.printed, ["shop: no back-off; nothing to clear."])
        self.assertEqual(self.saved(), before, "nothing is written")
        self.assertEqual(self.mac.log_text(self.project), "")

        self.printed.clear()
        self.save({A: self.record("used")}, failures=1, retry_after=self.mac.now + 120)
        ready_sessions.retry(self.project, self.mac, self.printed.append, within=20)
        self.assertEqual(self.saved()["sessions"], {A: self.record("used")}, "the sessions stay as they were")

    def test_a_project_with_no_state_yet_has_no_back_off_and_gets_no_file(self):
        self.assertFalse(ready_sessions.retry(self.project, self.mac, self.printed.append, within=20))

        self.assertEqual(self.printed, ["shop: no back-off; nothing to clear."])
        self.assertFalse(self.mac.store(self.project, ready_sessions.STATE).path.exists())


if __name__ == "__main__":
    unittest.main()
