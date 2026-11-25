"""Tests of `setup`, `init` and `deinit`: the screens each one asks, what it writes and what
it asks of launchd. The person is a stand-in that presses keys, the Mac a stand-in and the
configuration a scratch file: no curses starts, nothing is loaded and no session runs."""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from porchlight import agents, cli, config, names
from porchlight.atoms import worktrees
from porchlight.features import ready_sessions
from porchlight.ui.widgets import BACKSPACE, CTRL_C, DOWN, ENTER, SPACE, Choice, Confirm, TextField
from tests import standins
from tests.test_doctor import HELP, MODES

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
LIVE = "cse_01AAA"
SERVICE = standins.LABEL
SHOP = standins.LABEL + ".server.shop"
BLOG = standins.LABEL + ".server.blog"
CLAUDE_HELP = "/tools/claude --help"
NEXT_READY = (
    "Next: on the phone, the ready session appears in the app's session list. See it here with: porchlight status"
)
NEXT_SERVER = "Next: on the phone, create a session on this Mac from the app. See it here with: porchlight status"


class Linking(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.scratch.name))
        self.file = self.root / "config.toml"
        self.mac = standins.StandInMac(self.root, standins.Terminal())
        self.mac.outputs[CLAUDE_HELP] = HELP
        self.repositories = []
        self.mac.git_runner.answers = self.git
        self.printed = []
        self.errors = ""
        self.keys = None

    def tearDown(self):
        self.scratch.cleanup()

    def repository(self, name):
        """A folder that git takes for a repository's top level."""
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        self.repositories.append(folder)
        return folder

    def git(self, words):
        if "--show-toplevel" in words:
            asked = Path(words[words.index("-C") + 1])
            for folder in self.repositories:
                if asked == folder or folder in asked.parents:
                    return standins.result(stdout=str(folder) + "\n")
            return standins.result(128, stderr="fatal: not a git repository (or any of the parent directories): .git\n")
        if "symbolic-ref" in words:
            return standins.result(stdout="origin/main\n")

    def configure(self, terminal="warp", defaults=config.Defaults(), **projects):
        """Write a configuration: each project with the features given, in a repository of its own."""
        configured = []
        for name, features in projects.items():
            folder = self.repository(name)
            configured.append(config.Project(name, str(folder), "plan", config.ordered(features), None, name))
        configuration = config.Config(terminal, tuple(configured), defaults)
        config.save(configuration, self.file)
        return configuration

    def run_cli(self, *arguments, keys=None):
        """Run a command against the scratch configuration, the keys pressed by `keys` (by
        default nobody is at a terminal): its exit code."""
        self.keys = keys if keys is not None else standins.Keys(terminal=False)
        words = list(arguments) + ["--config", str(self.file)]
        errors, output = io.StringIO(), io.StringIO()
        with redirect_stderr(errors), redirect_stdout(output):
            code = cli.main(words, mac=self.mac, out=self.printed.append, asker=self.keys)
        self.errors = errors.getvalue()
        self.printed.extend(output.getvalue().splitlines())
        return code

    def saved(self):
        return config.load(self.file)

    def files(self):
        return sorted(path.name for path in (self.root / "agents").glob("*.plist"))


