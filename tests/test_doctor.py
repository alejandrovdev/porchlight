"""Tests of the checks `doctor` runs: this Mac's, then what each project's features need on
it. Git, the tools, the terminal, launchctl and what `claude --help` and `claude auth status`
print are stand-ins: nothing is run."""

import json
import tempfile
import unittest
from pathlib import Path

from porchlight import agents, config, doctor
from porchlight.atoms import launchd
from tests import standins

# As Claude Code prints it: the choices run over several lines, and another option's
# description names an option at the start of a line.
HELP = """Usage: claude [options] [command] [prompt]

Options:
  --output-format <format>              Output format (only works with --print)
                                        (choices: "text", "json", "stream-json")
  --permission-mode <mode>              Permission mode to use for the session
                                        (choices: "acceptEdits", "auto",
                                        "bypassPermissions", "manual",
                                        "dontAsk", "plan")
  --permission-prompts <target>         Who answers permission prompts with
                                        no terminal (see also
                                        --permission-prompt-tool) or "none"
  -v, --version                         Output the version number
"""
MODES = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
# What asks the installed Claude Code whether someone is signed in. It exits 1 when no one
# is, so a shell runs it and always ends well: its answer is read either way.
SIGN_IN = ["/tools/claude", "auth", "status", "--json"]
# As `claude auth status --json` answers, with made-up account details doctor never prints.
ACCOUNT = {"email": "someone@example.com", "orgName": "Example Org", "orgId": "org-0000", "planTier": "plan-x"}
SIGNED_IN = json.dumps(dict(ACCOUNT, loggedIn=True, authMethod="claude.ai", apiProvider="firstParty"))
SIGNED_OUT = json.dumps({"loggedIn": False, "authMethod": "none", "apiProvider": "firstParty"})


class PermissionModes(unittest.TestCase):
    def test_reads_the_choices_of_the_option_over_several_lines(self):
        self.assertEqual(doctor.permission_modes(HELP), MODES)

    def test_reads_only_that_options_choices(self):
        without = HELP.replace(
            '(choices: "acceptEdits", "auto",\n'
            '                                        "bypassPermissions", "manual",\n'
            '                                        "dontAsk", "plan")\n',
            "\n",
        )

        self.assertIsNone(doctor.permission_modes(without), "the choices of another option are not its own")

    def test_knows_nothing_when_the_text_does_not_say(self):
        for text in (None, "", "Usage: claude\n", "  --permission-mode <mode>  Permission mode\n"):
            self.assertIsNone(doctor.permission_modes(text))


