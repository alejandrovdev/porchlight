"""Tests of the tabs of server sessions and of the read-only view they run. They open no
tab and read no real Claude Code folder: the process list, the folders and the tab opener
are stand-ins."""

import tempfile
import unittest
from pathlib import Path

from porchlight import names
from porchlight.atoms import terminal, transcripts
from porchlight.features import live_view, view_tabs
from tests import standins

CLAUDE = "/usr/local/Caskroom/claude-code/2.1.325/claude"
LIVE = "cse_01AAA"
OTHER = "cse_01BBB"
SHOP = standins.project("shop", "/srv/shop", prefix="Shop")


def child(pid, session):
    return (
        f"{pid} {CLAUDE} --print --sdk-url wss://example.invalid/x --session-id {session} "
        "--input-format stream-json --output-format stream-json\n"
    )


class LiveSessions(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.worktrees = Path(self.scratch.name)
        (self.worktrees / f"bridge-{LIVE}").mkdir()

    def tearDown(self):
        self.scratch.cleanup()

    def test_finds_the_server_sessions_that_have_a_worktree_here(self):
        ps = (
            child(101, LIVE)
            + child(102, OTHER)  # another repository's server: no worktree here
            + "103 /bin/zsh -c echo claude --print --sdk-url x --session-id cse_01CCC \n"
            + f"104 {CLAUDE} --resume\n"
        )

        self.assertEqual(live_view.live_sessions(ps, self.worktrees), {LIVE: 101})

    def test_counts_agents_only_never_what_an_agent_starts(self):
        worktree = self.worktrees / f"bridge-{LIVE}"
        ps = (
            child(101, LIVE)
            # Runs a server session starts from its own worktree: a reviewer or a
            # subagent run as `claude -p`, a background session and its worker.
            + f"105 {CLAUDE} -p --output-format json --add-dir {worktree} Review the diff\n"
            + f"106 {CLAUDE} --print --model some-model --session-id 33333333-3333-4333-8333-333333333333\n"
            + f"107 {CLAUDE} --bg --name bridge-{LIVE} Check the tests\n"
            + f"108 {CLAUDE} daemon-worker --session-id {LIVE}\n"
        )

        self.assertEqual(live_view.live_sessions(ps, self.worktrees), {LIVE: 101})

    def test_finds_the_sessions_that_already_have_a_view(self):
        ps = (
            f"201 /usr/bin/python3 -m porchlight view shop {LIVE}\n"
            f"202 /bin/zsh -c grep porchlight view shop {OTHER} somewhere\n"
            "203 /usr/bin/python3 -m porchlight view\n"
            f"204 /usr/bin/python3 -m porchlight status shop {OTHER}\n"
            f"205 /usr/bin/python3 -m another view shop {OTHER}\n"
        )

        self.assertEqual(view_tabs.views(ps), {LIVE})

    def test_finds_a_view_the_installed_command_runs(self):
        ps = (
            f"201 /opt/homebrew/bin/porchlight view shop {LIVE}\n"
            f"202 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/porchlight view blog {OTHER}\n"
            "203 /opt/homebrew/bin/porchlight status\n"
        )

        self.assertEqual(view_tabs.views(ps), {LIVE, OTHER})


class Transcript(unittest.TestCase):
    def test_picks_the_server_session_and_not_a_run_it_started_in_its_worktree(self):
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / "repo").mkdir()
            project = standins.project("shop", str(Path(scratch) / "repo"))
            mac = standins.StandInMac(scratch)
            worktrees = names.repository(project) / ".claude" / "worktrees"
            folder = mac.transcripts / transcripts.folder_name(str(worktrees / f"bridge-{LIVE}"))
            folder.mkdir(parents=True)
            server = folder / "11111111-1111-5111-8111-111111111111.jsonl"
            server.write_text("{}\n")
            child_run = folder / "33333333-3333-4333-8333-333333333333.jsonl"
            child_run.write_text("{}\n")  # written later: the newest file in the folder

            self.assertEqual(live_view.transcript(project, LIVE, mac), server)
            self.assertIsNone(live_view.transcript(project, OTHER, mac))


