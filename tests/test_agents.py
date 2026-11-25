"""Tests of the background agents: which ones a configuration asks for, what is decided for
each, and what `apply`, `start`, `stop` and `uninstall` then do. launchctl is a stand-in
and the agents' folder a scratch one: nothing is loaded, unloaded or signalled."""

import dataclasses
import itertools
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from porchlight import agents, config, names, session_settings
from porchlight.agents import KEEP, LEAVE, LOAD, REMOVE, RESTART, SERVER, SERVICE
from porchlight.atoms import launchd, state
from porchlight.features import ready_sessions, view_tabs
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SERVICE_LABEL = standins.LABEL
SHOP = standins.LABEL + ".server.shop"
BLOG = standins.LABEL + ".server.blog"
CHECK = "Check with: porchlight status, porchlight doctor"


class Decisions(unittest.TestCase):
    """What is done to one agent, for every state it may be in: a pure decision."""

    # kind, wanted, the file in the folder, loaded: (without --servers, with --servers)
    TABLE = {
        (SERVICE, True, "none", False): (LOAD, LOAD),
        (SERVICE, True, "same", False): (LOAD, LOAD),
        (SERVICE, True, "other", False): (LOAD, LOAD),
        (SERVICE, True, "none", True): (RESTART, RESTART),
        (SERVICE, True, "same", True): (KEEP, KEEP),
        (SERVICE, True, "other", True): (RESTART, RESTART),
        (SERVICE, False, "none", False): (None, None),
        (SERVICE, False, "same", False): (REMOVE, REMOVE),
        (SERVICE, False, "other", False): (REMOVE, REMOVE),
        (SERVICE, False, "none", True): (REMOVE, REMOVE),
        (SERVICE, False, "same", True): (REMOVE, REMOVE),
        (SERVICE, False, "other", True): (REMOVE, REMOVE),
        (SERVER, True, "none", False): (LOAD, LOAD),
        (SERVER, True, "same", False): (LOAD, LOAD),
        (SERVER, True, "other", False): (LOAD, LOAD),
        (SERVER, True, "none", True): (LEAVE, RESTART),
        (SERVER, True, "same", True): (KEEP, KEEP),
        (SERVER, True, "other", True): (LEAVE, RESTART),
        (SERVER, False, "none", False): (None, None),
        (SERVER, False, "same", False): (REMOVE, REMOVE),
        (SERVER, False, "other", False): (REMOVE, REMOVE),
        (SERVER, False, "none", True): (LEAVE, REMOVE),
        (SERVER, False, "same", True): (LEAVE, REMOVE),
        (SERVER, False, "other", True): (LEAVE, REMOVE),
    }
    SAME = {"Label": "one", "ProgramArguments": ["/tools/porchlight", "run"]}
    OTHER = {"Label": "one", "ProgramArguments": ["/elsewhere/porchlight", "run"]}

    def decide(self, kind, wanted, file, loaded, servers):
        agent = agents.Agent("one", kind, self.SAME if wanted else None)
        found = {"none": {}, "same": {"one": self.SAME}, "other": {"one": self.OTHER}}[file]
        return agents.decide([agent], found, {"one"} if loaded else set(), servers)

    def test_the_table_has_every_state_an_agent_may_be_in(self):
        every = set(itertools.product((SERVICE, SERVER), (True, False), ("none", "same", "other"), (True, False)))

        self.assertEqual(set(self.TABLE), every)

    def test_every_state_gets_the_action_of_the_table(self):
        for state_of, verbs in self.TABLE.items():
            for servers, verb in zip((False, True), verbs):
                actions = self.decide(*state_of, servers)
                self.assertEqual([action.verb for action in actions], [verb] if verb else [], (state_of, servers))
                self.assertTrue(all(action.agent.label == "one" for action in actions))

    def test_a_loaded_server_is_never_stopped_restarted_or_removed_without_the_flag(self):
        for (kind, wanted, file, loaded), (verb, _) in self.TABLE.items():
            if kind == SERVER and loaded:
                self.assertIn(verb, (KEEP, LEAVE), (wanted, file))

    def test_a_server_left_as_it_is_says_why(self):
        self.assertEqual(self.decide(SERVER, True, "other", True, False)[0].why, agents.CHANGED)
        self.assertEqual(self.decide(SERVER, False, "same", True, False)[0].why, agents.UNWANTED)

    def test_servers_may_name_the_projects_or_the_labels_whose_running_server_may_change(self):
        unwanted = agents.Agent(SHOP, SERVER, None, "shop")
        changed = agents.Agent(SHOP, SERVER, self.SAME, "shop")

        def verbs(agent, servers):
            return [action.verb for action in agents.decide([agent], {SHOP: self.OTHER}, {SHOP}, servers)]

        for servers in (["shop"], {SHOP}, ("blog", "shop")):
            self.assertEqual(verbs(unwanted, servers), [REMOVE], servers)
            self.assertEqual(verbs(changed, servers), [RESTART], servers)
        for servers in (["blog"], (), None, False):
            self.assertEqual(verbs(unwanted, servers), [LEAVE], servers)
            self.assertEqual(verbs(changed, servers), [LEAVE], servers)

    def test_a_file_that_cannot_be_read_counts_as_changed(self):
        agent = agents.Agent("one", SERVICE, self.SAME)

        self.assertEqual([action.verb for action in agents.decide([agent], {"one": None}, {"one"})], [RESTART])

    def test_each_agent_is_decided_by_itself_in_the_order_given(self):
        one, two, three = (
            agents.Agent("one", SERVICE, self.SAME),
            agents.Agent("two", SERVER, self.SAME),
            agents.Agent("three", SERVER, None),
        )

        actions = agents.decide([one, two, three], {"two": self.OTHER, "three": self.SAME}, {"two", "three"})

        self.assertEqual([(action.agent.label, action.verb) for action in actions], [("one", LOAD), ("two", LEAVE), ("three", LEAVE)])


