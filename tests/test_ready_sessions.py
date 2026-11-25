"""Tests of the ready sessions' decisions. They start no session, open no tab and touch no
repository: the process list, the transcripts and the state are stand-ins."""

import shlex
import unittest
from pathlib import Path

from porchlight.features import ready_sessions
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
STARTED = 1_000_000.0
ENDED_ELSEWHERE = (
    "Remote Control disconnected — this session was ended or archived from another "
    "device or app (code 4090)"
)
SHOP = standins.project("shop", "/srv/shop", mode="plan", prefix="Shop")
CLAUDE = "/tools/claude"
SETTINGS = "/state/projects/shop/settings.json"


def known(state, **extra):
    record = {
        "state": state,
        "started": STARTED,
        "changed": STARTED,
        "worktree": "/repo/.claude/worktrees/porchlight-shop-x",
        "branch": "porchlight-shop-x",
        "prompt": "",
        "title": "",
        "cse": "",
        "tidied": False,
    }
    record.update(extra)
    return record


def summary(**extra):
    return dict(ready_sessions.new_summary(), **extra)


def tmux():
    return standins.tmux.Tmux("/tools/tmux", standins.TMUX_SERVER, "/package/tmux.conf", "/usr/bin", environ={})


class Running(unittest.TestCase):
    def test_finds_the_sessions_with_remote_control_by_their_id(self):
        ps = (
            f"301 claude --session-id {A} --permission-mode plan --settings /x/settings.json "
            "--append-system-prompt some words here --remote-control-session-name-prefix Shop --remote-control\n"
            f"302 /usr/local/bin/claude --resume {B} --permission-mode plan --remote-control\n"
            f"303 claude --resume {C}\n"  # a terminal session without Remote Control
            f"304 /bin/zsh -c claude --session-id {D} --remote-control\n"
            "305 claude --print --sdk-url wss://example.invalid --session-id cse_01AAA --resume=https://example.invalid\n"
            "306 claude --remote-control Trial\n"  # started by hand: no id to follow
            f"307 claude --session-id {D} --remote-control-session-name-prefix Shop\n"
            # What runs a hidden session: the tmux server and the shell that starts Claude Code.
            f"308 tmux -L porchlight new-session -d -s shop-dddddddd /bin/zsh -lic exec claude --session-id {D} --remote-control\n"
            f"309 /bin/zsh -lic exec /usr/local/bin/claude --session-id {D} --remote-control\n"
        )

        self.assertEqual(ready_sessions.running(ps), {A: 301, B: 302})


