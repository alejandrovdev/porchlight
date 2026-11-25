"""Tests of the names porchlight creates: all from its identifier and the project's name."""

import itertools
import os
import re
import unittest
from pathlib import Path
from unittest import mock

import porchlight
from porchlight import config, names
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SERVER_SESSIONS = ("cse_aaaaaaaa", "cse_01AAA")
SCRATCH = {"PORCHLIGHT_STATE_DIR": "/scratch/state", "PORCHLIGHT_LOG_DIR": "/scratch/logs"}


def every_name(project, environ=None):
    """Every name a project may produce, for one ready session and two server sessions."""
    found = {
        names.tmux_session(project, A),
        names.worktree(project, A),
        names.branch(project, A),
        names.lock_reason(project, A),
        names.ready_tab(project, A),
        names.tab_title(project, "Fix the header"),
        names.copy_name(project, "11111111-1111-5111-8111-111111111111", 1),
        names.copy_name(project, "11111111-1111-5111-8111-111111111111", 2),
        str(names.project_state(project, environ)),
        str(names.settings_file(project, environ)),
        str(names.log_file(project, environ)),
    }
    found.update(str(names.state_file(project, kind, environ)) for kind in ("ready-sessions", "view-tabs"))
    found.update(names.view_tab(project, session) for session in SERVER_SESSIONS)
    return found


class Names(unittest.TestCase):
    def test_two_projects_never_produce_the_same_name(self):
        # Names chosen to collide if a name were built by joining words carelessly.
        projects = [
            standins.project(name)
            for name in ("shop", "shop-view", "shop-ready", "view-shop", "ready-shop", "view", "ready", "s", "shop-a")
        ]

        for one, other in itertools.combinations(projects, 2):
            shared = every_name(one, SCRATCH) & every_name(other, SCRATCH)
            self.assertEqual(shared, set(), "%s and %s" % (one.name, other.name))

    def test_one_project_gives_each_thing_its_own_name(self):
        shop = standins.project("shop")

        self.assertNotEqual(names.ready_tab(shop, A), names.view_tab(shop, "cse_aaaaaaaa"))
        self.assertNotEqual(names.state_file(shop, "ready-sessions", SCRATCH), names.settings_file(shop, SCRATCH))

    def test_every_name_carries_the_project_and_what_the_tool_creates_carries_its_identifier(self):
        shop = standins.project("shop")

        self.assertEqual(names.TOOL, porchlight.__name__)
        self.assertEqual(names.tmux_session(shop, A), "shop-aaaaaaaa")
        self.assertEqual(names.worktree(shop, A), "porchlight-shop-aaaaaaaa")
        self.assertEqual(names.branch(shop, A), "porchlight-shop-aaaaaaaa")
        self.assertEqual(names.lock_reason(shop, A), "porchlight shop session aaaaaaaa")
        self.assertEqual(names.ready_tab(shop, A), "porchlight_ready_shop-aaaaaaaa")
        self.assertEqual(names.view_tab(shop, "cse_01AAA"), "porchlight_view_shop-01AAA")

    def test_a_tab_is_titled_after_the_projects_session_prefix(self):
        blog = standins.project("blog", prefix="Blog")

        self.assertEqual(names.tab_title(blog, "Fix the header"), "Blog · Fix the header")

    def test_a_project_owns_only_the_branches_made_for_its_own_sessions(self):
        shop = standins.project("shop")

        self.assertTrue(names.owns_branch(shop, names.branch(shop, A)))
        self.assertFalse(names.owns_branch(shop, names.branch(standins.project("shop-blue"), A)))
        self.assertFalse(names.owns_branch(shop, "porchlight-shop-feature"))
        self.assertFalse(names.owns_branch(shop, "main"))
        self.assertFalse(names.owns_branch(shop, ""))

    def test_state_and_logs_live_in_the_tools_own_folders_of_the_users_library(self):
        shop = standins.project("shop")
        library = Path.home() / "Library"

        self.assertEqual(names.state_root({}), library / "Application Support" / "porchlight")
        self.assertEqual(names.log_root({}), library / "Logs" / "porchlight")
        self.assertEqual(
            names.state_file(shop, "ready-sessions", {}),
            library / "Application Support" / "porchlight" / "projects" / "shop" / "ready-sessions.json",
        )
        self.assertEqual(names.log_file(shop, {}), library / "Logs" / "porchlight" / "shop.log")

    def test_the_environment_moves_the_folders_and_the_tmux_server(self):
        shop = standins.project("shop")
        environ = dict(SCRATCH, PORCHLIGHT_TMUX_SERVER="porchlight-test")

        self.assertEqual(names.variable("state_dir"), "PORCHLIGHT_STATE_DIR")
        self.assertEqual(names.project_state(shop, environ), Path("/scratch/state/projects/shop"))
        self.assertEqual(names.log_file(shop, environ), Path("/scratch/logs/shop.log"))
        self.assertEqual(names.tmux_server(environ), "porchlight-test")
        self.assertEqual(names.tmux_server({}), "porchlight")


