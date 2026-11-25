"""Tests of what the tabs of server sessions, and the view they run, do on the Mac:
against stand-ins and scratch folders."""

import importlib.util
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from porchlight import config, names
from porchlight.atoms import transcripts
from porchlight.features import live_view, view_tabs
from tests import standins

LIVE = "cse_01AAA"
SERVER_ID = "11111111-1111-5111-8111-111111111111"


def child(pid, session):
    return f"{pid} claude --print --sdk-url wss://example.invalid/x --session-id {session} --output-format stream-json\n"


class OnTheMac(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        (root / "shop").mkdir()
        self.project = standins.project("shop", str(root / "shop"), prefix="Shop")
        self.worktree = names.repository(self.project) / ".claude" / "worktrees" / ("bridge-" + LIVE)
        self.worktree.mkdir(parents=True)
        self.terminal = standins.Terminal()
        self.mac = standins.StandInMac(root, self.terminal, ps=child(101, LIVE))
        self.mac.now = time.time() + 3600  # the worktree is an hour old
        self.printed = []

    def tearDown(self):
        self.scratch.cleanup()

    def write_transcript(self, *entries, unfinished=""):
        folder = self.mac.transcripts / transcripts.folder_name(str(self.worktree))
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (SERVER_ID + ".jsonl")
        path.write_text("".join(json.dumps(entry) + "\n" for entry in entries) + unfinished, encoding="utf8")
        return path

    def saved(self):
        return self.mac.store(self.project, view_tabs.STATE).load({})

    def view_starts(self, tab):
        self.mac.ps += "401 " + tab.command[len("exec ") :] + "\n"


class Command(OnTheMac):
    def test_the_tab_runs_the_view_with_the_interpreter_that_runs_the_tool(self):
        command = live_view.command(self.project, LIVE, self.mac.python)

        self.assertEqual(command, "exec /tools/python3 -m porchlight.features.live_view shop cse_01AAA")
        self.assertIsNotNone(importlib.util.find_spec(live_view.MODULE))

    def test_the_process_list_recognizes_the_view_it_starts(self):
        command = live_view.command(self.project, LIVE, "/some where/Python")

        self.assertEqual(view_tabs.views("401 " + command[len("exec ") :].replace("'", "") + "\n"), {LIVE})


class OpenTab(OnTheMac):
    def test_opens_a_tab_named_for_the_project_that_runs_the_view(self):
        self.write_transcript({"type": "queue-operation", "content": "Fix the header"})
        self.terminal.on_open = self.view_starts

        self.assertTrue(view_tabs.open_tab(self.project, LIVE, self.mac))

        (tab,) = self.terminal.tabs
        self.assertEqual(tab.name, "porchlight_view_shop-01AAA")
        self.assertEqual(tab.title, "Shop · Fix the header")
        self.assertEqual(tab.command, live_view.command(self.project, LIVE, "/tools/python3"))
        self.assertEqual(tab.directory, str(Path.home()))
        self.assertEqual((tab.attempts, tab.patience), (2, 8))

    def test_says_when_the_view_did_not_start_or_the_tab_could_not_be_asked_for(self):
        self.assertFalse(view_tabs.open_tab(self.project, LIVE, self.mac, wait=0))
        self.assertIn("no tab opened for cse_01AAA", self.mac.log_text(self.project))

        self.terminal.error = OSError("no such folder")
        self.assertFalse(view_tabs.open_tab(self.project, LIVE, self.mac, wait=0))
        self.assertIn("failed to open a tab for cse_01AAA", self.mac.log_text(self.project))

    def test_waits_a_little_for_a_new_session_to_have_its_first_prompt(self):
        before = self.mac.now

        self.assertEqual(view_tabs.first_prompt(self.project, LIVE, self.mac), "")

        self.assertGreaterEqual(self.mac.now - before, 8)
        self.write_transcript({"type": "user"}, {"type": "queue-operation", "content": "Fix the header"})
        self.assertEqual(view_tabs.first_prompt(self.project, LIVE, self.mac), "Fix the header")


class Reconcile(OnTheMac):
    def test_opens_the_tab_of_a_live_session_once_and_keeps_that_in_the_projects_state(self):
        self.terminal.on_open = self.view_starts

        view_tabs.reconcile(self.project, self.mac, wait=0)
        view_tabs.reconcile(self.project, self.mac, wait=0)

        self.assertEqual(len(self.terminal.tabs), 1)
        self.assertEqual(self.saved(), {LIVE: {"opened": True, "attempts": 1}})
        self.assertTrue((Path(self.scratch.name) / "state" / "projects" / "shop" / "view-tabs.json").is_file())

    def test_a_tab_the_user_closed_is_not_opened_again(self):
        self.mac.store(self.project, view_tabs.STATE).save({LIVE: {"opened": True, "attempts": 1}})

        view_tabs.reconcile(self.project, self.mac, wait=0)

        self.assertEqual(self.terminal.tabs, [])

    def test_never_starts_the_terminal_the_tab_opens_at_a_later_pass(self):
        self.terminal.running = False
        self.mac.store(self.project, view_tabs.STATE).save({"cse_01GONE": {"opened": True, "attempts": 1}})

        view_tabs.reconcile(self.project, self.mac, wait=0)

        self.assertEqual(self.terminal.tabs, [])
        self.assertEqual(self.saved(), {}, "only a session that ended is forgotten")

        self.terminal.running = True
        view_tabs.reconcile(self.project, self.mac, wait=0)
        self.assertEqual(len(self.terminal.tabs), 1)

    def test_without_a_terminal_set_up_no_tab_is_asked_for(self):
        mac = standins.StandInMac(self.scratch.name, terminal=None, ps=child(101, LIVE))
        mac.now = self.mac.now

        view_tabs.reconcile(self.project, mac, wait=0)

        self.assertEqual(mac.store(self.project, view_tabs.STATE).load({}), {})

    def test_without_live_view_a_server_session_gets_no_tab_and_nothing_is_kept(self):
        features = ("server", "ready-session", "tabs")
        project = standins.project("shop", self.project.path, prefix="Shop", features=features)
        self.terminal.on_open = self.view_starts

        view_tabs.reconcile(project, self.mac, wait=0)

        self.assertEqual((self.terminal.tabs, self.terminal.asked), ([], 0))
        self.assertFalse((Path(self.scratch.name) / "state").exists())

    def test_another_projects_session_gets_no_tab_here(self):
        (Path(self.scratch.name) / "blog").mkdir()
        blog = standins.project("blog", str(Path(self.scratch.name) / "blog"))

        view_tabs.reconcile(blog, self.mac, wait=0)

        self.assertEqual(self.terminal.tabs, [])

    def test_waits_for_a_session_whose_worktree_was_just_made(self):
        self.mac.now = time.time()
        self.mac.ps = ""

        self.assertTrue(view_tabs.starting(self.project, {}, self.mac))
        self.assertFalse(view_tabs.starting(self.project, {LIVE: 101}, self.mac), "its process is up")
        before = self.mac.now
        view_tabs.reconcile(self.project, self.mac, wait=0)

        self.assertGreater(self.mac.now - before, 45, "it stops waiting after a while")


class Status(OnTheMac):
    def test_prints_each_live_session_with_its_tab(self):
        self.write_transcript({"type": "queue-operation", "content": "Fix the header"})

        view_tabs.status(self.project, self.mac, out=self.printed.append)
        self.mac.store(self.project, view_tabs.STATE).save({LIVE: {"opened": True, "attempts": 1}})
        view_tabs.status(self.project, self.mac, out=self.printed.append)
        self.mac.ps += "401 /tools/python3 -m porchlight.features.live_view shop cse_01AAA\n"
        view_tabs.status(self.project, self.mac, out=self.printed.append)

        self.assertRegex(self.printed[0], r"^cse_01AAA  pid 101 +no tab yet +Shop · Fix the header$")
        self.assertIn("tab closed by the user", self.printed[1])
        self.assertIn("tab open", self.printed[2])

    def test_says_when_no_server_session_runs(self):
        self.mac.ps = ""

        view_tabs.status(self.project, self.mac, out=self.printed.append)

        self.assertEqual(self.printed, ["No session the server started is running."])


class Follow(OnTheMac):
    def follow(self):
        screen = live_view.Screen(out=self.printed.append, width=lambda: 80)
        return live_view.follow(self.project, LIVE, self.mac, screen)

    def shown(self):
        return [line for line in (live_view.plain(text) for text in self.printed) if line]

    def test_says_when_the_session_does_not_run_here(self):
        self.mac.ps = ""

        self.assertEqual(self.follow(), 1)

        self.assertEqual(self.shown(), ["Session cse_01AAA is not running on this Mac."])

    def test_shows_the_conversation_and_closes_once_the_session_ended(self):
        self.write_transcript(
            {"type": "user", "message": {"content": "Fix the header"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "On it."}]}},
            unfinished='{"type":"assistant","message":{"content":"half a li',
        )
        # The process ended: ps shows nothing for its pid.

        self.assertEqual(self.follow(), 0)

        self.assertEqual(
            self.shown(),
            [
                "cse_01AAA · read-only view · type from the phone · closes when archived",
                "▌ Fix the header",
                "On it.",
                "The session ended (archived). Closing this tab.",
            ],
        )

    def test_stays_open_while_ps_cannot_tell(self):
        self.mac.commands[101] = None

        self.assertTrue(live_view.running(101, LIVE, self.mac))
        self.mac.commands[101] = "claude --print --session-id cse_01AAA --sdk-url x"
        self.assertTrue(live_view.running(101, LIVE, self.mac))
        self.mac.commands[101] = "claude --print --session-id cse_01AAAB"
        self.assertFalse(live_view.running(101, LIVE, self.mac), "the pid belongs to something else now")

    def test_shows_only_the_latest_items_of_a_long_conversation(self):
        self.write_transcript(*[{"type": "user", "message": {"content": "prompt %d" % n}} for n in range(40)])

        self.follow()

        shown = self.shown()
        self.assertEqual(shown[1], "… 10 earlier items not shown")
        self.assertEqual(shown[2], "▌ prompt 10")


class Main(OnTheMac):
    def main(self, *arguments, configuration=None):
        errors = io.StringIO()
        with redirect_stderr(errors):
            code = live_view.main(list(arguments), configuration, self.mac)
        return code, errors.getvalue()

    def test_rejects_anything_but_a_project_and_a_server_session(self):
        configuration = config.Config("warp", (self.project,))

        for arguments in ((), ("shop",), ("shop", "not-a-session"), ("shop", LIVE, "more")):
            code, errors = self.main(*arguments, configuration=configuration)
            self.assertEqual(code, 2)
            self.assertIn("usage", errors)

    def test_rejects_a_project_the_configuration_does_not_have(self):
        code, errors = self.main("blog", LIVE, configuration=config.Config("warp", (self.project,)))

        self.assertEqual(code, 2)
        self.assertIn('no project "blog"', errors)


if __name__ == "__main__":
    unittest.main()