class Setup(Linking):
    def test_asks_the_prerequisites_the_terminal_the_mode_the_features_and_a_summary(self):
        keys = standins.Keys(ENTER, ENTER, DOWN, DOWN, DOWN, ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("setup", keys=keys), 0)

        self.assertEqual(
            keys.titles(),
            ["Prerequisites", "Terminal", "Default permission mode", "Default features", "Keep the Mac awake", "Summary"],
        )
        self.assertEqual(self.saved(), config.Config("warp", (), config.Defaults("manual", config.PRESETS["recommended"])))
        self.assertEqual(self.mac.launchctl.did(), [], "no project: nothing to load")
        self.assertEqual(self.printed[-1], "Next: in a project's folder, run: porchlight init")

    def test_asks_when_to_keep_the_mac_awake_once_a_default_feature_or_a_project_has_keep_awake(self):
        keys = standins.Keys(ENTER, ENTER, ENTER, ENTER, DOWN, ENTER, "y")

        self.assertEqual(self.run_cli("setup", keys=keys), 0)

        self.assertEqual(
            keys.titles(),
            ["Prerequisites", "Terminal", "Default permission mode", "Default features", "Keep the Mac awake", "Summary"],
        )
        self.assertEqual([item.value for item in keys.last("Keep the Mac awake").items], ["always", "plugged-in"])
        self.assertEqual(self.saved().keep_awake, "plugged-in")
        self.assertIn("Keep the Mac awake: only on AC power", keys.last("Summary").body)

    def test_keep_awake_is_not_asked_when_nothing_has_the_feature(self):
        self.assertEqual(self.run_cli("setup", "--feature", "server", "--terminal", "warp", "--permission-mode", "plan", "--yes"), 0)

        self.assertIsNone(self.saved().keep_awake, "nothing chosen: nothing written")

    def test_the_keep_awake_flag_answers_its_screen(self):
        self.assertEqual(self.run_cli("setup", "--terminal", "warp", "--permission-mode", "plan", "--keep-awake", "plugged-in", "--yes"), 0)
        self.assertEqual(self.saved().keep_awake, "plugged-in")

        self.assertEqual(self.run_cli("setup", "--yes"), 0)
        self.assertEqual(self.saved().keep_awake, "plugged-in", "a later setup starts from it")

    def test_the_prerequisites_are_the_doctor_checks_of_each_tool_and_terminal_app_and_nothing_is_installed(self):
        del self.mac.found["tmux"]
        self.mac.apps["warp"].is_installed = False
        keys = standins.Keys("q")

        self.assertEqual(self.run_cli("setup", keys=keys), 1)

        body = keys.last("Prerequisites").body
        self.assertIn("ok       Claude Code (claude) at /tools/claude", body)
        self.assertIn("ok       git at /tools/git", body)
        self.assertIn("missing  tmux: install it with: brew install tmux", body)
        self.assertTrue([line for line in body if line.startswith("missing  Warp: install the Warp app")], body)
        self.assertEqual((self.mac.git_runner.calls, self.mac.tmux_runner.calls, self.mac.spawned), ([], [], []))

    def test_the_terminal_screen_lists_the_supported_terminals_and_marks_the_installed_ones(self):
        keys = standins.Keys(ENTER, "q")
        self.run_cli("setup", keys=keys)

        terminals = keys.last("Terminal")
        self.assertEqual([item.value for item in terminals.items], list(config.TERMINALS) + ["none"])
        self.assertEqual(terminals.items[0].note, "installed")
        self.assertEqual(terminals.current, None, "a first setup starts on the first terminal, not on none")

        self.mac.apps["warp"].is_installed = False
        keys = standins.Keys(ENTER, "q")
        self.run_cli("setup", keys=keys)

        self.assertEqual(keys.last("Terminal").items[0].note, "not installed")

    def test_choosing_no_terminal_saves_none_and_a_rerun_preselects_it(self):
        keys = standins.Keys(ENTER, DOWN, ENTER, ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("setup", keys=keys), 0)

        self.assertIsNone(self.saved().terminal)
        self.assertNotIn("terminal", self.file.read_text())
        keys = standins.Keys(ENTER, ENTER, ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("setup", keys=keys), 0)

        self.assertEqual(keys.last("Terminal").current, "none")
        self.assertIsNone(self.saved().terminal)

    def test_no_terminal_is_not_offered_while_a_linked_project_opens_tabs(self):
        self.configure(shop=("ready-session", "tabs"))
        keys = standins.Keys(ENTER, "q")

        self.run_cli("setup", keys=keys)

        self.assertEqual([item.value for item in keys.last("Terminal").items], list(config.TERMINALS))

    def test_the_terminal_flag_takes_none_unless_a_linked_project_opens_tabs(self):
        flags = ["--terminal", "none", "--permission-mode", "plan", "--preset", "minimal", "--yes"]

        self.assertEqual(self.run_cli("setup", *flags), 0)

        self.assertEqual(self.saved(), config.Config(None, (), config.Defaults("plan", ("server",))))
        self.configure(defaults=config.Defaults("plan", ("server",)), shop=("ready-session", "tabs"))
        self.printed.clear()

        self.assertEqual(self.run_cli("setup", *flags), 1)

        self.assertEqual(self.printed, ['terminal: required by "tabs" of the project "shop"', "Nothing was changed."])
        self.assertEqual(self.saved().terminal, "warp")

    def test_the_permission_modes_are_those_claude_lists_and_none_is_preselected(self):
        keys = standins.Keys(ENTER, ENTER, "q")

        self.run_cli("setup", keys=keys)

        modes = keys.last("Default permission mode")
        self.assertIsInstance(modes, Choice)
        self.assertEqual(tuple(item.value for item in modes.items), MODES)
        self.assertIsNone(modes.current)
        self.assertEqual(self.mac.asked, [["/tools/claude", "--help"]])

    def test_modes_that_cannot_be_read_are_typed(self):
        del self.mac.outputs[CLAUDE_HELP]
        keys = standins.Keys(ENTER, ENTER, "p", "l", "a", "n", ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("setup", keys=keys), 0)

        self.assertIsInstance(keys.last("Default permission mode"), TextField)
        self.assertEqual(self.saved().defaults.permission_mode, "plan")

    def test_the_features_start_from_the_recommended_preset(self):
        keys = standins.Keys(ENTER, ENTER, ENTER, "q")

        self.run_cli("setup", keys=keys)

        self.assertEqual(keys.last("Default features").checked, set(config.FEATURES))

    def test_a_rerun_preselects_the_current_values(self):
        self.configure(defaults=config.Defaults("plan", ("server",)))
        keys = standins.Keys(ENTER, ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("setup", keys=keys), 0)

        self.assertEqual(keys.last("Terminal").current, "warp")
        self.assertEqual(keys.last("Default permission mode").current, "plan")
        self.assertEqual(keys.last("Default features").checked, {"server"})
        self.assertEqual(self.saved().defaults, config.Defaults("plan", ("server",)))

    def test_saving_keeps_the_projects_and_applies_without_touching_their_running_servers(self):
        configuration = self.configure(shop=("server",))
        agents.apply(configuration, self.mac, lambda line: None)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"  # every definition changes
        self.mac.launchctl.calls.clear()
        keys = standins.Keys(ENTER, ENTER, ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("setup", keys=keys), 0)

        self.assertEqual([project.name for project in self.saved().projects], ["shop"])
        self.assertEqual(self.saved().defaults, config.Defaults("acceptEdits", config.PRESETS["recommended"]))
        self.assertNotIn(("unload", SHOP), self.mac.launchctl.did())
        self.assertIn(SHOP + ": left running as it is, though its definition changed", self.printed)
        self.assertNotIn("Next: in a project's folder, run: porchlight init", self.printed)

    def test_quitting_or_answering_no_changes_nothing(self):
        for keys in (
            standins.Keys("q"),
            standins.Keys(ENTER, CTRL_C),
            standins.Keys(ENTER, ENTER, ENTER, ENTER, ENTER, "n"),
        ):
            self.printed.clear()

            self.assertEqual(self.run_cli("setup", keys=keys), 1)

            self.assertFalse(self.file.exists())
            self.assertEqual(self.printed, ["Nothing was changed."])

    def test_flags_and_yes_ask_nothing(self):
        arguments = ["--terminal", "warp", "--permission-mode", "plan", "--feature", "server"]

        self.assertEqual(self.run_cli("setup", *arguments, "--feature", "resume-list", "--yes"), 0)

        self.assertEqual(self.keys.asked, 0)
        self.assertEqual(self.saved(), config.Config("warp", (), config.Defaults("plan", ("server", "resume-list"))))

    def test_yes_takes_the_current_values_for_what_no_flag_gives(self):
        self.configure(defaults=config.Defaults("plan", ("server",)))

        self.assertEqual(self.run_cli("setup", "--yes"), 0)

        self.assertEqual(self.saved().defaults, config.Defaults("plan", ("server",)))

    def test_without_a_terminal_a_missing_answer_is_a_usage_error_naming_its_flag(self):
        for arguments, flag in (
            (["--terminal", "warp", "--yes"], "--permission-mode"),
            (["--permission-mode", "plan", "--preset", "minimal", "--yes"], "--terminal"),
            (["--terminal", "warp", "--permission-mode", "plan", "--preset", "minimal"], "--yes"),
        ):
            self.assertEqual(self.run_cli("setup", *arguments), 2, arguments)

            self.assertIn("usage: porchlight setup", self.errors)
            self.assertIn("[--yes]", self.errors, "the usage has the command's own flags")
            self.assertIn(flag, self.errors.splitlines()[-1])
            self.assertFalse(self.file.exists())

    def test_flags_are_checked_before_anything_is_asked(self):
        for arguments, problem in (
            (["--permission-mode", "sometimes"], "claude lists"),
            (["--permission-mode", "two words"], "one word"),
            (["--feature", "live-view"], '"live-view" needs "server"'),
            (["--preset", "minimal", "--feature", "server"], "not allowed with"),
            (["--terminal", "kitty"], "invalid choice"),
        ):
            keys = standins.Keys()

            self.assertEqual(self.run_cli("setup", *arguments, keys=keys), 2, arguments)

            self.assertIn(problem, self.errors)
            self.assertEqual(keys.asked, 0)


