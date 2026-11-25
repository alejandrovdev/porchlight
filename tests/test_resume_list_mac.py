"""Tests of the rules the copies for `/resume` gain per project: the project's own state
and names, and one failure that never stops the rest."""

import json
import shlex
import unittest
from pathlib import Path
from unittest import mock

from porchlight import config
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

    def test_without_resume_list_no_copy_is_written_and_nothing_is_kept(self):
        project = standins.project("shop", self.project.path, features=("server",))
        self.source.write_text("".join(self.server_lines(1)))

        resume_list.sync(project, self.mac)

        self.assertEqual(self.copies(), [])
        self.assertFalse((Path(self.scratch.name) / "state").exists())

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
        self.assertEqual(printed[1], "    cd %s && claude --resume %s" % (shlex.quote(self.repo + WORKTREE), copy.stem))
        self.assertIn("live on the phone", printed[6])

    def test_quotes_the_folder_and_prints_the_prompt_printable(self):
        self.source.write_text(
            self.line("queue-operation", SOURCE_ID, operation="enqueue", content="Fix \x1b[2J the caf\u00e9 😀")
            + self.line("user", SOURCE_ID, "sdk-cli", uuid="u0", cwd="/srv/it's here/" + WORKTREE)
        )
        resume_list.sync(self.project, self.mac)
        (copy,) = self.copies()
        printed = []

        with mock.patch("pathlib.Path.is_dir", return_value=True):
            resume_list.list_copies(self.project, self.mac, out=printed.append)

        self.assertIn("worktree kept      Fix \ufffd[2J the café 😀", printed[0])
        self.assertEqual(printed[1], "    cd '/srv/it'\"'\"'s here/%s' && claude --resume %s" % (WORKTREE, copy.stem))

    def test_says_when_there_is_no_copy(self):
        printed = []

        resume_list.list_copies(self.project, self.mac, out=printed.append)

        self.assertEqual(printed, ["No session created from the phone has a copy yet."])


class Report(Scratch):
    """What the `resume-list` command prints: the copies of every project that keeps them."""

    def setUp(self):
        super().setUp()
        root = Path(self.scratch.name)
        (root / "blog").mkdir()
        (root / "docs").mkdir()
        self.blog = standins.project("blog", str(root / "blog"))
        self.docs = standins.project("docs", str(root / "docs"), features=("server",))  # without resume-list
        self.configuration = config.Config("warp", (self.project, self.blog, self.docs))
        self.source.write_text("".join(self.server_lines(1)))
        self.printed = []

    def report(self, configuration=None, **options):
        return resume_list.report(configuration or self.configuration, self.mac, out=self.printed.append, **options)

    def test_lists_the_copies_of_every_project_that_has_the_feature_under_its_name(self):
        resume_list.sync(self.project, self.mac)
        (copy,) = self.copies()

        self.assertEqual(self.report(), 0)

        self.assertEqual(self.printed[0], "shop")
        self.assertRegex(self.printed[1], r"^  \d{4}-\d\d-\d\d \d\d:\d\d  worktree removed +Fix the header$")
        self.assertEqual(self.printed[2], "      claude --resume " + copy.stem)
        blog = self.printed.index("blog")
        self.assertEqual(
            self.printed[blog - 1 : blog + 2], ["", "blog", "  No session created from the phone has a copy yet."]
        )
        self.assertNotIn("docs", self.printed, "a project without the feature is left out")
        self.assertEqual(
            self.printed[-4:-2], ["", "Each copy is its own session: continuing it does not reach the phone."]
        )
        self.assertEqual(len([line for line in self.printed if line.startswith("Each copy")]), 1, "said once")

    def test_does_not_bring_the_copies_up_to_date_unless_asked(self):
        self.assertEqual(self.report(), 0)
        self.assertEqual(self.copies(), [])

        self.assertEqual(self.report(sync_first=True), 0)
        (copy,) = self.copies()
        self.assertIn("      claude --resume " + copy.stem, self.printed)

    def test_says_when_no_project_has_the_feature(self):
        self.assertEqual(self.report(config.Config("warp", (self.docs,))), 1)

        self.assertEqual(self.printed, ['No project has the feature "resume-list". Nothing to list.'])

    def test_a_project_whose_copies_cannot_be_brought_up_to_date_is_said_and_the_next_still_listed(self):
        real = self.mac.store

        def store(project, kind):
            if project is self.project:
                raise RuntimeError("no state")
            return real(project, kind)

        self.mac.store = store

        self.assertEqual(self.report(sync_first=True), 1)

        self.assertEqual(self.printed[:2], ["shop", "  Could not read its copies: RuntimeError('no state')"])
        self.assertEqual(self.printed[-2:], ["blog", "  No session created from the phone has a copy yet."])
        self.assertIn("resume list failed: RuntimeError('no state')", self.mac.log_text(self.project))


if __name__ == "__main__":
    unittest.main()