class OnTheMac(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.mac = standins.StandInMac(self.root)
        self.mac.config_file = self.root / "config.toml"
        self.folder = self.root / "agents"
        self.printed = []

    def configuration(self, **projects):
        """A configuration: each project with the features given, in a folder of its own."""
        configured = []
        for name, features in projects.items():
            (self.root / name).mkdir(exist_ok=True)
            configured.append(
                config.Project(name, str(self.root / name), "plan", config.ordered(features), None, name.capitalize())
            )
        return config.Config(None, tuple(configured))

    def apply(self, configuration, **options):
        self.printed.clear()
        return agents.apply(configuration, self.mac, self.printed.append, **options)

    def files(self):
        return sorted(path.name for path in self.folder.iterdir()) if self.folder.is_dir() else []

    def definition(self, label):
        return launchd.read(launchd.file(self.folder, label))

    def everything(self):
        """What a test must find untouched: the files, what is loaded and what launchctl changed."""
        return self.files(), set(self.mac.launchctl.loaded), self.mac.launchctl.did()


class Wanted(OnTheMac):
    def test_no_project_asks_for_no_agent(self):
        self.assertEqual(agents.wanted(config.Config(), self.mac), [])

    def test_one_service_for_all_and_a_server_for_each_project_that_has_the_feature(self):
        configuration = self.configuration(shop=("server",), blog=("ready-session",), docs=("server", "resume-list"))

        found = agents.wanted(configuration, self.mac)

        self.assertEqual(
            [(agent.label, agent.kind) for agent in found],
            [(SERVICE_LABEL, SERVICE), (SHOP, SERVER), (standins.LABEL + ".server.docs", SERVER)],
        )

    def test_the_service_runs_the_tool_and_what_it_starts_outlives_it(self):
        service = agents.wanted(self.configuration(shop=("ready-session",)), self.mac)[0].definition

        self.assertEqual(service["Label"], SERVICE_LABEL)
        self.assertEqual(service["ProgramArguments"], ["/tools/porchlight", "run"])
        self.assertIs(service["RunAtLoad"], True)
        self.assertIs(service["KeepAlive"], True)
        self.assertIs(service["AbandonProcessGroup"], True, "its tmux sessions and tabs survive a restart")
        self.assertEqual(service["StandardOutPath"], str(self.root / "logs" / "agent.service.log"))
        self.assertEqual(service["StandardErrorPath"], service["StandardOutPath"])
        self.assertNotIn("WorkingDirectory", service)

    def test_a_server_runs_in_its_projects_folder_and_ends_with_what_it_started(self):
        configuration = self.configuration(shop=("server",))

        server = agents.wanted(configuration, self.mac)[1].definition

        self.assertEqual(server["Label"], SHOP)
        self.assertEqual(server["ProgramArguments"], ["/tools/porchlight", "server", "shop", "--permission-mode", "plan"])
        self.assertEqual(server["WorkingDirectory"], str(names.repository(configuration.project("shop"))))
        self.assertIs(server["RunAtLoad"], True)
        self.assertIs(server["KeepAlive"], True)
        self.assertNotIn("AbandonProcessGroup", server)
        self.assertEqual(server["StandardOutPath"], str(self.root / "logs" / "agent.server.shop.log"))

    def test_the_path_has_the_folders_of_the_tools_found_then_homebrews_and_the_systems(self):
        self.mac.found = {"claude": "/home/someone/.local/bin/claude", "git": "/usr/bin/git"}  # no tmux

        service = agents.wanted(self.configuration(shop=("server",)), self.mac)[0].definition

        self.assertEqual(
            service["EnvironmentVariables"]["PATH"].split(":"),
            ["/home/someone/.local/bin", "/usr/bin", "/opt/homebrew/bin", "/usr/local/bin", "/bin", "/usr/sbin", "/sbin"],
        )

    def test_every_variable_of_the_tool_and_the_configuration_file_reach_the_agents(self):
        self.mac.environ["PATH"] = "/somewhere/else"
        self.mac.environ["HOME"] = "/home/someone"

        for agent in agents.wanted(self.configuration(shop=("server",)), self.mac):
            environment = dict(agent.definition["EnvironmentVariables"])
            environment.pop("PATH")
            self.assertEqual(
                environment,
                {
                    "PORCHLIGHT_STATE_DIR": str(self.root / "state"),
                    "PORCHLIGHT_LOG_DIR": str(self.root / "logs"),
                    "PORCHLIGHT_TRANSCRIPTS_DIR": str(self.root / "transcripts"),
                    "PORCHLIGHT_TMUX_SERVER": standins.TMUX_SERVER,
                    "PORCHLIGHT_LAUNCH_AGENTS_DIR": str(self.root / "agents"),
                    "PORCHLIGHT_LABEL": standins.LABEL,
                    "PORCHLIGHT_CONFIG": str(self.root / "config.toml"),
                },
                agent.label,
            )

    def test_a_copy_that_was_never_installed_names_its_interpreter_and_its_own_folder(self):
        self.mac.own_command = lambda: (["/some/python3", "-m", "porchlight"], {"PYTHONPATH": "/its/folder"})

        service = agents.wanted(self.configuration(shop=("server",)), self.mac)[0].definition

        self.assertEqual(service["ProgramArguments"], ["/some/python3", "-m", "porchlight", "run"])
        self.assertEqual(service["EnvironmentVariables"]["PYTHONPATH"], "/its/folder")

    def test_launchd_reads_the_definitions_written(self):
        configuration = self.configuration(shop=("server",))
        for agent in agents.wanted(configuration, self.mac):
            launchd.write(launchd.file(self.folder, agent.label), agent.definition)

        for name in self.files():
            checked = subprocess.run(["/usr/bin/plutil", "-lint", str(self.folder / name)], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)


class Apply(OnTheMac):
    def setUp(self):
        super().setUp()
        self.both = self.configuration(shop=("server",), blog=("server",))

    def test_loads_what_is_wanted_and_not_loaded_from_a_file_it_writes(self):
        self.assertEqual(self.apply(self.both), 0)

        self.assertEqual(self.files(), [SERVICE_LABEL + ".plist", BLOG + ".plist", SHOP + ".plist"])
        self.assertEqual(self.mac.launchctl.did(), [("load", SERVICE_LABEL), ("load", SHOP), ("load", BLOG)])
        self.assertEqual(self.mac.launchctl.definitions[SHOP], agents.wanted(self.both, self.mac)[1].definition)
        self.assertEqual(
            self.printed,
            [SERVICE_LABEL + ": loaded", SHOP + ": loaded", BLOG + ": loaded", CHECK],
        )
        self.assertTrue((self.root / "logs").is_dir(), "launchd makes no folder for a log")

    def test_run_again_it_leaves_alone_what_is_loaded_and_unchanged(self):
        self.apply(self.both)
        before = self.everything()

        self.assertEqual(self.apply(self.both), 0)

        self.assertEqual(self.everything(), before)
        self.assertEqual(
            self.printed,
            [
                SERVICE_LABEL + ": already loaded, nothing changed",
                SHOP + ": already loaded, nothing changed",
                BLOG + ": already loaded, nothing changed",
                CHECK,
            ],
        )

    def test_the_service_whose_definition_changed_is_rewritten_and_restarted(self):
        self.apply(self.both)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"  # the PATH of every agent changes
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.both), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL), ("load", SERVICE_LABEL)])
        self.assertIn("/elsewhere/bin", self.definition(SERVICE_LABEL)["EnvironmentVariables"]["PATH"])
        self.assertIn("/elsewhere/bin", self.mac.launchctl.definitions[SERVICE_LABEL]["EnvironmentVariables"]["PATH"])
        self.assertEqual(self.printed[0], SERVICE_LABEL + ": restarted with its new definition")

    def test_a_loaded_server_whose_definition_changed_is_left_as_it_is_and_said(self):
        self.apply(self.both)
        written = self.definition(SHOP)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.both), 0, "nothing failed: it was left on purpose")

        self.assertNotIn(("unload", SHOP), self.mac.launchctl.did())
        self.assertNotIn(("load", SHOP), self.mac.launchctl.did())
        self.assertEqual(self.definition(SHOP), written, "the file still says what is loaded")
        self.assertEqual(
            self.printed[1:],
            [
                SHOP + ": left running as it is, though its definition changed",
                BLOG + ": left running as it is, though its definition changed",
                "A running server is restarted or removed only when asked, because the app cannot start its "
                "sessions again. To include them (shop, blog): porchlight apply --servers",
                CHECK,
            ],
        )

    def moded(self, configuration, **modes):
        """The configuration with the permission modes given, by project."""
        projects = tuple(dataclasses.replace(p, permission_mode=modes.get(p.name, p.permission_mode)) for p in configuration.projects)
        return dataclasses.replace(configuration, projects=projects)

    def test_a_new_permission_mode_changes_a_servers_definition_and_its_running_server_is_left_as_it_is(self):
        self.apply(self.both)
        written = self.definition(SHOP)
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.moded(self.both, shop="acceptEdits")), 0)

        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(self.definition(SHOP), written)
        self.assertEqual(
            self.printed[1:3],
            [SHOP + ": left running as it is, though its definition changed", BLOG + ": already loaded, nothing changed"],
        )

    def test_with_servers_a_new_permission_mode_restarts_the_server_with_it(self):
        self.apply(self.both)
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.moded(self.both, shop="acceptEdits"), servers=["shop"]), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SHOP), ("load", SHOP)])
        self.assertEqual(self.definition(SHOP)["ProgramArguments"][-2:], ["--permission-mode", "acceptEdits"])
        self.assertEqual(self.printed[1], SHOP + ": restarted with its new definition")

    def test_the_agent_file_of_a_server_left_running_keeps_its_old_mode_through_stop_and_start(self):
        self.apply(self.both)
        self.apply(self.moded(self.both, shop="acceptEdits"))  # left running as it is

        agents.stop(self.mac, self.printed.append, servers=True)
        agents.start(self.mac, self.printed.append)

        self.assertEqual(self.mac.launchctl.definitions[SHOP]["ProgramArguments"][-2:], ["--permission-mode", "plan"])

    def test_a_server_loaded_from_a_file_without_its_permission_mode_is_the_tools_and_counts_as_changed(self):
        self.apply(self.both)
        earlier = self.definition(SHOP)
        earlier["ProgramArguments"] = earlier["ProgramArguments"][:-2]
        launchd.write(launchd.file(self.folder, SHOP), earlier)
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.both), 0)
        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(self.printed[1], SHOP + ": left running as it is, though its definition changed")

        self.assertEqual(self.apply(self.both, servers=True), 0)
        self.assertEqual(self.mac.launchctl.did(), [("unload", SHOP), ("load", SHOP)])

    def test_a_loaded_server_the_configuration_no_longer_has_is_left_as_it_is_and_said(self):
        self.apply(self.both)
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.configuration(shop=("server",))), 0)

        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertIn(BLOG + ".plist", self.files())
        self.assertIn(BLOG, self.mac.launchctl.loaded)
        self.assertEqual(
            self.printed[2:],
            [
                BLOG + ": left running, though the configuration no longer has it",
                "A running server is restarted or removed only when asked, because the app cannot start its "
                "sessions again. To include them (blog): porchlight apply --servers",
                CHECK,
            ],
        )

    def test_with_servers_a_changed_server_is_restarted_and_an_unwanted_one_removed(self):
        self.apply(self.both)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.configuration(shop=("server",)), servers=True), 0)

        self.assertEqual(
            self.mac.launchctl.did(),
            [("unload", SERVICE_LABEL), ("load", SERVICE_LABEL), ("unload", SHOP), ("load", SHOP), ("unload", BLOG)],
        )
        self.assertEqual(self.files(), [SERVICE_LABEL + ".plist", SHOP + ".plist"])
        self.assertEqual(
            self.printed,
            [
                SERVICE_LABEL + ": restarted with its new definition",
                SHOP + ": restarted with its new definition",
                BLOG + ": unloaded and removed",
                CHECK,
            ],
        )

    def test_servers_may_name_the_projects_whose_running_server_it_may_restart_or_remove(self):
        self.apply(self.both)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"  # every definition changes
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.configuration(shop=("server",)), servers=["blog"]), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL), ("load", SERVICE_LABEL), ("unload", BLOG)])
        self.assertEqual(self.files(), [SERVICE_LABEL + ".plist", SHOP + ".plist"])
        self.assertEqual(
            self.printed[1:],
            [
                SHOP + ": left running as it is, though its definition changed",
                BLOG + ": unloaded and removed",
                "A running server is restarted or removed only when asked, because the app cannot start its "
                "sessions again. To include them (shop): porchlight apply --servers",
                CHECK,
            ],
        )

    def test_servers_may_name_them_by_their_labels_too(self):
        self.apply(self.both)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.both, servers=(SHOP,)), 0)

        self.assertIn(("load", SHOP), self.mac.launchctl.did())
        self.assertNotIn(("unload", BLOG), self.mac.launchctl.did())

    def test_naming_no_project_protects_every_running_server(self):
        self.apply(self.both)
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(self.configuration(), servers=[]), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL)])
        self.assertEqual(self.mac.launchctl.loaded, {SHOP, BLOG})

    def test_a_server_that_is_not_loaded_is_loaded_with_its_new_definition_without_the_flag(self):
        self.apply(self.both)
        self.mac.launchctl.loaded.discard(SHOP)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"

        self.apply(self.both)

        self.assertIn(("load", SHOP), self.mac.launchctl.did())
        self.assertIn("/elsewhere/bin", self.mac.launchctl.definitions[SHOP]["EnvironmentVariables"]["PATH"])

    def test_an_agent_no_longer_wanted_that_is_no_loaded_server_is_unloaded_and_removed(self):
        self.apply(self.both)
        self.mac.launchctl.loaded.discard(BLOG)  # a server that does not run
        self.mac.launchctl.calls.clear()

        self.assertEqual(self.apply(config.Config()), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL)], "the service goes with the last project")
        self.assertEqual(self.files(), [SHOP + ".plist"])
        self.assertEqual(self.printed[0], SERVICE_LABEL + ": unloaded and removed")
        self.assertEqual(self.printed[1], BLOG + ": removed")
        self.assertEqual(self.printed[2], SHOP + ": left running, though the configuration no longer has it")

    def test_touches_no_agent_that_is_not_its_own(self):
        self.folder.mkdir()
        others = ["com.example.other", standins.LABEL + ".rehearsal", standins.LABEL + "x", "io.github.alejandrovdev.porchlight"]
        for label in others:
            launchd.write(launchd.file(self.folder, label), {"Label": label})
        self.mac.launchctl.loaded.update(others)

        self.apply(config.Config(), servers=True)

        self.assertEqual(self.files(), sorted(label + ".plist" for label in others))
        self.assertEqual(self.mac.launchctl.did(), [])

    def test_without_a_project_and_without_an_agent_it_says_how_to_add_a_project(self):
        self.assertEqual(self.apply(config.Config()), 0)

        self.assertEqual(self.printed, ["No project is configured. Add one from its folder with: porchlight init", CHECK])
        self.assertEqual(self.files(), [])
        self.assertEqual(self.mac.launchctl.did(), [])

    def test_changes_nothing_when_launchd_cannot_say_what_is_loaded(self):
        self.mac.launchctl.lists = False

        self.assertEqual(self.apply(self.both), 1)

        self.assertEqual(self.files(), [])
        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(
            self.printed, ["launchd could not say what is loaded (Could not contact launchd). Nothing was changed."]
        )

    def test_an_agent_that_does_not_load_is_said_and_the_others_still_load(self):
        self.mac.launchctl.refused.add(SHOP)

        self.assertEqual(self.apply(self.both), 1)

        self.assertEqual(self.printed[1], SHOP + ": could not be loaded: Bootstrap failed: 5: Input/output error")
        self.assertEqual(self.mac.launchctl.loaded, {SERVICE_LABEL, BLOG})
        self.assertEqual(self.mac.launchctl.did().count(("load", SHOP)), 2, "asked once more, a moment later")

    def test_a_service_that_does_not_stop_keeps_its_file_and_is_said(self):
        self.apply(self.both)
        written = self.definition(SERVICE_LABEL)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"
        self.mac.launchctl.stuck.add(SERVICE_LABEL)

        self.assertEqual(self.apply(self.both), 1)

        self.assertEqual(self.definition(SERVICE_LABEL), written)
        self.assertEqual(self.printed[0], SERVICE_LABEL + ": could not be unloaded, so it was left as it is")


