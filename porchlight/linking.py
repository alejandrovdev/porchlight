"""Linking folders: `setup` once for this Mac, `init` in each project's folder, `deinit` to
unlink one.

    setup(chosen, configuration, mac, out, asker)    the terminal and the defaults of new projects
    init(chosen, configuration, mac, out, asker)     add or replace the project of a folder
    deinit(chosen, configuration, mac, out, asker)   remove the project of a folder, and its server

`setup` and `init` ask their screens through `asker` (drawn on the terminal, or plain
questions) and change nothing until the last one is confirmed. A flag answers its screen
beforehand; `--yes` takes what each other screen would start from, and confirms. A screen
still to answer when the input ends is a usage error that names its flag (`Usage`). Then
the configuration is saved and the agents brought up to date the way `apply` does without
`--servers`: a server that runs is left as it is.

When Homebrew is there and a prerequisite it installs is missing, `setup` warns, asks
whether to install them (`--install-missing` answers yes, `--yes` alone no), and runs the
installs, in front of the person, after the last confirmation and before saving.

`deinit` says everything it is about to do before it does it, asks only when sessions a
server started would end, and removes that one server; the other projects' running servers
are left as they are. The free session that waits ends, and its worktree is removed when
nothing in it would be lost; the worktrees of sessions in use are left as they are, and so
are the logs.
"""

import os
from pathlib import Path

from . import agents, answers, config, doctor, names, screens, ui
from .atoms import launchd, tools, worktrees
from .features import live_view, ready_sessions
from .ui.widgets import Confirm

NOTHING = "Nothing was changed."
NEXT_INIT = "Next: in a project's folder, run: " + names.command("init")
STATUS = "See it here with: " + names.command("status")
NEXT_READY = "Next: on the phone, the ready session appears in the app's session list. " + STATUS
NEXT_SERVER = "Next: on the phone, create a session on this Mac from the app. " + STATUS
SIGN_IN = "Sign in to Claude Code by running `claude` once."
NO_HOMEBREW = "Homebrew was not found, so nothing was installed (missing: %s): install Homebrew from https://brew.sh, or install them yourself."
NOTHING_MISSING = "Nothing to install: every prerequisite is there."


class Usage(Exception):
    """The command line misses or gets wrong something a command needs (exit 2)."""


def given_features(chosen):
    """The features the flags give, or None."""
    if chosen.preset:
        return config.PRESETS[chosen.preset]
    if not chosen.feature:
        return None
    features = config.ordered(chosen.feature)
    problem = answers.features_problem(features)
    if problem:
        raise Usage("argument --feature: " + problem)
    return features


def given_mode(chosen, modes):
    if chosen.permission_mode is None:
        return None
    problem = answers.mode_problem(chosen.permission_mode, modes)
    if problem:
        raise Usage("argument --permission-mode: %s" % problem)
    return chosen.permission_mode


def asked(asker, steps, start, flags, yes):
    """Ask the screens that no flag answered, starting from `start`: the answers, or None
    when the person quit or said no."""
    given = {key for key, value in flags.items() if value is not None}
    known = dict(start, **{key: flags[key] for key in given})
    if yes:
        given |= {key for key, value in known.items() if value is not None} | {answers.PREREQUISITES, answers.CONFIRM}
        known[answers.CONFIRM] = True
    sequence = ui.Sequence.start(steps, known, given)
    try:
        sequence = asker.ask(sequence)
    except ui.Missing as missing:
        raise Usage(str(missing))
    return sequence.answers if sequence.state == ui.DONE else None


def saved(configuration, path, out):
    """Write a configuration once it reads back as itself; whether it was written."""
    try:
        config.parse(config.dump(configuration))
    except config.ConfigError as error:
        for key, problem in error.problems:
            out("%s: %s" % (key, problem) if key else problem)
        out(NOTHING)
        return False
    config.save(configuration, path)
    return True


