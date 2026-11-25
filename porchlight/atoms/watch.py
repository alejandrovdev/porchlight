"""Waiting until a file or a folder changes, instead of looking at it every few seconds.

    watcher.watch(paths)    from now on, these files and folders and no other
    watcher.wait(seconds)   True as soon as one of them changed; False once the seconds passed

The system tells the changes (kqueue), so a wait costs nothing while nothing happens. A file
counts as changed when it is written, grows, is renamed or is removed; a folder when
something appears in it or leaves it. What changes between two waits is told by the next
one. A path that is not there is skipped: watch its folder to learn that it appeared.

A file replaced by another (written beside it and renamed over it) is told as a change of
the one that was watched; `watch` then follows the new one.

`wake` is a descriptor to read from, such as the end of a pipe a signal writes to: a byte in
it ends a wait, which answers False, and is read away.
"""

import os
import select

OPEN_TO_WATCH = getattr(os, "O_EVTONLY", 0x8000)  # no reading: the file may still be removed or unmounted
CHANGES = select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME


class Watcher:
    def __init__(self, wake=None):
        self.queue = select.kqueue()
        self.open = {}  # path: (its descriptor, the file it was when opened)
        self.wake = wake
        if wake is not None:
            self.queue.control([select.kevent(wake, select.KQ_FILTER_READ, select.KQ_EV_ADD)], 0, 0)

    def watched(self):
        return sorted(self.open)

    def watch(self, paths):
        """Watch these paths that exist, and let go of every other."""
        wanted = {}
        for path in map(str, paths):
            try:
                found = os.stat(path)
            except OSError:
                continue
            known = self.open.get(path)
            if known is not None and known[1] == (found.st_dev, found.st_ino):
                wanted[path] = known  # the same file: what happened to it meanwhile is still told
                continue
            try:
                descriptor = os.open(path, OPEN_TO_WATCH)
            except OSError:
                continue
            opened = os.fstat(descriptor)
            flags = select.KQ_EV_ADD | select.KQ_EV_CLEAR
            self.queue.control([select.kevent(descriptor, select.KQ_FILTER_VNODE, flags, CHANGES)], 0, 0)
            wanted[path] = (descriptor, (opened.st_dev, opened.st_ino))
        for path, known in self.open.items():
            if wanted.get(path) is not known:
                os.close(known[0])  # closing it ends its watch
        self.open = wanted

    def wait(self, seconds):
        """Whether something watched changed within some seconds."""
        changed = False
        for event in self.queue.control(None, 64, max(0.0, seconds)):
            if event.filter == select.KQ_FILTER_READ:
                self.drain()
            else:
                changed = True
        return changed

    def drain(self):
        try:
            while os.read(self.wake, 512):
                pass
        except OSError:  # nothing more to read
            pass

    def close(self):
        for descriptor, _ in self.open.values():
            os.close(descriptor)
        self.open = {}
        self.queue.close()