class Settings(OnTheMac):
    def stage(self, configuration, name, mode):
        """Session settings in place, and others waiting with another mode."""
        project = configuration.project(name)
        path = self.mac.settings(project)
        session_settings.stage(standins.project(name, project.path, mode=mode), path)
        session_settings.stage(project, path)
        return path

    def mode(self, path):
        return json.loads(Path(path).read_text())["permissions"]["defaultMode"]

    def test_installs_the_settings_that_waited_for_a_project_without_the_server(self):
        configuration = self.configuration(shop=("ready-session",))
        path = self.stage(configuration, "shop", "acceptEdits")
        self.assertEqual(self.mode(path), "acceptEdits")

        self.assertEqual(self.apply(configuration), 0)

        self.assertEqual(self.mode(path), "plan")
        self.assertFalse(session_settings.waiting(path).exists())
        self.assertIn("shop: installed the session settings that waited", self.printed)

    def test_brings_the_settings_of_such_a_project_up_to_date_even_before_anything_waits(self):
        configuration = self.configuration(shop=("ready-session",))
        path = self.mac.settings(configuration.project("shop"))
        session_settings.stage(standins.project("shop", mode="acceptEdits"), path)

        self.apply(configuration)

        self.assertEqual(self.mode(path), "plan")

    def test_with_the_server_they_wait_for_its_next_start(self):
        configuration = self.configuration(shop=("server", "ready-session"))
        path = self.stage(configuration, "shop", "acceptEdits")

        self.apply(configuration)

        self.assertEqual(self.mode(path), "acceptEdits", "a running server refuses a file that changed")
        self.assertEqual(self.mode(session_settings.waiting(path)), "plan")

    def test_they_wait_too_while_the_server_the_project_no_longer_has_is_left_running(self):
        self.apply(self.configuration(shop=("server",)))
        configuration = self.configuration(shop=("ready-session",))
        path = self.stage(configuration, "shop", "acceptEdits")

        self.apply(configuration)
        self.assertEqual(self.mode(path), "acceptEdits", "the server that still runs refuses a file that changed")

        self.apply(configuration, servers=True)
        self.assertEqual(self.mode(path), "plan")

    def test_makes_no_settings_for_a_project_that_never_had_any(self):
        configuration = self.configuration(shop=("ready-session",))

        self.apply(configuration)

        self.assertFalse(self.mac.settings(configuration.project("shop")).exists())
        self.assertEqual(self.printed, [SERVICE_LABEL + ": loaded", CHECK])


