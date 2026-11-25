"""The Mac stays awake while the service runs, on AC power and on battery, or on AC power
only when the configuration says `keep_awake = "plugged-in"`.

    wanted(configuration)               whether any project asks for it
    Awake().keep(wanted, mac, say, how) start the child that does it, or end it

One child for the whole service, whatever the number of projects: `caffeinate -i -s -w
<the service's pid>`, without -i on AC power only. The display still sleeps. On battery the
Mac does not sleep while idle, but closing its lid still puts it to sleep, as macOS decides.
A new setting replaces the child. The child
ends by itself when the service does, however that happens, so a Mac is never kept awake by
a service that is gone.
"""

FEATURE = "keep-awake"
CAFFEINATE = "/usr/bin/caffeinate"


def command(pid, how="always"):
    """Keep the Mac from any sleep on AC power (-s), and from idle sleep on battery too (-i)
    unless `how` is "plugged-in", for as long as a process runs (-w)."""
    idle = [] if how == "plugged-in" else ["-i"]
    return [CAFFEINATE] + idle + ["-s", "-w", str(pid)]


def wanted(configuration):
    return any(project.has(FEATURE) for project in configuration.projects)


class Awake:
    def __init__(self):
        self.child = None
        self.how = None  # the setting the child was started with
        self.failed = False  # so that a child that cannot start is said once

    def keep(self, wanted, mac, say=lambda line: None, how="always"):
        """Have the child when it is wanted and none otherwise; one started with another
        setting is replaced."""
        if self.child is not None and self.child.poll() is not None:
            self.child = None  # it ended by itself
        if wanted and self.child is not None and self.how != how:
            self.end()
        if wanted and self.child is None:
            try:
                self.child = mac.spawn(command(mac.pid(), how))
                self.how = how
                self.failed = False
            except OSError as error:
                if not self.failed:
                    say("Could not keep the Mac awake: %r" % (error,))
                self.failed = True
        elif not wanted and self.child is not None:
            self.end()

    def end(self):
        if self.child is not None:
            child, self.child = self.child, None
            try:
                child.terminate()
                child.wait(timeout=5)
            except Exception:  # it is gone, or will be when the service is
                pass
