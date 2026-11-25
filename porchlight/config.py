"""The configuration file: the projects porchlight serves and the features of each.

One TOML file that `setup` and `init` write and a person may edit by hand:

    terminal = "warp"

    [defaults]
    permission_mode = "manual"
    preset = "recommended"

    [projects.shop]
    path = "~/Projects/shop"
    permission_mode = "manual"
    preset = "recommended"

    [projects.blog]
    path = "~/Projects/blog"
    permission_mode = "plan"
    features = ["server", "resume-list"]

`[defaults]` is optional: what a new project starts from, with the same rules as a
project's table, each value of it optional. Reading it checks its shape only: types, names, and that each feature has the features it
builds on. Whether a folder exists or a tool is installed is for `doctor` to say.
"""

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import names
from .atoms import state


@dataclass(frozen=True)
class Feature:
    summary: str
    needs: tuple = ()  # other features
    tools: tuple = ()  # what must be installed


# In the order a feature may be turned on: each one comes after the features it needs.
FEATURES = {
    "server": Feature(
        "The app creates sessions on this Mac, each in its own worktree", tools=("claude", "git")
    ),
    "ready-session": Feature(
        "A session with Claude Code's interface is always ready to write in", tools=("claude", "git", "tmux")
    ),
    "tabs": Feature(
        "A terminal tab opens when a session is used and closes when it is archived",
        needs=("ready-session",),
        tools=("terminal",),
    ),
    "live-view": Feature("A read-only tab follows a session the server started", needs=("server", "tabs")),
    "reopen": Feature("A closed session comes back by name, asked from the phone", needs=("ready-session",)),
    "resume-list": Feature("The server's sessions appear in /resume", needs=("server",)),
    "keep-awake": Feature("The Mac stays awake on AC power while porchlight runs"),
}

PRESETS = {
    "minimal": ("server",),
    "recommended": tuple(FEATURES),
}

TERMINALS = ("warp",)
TOOLS = ("claude", "git", "tmux", "terminal")

PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,31}$")
ONE_WORD = re.compile(r"^[A-Za-z]+$")
PROJECT_KEYS = ("path", "permission_mode", "preset", "features", "base", "session_prefix")
DEFAULTS_KEYS = ("permission_mode", "preset", "features")


class ConfigError(Exception):
    """What is wrong with a configuration file, as (key, message) pairs in the file's order."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("\n".join(("%s: %s" % pair) if pair[0] else pair[1] for pair in self.problems))


@dataclass(frozen=True)
class Project:
    name: str
    path: str  # as written, so that it is written back the same way
    permission_mode: str
    features: tuple
    base: Optional[str] = None  # None: the repository's default branch
    prefix: str = ""

    @property
    def directory(self):
        return Path(os.path.expanduser(self.path))

    def has(self, feature):
        return feature in self.features


@dataclass(frozen=True)
class Defaults:
    """What a new project starts from; None where nothing was chosen."""

    permission_mode: Optional[str] = None
    features: Optional[tuple] = None


@dataclass(frozen=True)
class Config:
    terminal: Optional[str] = None
    projects: tuple = ()
    defaults: Defaults = Defaults()

    def project(self, name):
        return next((project for project in self.projects if project.name == name), None)


def default_path():
    chosen = os.environ.get("PORCHLIGHT_CONFIG")
    if chosen:
        return Path(chosen)
    return Path.home() / "Library" / "Application Support" / "porchlight" / "config.toml"


def ordered(features):
    """The given features in the order of the feature table."""
    return tuple(name for name in FEATURES if name in features)


def tools(features):
    """What must be installed for these features, in a fixed order."""
    needed = {tool for name in features for tool in FEATURES[name].tools}
    return tuple(tool for tool in TOOLS if tool in needed)


def folder_key(path):
    return os.path.normpath(os.path.expanduser(path))


def chosen_features(key, table, problems):
    """The features a project's table asks for, or None when it states them wrongly."""
    has_preset, has_features = "preset" in table, "features" in table
    if has_preset and has_features:
        problems.append((key, "give either preset or features, not both"))
        return None
    if not has_preset and not has_features:
        problems.append((key, "give a preset or a list of features"))
        return None
    if has_preset:
        preset = table["preset"]
        if not isinstance(preset, str):
            problems.append((key + ".preset", "must be text"))
            return None
        if preset not in PRESETS:
            problems.append((key + ".preset", 'unknown preset "%s"; one of: %s' % (preset, ", ".join(PRESETS))))
            return None
        return PRESETS[preset]
    listed = table["features"]
    if not isinstance(listed, list) or not all(isinstance(name, str) for name in listed):
        problems.append((key + ".features", "must be a list of feature names"))
        return None
    if not listed:
        problems.append((key + ".features", "name at least one feature"))
        return None
    before = len(problems)
    for name in listed:
        if name not in FEATURES:
            problems.append((key + ".features", 'unknown feature "%s"' % name))
    for name in ordered(listed):
        for needed in FEATURES[name].needs:
            if needed not in listed:
                problems.append((key + ".features", '"%s" needs "%s"' % (name, needed)))
    return ordered(listed) if len(problems) == before else None


def text_value(key, table, name, problems, pattern=None, shape="", required=False):
    """A text value of a table, or None when it is absent or wrong."""
    if name not in table:
        if required:
            problems.append(("%s.%s" % (key, name), "missing"))
        return None
    value = table[name]
    if not isinstance(value, str):
        problems.append(("%s.%s" % (key, name), "must be text"))
        return None
    if not value or (pattern and not pattern.fullmatch(value)):
        problems.append(("%s.%s" % (key, name), shape or "must not be empty"))
        return None
    return value