class Scratch(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.terminal = standins.Terminal()
        self.mac = standins.StandInMac(self.root, self.terminal)
        self.mac.git_runner.answers = self.git
        self.mac.outputs["/tools/claude --help"] = HELP
        self.mac.outputs[" ".join(SIGN_IN)] = SIGNED_IN
        self.repositories = True
        self.default_branch = "origin/trunk"
        self.printed = []

    def tearDown(self):
        self.scratch.cleanup()

    def git(self, words):
        if "--is-inside-work-tree" in words:
            return standins.result(stdout="true\n") if self.repositories else standins.result(returncode=128)
        if "symbolic-ref" in words:
            return standins.result(stdout=self.default_branch + "\n") if self.default_branch else standins.result(1)

    def project(self, name="shop", features=None, make=True, mode="plan", base=None):
        if make:
            (self.root / name).mkdir(exist_ok=True)
        return standins.project(name, str(self.root / name), mode=mode, base=base, features=features)

    def checks(self, project):
        return [(check.state, check.what, check.advice) for check in doctor.checks(project, self.mac)]

    def states(self, project):
        return {check.what: check.state for check in doctor.checks(project, self.mac)}

    def report(self, *projects):
        return doctor.report(config.Config("warp", projects), self.mac, out=self.printed.append)

    def install(self, *projects):
        """Write and load the agents of a configuration, as `apply` does."""
        self.assertEqual(agents.apply(config.Config("warp", projects), self.mac, out=[].append), 0)
        self.mac.launchctl.calls.clear()

    def section(self, heading):
        """The lines printed under a heading, up to the blank line that ends them."""
        start = self.printed.index(heading) + 1
        end = self.printed.index("", start) if "" in self.printed[start:] else len(self.printed)
        return self.printed[start:end]


class Checks(Scratch):
    def test_a_project_with_everything_in_place_passes_every_check(self):
        shop = self.project()

        self.assertEqual(
            self.checks(shop),
            [
                ("ok", "folder %s" % shop.directory, ""),
                ("ok", "Claude Code (claude) at /tools/claude", ""),
                ("ok", "git at /tools/git", ""),
                ("ok", "tmux at /tools/tmux", ""),
                ("ok", "Stand-in, the terminal its tabs open in", ""),
                ("ok", "git repository", ""),
                ("ok", "base branch origin/trunk", ""),
                ("ok", 'permission mode "plan"', ""),
            ],
        )

    def test_a_folder_that_is_missing_is_said_and_nothing_is_asked_of_it(self):
        shop = self.project(make=False)

        checks = self.checks(shop)

        self.assertEqual(
            checks[0],
            ("missing", "folder %s" % shop.directory, "create it, or correct `path` of the project in the configuration"),
        )
        self.assertNotIn("git repository", [what for _, what, _ in checks])
        self.assertEqual(self.mac.git_runner.calls, [], "git is not asked about a folder that is not there")

    def test_a_folder_that_is_no_git_repository_is_a_problem(self):
        self.repositories = False
        shop = self.project()

        checks = self.checks(shop)

        self.assertIn(
            ("problem", "git repository", "%s is not one: run `git init` in it, or correct `path`" % shop.directory),
            checks,
        )
        self.assertFalse([what for _, what, _ in checks if what.startswith("base branch")], "and it has no branch")

    def test_names_the_command_that_installs_a_missing_tool(self):
        del self.mac.found["tmux"]
        del self.mac.found["git"]

        checks = self.checks(self.project())

        self.assertIn(("missing", "tmux", "install it with: brew install tmux"), checks)
        self.assertIn(("missing", "git", "install it with: brew install git"), checks)
        self.assertNotIn("git repository", [what for _, what, _ in checks], "without git nothing is asked of it")

    def test_says_claude_code_is_installed_separately_and_gives_no_address(self):
        del self.mac.found["claude"]

        checks = self.checks(self.project())

        ((state, what, advice),) = [check for check in checks if check[1].startswith("Claude Code")]
        self.assertEqual((state, what), ("missing", "Claude Code (claude)"))
        self.assertIn("installed separately", advice)
        self.assertNotIn("brew", advice)
        self.assertNotIn("http", advice)
        self.assertFalse([what for _, what, _ in checks if what.startswith("permission mode")])
        self.assertEqual(self.mac.asked, [], "a tool that is not there is not run")

    def test_asks_only_for_what_the_projects_features_need(self):
        server = self.project("blog", features=("server", "resume-list"))

        self.assertEqual(
            [what for _, what, _ in self.checks(server)],
            [
                "folder %s" % server.directory,
                "Claude Code (claude) at /tools/claude",
                "git at /tools/git",
                "git repository",
                'permission mode "plan"',
            ],
            "no tmux, no terminal and no base branch: nothing it has makes a worktree",
        )

        nothing = self.project("docs", features=("keep-awake",))
        self.mac.git_runner.calls.clear()
        self.assertEqual([what for _, what, _ in self.checks(nothing)], ["folder %s" % nothing.directory])
        self.assertEqual(self.mac.git_runner.calls, [])

    def test_the_terminal_is_asked_for_only_with_tabs_and_missing_when_its_app_is_not_installed(self):
        self.terminal.is_installed = False

        without = self.states(self.project("blog", features=("ready-session", "reopen")))
        with_tabs = self.checks(self.project())

        self.assertNotIn("Stand-in", without)
        self.assertIn(("missing", "Stand-in", "install the Stand-in app, or turn off `tabs` for this project"), with_tabs)
        self.assertEqual(self.terminal.asked, 0, "whether it runs is not doctor's question")

    def test_tabs_without_a_terminal_set_up_are_a_problem(self):
        self.mac.terminal = None

        self.assertIn(
            ("problem", "terminal", "set `terminal` in the configuration: tabs open in it"), self.checks(self.project())
        )

    def test_a_base_branch_that_cannot_be_determined_is_a_problem_until_the_project_sets_one(self):
        self.default_branch = None

        self.assertIn(
            ("problem", "base branch", "none could be determined: set `base` for the project in the configuration"),
            self.checks(self.project()),
        )
        self.assertEqual(self.states(self.project(base="origin/main"))["base branch origin/main"], "ok")

    def test_a_permission_mode_the_installed_claude_does_not_list_is_a_problem(self):
        checks = self.checks(self.project(mode="reckless"))

        self.assertIn(
            (
                "problem",
                'permission mode "reckless"',
                "claude lists: %s; correct `permission_mode` of the project" % ", ".join(MODES),
            ),
            checks,
        )
        self.assertEqual(self.mac.asked, [["/tools/claude", "--help"]])

    def test_modes_that_cannot_be_read_leave_the_mode_unknown_and_fail_nothing(self):
        self.install(self.project())
        for text in (None, "Usage: claude\n"):
            self.mac.outputs["/tools/claude --help"] = text
            shop = self.project()

            checks = doctor.checks(shop, self.mac)

            (mode,) = [check for check in checks if check.what.startswith("permission mode")]
            self.assertEqual((mode.state, mode.failed), ("unknown", False))
            self.assertEqual(mode.advice, "the modes `claude --help` lists could not be read")
            self.assertEqual(self.report(shop), 0)


class Report(Scratch):
    def test_prints_this_macs_checks_then_one_line_for_each_check_under_the_projects_name_and_exits_zero(self):
        shop, blog = self.project(), self.project("blog", features=("server",))
        self.install(shop, blog)

        self.assertEqual(self.report(shop, blog), 0)

        self.assertEqual(
            self.printed[:4],
            ["This Mac", "  ok       Claude Code sign-in", "  ok       service agent %s" % standins.LABEL, ""],
        )
        self.assertEqual(self.printed[4], "shop")
        self.assertEqual(self.printed[5], "  ok       folder %s" % shop.directory)
        self.assertEqual(self.printed[8], "  ok       tmux at /tools/tmux")
        self.assertEqual(self.printed[12], '  ok       permission mode "plan"')
        self.assertEqual(self.printed[13], "  ok       server agent %s.server.shop" % standins.LABEL)
        self.assertEqual(self.printed[14:16], ["", "blog"])
        self.assertTrue(all(line.startswith("  ok ") for line in self.printed[16:]))
        self.assertEqual(self.printed[-1], "  ok       server agent %s.server.blog" % standins.LABEL)
        self.assertEqual(len(self.printed), 22)
        self.assertEqual(self.mac.asked, [SIGN_IN, ["/tools/claude", "--help"]], "claude is asked once for every project")
        self.assertEqual(self.mac.launchctl.did(), [], "launchd is only asked")

    def test_exits_one_when_a_check_fails_and_says_what_to_do(self):
        del self.mac.found["tmux"]
        shop, blog = self.project(), self.project("blog", make=False, features=("server",))

        self.assertEqual(self.report(shop, blog), 1)

        self.assertIn("  missing  tmux: install it with: brew install tmux", self.printed)
        self.assertIn(
            "  missing  folder %s: create it, or correct `path` of the project in the configuration" % blog.directory,
            self.printed,
        )

    def test_one_project_whose_checks_fail_to_run_does_not_stop_the_next(self):
        shop, blog = self.project(), self.project("blog", features=("server",))
        real = self.mac.tool
        self.mac.tool = lambda name: (_ for _ in ()).throw(RuntimeError("broken")) if name == "tmux" else real(name)

        self.assertEqual(self.report(shop, blog), 1)

        self.assertEqual(self.section("shop"), ["  problem  its checks could not run: RuntimeError('broken')"])
        self.assertIn("blog", self.printed)

    def test_without_a_project_checks_the_sign_in_only_then_says_how_to_add_one(self):
        self.assertEqual(self.report(), 0)

        self.assertEqual(
            self.printed,
            [
                "This Mac",
                "  ok       Claude Code sign-in",
                "",
                "No project is configured. Add one from its folder with: porchlight init",
            ],
            "the service exists only with a project, so its agent is not asked for",
        )
        self.assertEqual(self.mac.launchctl.calls, [])


class SignIn(Scratch):
    def test_signed_in_is_ok_and_no_account_detail_is_printed(self):
        shop = self.project()
        self.install(shop)

        self.assertEqual(self.report(shop), 0)

        self.assertEqual(self.section("This Mac")[0], "  ok       Claude Code sign-in")
        self.assertIn(SIGN_IN, self.mac.asked)
        for detail in ACCOUNT.values():
            self.assertFalse([line for line in self.printed if detail in line], detail)

    def test_no_one_signed_in_is_a_problem_that_says_how_to_sign_in(self):
        self.mac.outputs[" ".join(SIGN_IN)] = SIGNED_OUT
        shop = self.project()
        self.install(shop)

        self.assertEqual(self.report(shop), 1)

        self.assertEqual(
            self.section("This Mac")[0], "  problem  Claude Code sign-in: no one is signed in: run `claude auth login`"
        )
        self.assertTrue(all(line.startswith("  ok ") for line in self.section("shop")), "only the sign-in failed")

    def test_without_claude_the_tool_check_says_so_and_the_sign_in_is_not_asked(self):
        del self.mac.found["claude"]
        shop = self.project()
        self.install(shop)

        self.assertEqual(self.report(shop), 1)

        self.assertFalse([line for line in self.printed if "sign-in" in line])
        self.assertEqual([line for line in self.printed if "Claude Code" in line], ["  missing  Claude Code (claude): " + doctor.INSTALL["claude"]])
        self.assertEqual(self.mac.asked, [])

    def test_an_answer_that_cannot_be_read_leaves_it_unknown_and_fails_nothing(self):
        shop = self.project()
        self.install(shop)
        for answer in (None, "", "not json", "[]", '{"other": true}', '{"loggedIn": "yes"}'):
            self.mac.outputs[" ".join(SIGN_IN)] = answer
            self.printed.clear()

            self.assertEqual(self.report(shop), 0, answer)

            self.assertEqual(
                self.section("This Mac")[0], "  unknown  Claude Code sign-in: `claude auth status` could not say", answer
            )


class LoginAgents(Scratch):
    def setUp(self):
        super().setUp()
        self.shop = self.project()
        self.blog = self.project("blog", features=("ready-session",))
        self.install(self.shop, self.blog)
        self.server = "%s.server.shop" % standins.LABEL

    def agent_lines(self):
        return [line for line in self.printed if " agent " in line]

    def test_loaded_agents_are_ok_and_only_a_project_with_server_has_a_server_line(self):
        self.assertEqual(self.report(self.shop, self.blog), 0)

        self.assertEqual(
            self.agent_lines(),
            ["  ok       service agent %s" % standins.LABEL, "  ok       server agent %s" % self.server],
        )
        self.assertIn("  ok       service agent %s" % standins.LABEL, self.section("This Mac"))
        self.assertIn("  ok       server agent %s" % self.server, self.section("shop"))
        self.assertFalse([line for line in self.section("blog") if " agent " in line])

    def test_an_agent_that_is_not_loaded_is_a_problem_porchlight_start_fixes(self):
        self.mac.launchctl.loaded.clear()

        self.assertEqual(self.report(self.shop, self.blog), 1)

        self.assertEqual(
            self.agent_lines(),
            [
                "  problem  service agent %s: not loaded: run `porchlight start`" % standins.LABEL,
                "  problem  server agent %s: not loaded: run `porchlight start`" % self.server,
            ],
        )
        self.assertEqual(self.mac.launchctl.did(), [], "nothing is loaded")

    def test_an_agent_whose_file_is_missing_is_a_problem_porchlight_apply_fixes(self):
        for label in (standins.LABEL, self.server):
            launchd.file(self.mac.launch_agents, label).unlink()

        self.assertEqual(self.report(self.shop, self.blog), 1)

        self.assertEqual(
            self.agent_lines(),
            [
                "  problem  service agent %s: its file is missing: run `porchlight apply`" % standins.LABEL,
                "  problem  server agent %s: its file is missing: run `porchlight apply`" % self.server,
            ],
        )

    def test_when_launchd_cannot_say_the_agents_are_unknown_and_fail_nothing(self):
        self.mac.launchctl.lists = False

        self.assertEqual(self.report(self.shop, self.blog), 0)

        self.assertEqual(
            self.agent_lines(),
            [
                "  unknown  service agent %s: launchd could not say whether it is loaded" % standins.LABEL,
                "  unknown  server agent %s: launchd could not say whether it is loaded" % self.server,
            ],
        )
        self.assertFalse([line for line in self.printed if "Nothing was changed" in line])


if __name__ == "__main__":
    unittest.main()
