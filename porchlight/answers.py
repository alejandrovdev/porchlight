"""What the screens of `setup` and `init` answer, turned into a configuration, and a
configuration turned into the answers they start from: the only module that knows both.

    setup_answers(configuration)            what setup starts from: the current values
    with_setup(configuration, answers)      the configuration setup saves
    init_answers(configuration, existing, suggested)   what init starts from
    with_project(configuration, answers, folder, existing, base)   the configuration init saves
    without(configuration, project)         the configuration deinit saves
    suggested_name(folder, configuration)   a project name made from a folder's name
    name_problem, mode_problem, features_problem   what is wrong with an answer, or ""

Answers are a dict, under the keys below. Nothing here asks, prints or writes.
"""

import dataclasses
import re
from pathlib import Path

from . import config

PREREQUISITES, TERMINAL, MODE, FEATURES, NAME, CONFIRM = (
    "prerequisites",
    "terminal",
    "permission_mode",
    "features",
    "name",
    "confirm",
)
NAME_SHAPE = "a project's name has lowercase letters, digits and hyphens, at most 32"
FIRST = "recommended"  # the preset the features start from when nothing was chosen


def setup_answers(configuration):
    """What setup starts from: the terminal and the defaults saved, else nothing chosen and
    the recommended features."""
    defaults = configuration.defaults
    return {
        TERMINAL: configuration.terminal,
        MODE: defaults.permission_mode,
        FEATURES: defaults.features or config.PRESETS[FIRST],
    }


def with_setup(configuration, answers):
    """The configuration with setup's answers: its projects as they were."""
    defaults = config.Defaults(answers[MODE], config.ordered(answers[FEATURES]))
    return dataclasses.replace(configuration, terminal=answers[TERMINAL], defaults=defaults)


def init_answers(configuration, existing, suggested):
    """What init starts from: a linked project's values, else the defaults saved."""
    if existing is not None:
        return {
            NAME: existing.name,
            MODE: existing.permission_mode,
            FEATURES: existing.features,
            TERMINAL: configuration.terminal,
        }
    defaults = configuration.defaults
    return {
        NAME: suggested,
        MODE: defaults.permission_mode,
        FEATURES: defaults.features or config.PRESETS[FIRST],
        TERMINAL: configuration.terminal,
    }


def needs_terminal(configuration, answers):
    """Whether init must ask for a terminal: the features chosen open tabs, and none is set."""
    return "terminal" in config.tools(answers.get(FEATURES) or ()) and not configuration.terminal


def with_project(configuration, answers, folder, existing=None, base=None):
    """(the configuration with init's project, the project). A linked project is replaced
    where it is, in its folder as written; a new one is added last, in `folder`. Its session
    prefix stays when it was chosen by hand, else it follows the name."""
    name = answers[NAME]
    if existing is not None:
        path = existing.path
        prefix = existing.prefix if existing.prefix != existing.name else name
        base = existing.base if base is None else base
    else:
        path, prefix = str(folder), name
    project = config.Project(name, path, answers[MODE], config.ordered(answers[FEATURES]), base, prefix)
    if existing is not None:
        projects = tuple(project if other is existing else other for other in configuration.projects)
    else:
        projects = configuration.projects + (project,)
    terminal = answers.get(TERMINAL) or configuration.terminal
    return dataclasses.replace(configuration, terminal=terminal, projects=projects), project


def without(configuration, project):
    """The configuration without a project: its terminal and defaults stay."""
    return dataclasses.replace(configuration, projects=tuple(other for other in configuration.projects if other != project))


def name_problem(name, configuration, existing=None):
    """What is wrong with a project's name, or "": its shape, or another project using it."""
    if not config.PROJECT_NAME.fullmatch(name or ""):
        return NAME_SHAPE
    for other in configuration.projects:
        if other is existing:
            continue
        if other.name == name:
            return 'the project "%s" already has this name' % name
        if other.prefix == name:
            return 'the project "%s" already uses it as its session prefix' % other.name
    return ""


def suggested_name(folder, configuration):
    """A folder's name made a project's: lowercase, anything else a hyphen, at most 32, and
    numbered when another project has it."""
    base = re.sub(r"[^a-z0-9]+", "-", Path(folder).name.lower()).strip("-")[:32].strip("-") or "project"
    name, number = base, 2
    while name_problem(name, configuration):
        tail = "-%d" % number
        name = base[: 32 - len(tail)].rstrip("-") + tail
        number += 1
    return name


def mode_problem(mode, modes=None):
    """What is wrong with a permission mode, or "": one word, and one of `modes` when the
    installed Claude Code lists them."""
    if not config.ONE_WORD.fullmatch(mode or ""):
        return "a permission mode is one word"
    if modes and mode not in modes:
        return "claude lists: %s" % ", ".join(modes)
    return ""


def features_problem(features):
    """What is wrong with a list of features, or "": each needs what it builds on."""
    missing = [
        '"%s" needs "%s"' % (name, needed)
        for name in config.ordered(features)
        for needed in config.FEATURES[name].needs
        if needed not in features
    ]
    return "; ".join(missing)


def setup_summary(configuration, answers):
    """What setup is about to save, in lines."""
    lines = [
        "Terminal: %s" % (answers.get(TERMINAL) or "none"),
        "Default permission mode: %s" % answers[MODE],
        "Default features: %s" % ", ".join(config.ordered(answers[FEATURES])),
    ]
    if configuration.projects:
        names = ", ".join(project.name for project in configuration.projects)
        lines.append("Projects: %s. Their agents are brought up to date; a running server is left as it is." % names)
    else:
        lines.append("No project yet: link one from its folder with porchlight init.")
    return lines


def init_summary(configuration, answers, folder, existing=None):
    """What init is about to save, in lines."""
    lines = [
        "Project: %s" % answers[NAME],
        "Folder: %s" % (existing.path if existing is not None else folder),
        "Permission mode: %s" % answers[MODE],
        "Features: %s" % ", ".join(config.ordered(answers[FEATURES])),
    ]
    if "terminal" in config.tools(answers[FEATURES]):
        lines.append("Terminal: %s" % (answers.get(TERMINAL) or configuration.terminal))
    if existing is not None and existing.name != answers[NAME]:
        lines.append(
            'This folder is linked already, as "%s": this renames that project to "%s".' % (existing.name, answers[NAME])
        )
    elif existing is not None:
        lines.append('It replaces the settings of the linked project "%s".' % existing.name)
    return lines
