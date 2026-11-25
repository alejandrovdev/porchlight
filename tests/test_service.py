"""Tests of the resident service: its rounds, what it waits for, how it stops, that there is
only one, and the child that keeps the Mac awake. The clock, the waiting and the pass are
stand-ins, so no test sleeps and nothing is started."""

import signal
import tempfile
import unittest
from pathlib import Path

from porchlight import config, names, passes, service
from porchlight.atoms import state, transcripts, watch
from porchlight.features import keep_awake, ready_sessions
from tests import standins

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


QUIET = (False, None, None)  # a wait in which nothing happens


def change(meanwhile=None):
    """One change, a second into the wait, and then the moment a burst is given, quiet."""
    return [(True, 1, meanwhile), QUIET]


class Waits:
    """Stands in for the watcher: each wait takes the next answer of a script.

    An answer is (whether something changed, the seconds it took or None for all of them,
    what happens meanwhile). Once the script ends, the service is asked to stop.
    """

    def __init__(self, test, script):
        self.test = test
        self.script = list(script)
        self.asked = []  # the paths of each `watch`
        self.waits = []  # the seconds of each `wait`

    def watch(self, paths):
        self.asked.append([str(path) for path in paths])

    def wait(self, seconds):
        self.waits.append(seconds)
        if not self.script:
            self.test.stop = True
            return False
        changed, took, meanwhile = self.script.pop(0)
        self.test.now += seconds if took is None else took
        if meanwhile:
            meanwhile()
        return changed


