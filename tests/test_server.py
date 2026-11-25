"""Tests of starting the Remote Control server of a project and of one pass over a
project (`test_passes` has the pass over a whole configuration). Nothing is started: the
program that would replace this one is a stand-in."""

import json
import tempfile
import unittest
from pathlib import Path

from porchlight import names, passes, session_settings
from porchlight.features import server
from tests import standins


class Server(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        (root / "shop").mkdir()
        self.project = standins.project("shop", str(root / "shop"), mode="plan")
        self.mac = standins.StandInMac(root)
        self.mac.environ["PATH"] = "/custom/bin"
        self.done = []

    def tearDown(self):
        self.scratch.cleanup()

    def run_server(self, **options):
        server.run(
            self.project,
            self.mac,
            execute=lambda program, words, environment: self.done.append(("exec", program, words, environment)),
            spawn=lambda words: self.done.append(("spawn", words)),
            chdir=lambda folder: self.done.append(("cd", str(folder))),
            pid=lambda: 4242,
            **options,
        )

    def test_the_server_gives_each_session_a_worktree_with_the_projects_mode(self):
        self.assertEqual(
            server.command(self.project, "/tools/claude", "/state/settings.json"),
            [
                "/tools/claude", "remote-control", "--spawn", "worktree", "--permission-mode", "plan",
                "--settings", "/state/settings.json", "--no-create-session-in-dir",
            ],
        )  # fmt: skip

    def test_starts_in_the_projects_folder_and_becomes_the_server(self):
        self.run_server()

        settings = self.mac.settings(self.project)
        self.assertEqual([step[0] for step in self.done], ["cd", "spawn", "exec"])
        self.assertEqual(self.done[0][1], str(names.repository(self.project)))
        self.assertEqual(self.done[2][1:3], ("/tools/claude", server.command(self.project, "/tools/claude", settings)))
        self.assertEqual(json.loads(settings.read_text())["permissions"]["defaultMode"], "plan")

    def test_its_sessions_find_homebrew_whatever_started_it(self):
        self.run_server()

        folders = self.done[-1][3]["PATH"].split(":")
        self.assertEqual(folders[:2], ["/opt/homebrew/bin", "/usr/local/bin"])
        self.assertIn("/usr/bin", folders)
        self.assertEqual(folders[-1], "/custom/bin")

    def test_keeps_the_mac_awake_on_ac_power_for_as_long_as_it_runs(self):
        self.run_server()

        self.assertEqual(self.done[1], ("spawn", ["/usr/bin/caffeinate", "-s", "-w", "4242"]))

    def test_does_not_keep_the_mac_awake_when_told_not_to(self):
        self.run_server(keep_awake=False)

        self.assertEqual([step[0] for step in self.done], ["cd", "exec"])

    def test_installs_the_settings_that_waited_for_a_restart(self):
        settings = self.mac.settings(self.project)
        session_settings.stage(standins.project("shop", self.project.path, mode="acceptEdits"), settings)

        self.run_server()

        self.assertEqual(json.loads(settings.read_text())["permissions"]["defaultMode"], "plan")
        self.assertFalse(session_settings.waiting(settings).exists())


class Pass(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.project = standins.project("shop", self.scratch.name)
        self.mac = standins.StandInMac(self.scratch.name)
        self.ran = []

    def tearDown(self):
        self.scratch.cleanup()

    def step(self, name, error=None):
        def run(project, mac):
            self.ran.append((name, project.name))
            if error:
                raise error

        return (name, run)

    def test_one_part_that_fails_is_logged_and_does_not_stop_the_others(self):
        steps = (self.step("first"), self.step("second", RuntimeError("broken")), self.step("third"))

        passes.run_project(self.project, self.mac, steps)

        self.assertEqual(self.ran, [("first", "shop"), ("second", "shop"), ("third", "shop")])
        self.assertIn("second failed: RuntimeError('broken')", self.mac.log_text(self.project))

    def test_a_pass_keeps_the_tabs_then_the_ready_sessions_then_the_copies(self):
        self.assertEqual([name for name, _ in passes.STEPS], ["view tabs", "ready sessions", "resume list"])

    def test_the_status_of_a_project_names_both_kinds_of_session(self):
        printed = []

        passes.project_status(self.project, self.mac, out=printed.append)

        self.assertEqual(
            printed,
            [
                "Ready sessions, with Claude Code's interface:",
                "  No session with Claude Code's interface yet.",
                "Sessions the server started, with a read-only view:",
                "  No session the server started is running.",
            ],
        )

    def test_the_status_of_a_project_without_the_server_names_its_ready_sessions_only(self):
        project = standins.project("shop", self.project.path, features=("ready-session",))
        printed = []

        passes.project_status(project, self.mac, out=printed.append)

        self.assertEqual(
            printed, ["Ready sessions, with Claude Code's interface:", "  No session with Claude Code's interface yet."]
        )


if __name__ == "__main__":
    unittest.main()
