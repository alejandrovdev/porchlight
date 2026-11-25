"""Tests of the atoms: the process list, transcripts, git worktrees, tmux, the terminal's
tab opener, the state file, the log, text from a session made printable and how the tool is named in a command. Each runs
against scratch folders and stand-ins."""

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import porchlight
from porchlight import config
from porchlight.atoms import invocation, logs, processes, state, terminal, text, tmux, transcripts, worktrees
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

    def test_reads_what_a_command_prints_and_nothing_when_it_cannot_run(self):
        runner = standins.Runner(lambda words: standins.result(stdout="Usage: claude\n"))

        self.assertEqual(processes.output(["/tools/claude", "--help"], run=runner), "Usage: claude\n")
        self.assertEqual(runner.calls, [["/tools/claude", "--help"]])
        self.assertIsNone(processes.output(["/nowhere/claude"], run=standins.Runner(lambda words: OSError("gone"))))
        failing = standins.Runner(lambda words: standins.result(returncode=1, stdout="half an answer"))
        self.assertIsNone(processes.output(["/tools/claude", "--help"], run=failing))

    def test_reads_what_a_failing_command_prints_when_any_exit_is_asked_for(self):
        failing = standins.Runner(lambda words: standins.result(returncode=1, stdout='{"loggedIn": false}'))

        self.assertEqual(processes.output(["/tools/claude", "auth"], run=failing, any_exit=True), '{"loggedIn": false}')
        self.assertIsNone(processes.output(["/nowhere/claude"], run=standins.Runner(lambda words: OSError("gone")), any_exit=True))


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

    def test_tells_whether_a_folder_is_a_git_repository(self):
        inside = standins.Runner(lambda words: standins.result(stdout="true\n"))
        outside = standins.Runner(lambda words: standins.result(returncode=128, stderr="fatal: not a git repository"))

        self.assertTrue(worktrees.is_repository(worktrees.Git("/tools/git", run=inside), "/srv/shop"))
        self.assertFalse(worktrees.is_repository(worktrees.Git("/tools/git", run=outside), "/srv/shop"))
        self.assertEqual(inside.calls, [["/tools/git", "-C", "/srv/shop", "rev-parse", "--is-inside-work-tree"]])

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

    def test_reads_the_text_a_session_shows_and_knows_nothing_when_it_cannot(self):
        shows = standins.Runner(lambda words: standins.result(stdout="Quick safety check\n"))
        gone = standins.Runner(lambda words: standins.result(returncode=1, stderr="can't find session: shop-aaaaaaaa"))
        stuck = standins.Runner(lambda words: subprocess.TimeoutExpired(words, 30))
        missing = standins.Runner(lambda words: FileNotFoundError(words[0]))

        self.assertEqual(self.tmux(shows).pane_text("shop-aaaaaaaa"), "Quick safety check\n")
        self.assertEqual(shows.calls, [["/tools/tmux", "-L", "porchlight-test", "-f", "/package/tmux.conf",
                                        "capture-pane", "-p", "-J", "-t", "=shop-aaaaaaaa:"]])  # fmt: skip
        for runner in (gone, stuck, missing):
            self.assertIsNone(self.tmux(runner).pane_text("shop-aaaaaaaa"), "what cannot be read is not known")
            self.assertEqual(len(runner.calls), 1)

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

    def test_tells_whether_the_app_is_installed_without_starting_it(self):
        applications = Path(self.scratch.name) / "Applications"
        runner = standins.Runner()
        warp = terminal.Warp(self.configs, run=runner, applications=[applications])

        self.assertFalse(warp.installed())
        (applications / "Warp.app").mkdir(parents=True)
        self.assertTrue(warp.installed())
        self.assertEqual(runner.calls, [], "nothing is run to find out")

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
        self.assertIsInstance(terminal.named("apple-terminal"), terminal.AppleTerminal)