def installed(brew, installs, mac, out):
    """Install each check's prerequisite with Homebrew, its output in view; a failure is
    said and the rest go on. Whether every one was installed."""
    every = True
    for check in installs:
        out("Installing %s: %s" % (check.what, doctor.brew_command(check)))
        code = mac.run_in_view([brew] + list(check.install))
        if code:
            out("Could not install %s: brew exited %d." % (check.what, code))
            every = False
        elif check.install == doctor.BREW["claude"]:
            out(SIGN_IN)
    return every


def setup(chosen, configuration, mac, out, asker):
    modes = doctor.listed_modes(mac)
    checks = doctor.prerequisites(mac)
    brew = doctor.homebrew(mac)
    installs = doctor.installable(checks) if brew else []
    labels = [check.what for check in installs]
    flags = {
        answers.INSTALL: "yes" if chosen.install_missing else None,
        answers.TERMINAL: chosen.terminal,
        answers.MODE: given_mode(chosen, modes),
        answers.FEATURES: given_features(chosen),
        answers.KEEP_AWAKE: chosen.keep_awake,
    }
    steps = [
        screens.prerequisites(checks, installs),
        screens.install(installs),
        screens.terminal(
            [mac.terminal_app(name) for name in config.TERMINALS], none=not answers.terminal_needed(configuration)
        ),
        screens.permission_mode("Default permission mode", modes),
        screens.features("Default features"),
        screens.keep_awake(lambda given: answers.needs_keep_awake(configuration, given)),
        screens.confirm("Save this configuration?", lambda given: answers.setup_summary(configuration, given, labels)),
    ]
    got = asked(asker, steps, answers.setup_answers(configuration), flags, chosen.yes)
    if got is None:
        out(NOTHING)
        return 1
    every = installed(brew, installs, mac, out) if got.get(answers.INSTALL) == "yes" else True
    if chosen.install_missing and not installs:  # the flag asked for what cannot be done, or for nothing
        missing = doctor.installable(checks)
        if missing:
            out(NO_HOMEBREW % ", ".join(check.what for check in missing))
            every = False
        else:
            out(NOTHING_MISSING)
    configured = answers.with_setup(configuration, got)
    if not saved(configured, chosen.config_file, out):
        return 1
    out("Saved the configuration in %s." % chosen.config_file)
    if not configured.projects:
        out(NEXT_INIT)
        code = 0
    else:
        code = agents.apply(configured, mac, out)
    return code if every else 1


def same_folder(one, other):
    return os.path.realpath(os.path.expanduser(str(one))) == os.path.realpath(os.path.expanduser(str(other)))


def given_name(chosen, check):
    if chosen.name is None:
        return None
    problem = check(chosen.name)
    if problem:
        raise Usage("argument --name: " + problem)
    return chosen.name


def chosen_folder(chosen):
    return Path(os.path.expanduser(chosen.folder)) if chosen.folder else Path.cwd()


