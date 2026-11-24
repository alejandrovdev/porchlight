"""Tests of what the ready sessions do on the Mac, against stand-ins: git, tmux, the
terminal, the process list and the clock answer what each test tells them to."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from porchlight import names
from porchlight.atoms import tools
from porchlight.features import ready_sessions
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
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

    def worktree(self, session=A, make=True):
        path = self.repository / ".claude" / "worktrees" / names.worktree(self.project, session)
        if make:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def record(self, state="used", session=A, **extra):
        record = {
            "state": state,
            "started": self.mac.now,
            "changed": self.mac.now,
            "worktree": str(self.worktree(session, make=False)),
            "branch": names.branch(self.project, session),
            "prompt": "",
            "title": "",
            "cse": "",
            "tidied": False,
            "shown": True,
            "tmux": "",
        }
        record.update(extra)
        return record

    def save(self, sessions, **extra):
        state = dict({"sessions": sessions, "read": {}, "failures": 0, "retry_after": 0}, **extra)
        self.mac.store(self.project, ready_sessions.STATE).save(state)

    def saved(self):
        return self.mac.store(self.project, ready_sessions.STATE).load({})

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
    def test_says_in_english_how_to_reopen_and_names_the_command(self):
        note = ready_sessions.note()

        self.assertIn("reopen <name>", note)
        self.assertIn("porchlight reopen <name>", note)
        self.assertNotIn("/", note, "a command, not the path of a script")
        self.assertNotIn(".sh", note)

    def test_every_session_is_told_how(self):
        project = standins.project("blog", "/srv/blog", mode="acceptEdits", prefix="Blog")

        command = ready_sessions.command_line(project, A, False, "/tools/claude", "/state/settings.json")

        self.assertIn("porchlight reopen", command)
        self.assertIn(" --permission-mode acceptEdits ", command, "the mode is the project's")
        self.assertIn(" --remote-control-session-name-prefix Blog ", command, "the prefix is the project's")
        self.assertIn(" --settings /state/settings.json ", command)


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

    def test_says_when_there_is_none(self):
        ready_sessions.status(self.project, self.mac, out=self.printed.append)

        self.assertEqual(self.printed, ["No session with Claude Code's interface yet."])


if __name__ == "__main__":
    unittest.main()
