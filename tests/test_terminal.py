"""`setup` on a real terminal: a pseudo-terminal, the curses screens and the keys a person
presses. The Mac is still a stand-in; only the terminal is real."""

import fcntl
import os
import pty
import re
import select
import signal
import struct
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path

from porchlight import cli
from tests import standins

ENTER, DOWN, ESC, CTRL_C = b"\r", b"\x1bOB", b"\x1b", b"\x03"
WIDE, ROOMY, NARROW = (112, 32), (80, 24), (40, 12)
GIVE_UP = 20  # seconds a run may take before the test stops it
ESCAPES = re.compile(r"\x1b(\[[0-9;?]*[A-Za-z]|[()][A-Z0-9]|[=>])")


def resize(descriptor, size):
    columns, rows = size
    fcntl.ioctl(descriptor, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))


class Run:
    """`porchlight setup` in a child process whose terminal is a pseudo-terminal: what it
    drew, its exit code, the configuration file it was given."""

    def __init__(self, root, size, environ=None):
        self.config = Path(root) / "config.toml"
        self.screen = b""
        pid, descriptor = pty.fork()
        if pid == 0:  # the child: the pseudo-terminal is its terminal
            code = 70
            try:
                # the streams the parent made may buffer for a pipe: print to the terminal
                sys.stdout = sys.stderr = open(1, "w", buffering=1, encoding="utf-8", closefd=False)
                os.environ.update({"TERM": "xterm-256color", "LANG": "en_US.UTF-8"})
                os.environ.pop("NO_COLOR", None)
                os.environ.update(environ or {})
                resize(0, size)
                mac = standins.StandInMac(root, standins.Terminal())
                code = cli.main(["setup", "--config", str(self.config)], mac=mac)
            finally:
                sys.stdout.flush()
                os._exit(code)
        self.pid, self.descriptor, self.code = pid, descriptor, None

    def read(self, seconds):
        """Collect what is drawn for a while, or until the child is gone."""
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            ready, _, _ = select.select([self.descriptor], [], [], max(0.0, end - time.monotonic()))
            if not ready:
                break
            try:
                chunk = os.read(self.descriptor, 65536)
            except OSError:  # the child closed its terminal
                return False
            if not chunk:
                return False
            self.screen += chunk
        return True

    def started(self):
        """Wait for the first drawing."""
        end = time.monotonic() + GIVE_UP
        while not self.screen and time.monotonic() < end:
            self.read(0.2)
        self.read(0.3)

    def press(self, *keys):
        for key in keys:
            os.write(self.descriptor, key)
            self.read(0.15)

    def resized(self, size):
        resize(self.descriptor, size)
        os.kill(self.pid, signal.SIGWINCH)
        self.read(0.4)

    def ended(self):
        """The exit code once the child ends; the test fails if it does not."""
        end = time.monotonic() + GIVE_UP
        while time.monotonic() < end:
            self.read(0.2)
            done, status = os.waitpid(self.pid, os.WNOHANG)
            if done:
                self.read(0.2)
                os.close(self.descriptor)
                self.code = os.waitstatus_to_exitcode(status)
                return self.code
        os.kill(self.pid, signal.SIGKILL)
        os.waitpid(self.pid, 0)
        os.close(self.descriptor)
        raise AssertionError("setup still ran after %d seconds; it drew: %s" % (GIVE_UP, self.words))

    @property
    def text(self):
        return self.screen.decode("utf-8", "replace")

    @property
    def words(self):
        """The text without the terminal's escapes and the drawing, for a failure's message."""
        return " ".join(ESCAPES.sub(" ", self.text).replace("\u2580", " ").replace("\u2584", " ").split())[-600:]


class SetupOnATerminal(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = scratch.name

    def walk_through(self, size, environ=None, terminal=()):
        """Every screen with its default (the stand-in Claude Code lists no permission mode,
        so one is typed), then yes to saving. `terminal`: keys for the terminal's screen."""
        run = Run(self.root, size, environ)
        run.started()
        run.press(ENTER, *terminal, ENTER, b"plan", ENTER, ENTER, ENTER, b"y")
        return run

    def test_the_whole_screen_draws_and_saves_what_was_chosen(self):
        run = self.walk_through(WIDE)
        self.assertEqual(run.ended(), 0, run.words)
        self.assertTrue(run.config.exists())
        self.assertIn("▀", run.text)  # the lantern and the name, drawn in half blocks
        self.assertIn("Saved the configuration in %s." % run.config, run.text)

    def test_a_roomy_terminal_also_gets_the_whole_screen(self):
        run = self.walk_through(ROOMY)
        self.assertEqual(run.ended(), 0, run.words)
        self.assertTrue(run.config.exists())
        self.assertIn("▀", run.text)

    def test_without_colors_the_screens_are_plain_and_still_save(self):
        run = self.walk_through(WIDE, {"NO_COLOR": "1"})
        self.assertEqual(run.ended(), 0, run.words)
        self.assertTrue(run.config.exists())
        self.assertNotIn("▀", run.text)

    def test_q_quits_and_changes_nothing(self):
        run = Run(self.root, WIDE)
        run.started()
        run.press(b"q")
        self.assertEqual(run.ended(), 1)
        self.assertFalse(run.config.exists())
        self.assertIn("Nothing was changed.", run.text)

    def test_arrows_move_and_esc_goes_back(self):
        chosen = self.walk_through(WIDE, terminal=(DOWN, ESC, ENTER, DOWN))
        self.assertEqual(chosen.ended(), 0, chosen.words)
        moved = chosen.config.read_text()
        chosen.config.unlink()
        default = self.walk_through(WIDE)
        self.assertEqual(default.ended(), 0, default.words)
        self.assertNotEqual(moved, default.config.read_text())
        self.assertIn('"apple-terminal"', moved)

    def test_ctrl_c_while_typing_quits_and_changes_nothing(self):
        run = Run(self.root, WIDE)
        run.started()
        run.press(ENTER, ENTER, b"pl", CTRL_C)
        self.assertEqual(run.ended(), 1, run.words)
        self.assertFalse(run.config.exists())
        self.assertIn("Nothing was changed.", run.text)

    def test_a_terminal_that_shrinks_and_grows_keeps_drawing(self):
        run = Run(self.root, WIDE)
        run.started()
        run.resized(NARROW)
        run.resized((20, 5))
        run.resized(WIDE)
        drawn = len(run.screen)
        run.read(0.5)
        self.assertGreater(len(run.screen), drawn)  # the lantern still moves
        run.press(b"q")
        self.assertEqual(run.ended(), 1)
        self.assertIn("Nothing was changed.", run.text)


if __name__ == "__main__":
    unittest.main()