def project_from(name, table, problems):
    key = "projects.%s" % name
    if not PROJECT_NAME.fullmatch(name):
        problems.append((key, "a project's name has lowercase letters, digits and hyphens, at most 32"))
        return None
    if not isinstance(table, dict):
        problems.append((key, "must be a table"))
        return None
    before = len(problems)
    path = text_value(key, table, "path", problems, required=True)
    mode = text_value(key, table, "permission_mode", problems, ONE_WORD, "must be one word", required=True)
    features = chosen_features(key, table, problems)
    base = text_value(key, table, "base", problems)
    prefix = text_value(
        key, table, "session_prefix", problems, PREFIX, "has letters, digits and hyphens, at most 32"
    )
    for other in table:
        if other not in PROJECT_KEYS:
            problems.append(("%s.%s" % (key, other), "unknown key"))
    if len(problems) != before:
        return None
    return Project(name, path, mode, features, base, prefix or name)


def defaults_from(table, problems):
    key = "defaults"
    if not isinstance(table, dict):
        problems.append((key, "must be a table"))
        return Defaults()
    mode = text_value(key, table, "permission_mode", problems, ONE_WORD, "must be one word")
    features = chosen_features(key, table, problems) if "preset" in table or "features" in table else None
    for other in table:
        if other not in DEFAULTS_KEYS:
            problems.append(("%s.%s" % (key, other), "unknown key"))
    return Defaults(mode, features)


def parse(text):
    """The configuration a TOML text describes; ConfigError lists everything wrong with it."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError([("", str(error))])
    problems = []
    terminal = data.get("terminal")
    if terminal is not None and not isinstance(terminal, str):
        problems.append(("terminal", "must be text"))
    elif terminal is not None and terminal not in TERMINALS:
        problems.append(("terminal", 'unknown terminal "%s"; one of: %s' % (terminal, ", ".join(TERMINALS))))
    for key in data:
        if key not in ("terminal", "defaults", "projects"):
            problems.append((key, "unknown key"))
    defaults = defaults_from(data.get("defaults", {}), problems)
    tables = data.get("projects", {})
    if not isinstance(tables, dict):
        problems.append(("projects", "must be a table of projects"))
        tables = {}
    projects, folders, prefixes = [], {}, {}
    for name, table in tables.items():
        project = project_from(name, table, problems)
        if project is None:
            continue
        key = "projects.%s" % name
        folder = folder_key(project.path)
        if folder in folders:
            problems.append((key + ".path", 'the project "%s" already uses this folder' % folders[folder]))
        if project.prefix in prefixes:
            problems.append(
                (key + ".session_prefix", 'the project "%s" already uses this prefix' % prefixes[project.prefix])
            )
        folders.setdefault(folder, name)
        prefixes.setdefault(project.prefix, name)
        projects.append(project)
    if terminal is None:
        for project in projects:
            if "terminal" in tools(project.features):
                feature = next(name for name in project.features if "terminal" in FEATURES[name].tools)
                problems.append(("terminal", 'required by "%s" of the project "%s"' % (feature, project.name)))
                break
    if problems:
        raise ConfigError(problems)
    return Config(terminal, tuple(projects), defaults)


def quoted(value):
    # A JSON string is a valid TOML basic string.
    return json.dumps(value, ensure_ascii=False)


def features_line(features):
    """A set of features as a table states it: by its preset's name, else as a list."""
    preset = next((name for name, chosen in PRESETS.items() if chosen == features), None)
    if preset:
        return "preset = %s" % quoted(preset)
    return "features = [%s]" % ", ".join(quoted(name) for name in features)


def dump(config):
    """The TOML text of a configuration; `parse` reads back the same configuration."""
    lines = []
    if config.terminal:
        lines.append("terminal = %s" % quoted(config.terminal))
    defaults = config.defaults
    if defaults.permission_mode is not None or defaults.features is not None:
        if lines:
            lines.append("")
        lines.append("[defaults]")
        if defaults.permission_mode is not None:
            lines.append("permission_mode = %s" % quoted(defaults.permission_mode))
        if defaults.features is not None:
            lines.append(features_line(defaults.features))
    for project in config.projects:
        if lines:
            lines.append("")
        lines.append("[projects.%s]" % project.name)
        lines.append("path = %s" % quoted(project.path))
        lines.append("permission_mode = %s" % quoted(project.permission_mode))
        if project.base:
            lines.append("base = %s" % quoted(project.base))
        if project.prefix != project.name:
            lines.append("session_prefix = %s" % quoted(project.prefix))
        lines.append(features_line(project.features))
    return "\n".join(lines) + "\n" if lines else ""


def load(path=None):
    """The configuration in a file; an absent file is a configuration without projects."""
    path = Path(path) if path else default_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Config()
    return parse(text)


def save(config, path=None):
    """Write a configuration, replacing the file in one step. A folder made for it is marked
    as the tool's, as the state folder is: by default they are the same folder."""
    path = Path(path) if path else default_path()
    state.claim(path.parent, names.MARKER)
    draft = path.with_name(path.name + ".new")
    draft.write_text(dump(config), encoding="utf-8")
    os.replace(draft, path)