def init(chosen, configuration, mac, out, asker):
    folder = chosen_folder(chosen)
    if not folder.is_dir():
        out("%s is not a folder. %s" % (folder, NOTHING))
        return 1
    top = worktrees.top_level(mac.git, folder)
    if top is None:
        out("%s is not in a git repository, and the features need one: run `git init` in it first. %s" % (folder, NOTHING))
        return 1
    existing = next((project for project in configuration.projects if same_folder(project.directory, top)), None)
    modes = doctor.listed_modes(mac)

    def check(name):
        return answers.name_problem(name, configuration, existing)

    flags = {
        answers.NAME: given_name(chosen, check),
        answers.MODE: given_mode(chosen, modes),
        answers.FEATURES: given_features(chosen),
        answers.TERMINAL: chosen.terminal,
    }
    def question(given):
        if existing is None:
            return "Link this folder?"
        return "Rename it?" if given[answers.NAME] != existing.name else "Replace its settings?"

    steps = [
        screens.name(check),
        screens.permission_mode("Permission mode", modes),
        screens.features("Features"),
        screens.terminal(
            [mac.terminal_app(name) for name in config.TERMINALS], lambda given: answers.needs_terminal(configuration, given)
        ),
        screens.confirm(question, lambda given: answers.init_summary(configuration, given, top, existing)),
    ]
    start = answers.init_answers(configuration, existing, answers.suggested_name(top, configuration))
    got = asked(asker, steps, start, flags, chosen.yes)
    if got is None:
        out(NOTHING)
        return 1
    configured, project = answers.with_project(configuration, got, top, existing, chosen.base)
    if not saved(configured, chosen.config_file, out):
        return 1
    if existing is not None and existing.name != project.name:
        out('Renamed "%s" to "%s".' % (existing.name, project.name))
    out('Linked "%s" (%s) in %s.' % (project.name, project.path, chosen.config_file))
    code = agents.apply(configured, mac, out)
    if existing is not None and existing.name != project.name and project.has("server"):
        renamed(existing, project, mac, out)
    if project.has("ready-session"):
        out(NEXT_READY)
    elif project.has("server"):
        out(NEXT_SERVER)
    else:
        out(STATUS)
    return code


def renamed(before, after, mac, out):
    """Say when the server of a project's old name still runs in its folder: `apply` loads
    no second server into a folder, and leaves a running one as it is."""
    old, new = (names.server_label(project.name, mac.environ) for project in (before, after))
    if mac.launchd.state(old) == launchd.LOADED and mac.launchd.state(new) != launchd.LOADED:
        out(
            'The server of "%s" still runs in this folder, so the server of "%s" did not start. To replace it '
            "(the sessions it started end): %s" % (before.name, after.name, names.command("apply", "--servers"))
        )


def holding(configuration, folder, mac):
    """The project whose folder is the folder's repository or holds the folder; the
    innermost when several do. None when none does."""
    places = [Path(os.path.realpath(folder))]
    try:
        top = worktrees.top_level(mac.git, folder) if folder.is_dir() else None
    except tools.ToolNotFound:
        top = None
    if top is not None:
        places.append(Path(os.path.realpath(top)))
    found = None
    for project in configuration.projects:
        repository = names.repository(project)
        if any(place == repository or repository in place.parents for place in places):
            if found is None or len(repository.parts) > len(names.repository(found).parts):
                found = project
    return found


def ready_records(project, mac):
    sessions = ready_sessions.load_state(mac.store(project, ready_sessions.STATE)).get("sessions")
    return sessions if isinstance(sessions, dict) else {}


def in_use(project, mac, ps_text):
    """The ready sessions of a project that were used and still run: [(session, record)]."""
    running = ready_sessions.running(ps_text)
    return [
        (session, record)
        for session, record in sorted(ready_records(project, mac).items())
        if session in running and isinstance(record, dict) and record.get("state") != "free"
    ]


def reach(record, mac):
    """How to see a session in use again: the command that attaches to it, or its tab."""
    try:
        return "reach it with: " + mac.tmux.attach(record["tmux"]) if record.get("tmux") else ""
    except tools.ToolNotFound:
        return ""


def plan(project, remaining, loaded, files, live, used, mac):
    """What deinit is about to do, in lines."""
    environ = mac.environ
    label = names.server_label(project.name, environ)
    service = names.service_label(environ)
    lines = ['Unlinking "%s" (%s):' % (project.name, project.path), "  - it is removed from the configuration"]
    if project.has("ready-session"):
        lines.append("  - its free ready session, if one waits, ends, and its worktree is removed when nothing in it would be lost")
    if label in loaded or label in files:
        line = "  - its server %s is unloaded and removed" % label
        if live:
            line += ": the %s it started %s" % (agents.counted(len(live), "session", "sessions"), "ends" if len(live) == 1 else "end")
        lines.append(line)
    if not remaining.projects and (service in loaded or service in files):
        lines.append("  - the service %s is unloaded and removed: no project is left" % service)
    for session, record in used:
        how = reach(record, mac)
        lines.append(
            '  - the session "%s" keeps running%s' % (ready_sessions.label(record, session), "; " + how if how else " in its terminal tab")
        )
    lines.append("  - the worktrees of its sessions in use in %s are left as they are" % worktrees.folder(names.repository(project)))
    return lines