class StartAndStop(OnTheMac):
    def setUp(self):
        super().setUp()
        agents.apply(self.configuration(shop=("server",), blog=("server",)), self.mac, lambda line: None)
        self.mac.launchctl.calls.clear()

    def start(self):
        return agents.start(self.mac, self.printed.append)

    def stop(self, **options):
        return agents.stop(self.mac, self.printed.append, **options)

    def test_start_loads_every_agent_that_has_a_file_and_is_not_loaded(self):
        self.mac.launchctl.loaded = {BLOG}

        self.assertEqual(self.start(), 0)

        self.assertEqual(self.mac.launchctl.did(), [("load", SERVICE_LABEL), ("load", SHOP)])
        self.assertEqual(self.printed, [SERVICE_LABEL + ": loaded", BLOG + ": already loaded", SHOP + ": loaded"])

    def test_start_without_any_file_says_to_apply(self):
        for name in self.files():
            (self.folder / name).unlink()

        self.assertEqual(self.start(), 1)

        self.assertEqual(self.printed, ["No agent is installed. Install them with: porchlight apply"])
        self.assertEqual(self.mac.launchctl.did(), [])

    def test_start_loads_no_file_that_is_not_its_own(self):
        launchd.write(launchd.file(self.folder, "com.example.other"), {"Label": "com.example.other"})
        self.mac.launchctl.loaded = set()

        self.start()

        self.assertNotIn(("load", "com.example.other"), self.mac.launchctl.did())

    def test_stop_unloads_the_service_only_and_says_the_sessions_keep_running(self):
        self.assertEqual(self.stop(), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL)])
        self.assertEqual(self.mac.launchctl.loaded, {SHOP, BLOG})
        self.assertEqual(len(self.files()), 3, "the files stay: start loads them again")
        self.assertEqual(
            self.printed,
            [
                SERVICE_LABEL + ": unloaded",
                "The servers keep running (blog, shop); porchlight stop --servers unloads them too.",
                "Sessions already running keep running. Start again with: porchlight start",
            ],
        )

    def test_stop_with_servers_unloads_them_too(self):
        self.assertEqual(self.stop(servers=True), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL), ("unload", BLOG), ("unload", SHOP)])
        self.assertEqual(self.mac.launchctl.loaded, set())
        self.assertEqual(
            self.printed,
            [
                SERVICE_LABEL + ": unloaded",
                BLOG + ": unloaded",
                SHOP + ": unloaded",
                "Sessions already running keep running, except those a server started: they ended with it. "
                "Start again with: porchlight start",
            ],
        )

    def test_stop_says_when_the_service_is_not_loaded(self):
        self.mac.launchctl.loaded = set()

        self.assertEqual(self.stop(), 0)

        self.assertEqual(self.printed[0], SERVICE_LABEL + ": not loaded")
        self.assertEqual(self.mac.launchctl.did(), [])

    def test_stop_says_what_did_not_unload(self):
        self.mac.launchctl.stuck.add(SERVICE_LABEL)

        self.assertEqual(self.stop(), 1)

        self.assertEqual(self.printed[0], SERVICE_LABEL + ": could not be unloaded, so it was left as it is")

    def test_neither_does_anything_when_launchd_cannot_say_what_is_loaded(self):
        self.mac.launchctl.lists = False

        self.assertEqual(self.start(), 1)
        self.assertEqual(self.stop(servers=True), 1)

        self.assertEqual(self.mac.launchctl.did(), [])


