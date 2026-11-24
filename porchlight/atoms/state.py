"""A state file: a JSON table replaced whole, with a lock beside it.

Two runs may overlap (a pass every few seconds, a command a person runs), so whoever
reads the state to change it holds the lock from the read to the write.
"""

import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(".lock")

    @contextmanager
    def locked(self):
        """Hold the file's lock; waits for whoever holds it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield self

    def load(self, default):
        """The table in the file; `default` when the file is absent or is not a table."""
        try:
            loaded = json.loads(self.path.read_text(encoding="utf8"))
        except (OSError, ValueError):
            return default
        return loaded if isinstance(loaded, dict) else default

    def save(self, table):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        draft = self.path.with_suffix(".writing")
        draft.write_text(json.dumps(table, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf8")
        os.replace(draft, self.path)