class AppleTerminal(unittest.TestCase):
    PROCESS = "88 /System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal\n"

    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.now = 0.0

    def tearDown(self):
        self.scratch.cleanup()

    def sleep(self, seconds):
        self.now += seconds

    def apple(self, runner):
        return terminal.AppleTerminal(run=runner, clock=lambda: self.now, sleep=self.sleep)

    def test_is_named_as_the_configuration_and_a_person_name_it(self):
        self.assertEqual((terminal.AppleTerminal.name, terminal.AppleTerminal.title), ("apple-terminal", "Terminal"))
        self.assertIsInstance(terminal.AppleTerminal(), terminal.Terminal)

    def test_tells_whether_the_app_runs(self):
        apple = terminal.AppleTerminal()

        self.assertTrue(apple.runs(self.PROCESS))
        self.assertFalse(apple.runs("77 /Applications/Warp.app/Contents/MacOS/stable\n78 grep Terminal.app\n"))

    def test_tells_whether_the_app_is_installed_without_starting_it(self):
        utilities = Path(self.scratch.name) / "Utilities"
        runner = standins.Runner()
        apple = terminal.AppleTerminal(run=runner, applications=[utilities])

        self.assertFalse(apple.installed())
        (utilities / "Terminal.app").mkdir(parents=True)
        self.assertTrue(apple.installed())
        self.assertEqual(runner.calls, [], "nothing is run to find out")
        self.assertEqual(terminal.AppleTerminal().applications, (Path("/System/Applications/Utilities"),))

    def test_opens_a_window_that_runs_the_command_in_the_folder_with_the_title(self):
        runner = standins.Runner()

        found = self.apple(runner).open_tab("porchlight_ready_shop-aaaaaaaa", "shop · Fix", "/srv/my shop", "exec x", lambda: 301)

        self.assertEqual(found, 301)
        self.assertEqual(
            runner.calls,
            [["/usr/bin/osascript", "-e", terminal.AppleTerminal.SCRIPT, "--", "cd -- '/srv/my shop' && exec x", "shop · Fix"]],
        )
        self.assertIn("do script", terminal.AppleTerminal.SCRIPT)
        self.assertIn("on run argv", terminal.AppleTerminal.SCRIPT)
        self.assertNotIn("System Events", terminal.AppleTerminal.SCRIPT)
        self.assertEqual(runner.options[0].get("timeout"), 15)

    def test_every_value_reaches_applescript_only_as_an_argument(self):
        hostile = '" & do shell script "touch /tmp/x" & "\\ \'quoted\' $(rm -rf ~) `id`'
        runner = standins.Runner()

        self.apple(runner).open_tab("porchlight_view_shop-01AAA", hostile, hostile, "exec x", lambda: 1)

        words = runner.calls[0]
        self.assertEqual(words[:4], ["/usr/bin/osascript", "-e", terminal.AppleTerminal.SCRIPT, "--"])
        self.assertEqual(words[5], hostile, "the title is passed as it was given")
        self.assertEqual(shlex.split(words[4]), ["cd", "--", hostile, "&&", "exec", "x"], "the folder is one shell word")
        self.assertNotIn("touch", terminal.AppleTerminal.SCRIPT)
        self.assertEqual(len(words), 6)

    def test_a_folder_of_any_name_is_one_word_of_the_shell_line_that_runs_in_it(self):
        marker = Path(self.scratch.name) / "marker"
        names = ["it's", "$(touch %s)" % marker, "`touch %s`" % marker, "a; touch %s" % marker, "-n", "two\nlines",
                 "!!", "*", "~", "' ; touch %s ; '" % marker]
        for name in names:
            with self.subTest(folder=name):
                folder = Path(self.scratch.name) / "projects" / name
                folder.mkdir(parents=True)
                runner = standins.Runner()

                self.apple(runner).open_tab("porchlight_ready_shop-aaaaaaaa", "t", folder, "exec /bin/pwd", lambda: 1)

                shell_line = runner.calls[0][4]
                ran = subprocess.run(["/bin/sh", "-c", shell_line], cwd=self.scratch.name, capture_output=True, text=True, timeout=10)
                self.assertEqual((ran.returncode, ran.stdout), (0, str(folder) + "\n"), ran.stderr)
                self.assertFalse(marker.exists(), "nothing in the folder's name ran")

    def test_a_title_of_any_text_stays_after_the_script_and_the_end_of_options(self):
        for title in ("-e", "--", "-l JavaScript", '" & do shell script "id" & "', "a\nb", "end run", "$(id)"):
            with self.subTest(title=title):
                runner = standins.Runner()

                self.apple(runner).open_tab("porchlight_view_shop-01AAA", title, "/srv", "exec x", lambda: 1)

                words = runner.calls[0]
                self.assertEqual(words[2], terminal.AppleTerminal.SCRIPT)
                self.assertEqual(words[3], "--")
                self.assertEqual(words[5], title)

    def test_a_nul_in_the_title_is_dropped_and_the_window_opens(self):
        runner = standins.Runner(lambda words: ValueError("embedded null byte") if any("\0" in w for w in words) else None)

        found = self.apple(runner).open_tab("porchlight_view_shop-01AAA", "shop\0 · Fix\0", "/srv", "exec x", lambda: 7)

        self.assertEqual(found, 7)
        self.assertEqual(runner.calls[0][5], "shop · Fix")

    def test_a_nul_in_the_folder_or_the_command_cannot_be_run_and_says_so(self):
        for directory, command in (("/srv/a\0b", "exec x"), ("/srv", "exec x\0y")):
            with self.subTest(directory=directory, command=command):
                runner = standins.Runner()

                with self.assertRaises(OSError) as raised:
                    self.apple(runner).open_tab("porchlight_view_shop-01AAA", "t", directory, command, lambda: 1)

                self.assertIn("NUL", str(raised.exception))
                self.assertEqual(runner.calls, [], "nothing is run")

    def test_asks_again_when_the_window_did_not_start_and_then_gives_up(self):
        runner = standins.Runner()

        found = self.apple(runner).open_tab("porchlight_view_shop-01AAA", "t", "/srv", "x", lambda: 0, attempts=2, patience=8)

        self.assertEqual(found, 0)
        self.assertEqual(len(runner.calls), 2)
        self.assertGreaterEqual(self.now, 2 * 8)

    def test_a_refused_window_raises_so_that_it_is_logged(self):
        refused = standins.result(1, stderr="execution error: Not authorized to send Apple events to Terminal. (-1743)\n")
        runner = standins.Runner(lambda words: refused)

        with self.assertRaises(subprocess.SubprocessError) as raised:
            self.apple(runner).open_tab("porchlight_ready_shop-aaaaaaaa", "t", "/srv", "x", lambda: 1)

        self.assertIn("Not authorized to send Apple events to Terminal", str(raised.exception))
        self.assertEqual(len(runner.calls), 1)