class Step(unittest.TestCase):
    def setUp(self):
        self.opened = []

    def opener(self, works=True):
        def open_tab(session):
            self.opened.append(session)
            return works

        return open_tab

    def test_opens_one_tab_for_a_live_session_and_remembers_it(self):
        state = view_tabs.step({LIVE: 101}, set(), {}, self.opener())

        self.assertEqual(self.opened, [LIVE])
        self.assertTrue(state[LIVE]["opened"])

        state = view_tabs.step({LIVE: 101}, {LIVE}, state, self.opener())
        self.assertEqual(self.opened, [LIVE], "a session with a view gets no second tab")

    def test_does_not_reopen_a_tab_the_user_closed(self):
        state = view_tabs.step({LIVE: 101}, set(), {}, self.opener())

        view_tabs.step({LIVE: 101}, set(), state, self.opener())

        self.assertEqual(self.opened, [LIVE])

    def test_adopts_a_view_that_is_already_running(self):
        state = view_tabs.step({LIVE: 101}, {LIVE}, {}, self.opener())

        self.assertEqual(self.opened, [])
        self.assertTrue(state[LIVE]["opened"])

    def test_forgets_a_session_once_it_is_archived(self):
        state = view_tabs.step({LIVE: 101}, set(), {}, self.opener())

        state = view_tabs.step({}, set(), state, self.opener())

        self.assertEqual(state, {})

    def test_gives_up_after_three_tabs_that_did_not_open(self):
        state = {}
        for _ in range(5):
            state = view_tabs.step({LIVE: 101}, set(), state, self.opener(works=False))

        self.assertEqual(self.opened, [LIVE] * 3)
        self.assertFalse(state[LIVE]["opened"])


class TabConfig(unittest.TestCase):
    def test_writes_a_tab_that_runs_only_the_view(self):
        text = terminal.tab_config("porchlight_view_shop-01AAA", 'Shop · say "hi" \\ now', "/tmp", "exec view")

        self.assertIn('name = "porchlight_view_shop-01AAA"\n', text)
        self.assertIn('title = "Shop · say \\"hi\\" \\\\ now"\n', text)
        self.assertIn('directory = "/tmp"\n', text)
        self.assertIn('commands = ["exec view"]\n', text)
        self.assertNotIn("[params", text, "a parameter would open a dialog")

    def test_names_the_tab_after_the_first_prompt(self):
        long_prompt = "Fix the header on phones and then check every page " * 3

        self.assertEqual(view_tabs.tab_title(SHOP, "Fix the\nheader", LIVE), "Shop · Fix the header")
        self.assertLessEqual(len(view_tabs.tab_title(SHOP, long_prompt, LIVE)), len("Shop · ") + 40)
        self.assertEqual(view_tabs.tab_title(SHOP, "", "cse_01ABCDEFGHJKMNPQRSTVWXYZ"), "Shop · TVWXYZ")
        self.assertEqual(view_tabs.tab_title(SHOP, "Fix \x1b]0;x\x07 the café 😀\ud83d", LIVE), "Shop · Fix \ufffd]0;x\ufffd the café 😀")


def message(kind, content, **extra):
    return dict({"type": kind, "message": {"content": content}}, **extra)


class Render(unittest.TestCase):
    def test_shows_what_the_user_wrote(self):
        self.assertEqual(live_view.render(message("user", "Fix the header")), [("user", "Fix the header")])
        self.assertEqual(
            live_view.render(message("user", [{"type": "text", "text": "And the footer"}])),
            [("user", "And the footer")],
        )

    def test_shows_what_claude_said_and_one_line_per_tool_call(self):
        entry = message(
            "assistant",
            [
                {"type": "thinking", "thinking": ""},
                {"type": "text", "text": "I will run the tests."},
                {
                    "type": "tool_use",
                    "name": "Bash",
                    "input": {"command": "make test | tail -40", "description": "Run the tests"},
                },
                {"type": "tool_use", "name": "Edit", "input": {"file_path": "/repo/site/page.html"}},
                {"type": "tool_use", "name": "ToolSearch", "input": {"query": "x" * 300, "max_results": 5}},
            ],
        )

        rendered = live_view.render(entry)

        self.assertEqual(rendered[0], ("assistant", "I will run the tests."))
        self.assertEqual(rendered[1], ("tool", "Bash · Run the tests"))
        self.assertEqual(rendered[2], ("tool", "Edit · /repo/site/page.html"))
        self.assertTrue(rendered[3][1].startswith("ToolSearch · xxx"))
        self.assertLessEqual(len(rendered[3][1]), 120)

    def test_leaves_out_what_is_not_conversation(self):
        tool_result = message("user", [{"type": "tool_result", "tool_use_id": "t", "content": []}])
        notification = message("user", "<task-notification>\n<task-id>a</task-id>")
        reminder = message("user", [{"type": "text", "text": "<system-reminder>x</system-reminder>"}])

        self.assertEqual(live_view.render(tool_result), [])
        self.assertEqual(live_view.render(notification), [])
        self.assertEqual(live_view.render(reminder), [])
        self.assertEqual(live_view.render(message("user", "hidden", isMeta=True)), [])
        self.assertEqual(
            live_view.render(message("assistant", [{"type": "text", "text": "sub"}], isSidechain=True)), []
        )
        self.assertEqual(live_view.render({"type": "attachment"}), [])
        self.assertEqual(live_view.render({"type": "user"}), [])

    def test_reads_only_finished_lines(self):
        lines, rest = transcripts.finished_lines(b'{"a":1}\n{"b":2}\n{"c":')

        self.assertEqual(lines, [b'{"a":1}', b'{"b":2}'])
        self.assertEqual(rest, b'{"c":')


if __name__ == "__main__":
    unittest.main()