class Uninstall(OnTheMac):
    def setUp(self):
        super().setUp()
        self.both = self.configuration(shop=("server", "ready-session"), blog=("ready-session",))
        self.shop, self.blog = self.both.projects
        agents.apply(self.both, self.mac, lambda line: None)
        self.mac.launchctl.calls.clear()
        self.mac.git_runner.answers = self.git

    def git(self, words):
        """A repository whose worktrees are clean and on the base branch."""
        if "symbolic-ref" in words:
            return standins.result(stdout="origin/main\n")

    def uninstall(self, **options):
        self.printed.clear()
        return agents.uninstall(self.both, self.mac, self.printed.append, **options)

    def session(self, project, session, state_of, pid):
        """A ready session in a project's state, its worktree and its process."""
        worktree = names.repository(project) / ".claude" / "worktrees" / names.worktree(project, session)
        worktree.mkdir(parents=True)
        record = {
            "state": state_of,
            "started": self.mac.now,
            "changed": self.mac.now,
            "worktree": str(worktree),
            "branch": names.branch(project, session),
            "prompt": "" if state_of == "free" else "Fix the header",
            "title": "",
            "cse": "",
            "tidied": False,
            "shown": state_of != "free",
            "tmux": names.tmux_session(project, session),
        }
        store = self.mac.store(project, ready_sessions.STATE)
        saved = ready_sessions.load_state(store)
        saved["sessions"][session] = record
        store.save(saved)
        self.mac.ps += f"{pid} claude --session-id {session} --remote-control\n"

    def ends_when_asked(self):
        """A process ends once it is asked to, as Claude Code does."""

        def terminate(pid):
            self.mac.terminated.append(pid)
            self.mac.ps = "".join(line for line in self.mac.ps.splitlines(True) if not line.startswith("%d " % pid))

        self.mac.terminate = terminate

    def sessions(self, project):
        return self.mac.store(project, ready_sessions.STATE).load({}).get("sessions", {})

    def test_removes_every_agent_but_a_loaded_server_and_exits_one_listing_it(self):
        self.assertEqual(self.uninstall(), 1)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL)])
        self.assertEqual(self.files(), [SHOP + ".plist"])
        self.assertEqual(self.mac.launchctl.loaded, {SHOP})
        self.assertEqual(
            self.printed,
            [
                SERVICE_LABEL + ": unloaded and removed",
                SHOP + ": left running",
                "No ready session and no session in use is running. A server left running keeps the sessions it "
                "started.",
                "A running server is removed only when asked, because the app cannot start its sessions again. "
                "To remove them (shop): porchlight uninstall --servers",
                "The configuration, the state and the logs were kept; porchlight uninstall --purge removes them.",
            ],
        )

    def test_with_servers_removes_them_too_and_exits_zero(self):
        self.assertEqual(self.uninstall(servers=True), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL), ("unload", SHOP)])
        self.assertEqual(self.files(), [])
        self.assertEqual(self.printed[:2], [SERVICE_LABEL + ": unloaded and removed", SHOP + ": unloaded and removed"])

    def test_a_server_that_is_not_loaded_is_removed_without_the_flag(self):
        self.mac.launchctl.loaded.discard(SHOP)

        self.assertEqual(self.uninstall(), 0)

        self.assertEqual(self.files(), [])
        self.assertEqual(self.printed[1], SHOP + ": removed")

    def test_ends_the_free_sessions_and_leaves_those_in_use_running_and_counted(self):
        self.session(self.shop, A, "free", 601)
        self.session(self.blog, B, "used", 602)
        self.ends_when_asked()

        self.assertEqual(self.uninstall(servers=True), 0)

        self.assertEqual(self.mac.terminated, [601], "only the session nobody used")
        self.assertEqual(self.sessions(self.shop), {}, "let go as a feature turned off lets go of it")
        self.assertEqual(self.sessions(self.blog)[B]["state"], "used")
        self.assertIn("removed the worktree porchlight-shop-aaaaaaaa", self.mac.log_text(self.shop))
        self.assertEqual(self.terminal_tabs(), [], "no tab opens while uninstalling")
        self.assertEqual(self.printed[2:4], ["shop: ended the free session it held", "1 session in use keeps running."])

    def terminal_tabs(self):
        return [] if self.mac.terminal is None else self.mac.terminal.tabs

    def test_the_service_is_unloaded_before_the_free_sessions_are_let_go(self):
        self.session(self.shop, A, "free", 601)
        self.ends_when_asked()
        order = []
        self.mac.launchctl.on_unload = lambda label: order.append("unload " + label)
        terminate = self.mac.terminate
        self.mac.terminate = lambda pid: (order.append("end %d" % pid), terminate(pid))

        self.uninstall()

        self.assertEqual(order, ["unload " + SERVICE_LABEL, "end 601"], "else the service would prepare another")

    def test_lets_go_of_no_session_while_a_service_started_by_hand_still_runs(self):
        self.session(self.shop, A, "free", 601)
        held = state.exclusive(names.service_lock(self.mac.environ))
        self.addCleanup(held.close)

        self.assertEqual(self.uninstall(servers=True), 1)

        self.assertEqual(self.mac.terminated, [])
        self.assertIn(
            "A porchlight run that launchd did not start is still running: end it, and run this again.", self.printed
        )

    def test_keeps_the_configuration_the_state_and_the_logs_unless_purged(self):
        self.mac.config_file.write_text("")
        self.session(self.blog, B, "closed", 602)
        self.mac.ps = ""
        self.mac.log(self.blog, "something happened")

        self.assertEqual(self.uninstall(servers=True), 0)

        self.assertTrue(self.mac.config_file.exists())
        self.assertIn(B, self.sessions(self.blog))
        self.assertTrue(names.log_file(self.blog, self.mac.environ).exists())

    def purged(self, before=lambda: None):
        """A purge that nothing stops: files of every kind the tool keeps, and no session
        running. `before` runs once they are written."""
        self.mac.config_file.write_text("")
        self.session(self.blog, B, "closed", 602)
        self.mac.ps = ""
        self.mac.store(self.shop, view_tabs.STATE).save({})
        session_settings.stage(self.shop, self.mac.settings(self.shop))
        session_settings.stage(standins.project("shop", mode="acceptEdits"), self.mac.settings(self.shop))
        self.mac.log(self.blog, "something happened")
        names.service_log(self.mac.environ).write_text("started\n")
        names.server_log(self.shop, self.mac.environ).write_text("started\n")
        before()
        return self.uninstall(servers=True, purge=True)

    def test_purge_removes_the_configuration_the_state_and_the_logs(self):
        self.assertEqual(self.purged(), 0)

        self.assertFalse(self.mac.config_file.exists())
        self.assertFalse((self.root / "state").exists())
        self.assertFalse((self.root / "logs").exists())
        self.assertEqual(self.printed[-1], "Removed the configuration, the state and the logs.")

    def test_purge_removes_the_state_folder_that_saving_the_configuration_made(self):
        """By default the configuration file lives in the state folder: whoever saves it first
        makes that folder, and the tool owns it."""
        shared = self.root / "state"
        self.mac.config_file = shared / "config.toml"
        config.save(config.Config("warp", (), config.Defaults()), self.mac.config_file)

        self.assertEqual(self.uninstall(servers=True, purge=True), 0)

        self.assertFalse(shared.exists())
        self.assertEqual(self.printed[-1], "Removed the configuration, the state and the logs.")

    def test_purge_removes_no_configuration_file_it_was_not_given(self):
        default = self.root / "default.toml"
        default.write_text("")
        self.mac.config_file = None

        with mock.patch.dict("os.environ", {"PORCHLIGHT_CONFIG": str(default)}):
            self.assertEqual(self.uninstall(servers=True, purge=True), 0)

        self.assertTrue(default.exists(), "the file in use is named by whoever read it, never guessed")
        self.assertFalse((self.root / "state").exists())

    def test_purge_removes_the_configuration_file_it_is_given(self):
        given = self.root / "given.toml"
        given.write_text("")

        self.assertEqual(self.uninstall(servers=True, purge=True, config_file=given), 0)

        self.assertFalse(given.exists())

    def test_purge_removes_only_the_files_the_tool_makes(self):
        self.mac.store(self.blog, ready_sessions.STATE).save({})  # the tool makes its folder, and marks it
        mine = [
            self.root / "state" / "notes.txt",
            self.root / "state" / "projects" / "blog" / "keep.json",
            self.root / "logs" / "another.tool.log",
        ]
        (self.root / "logs").mkdir(exist_ok=True)
        for path in mine:
            path.write_text("the person's own")

        self.assertEqual(self.purged(), 0)

        self.assertTrue(all(path.exists() for path in mine))
        kept = sorted(path.name for path in (self.root / "state").rglob("*") if path.is_file())
        self.assertEqual(kept, [self.MARKER, "keep.json", "notes.txt"], "the folder is still the tool's: its marker stays")
        self.assertEqual(sorted(path.name for path in (self.root / "logs").iterdir()), [self.MARKER, "another.tool.log"])

    def test_purge_refuses_while_a_session_of_the_tools_state_still_runs(self):
        self.mac.config_file.write_text("")
        self.session(self.blog, B, "used", 602)

        self.assertEqual(self.uninstall(servers=True, purge=True), 1)

        self.assertTrue(self.mac.config_file.exists())
        self.assertIn(B, self.sessions(self.blog))
        # The service that ended a session the app archived is gone: only its tab or its terminal ends it.
        self.assertEqual(
            self.printed[-1],
            "Nothing was purged: 1 session still runs. Close its tab, or end it in its terminal, and run this again.",
        )
        self.assertFalse(any("Archive" in line for line in self.printed), self.printed)

    def test_purge_refusal_speaks_of_several_sessions_in_the_plural(self):
        self.mac.config_file.write_text("")
        self.session(self.blog, A, "used", 601)
        self.session(self.blog, B, "used", 602)

        self.assertEqual(self.uninstall(servers=True, purge=True), 1)

        self.assertEqual(
            self.printed[-1],
            "Nothing was purged: 2 sessions still run. Close their tabs, or end them in their terminals,"
            " and run this again.",
        )

    def test_purge_refuses_while_a_session_of_a_project_no_longer_configured_still_runs(self):
        gone = standins.project("gone", str(self.root / "gone"))
        self.session(gone, A, "used", 603)

        self.assertEqual(self.uninstall(servers=True, purge=True), 1)

        self.assertIn(A, self.sessions(gone))
        self.assertTrue(self.printed[-1].startswith("Nothing was purged: 1 session still runs."))

    def test_purge_refuses_while_a_session_the_server_started_still_runs(self):
        self.mac.store(self.shop, view_tabs.STATE).save({"cse_01AAA": {"opened": True, "attempts": 1}})
        self.mac.ps = "701 claude --print --sdk-url wss://example.invalid/x --session-id cse_01AAA\n"

        self.assertEqual(self.uninstall(servers=True, purge=True), 1)

        self.assertTrue(self.mac.store(self.shop, view_tabs.STATE).path.exists())

    def test_purge_refuses_while_a_server_is_left_loaded(self):
        self.mac.config_file.write_text("")

        self.assertEqual(self.uninstall(purge=True), 1)

        self.assertTrue(self.mac.config_file.exists())
        self.assertEqual(
            self.printed[-1], "Nothing was purged: a server that is left running still reads the configuration and the state."
        )

    def test_does_nothing_when_launchd_cannot_say_what_is_loaded(self):
        self.session(self.shop, A, "free", 601)
        self.mac.launchctl.lists = False

        self.assertEqual(self.uninstall(servers=True, purge=True), 1)

        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(self.mac.terminated, [])
        self.assertEqual(len(self.files()), 2)

    def test_ends_the_free_session_of_a_project_the_configuration_no_longer_has(self):
        gone = standins.project("gone", str(self.root / "gone"))
        self.session(gone, A, "free", 603)
        self.ends_when_asked()

        self.assertEqual(self.uninstall(servers=True), 0)

        self.assertEqual(self.mac.terminated, [603])
        self.assertEqual(self.sessions(gone), {}, "let go as a feature turned off lets go of it")
        self.assertIn("removed the worktree porchlight-gone-aaaaaaaa", self.mac.log_text(gone))
        self.assertEqual(self.printed[2:], ["gone: ended the free session it held", "No session is running.", self.printed[-1]])

    def test_leaves_the_session_in_use_of_a_project_the_configuration_no_longer_has(self):
        gone = standins.project("gone", str(self.root / "gone"))
        self.session(gone, A, "free", 603)
        self.session(gone, B, "used", 604)
        self.ends_when_asked()

        self.assertEqual(self.uninstall(servers=True), 0)

        self.assertEqual(self.mac.terminated, [603], "only the session nobody used")
        self.assertEqual(self.sessions(gone)[B]["state"], "used")
        self.assertIn("1 session in use keeps running.", self.printed)

    def test_never_says_that_no_session_runs_while_a_free_one_did_not_end(self):
        self.session(self.shop, A, "free", 601)  # asked to end, it keeps running

        self.assertEqual(self.uninstall(servers=True), 1)

        self.assertNotIn("No session is running.", self.printed)
        self.assertIn("1 free session could not be ended and still runs.", self.printed)

    def test_counts_the_free_sessions_that_did_not_end_apart_from_those_in_use(self):
        gone = standins.project("gone", str(self.root / "gone"))
        self.session(gone, A, "free", 603)
        self.session(self.blog, B, "used", 602)
        (self.root / "gone").rename(self.root / "moved")  # nothing can be tidied in a folder that is gone

        self.assertEqual(self.uninstall(servers=True), 1)

        self.assertEqual(self.mac.terminated, [])
        self.assertEqual(
            self.printed[2:4],
            ["1 session in use keeps running.", "1 free session could not be ended and still runs."],
        )

    def test_works_without_a_configuration_from_the_labels_and_the_state_folders(self):
        self.session(self.shop, A, "free", 601)
        self.ends_when_asked()
        self.printed.clear()

        code = agents.uninstall(config.Config(), self.mac, self.printed.append, servers=True, purge=True, readable=False)

        self.assertEqual(code, 0)
        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL), ("unload", SHOP)])
        self.assertEqual(self.mac.terminated, [601])
        self.assertFalse((self.root / "state").exists())


    MARKER = ".porchlight"  # what says that the tool made a folder: only there does a purge delete

    def test_the_folders_the_tool_makes_carry_its_marker(self):
        self.mac.store(self.blog, ready_sessions.STATE).save({})

        self.assertTrue((self.root / "state" / self.MARKER).is_file())
        self.assertTrue((self.root / "logs" / self.MARKER).is_file(), "made when the first agent was loaded")

    def test_a_folder_that_was_already_there_is_never_marked(self):
        elsewhere = standins.StandInMac(self.root / "elsewhere")
        (self.root / "elsewhere" / "state").mkdir(parents=True)
        (self.root / "elsewhere" / "logs").mkdir()

        elsewhere.store(self.blog, ready_sessions.STATE).save({})
        elsewhere.log(self.blog, "something happened")

        self.assertFalse((self.root / "elsewhere" / "state" / self.MARKER).exists())
        self.assertFalse((self.root / "elsewhere" / "logs" / self.MARKER).exists())

    def test_purge_deletes_nothing_in_a_folder_the_tool_did_not_make_and_says_so(self):
        home, shared = self.root / "home", self.root / "shared"
        theirs = [
            home / "projects" / "webshop" / "settings.json",
            home / "projects" / "webshop" / "settings.json.next",
            home / "projects" / "webshop" / "ready-sessions.json",
            home / "projects" / "webshop" / "view-tabs.lock",
            home / "service.lock",
            shared / "webshop.log",
            shared / "agent.service.log",
        ]
        for path in theirs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("the person's own")
        self.mac.environ["PORCHLIGHT_STATE_DIR"] = str(home)
        self.mac.environ["PORCHLIGHT_LOG_DIR"] = str(shared)
        self.mac.launchctl.loaded.clear()

        self.assertEqual(self.uninstall(servers=True, purge=True), 1)

        self.assertEqual([path for path in theirs if not path.exists()], [])
        self.assertFalse((home / self.MARKER).exists())
        self.assertIn("%s was left as it is: porchlight did not make that folder." % home, self.printed)
        self.assertIn("%s was left as it is: porchlight did not make that folder." % shared, self.printed)
        self.assertEqual(self.printed[-1], "Removed the configuration.")

    def test_purge_keeps_the_marker_of_a_folder_that_still_holds_something(self):
        self.mac.store(self.blog, ready_sessions.STATE).save({})
        (self.root / "state" / "notes.txt").write_text("the person's own")

        self.assertEqual(self.purged(), 0)

        self.assertEqual(sorted(path.name for path in (self.root / "state").iterdir()), [self.MARKER, "notes.txt"])
        self.assertFalse((self.root / "logs").exists())

    def test_purge_removes_the_logs_of_projects_no_longer_linked(self):
        """A project deinit unlinked is neither configured nor in the state: its logs, and its
        server's, go all the same, and the folder with them."""
        gone = standins.project("gone")
        logs = self.root / "logs"
        (logs).mkdir(exist_ok=True)
        names.log_file(gone, self.mac.environ).write_text("something happened\n")
        names.server_log(gone, self.mac.environ).write_text("started\n")

        self.assertEqual(self.purged(), 0)

        self.assertFalse(logs.exists(), "the logs and the folder's marker are gone")
        self.assertEqual(self.printed[-1], "Removed the configuration, the state and the logs.")

    def test_purge_names_what_it_leaves_in_the_log_folder(self):
        logs = self.root / "logs"
        (logs / "old.log").mkdir(parents=True)  # a folder, not a log, whatever its name
        (logs / "notes.txt").write_text("the person's own")

        self.assertEqual(self.purged(), 0)

        self.assertEqual(sorted(path.name for path in logs.iterdir()), [self.MARKER, "notes.txt", "old.log"])
        self.assertEqual(
            self.printed[-2:],
            [
                "%s was kept: it holds notes.txt and old.log, which porchlight did not make." % logs,
                "Removed the configuration, the state and the logs.",
            ],
        )

    def test_purge_says_which_logs_it_could_not_remove_and_claims_no_logs(self):
        logs = self.root / "logs"
        self.addCleanup(os.chmod, logs, 0o755)

        self.assertEqual(self.purged(before=lambda: os.chmod(logs, 0o555)), 1, "not everything asked for was removed")

        stuck = ["agent.server.shop.log", "agent.service.log", "blog.log"]
        self.assertEqual(sorted(path.name for path in logs.iterdir()), [self.MARKER] + stuck)
        self.assertEqual(
            self.printed[-2:],
            [
                "agent.server.shop.log, agent.service.log and blog.log could not be removed from %s." % logs,
                "Removed the configuration and the state.",
            ],
        )