class Init(Linking):
    def test_outside_a_git_repository_it_refuses_saying_why(self):
        folder = self.root / "notes"
        folder.mkdir()

        self.assertEqual(self.run_cli("init", str(folder), keys=standins.Keys()), 1)

        self.assertEqual(
            self.printed,
            [
                "%s is not in a git repository, and the features need one: run `git init` in it first. "
                "Nothing was changed." % folder
            ],
        )
        self.assertFalse(self.file.exists())

    def test_without_setup_it_asks_everything_then_saves_applies_and_says_what_next(self):
        shop = self.repository("shop")
        keys = standins.Keys(ENTER, DOWN, DOWN, DOWN, ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("init", str(shop), keys=keys), 0)

        self.assertEqual(keys.titles(), ["Project name", "Permission mode", "Features", "Terminal", "Summary"])
        project = config.Project("shop", str(shop), "manual", tuple(config.FEATURES), None, "shop")
        self.assertEqual(self.saved(), config.Config("warp", (project,)))
        self.assertEqual(self.mac.launchctl.did(), [("load", SERVICE), ("load", SHOP)])
        self.assertIn(SHOP + ": loaded", self.printed)
        self.assertEqual(self.printed[-1], NEXT_READY)

    def test_a_folder_inside_a_repository_links_the_repository(self):
        shop = self.repository("shop")
        inner = shop / "src" / "pages"
        inner.mkdir(parents=True)

        self.assertEqual(self.run_cli("init", str(inner), "--permission-mode", "plan", "--preset", "minimal", "--yes"), 0)

        (project,) = self.saved().projects
        self.assertEqual((project.name, project.path), ("shop", str(shop)))
        self.assertEqual(self.printed[-1], NEXT_SERVER)

    def test_the_suggested_name_is_the_folders_made_valid_and_unique(self):
        self.configure(**{"my-shop-app": ("server",)})
        for folder, suggested in (
            ("My Shop_App!", "my-shop-app-2"),
            ("Very Long Folder Name For A Project Of Ours", "very-long-folder-name-for-a-proj"),
        ):
            keys = standins.Keys(CTRL_C)

            self.assertEqual(self.run_cli("init", str(self.repository(folder)), keys=keys), 1)

            self.assertEqual(keys.last("Project name").value, suggested)

    def test_the_name_is_checked_when_it_is_accepted(self):
        self.configure(blog=("server",))
        keys = standins.Keys(*[BACKSPACE] * 4, "b", "l", "o", "g", ENTER, CTRL_C)

        self.run_cli("init", str(self.repository("shop")), keys=keys)

        self.assertEqual(keys.last("Project name").error, 'the project "blog" already has this name')

    def test_the_screens_start_from_the_defaults(self):
        self.configure(defaults=config.Defaults("plan", ("server", "resume-list")))
        shop = self.repository("shop")
        keys = standins.Keys(ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("init", str(shop), keys=keys), 0)

        self.assertEqual(keys.titles(), ["Project name", "Permission mode", "Features", "Summary"], "a terminal is set")
        self.assertEqual(keys.last("Permission mode").current, "plan")
        self.assertEqual(keys.last("Features").checked, {"server", "resume-list"})
        (project,) = self.saved().projects
        self.assertEqual((project.permission_mode, project.features), ("plan", ("server", "resume-list")))

    def test_the_terminal_is_asked_only_when_the_features_need_one_and_none_is_set(self):
        config.save(config.Config(None, (), config.Defaults("plan", ("server",))), self.file)
        keys = standins.Keys(ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("init", str(self.repository("shop")), keys=keys), 0)

        self.assertNotIn("Terminal", keys.titles())
        self.assertIsNone(self.saved().terminal)
        blog = self.repository("blog")
        self.assertEqual(self.run_cli("init", str(blog), "--preset", "recommended", "--yes"), 2)
        self.assertIn("--terminal", self.errors.splitlines()[-1])
        self.assertEqual(self.run_cli("init", str(blog), "--preset", "recommended", "--terminal", "warp", "--yes"), 0)
        self.assertEqual(self.saved().terminal, "warp")

    def test_a_linked_folder_shows_its_current_values_and_is_replaced_in_place(self):
        self.configure(shop=("server",), blog=("server",))
        keys = standins.Keys(ENTER, ENTER, DOWN, DOWN, DOWN, DOWN, DOWN, SPACE, ENTER, "y")

        self.assertEqual(self.run_cli("init", str(self.root / "shop"), keys=keys), 0)

        self.assertEqual(keys.last("Project name").value, "shop")
        self.assertEqual(keys.last("Permission mode").current, "plan")
        self.assertEqual(keys.last("Features").checked, {"server", "resume-list"})
        shop, blog = self.saved().projects
        self.assertEqual((shop.name, shop.path, shop.features), ("shop", str(self.root / "shop"), ("server", "resume-list")))
        self.assertEqual(blog.name, "blog")

    def test_a_new_name_for_a_linked_folder_says_it_renames_that_project(self):
        self.configure(shop=("server",))
        keys = standins.Keys(*[BACKSPACE] * 4, "s", "t", "o", "r", "e", ENTER, ENTER, ENTER, "y")

        self.assertEqual(self.run_cli("init", str(self.root / "shop"), keys=keys), 0)

        summary = keys.last("Summary")
        self.assertEqual(summary.question, "Rename it?")
        self.assertIn(
            'This folder is linked already, as "shop": this renames that project to "store".', summary.body
        )
        self.assertIn('Renamed "shop" to "store".', self.printed)

    def test_renaming_a_project_whose_server_runs_says_the_old_server_holds_the_folder(self):
        configuration = self.configure(shop=("server",))
        agents.apply(configuration, self.mac, lambda line: None)
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.run_cli("init", str(self.root / "shop"), "--name", "store", "--yes"), 1)

        self.assertEqual([project.name for project in self.saved().projects], ["store"])
        self.assertEqual(self.mac.launchctl.loaded, {SERVICE, SHOP})
        self.assertIn(
            'The server of "shop" still runs in this folder, so the server of "store" did not start. To replace it '
            "(the sessions it started end): porchlight apply --servers",
            self.printed,
        )

    def test_yes_fills_what_no_flag_gives_from_the_defaults_and_asks_nothing(self):
        self.configure(defaults=config.Defaults("plan", ("server",)))
        shop = self.repository("shop")

        self.assertEqual(self.run_cli("init", str(shop), "--yes", "--base", "develop"), 0)

        self.assertEqual(self.keys.asked, 0)
        self.assertEqual(self.saved().projects, (config.Project("shop", str(shop), "plan", ("server",), "develop", "shop"),))

    def test_without_a_terminal_a_missing_value_is_a_usage_error_naming_its_flag(self):
        shop = self.repository("shop")
        for arguments, flag in (
            (["--yes"], "--permission-mode"),
            (["--permission-mode", "plan", "--preset", "minimal"], "--name"),
            (["--name", "shop", "--permission-mode", "plan", "--preset", "minimal"], "--yes"),
        ):
            self.assertEqual(self.run_cli("init", str(shop), *arguments), 2, arguments)

            self.assertIn("usage: porchlight init", self.errors)
            self.assertIn("[--name <name>]", self.errors, "the usage has the command's own flags")
            self.assertIn(flag, self.errors.splitlines()[-1])
        self.assertFalse(self.file.exists())

    def test_quitting_or_answering_no_changes_nothing(self):
        shop = self.repository("shop")
        for keys in (standins.Keys(CTRL_C), standins.Keys(ENTER, ENTER, ENTER, ENTER, "n")):
            self.printed.clear()

            self.assertEqual(self.run_cli("init", str(shop), keys=keys), 1)

            self.assertEqual(self.printed, ["Nothing was changed."])
            self.assertFalse(self.file.exists())
            self.assertEqual(self.mac.launchctl.did(), [])

    def test_flags_are_checked_before_anything_is_asked(self):
        self.configure(blog=("server",))
        shop = self.repository("shop")
        for arguments, problem in (
            (["--name", "Shop"], "lowercase"),
            (["--name", "blog"], 'the project "blog" already has this name'),
            (["--permission-mode", "sometimes"], "claude lists"),
            (["--feature", "tabs"], '"tabs" needs "ready-session"'),
            (["--terminal", "none"], "invalid choice"),  # only setup may leave the terminal out
        ):
            keys = standins.Keys()

            self.assertEqual(self.run_cli("init", str(shop), *arguments, keys=keys), 2, arguments)

            self.assertIn(problem, self.errors)
            self.assertEqual(keys.asked, 0)


