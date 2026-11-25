"""Tests of finding claude, tmux and git: through PATH, then Homebrew's two prefixes."""

import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

import porchlight
from porchlight import config, names
from porchlight.atoms import tmux, tools
from porchlight.mac import Mac


class Find(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.folder = Path(self.scratch.name)

    def tearDown(self):
        self.scratch.cleanup()

    def tool(self, name):
        path = self.folder / name
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return str(path)

    def test_finds_a_tool_on_the_path_first(self):
        tmux = self.tool("tmux")

        found = tools.find("tmux", path=str(self.folder), executable=lambda candidate: True)

        self.assertEqual(found, tmux)

    def test_falls_back_to_the_homebrew_prefix_of_either_architecture(self):
        for folder in ("/opt/homebrew/bin", "/usr/local/bin"):
            found = tools.find(
                "tmux", path=str(self.folder), executable=lambda candidate: candidate == folder + "/tmux"
            )

            self.assertEqual(found, folder + "/tmux")

    def test_an_override_wins_over_the_path(self):
        self.tool("claude")

        self.assertEqual(tools.find("claude", override="/elsewhere/claude", path=str(self.folder)), "/elsewhere/claude")

    def test_says_which_tool_is_nowhere(self):
        self.assertIsNone(tools.find("tmux", path=str(self.folder), executable=lambda candidate: False))
        with self.assertRaises(tools.ToolNotFound) as caught:
            tools.need("tmux", path=str(self.folder), executable=lambda candidate: False)
        self.assertIn("tmux", str(caught.exception))

    def test_what_porchlight_starts_finds_homebrew_and_the_system(self):
        folders = tools.search_path().split(":")

        self.assertEqual(folders[:2], ["/opt/homebrew/bin", "/usr/local/bin"])
        self.assertEqual(folders[2:], ["/usr/bin", "/bin", "/usr/sbin", "/sbin"])
        self.assertEqual(
            tools.search_path("/custom/bin:/usr/bin").split(":")[-1], "/custom/bin", "what was there stays, last"
        )


class TheMac(unittest.TestCase):
    def test_reads_an_override_from_the_tools_own_variable(self):
        mac = Mac(environ={"PORCHLIGHT_CLAUDE": "/elsewhere/claude", "PATH": os.devnull})

        self.assertEqual(mac.claude, "/elsewhere/claude")

    def test_a_tool_is_looked_for_only_when_it_is_needed(self):
        mac = Mac(environ={"PORCHLIGHT_TMUX": "/elsewhere/tmux", "PORCHLIGHT_TMUX_SERVER": "porchlight-test"})

        self.assertEqual(mac.tmux.words("kill-server")[:3], ["/elsewhere/tmux", "-L", "porchlight-test"])
        self.assertEqual(mac.tmux.words()[3:], ["-f", str(tmux.packaged_config())])

    def test_opens_tabs_with_the_terminal_the_configuration_names(self):
        environ = {"PORCHLIGHT_WARP_TAB_CONFIGS": "/scratch/tab_configs"}

        self.assertIsNone(Mac.of(config.Config(), environ).terminal)
        self.assertEqual(Mac.of(config.Config("warp"), environ).terminal.configs, Path("/scratch/tab_configs"))
        self.assertEqual(Mac.of(config.Config("warp"), {}).terminal.configs, Path.home() / ".warp" / "tab_configs")

    def test_names_itself_by_the_installed_command_when_its_path_has_one(self):
        with tempfile.TemporaryDirectory() as scratch:
            installed = Path(scratch) / "porchlight"
            installed.write_text("#!/bin/sh\n")
            installed.chmod(0o755)

            self.assertEqual(Mac(environ={"PATH": scratch}).porchlight, shlex.quote(str(installed)))

    def test_names_itself_by_its_interpreter_and_its_own_folder_otherwise(self):
        package = Path(porchlight.__file__).resolve().parent

        self.assertEqual(
            shlex.split(Mac(environ={"PATH": os.devnull}).porchlight),
            ["/usr/bin/env", "PYTHONPATH=%s" % package.parent, sys.executable, "-m", "porchlight"],
        )

    def test_what_it_hands_out_reads_the_configuration_file_and_the_folders_it_reads_itself(self):
        environ = {"PATH": os.devnull, "PORCHLIGHT_STATE_DIR": "/scratch/state"}
        mac = Mac(environ=environ, config_file="/scratch/my config.toml")

        words = shlex.split(mac.porchlight)

        self.assertEqual(words[0], "/usr/bin/env")
        self.assertIn("PORCHLIGHT_CONFIG=/scratch/my config.toml", words)
        self.assertIn("PORCHLIGHT_STATE_DIR=/scratch/state", words)
        self.assertEqual(words[-3:], [sys.executable, "-m", "porchlight"])

    def test_what_it_hands_out_names_no_file_when_it_reads_the_default_one(self):
        with tempfile.TemporaryDirectory() as scratch:
            installed = Path(scratch) / "porchlight"
            installed.write_text("#!/bin/sh\n")
            installed.chmod(0o755)
            mac = Mac.of(config.Config(), {"PATH": scratch}, config_file=names.default_config())

            self.assertEqual(mac.porchlight, shlex.quote(str(installed)))
            self.assertEqual(mac.own_command(), ([str(installed)], {}))

    def test_keeps_its_agents_and_asks_launchd_as_the_environment_says(self):
        mac = Mac(environ={"PORCHLIGHT_LAUNCH_AGENTS_DIR": "/scratch/agents"})

        self.assertEqual(mac.launch_agents, Path("/scratch/agents"))
        self.assertEqual(mac.launchd.domain(), "gui/%d" % os.getuid())

    def test_reads_claude_codes_sessions_where_it_keeps_them_unless_told_otherwise(self):
        self.assertEqual(Mac(environ={}).transcripts, Path.home() / ".claude" / "projects")
        self.assertEqual(Mac(environ={"PORCHLIGHT_TRANSCRIPTS_DIR": "/scratch/t"}).transcripts, Path("/scratch/t"))


if __name__ == "__main__":
    unittest.main()