class Package(unittest.TestCase):
    """What the code must not carry: a fixed home, a fixed base branch, another tool's names."""

    def sources(self):
        root = Path(porchlight.__file__).resolve().parent
        return [path for path in root.rglob("*") if path.suffix in (".py", ".conf")]

    def test_no_module_names_a_fixed_base_branch_or_a_home_folder(self):
        fixed = re.compile("origin/" + "main|/" + "Users/|/home/")

        for path in self.sources():
            for number, line in enumerate(path.read_text(encoding="utf8").splitlines(), 1):
                self.assertIsNone(fixed.search(line), "%s:%d %s" % (path.name, number, line.strip()))

    def test_only_the_tool_finder_names_the_homebrew_prefixes(self):
        naming = [
            path.name for path in self.sources() if "/opt/" + "homebrew" in path.read_text(encoding="utf8")
        ]

        self.assertEqual(naming, ["tools.py"])


class Agents(unittest.TestCase):
    """The names of the background agents, and what moves them for a rehearsal."""

    def test_the_labels_start_with_the_tools_own_address_and_carry_the_projects_name(self):
        self.assertEqual(names.service_label({}), "io.github.alejandrovdev.porchlight")
        self.assertEqual(names.server_label("shop", {}), "io.github.alejandrovdev.porchlight.server.shop")

    def test_a_variable_replaces_the_start_of_every_label(self):
        environ = {"PORCHLIGHT_LABEL": "test.porchlight.scratch"}

        self.assertEqual(names.service_label(environ), "test.porchlight.scratch")
        self.assertEqual(names.server_label("shop", environ), "test.porchlight.scratch.server.shop")

    def test_tells_which_project_a_label_is_the_server_of(self):
        self.assertEqual(names.served("io.github.alejandrovdev.porchlight.server.my-shop", {}), "my-shop")
        self.assertIsNone(names.served("io.github.alejandrovdev.porchlight", {}))
        self.assertIsNone(names.served("io.github.alejandrovdev.porchlight.server.", {}))

    def test_only_the_service_and_the_servers_of_one_prefix_are_the_tools_own(self):
        own = ("io.github.alejandrovdev.porchlight", "io.github.alejandrovdev.porchlight.server.shop")
        others = (
            "io.github.alejandrovdev.porchlight.rehearsal",  # another install, whose labels start the same
            "io.github.alejandrovdev.porchlight.rehearsal.server.shop",
            "io.github.alejandrovdev.porchlightx",
            "io.github.alejandrovdev.porchlight.server.Shop.backup",
            "com.example.io.github.alejandrovdev.porchlight",
            "test.porchlight.scratch",
        )

        self.assertEqual([label for label in own + others if names.own_label(label, {})], list(own))
        self.assertTrue(names.own_label("test.porchlight.scratch", {"PORCHLIGHT_LABEL": "test.porchlight.scratch"}))
        self.assertFalse(names.own_label(own[0], {"PORCHLIGHT_LABEL": "test.porchlight.scratch"}))

    def test_the_start_of_the_labels_must_be_a_reverse_domain_name(self):
        for label in ("", "test.porchlight.scratch", "io.github.someone.porchlight", "a-b.c-d", "A1.b2"):
            self.assertEqual(names.label_problem({"PORCHLIGHT_LABEL": label}), "", label)
        self.assertEqual(names.label_problem({}), "")

        for label in ("porchlight", "../../escape", "a/b", " ", "com.example.", ".com.example", "com..example", "com.example\n", "com.exam ple"):
            self.assertEqual(
                names.label_problem({"PORCHLIGHT_LABEL": label}),
                "PORCHLIGHT_LABEL must be a reverse domain name such as com.example.porchlight (letters, digits and "
                "hyphens, in parts joined by dots), not %r" % label,
            )

    def test_the_agents_are_kept_where_a_persons_own_are_unless_a_variable_moves_them(self):
        self.assertEqual(names.launch_agents({}), Path.home() / "Library" / "LaunchAgents")
        self.assertEqual(names.launch_agents({"PORCHLIGHT_LAUNCH_AGENTS_DIR": "/scratch/agents"}), Path("/scratch/agents"))

    def test_an_agents_log_is_no_projects_log(self):
        service = standins.project("service")
        logs = {
            names.log_file(service, SCRATCH),
            names.service_log(SCRATCH),
            names.server_log(service, SCRATCH),
            names.server_log(standins.project("server"), SCRATCH),
        }

        self.assertEqual(len(logs), 4)
        self.assertEqual({log.parent for log in logs}, {Path("/scratch/logs")})

    def test_the_lock_of_the_service_is_in_the_state_folder(self):
        self.assertEqual(names.service_lock(SCRATCH), Path("/scratch/state/service.lock"))


