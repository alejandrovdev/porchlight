"""Tests of launchd's agents: the definition of one, the folder that keeps them, and what
is asked of launchctl. launchctl is a stand-in: nothing is loaded and nothing is unloaded."""

import os
import plistlib
import tempfile
import unittest
from pathlib import Path

from porchlight.atoms import launchd
from tests import standins

LABEL = "test.porchlight.unit"


def definition(**options):
    return launchd.definition(
        LABEL, ["/tools/porchlight", "run"], {"PATH": "/tools:/usr/bin"}, "/logs/agent.log", **options
    )


class Definition(unittest.TestCase):
    def test_an_agent_starts_at_login_is_kept_running_and_logs_to_one_file(self):
        self.assertEqual(
            definition(),
            {
                "Label": LABEL,
                "ProgramArguments": ["/tools/porchlight", "run"],
                "EnvironmentVariables": {"PATH": "/tools:/usr/bin"},
                "RunAtLoad": True,
                "KeepAlive": True,
                "ProcessType": "Interactive",
                "StandardOutPath": "/logs/agent.log",
                "StandardErrorPath": "/logs/agent.log",
            },
        )

    def test_what_it_started_outlives_it_only_when_asked(self):
        self.assertNotIn("AbandonProcessGroup", definition())
        self.assertIs(definition(outlived=True)["AbandonProcessGroup"], True)

    def test_runs_in_a_folder_and_waits_between_two_starts_when_asked(self):
        asked = definition(directory=Path("/srv/shop"), throttle=30)

        self.assertEqual(asked["WorkingDirectory"], "/srv/shop")
        self.assertEqual(asked["ThrottleInterval"], 30)
        self.assertNotIn("WorkingDirectory", definition())
        self.assertNotIn("ThrottleInterval", definition())


class Folder(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.folder = Path(self.scratch.name) / "LaunchAgents"

    def test_writes_a_property_list_named_after_the_label_and_reads_it_back(self):
        path = launchd.file(self.folder, LABEL)

        launchd.write(path, definition(outlived=True))

        self.assertEqual(path, self.folder / (LABEL + ".plist"))
        with open(path, "rb") as handle:
            self.assertEqual(plistlib.load(handle), definition(outlived=True))
        self.assertTrue(path.read_bytes().startswith(b"<?xml"), "a text a person can read")
        self.assertEqual(launchd.read(path), definition(outlived=True))
        self.assertEqual([entry.name for entry in self.folder.iterdir()], [LABEL + ".plist"], "no draft is left")

    def test_reads_nothing_from_a_file_that_is_absent_or_is_no_property_list(self):
        self.folder.mkdir()
        broken = launchd.file(self.folder, "broken")
        broken.write_text("not a property list")

        self.assertIsNone(launchd.read(launchd.file(self.folder, "absent")))
        self.assertIsNone(launchd.read(broken))

    def test_lists_the_labels_that_have_a_file(self):
        self.assertEqual(launchd.labels(self.folder), [], "a folder that is not there has none")
        launchd.write(launchd.file(self.folder, "b.two"), definition())
        launchd.write(launchd.file(self.folder, "a.one"), definition())
        (self.folder / "notes.txt").write_text("")

        self.assertEqual(launchd.labels(self.folder), ["a.one", "b.two"])

    def test_removing_a_file_that_is_not_there_is_no_error(self):
        path = launchd.file(self.folder, LABEL)
        launchd.write(path, definition())

        launchd.remove(path)
        launchd.remove(path)

        self.assertFalse(path.exists())

    def test_a_file_is_written_for_its_owner_alone_to_change_whatever_the_umask(self):
        for umask in (0o002, 0o000, 0o077):
            before = os.umask(umask)
            try:
                path = launchd.file(self.folder, "umask.%o" % umask)
                launchd.write(path, definition())
            finally:
                os.umask(before)

            self.assertEqual(path.stat().st_mode & 0o777, 0o644, "launchd refuses a file others may write")


class Launchctl(unittest.TestCase):
    def launchd(self, answers=None):
        self.runner = standins.Runner(answers)
        return launchd.Launchd(run=self.runner, uid=lambda: 501)

    def test_reads_the_loaded_labels_from_the_list(self):
        listing = "PID\tStatus\tLabel\n412\t0\tcom.example.one\n-\t78\ttest.porchlight.unit\n"
        asked = self.launchd(lambda words: standins.result(stdout=listing))

        self.assertEqual(asked.loaded(), {"com.example.one", "test.porchlight.unit"})
        self.assertEqual(self.runner.calls, [["/bin/launchctl", "list"]])

    def test_says_it_cannot_tell_when_launchctl_fails_or_cannot_run(self):
        for answer in (standins.result(returncode=1, stderr="no domain"), OSError("no launchctl")):
            with self.assertRaises(launchd.Unavailable):
                self.launchd(lambda words: answer).loaded()

    def test_tells_whether_one_label_is_loaded_in_the_users_own_domain(self):
        asked = self.launchd(lambda words: standins.result(returncode=113))

        self.assertFalse(asked.is_loaded(LABEL))
        self.assertTrue(self.launchd().is_loaded(LABEL))
        self.assertEqual(self.runner.calls, [["/bin/launchctl", "print", "gui/501/" + LABEL]])

    def test_a_label_is_gone_only_when_launchd_says_it_does_not_know_it(self):
        answers = {0: launchd.LOADED, 113: launchd.GONE, 1: launchd.UNKNOWN, 112: launchd.UNKNOWN, 3: launchd.UNKNOWN}
        for code, found in answers.items():
            asked = self.launchd(lambda words: standins.result(returncode=code))

            self.assertEqual(asked.state(LABEL), found, code)
            self.assertEqual(self.runner.calls, [["/bin/launchctl", "print", "gui/501/" + LABEL]])

        self.assertEqual(self.launchd(lambda words: OSError("no launchctl")).state(LABEL), launchd.UNKNOWN)

    def test_loads_a_definition_into_the_users_own_domain(self):
        self.launchd().load(Path("/agents/one.plist"))

        self.assertEqual(self.runner.calls, [["/bin/launchctl", "bootstrap", "gui/501", "/agents/one.plist"]])

    def test_unloads_an_agent_by_its_label(self):
        self.launchd().unload(LABEL)

        self.assertEqual(self.runner.calls, [["/bin/launchctl", "bootout", "gui/501/" + LABEL]])

    def test_a_launchctl_that_cannot_run_answers_as_one_that_failed(self):
        asked = self.launchd(lambda words: OSError("no launchctl"))

        self.assertNotEqual(asked.load(Path("/agents/one.plist")).returncode, 0)
        self.assertNotEqual(asked.unload(LABEL).returncode, 0)
        self.assertFalse(asked.is_loaded(LABEL))


if __name__ == "__main__":
    unittest.main()
