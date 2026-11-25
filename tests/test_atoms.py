"""Tests of the atoms: the process list, transcripts, git worktrees, tmux, the terminal's
tab opener and the state file. Each runs against scratch folders and stand-ins."""

import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from porchlight import config
from porchlight.atoms import logs, processes, state, terminal, tmux, transcripts, worktrees
from tests import standins


class Processes(unittest.TestCase):
    def test_reads_the_pid_the_program_and_its_arguments(self):
        ps = "  301 /bin/claude --resume x\n302 tmux\nnot a process line\n\n"

        self.assertEqual(
            list(processes.rows(ps)), [(301, "/bin/claude", ["--resume", "x"]), (302, "tmux", [])]
        )

    def test_asks_ps_for_every_process_with_its_command(self):
        runner = standins.Runner(lambda words: standins.result(stdout="1 launchd\n"))

        self.assertEqual(processes.listing(run=runner), "1 launchd\n")
        self.assertEqual(runner.calls, [["/bin/ps", "-axo", "pid=,command="]])

    def test_cannot_tell_the_command_of_a_process_when_ps_fails(self):
        failing = standins.Runner(lambda words: subprocess.TimeoutExpired(words, 10))

        self.assertIsNone(processes.command_of(301, run=failing))
        self.assertEqual(
            processes.command_of(301, run=standins.Runner(lambda words: standins.result(stdout="claude x\n"))),
            "claude x\n",
        )