class Carried(unittest.TestCase):
    """What a command the tool hands to someone else must carry to act as the tool that made it."""

    def test_the_default_configuration_file_is_the_one_the_configuration_reads(self):
        with mock.patch.dict("os.environ", clear=False) as environ:
            environ.pop("PORCHLIGHT_CONFIG", None)

            self.assertEqual(names.default_config(), config.default_path())

    def test_an_install_that_moved_nothing_carries_nothing(self):
        self.assertEqual(names.carried({"PATH": "/usr/bin", "HOME": "/home/someone"}), {})
        self.assertEqual(names.carried({"PATH": "/usr/bin"}, names.default_config()), {})

    def test_every_variable_of_the_tool_is_carried_and_no_other(self):
        environ = dict(SCRATCH, PORCHLIGHT_TMUX_SERVER="porchlight-test", PATH="/usr/bin", PORCHLIGHTS="no")

        self.assertEqual(names.carried(environ), dict(SCRATCH, PORCHLIGHT_TMUX_SERVER="porchlight-test"))

    def test_a_configuration_file_that_is_not_the_default_one_is_carried_whole(self):
        carried = names.carried(SCRATCH, "scratch/config.toml")

        self.assertEqual(carried, dict(SCRATCH, PORCHLIGHT_CONFIG=os.path.abspath("scratch/config.toml")))

    def test_the_file_in_use_wins_over_the_one_the_environment_names(self):
        environ = {"PORCHLIGHT_CONFIG": "/scratch/other.toml"}

        self.assertEqual(names.carried(environ, "/scratch/config.toml"), {"PORCHLIGHT_CONFIG": "/scratch/config.toml"})
        self.assertEqual(names.carried(environ, names.default_config()), {})
        self.assertEqual(names.carried(environ), environ, "no file was named: the environment's own stands")

    def test_a_folder_or_a_file_named_from_where_the_command_runs_is_carried_whole(self):
        environ = {
            "PORCHLIGHT_STATE_DIR": "relative/state",
            "PORCHLIGHT_LOG_DIR": "relative/logs",
            "PORCHLIGHT_TRANSCRIPTS_DIR": "transcripts",
            "PORCHLIGHT_LAUNCH_AGENTS_DIR": "./agents",
            "PORCHLIGHT_WARP_TAB_CONFIGS": "tabs",
            "PORCHLIGHT_CONFIG": "relative.toml",
            "PORCHLIGHT_TMUX_SERVER": "porchlight-test",
            "PORCHLIGHT_LABEL": "test.porchlight.scratch",
            "PORCHLIGHT_CLAUDE": "claude",
        }

        carried = names.carried(environ)

        for name in ("STATE_DIR", "LOG_DIR", "TRANSCRIPTS_DIR", "LAUNCH_AGENTS_DIR", "WARP_TAB_CONFIGS", "CONFIG"):
            self.assertEqual(carried["PORCHLIGHT_" + name], os.path.abspath(environ["PORCHLIGHT_" + name]), name)
        for name in ("TMUX_SERVER", "LABEL", "CLAUDE"):
            self.assertEqual(carried["PORCHLIGHT_" + name], environ["PORCHLIGHT_" + name], "no folder: as it is")


if __name__ == "__main__":
    unittest.main()
