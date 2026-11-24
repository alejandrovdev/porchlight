"""Tests of the rules the copies for `/resume` gain per project: the project's own state
and names, and one failure that never stops the rest."""

import json
import unittest
from pathlib import Path

from porchlight.features import resume_list
from tests import standins
from tests.test_resume_list import SOURCE_ID, WORKTREE, Scratch


class OnTheMac(Scratch):
    """Rules the port adds: per project, with the project's own state and names."""

    def test_keeps_what_it_copied_in_the_projects_own_state(self):
        self.source.write_text("".join(self.server_lines(1)))

        resume_list.sync(self.project, self.mac)

        state = json.loads((Path(self.scratch.name) / "state" / "projects" / "shop" / "resume-list.json").read_text())
        (copy,) = self.copies()
        self.assertEqual(state[SOURCE_ID]["copy"], copy.stem)
        self.assertEqual(state[SOURCE_ID]["source"], str(self.source))

    def test_two_projects_give_the_same_session_different_copies(self):
        blog = standins.project("blog", self.project.path)

        self.assertNotEqual(resume_list.copy_id(self.project, SOURCE_ID, 1), resume_list.copy_id(blog, SOURCE_ID, 1))
        self.assertNotEqual(
            resume_list.copy_id(self.project, SOURCE_ID, 1), resume_list.copy_id(self.project, SOURCE_ID, 2)
        )

    def test_one_transcript_that_fails_does_not_stop_the_others(self):
        (self.server / "00000000-0000-5000-8000-000000000000.jsonl").mkdir()  # cannot be read as a file
        self.source.write_text("".join(self.server_lines(1)))

        resume_list.sync(self.project, self.mac)

        self.assertEqual(len(self.copies()), 1)
        self.assertIn("failed 00000000-0000-5000-8000-000000000000.jsonl", self.mac.log_text(self.project))

    def test_a_pass_never_fails_whatever_happens(self):
        self.mac.store = lambda project, kind: (_ for _ in ()).throw(RuntimeError("no state"))

        result = self.run_command("sync")

        self.assertEqual(result.returncode, 0)
        self.assertIn("sync failed", self.mac.log_text(self.project))

    def test_does_nothing_for_a_repository_claude_code_never_ran_in(self):
        self.source.write_text("".join(self.server_lines(1)))
        self.main.rmdir()

        resume_list.sync(self.project, self.mac)

        self.assertFalse(self.main.exists())

    def test_says_which_copies_are_live_and_where_to_resume_them(self):
        self.source.write_text("".join(self.server_lines(1)))
        resume_list.sync(self.project, self.mac)
        (copy,) = self.copies()
        Path(self.repo + WORKTREE).mkdir(parents=True)
        printed = []

        resume_list.list_copies(self.project, self.mac, out=printed.append)
        self.mac.ps = "101 claude --print --sdk-url x --session-id cse_01ABC --output-format stream-json\n"
        resume_list.list_copies(self.project, self.mac, out=printed.append)

        self.assertIn("worktree kept", printed[0])
        self.assertEqual(printed[1], "    cd '%s' && claude --resume %s" % (self.repo + WORKTREE, copy.stem))
        self.assertIn("live on the phone", printed[6])

    def test_says_when_there_is_no_copy(self):
        printed = []

        resume_list.list_copies(self.project, self.mac, out=printed.append)

        self.assertEqual(printed, ["No session created from the phone has a copy yet."])


if __name__ == "__main__":
    unittest.main()