class OneServerForAFolder(OnTheMac):
    """A folder is served by one server: a project that changed its name gets no second one
    beside the server left running in its folder."""

    def setUp(self):
        super().setUp()
        self.before = self.configuration(shop=("server",))
        self.after = config.Config(None, (dataclasses.replace(self.before.projects[0], name="store"),))
        self.apply(self.before)
        self.mac.launchctl.calls.clear()

    STORE = standins.LABEL + ".server.store"

    def test_a_renamed_project_gets_no_server_beside_the_one_left_running_in_its_folder(self):
        self.assertEqual(self.apply(self.after), 1)

        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertEqual(self.mac.launchctl.loaded, {SERVICE_LABEL, SHOP})
        self.assertEqual(self.files(), [SERVICE_LABEL + ".plist", SHOP + ".plist"], "no file is written for it")
        self.assertEqual(
            self.printed,
            [
                SERVICE_LABEL + ": already loaded, nothing changed",
                "%s: not loaded: %s is left running in the same folder, %s; porchlight apply --servers replaces it"
                % (self.STORE, SHOP, names.repository(self.before.projects[0])),
                SHOP + ": left running, though the configuration no longer has it",
                "A running server is restarted or removed only when asked, because the app cannot start its "
                "sessions again. To include them (shop): porchlight apply --servers",
                CHECK,
            ],
        )

    def test_with_servers_the_old_one_is_removed_first_and_then_the_new_one_loaded(self):
        self.assertEqual(self.apply(self.after, servers=True), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SHOP), ("load", self.STORE)])
        self.assertEqual(self.files(), [SERVICE_LABEL + ".plist", self.STORE + ".plist"])
        self.assertEqual(self.printed[1:3], [SHOP + ": unloaded and removed", self.STORE + ": loaded"])

    def test_the_new_one_is_not_loaded_when_the_old_one_does_not_unload(self):
        self.mac.launchctl.stuck.add(SHOP)

        self.assertEqual(self.apply(self.after, servers=True), 1)

        self.assertNotIn(("load", self.STORE), self.mac.launchctl.did())
        self.assertNotIn(self.STORE + ".plist", self.files())

    def test_a_changed_server_is_not_restarted_into_the_folder_of_one_that_did_not_unload(self):
        stale = dict(launchd.read(launchd.file(self.folder, SHOP)), Label=self.STORE, ThrottleInterval=1)
        words = stale["ProgramArguments"]
        stale["ProgramArguments"] = words[: words.index("shop")] + ["store"] + words[words.index("shop") + 1 :]
        launchd.write(launchd.file(self.folder, self.STORE), stale)
        self.mac.launchctl.loaded.add(self.STORE)
        self.mac.launchctl.stuck.add(SHOP)

        self.assertEqual(self.apply(self.after, servers=True), 1)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SHOP)], "the store server is not touched")
        self.assertIn(
            "%s: not restarted: %s still runs in the same folder, %s"
            % (self.STORE, SHOP, names.repository(self.before.projects[0])),
            self.printed,
        )

    def test_a_server_in_another_folder_is_loaded_beside_one_left_running(self):
        both = config.Config(None, self.after.projects + self.configuration(blog=("server",)).projects)

        self.apply(both)

        self.assertEqual(self.mac.launchctl.did(), [("load", BLOG)])

    def test_no_server_is_loaded_beside_one_left_running_whose_folder_cannot_be_read(self):
        launchd.file(self.folder, SHOP).unlink()

        self.assertEqual(self.apply(self.after), 1)

        self.assertEqual(self.mac.launchctl.did(), [])
        self.assertIn(
            "%s: not loaded: %s is left running and its folder is not known; porchlight apply --servers replaces it"
            % (self.STORE, SHOP),
            self.printed,
        )


