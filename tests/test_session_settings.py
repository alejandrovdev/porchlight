"""Tests of the settings file a project's sessions start with."""

import json
import tempfile
import unittest
from pathlib import Path

from porchlight import session_settings
from tests import standins


class SessionSettings(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.path = Path(self.scratch.name) / "projects" / "shop" / "settings.json"
        self.waiting = self.path.with_name("settings.json.next")

    def tearDown(self):
        self.scratch.cleanup()

    def test_the_permission_mode_is_the_projects(self):
        self.assertEqual(
            session_settings.content(standins.project(mode="acceptEdits"))["permissions"], {"defaultMode": "acceptEdits"}
        )

    def test_the_first_time_the_file_is_written_in_place(self):
        session_settings.stage(standins.project(mode="plan"), self.path)

        self.assertEqual(json.loads(self.path.read_text())["permissions"]["defaultMode"], "plan")
        self.assertFalse(self.waiting.exists())

    def test_a_change_waits_beside_the_file_a_running_server_recorded(self):
        session_settings.stage(standins.project(mode="plan"), self.path)
        before = self.path.read_bytes()

        session_settings.stage(standins.project(mode="acceptEdits"), self.path)

        self.assertEqual(self.path.read_bytes(), before, "the server refuses new sessions once its file differs")
        self.assertEqual(json.loads(self.waiting.read_text())["permissions"]["defaultMode"], "acceptEdits")

    def test_a_change_that_was_taken_back_stops_waiting(self):
        session_settings.stage(standins.project(mode="plan"), self.path)
        session_settings.stage(standins.project(mode="acceptEdits"), self.path)

        session_settings.stage(standins.project(mode="plan"), self.path)

        self.assertFalse(self.waiting.exists())

    def test_what_waits_is_installed_when_the_server_starts(self):
        session_settings.stage(standins.project(mode="plan"), self.path)
        session_settings.stage(standins.project(mode="acceptEdits"), self.path)

        self.assertTrue(session_settings.install_pending(self.path))

        self.assertEqual(json.loads(self.path.read_text())["permissions"]["defaultMode"], "acceptEdits")
        self.assertFalse(self.waiting.exists())
        self.assertFalse(session_settings.install_pending(self.path), "nothing waits any more")


if __name__ == "__main__":
    unittest.main()
