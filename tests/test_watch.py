"""Tests of waiting for files and folders to change. They use real files in a scratch
folder: the wait is the system's own, and no test waits longer than a moment."""

import os
import signal
import tempfile
import time
import unittest
from pathlib import Path

from porchlight.atoms import watch

SOON = 2.0  # far longer than a change takes to be told; a test that passes never waits it


class Watching(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.file = self.root / "notes.txt"
        self.file.write_text("one\n")
        self.watcher = watch.Watcher()
        self.addCleanup(self.watcher.close)

    def append(self, path, text="more\n"):
        with open(path, "a") as handle:
            handle.write(text)

    def test_waits_the_seconds_given_when_nothing_changes(self):
        self.watcher.watch([self.file])
        began = time.monotonic()

        self.assertFalse(self.watcher.wait(0.05))

        self.assertGreaterEqual(time.monotonic() - began, 0.04)

    def test_a_file_that_grows_ends_the_wait_and_is_told_once(self):
        self.watcher.watch([self.file])
        self.append(self.file)

        began = time.monotonic()
        self.assertTrue(self.watcher.wait(SOON))
        self.assertLess(time.monotonic() - began, SOON / 2)
        self.assertFalse(self.watcher.wait(0), "what was told is not told again")

    def test_a_change_made_between_two_waits_is_told_by_the_next(self):
        self.watcher.watch([self.file])
        self.assertFalse(self.watcher.wait(0))
        self.append(self.file)
        self.watcher.watch([self.file])  # asked again, as every round does: nothing is forgotten

        self.assertTrue(self.watcher.wait(0))

    def test_a_file_replaced_by_another_ends_the_wait_and_the_new_one_is_watched_next(self):
        self.watcher.watch([self.file])
        draft = self.root / "notes.txt.new"
        draft.write_text("two\n")
        os.replace(draft, self.file)

        self.assertTrue(self.watcher.wait(SOON))

        self.watcher.watch([self.file])
        self.assertFalse(self.watcher.wait(0))
        self.append(self.file)
        self.assertTrue(self.watcher.wait(SOON))

    def test_a_folder_ends_the_wait_when_something_appears_in_it(self):
        self.watcher.watch([self.root])
        (self.root / "new.txt").write_text("")

        self.assertTrue(self.watcher.wait(SOON))

    def test_what_is_not_there_is_skipped_and_watched_once_it_is(self):
        later = self.root / "later.txt"
        self.watcher.watch([later, self.file])
        self.assertEqual(self.watcher.watched(), [str(self.file)])

        later.write_text("")
        self.watcher.watch([later, self.file])
        self.append(later)

        self.assertEqual(self.watcher.watched(), sorted([str(later), str(self.file)]))
        self.assertTrue(self.watcher.wait(SOON))

    def test_what_is_neither_a_file_nor_a_folder_is_not_watched(self):
        pipe = self.root / "pipe"
        os.mkfifo(pipe)

        def too_long(number, frame):
            raise AssertionError("watching a pipe nobody writes to never returned")

        before = signal.signal(signal.SIGALRM, too_long)  # opening such a pipe waits for its other end
        signal.alarm(5)
        try:
            self.watcher.watch([pipe, "/dev/null", self.file])
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, before)

        self.assertEqual(self.watcher.watched(), [str(self.file)])
        self.append(self.file)
        self.assertTrue(self.watcher.wait(SOON))

    def test_what_is_no_longer_asked_for_is_let_go(self):
        self.watcher.watch([self.file])
        self.watcher.watch([])
        self.append(self.file)

        self.assertEqual(self.watcher.watched(), [])
        self.assertFalse(self.watcher.wait(0.05))


class Waking(unittest.TestCase):
    def test_a_byte_on_the_wake_descriptor_ends_the_wait_and_is_no_change(self):
        reading, writing = os.pipe()
        self.addCleanup(os.close, reading)
        self.addCleanup(os.close, writing)
        os.set_blocking(reading, False)
        watcher = watch.Watcher(wake=reading)
        self.addCleanup(watcher.close)
        os.write(writing, b"\0")

        began = time.monotonic()
        self.assertFalse(watcher.wait(SOON))
        self.assertLess(time.monotonic() - began, SOON / 2)
        self.assertFalse(watcher.wait(0.01), "the byte was read: it wakes one wait")


if __name__ == "__main__":
    unittest.main()