class WhatLaunchdSays(OnTheMac):
    """An agent is loaded when the list has it or launchd knows it by its label, and gone
    only when launchd says it does not know it."""

    def setUp(self):
        super().setUp()
        self.both = self.configuration(shop=("server",), blog=("server",))
        self.apply(self.both)
        self.mac.launchctl.calls.clear()

    def blind(self):
        """A list that answers and leaves out the agents of this install."""
        self.mac.launchctl.unlisted = {SERVICE_LABEL, SHOP, BLOG}

    def test_a_running_server_the_list_leaves_out_keeps_its_file(self):
        self.blind()
        written = self.definition(SHOP)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"

        self.assertEqual(self.apply(self.both), 0)

        self.assertEqual(self.definition(SHOP), written)
        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL), ("load", SERVICE_LABEL)])
        self.assertEqual(self.printed[1], SHOP + ": left running as it is, though its definition changed")

    def test_without_a_project_the_servers_the_list_leaves_out_keep_their_files(self):
        self.blind()

        self.assertEqual(self.apply(config.Config()), 0)

        self.assertEqual(self.files(), [BLOG + ".plist", SHOP + ".plist"])
        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL)])

    def test_uninstall_purges_nothing_while_a_server_the_list_leaves_out_runs(self):
        self.blind()
        self.mac.config_file.write_text("")

        self.assertEqual(agents.uninstall(self.both, self.mac, self.printed.append, purge=True), 1)

        self.assertEqual(self.files(), [BLOG + ".plist", SHOP + ".plist"])
        self.assertEqual(self.mac.launchctl.loaded, {SHOP, BLOG})
        self.assertTrue(self.mac.config_file.exists())

    def test_every_own_label_that_has_a_file_is_asked_about_by_itself(self):
        self.apply(self.both)

        asked = [words[2] for words in self.mac.launchctl.calls if words[1] == "print"]
        self.assertEqual(sorted(asked), sorted("gui/501/" + label for label in (SERVICE_LABEL, SHOP, BLOG)))

    def test_nothing_changes_when_launchd_cannot_say_whether_an_agent_is_loaded(self):
        self.blind()
        self.mac.launchctl.untold[SHOP] = 1
        before = self.everything()

        for command in (
            lambda: self.apply(config.Config(), servers=True),
            lambda: agents.start(self.mac, self.printed.append),
            lambda: agents.stop(self.mac, self.printed.append, servers=True),
            lambda: agents.uninstall(self.both, self.mac, self.printed.append, servers=True, purge=True),
        ):
            self.printed.clear()
            self.assertEqual(command(), 1)
            self.assertEqual(self.everything(), before)
            self.assertEqual(
                self.printed, ["launchd could not say whether %s is loaded. Nothing was changed." % SHOP]
            )

    def unloads_without_saying_so(self):
        """Once asked to unload an agent, launchd no longer says whether it is loaded."""
        self.mac.launchctl.on_unload = lambda label: self.mac.launchctl.untold.update({label: 1})

    NOT_TOLD = ": launchd could not say whether it was unloaded, so it was left as it is"

    def test_an_agent_is_gone_only_when_launchd_says_it_does_not_know_it(self):
        self.unloads_without_saying_so()

        self.assertEqual(self.apply(config.Config(), servers=True), 1)

        self.assertEqual(len(self.files()), 3, "no file is removed of an agent that may still run")
        self.assertEqual(self.printed[:3], [label + self.NOT_TOLD for label in (SERVICE_LABEL, BLOG, SHOP)])

    def test_a_changed_agent_is_not_loaded_again_before_launchd_says_it_is_gone(self):
        self.unloads_without_saying_so()
        written = self.definition(SERVICE_LABEL)
        self.mac.found["tmux"] = "/elsewhere/bin/tmux"

        self.assertEqual(self.apply(self.both), 1)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL)])
        self.assertEqual(self.definition(SERVICE_LABEL), written)

    def test_stop_says_which_agent_it_could_not_tell_unloaded(self):
        self.unloads_without_saying_so()
        self.printed.clear()

        self.assertEqual(agents.stop(self.mac, self.printed.append), 1)

        self.assertEqual(self.printed[0], SERVICE_LABEL + self.NOT_TOLD)

    def test_uninstall_removes_nothing_of_an_agent_it_could_not_tell_unloaded(self):
        self.unloads_without_saying_so()

        self.assertEqual(agents.uninstall(self.both, self.mac, self.printed.append, servers=True, purge=True), 1)

        self.assertEqual(len(self.files()), 3)
        self.assertEqual(self.printed[-1], "Nothing else was done: run this again once every agent is unloaded.")


