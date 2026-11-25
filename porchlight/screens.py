"""The screens `setup` and `init` ask, each one a widget for one answer, built from what the
command found (the checks, the terminal apps, the modes Claude Code lists) and from the
answers so far. Nothing is decided here: `answers` turns the answers into a configuration.
"""

from . import answers, config
from .ui import Screen
from .ui.widgets import Checklist, Choice, Confirm, Item, Summary, TextField

FEATURE_FLAGS = "--preset or --feature"


def prerequisites(checks):
    body = tuple(check.line() for check in checks) + ("", "Nothing is installed from here: install what is missing yourself.")
    return Screen(answers.PREREQUISITES, "--yes", lambda given: Summary("Prerequisites", body))


def terminal(apps, asked=lambda given: True):
    """The terminal apps porchlight supports, each marked installed or not; asked only when
    `asked(answers so far)`."""
    items = tuple(Item(app.name, app.title, "installed" if app.installed() else "not installed") for app in apps)

    def make(given):
        return Choice.of("Terminal", items, given.get(answers.TERMINAL)) if asked(given) else None

    return Screen(answers.TERMINAL, "--terminal", make)


def keep_awake(asked=lambda given: True):
    """When keep-awake holds the Mac awake; asked only when `asked(answers so far)`."""
    items = tuple(Item(value, answers.KEEP_AWAKE_TITLES[value]) for value in config.KEEP_AWAKE)

    def make(given):
        return Choice.of("Keep the Mac awake", items, given.get(answers.KEEP_AWAKE)) if asked(given) else None

    return Screen(answers.KEEP_AWAKE, "--keep-awake", make)


def permission_mode(title, modes):
    """A choice of the modes Claude Code lists, or a field to type one when they could not
    be read."""

    def make(given):
        current = given.get(answers.MODE)
        if modes is None:
            note = "The modes `claude --help` lists could not be read: type one, such as plan."
            return TextField(title, current or "", answers.mode_problem, note)
        return Choice.of(title, tuple(Item(mode, mode) for mode in modes), current)

    return Screen(answers.MODE, "--permission-mode", make)


def features(title):
    items = tuple(Item(name, name, feature.summary) for name, feature in config.FEATURES.items())
    needs = {name: feature.needs for name, feature in config.FEATURES.items()}
    return Screen(
        answers.FEATURES, FEATURE_FLAGS, lambda given: Checklist.of(title, items, needs, given.get(answers.FEATURES) or ())
    )


def name(check):
    note = "Lowercase letters, digits and hyphens, at most 32."
    return Screen(answers.NAME, "--name", lambda given: TextField("Project name", given.get(answers.NAME) or "", check, note))


def confirm(question, describe):
    """The last screen: what is about to be saved (`describe(answers)`), and yes or no. The
    question may depend on the answers too."""

    def shown(given):
        asked = question(given) if callable(question) else question
        return Confirm("Summary", tuple(describe(given)), asked)

    return Screen(answers.CONFIRM, "--yes", shown)