class Text(unittest.TestCase):
    def test_ordinary_text_is_left_as_it_is(self):
        for ordinary in ("Fix the header", "Café niño über", "😀 👨‍👩‍👧 ❤️ 🇦🇷", "日本語 العربية", "a  b"):
            self.assertEqual(text.printable(ordinary), ordinary)

    def test_each_control_character_is_replaced_and_half_characters_are_dropped(self):
        self.assertEqual(text.printable("a\x1b[31mred\x07\x00\x7f\x9b2J"), "a\ufffd[31mred\ufffd\ufffd\ufffd\ufffd2J")
        self.assertEqual(text.printable("line\rover\ttab\nnext"), "line\ufffdover\ufffdtab\ufffdnext")
        self.assertEqual(text.printable("half \ud83d of \ude00 one"), "half  of  one")

    def test_on_one_line_white_space_is_one_space(self):
        self.assertEqual(text.one_line("  Fix the\nheader\r\n\tnow 😀 "), "Fix the header now 😀")
        self.assertEqual(text.one_line("Fix \ud83d the \x1b[2J header"), "Fix the \ufffd[2J header")

    def test_the_characters_asked_for_are_kept(self):
        self.assertEqual(text.printable("a\tb\nc\x1bd\re", keep="\t\n"), "a\tb\nc\ufffdd\ufffde")


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

    def test_text_that_is_not_ascii_is_stored_as_it_is(self):
        self.store.save({"sessions": {"a": {"title": "Café 😀 niño", "prompt": "日本語"}}})

        written = self.store.path.read_text(encoding="utf8")
        self.assertIn('"title": "Café 😀 niño"', written)
        self.assertIn('"prompt": "日本語"', written)

    def test_half_a_character_from_a_transcript_never_stops_a_save(self):
        # JSON lets a transcript hold a lone surrogate (half an emoji); no file can take it.
        table = {"sessions": {"a": {"title": "Fix \ud83d", "prompt": "plain"}}}

        self.store.save(table)

        written = self.store.path.read_bytes()
        written.decode("utf8")  # the file is UTF-8 all the same
        self.assertIn(b'"title": "Fix \\ud83d"', written)
        self.assertEqual(self.store.load({}), table, "it reads back as it was given")
        self.assertEqual([path.name for path in self.store.path.parent.iterdir()], ["ready-sessions.json"])

    def test_one_holder_of_the_lock_at_a_time(self):
        import fcntl

        with self.store.locked():
            with open(self.store.lock_path, "w") as other:
                with self.assertRaises(OSError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(self.store.lock_path, "w") as other:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_a_lock_is_taken_by_one_and_refused_to_the_next_until_it_is_let_go(self):
        path = Path(self.scratch.name) / "state" / "service.lock"

        held = state.exclusive(path)
        self.assertIsNotNone(held, "its folder is made")
        self.assertIsNone(state.exclusive(path), "another holds it: no waiting")
        held.close()
        again = state.exclusive(path)
        self.assertIsNotNone(again)
        again.close()

    def test_a_folder_it_makes_is_marked_and_one_that_was_there_never_is(self):
        root = Path(self.scratch.name)
        made, found = root / "deep" / "made", root / "found"
        found.mkdir()

        self.assertEqual(state.claim(made, ".mark"), made)
        state.claim(made, ".mark")  # again: nothing to do
        state.claim(found, ".mark")

        self.assertTrue(state.claimed(made, ".mark"))
        self.assertEqual([entry.name for entry in made.iterdir()], [".mark"])
        self.assertFalse(state.claimed(found, ".mark"))
        self.assertEqual(list(found.iterdir()), [])
        self.assertFalse(state.claimed(root / "absent", ".mark"))

    def test_a_marked_folder_is_let_go_of_only_once_nothing_else_is_in_it(self):
        root = Path(self.scratch.name)
        made = state.claim(root / "made", ".mark")
        (made / "notes.txt").write_text("")

        state.release(made, ".mark")
        self.assertEqual(sorted(entry.name for entry in made.iterdir()), [".mark", "notes.txt"])

        (made / "notes.txt").unlink()
        state.release(made, ".mark")
        self.assertFalse(made.exists())
        state.release(made, ".mark")  # gone already: no error

    def test_a_store_marks_the_folder_of_the_tool_it_is_the_first_to_write_in(self):
        root = Path(self.scratch.name) / "state"
        marked = []
        store = state.Store(root / "projects" / "shop" / "view-tabs.json", prepare=lambda: marked.append(root.exists()))

        store.load({})
        self.assertEqual(marked, [], "reading makes nothing")
        store.save({})
        with store.locked():
            pass

        self.assertEqual(marked, [False, True], "asked before its own folder is made, each time it writes")


class Logs(unittest.TestCase):
    def test_a_dated_line_starts_with_the_date_a_log_line_has(self):
        self.assertRegex(logs.dated("started"), r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d started$")

    def test_appends_a_dated_line_and_never_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "logs" / "shop.log"

            logs.write(path, "first")
            logs.write(path, "second")
            lines = path.read_text(encoding="utf8").splitlines()

            self.assertEqual([line[20:] for line in lines], ["first", "second"])
            self.assertRegex(lines[0], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} first$")
            logs.write(Path(scratch) / "logs" / "shop.log" / "below-a-file", "ignored")

    def test_a_message_that_repeats_the_last_line_is_written_once_until_it_changes(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "logs" / "shop.log"

            for message in ("missing", "missing", "missing", "back", "missing", "missing"):
                logs.write(path, message)

            self.assertEqual(
                [line[20:] for line in path.read_text(encoding="utf8").splitlines()], ["missing", "back", "missing"]
            )

    def test_only_the_whole_last_message_counts_as_a_repeat(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "shop.log"

            for message in ("no worktree: fatal\nhint: missing", "missing", "no worktree: fatal\nhint: missing"):
                logs.write(path, message)
                logs.write(path, message)

            text = path.read_text(encoding="utf8")
            self.assertEqual(text.count("no worktree: fatal\nhint: missing\n"), 2, "a message of two lines too")
            self.assertEqual(len(text.splitlines()), 5)


    def test_text_from_a_session_is_written_printable_and_never_fails(self):
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "shop.log"

            logs.write(path, "opened the tab of aaaa (Fix \ud83d\x1b[2J the café 😀)")
            logs.write(path, "opened the tab of aaaa (Fix \ud83d\x1b[2J the café 😀)")
            logs.write(path, "failed:\tfatal\nhint: missing")

            lines = path.read_bytes().decode("utf8").splitlines()
            self.assertEqual(
                [line[20:] for line in lines[:2]] + lines[2:],
                ["opened the tab of aaaa (Fix \ufffd[2J the café 😀)", "failed:\tfatal", "hint: missing"],
                "once, without the control character or the half character; tabs and lines kept",
            )


class Invocation(unittest.TestCase):
    """How the tool is named in a command it hands to a tab, a session or a service."""

    def test_names_the_installed_command_when_the_path_has_one(self):
        with tempfile.TemporaryDirectory() as scratch:
            installed = Path(scratch) / "porchlight"
            installed.write_text("#!/bin/sh\n")
            installed.chmod(0o755)

            words, environment = invocation.words("porchlight", path=scratch)

            self.assertEqual((words, environment), ([str(installed)], {}))
            self.assertEqual(invocation.shell(words, environment), shlex.quote(str(installed)))

    def test_falls_back_to_this_interpreter_and_this_package(self):
        with tempfile.TemporaryDirectory() as scratch:
            words, environment = invocation.words("porchlight", path=scratch)

        self.assertEqual(words, [sys.executable, "-P", "-m", "porchlight"])
        self.assertEqual(environment, {"PYTHONPATH": str(Path(porchlight.__file__).resolve().parent.parent)})

    def test_the_fallback_ignores_modules_of_the_folder_it_runs_in(self):
        # A repository with a json.py of its own must not have it imported in its place.
        with tempfile.TemporaryDirectory() as scratch:
            folder = Path(scratch)
            planted = folder / "planted"
            (folder / "json.py").write_text("open(%r, 'w').close()\nraise SystemExit(9)\n" % str(planted))
            words, environment = invocation.words("porchlight", path=str(folder / "nowhere"))

            done = subprocess.run(
                words + ["--version"], cwd=folder, capture_output=True, text=True, timeout=60,
                env={"PATH": "/usr/bin:/bin", **environment},
            )  # fmt: skip

            self.assertEqual((done.returncode, done.stdout.strip()), (0, "porchlight " + porchlight.__version__), done.stderr)
            self.assertFalse(planted.exists(), "the folder's json.py was imported")

    def test_a_shell_reads_the_fallback_as_one_command_even_after_exec(self):
        words, environment = ["/some where/python3", "-m", "porchlight"], {"PYTHONPATH": "/its own/folder"}

        command = invocation.shell(words, environment)

        self.assertEqual(command, "/usr/bin/env 'PYTHONPATH=/its own/folder' '/some where/python3' -m porchlight")
        self.assertEqual(
            shlex.split(command), ["/usr/bin/env", "PYTHONPATH=/its own/folder", "/some where/python3", "-m", "porchlight"]
        )


if __name__ == "__main__":
    unittest.main()
