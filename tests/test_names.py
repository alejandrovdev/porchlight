"""Tests of the names porchlight creates: all from its identifier and the project's name."""

import itertools
import re
import unittest
from pathlib import Path

import porchlight
from porchlight import names
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


if __name__ == "__main__":
    unittest.main()