class Deinit(Linking):
    def setUp(self):
        super().setUp()
        self.both = self.configure(shop=("server", "ready-session"), blog=("server",))
        self.shop, self.blog = self.both.projects
        agents.apply(self.both, self.mac, lambda line: None)
        self.mac.launchctl.calls.clear()

    def ready_session(self, project, session, state_of, pid):
        """A ready session in a project's state, its worktree and its process."""
        worktree = names.repository(project) / ".claude" / "worktrees" / names.worktree(project, session)
        worktree.mkdir(parents=True)
        record = {
            "state": state_of,
            "started": self.mac.now,
            "changed": self.mac.now,
            "worktree": str(worktree),
            "branch": names.branch(project, session),
            "prompt": "" if state_of == "free" else "Fix the header",
            "title": "",
            "cse": "",
            "tidied": False,
            "shown": state_of != "free",
            "tmux": names.tmux_session(project, session),
        }
        store = self.mac.store(project, ready_sessions.STATE)
        saved = ready_sessions.load_state(store)
        saved["sessions"][session] = record
        store.save(saved)
        self.mac.ps += f"{pid} claude --session-id {session} --remote-control\n"

    def server_session(self, project, session, pid):
        """A session its server started, which ends when the server is unloaded."""
        worktrees.of_server_session(names.repository(project), session).mkdir(parents=True)
        line = f"{pid} claude --print --sdk-url wss://example.invalid/x --session-id {session}\n"
        self.mac.ps += line

        def unloaded(label):
            if label == names.server_label(project.name, self.mac.environ):
                self.mac.ps = self.mac.ps.replace(line, "")

        self.mac.launchctl.on_unload = unloaded

    def ends_when_asked(self):
        def terminate(pid):
            self.mac.terminated.append(pid)
            self.mac.ps = "".join(line for line in self.mac.ps.splitlines(True) if not line.startswith("%d " % pid))

        self.mac.terminate = terminate

    def test_a_folder_no_project_has_is_refused_listing_the_linked_ones(self):
        notes = self.repository("notes")

        self.assertEqual(self.run_cli("deinit", str(notes)), 1)

        self.assertEqual(
            self.printed,
            [
                "No project is linked to %s. The linked projects: shop (%s), blog (%s)"
                % (notes, self.root / "shop", self.root / "blog")
            ],
        )
        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(self.saved(), self.both)

    def test_shows_the_plan_before_changing_anything(self):
        printed_before_unload = []
        self.mac.launchctl.on_unload = lambda label: printed_before_unload.append(len(self.printed))

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 0)

        plan = [
            'Unlinking "shop" (%s):' % (self.root / "shop"),
            "  - it is removed from the configuration",
            "  - its free ready session, if one waits, ends",
            "  - its server %s is unloaded and removed" % SHOP,
            "  - its worktrees in %s are left as they are" % worktrees.folder(self.root / "shop"),
        ]
        self.assertEqual(self.printed[: len(plan)], plan)
        self.assertGreaterEqual(printed_before_unload[0], len(plan))

    def test_removes_the_project_and_its_server_and_leaves_the_other_running_servers_alone(self):
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"  # every definition changes

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 0)

        self.assertEqual(self.saved().projects, (self.blog,))
        self.assertIn(("unload", SHOP), self.mac.launchctl.did())
        self.assertNotIn(("unload", BLOG), self.mac.launchctl.did())
        self.assertEqual(self.files(), [SERVICE + ".plist", BLOG + ".plist"])
        self.assertIn(BLOG + ": left running as it is, though its definition changed", self.printed)
        self.assertEqual(self.printed[-1], "Left as they are: its worktrees and its logs.")

    def test_a_folder_inside_a_project_finds_it(self):
        inner = self.root / "shop" / "src"
        inner.mkdir()

        self.assertEqual(self.run_cli("deinit", str(inner)), 0)

        self.assertEqual(self.saved().projects, (self.blog,))

    def test_the_last_project_takes_the_service_with_it_and_the_rest_of_the_configuration_stays(self):
        self.assertEqual(self.run_cli("deinit", str(self.root / "blog")), 0)
        self.printed.clear()

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 0)

        self.assertIn("  - the service %s is unloaded and removed: no project is left" % SERVICE, self.printed)
        self.assertEqual(self.files(), [])
        self.assertEqual(self.mac.launchctl.loaded, set())
        self.assertEqual(self.saved(), config.Config("warp", ()))

    def test_its_free_session_ends(self):
        self.ready_session(self.shop, A, "free", 601)
        self.ends_when_asked()

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 0)

        self.assertEqual(self.mac.terminated, [601])
        self.assertIn("shop: ended the free session it held", self.printed)

    def test_a_server_running_sessions_asks_before_they_end(self):
        self.server_session(self.shop, LIVE, 701)
        keys = standins.Keys("n")

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop"), keys=keys), 1)

        self.assertIsInstance(keys.shown[-1], Confirm)
        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(self.saved(), self.both)
        self.assertIn("  - its server %s is unloaded and removed: the 1 session it started ends" % SHOP, self.printed)
        self.assertEqual(self.printed[-1], "Nothing was changed.")

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop"), keys=standins.Keys("y")), 0)

        self.assertIn(("unload", SHOP), self.mac.launchctl.did())
        self.assertEqual(self.saved().projects, (self.blog,))

    def test_without_a_terminal_it_ends_a_servers_sessions_only_with_yes(self):
        self.server_session(self.shop, LIVE, 701)

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 1)

        self.assertEqual(
            self.printed[-1],
            "Its server runs 1 session, which would end. Confirm in a terminal, or give --yes. Nothing was changed.",
        )
        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(self.saved(), self.both)

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop"), "--yes"), 0)

        self.assertEqual(self.saved().projects, (self.blog,))

    def test_sessions_in_use_keep_running_and_the_plan_says_how_to_reach_each(self):
        self.ready_session(self.shop, A, "used", 601)

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 0)

        attach = self.mac.tmux.attach(names.tmux_session(self.shop, A))
        self.assertIn('  - the session "Fix the header" keeps running; reach it with: %s' % attach, self.printed)
        self.assertEqual(self.mac.terminated, [])
        store = self.mac.store(self.shop, ready_sessions.STATE)
        self.assertIn(A, store.load({})["sessions"], "its state stays while a session of it runs")
        self.assertIn("Its state was kept: a session of it still runs.", self.printed)

    def test_its_state_is_removed_when_nothing_of_it_runs_and_its_logs_stay(self):
        self.ready_session(self.shop, A, "closed", 601)
        self.mac.ps = ""
        self.mac.log(self.shop, "something happened")

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 0)

        self.assertFalse(names.project_state(self.shop, self.mac.environ).exists())
        self.assertTrue(names.log_file(self.shop, self.mac.environ).exists())
        self.assertIn("Removed its state.", self.printed)

    def test_its_state_stays_in_a_folder_the_tool_did_not_make(self):
        self.ready_session(self.shop, A, "closed", 601)
        self.mac.ps = ""
        (names.state_root(self.mac.environ) / names.MARKER).unlink()

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 0)

        self.assertTrue(names.project_state(self.shop, self.mac.environ).exists())
        self.assertIn(
            "%s was left as it is: porchlight did not make that folder." % names.state_root(self.mac.environ),
            self.printed,
        )

    def test_a_server_that_does_not_unload_keeps_the_project_linked_and_exits_one(self):
        self.mac.launchctl.stuck.add(SHOP)

        self.assertEqual(self.run_cli("deinit", str(self.root / "shop")), 1)

        self.assertEqual(self.saved(), self.both)
        self.assertEqual(
            self.printed[-1], '"shop" stays in the configuration: its server could not be removed. Run this again.'
        )


if __name__ == "__main__":
    unittest.main()