class Transcripts(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.folder = Path(self.scratch.name)

    def tearDown(self):
        self.scratch.cleanup()

    def test_names_a_folder_as_claude_code_does(self):
        self.assertEqual(transcripts.folder_name("/srv/my shop/.claude/x_1"), "-srv-my-shop--claude-x-1")

    def test_reads_only_the_finished_lines_written_since_the_last_read(self):
        path = self.folder / "session.jsonl"
        path.write_bytes(b'{"a":1}\nnot json\n[1]\n{"b":')

        entries, offset = transcripts.read_new(path, 0)
        self.assertEqual(entries, [{"a": 1}])

        path.write_bytes(b'{"a":1}\nnot json\n[1]\n{"b":2}\n')
        self.assertEqual(transcripts.read_new(path, offset), ([{"b": 2}], path.stat().st_size))

    def test_starts_over_when_the_transcript_became_shorter(self):
        path = self.folder / "session.jsonl"
        path.write_bytes(b'{"a":1}\n')

        self.assertEqual(transcripts.read_new(path, 500), ([{"a": 1}], 8))

    def test_a_transcript_that_is_not_there_yet_reads_as_nothing(self):
        self.assertEqual(transcripts.read_new(self.folder / "absent.jsonl", 7), ([], 7))


class Worktrees(unittest.TestCase):
    def test_reads_the_default_branch_of_the_repository_from_git(self):
        runner = standins.Runner(
            lambda words: standins.result(stdout="origin/trunk\n") if "symbolic-ref" in words else None
        )
        git = worktrees.Git("/tools/git", run=runner)

        self.assertEqual(worktrees.default_base(git, "/srv/shop"), "origin/trunk")
        self.assertEqual(
            runner.calls,
            [["/tools/git", "-C", "/srv/shop", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]],
        )

    def test_knows_no_default_branch_when_git_states_none(self):
        git = worktrees.Git("/tools/git", run=standins.Runner(lambda words: standins.result(returncode=1)))

        self.assertIsNone(worktrees.default_base(git, "/srv/shop"))

    def test_tells_whether_the_repository_has_a_remote(self):
        runner = standins.Runner()
        without = standins.Runner(lambda words: standins.result(returncode=2, stderr="error: No such remote 'origin'"))

        self.assertTrue(worktrees.has_remote(worktrees.Git("/tools/git", run=runner), "/srv/shop", "origin"))
        self.assertFalse(worktrees.has_remote(worktrees.Git("/tools/git", run=without), "/srv/shop", "origin"))
        self.assertEqual(runner.calls, [["/tools/git", "-C", "/srv/shop", "remote", "get-url", "origin"]])

    def test_keeps_its_worktrees_where_claude_code_keeps_a_repositorys(self):
        self.assertEqual(worktrees.folder("/srv/shop"), Path("/srv/shop/.claude/worktrees"))
        self.assertEqual(
            worktrees.of_server_session("/srv/shop", "cse_01AAA"), Path("/srv/shop/.claude/worktrees/bridge-cse_01AAA")
        )

    def test_a_worktree_is_added_locked_with_the_reason_given(self):
        runner = standins.Runner()
        git = worktrees.Git("/tools/git", run=runner)

        worktrees.add(git, "/srv/shop", "/srv/shop/w", "a reason", "origin/trunk", "-b", "new-branch")

        self.assertEqual(
            runner.calls[0][3:],
            ["worktree", "add", "--lock", "--reason", "a reason", "-b", "new-branch", "/srv/shop/w", "origin/trunk"],
        )


class Tmux(unittest.TestCase):
    def tmux(self, runner=None, environ=None):
        return tmux.Tmux(
            "/tools/tmux", "porchlight-test", "/package/tmux.conf", "/tools:/usr/bin", run=runner, environ=environ or {}
        )

    def test_a_session_starts_detached_in_a_folder_from_a_login_shell(self):
        words = self.tmux().new_session("shop-aaaaaaaa", "/srv/shop/w", "exec claude --remote-control")

        self.assertEqual(words[:5], ["/tools/tmux", "-L", "porchlight-test", "-f", "/package/tmux.conf"])
        self.assertIn("-d", words)
        self.assertEqual(words[words.index("-s") + 1], "shop-aaaaaaaa")
        self.assertEqual(words[words.index("-c") + 1], "/srv/shop/w")
        self.assertEqual(shlex.split(words[-1]), ["/bin/zsh", "-lic", "exec claude --remote-control"])

    def test_every_command_goes_to_its_own_server_with_a_clean_environment(self):
        runner = standins.Runner()
        environ = {"HOME": "/home/x", "LANG": "C", "CLAUDE_CODE_SESSION": "leaks", "PATH": "/somewhere"}

        self.tmux(runner, environ).kill_session("shop-aaaaaaaa")

        self.assertEqual(
            runner.calls,
            [["/tools/tmux", "-L", "porchlight-test", "-f", "/package/tmux.conf", "kill-session", "-t", "=shop-aaaaaaaa"]],
        )
        self.assertEqual(
            runner.options[0]["env"],
            {"HOME": "/home/x", "SHELL": "/bin/zsh", "PATH": "/tools:/usr/bin", "LANG": "en_US.UTF-8"},
            "nothing of the calling process reaches the sessions",
        )

    def test_keeps_a_language_that_is_utf8(self):
        environment = tmux.clean_environment({"LANG": "es_MX.UTF-8"}, "/usr/bin")

        self.assertEqual(environment["LANG"], "es_MX.UTF-8")

    def test_tells_whether_a_tab_shows_a_session(self):
        shown = standins.Runner(lambda words: standins.result(stdout="4242\n"))
        hidden = standins.Runner(lambda words: standins.result(stdout=""))
        gone = standins.Runner(lambda words: standins.result(returncode=1, stdout="no such session"))

        self.assertTrue(self.tmux(shown).attached("shop-aaaaaaaa"))
        self.assertFalse(self.tmux(hidden).attached("shop-aaaaaaaa"))
        self.assertFalse(self.tmux(gone).attached("shop-aaaaaaaa"))
        self.assertEqual(shown.calls[0][5:], ["list-clients", "-t", "=shop-aaaaaaaa", "-F", "#{client_pid}"])

    def test_the_command_that_attaches_to_a_session_is_what_a_tab_runs_without_exec(self):
        attach = self.tmux().attach("shop-aaaaaaaa")

        self.assertEqual(attach, "/tools/tmux -L porchlight-test -u attach-session -t '=shop-aaaaaaaa'")
        self.assertEqual(self.tmux().attach_command("shop-aaaaaaaa"), "exec " + attach)

    def test_a_shown_session_ends_with_its_tab(self):
        runner = standins.Runner()

        self.tmux(runner).end_with_its_tab("shop-aaaaaaaa")

        self.assertEqual(runner.calls[0][5:], ["set-option", "-t", "=shop-aaaaaaaa:", "destroy-unattached", "on"])

    def test_the_configuration_ships_inside_the_package(self):
        path = tmux.packaged_config()
        text = path.read_text(encoding="utf8")

        self.assertTrue(path.is_file())
        self.assertEqual(path.name, "tmux.conf")
        self.assertIn("set -g status off", text)
        self.assertIn("set -g mouse on", text)
        self.assertIn("set -g allow-passthrough on", text)
        self.assertNotIn("destroy-unattached", text, "a hidden session must outlive having no tab")


class Warp(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.configs = Path(self.scratch.name) / "tab_configs"
        self.now = 0.0
        self.seen = []

    def tearDown(self):
        self.scratch.cleanup()

    def sleep(self, seconds):
        self.now += seconds

    def warp(self, runner):
        return terminal.Warp(self.configs, run=runner, clock=lambda: self.now, sleep=self.sleep)

    def opening(self, words):
        # What Warp would find when it is asked to open the tab.
        self.seen.append((self.now, sorted(path.name for path in self.configs.iterdir())))

    def test_tells_whether_the_app_runs(self):
        warp = terminal.Warp(self.configs)

        self.assertTrue(warp.runs("77 /Applications/Warp.app/Contents/MacOS/stable\n"))
        self.assertFalse(warp.runs("77 /Applications/Other.app/Contents/MacOS/other\n78 grep Warp.app\n"))

    def test_opens_a_tab_through_a_configuration_it_removes_afterwards(self):
        runner = standins.Runner(self.opening)

        found = self.warp(runner).open_tab("porchlight_ready_shop-aaaaaaaa", "shop · Fix", "/srv", "exec x", lambda: 301)

        self.assertEqual(found, 301)
        self.assertEqual(runner.calls, [["/usr/bin/open", "-g", "warp://tab_config/porchlight_ready_shop-aaaaaaaa"]])
        self.assertEqual(
            self.seen, [(1.5, ["porchlight_ready_shop-aaaaaaaa.toml"])], "written a moment before it is opened"
        )
        self.assertEqual(list(self.configs.iterdir()), [])

    def test_asks_again_when_the_tab_did_not_start_and_then_gives_up(self):
        runner = standins.Runner()

        found = self.warp(runner).open_tab("porchlight_view_shop-01AAA", "t", "/srv", "x", lambda: 0, attempts=2, patience=8)

        self.assertEqual(found, 0)
        self.assertEqual(len(runner.calls), 2)
        self.assertGreaterEqual(self.now, 2 * (1.5 + 8))
        self.assertEqual(list(self.configs.iterdir()), [])

    def test_removes_the_configuration_when_opening_fails(self):
        runner = standins.Runner(lambda words: OSError("no open"))

        with self.assertRaises(OSError):
            self.warp(runner).open_tab("porchlight_ready_shop-aaaaaaaa", "t", "/srv", "x", lambda: 1)

        self.assertEqual(list(self.configs.iterdir()), [])

    def test_every_terminal_the_configuration_accepts_has_an_opener(self):
        for name in config.TERMINALS:
            self.assertEqual(terminal.named(name).name, name)
        self.assertIsInstance(terminal.named("warp", configs=self.configs), terminal.Terminal)
        self.assertEqual(terminal.named("warp", configs=self.configs).configs, self.configs)
        self.assertIsNone(terminal.named(None))


class State(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.store = state.Store(Path(self.scratch.name) / "projects" / "shop" / "ready-sessions.json")

    def tearDown(self):
        self.scratch.cleanup()

    def test_an_absent_or_broken_file_reads_as_the_default(self):
        self.assertEqual(self.store.load({"sessions": {}}), {"sessions": {}})

        self.store.path.parent.mkdir(parents=True)
        self.store.path.write_text("{ not json")
        self.assertEqual(self.store.load({}), {})
        self.store.path.write_text("[1, 2]")
        self.assertEqual(self.store.load({}), {}, "a state is a table")

    def test_writes_the_file_whole_and_reads_it_back(self):
        with self.store.locked():
            self.store.save({"sessions": {"a": {"title": "Café"}}})

        self.assertEqual(self.store.load({}), {"sessions": {"a": {"title": "Café"}}})
        self.assertEqual(json.loads(self.store.path.read_text(encoding="utf8"))["sessions"]["a"]["title"], "Café")
        self.assertEqual(
            sorted(path.name for path in self.store.path.parent.iterdir()),
            ["ready-sessions.json", "ready-sessions.lock"],
            "the lock beside it, no draft left",
        )

    def test_one_holder_of_the_lock_at_a_time(self):
        import fcntl

        with self.store.locked():
            with open(self.store.lock_path, "w") as other:
                with self.assertRaises(OSError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(self.store.lock_path, "w") as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


class Logs(unittest.TestCase):
    def test_appends_a_dated_line_and_never_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "logs" / "shop.log"

            logs.write(path, "first")
            logs.write(path, "second")
            lines = path.read_text(encoding="utf8").splitlines()

            self.assertEqual([line[20:] for line in lines], ["first", "second"])
            self.assertRegex(lines[0], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} first$")
            logs.write(Path(scratch) / "logs" / "shop.log" / "below-a-file", "ignored")


if __name__ == "__main__":
    unittest.main()