class WhoMayAsk(OnTheMac):
    def setUp(self):
        super().setUp()
        self.both = self.configuration(shop=("server",), blog=("server",))
        self.apply(self.both)
        self.mac.launchctl.calls.clear()
        self.commands = (
            lambda: self.apply(config.Config(), servers=True),
            lambda: agents.start(self.mac, self.printed.append),
            lambda: agents.stop(self.mac, self.printed.append, servers=True),
            lambda: agents.uninstall(self.both, self.mac, self.printed.append, servers=True, purge=True),
        )

    def test_root_is_refused_by_every_command_that_changes_launchd_or_deletes_files(self):
        self.mac.uid = 0
        before = self.everything()

        for command in self.commands:
            self.printed.clear()
            self.assertEqual(command(), 1)
            self.assertEqual(self.mac.launchctl.calls, [], "launchd was not even asked")
            self.assertEqual(self.everything(), before)
            self.assertEqual(
                self.printed,
                ["Run this as the person who is logged in, without sudo: root has other agents. Nothing was changed."],
            )

    def test_a_label_that_is_no_reverse_domain_name_is_refused_before_anything_changes(self):
        before = self.everything()

        for label in ("../../escape", "a/b", " ", "porchlight", "com.example.", ".com.example", "com.example\n"):
            self.mac.environ["PORCHLIGHT_LABEL"] = label
            for command in self.commands:
                self.printed.clear()
                self.assertEqual(command(), 2, label)
                self.assertEqual(self.mac.launchctl.calls, [])
                self.assertEqual(self.everything(), before)
                self.assertEqual(len(self.printed), 1)
                self.assertIn("PORCHLIGHT_LABEL", self.printed[0])


class OwnFiles(OnTheMac):
    """A file is the tool's when it is named after one of its labels and runs the tool."""

    FOREIGN = {"ProgramArguments": ["/usr/local/bin/another", "run"]}

    def plant(self, *labels):
        for label in labels:
            launchd.write(launchd.file(self.folder, label), dict(self.FOREIGN, Label=label))

    def test_a_file_under_one_of_its_labels_that_does_not_run_the_tool_is_never_touched(self):
        self.plant(SERVICE_LABEL, SHOP)
        self.mac.launchctl.loaded.update({SERVICE_LABEL, SHOP})
        before = self.everything()

        self.assertEqual(self.apply(config.Config(), servers=True), 0)
        agents.start(self.mac, self.printed.append)
        agents.stop(self.mac, self.printed.append, servers=True)
        agents.uninstall(config.Config(), self.mac, self.printed.append, servers=True, purge=True)

        self.assertEqual(self.everything(), before)
        self.assertEqual(self.definition(SHOP), dict(self.FOREIGN, Label=SHOP))

    def test_only_the_arguments_the_tool_itself_writes_make_a_file_its_own(self):
        shapes = {
            ("/tools/porchlight", "run"): [SERVICE_LABEL],
            ("/some/python3", "-m", "porchlight", "run"): [SERVICE_LABEL],
            ("/tools/porchlight", "server", "shop"): [SHOP],
            ("/tools/porchlight", "server", "shop", "--permission-mode", "plan"): [SHOP],
            ("/tools/porchlight", "server", "blog"): [],  # another project's
            ("/tools/porchlight", "server", "blog", "--permission-mode", "plan"): [],
            ("/tools/porchlight", "server", "shop", "--other", "plan"): [],
            ("/tools/porchlight", "server", "shop", "--permission-mode"): [],
            ("/tools/porchlight", "run", "--permission-mode", "plan"): [],
            ("/tools/porchlight", "run", "--once"): [],
            ("/tools/another", "run"): [],
            ("run",): [],
            (): [],
        }
        for words, own in shapes.items():
            for label in (SERVICE_LABEL, SHOP):
                launchd.write(launchd.file(self.folder, label), {"Label": label, "ProgramArguments": list(words)})

            self.assertEqual([agent.label for agent in agents.installed(self.mac)], own, words)

    def test_an_agent_that_is_loaded_and_has_no_file_is_known_by_its_name(self):
        self.mac.launchctl.loaded.update({SERVICE_LABEL, SHOP})

        self.assertEqual(agents.uninstall(config.Config(), self.mac, self.printed.append, servers=True), 0)

        self.assertEqual(self.mac.launchctl.did(), [("unload", SERVICE_LABEL), ("unload", SHOP)])

    def test_apply_writes_over_no_file_that_is_not_its_own_and_says_so(self):
        self.plant(SHOP)

        self.assertEqual(self.apply(self.configuration(shop=("server",))), 1)

        self.assertEqual(self.definition(SHOP), dict(self.FOREIGN, Label=SHOP))
        self.assertEqual(self.mac.launchctl.did(), [("load", SERVICE_LABEL)])
        self.assertEqual(
            self.printed[1],
            "%s: left as it is: the file %s was not written by porchlight. Move it away, and run this again."
            % (SHOP, launchd.file(self.folder, SHOP)),
        )


class Written(OnTheMac):
    def test_relative_folders_reach_the_agents_as_absolute_paths(self):
        self.mac.environ.update(
            PORCHLIGHT_STATE_DIR="relative/state", PORCHLIGHT_LOG_DIR="relative/logs", PORCHLIGHT_CONFIG="relative.toml"
        )
        self.mac.config_file = None

        for agent in agents.wanted(self.configuration(shop=("server",)), self.mac):
            told = agent.definition
            self.assertTrue(os.path.isabs(told["StandardOutPath"]), told["StandardOutPath"])
            self.assertTrue(os.path.isabs(told["StandardErrorPath"]))
            self.assertEqual(os.path.dirname(told["StandardOutPath"]), os.path.abspath("relative/logs"))
            environment = told["EnvironmentVariables"]
            self.assertEqual(environment["PORCHLIGHT_STATE_DIR"], os.path.abspath("relative/state"))
            self.assertEqual(environment["PORCHLIGHT_LOG_DIR"], os.path.abspath("relative/logs"))
            self.assertEqual(environment["PORCHLIGHT_CONFIG"], os.path.abspath("relative.toml"))

    def test_a_value_a_property_list_cannot_hold_is_said_for_its_agent_and_not_raised(self):
        for odd in ("a\x1bb", "caf\udce9"):
            self.mac.environ["PORCHLIGHT_TMUX_SERVER"] = odd

            self.assertEqual(self.apply(self.configuration(shop=("server",))), 1)

            self.assertEqual(self.files(), [])
            self.assertEqual(self.mac.launchctl.did(), [])
            self.assertEqual(len(self.printed), 3)
            self.assertTrue(self.printed[0].startswith(SERVICE_LABEL + ": could not be written: "), self.printed[0])
            self.assertTrue(self.printed[1].startswith(SHOP + ": could not be written: "), self.printed[1])


if __name__ == "__main__":
    unittest.main()