class Service(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.file = self.root / "config.toml"
        self.mac = standins.StandInMac(self.root)
        self.now = 500.0
        self.stop = False
        self.said = []
        self.passes = []  # the projects of each pass
        self.macs = []  # the configuration of each Mac asked for

    def configure(self, *projects, features=("server",), keep_awake=None):
        configured = []
        for name in projects:
            (self.root / name).mkdir(exist_ok=True)
            configured.append(config.Project(name, str(self.root / name), "plan", config.ordered(features), None, name))
        config.save(config.Config(None, tuple(configured), keep_awake=keep_awake), self.file)

    def a_pass(self, configuration, mac):
        self.passes.append([project.name for project in configuration.projects])

    def mac_for(self, configuration):
        self.macs.append(configuration)
        return self.mac

    def serve(self, *script, **options):
        steps = []
        for step in script:
            steps += step if isinstance(step, list) else [step]
        self.waits = Waits(self, steps)
        options.setdefault("a_pass", self.a_pass)
        return service.serve(
            self.file,
            self.mac_for,
            self.said.append,
            watcher=self.waits,
            clock=lambda: self.now,
            stopped=lambda: self.stop,
            **options,
        )


class Rounds(Service):
    def test_each_round_reads_the_configuration_again(self):
        self.configure("shop")

        code = self.serve(change(lambda: self.configure("shop", "blog")), QUIET)

        self.assertEqual(code, 0)
        self.assertEqual(self.passes[:2], [["shop"], ["shop", "blog"]])
        self.assertEqual(self.said, [])

    def test_waits_for_a_change_or_for_the_slow_interval_whichever_comes_first(self):
        self.configure("shop")

        self.serve(QUIET, QUIET)

        self.assertEqual(self.waits.waits, [20.0, 20.0, 20.0])
        self.assertEqual(len(self.passes), 3, "one pass before each wait")
        self.assertEqual(self.now, 540.0)

    def test_watches_the_configuration_file_and_what_the_projects_sessions_write(self):
        self.configure("shop", features=("ready-session",))
        store = self.mac.store(config.load(self.file).project("shop"), ready_sessions.STATE)
        worktree = str(self.root / "shop" / ".claude" / "worktrees" / "porchlight-shop-aaaaaaaa")
        store.save({"sessions": {A: {"state": "free", "worktree": worktree}}})

        self.serve()

        folder = transcripts.folder(self.mac.transcripts, worktree)
        self.assertEqual(
            self.waits.asked,
            [[str(self.file), str(self.mac.transcripts), str(folder / (A + ".jsonl")), str(folder)]],
        )

    def test_watches_the_folder_of_a_configuration_file_that_is_not_there_yet(self):
        self.serve()

        self.assertEqual(self.waits.asked, [[str(self.file), str(self.root), str(self.mac.transcripts)]])
        self.assertEqual(self.passes, [[]], "no file is a configuration without projects")

    def test_a_burst_of_changes_makes_one_pass(self):
        self.configure("shop")

        self.serve((True, 5, None), (True, 0.5, None), (True, 0.5, None), (True, 0.5, None), QUIET)

        self.assertEqual(len(self.passes), 2, "one before the burst, one for all of it")
        self.assertEqual(self.waits.waits[:5], [20.0, 2.0, 1.5, 1.0, 0.5])
        self.assertEqual(self.waits.waits[5], 20.0, "then the slow interval again")

    def test_the_process_list_is_read_by_the_passes_alone(self):
        self.configure("shop", features=("ready-session", "keep-awake"))
        reads = []
        self.mac.ps = lambda: reads.append(1) or ""

        self.serve(QUIET, change(), QUIET)

        self.assertEqual(len(self.passes), 4)
        self.assertEqual(reads, [], "neither the waiting nor what is watched reads it")

    def test_once_makes_one_pass_and_never_waits(self):
        self.configure("shop")

        self.assertEqual(self.serve(once=True), 0)

        self.assertEqual(self.passes, [["shop"]])
        self.assertEqual(self.waits.waits, [])

    def test_asked_to_stop_during_a_pass_it_ends_after_that_pass(self):
        self.configure("shop")

        def a_pass(configuration, mac):
            self.passes.append("whole")
            self.stop = True

        self.assertEqual(self.serve(a_pass=a_pass), 0)

        self.assertEqual(self.passes, ["whole"])
        self.assertEqual(self.waits.waits, [])

    def test_asked_to_stop_during_a_wait_it_makes_no_other_pass(self):
        self.configure("shop")

        self.assertEqual(self.serve((False, 3, lambda: setattr(self, "stop", True))), 0)

        self.assertEqual(len(self.passes), 1)

    def test_asked_to_stop_during_a_burst_it_does_not_wait_the_burst_out(self):
        self.configure("shop")

        self.serve((True, 5, None), (True, 0.5, lambda: setattr(self, "stop", True)))

        self.assertEqual(self.waits.waits, [20.0, 2.0])
        self.assertEqual(len(self.passes), 1)

    def test_a_pass_that_raises_is_said_and_the_next_round_still_comes(self):
        self.configure("shop")
        attempts = []

        def a_pass(configuration, mac):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("broken")

        self.assertEqual(self.serve(QUIET, a_pass=a_pass), 0)

        self.assertEqual(len(attempts), 2)
        self.assertEqual(self.said, ["The pass failed: RuntimeError('broken')"])

    def test_the_mac_is_asked_for_again_only_when_the_configuration_changed(self):
        self.configure("shop")

        self.serve(QUIET, change(lambda: self.configure("shop", "blog")), QUIET)

        self.assertEqual([len(configuration.projects) for configuration in self.macs], [1, 2])


class BrokenConfiguration(Service):
    def test_a_file_that_no_longer_parses_is_said_once_and_the_last_good_one_keeps_being_served(self):
        self.configure("shop")

        def break_it():
            self.file.write_text('[projects.shop]\npermission_mode = "plan"\npreset = "minimal"\n')

        self.serve(change(break_it), QUIET, QUIET)

        self.assertEqual(self.passes, [["shop"]] * 4)
        self.assertEqual(
            self.said,
            [
                "The configuration %s has problems:" % self.file,
                "projects.shop.path: missing",
                "The last configuration that could be read keeps being served.",
            ],
        )

    def test_once_it_parses_again_it_is_served_and_a_later_problem_is_said_again(self):
        self.configure("shop")

        def break_it():
            self.file.write_text("terminal = \n")

        self.serve(
            change(break_it),
            change(lambda: self.configure("shop", "blog")),
            change(break_it),
            QUIET,
        )

        self.assertEqual(self.passes, [["shop"], ["shop"], ["shop", "blog"], ["shop", "blog"], ["shop", "blog"]])
        self.assertEqual(len([line for line in self.said if line.startswith("The configuration")]), 2)

    def test_a_file_broken_from_the_start_serves_no_project_until_it_parses(self):
        self.file.write_text("terminal = \n")

        self.serve(change(lambda: self.configure("shop")), QUIET)

        self.assertEqual(self.passes, [[], ["shop"], ["shop"]])
        self.assertEqual(self.said[0], "The configuration %s has problems:" % self.file)

    def test_a_file_broken_from_the_start_is_not_said_to_keep_an_earlier_one_served(self):
        self.file.write_text("terminal = 7\n")

        self.serve(QUIET)

        self.assertEqual(
            self.said,
            [
                "The configuration %s has problems:" % self.file,
                "terminal: must be text",
                "Nothing is served until the file is fixed.",
            ],
        )

    def test_a_file_that_breaks_after_one_was_read_keeps_that_one_served_even_when_it_had_no_project(self):
        self.file.write_text("")

        self.serve(change(lambda: self.file.write_text("terminal = 7\n")), QUIET)

        self.assertEqual(self.said[-1], "The last configuration that could be read keeps being served.")

    def test_once_refuses_a_file_that_does_not_parse(self):
        self.file.write_text("terminal = \n")

        self.assertEqual(self.serve(once=True), 1)

        self.assertEqual(self.passes, [])
        self.assertEqual(self.said[0], "The configuration %s has problems:" % self.file)

    def test_reads_a_file_into_a_configuration_or_into_what_is_wrong_with_it(self):
        self.configure("shop")
        self.assertEqual(service.read(self.file), (config.load(self.file), []))

        self.file.write_text('terminal = "kitty"\n')
        self.assertEqual(
            service.read(self.file),
            (None, ["The configuration %s has problems:" % self.file, 'terminal: unknown terminal "kitty"; one of: warp, apple-terminal']),
        )

        self.file.unlink()
        self.file.mkdir()
        found, lines = service.read(self.file)
        self.assertIsNone(found)
        self.assertIn("The configuration %s cannot be read" % self.file, lines[0])


class KeepAwake(Service):
    AWAKE = ("server", "keep-awake")

    def children(self):
        return [(child.words, child.ended) for child in self.mac.spawned]

    def test_keeps_one_child_that_keeps_the_mac_awake_on_ac_power_while_a_project_has_the_feature(self):
        self.configure("shop", "blog", features=self.AWAKE)
        seen = []

        self.serve(QUIET, (False, None, lambda: seen.extend(self.children())))

        self.assertEqual(seen, [(["/usr/bin/caffeinate", "-i", "-s", "-w", "4242"], False)], "one, for the service's own pid")

    def test_starts_none_while_no_project_has_the_feature(self):
        self.configure("shop")

        self.serve(QUIET)

        self.assertEqual(self.mac.spawned, [])

    def test_ends_it_when_no_project_has_the_feature_any_more(self):
        self.configure("shop", features=self.AWAKE)
        seen = []

        self.serve(change(lambda: self.configure("shop")), (False, None, lambda: seen.extend(self.children())))

        self.assertEqual(seen, [(["/usr/bin/caffeinate", "-i", "-s", "-w", "4242"], True)])

    def test_starts_it_again_when_it_ended_by_itself(self):
        self.configure("shop", features=self.AWAKE)

        self.serve((False, None, lambda: setattr(self.mac.spawned[0], "exited", 1)), QUIET)

        self.assertEqual(len(self.mac.spawned), 2)

    def test_ends_it_when_the_service_stops(self):
        self.configure("shop", features=self.AWAKE)

        self.serve(QUIET)

        self.assertEqual(self.children(), [(["/usr/bin/caffeinate", "-i", "-s", "-w", "4242"], True)])

    def test_plugged_in_keeps_it_awake_on_ac_power_only(self):
        self.configure("shop", features=self.AWAKE, keep_awake="plugged-in")

        self.serve(QUIET)

        self.assertEqual(self.children(), [(["/usr/bin/caffeinate", "-s", "-w", "4242"], True)])

    def test_a_new_keep_awake_setting_replaces_the_child(self):
        self.configure("shop", features=self.AWAKE)

        self.serve(change(lambda: self.configure("shop", features=self.AWAKE, keep_awake="plugged-in")))

        self.assertEqual(
            self.children(),
            [
                (["/usr/bin/caffeinate", "-i", "-s", "-w", "4242"], True),
                (["/usr/bin/caffeinate", "-s", "-w", "4242"], True),
            ],
        )

    def test_one_pass_alone_starts_none(self):
        self.configure("shop", features=self.AWAKE)

        self.serve(once=True)

        self.assertEqual(self.mac.spawned, [])

    def test_says_once_that_it_could_not_be_started_and_the_passes_go_on(self):
        self.configure("shop", features=self.AWAKE)
        self.mac.spawn_error = OSError("no caffeinate")

        self.serve(QUIET, QUIET)

        self.assertEqual(len(self.passes), 3)
        self.assertEqual(self.said, ["Could not keep the Mac awake: OSError('no caffeinate')"])

    def test_the_configuration_wants_it_when_any_project_has_the_feature(self):
        with_it = standins.project("shop", features=("keep-awake",))
        without = standins.project("blog", features=("server",))

        self.assertTrue(keep_awake.wanted(config.Config(None, (without, with_it))))
        self.assertFalse(keep_awake.wanted(config.Config(None, (without,))))
        self.assertFalse(keep_awake.wanted(config.Config()))


class Watched(unittest.TestCase):
    def test_a_pass_is_called_for_by_the_transcripts_of_the_sessions_that_run_or_wait(self):
        with tempfile.TemporaryDirectory() as scratch:
            mac = standins.StandInMac(scratch)
            shop = standins.project("shop", scratch + "/shop")
            blog = standins.project("blog", scratch + "/blog")
            records = {
                A: {"state": "free", "worktree": "/srv/shop/free"},
                B: {"state": "used", "worktree": "/srv/shop/used"},
                C: {"state": "closed", "worktree": "/srv/shop/closed"},
            }
            mac.store(shop, ready_sessions.STATE).save({"sessions": records})

            found = passes.watched(config.Config(None, (shop, blog)), mac)

        free = transcripts.folder(mac.transcripts, "/srv/shop/free")
        used = transcripts.folder(mac.transcripts, "/srv/shop/used")
        self.assertEqual(found, [mac.transcripts, free / (A + ".jsonl"), free, used / (B + ".jsonl"), used])

    def test_a_project_whose_state_cannot_be_read_does_not_hide_the_others(self):
        with tempfile.TemporaryDirectory() as scratch:
            mac = standins.StandInMac(scratch)
            shop = standins.project("shop", scratch + "/shop")
            blog = standins.project("blog", scratch + "/blog")
            mac.store(shop, ready_sessions.STATE).save({"sessions": {A: "not a record"}})
            mac.store(blog, ready_sessions.STATE).save({"sessions": {B: {"state": "free", "worktree": "/srv/blog/b"}}})

            found = passes.watched(config.Config(None, (shop, blog)), mac)

        self.assertEqual(len(found), 3)


class OnlyOne(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.lock = self.root / "state" / "service.lock"
        self.said = []
        self.served = []

    def serve(self, path, mac_for, say, **options):
        self.served.append(options)
        return 0

    def start(self, **options):
        options.setdefault("serve", self.serve)
        return service.run(self.root / "config.toml", lambda configuration: None, self.said.append, self.lock, **options)

    def test_a_second_run_exits_one_saying_another_is_running(self):
        held = state.exclusive(self.lock)
        self.addCleanup(held.close)

        self.assertEqual(self.start(), 1)

        self.assertEqual(self.served, [])
        self.assertEqual(self.said, ["Another %s is already running. Only one runs at a time." % names.command("run")])

    def test_one_pass_alone_is_refused_too_while_the_service_runs(self):
        held = state.exclusive(self.lock)
        self.addCleanup(held.close)

        self.assertEqual(self.start(once=True), 1)

        self.assertEqual(self.served, [])

    def test_holds_the_lock_while_it_serves_and_lets_it_go_after(self):
        def serve(path, mac_for, say, **options):
            self.assertIsNone(state.exclusive(self.lock))
            return 0

        self.assertEqual(self.start(serve=serve), 0)

        free = state.exclusive(self.lock)
        self.assertIsNotNone(free)
        free.close()

    def test_passes_on_what_it_was_asked(self):
        self.assertEqual(self.start(once=True), 0)

        self.assertIs(self.served[0]["once"], True)
        self.assertIsInstance(self.served[0]["watcher"], watch.Watcher)

    def test_sigterm_and_sigint_ask_it_to_stop_and_end_the_wait_without_ending_the_process(self):
        for asked in (signal.SIGTERM, signal.SIGINT):
            seen = []

            def serve(path, mac_for, say, stopped, watcher, **options):
                seen.append(stopped())
                signal.raise_signal(asked)  # to this very process: the handler in place is the service's
                seen.append(watcher.wait(30))  # ends at once, though nothing watched changed
                seen.append(stopped())
                return 0

            self.assertEqual(self.start(serve=serve), 0)

            self.assertEqual(seen, [False, False, True], asked)

    def test_puts_back_what_the_signals_did_before(self):
        before = [signal.getsignal(asked) for asked in (signal.SIGTERM, signal.SIGINT)]

        self.start()

        self.assertEqual([signal.getsignal(asked) for asked in (signal.SIGTERM, signal.SIGINT)], before)


if __name__ == "__main__":
    unittest.main()