class Summarize(unittest.TestCase):
    def test_reads_the_first_prompt_the_title_and_the_phone_session(self):
        entries = [
            {"type": "bridge-session", "bridgeSessionId": "cse_01OLD", "lastSequenceNum": 0},
            {"type": "user", "isMeta": True, "message": {"content": "hidden"}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": []}]}},
            {"type": "user", "message": {"content": "Fix the\nheader"}},
            {"type": "user", "message": {"content": "And the footer"}},
            {"type": "ai-title", "aiTitle": "Header fix"},
            {"type": "custom-title", "customTitle": "Header  on phones"},
            {"type": "bridge-session", "bridgeSessionId": "cse_01NEW", "lastSequenceNum": 26},
        ]

        self.assertEqual(
            ready_sessions.summarize(entries),
            {"prompt": "Fix the header", "title": "Header on phones", "cse": "cse_01NEW", "ended_at": 0.0},
        )

    def test_reads_when_the_phone_archived_the_session(self):
        entries = [
            {"type": "system", "subtype": "informational", "content": ENDED_ELSEWHERE,
             "timestamp": "2026-11-24T22:15:47.712Z"},
            {"type": "system", "subtype": "informational", "content": ENDED_ELSEWHERE,
             "timestamp": "2026-11-24T22:23:14.266Z"},
            # Other ways Remote Control ends are not an archive.
            {"type": "system", "subtype": "informational", "content": "Remote Control disconnected.",
             "timestamp": "2026-11-24T23:00:00.000Z"},
            {"type": "system", "subtype": "bridge_status", "content": "/remote-control is active",
             "timestamp": "2026-11-24T23:30:00.000Z"},
        ]  # fmt: skip

        self.assertEqual(ready_sessions.summarize(entries)["ended_at"], 1795558994.0)

    def test_an_empty_transcript_is_a_session_nobody_used(self):
        self.assertEqual(ready_sessions.summarize([]), ready_sessions.new_summary())


class Plan(unittest.TestCase):
    def plan(self, sessions, live, summaries=None, create=True, now=STARTED + 10, tabs=True, ready=True):
        return ready_sessions.plan(sessions, live, summaries or {}, create, now, tabs, ready)

    def test_a_hidden_free_session_waits_without_a_tab(self):
        sessions = {A: known("free", shown=False, tmux="shop-aaaaaaaa")}

        self.assertEqual(self.plan(sessions, {A: 301}, {A: summary()}), (sessions, []))

    def test_a_hidden_session_gets_its_tab_once_it_is_used(self):
        sessions = {A: known("free", shown=False, tmux="shop-aaaaaaaa")}

        new, actions = self.plan(sessions, {A: 301}, {A: summary(prompt="Fix the header")})

        self.assertEqual(new[A]["state"], "used")
        self.assertEqual(actions, [("show", A), ("create",)])

    def test_asks_for_the_tab_until_it_is_shown_and_only_while_tabs_can_open(self):
        waiting = {A: known("used", shown=False, tmux="shop-aaaaaaaa"), B: known("free", shown=False)}
        shown = {A: known("used", shown=True, tmux="shop-aaaaaaaa"), B: known("free", shown=False)}

        self.assertEqual(self.plan(waiting, {A: 301, B: 302})[1], [("show", A)])
        self.assertEqual(self.plan(waiting, {A: 301, B: 302}, tabs=False)[1], [])
        self.assertEqual(self.plan(shown, {A: 301, B: 302})[1], [])

    def test_an_archived_hidden_session_is_stopped_and_gets_no_tab(self):
        sessions = {A: known("used", shown=False, tmux="shop-aaaaaaaa"), B: known("free", shown=False)}

        _, actions = self.plan(sessions, {A: 301, B: 302}, {A: summary(ended_at=STARTED + 5)})

        self.assertEqual(actions, [("stop", A)])

    def test_asks_for_a_free_session_when_there_is_none(self):
        self.assertEqual(self.plan({}, {}), ({}, [("create",)]))

    def test_leaves_a_free_session_that_waits(self):
        sessions = {A: known("free")}

        self.assertEqual(self.plan(sessions, {A: 301}, {A: summary()}), (sessions, []))

    def test_a_free_session_that_got_a_prompt_is_used_and_another_is_prepared(self):
        new, actions = self.plan({A: known("free")}, {A: 301}, {A: summary(prompt="Fix the header", cse="cse_01A")})

        self.assertEqual(new[A]["state"], "used")
        self.assertEqual(new[A]["prompt"], "Fix the header")
        self.assertEqual(new[A]["cse"], "cse_01A")
        self.assertEqual(actions, [("create",)])

    def test_prepares_no_free_session_when_told_not_to(self):
        _, actions = self.plan({A: known("used")}, {A: 301}, create=False)

        self.assertEqual(actions, [])

    def test_stops_a_session_the_phone_archived(self):
        sessions = {A: known("used"), B: known("free")}

        new, actions = self.plan(sessions, {A: 301, B: 302}, {A: summary(ended_at=STARTED + 5)})

        self.assertEqual(new[A]["state"], "archived")
        self.assertEqual(actions, [("stop", A)])

    def test_keeps_a_session_that_was_reopened_after_its_archive(self):
        sessions = {A: known("used"), B: known("free")}

        new, actions = self.plan(sessions, {A: 301, B: 302}, {A: summary(ended_at=STARTED - 60)})

        self.assertEqual(new[A]["state"], "used")
        self.assertEqual(actions, [])

    def test_tidies_an_archived_session_once_its_process_ended(self):
        sessions = {A: known("archived"), B: known("free")}

        new, actions = self.plan(sessions, {B: 302})
        self.assertEqual(actions, [("tidy", A)])
        self.assertTrue(new[A]["tidied"])

        _, actions = self.plan(new, {B: 302})
        self.assertEqual(actions, [], "tidied once")

    def test_a_used_session_whose_tab_was_closed_stays_closed_and_can_be_reopened(self):
        sessions = {A: known("used", prompt="Fix the header"), B: known("free")}

        new, actions = self.plan(sessions, {B: 302})

        self.assertEqual(new[A]["state"], "closed")
        self.assertEqual(actions, [("tidy", A)], "it is not opened again by itself")

    def test_discards_a_free_session_whose_tab_was_closed_and_prepares_another(self):
        free = known("free")

        new, actions = self.plan({A: free}, {})

        self.assertEqual(new, {})
        self.assertEqual(actions, [("discard", free), ("create",)])

    def test_forgets_a_closed_session_after_thirty_days(self):
        sessions = {A: known("archived", tidied=True), B: known("free")}

        new, _ = self.plan(sessions, {B: 302}, now=STARTED + 31 * 86400)

        self.assertEqual(list(new), [B])

    def test_with_ready_sessions_off_none_is_prepared(self):
        self.assertEqual(self.plan({}, {}, ready=False), ({}, []))

    def test_with_ready_sessions_off_a_free_session_is_ended_and_stays_known_until_it_ended(self):
        sessions = {A: known("free", shown=False, tmux="shop-aaaaaaaa")}

        self.assertEqual(self.plan(sessions, {A: 301}, {A: summary()}, ready=False), (sessions, [("release", A)]))

    def test_with_ready_sessions_off_a_free_session_that_ended_is_discarded_like_any_other(self):
        free = known("free")

        self.assertEqual(self.plan({A: free}, {}, ready=False), ({}, [("discard", free)]))

    def test_with_ready_sessions_off_a_session_in_use_is_followed_until_it_ends(self):
        sessions = {A: known("used", prompt="Fix the header")}

        self.assertEqual(self.plan(sessions, {A: 301}, ready=False), (sessions, []), "it is not ended")

        archived, actions = self.plan(sessions, {A: 301}, {A: summary(ended_at=STARTED + 5)}, ready=False)
        self.assertEqual((archived[A]["state"], actions), ("archived", [("stop", A)]))

        _, actions = self.plan(archived, {}, ready=False)
        self.assertEqual(actions, [("tidy", A)])

    def test_with_ready_sessions_off_a_free_session_someone_just_wrote_in_is_in_use(self):
        new, actions = self.plan({A: known("free")}, {A: 301}, {A: summary(prompt="Fix the header")}, ready=False)

        self.assertEqual((new[A]["state"], actions), ("used", []))


class Match(unittest.TestCase):
    sessions = {
        A: known("archived", title="Header on phones", prompt="Fix the header"),
        B: known("closed", prompt="Review the footer copy", cse="cse_01BBB"),
        C: known("used", prompt="Fix the header too"),
        D: known("free"),
    }

    def test_finds_a_closed_session_by_title_prompt_or_id(self):
        self.assertEqual(ready_sessions.match(self.sessions, "header on PHONES"), [A])
        self.assertEqual(ready_sessions.match(self.sessions, "footer"), [B])
        self.assertEqual(ready_sessions.match(self.sessions, "bbbbbbbb"), [B])
        self.assertEqual(ready_sessions.match(self.sessions, "cse_01BBB"), [B])

    def test_never_offers_a_session_that_is_open(self):
        self.assertEqual(ready_sessions.match(self.sessions, "fix the header"), [A])
        self.assertEqual(ready_sessions.match(self.sessions, ""), [A, B])
        self.assertEqual(ready_sessions.match(self.sessions, "nothing like it"), [])


class CommandLine(unittest.TestCase):
    def test_a_new_session_has_its_id_no_name_and_remote_control(self):
        command = ready_sessions.command_line(SHOP, A, False, CLAUDE, SETTINGS)

        self.assertTrue(command.startswith("exec "))
        self.assertIn(f" --session-id {A} ", command)
        self.assertIn(" --permission-mode plan ", command)
        self.assertIn(" --remote-control-session-name-prefix Shop ", command)
        self.assertTrue(command.endswith(" --remote-control"), "a word after it would be taken as a name")
        self.assertNotIn("--resume", command)

    def test_a_reopened_session_resumes_the_same_conversation(self):
        command = ready_sessions.command_line(SHOP, A, True, CLAUDE, SETTINGS)

        self.assertIn(f" --resume {A} ", command)
        self.assertNotIn("--session-id", command)
        self.assertTrue(command.endswith(" --remote-control"))

    def test_a_hidden_session_starts_detached_in_its_worktree_from_a_login_shell(self):
        worktree = "/srv/shop/.claude/worktrees/porchlight-shop-aaaaaaaa"

        words = ready_sessions.hidden_start(SHOP, A, worktree, tmux(), CLAUDE, SETTINGS)

        self.assertEqual(Path(words[0]).name, "tmux")
        self.assertEqual(words[words.index("-L") + 1], standins.TMUX_SERVER, "its own server, not the user's tmux")
        self.assertIn("-d", words)
        self.assertEqual(words[words.index("-s") + 1], "shop-aaaaaaaa")
        self.assertEqual(words[words.index("-c") + 1], worktree)
        shell = shlex.split(words[-1])
        self.assertEqual(shell[:2], ["/bin/zsh", "-lic"])
        self.assertEqual(shell[2], ready_sessions.command_line(SHOP, A, False, CLAUDE, SETTINGS))

    def test_the_tab_of_a_hidden_session_attaches_to_exactly_that_session(self):
        self.assertEqual(
            tmux().attach_command("shop-aaaaaaaa"),
            "exec /tools/tmux -L porchlight-test -u attach-session -t '=shop-aaaaaaaa'",
            "quoted: zsh takes a word that starts with = for a command to look up",
        )

    def test_the_process_list_recognizes_what_it_starts(self):
        for resume in (False, True):
            words = ready_sessions.command_line(SHOP, A, resume, CLAUDE, SETTINGS)[len("exec ") :].replace("'", "")
            self.assertEqual(ready_sessions.running(f"401 {words}\n"), {A: 401})


if __name__ == "__main__":
    unittest.main()
