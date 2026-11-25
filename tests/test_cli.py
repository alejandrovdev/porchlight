"""Tests of the command line: what each command reads, prints and exits with. The Mac is a
stand-in and the configuration a scratch file: no session starts and no tab opens."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import porchlight
from porchlight import agents, cli, config, names, service, session_settings
from porchlight.atoms import state, transcripts
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
        listed = ("setup", "init", "deinit", "status", "reopen", "doctor", "view", "resume-list", "apply", "start")
        for command in listed + ("stop", "uninstall", "run", "server"):
            self.assertIn("\n    %s " % command, text)

    def test_help_gives_setup_init_and_deinit_one_line_each(self):
        self.assertEqual(self.run_cli("--help", config_file=False), 0)

        lines = self.printed[0].splitlines() if len(self.printed) == 1 else self.printed
        text = "\n".join(lines)
        for command in ("setup", "init", "deinit"):
            (line,) = [line for line in text.splitlines() if line.startswith("    %s " % command)]
            following = text.splitlines()[text.splitlines().index(line) + 1]
            self.assertTrue(following.startswith("    ") and not following.startswith("     "), following)

    def test_a_configuration_that_does_not_parse_prints_each_problem_by_key_and_exits_one(self):
        self.file.write_text('terminal = "kitty"\n[projects.shop]\npermission_mode = "plan"\npreset = "minimal"\n')

        every = (["status"], ["doctor"], ["reopen"], ["resume-list"], ["view", "shop", LIVE])
        every += (["apply"], ["apply", "--servers"], ["server", "shop"])  # `uninstall` works without it
        for command in every:
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

        self.assertEqual(self.printed, ["No project is configured. Add one from its folder with: porchlight init"])


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


SERVICE_LABEL = standins.LABEL
SHOP = standins.LABEL + ".server.shop"
CHECK = "Check with: porchlight status, porchlight doctor"


class Run(CommandLine):
    def test_once_makes_one_pass_over_the_configuration_and_exits(self):
        (shop,) = self.configure(shop=("server",))
        (self.root / "shop").rmdir()  # what a pass says in the project's log

        self.assertEqual(self.run_cli("run", "--once"), 0)

        self.assertIn("skipped: the folder %s is missing" % shop.directory, self.mac.log_text(shop))
        self.assertEqual(self.printed, [])
        self.assertEqual(self.mac.spawned, [], "one pass keeps no Mac awake")

    def test_once_refuses_a_configuration_that_does_not_parse_in_dated_lines(self):
        self.file.write_text('terminal = "kitty"\n')

        self.assertEqual(self.run_cli("run", "--once"), 1)

        self.assertEqual(len(self.printed), 2)
        self.assertRegex(
            self.printed[0], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d The configuration .* has problems:$"
        )

    def test_a_second_one_exits_one_saying_another_is_running(self):
        self.configure(shop=("server",))
        held = state.exclusive(names.service_lock(self.mac.environ))
        self.addCleanup(held.close)

        for words in (["run"], ["run", "--once"]):
            self.printed.clear()
            self.assertEqual(self.run_cli(*words), 1)
            self.assertEqual(len(self.printed), 1)
            self.assertTrue(
                self.printed[0].endswith(" Another porchlight run is already running. Only one runs at a time.")
            )

    def test_serves_the_file_it_was_given_with_the_lock_of_this_install(self):
        with mock.patch.object(service, "run", return_value=0) as run:
            self.assertEqual(self.run_cli("run"), 0, "even before the file exists: the service waits for it")

        (path, mac_for, say, lock), options = run.call_args
        self.assertEqual(str(path), str(self.file))
        self.assertEqual(lock, names.service_lock(self.mac.environ))
        self.assertEqual(options, {"once": False})
        self.assertIs(mac_for(config.Config()), self.mac)

    def test_each_configuration_gets_a_mac_that_reads_the_file_the_service_reads(self):
        with mock.patch.object(service, "run", return_value=0) as run, mock.patch.object(cli.Mac, "of") as of:
            cli.main(["run", "--config", str(self.file)], out=self.printed.append)
            run.call_args.args[1](config.Config("warp"))

        of.assert_called_once_with(config.Config("warp"), config_file=str(self.file))


class Server(CommandLine):
    def become(self, *words):
        """Run `server` with what would replace this process recorded instead."""
        with mock.patch.object(os, "execve") as self.execve, mock.patch.object(os, "chdir") as self.chdir:
            return self.run_cli("server", *words)

    def test_installs_the_settings_that_waited_and_becomes_the_projects_server(self):
        (shop,) = self.configure(shop=("server",))
        settings = self.mac.settings(shop)
        session_settings.stage(standins.project("shop", mode="acceptEdits"), settings)
        session_settings.stage(shop, settings)

        self.assertEqual(self.become("shop"), 0)

        self.assertEqual(json.loads(settings.read_text())["permissions"]["defaultMode"], "plan")
        self.assertFalse(session_settings.waiting(settings).exists())
        self.chdir.assert_called_once_with(names.repository(shop))
        program, words, environment = self.execve.call_args.args
        self.assertEqual(program, "/tools/claude")
        self.assertEqual(words[:4], ["/tools/claude", "remote-control", "--spawn", "worktree"])
        self.assertEqual(words[words.index("--settings") + 1], str(settings))
        self.assertEqual(self.mac.spawned, [], "keeping the Mac awake is the service's")

    def test_refuses_a_project_the_configuration_does_not_have(self):
        self.configure(shop=("server",))

        self.assertEqual(self.become("blog"), 1)

        self.assertEqual(self.printed, ['No project "blog" in the configuration. Its projects: shop'])
        self.execve.assert_not_called()

    def test_refuses_a_project_without_the_server(self):
        (blog,) = self.configure(blog=("ready-session",))

        self.assertEqual(self.become("blog"), 1)

        self.assertEqual(self.printed, ['The project "blog" does not have the server feature: it has no server to run.'])
        self.execve.assert_not_called()
        self.assertFalse(self.mac.settings(blog).exists())

    def test_needs_a_project(self):
        self.assertEqual(self.become(), 2)


class Agents(CommandLine):
    def test_apply_makes_launchd_match_the_configuration(self):
        self.configure(shop=("server",))

        self.assertEqual(self.run_cli("apply"), 0)

        self.assertEqual(self.mac.launchctl.did(), [("load", SERVICE_LABEL), ("load", SHOP)])
        self.assertEqual(self.printed, [SERVICE_LABEL + ": loaded", SHOP + ": loaded", CHECK])

    def test_apply_changes_nothing_for_a_configuration_that_does_not_parse(self):
        self.configure(shop=("server",))
        self.run_cli("apply")
        files = sorted(path.name for path in (self.root / "agents").iterdir())
        self.mac.launchctl.calls.clear()
        self.printed.clear()
        self.file.write_text('[projects.shop]\npermission_mode = "plan"\npreset = "minimal"\n')

        self.assertEqual(self.run_cli("apply", "--servers"), 1)

        self.assertEqual(self.printed, ["The configuration %s has problems:" % self.file, "projects.shop.path: missing"])
        self.assertEqual(self.mac.launchctl.calls, [], "launchd was not even asked")
        self.assertEqual(sorted(path.name for path in (self.root / "agents").iterdir()), files)

    def test_apply_restarts_a_running_server_only_with_servers(self):
        self.configure(shop=("server",))
        self.run_cli("apply")
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.run_cli("apply"), 0)
        self.assertNotIn(("unload", SHOP), self.mac.launchctl.did())
        self.assertIn("porchlight apply --servers", self.printed[-2])

        self.assertEqual(self.run_cli("apply", "--servers"), 0)
        self.assertEqual(self.mac.launchctl.did()[-2:], [("unload", SHOP), ("load", SHOP)])

    def test_stop_and_start_need_no_configuration_that_parses(self):
        self.configure(shop=("server",))
        self.run_cli("apply")
        self.mac.launchctl.calls.clear()
        self.printed.clear()
        self.file.write_text("terminal = \n")

        self.assertEqual(self.run_cli("stop"), 0)
        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL)])
        self.assertEqual(self.printed[-1], "Sessions already running keep running. Start again with: porchlight start")

        self.assertEqual(self.run_cli("start"), 0)
        self.assertEqual(self.mac.launchctl.did()[-1], ("load", SERVICE_LABEL))

    def test_stop_unloads_the_servers_only_with_servers(self):
        self.configure(shop=("server",))
        self.run_cli("apply")

        self.assertEqual(self.run_cli("stop", "--servers"), 0)

        self.assertEqual(self.mac.launchctl.loaded, set())

    def test_start_without_any_agent_says_to_apply(self):
        self.assertEqual(self.run_cli("start"), 1)

        self.assertEqual(self.printed, ["No agent is installed. Install them with: porchlight apply"])

    def test_uninstall_leaves_a_running_server_unless_told(self):
        self.configure(shop=("server",))
        self.run_cli("apply")

        self.assertEqual(self.run_cli("uninstall"), 1)
        self.assertEqual(self.mac.launchctl.loaded, {SHOP})

        self.assertEqual(self.run_cli("uninstall", "--servers"), 0)
        self.assertEqual(self.mac.launchctl.loaded, set())
        self.assertTrue(self.file.exists(), "the configuration stays")

    def test_uninstall_purge_removes_the_configuration_file_it_read(self):
        self.configure(shop=("server",))
        self.run_cli("apply")

        self.assertEqual(self.run_cli("uninstall", "--servers", "--purge"), 0)

        self.assertFalse(self.file.exists())
        self.assertFalse((self.root / "state").exists())
        self.assertEqual(self.printed[-1], "Removed the configuration, the state and the logs.")

    def test_apply_refuses_a_configuration_file_that_was_named_and_is_not_there(self):
        self.configure(shop=("server",))
        self.run_cli("apply")
        self.file.unlink()  # or a name typed wrong
        files = sorted(path.name for path in (self.root / "agents").iterdir())
        self.mac.launchctl.calls.clear()
        self.printed.clear()

        self.assertEqual(self.run_cli("apply", "--servers"), 1)

        self.assertEqual(self.printed, ["The configuration file %s does not exist. Nothing was changed." % self.file])
        self.assertEqual(self.mac.launchctl.calls, [], "launchd was not even asked")
        self.assertEqual(sorted(path.name for path in (self.root / "agents").iterdir()), files)

    def test_apply_without_the_default_file_still_means_no_project(self):
        with mock.patch.dict("os.environ", {"PORCHLIGHT_CONFIG": str(self.file)}):
            self.assertEqual(self.run_cli("apply", config_file=False), 0)

        self.assertEqual(self.printed, ["No project is configured. Add one from its folder with: porchlight init", CHECK])

    def broken_after_a_free_session(self):
        """An install whose configuration stopped parsing while a free session waits."""
        (shop,) = self.configure(shop=("server", "ready-session"))
        self.run_cli("apply")
        worktree = names.repository(shop) / ".claude" / "worktrees" / names.worktree(shop, A)
        worktree.mkdir(parents=True)
        record = {"state": "free", "started": self.mac.now, "changed": self.mac.now, "worktree": str(worktree)}
        record.update(branch=names.branch(shop, A), prompt="", title="", cse="", tidied=False, shown=False)
        record["tmux"] = names.tmux_session(shop, A)
        self.mac.store(shop, ready_sessions.STATE).save({"sessions": {A: record}})
        self.mac.ps = f"601 claude --session-id {A} --remote-control\n"

        def terminate(pid):
            self.mac.terminated.append(pid)
            self.mac.ps = ""

        self.mac.terminate = terminate
        self.mac.git_runner.answers = lambda words: standins.result(stdout="origin/main\n") if "symbolic-ref" in words else None
        self.file.write_text('terminal = "kitty"\n')
        self.printed.clear()
        return shop

    def test_uninstall_works_with_a_configuration_that_does_not_parse(self):
        shop = self.broken_after_a_free_session()

        self.assertEqual(self.run_cli("uninstall", "--servers"), 0)

        self.assertEqual(self.mac.launchctl.loaded, set())
        self.assertEqual(list((self.root / "agents").iterdir()), [])
        self.assertEqual(self.mac.terminated, [601], "the free session of a folder of the state")
        self.assertEqual(self.mac.store(shop, ready_sessions.STATE).load({})["sessions"], {})
        self.assertEqual(
            self.printed[:5],
            [
                "The configuration %s has problems:" % self.file,
                'terminal: unknown terminal "kitty"; one of: warp',
                "The file could not be read: the agents are found by their labels, and the free sessions in the "
                "folders of the state.",
                SERVICE_LABEL + ": unloaded and removed",
                SHOP + ": unloaded and removed",
            ],
        )

    def test_uninstall_purge_keeps_a_configuration_file_it_could_not_read(self):
        self.broken_after_a_free_session()

        self.assertEqual(self.run_cli("uninstall", "--servers", "--purge"), 1, "not everything asked for was removed")

        self.assertEqual(self.file.read_text(), 'terminal = "kitty"\n', "it may be a file named by mistake")
        self.assertFalse((self.root / "state").exists())
        self.assertEqual(
            self.printed[-2:],
            ["The configuration file %s was kept: it could not be read." % self.file, "Removed the state and the logs."],
        )

    def test_a_label_that_is_no_reverse_domain_name_is_a_usage_error_before_anything_changes(self):
        self.configure(shop=("server",))
        self.run_cli("apply")
        files = sorted(path.name for path in (self.root / "agents").iterdir())
        self.mac.launchctl.calls.clear()
        self.printed.clear()
        self.mac.environ["PORCHLIGHT_LABEL"] = "../../escape"

        every = (["status"], ["doctor"], ["apply", "--servers"], ["start"], ["stop", "--servers"])
        every += (["uninstall", "--servers", "--purge"], ["run", "--once"])
        for command in every:
            self.assertEqual(self.run_cli(*command), 2, command)
            self.assertIn("usage: porchlight", self.errors)
            self.assertIn("PORCHLIGHT_LABEL must be a reverse domain name", self.errors)

        self.assertEqual(self.printed, [])
        self.assertEqual(self.mac.launchctl.calls, [])
        self.assertEqual(sorted(path.name for path in (self.root / "agents").iterdir()), files)
        self.assertTrue(self.file.exists())

    def test_root_is_refused_by_the_commands_that_change_launchd_or_delete_files(self):
        self.configure(shop=("server",))
        self.run_cli("apply")
        self.mac.launchctl.calls.clear()
        self.mac.uid = 0

        for command in (["apply", "--servers"], ["start"], ["stop", "--servers"], ["uninstall", "--servers", "--purge"]):
            self.printed.clear()
            self.assertEqual(self.run_cli(*command), 1, command)
            self.assertEqual(len(self.printed), 1)
            self.assertIn("without sudo", self.printed[0])

        self.assertEqual(self.mac.launchctl.calls, [])
        self.assertTrue(self.file.exists())

    def test_root_is_refused_by_the_service_and_the_server_which_tidy_the_persons_files(self):
        self.configure(shop=("server",))
        self.mac.uid = 0

        with mock.patch.object(cli.service, "run") as service, mock.patch.object(cli.project_server, "run") as server:
            for command in (["run", "--once"], ["server", "shop"]):
                self.printed.clear()
                self.assertEqual(self.run_cli(*command), 1, command)
                self.assertEqual(self.printed, [agents.AS_ROOT])

        service.assert_not_called()
        server.assert_not_called()


class OneConfigurationFile(CommandLine):
    def test_the_mac_of_a_command_hands_out_the_file_the_command_read(self):
        self.configure(shop=("server",))

        with mock.patch.object(cli.Mac, "of", return_value=self.mac) as of:
            code = cli.main(["status", "--config", str(self.file)], out=self.printed.append)

        self.assertEqual(code, 0)
        of.assert_called_once_with(self.configuration, config_file=str(self.file))


if __name__ == "__main__":
    unittest.main()
