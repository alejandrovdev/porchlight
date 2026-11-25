"""Tests of the command line: what each command reads, prints and exits with. The Mac is a
stand-in and the configuration a scratch file: no session starts and no tab opens."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import porchlight
from porchlight import cli, config, names
from porchlight.atoms import transcripts
from porchlight.features import ready_sessions, resume_list
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
LIVE = "cse_01AAA"
SERVER_ID = "11111111-1111-5111-8111-111111111111"


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.file = self.root / "config.toml"
        self.terminal = standins.Terminal()
        self.mac = standins.StandInMac(self.root, self.terminal)
        self.printed = []
        self.errors = ""

    def tearDown(self):
        self.scratch.cleanup()

    def configure(self, **projects):
        """Write a configuration: each project with the features given, in a folder of its own."""
        configured = []
        for name, features in projects.items():
            (self.root / name).mkdir(exist_ok=True)
            configured.append(
                config.Project(name, str(self.root / name), "plan", config.ordered(features), None, name.capitalize())
            )
        self.configuration = config.Config("warp", tuple(configured))
        config.save(self.configuration, self.file)
        return self.configuration.projects

    def run_cli(self, *arguments, config_file=True):
        """Run a command against the scratch configuration: its exit code. What it printed
        is in `printed`, and what it wrote as an error in `errors`."""
        words = list(arguments) + (["--config", str(self.file)] if config_file else [])
        errors, output = io.StringIO(), io.StringIO()
        with redirect_stderr(errors), redirect_stdout(output):
            code = cli.main(words, mac=self.mac, out=self.printed.append)
        self.errors = errors.getvalue()
        self.printed.extend(output.getvalue().splitlines())
        return code

    def closed_session(self, project, session, title):
        record = {
            "state": "closed",
            "started": self.mac.now,
            "changed": self.mac.now,
            "worktree": str(names.repository(project) / ".claude" / "worktrees" / names.worktree(project, session)),
            "branch": names.branch(project, session),
            "prompt": "",
            "title": title,
            "cse": "",
            "tidied": True,
            "shown": True,
            "tmux": "",
        }
        store = self.mac.store(project, ready_sessions.STATE)
        state = ready_sessions.load_state(store)
        state["sessions"][session] = record
        store.save(state)


class Basics(CommandLine):
    def test_version_prints_the_name_and_the_version(self):
        self.assertEqual(self.run_cli("--version", config_file=False), 0)

        self.assertEqual(self.printed, ["porchlight %s" % porchlight.__version__])

    def test_an_unknown_command_is_a_usage_error(self):
        self.assertEqual(self.run_cli("nonsense", config_file=False), 2)

        self.assertIn("usage: porchlight", self.errors)
        self.assertIn("nonsense", self.errors)
        self.assertEqual(self.printed, [])

    def test_no_command_is_a_usage_error(self):
        self.assertEqual(self.run_cli(config_file=False), 2)

        self.assertIn("usage: porchlight", self.errors)

    def test_help_lists_the_commands_that_exist_and_no_other(self):
        self.assertEqual(self.run_cli("--help", config_file=False), 0)

        text = "\n".join(self.printed)
        for command in ("status", "reopen", "doctor", "view", "resume-list"):
            self.assertIn("\n    %s " % command, text)
        for later in ("run", "server", "apply", "start", "stop", "uninstall", "setup"):
            self.assertNotIn("\n    %s " % later, text, "a command that does nothing yet is not listed")

    def test_a_configuration_that_does_not_parse_prints_each_problem_by_key_and_exits_one(self):
        self.file.write_text('terminal = "kitty"\n[projects.shop]\npermission_mode = "plan"\npreset = "minimal"\n')

        for command in (["status"], ["doctor"], ["reopen"], ["resume-list"], ["view", "shop", LIVE]):
            self.printed.clear()
            self.assertEqual(self.run_cli(*command), 1, command)
            self.assertEqual(
                self.printed,
                [
                    "The configuration %s has problems:" % self.file,
                    'terminal: unknown terminal "kitty"; one of: warp',
                    "projects.shop.path: missing",
                ],
            )

    def test_a_configuration_that_is_not_toml_says_where_it_breaks(self):
        self.file.write_text("terminal = \n")

        self.assertEqual(self.run_cli("status"), 1)

        self.assertEqual(len(self.printed), 2)
        self.assertIn("line 1", self.printed[1])

    def test_a_configuration_that_cannot_be_read_is_said_and_exits_one(self):
        self.file.mkdir()

        self.assertEqual(self.run_cli("status"), 1)

        self.assertEqual(len(self.printed), 1)
        self.assertIn("The configuration %s cannot be read" % self.file, self.printed[0])

    def test_the_configuration_may_be_named_before_the_command(self):
        self.configure(shop=("server",))

        self.assertEqual(self.run_cli("--config", str(self.file), "status", config_file=False), 0)

        self.assertEqual(self.printed[0], "shop")

    def test_without_config_reads_the_default_file(self):
        self.configure(shop=("server",))

        with mock.patch.dict("os.environ", {"PORCHLIGHT_CONFIG": str(self.file)}):
            self.assertEqual(self.run_cli("status", config_file=False), 0)

        self.assertEqual(self.printed[0], "shop")

    def test_a_tool_that_is_not_installed_is_said_and_exits_one(self):
        (shop,) = self.configure(shop=("ready-session", "reopen"))
        self.closed_session(shop, A, "Header on phones")
        del self.mac.tmux
        del self.mac.found["tmux"]

        self.assertEqual(self.run_cli("reopen", "header"), 1)

        self.assertEqual(
            self.printed,
            ["tmux was not found in PATH or in Homebrew's folders. See what is missing with: porchlight doctor"],
        )


class Status(CommandLine):
    def test_prints_every_project_under_its_name(self):
        self.configure(shop=config.FEATURES, blog=("ready-session",))

        self.assertEqual(self.run_cli("status"), 0)

        self.assertEqual(
            self.printed,
            [
                "shop",
                "  Ready sessions, with Claude Code's interface:",
                "    No session with Claude Code's interface yet.",
                "  Sessions the server started, with a read-only view:",
                "    No session the server started is running.",
                "",
                "blog",
                "  Ready sessions, with Claude Code's interface:",
                "    No session with Claude Code's interface yet.",
            ],
        )

    def test_without_a_project_says_how_to_add_one(self):
        self.assertEqual(self.run_cli("status"), 0, "a file that is not there is a configuration without projects")

        self.assertEqual(self.printed, ["No project is configured. Add one with: porchlight setup"])


class Reopen(CommandLine):
    def setUp(self):
        super().setUp()
        self.shop, self.blog = self.configure(shop=("ready-session", "reopen"), blog=("ready-session", "reopen"))
        self.closed_session(self.shop, A, "Fix the header")
        self.closed_session(self.blog, B, "Fix the footer")

    def test_without_a_name_lists_the_closed_sessions_of_every_project(self):
        self.assertEqual(self.run_cli("reopen"), 0)

        self.assertEqual(self.printed[0], "Closed sessions:")
        self.assertEqual([line.split()[0] for line in self.printed[1:]], ["blog", "shop"])

    def test_reopens_the_one_session_that_matches_among_every_project(self):
        self.mac.tmux_runner.answers = lambda words: (
            setattr(self.mac, "ps", f"601 claude --resume {B} --remote-control\n") if "new-session" in words else None
        )

        self.assertEqual(self.run_cli("reopen", "the", "footer"), 0, "a name of several words needs no quotes")

        self.assertIn('Reopened "Fix the footer" (project blog), hidden', self.printed[0])
        self.assertEqual(self.printed[1], "    /tools/tmux -L porchlight-test -u attach-session -t '=blog-bbbbbbbb'")

    def test_several_matches_are_refused_and_listed_with_their_project(self):
        self.assertEqual(self.run_cli("reopen", "fix"), 1)

        self.assertEqual(self.printed[0], 'Several closed sessions match "fix"; run it again with the id of one:')
        self.assertEqual(len(self.printed), 3)

    def test_project_limits_it_to_one(self):
        self.assertEqual(self.run_cli("reopen", "--project", "shop"), 0)
        self.assertEqual(len(self.printed), 2)
        self.assertRegex(self.printed[1], r"^  aaaaaaaa  closed .* Fix the header$")

        self.printed.clear()
        self.assertEqual(self.run_cli("reopen", "footer", "--project", "shop"), 1)
        self.assertEqual(self.printed[0], 'No closed session matches "footer". The closed ones:')

    def test_a_project_the_configuration_does_not_have_is_refused(self):
        self.assertEqual(self.run_cli("reopen", "header", "--project", "docs"), 1)

        self.assertEqual(self.printed, ['No project "docs" in the configuration. Its projects: shop, blog'])


class Doctor(CommandLine):
    def setUp(self):
        super().setUp()
        self.configure(shop=("server",))
        self.mac.git_runner.answers = lambda words: (
            standins.result(stdout="true\n") if "--is-inside-work-tree" in words else None
        )

    def test_prints_one_line_for_each_check_and_exits_zero_when_all_pass(self):
        self.assertEqual(self.run_cli("doctor"), 0)

        self.assertEqual(self.printed[0], "shop")
        self.assertEqual(len(self.printed), 6)
        self.assertTrue(all(line.startswith(("  ok ", "  unknown ")) for line in self.printed[1:]), self.printed)

    def test_exits_one_when_a_check_fails(self):
        del self.mac.found["git"]

        self.assertEqual(self.run_cli("doctor"), 1)

        self.assertIn("  missing  git: install it with: brew install git", self.printed)


class View(CommandLine):
    def setUp(self):
        super().setUp()
        (self.shop,) = self.configure(shop=config.FEATURES)

    def test_runs_the_read_only_view_of_a_session_of_a_project(self):
        worktree = names.repository(self.shop) / ".claude" / "worktrees" / ("bridge-" + LIVE)
        worktree.mkdir(parents=True)
        self.mac.ps = f"101 claude --print --sdk-url wss://example.invalid/x --session-id {LIVE}\n"
        folder = self.mac.transcripts / transcripts.folder_name(str(worktree))
        folder.mkdir(parents=True)
        (folder / (SERVER_ID + ".jsonl")).write_text(
            json.dumps({"type": "user", "message": {"content": "Fix the header"}}) + "\n", encoding="utf8"
        )

        self.assertEqual(self.run_cli("view", "shop", LIVE), 0)  # the process is gone: the view closes

        self.assertIn("▌ Fix the header", " ".join(self.printed))
        self.assertIn("The session ended (archived). Closing this tab.", " ".join(self.printed))

    def test_a_session_that_does_not_run_here_exits_one(self):
        self.assertEqual(self.run_cli("view", "shop", LIVE), 1)

        self.assertIn("Session cse_01AAA is not running on this Mac.", " ".join(self.printed))

    def test_anything_but_a_project_and_a_server_session_is_a_usage_error(self):
        for arguments in ((), ("shop",), ("shop", "not-a-session"), ("shop", LIVE, "more")):
            self.assertEqual(self.run_cli("view", *arguments), 2, arguments)
            self.assertIn("usage: porchlight", self.errors)
            self.assertEqual(self.printed, [])

    def test_a_project_the_configuration_does_not_have_is_refused(self):
        self.assertEqual(self.run_cli("view", "blog", LIVE), 1)

        self.assertEqual(self.printed, ['No project "blog" in the configuration. Its projects: shop'])


class ResumeList(CommandLine):
    def setUp(self):
        super().setUp()
        self.shop, self.blog = self.configure(shop=("server", "resume-list"), blog=("server",))
        worktree = str(names.repository(self.shop)) + "/.claude/worktrees/bridge-cse_01ABC"
        server = self.mac.transcripts / transcripts.folder_name(worktree)
        server.mkdir(parents=True)
        self.main = self.mac.transcripts / transcripts.folder_name(str(names.repository(self.shop)))
        self.main.mkdir()
        lines = [
            {"type": "queue-operation", "sessionId": SERVER_ID, "content": "Fix the header"},
            {"type": "user", "sessionId": SERVER_ID, "entrypoint": "sdk-cli", "cwd": worktree},
        ]
        (server / (SERVER_ID + ".jsonl")).write_text(
            "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines), encoding="utf8"
        )

    def test_lists_the_copies_of_the_projects_that_have_the_feature(self):
        resume_list.sync(self.shop, self.mac)

        self.assertEqual(self.run_cli("resume-list"), 0)

        self.assertEqual(self.printed[0], "shop")
        self.assertIn("Fix the header", self.printed[1])
        self.assertEqual(self.printed[2], "      claude --resume " + resume_list.copy_id(self.shop, SERVER_ID, 1))
        self.assertNotIn("blog", self.printed)

    def test_lists_without_bringing_the_copies_up_to_date(self):
        self.assertEqual(self.run_cli("resume-list"), 0)

        self.assertEqual(self.printed, ["shop", "  No session created from the phone has a copy yet."])
        self.assertEqual(list(self.main.iterdir()), [])

    def test_sync_brings_them_up_to_date_first(self):
        self.assertEqual(self.run_cli("resume-list", "sync"), 0)

        self.assertEqual(self.printed[2], "      claude --resume " + resume_list.copy_id(self.shop, SERVER_ID, 1))
        self.assertEqual(len(list(self.main.glob("*.jsonl"))), 1)

    def test_anything_else_is_a_usage_error(self):
        self.assertEqual(self.run_cli("resume-list", "frobnicate"), 2)

        self.assertIn("usage: porchlight resume-list", self.errors)


if __name__ == "__main__":
    unittest.main()
