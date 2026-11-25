"""Tests of one pass over a whole configuration: every project by itself, each feature only
where it is on, and nothing shared between two projects. Against stand-ins and scratch
folders: no session starts, no tab opens and no process is signalled."""

import json
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from porchlight import config, names, passes
from porchlight.atoms import transcripts
from porchlight.features import ready_sessions, resume_list, view_tabs
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
SHOP_LIVE = "cse_01AAA"
BLOG_LIVE = "cse_01BBB"
SERVER_ID = "11111111-1111-5111-8111-111111111111"
ARCHIVED = {
    "type": "system",
    "content": ready_sessions.ARCHIVED + " (code 4090)",
    "timestamp": "2026-11-24T22:23:14.266Z",
}
ARCHIVED_AT = 1795558994.0


class Scratch(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.terminal = standins.Terminal()
        self.terminal.on_open = self.tab_opens
        self.mac = standins.StandInMac(self.root, self.terminal)
        self.mac.now = time.time() + 3600  # every folder made here is an hour old
        self.mac.git_runner.answers = self.git
        self.mac.tmux_runner.answers = self.tmux
        self.pid = 500

    def tearDown(self):
        self.scratch.cleanup()

    def project(self, name, features=None, make=True):
        if make:
            (self.root / name).mkdir()
        return standins.project(name, str(self.root / name), prefix=name.capitalize(), features=features)

    def git(self, words):
        """A repository whose origin states a default branch and that has no branch of a session yet."""
        if "symbolic-ref" in words:
            return standins.result(stdout="origin/trunk\n")
        if "rev-parse" in words:
            return standins.result(returncode=1)

    def tmux(self, words):
        """Claude Code shows up in the process list once tmux starts it; a tab shows what it attaches to."""
        if "new-session" in words:
            self.pid += 1
            session = re.search(r"--session-id (\S+)", words[-1]).group(1)
            self.mac.ps += f"{self.pid} claude --session-id {session} --remote-control\n"
        if "list-clients" in words:
            return standins.result(stdout="4242\n")

    def tab_opens(self, tab):
        if tab.name.startswith("porchlight_view_"):
            self.mac.ps += "401 " + tab.command[len("exec ") :] + "\n"

    def server_session(self, project, session, pid):
        """A session the server runs for a project: its worktree, its process and its transcript."""
        repository = names.repository(project)
        worktree = repository / ".claude" / "worktrees" / ("bridge-" + session)
        worktree.mkdir(parents=True)
        self.mac.ps += (
            f"{pid} claude --print --sdk-url wss://example.invalid/x --session-id {session} "
            "--output-format stream-json\n"
        )
        lines = [
            {"type": "queue-operation", "sessionId": SERVER_ID, "content": "Fix the header"},
            {"type": "user", "sessionId": SERVER_ID, "entrypoint": "sdk-cli", "cwd": str(worktree)},
        ]
        folder = self.mac.transcripts / transcripts.folder_name(worktree)
        folder.mkdir(parents=True)
        (folder / (SERVER_ID + ".jsonl")).write_text(
            "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines), encoding="utf8"
        )
        self.copies_folder(project).mkdir(parents=True)  # Claude Code keeps the repository's own sessions here

    def copies_folder(self, project):
        return self.mac.transcripts / transcripts.folder_name(names.repository(project))

    def copies(self, project):
        return sorted(path.stem for path in self.copies_folder(project).glob("*.jsonl"))

    def ready_session(self, project, session, state, pid, **extra):
        """A hidden session in a project's state, and its process."""
        record = {
            "state": state,
            "started": self.mac.now,
            "changed": self.mac.now,
            "worktree": str(names.repository(project) / ".claude" / "worktrees" / names.worktree(project, session)),
            "branch": names.branch(project, session),
            "prompt": "",
            "title": "",
            "cse": "",
            "tidied": False,
            "shown": False,
            "tmux": names.tmux_session(project, session),
        }
        record.update(extra)
        store = self.mac.store(project, ready_sessions.STATE)
        state = ready_sessions.load_state(store)
        state["sessions"][session] = record
        store.save(state)
        self.mac.ps += f"{pid} claude --session-id {session} --remote-control\n"
        return record

    def ready(self, project):
        return self.mac.store(project, ready_sessions.STATE).load({}).get("sessions", {})

    def state_folder(self, project):
        return self.root / "state" / "projects" / project.name


class WholeConfiguration(Scratch):
    def test_runs_every_project_in_the_order_of_the_configuration(self):
        shop, blog = self.project("shop"), self.project("blog")
        ran = []
        steps = (
            ("first", lambda project, mac: ran.append(("first", project.name))),
            ("second", lambda project, mac: ran.append(("second", project.name))),
        )

        passes.run(config.Config("warp", (shop, blog)), self.mac, steps)

        self.assertEqual(ran, [("first", "shop"), ("second", "shop"), ("first", "blog"), ("second", "blog")])

    def test_a_project_whose_folder_is_missing_is_logged_and_the_next_still_runs(self):
        shop, blog = self.project("shop", make=False), self.project("blog")

        passes.run(config.Config("warp", (shop, blog)), self.mac)

        self.assertIn("is missing", self.mac.log_text(shop))
        self.assertIn(str(self.root / "shop"), self.mac.log_text(shop))
        self.assertFalse(self.state_folder(shop).exists(), "nothing is done for it")
        self.assertEqual([record["state"] for record in self.ready(blog).values()], ["free"])

    def test_a_project_that_raises_is_logged_and_the_next_still_runs(self):
        shop, blog = self.project("shop"), self.project("blog")
        self.state_folder(shop).parent.mkdir(parents=True)
        self.state_folder(shop).write_text("where its state folder should be")

        passes.run(config.Config("warp", (shop, blog)), self.mac)

        self.assertIn("view tabs failed", self.mac.log_text(shop))
        self.assertIn("ready sessions failed", self.mac.log_text(shop))
        self.assertEqual([record["state"] for record in self.ready(blog).values()], ["free"])
        self.assertNotIn("failed", self.mac.log_text(blog))

    def test_whatever_the_pass_of_a_project_raises_the_next_project_still_runs(self):
        shop, blog = self.project("shop"), self.project("blog")
        ran = []

        def one(project, mac, steps):
            ran.append(project.name)
            if project is shop:
                raise RuntimeError("broken")

        with mock.patch.object(passes, "run_project", one):
            passes.run(config.Config("warp", (shop, blog)), self.mac)

        self.assertEqual(ran, ["shop", "blog"])
        self.assertIn("the pass failed: RuntimeError('broken')", self.mac.log_text(shop))


class RemovedProject(Scratch):
    """A project that left the configuration still has a folder in the tool's state."""

    def ends_when_asked(self):
        def terminate(pid):
            self.mac.terminated.append(pid)
            self.mac.ps = "".join(line for line in self.mac.ps.splitlines(True) if not line.startswith("%d " % pid))

        self.mac.terminate = terminate

    def test_its_free_session_is_let_go_as_when_the_feature_is_turned_off(self):
        shop, blog = self.project("shop"), self.project("blog")
        record = self.ready_session(shop, A, "free", 501)
        Path(record["worktree"]).mkdir(parents=True)
        self.ends_when_asked()

        passes.run(config.Config("warp", (blog,)), self.mac)

        self.assertEqual(self.mac.terminated, [501])
        self.assertEqual(self.ready(shop), {})
        self.assertIn("the ready session is turned off", self.mac.log_text(shop))
        self.assertIn("removed the worktree porchlight-shop-aaaaaaaa", self.mac.log_text(shop))
        self.assertEqual([record["state"] for record in self.ready(blog).values()], ["free"], "the others go on")

    def test_its_sessions_in_use_and_its_closed_ones_are_left_as_they_are(self):
        shop = self.project("shop")
        self.ready_session(shop, A, "used", 501, prompt="Fix the header", shown=True)
        self.ready_session(shop, B, "closed", 502, tidied=True)
        self.mac.ps = self.mac.ps.replace(f"502 claude --session-id {B} --remote-control\n", "")
        before = self.ready(shop)

        passes.run(config.Config(), self.mac)

        self.assertEqual(self.mac.terminated, [])
        self.assertEqual(self.ready(shop), before)
        self.assertEqual(self.terminal.tabs, [])

    def test_a_folder_of_the_state_that_holds_no_free_session_is_not_even_opened_as_a_project(self):
        shop = self.project("shop")
        self.state_folder(shop).mkdir(parents=True)
        (self.state_folder(shop).parent / "Not A Project").mkdir()

        passes.run(config.Config(), self.mac)

        self.assertEqual(self.mac.log_text(shop), "")
        self.assertEqual(self.mac.git_runner.calls, [])

    def test_free_sessions_whose_worktrees_name_two_folders_are_left_as_they_are(self):
        shop, elsewhere = self.project("shop"), self.project("elsewhere")
        self.ready_session(shop, A, "free", 501)
        moved = names.repository(elsewhere) / ".claude" / "worktrees" / names.worktree(shop, B)
        self.ready_session(shop, B, "free", 502, worktree=str(moved))
        before = self.ready(shop)
        self.ends_when_asked()

        passes.run(config.Config(), self.mac)

        self.assertEqual(self.mac.terminated, [], "the state does not say which folder the project was in")
        self.assertEqual(self.ready(shop), before)

    def test_a_free_session_whose_repository_is_gone_is_left_and_the_pass_goes_on(self):
        shop, blog = self.project("shop"), self.project("blog")
        self.ready_session(shop, A, "free", 501)
        (self.root / "shop").rmdir()

        passes.run(config.Config("warp", (blog,)), self.mac)

        self.assertEqual(self.mac.terminated, [])
        self.assertIn(A, self.ready(shop))
        self.assertEqual([record["state"] for record in self.ready(blog).values()], ["free"])


class Features(Scratch):
    def test_each_project_gets_only_what_its_features_give(self):
        shop, blog = self.project("shop", features=("server",)), self.project("blog")
        self.server_session(shop, SHOP_LIVE, 101)
        self.server_session(blog, BLOG_LIVE, 102)

        passes.run(config.Config("warp", (shop, blog)), self.mac)

        self.assertEqual([tab.name for tab in self.terminal.tabs], ["porchlight_view_blog-01BBB"])
        self.assertEqual(self.copies(shop), [])
        self.assertEqual(self.copies(blog), [resume_list.copy_id(blog, SERVER_ID, 1)])
        self.assertEqual([record["state"] for record in self.ready(blog).values()], ["free"])
        (started,) = self.mac.tmux_runner.having("new-session")
        self.assertEqual(started[started.index("-s") + 1][:5], "blog-")
        self.assertFalse(self.state_folder(shop).exists(), "features that are off keep nothing")
        self.assertEqual(self.mac.log_text(shop), "")

    def test_a_project_without_the_server_gets_its_ready_session_all_the_same(self):
        shop = self.project("shop", features=("ready-session",))

        passes.run(config.Config(None, (shop,)), self.mac)

        self.assertEqual([record["state"] for record in self.ready(shop).values()], ["free"])
        self.assertNotIn("failed", self.mac.log_text(shop))
        self.assertEqual((self.terminal.tabs, self.terminal.asked), ([], 0), "and the terminal is never looked for")
        kept = sorted(path.name for path in self.state_folder(shop).glob("*.json"))
        self.assertEqual(kept, ["ready-sessions.json", "settings.json"], "nothing of the features it lacks")


class TwoProjects(Scratch):
    def test_two_projects_with_everything_on_never_touch_each_others_sessions_state_or_tabs(self):
        shop, blog = self.project("shop"), self.project("blog")
        self.server_session(shop, SHOP_LIVE, 101)
        self.server_session(blog, BLOG_LIVE, 102)
        used = self.ready_session(shop, A, "used", 301, prompt="Fix the header")
        self.ready_session(shop, B, "free", 302)
        archived = self.ready_session(blog, C, "used", 303, prompt="Fix the footer", started=ARCHIVED_AT - 100)
        self.ready_session(blog, D, "free", 304)
        transcript = self.mac.transcripts / transcripts.folder_name(archived["worktree"]) / (C + ".jsonl")
        transcript.parent.mkdir(parents=True)
        transcript.write_text(json.dumps(ARCHIVED) + "\n", encoding="utf8")

        passes.run(config.Config("warp", (shop, blog)), self.mac)

        # Tabs: each carries its project's name, and the archived session of blog gets none.
        self.assertEqual(
            [(tab.name, tab.title) for tab in self.terminal.tabs],
            [
                ("porchlight_view_shop-01AAA", "Shop · Fix the header"),
                ("porchlight_ready_shop-aaaaaaaa", "Shop · Fix the header"),
                ("porchlight_view_blog-01BBB", "Blog · Fix the header"),
            ],
        )
        self.assertEqual(self.terminal.tabs[1].directory, used["worktree"])
        self.assertEqual(self.terminal.tabs[1].command, self.mac.tmux.attach_command("shop-aaaaaaaa"))
        self.assertEqual(
            [call[5:] for call in self.mac.tmux_runner.having("set-option")],
            [["set-option", "-t", "=shop-aaaaaaaa:", "destroy-unattached", "on"]],
        )
        # Sessions: only the one the app archived is ended, in the project it belongs to.
        self.assertEqual(set(self.mac.terminated), {303})
        self.assertIn("stopped cccccccc", self.mac.log_text(blog))
        self.assertNotIn("cccccccc", self.mac.log_text(shop))
        self.assertEqual(self.mac.tmux_runner.having("new-session"), [], "each already has its free session")
        # State: each project knows its own sessions and no other.
        self.assertEqual({key: record["state"] for key, record in self.ready(shop).items()}, {A: "used", B: "free"})
        self.assertEqual({key: record["state"] for key, record in self.ready(blog).items()}, {C: "archived", D: "free"})
        self.assertTrue(self.ready(shop)[A]["shown"])
        self.assertEqual(list(self.mac.store(shop, view_tabs.STATE).load({})), [SHOP_LIVE])
        self.assertEqual(list(self.mac.store(blog, view_tabs.STATE).load({})), [BLOG_LIVE])
        # Copies: the same server session id in two projects gives two copies, one in each.
        self.assertEqual(self.copies(shop), [resume_list.copy_id(shop, SERVER_ID, 1)])
        self.assertEqual(self.copies(blog), [resume_list.copy_id(blog, SERVER_ID, 1)])
        self.assertNotEqual(self.copies(shop), self.copies(blog))
        self.assertEqual(list(self.mac.store(shop, resume_list.STATE).load({})), [SERVER_ID])
        self.assertEqual(
            sorted(path.name for path in (self.root / "state" / "projects").iterdir()), ["blog", "shop"]
        )


class RepeatedLines(Scratch):
    def test_a_folder_that_stays_missing_is_logged_once_and_again_when_something_else_happened(self):
        shop, blog = self.project("shop", make=False), self.project("blog", features=("server",))
        configuration = config.Config("warp", (shop, blog))

        for _ in range(3):
            passes.run(configuration, self.mac)

        self.assertEqual(self.mac.log_text(shop).count("is missing"), 1)

        self.mac.log(shop, "something else")
        self.mac.log(blog, "skipped: the folder %s is missing" % shop.directory)
        passes.run(configuration, self.mac)

        self.assertEqual(self.mac.log_text(shop).count("is missing"), 2, "it is said again once the message changed")
        self.assertEqual(self.mac.log_text(blog).count("is missing"), 1, "each project has its own log")


class TrustQuestion(Scratch):
    def test_the_log_says_once_for_each_session_that_it_waits_for_the_folder_to_be_trusted(self):
        shop = self.project("shop", features=("ready-session",))
        self.ready_session(shop, A, "free", 301)
        self.ready_session(shop, B, "used", 302, prompt="Fix the footer")
        self.ready_session(shop, C, "used", 303, prompt="Fix the header")
        waiting = {"=shop-aaaaaaaa:", "=shop-cccccccc:"}

        def tmux(words):
            if "capture-pane" in words:
                return standins.result(stdout=standins.TRUST_QUESTION if words[-1] in waiting else "> \n")
            return self.tmux(words)

        self.mac.tmux_runner.answers = tmux

        for _ in range(3):
            passes.run(config.Config(None, (shop,)), self.mac)

        said = [line for line in self.mac.log_text(shop).splitlines() if "trust" in line]
        self.assertEqual(len(said), 2, said)
        for line, session in zip(said, ("aaaaaaaa", "cccccccc")):
            self.assertTrue(
                line.endswith(
                    '%s waits for you to trust the folder: answer "Yes, I trust this folder" in that session '
                    "(`porchlight status` prints the command that attaches to it), and run `claude` once in %s "
                    "and trust it so the next sessions do not ask" % (session, names.repository(shop))
                ),
                line,
            )
        self.assertEqual(self.mac.tmux_runner.having("send-keys"), [], "the question is never answered")
        self.assertEqual(self.mac.tmux_runner.having("new-session"), [], "the waiting free session is kept")
        self.assertEqual(self.mac.terminated, [])
        self.assertEqual({key: record["state"] for key, record in self.ready(shop).items()},
                         {A: "free", B: "used", C: "used"})  # fmt: skip


class Status(Scratch):
    def status(self, *projects, terminal="warp"):
        printed = []
        code = passes.status(config.Config(terminal, projects), self.mac, out=printed.append)
        return code, printed

    def test_prints_every_project_under_its_name_and_server_sessions_only_where_the_server_is_on(self):
        shop, blog = self.project("shop"), self.project("blog", features=("ready-session",))
        self.server_session(shop, SHOP_LIVE, 101)
        self.ready_session(blog, A, "used", 301, prompt="Fix the footer")

        code, printed = self.status(shop, blog)

        self.assertEqual(code, 0)
        self.assertEqual(printed[0], "shop")
        self.assertEqual(printed[1], "  Ready sessions, with Claude Code's interface:")
        self.assertEqual(printed[2], "    No session with Claude Code's interface yet.")
        self.assertEqual(printed[3], "  Sessions the server started, with a read-only view:")
        self.assertRegex(printed[4], r"^    cse_01AAA  pid 101 +no tab yet +Shop · Fix the header$")
        self.assertEqual(printed[5:8], ["", "blog", "  Ready sessions, with Claude Code's interface:"])
        self.assertRegex(printed[8], r"^    aaaaaaaa  used .* Fix the footer  \(pid 301, not in the app yet, hidden\)$")
        self.assertEqual(printed[9], "        /tools/tmux -L porchlight-test -u attach-session -t '=blog-aaaaaaaa'")
        self.assertEqual(len(printed), 10, "a project without the server has no server sessions to show")

    def test_a_project_without_ready_sessions_has_no_heading_for_them(self):
        shop = self.project("shop", features=("server",))

        code, printed = self.status(shop)

        self.assertEqual(code, 0)
        self.assertEqual(
            printed,
            ["shop", "  Sessions the server started, with a read-only view:", "    No session the server started is running."],
        )

    def test_a_session_in_use_from_before_ready_sessions_were_turned_off_is_still_shown(self):
        blog = self.project("blog", features=("server",))
        self.ready_session(blog, A, "used", 301, prompt="Fix the footer")

        code, printed = self.status(blog)

        self.assertEqual(code, 0)
        self.assertEqual(printed[1], "  Ready sessions, with Claude Code's interface:")
        self.assertRegex(printed[2], r"^    aaaaaaaa  used .* Fix the footer  \(pid 301, ")

    def test_a_project_with_no_feature_that_starts_sessions_says_so(self):
        quiet = self.project("quiet", features=("keep-awake",))

        code, printed = self.status(quiet)

        self.assertEqual(code, 0)
        self.assertEqual(printed, ["quiet", "  No feature that starts sessions is on."])

    def test_without_a_project_says_so_and_how_to_add_one(self):
        code, printed = self.status()

        self.assertEqual(code, 0)
        self.assertEqual(printed, ["No project is configured. Add one from its folder with: porchlight init"])

    def test_says_when_a_projects_folder_is_missing_and_still_shows_the_next_project(self):
        shop, blog = self.project("shop", make=False), self.project("blog", features=("ready-session",))

        code, printed = self.status(shop, blog)

        self.assertEqual(code, 1, "something needs attention")
        self.assertEqual(printed[1], "  The folder %s is missing." % shop.directory)
        self.assertIn("blog", printed)

    def test_a_project_whose_sessions_cannot_be_read_does_not_hide_the_next(self):
        shop, blog = self.project("shop", features=("ready-session",)), self.project("blog", features=("ready-session",))
        self.ready_session(shop, A, "used", 301)
        del self.mac.tmux  # tmux is not installed: the command that attaches cannot be named
        del self.mac.found["tmux"]

        code, printed = self.status(shop, blog)

        self.assertEqual(code, 1)
        self.assertTrue(any("tmux was not found" in line for line in printed), printed)
        self.assertEqual(printed[-3:], ["blog", "  Ready sessions, with Claude Code's interface:",
                                        "    No session with Claude Code's interface yet."])  # fmt: skip


if __name__ == "__main__":
    unittest.main()