def confirmed(chosen, asker, lines, live, out):
    """Whether the sessions a server started may end: --yes, or yes at a terminal."""
    if chosen.yes:
        return True
    count = agents.counted(len(live), "session", "sessions")
    if not asker.terminal:
        out("Its server runs %s, which would end. Confirm in a terminal, or give --yes. %s" % (count, NOTHING))
        return False
    question = "End the %s its server started, and unlink it?" % count
    step = ui.Screen(answers.CONFIRM, "--yes", lambda given: Confirm("Unlink", tuple(lines), question))
    if asker.ask(ui.Sequence.start([step])).state != ui.DONE:
        out(NOTHING)
        return False
    return True


def still_runs(project, mac):
    """Whether a session of the project's still runs: a ready session of its state, or one a
    server started in its folder."""
    ps_text = mac.processes()
    if set(ready_records(project, mac)) & set(ready_sessions.running(ps_text)):
        return True
    return bool(live_view.live_sessions(ps_text, worktrees.folder(names.repository(project))))


def deinit(chosen, configuration, mac, out, asker):
    """Unlink the project of a folder: say the plan, then remove it from the configuration
    and its server, end its free session (its worktree is removed when nothing in it would
    be lost) and remove its state once nothing of it runs. Sessions in use keep running and
    their worktrees stay, and so do the logs. 0 when all of it went well."""
    code = agents.refused(mac, out)
    if code:
        return code
    folder = chosen_folder(chosen)
    project = holding(configuration, folder, mac)
    if project is None:
        linked = ", ".join("%s (%s)" % (other.name, other.path) for other in configuration.projects)
        out("No project is linked to %s. %s" % (folder, "The linked projects: " + linked if linked else names.no_project()))
        return 1
    mine, foreign = agents.own_files(mac)
    loaded = agents.what_is_loaded(mac, out, mine)
    if loaded is None:
        return 1
    label = names.server_label(project.name, mac.environ)
    ps_text = mac.processes()
    live = live_view.live_sessions(ps_text, worktrees.folder(names.repository(project))) if label in loaded else {}
    remaining = answers.without(configuration, project)
    lines = plan(project, remaining, loaded, set(mine) | foreign, live, in_use(project, mac, ps_text), mac)
    for line in lines:
        out(line)
    if live and not confirmed(chosen, asker, lines, live, out):
        return 1
    code = agents.apply(remaining, mac, out, servers=[project.name])
    if mac.launchd.state(label) != launchd.GONE or launchd.file(mac.launch_agents, label).exists():
        out('"%s" stays in the configuration: its server could not be removed. Run this again.' % project.name)
        return 1
    config.save(remaining, chosen.config_file)
    out('Removed "%s" from %s.' % (project.name, chosen.config_file))
    if not agents.let_go_of(project, mac, out):
        code = 1
    forget(project, mac, out)
    out("Left as they are: the worktrees of its sessions in use, and its logs.")
    return code


def forget(project, mac, out):
    """Remove what the tool keeps of a project in its state, once nothing of it runs, and
    only in a state folder the tool made."""
    environ = mac.environ
    if still_runs(project, mac):
        out("Its state was kept: a session of it still runs.")
        return
    folder = names.project_state(project, environ)
    if not folder.exists() or not agents.made_here(names.state_root(environ), out):
        return
    agents.forget_state(project, environ)
    if folder.exists():
        out("Its state folder %s was kept: it holds files %s did not write." % (folder, names.TOOL))
    else:
        out("Removed its state.")
