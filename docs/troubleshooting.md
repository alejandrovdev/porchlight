# Troubleshooting porchlight

Part of [porchlight](../README.md): what `doctor`, `status` and the logs tell you, and the
common problems with their fixes.

Start with:

```sh
porchlight doctor
porchlight status
```

`doctor` first checks this Mac: whether Claude Code is signed in (it asks
`claude auth status`, reads only whether someone is, and prints no account detail), its
version (`claude --version`: a `problem` below 2.1.92, which lacks options porchlight
uses; `ok` from there, with 2.1.327 or later recommended) and, once a project is
configured, whether the service's login agent is loaded. Then it checks,
for each project, only what its features need: the folder, Claude Code, git, tmux, the
terminal, the git repository, the base branch, the permission mode and, with `server`,
whether the server's login agent is loaded. An agent that is not loaded is fixed with
`porchlight start`; one whose file is missing, with `porchlight apply`. Each line is `ok`,
`missing`, `problem` or `unknown` (what could not be found out), with what to do; the exit
code is 1 when something is `missing` or a `problem`.

```text
This Mac
  ok       Claude Code sign-in
  ok       Claude Code version 2.1.327
  ok       service agent io.github.alejandrovdev.porchlight

shop
  ok       folder ~/Projects/shop
  ok       Claude Code (claude) at ~/.local/bin/claude
  ok       git at /usr/bin/git
  ok       tmux at /opt/homebrew/bin/tmux
  ok       Warp, the terminal its tabs open in
  ok       git repository
  problem  base branch: none could be determined: set `base` for the project in the configuration, or run `git remote set-head origin --auto` in the repository
  ok       permission mode "manual"
  problem  server agent io.github.alejandrovdev.porchlight.server.shop: not loaded: run `porchlight start`
```

**Logs** are in `~/Library/Logs/porchlight/`: `<project>.log` for what happens to a
project's sessions, tabs and worktrees, `agent.service.log` for the service, and
`agent.server.<project>.log` for a server. A message that repeats the last one is not
written again.

```sh
tail -f ~/Library/Logs/porchlight/shop.log
```

**The login agents**: `launchctl print` shows one agent, its state and its last exit; it
fails when the agent is not loaded.

```sh
launchctl print gui/$(id -u)/io.github.alejandrovdev.porchlight
launchctl print gui/$(id -u)/io.github.alejandrovdev.porchlight.server.shop
launchctl list | grep alejandrovdev.porchlight
```

An agent that is not loaded comes back with `porchlight start`; one that has no file, with
`porchlight apply`.

## No ready session appears in the app

- `porchlight status` should list a `free` session with a pid. If it lists none, check that
  the project has `ready-session`, that `doctor` passes, and that the service is loaded
  (above).
- Read the project's log. `no worktree for ...` names the git problem; with
  `no base branch is known`, set `base` for the project, or record the default branch of
  `origin` with `git remote set-head origin --auto`. After `no free session started (N in a
  row)`, porchlight waits before trying again: two minutes after the first failure, twice as
  long after each next one, at most an hour. `status` then says, under the project's ready
  sessions, how many attempts failed and when the next one comes. Once the cause is fixed,
  `porchlight retry --project <name>` clears the wait. It starts nothing itself and does not
  wake the service: the service tries at its next pass, within 20 seconds.
- If the session runs but `status` says `not in the app yet`, its transcript does not name a
  Remote Control session yet. Most often Claude Code is waiting for you to trust the
  folder: the first time it opens a repository it asks "Is this a project you created or
  one you trust?", and the session cannot answer from the phone. `status` then says
  `waiting for you to trust the folder` and prints the command that attaches to it, and
  `doctor` reports it. Answer "Yes, I trust this folder" in that session; run `claude` once
  in the repository and trust it too, so the next sessions do not ask. Otherwise, check
  that Claude Code is signed in and that your plan includes Remote Control.

## A tab does not open

- The project needs `tabs`, and the configuration a terminal: `terminal = "warp"` or
  `terminal = "apple-terminal"`. Warp must be installed (`doctor` looks for it in
  `/Applications` and `~/Applications`); Terminal comes with macOS.
- The terminal must be running: porchlight never starts it. The tab opens at the next pass
  once it runs.
- With Terminal, porchlight opens each window through AppleScript, so macOS asks once
  whether it may control Terminal. If that was refused, the log says
  `failed to open a tab ... Not authorized to send Apple events to Terminal`: allow it in
  System Settings, Privacy & Security, Automation.
- With Terminal, a window whose session ended stays open, showing `[Process completed]`,
  when its profile says so. To have it close, set Terminal, Settings, Profiles, your
  profile, Shell, "When the shell exits" to "Close if the shell exited cleanly" or
  "Close the window". porchlight does not change your Terminal settings.
- After three failed attempts the session keeps running without a tab, driven from the app,
  and no tab is tried again for it. `status` marks it `hidden` and prints, below it, the
  command that attaches to it in a terminal. The log says `no tab opened for ... (attempt N)`.
- For the server's sessions, `status` says `tab open`, `no tab yet` or
  `tab closed by the user`. A view tab you closed is not opened again; open the view
  yourself with `porchlight view <project> <session>`.

## A closed tab leaves the session listed in the app

- Closing a session's tab ends the session on the Mac, but the app keeps it listed until you
  archive it there: porchlight cannot archive a session from the Mac.
- Unarchiving a session in the app reaches nothing on the Mac. To bring it back, ask a ready
  session to reopen it by name (the `reopen` feature), or run `porchlight reopen <name>` on
  the Mac.

## A session archived in the app keeps running

- porchlight ends only the sessions it started (ready and reopened ones), never a session
  you started yourself, and only while the service runs: it reads the archive in the
  session's transcript and ends the process at its next pass. Check that the service is
  loaded; once it runs again, it ends the session.
- A session the server started ends through the server itself, not through porchlight.

## `/resume` does not list the server's sessions

- The project needs `resume-list` (which needs `server`).
- The copies are kept in the session folder of the repository's top folder: run `claude` in
  that folder, not in a worktree, and use `/resume` there.
- That folder exists only once Claude Code has run a session in the repository's top folder.
  Until then porchlight makes no copy.
- `porchlight resume-list sync` brings the copies up to date and prints, for each one, the
  command that resumes it.

## The Mac sleeps

- Turn on `keep-awake` for a project. It works while the service runs, on AC power and on
  battery unless `setup` set it to `Only on AC power` (`keep_awake = "plugged-in"`); the
  display still sleeps. On battery, closing the lid still puts the Mac to sleep. `pmset -g assertions` lists `caffeinate` while it holds the Mac
  awake.
- While the Mac sleeps, nothing on it runs, so the app cannot reach its sessions.

## A server uses an old permission mode

A running server keeps the mode it started with. Restart it with `porchlight apply --servers`
(its sessions end). See [Running and stopping](../README.md#running-and-stopping).

