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
from porchlight.features import live_view, ready_sessions, resume_list, view_tabs
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
        if live_view.MODULE in tab.command:
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


if __name__ == "__main__":
    unittest.main()
