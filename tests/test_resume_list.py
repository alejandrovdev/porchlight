"""Tests of the copies that `/resume` lists, run against scratch folders: nothing here
reads or writes the real Claude Code folders."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from porchlight import names
from porchlight.atoms import transcripts
from porchlight.features import resume_list
from tests import standins

SOURCE_ID = "11111111-1111-5111-8111-111111111111"
WORKTREE = "/.claude/worktrees/bridge-cse_01ABC"


class Scratch(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        root = Path(self.scratch.name)
        (root / "repo").mkdir()
        self.project = standins.project("shop", str(root / "repo"))
        self.repo = str(names.repository(self.project))
        self.mac = standins.StandInMac(root)
        self.projects = self.mac.transcripts
        self.main = self.projects / transcripts.folder_name(self.repo)
        self.server = self.projects / transcripts.folder_name(self.repo + WORKTREE)
        self.main.mkdir(parents=True)
        self.server.mkdir(parents=True)
        self.source = self.server / f"{SOURCE_ID}.jsonl"

    def tearDown(self):
        self.scratch.cleanup()

    def line(self, kind, session_id, entrypoint=None, **extra):
        entry = {"type": kind, "sessionId": session_id}
        if entrypoint is not None:
            entry["entrypoint"] = entrypoint
            entry["cwd"] = self.repo + WORKTREE
        entry.update(extra)
        return json.dumps(entry, separators=(",", ":")) + "\n"

    def server_lines(self, count):
        lines = [self.line("session-owner", SOURCE_ID, accountUuid="a")]
        lines.append(self.line("queue-operation", SOURCE_ID, operation="enqueue", content="Fix the header"))
        for index in range(count):
            lines.append(self.line("user", SOURCE_ID, "sdk-cli", uuid=f"u{index}"))
        return lines

    def run_command(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            code = resume_list.main(list(arguments), self.project, self.mac)
        return standins.result(code, output.getvalue(), errors.getvalue())

    def copies(self):
        return sorted(self.main.glob("*.jsonl"))


class ResumeList(Scratch):
    def test_copies_a_server_session_into_the_main_folder_as_a_terminal_session(self):
        self.source.write_text("".join(self.server_lines(2)))

        result = self.run_command("sync")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "", "a pass must print nothing")
        (copy,) = self.copies()
        entries = [json.loads(text) for text in copy.read_text().splitlines()]
        self.assertEqual(len(entries), 4)
        self.assertNotEqual(copy.stem, SOURCE_ID)
        self.assertEqual({entry["sessionId"] for entry in entries}, {copy.stem})
        self.assertEqual({entry["entrypoint"] for entry in entries if "entrypoint" in entry}, {"cli"})
        self.assertEqual(entries[1]["content"], "Fix the header")
        self.assertEqual(self.source.read_text(), "".join(self.server_lines(2)), "source untouched")

    def test_updates_the_same_copy_when_the_server_session_grows(self):
        self.source.write_text("".join(self.server_lines(1)))
        self.run_command("sync")
        (first,) = self.copies()
        self.source.write_text("".join(self.server_lines(3)))

        result = self.run_command("sync")

        self.assertEqual(result.returncode, 0, result.stderr)
        (copy,) = self.copies()
        self.assertEqual(copy.name, first.name)
        self.assertEqual(len(copy.read_text().splitlines()), 5)

    def test_leaves_the_copy_alone_when_the_server_session_did_not_change(self):
        self.source.write_text("".join(self.server_lines(1)))
        self.run_command("sync")
        (copy,) = self.copies()
        before = copy.stat().st_mtime_ns

        self.run_command("sync")

        self.assertEqual(copy.stat().st_mtime_ns, before)

    def test_ignores_a_line_that_is_still_being_written(self):
        self.source.write_text("".join(self.server_lines(1)) + '{"type":"user","sessionId":"')

        self.run_command("sync")

        (copy,) = self.copies()
        self.assertEqual(len(copy.read_text().splitlines()), 3)

    def test_never_overwrites_a_copy_that_was_continued_in_the_terminal(self):
        self.source.write_text("".join(self.server_lines(1)))
        self.run_command("sync")
        (first,) = self.copies()
        continued = first.read_text() + self.line("user", first.stem, "cli", uuid="terminal")
        first.write_text(continued)

        self.run_command("sync")
        self.assertEqual(first.read_text(), continued, "an unchanged source adds nothing")
        self.assertEqual(len(self.copies()), 1)

        self.source.write_text("".join(self.server_lines(4)))
        result = self.run_command("sync")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(first.read_text(), continued, "the continued copy is kept as it is")
        second = [copy for copy in self.copies() if copy.name != first.name]
        self.assertEqual(len(second), 1, "what the phone added goes to a new copy")
        self.assertEqual(len(second[0].read_text().splitlines()), 6)

    def test_does_not_bring_back_a_copy_the_user_deleted(self):
        self.source.write_text("".join(self.server_lines(1)))
        self.run_command("sync")
        (copy,) = self.copies()
        copy.unlink()

        self.run_command("sync")

        self.assertEqual(self.copies(), [])

    def test_skips_sessions_that_were_not_created_from_the_phone(self):
        terminal = self.server / "22222222-2222-4222-8222-222222222222.jsonl"
        terminal.write_text(self.line("user", terminal.stem, "cli", uuid="t"))
        # A `claude -p` run that the server session itself started in its worktree: the
        # same origin, but an ordinary random id (the server's sessions have a version 5 id).
        child_run = self.server / "33333333-3333-4333-8333-333333333333.jsonl"
        child_run.write_text(self.line("user", child_run.stem, "sdk-cli", uuid="c"))
        other = self.projects / transcripts.folder_name(str(Path(self.scratch.name).resolve() / "other") + WORKTREE)
        other.mkdir()
        (other / f"{SOURCE_ID}.jsonl").write_text("".join(self.server_lines(1)))

        self.run_command("sync")

        self.assertEqual(self.copies(), [])

    def test_exits_zero_and_logs_when_a_transcript_cannot_be_read(self):
        self.source.write_bytes(b"\xff\xfe not text\n")

        result = self.run_command("sync")

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.copies(), [])

    def test_lists_each_copy_with_the_command_that_resumes_it(self):
        self.source.write_text("".join(self.server_lines(1)))
        self.run_command("sync")
        (copy,) = self.copies()

        result = self.run_command("list")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Fix the header", result.stdout)
        self.assertIn(f"claude --resume {copy.stem}", result.stdout)
        self.assertIn("worktree removed", result.stdout)

    def test_rejects_an_unknown_command(self):
        result = self.run_command("frobnicate")

        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)


if __name__ == "__main__":
    unittest.main()
