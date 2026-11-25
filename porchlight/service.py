"""The resident service: what keeps the sessions of every project, for as long as it runs.

    run(path, mac_for, say, lock_file)   the service, one at a time, until it is asked to stop
    serve(path, mac_for, say)            its rounds
    read(path)                           a configuration file, or what is wrong with it

Each round reads the configuration again, makes one pass over its projects, and then waits
until something a pass depends on changes or a slow interval passes, whichever comes first.
What changes is told by the system (`atoms/watch`): the configuration file and what the
sessions write. The process list cannot be watched, which is why the interval stays. A burst
of changes makes one pass: after the first, the service lets a moment go by before it acts.

A configuration file that no longer parses is said once, and the last one that could be
read keeps being served until the file parses again.

Only one service runs at a time: it holds a lock file, and a second one says so and exits.
SIGTERM and SIGINT end it between two passes, never in the middle of one.
"""

import os
import signal
import time
from contextlib import contextmanager
from pathlib import Path

from . import config, names, passes
from .atoms import state, watch
from .features import keep_awake

INTERVAL = 20.0  # the seconds between two passes when nothing is told
SETTLE = 2.0  # the seconds a burst of changes is given to end
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)


def read(path):
    """The configuration in a file: (it, no line), or (None, the lines that say what is
    wrong with the file)."""
    try:
        return config.load(path), []
    except config.ConfigError as error:
        lines = ["The configuration %s has problems:" % path]
        return None, lines + [("%s: %s" % (key, message)) if key else message for key, message in error.problems]
    except (OSError, UnicodeDecodeError) as error:
        return None, ["The configuration %s cannot be read: %s" % (path, error)]


def never():
    return False


def serve(
    path,
    mac_for,
    say,
    a_pass=passes.run,
    watcher=None,
    clock=time.monotonic,
    stopped=never,
    once=False,
    interval=INTERVAL,
    settle=SETTLE,
):
    """Round after round until `stopped()`; with `once`, one pass. The exit code.

    `mac_for(configuration)` gives the Mac of a configuration, `say` takes a line for the
    service's log, `a_pass(configuration, mac)` is one pass, `watcher` waits for changes and
    `clock` counts seconds.
    """
    path = Path(path)
    configuration, mac, problem = config.Config(), None, []
    awake = keep_awake.Awake()
    try:
        while True:
            found, lines = read(path)
            if found is None:
                if lines != problem:
                    for line in lines:
                        say(line)
                    if not once:
                        say("The last configuration that could be read keeps being served.")
                if once:
                    return 1
            elif mac is None or found != configuration:
                configuration, mac = found, mac_for(found)
            problem = lines
            if mac is None:
                mac = mac_for(configuration)
            if not once:
                awake.keep(keep_awake.wanted(configuration), mac, say)
            try:
                a_pass(configuration, mac)
            except Exception as error:  # the next round tries again
                say("The pass failed: %r" % (error,))
            if once or stopped():
                return 0
            watcher.watch([path] + ([] if path.exists() else [path.parent]) + passes.watched(configuration, mac))
            if watcher.wait(interval):
                quiet = clock() + settle  # a burst of changes makes one pass
                while not stopped() and clock() < quiet:
                    watcher.wait(quiet - clock())
            if stopped():
                return 0
    finally:
        awake.keep(False, mac)


@contextmanager
def stop_signals():
    """While inside, SIGTERM and SIGINT only ask to stop: (whether one came, a descriptor
    that becomes readable when one comes, to end a wait)."""
    came = []
    reading, writing = os.pipe()
    for end in (reading, writing):
        os.set_blocking(end, False)
    before_wakeup = signal.set_wakeup_fd(writing, warn_on_full_buffer=False)
    before = {asked: signal.signal(asked, lambda number, frame: came.append(number)) for asked in STOP_SIGNALS}
    try:
        yield (lambda: bool(came)), reading
    finally:
        for asked, handler in before.items():
            signal.signal(asked, handler)
        signal.set_wakeup_fd(before_wakeup)
        os.close(reading)
        os.close(writing)


def run(path, mac_for, say, lock_file, once=False, serve=serve):
    """The service, or with `once` one pass of it. 1, and said, when another one runs."""
    lock = state.exclusive(lock_file)
    if lock is None:
        say("Another %s is already running. Only one runs at a time." % names.command("run"))
        return 1
    with lock, stop_signals() as (stopped, wake):
        watcher = watch.Watcher(wake=wake)
        try:
            return serve(path, mac_for, say, watcher=watcher, stopped=stopped, once=once)
        finally:
            watcher.close()
