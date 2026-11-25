# porchlight

Leave a light on for your phone: porchlight keeps Claude Code sessions ready on your Mac so
you can start, follow and close them from the Claude mobile app.

> **Status: in development.** The repository and its Homebrew tap are private for now:
> `brew install` works only for a GitHub account with access to both. Commands and files
> may still change before the first public release.

Contents: [The problem it solves](#the-problem-it-solves) ·
[Requirements](#requirements) · [Install](#install) · [Quick start](#quick-start) ·
[Linking and unlinking folders](#linking-and-unlinking-folders) ·
[How it works](#how-it-works) · [Features and presets](#features-and-presets) ·
[Configuration](#configuration) · [Commands](#commands) ·
[Running and stopping](#running-and-stopping) · [Security and privacy](#security-and-privacy) ·
[Troubleshooting](#troubleshooting) · [Uninstall](#uninstall) · [Development](#development)

## The problem it solves

Claude Code's Remote Control lets you drive a session that runs on your Mac from the Claude
mobile app. On its own it leaves four gaps when the phone is the only thing in your hands:

| Without porchlight | With porchlight |
| --- | --- |
| The app cannot start a session that has Claude Code's own interface. Someone has to open a terminal on the Mac first. | A session is always waiting, already connected. You write in it and work starts. |
| A session the app creates through the Remote Control server has no window. On the Mac there is nothing to look at or type in. | A session you use gets a terminal tab, and a session the server started gets a read-only tab that follows it. |
| Archiving a session in the app does not end it on the Mac. Processes, tabs and worktrees pile up. | Archiving closes the tab, ends the session and removes its worktree when nothing in it would be lost. |
| Unarchiving in the app does not bring a session back online. | You ask for it by name from the phone and it comes back in a new tab. |

It serves one project or several, and each one runs only the features you turn on.

## Requirements

- A Mac with [Homebrew](https://brew.sh).
- Claude Code, installed on its own (porchlight does not install it), with `claude` in your
  `PATH`, signed in with a plan that includes Remote Control.
- The Claude mobile app, signed in to the same account.
- git: the one in Apple's Command Line Tools or Homebrew's.
- tmux and Python 3.11 or later. The Homebrew formula installs both.
- A terminal for the features that open terminal tabs (`tabs` and `live-view`):
  [Warp](https://www.warp.dev), or Terminal, the app macOS comes with. Without one you can
  still use every other feature.

## Install

```sh
brew install alejandrovdev/porchlight/porchlight
porchlight --version
```

The tap is `alejandrovdev/porchlight`. Installing adds the `porchlight` command; nothing
runs in the background until you link a folder with `porchlight init`.

While the repositories are private, Homebrew downloads them with `git`, which uses your
own GitHub credentials (for example `gh auth setup-git`).

## Quick start

1. Set up this Mac once:

   ```sh
   porchlight setup
   ```

2. Link a project. Go to its folder (a git repository) and run `init`:

   ```sh
   cd ~/Projects/shop
   porchlight init
   ```

3. **On the phone**, open the Claude app. The ready session appears in your session list;
   its name starts with the project's name (`shop`). Write in it and work starts.
4. **On the Mac**, with your terminal running, a tab opens on that session soon after your
   first message, and porchlight prepares the next ready session. Archiving the session in
   the app ends it and closes its tab (in Terminal, when its profile closes windows: see
   [A tab does not open](#a-tab-does-not-open)).
5. See every project's sessions:

   ```sh
   porchlight status
   ```

   ```text
   shop
     Ready sessions, with Claude Code's interface:
       5f0c9e21  free     2026-11-24 09:41  5f0c9e21  (pid 48211, cse_01Hq7c, hidden)
       a83d2b7c  used     2026-11-24 09:12  Fix the checkout total  (pid 47102, cse_01Xk2m)
     Sessions the server started, with a read-only view:
       No session the server started is running.
   ```

With the `server` feature on, you can also create new sessions on this Mac from the app.

### What `setup` asks

1. **Prerequisites**: Claude Code, git, tmux and each supported terminal app, each marked
   `ok` or `missing` with what to do about it. Nothing is installed from here.
2. **Terminal**: the app tabs open in (Warp, or Terminal), marked installed or not
   installed, or `None`: no tab opens and sessions run hidden. `None` is offered only while
   no linked project has `tabs`; a project linked later with `tabs` asks for a terminal.
3. **Default permission mode**: one of the modes your installed `claude --help` lists. When
   they cannot be read, you type one.
4. **Default features**: a checklist of the [features](#features-and-presets). Turning one
   on turns on what it needs; turning one off turns off what needs it, and says why.
5. **Keep the Mac awake**: `On AC power and on battery` (the default) or `Only on AC
   power`. Asked only when the default features or a linked project have `keep-awake`.
6. **Summary**: what is about to be saved, and `Save this configuration?`. `y` saves it;
   `n` changes nothing.

### What `init` asks

1. **Project name**: filled in from the folder's name. Lowercase letters, digits and
   hyphens, at most 32.
2. **Permission mode**: starts from the default you chose in `setup`.
3. **Features**: start from the default features.
4. **Terminal**: only when the features open tabs and no terminal is set yet.
5. **Summary**: `Link this folder?`, or `Replace its settings?` for a folder already linked
   (`Rename it?` when you changed its name).

The screens are drawn when your terminal can draw them: up and down move, Enter chooses,
Space turns a feature on or off, Esc goes back, `q` quits (Ctrl-C in a text field).
Otherwise they are numbered questions: type the number or the answer and press Enter, `<`
goes back, `q` or Ctrl-C quits. Quitting, or answering no at the summary, changes nothing
(exit code 1).

## Linking and unlinking folders

### `porchlight init [folder]`

- Links the git repository a folder is in. Run it at the top of the repository or in any
  folder inside it: the project is always the repository's top folder. Without `folder`,
  it uses the current one.
- Outside a git repository it refuses and changes nothing:

  ```text
  ~/notes is not in a git repository, and the features need one: run `git init` in it first. Nothing was changed.
  ```

- In a folder that is linked already, it edits that project: the screens start from its
  current values. Its folder stays as it is written in the configuration. A new name
  renames that project; to link another repository, run `init` in that repository's folder
  (or pass it: `porchlight init ~/path/to/repository`).
- After saving, it brings the background agents up to date the way `apply` does: a
  server that is running is left as it is.

Flags answer the screens beforehand, so `init` can run without asking anything:

```sh
porchlight init ~/Projects/shop --name shop --permission-mode plan --preset recommended --terminal warp --yes
```

| Flag | Answers |
| --- | --- |
| `--name <name>` | the project's name |
| `--permission-mode <mode>` | its permission mode; one that `claude --help` lists |
| `--preset <name>` or `--feature <feature>` | its features: a preset, or each feature with its own `--feature`, including the features each one builds on |
| `--terminal warp` or `--terminal apple-terminal` | the terminal, for all projects |
| `--base <branch>` | the branch new worktrees start from (no screen asks for it) |
| `--yes` | every other screen takes the value it starts from, and the summary is confirmed |

Even with `--yes`, a screen that no flag answers and that has no value to start from (no
default permission mode yet, for example) is still asked. With no terminal to ask on, the
command stops with exit code 2 and names the flag, for example
`nothing answered "Permission mode": give --permission-mode`. A list of features that
leaves one out is refused the same way: `argument --feature: "tabs" needs "ready-session"`.

### `porchlight deinit [folder]`

Unlinks the project of a folder: its top folder or any folder inside it. It first prints
everything it is about to do, then:

- removes the project from the configuration;
- ends its free ready session, if one waits;
- unloads and removes its server's background agent, if it has one: **the sessions that
  server started end**;
- unloads and removes the service too when no project is left;
- removes what it kept in its state, once nothing of the project runs, and only in a state
  folder porchlight made (when it says porchlight did not make that folder, it removed
  nothing there).

It leaves as they are: the sessions in use (it says how to reach each), the project's
worktrees, its logs, and the running servers of other projects.

It asks for confirmation only when its server is running sessions, because they end and the
app cannot start them again. Where it cannot ask (no terminal), it refuses unless you give
`--yes`:

```sh
porchlight deinit ~/Projects/shop --yes
```

If the server cannot be unloaded, the project stays in the configuration and the exit code
is 1: run `deinit` again.

### `porchlight setup`

`setup` changes the terminal and the `[defaults]` that new projects start from; linked
projects keep their own values. It takes the same flags as `init`, except `--name` and
`--base`; its `--terminal` also takes `none`, which leaves `terminal` out of the
configuration:

```sh
porchlight setup --terminal warp --permission-mode plan --preset recommended --yes
```

When projects are already linked, it brings their agents up to date afterwards, as `apply`
does.

## How it works

porchlight runs as a service, `porchlight run`, under a login agent: launchd starts it when
you log in and starts it again if it ends. It reads the configuration file, keeps the
sessions of each project running, and follows what happens in them by reading the
transcripts Claude Code writes. Each project with the `server` feature has a login agent of
its own, which runs that project's Remote Control server
(`porchlight server <project> --permission-mode <mode>`) in its repository. porchlight never talks to Claude's servers itself: every session is an
ordinary `claude` process, connected through Remote Control.

```mermaid
flowchart LR
    app["Claude mobile app"]
    rc(["Claude Remote Control"])

    subgraph mac["Your Mac"]
        direction TB
        launchd["launchd<br/>login agents"]
        config[("config.toml")]
        service["porchlight run<br/>the service"]
        tab["Terminal tab"]

        subgraph project["Each project: a git repository"]
            direction TB
            server["Remote Control server<br/>sessions the app creates"]
            ready["Ready session<br/>hidden in tmux"]
            inuse["Session in use"]
            logs[("Session transcripts")]
        end
    end

    app <--> rc
    rc <-- "every session" --> project

    launchd -- "starts at login,<br/>restarts if it ends" --> service
    launchd -- "one agent per project<br/>with the server feature" --> server
    config -- "read on every pass" --> service
    service -- "prepares in its own worktree" --> ready
    ready -- "your first message" --> inuse
    inuse -- "writes" --> logs
    service -- "reads" --> logs
    service -- "opens on first use<br/>ends on archive" --> tab
    tab -- "shows" --> inuse
```

The service works in passes. A pass goes over every project: it keeps one ready session
waiting, opens the tab of a session that is now in use, ends a session the app archived,
tidies what ended, opens the read-only tabs of the server's sessions, updates the
`/resume` copies and removes the worktrees the server's ended sessions left, each only for
the projects that have that feature. A pass comes as soon as
the configuration file or a session's transcript changes, and every 20 seconds otherwise
(the process list cannot be watched). A burst of changes makes one pass.

- One project that fails, or whose folder is missing, is written to its log; the others
  still run.
- A configuration file that stops parsing is reported once in the service's log, and the
  last one that parsed keeps being served until the file is fixed.
- Only one service runs at a time. Sessions and tabs keep running when the service restarts.

### The life of a session

```mermaid
sequenceDiagram
    actor You as You on the phone
    participant Ready as Ready session
    participant P as porchlight
    participant Tab as Terminal tab

    Note over Ready: hidden in tmux, connected to the app
    You->>Ready: first message
    Ready-->>P: the transcript shows a prompt
    P->>Tab: open a tab on the session
    P->>P: prepare the next ready session
    You->>Ready: keep working from the phone or the Mac
    You->>Ready: archive in the app
    Ready-->>P: the transcript shows the archive
    P->>Ready: stop
    Note over Tab: closes with the session
    P->>P: remove the worktree if nothing in it would be lost
    You->>Ready: ask the next ready session to reopen it by name
    Ready->>P: porchlight reopen, with the name
    P->>Tab: resume it in a new tab, back online in the app
```

Each ready session works in its own git worktree, `.claude/worktrees/porchlight-<project>-<id>`
in the repository, on a branch of the same name that starts from the project's base branch.
Two tasks never share files. When a session ends, its worktree is removed (and its branch
deleted) only if it is clean and everything committed in it is on the base branch;
otherwise it is left where it is for you to pick up, and the project's log says why.
Closing a session's tab ends the session; it then counts as closed, and `reopen` brings it
back.

The Remote Control server gives each of its sessions a worktree too,
`.claude/worktrees/bridge-cse_<id>`, and leaves it there when the session ends. For a
project with `server`, porchlight removes such a worktree by the same rule, once no process
runs its session and neither the worktree nor its transcript has changed for 10 minutes:
only when it is clean (nothing changed, nothing untracked) and its HEAD is on the base
branch. Otherwise it is unlocked and left, and the project's log says why. A locked one is
looked at only when Claude Code locked it (its lock reason starts with `claude `) and no
process that reason names still runs; any other lock is left as it is, still locked, and
the log says so. Its branch was made by Claude Code and is never deleted. porchlight checks
each one once after its session ended, and again only when something in it or in the
repository's branches changed, or when the process that held its lock ended; the log says
why a worktree is left only when that reason is new. It touches nothing else of the
server: a folder of another name, one git does not list as a worktree of the repository,
and any case git cannot answer are left as they are.

The base branch is the project's `base`, else the default branch git recorded for the
repository's `origin`, else, for a repository without `origin`, the branch its main
checkout is on. porchlight does not fetch: a new worktree starts from that branch as your
repository knows it.

## Features and presets

| Feature | What you get | Needs |
| --- | --- | --- |
| `server` | The app creates sessions on the Mac, each in its own worktree | Claude Code, git |
| `ready-session` | A session with Claude Code's interface is always ready to write in | Claude Code, git, tmux |
| `tabs` | A terminal tab opens when a session is used and closes when it is archived | `ready-session`, a supported terminal |
| `live-view` | A read-only tab follows a session the server started | `server`, `tabs` |
| `reopen` | A closed session comes back by name, asked from the phone | `ready-session` |
| `resume-list` | The server's sessions appear in `/resume` | `server` |
| `keep-awake` | The Mac stays awake while porchlight runs, on AC power and on battery | nothing |

The presets are `minimal` (`server`) and `recommended` (all seven).

- **`server`**: the app creates sessions in the repository through Claude Code's Remote
  Control server, each in its own worktree, `.claude/worktrees/bridge-cse_<id>`. Once a
  session ended, porchlight removes its worktree if it is clean and its HEAD is on the base
  branch, and leaves it otherwise, saying why in the project's log; a worktree locked by
  anything but an ended Claude Code process is left locked (see
  [How it works](#how-it-works)). The worktree's branch stays.
- **`ready-session`**: the session waits hidden in porchlight's own tmux server
  (`tmux -L porchlight`), apart from any tmux you run. Its name in the app starts with the
  project's session prefix, which is the project's name unless you set `session_prefix`.
  Turning the feature off ends the session that waits; sessions in use are followed until
  they end.
- **`tabs`**: tabs open in the terminal you chose, and only while it is running:
  porchlight never starts it. In Warp each session gets a tab; in Terminal, a window.
  A tab's title is the session prefix and the session's title or first prompt. Without
  `tabs`, a session in use keeps running hidden, and `porchlight status` prints the command
  that shows it in a terminal.
- **`live-view`**: the tab runs `porchlight view <project> <session>`. Nothing typed there
  reaches the session; it closes by itself when the session is archived. A view tab you
  close is not opened again.
- **`reopen`**: each ready session is told, beside its system prompt, how to run
  `porchlight reopen`. Write "reopen" and the session's name in a ready session and it
  reopens that one, in a new tab, back online in the app. On the Mac,
  `porchlight reopen` lists the closed sessions and `porchlight reopen <name>` reopens one
  (by its title, its first prompt, part of either, or its id). The session runs that
  command itself, so its permission mode may ask you first. A closed session is remembered
  for 30 days. In a project without `tabs`, it comes back hidden in tmux.
- **`resume-list`**: Claude Code's `/resume` leaves out the sessions that did not start in a
  terminal, the server's among them. porchlight keeps a copy of each in the session folder
  of the repository's top folder, where `/resume` lists it. A copy is a separate session:
  continuing it in the terminal does not reach the phone. A copy you continued is never
  overwritten; what the phone adds afterwards goes to a new one.
- **`keep-awake`**: while the service runs and any project has this feature, the Mac does
  not go to sleep while idle, on AC power or on battery (`caffeinate -i -s`). The display
  still sleeps. On battery, closing the lid still puts the Mac to sleep: macOS decides
  that, so keep the lid open or the Mac plugged in. On battery it drains the battery
  faster. To keep it awake on AC power only (`caffeinate -s`), choose `Only on AC power`
  in `setup`, or set `keep_awake = "plugged-in"`; the service picks up the change by itself.

## Configuration

One file, written by `setup` and `init` and editable by hand:

```text
~/Library/Application Support/porchlight/config.toml
```

Every command takes `--config <file>` to use another one, and the `PORCHLIGHT_CONFIG`
variable moves the default. A full example:

```toml
terminal = "warp"

[defaults]
permission_mode = "plan"
preset = "recommended"

[projects.shop]
path = "~/Projects/shop"
permission_mode = "manual"
preset = "recommended"
base = "main"
session_prefix = "Shop"

[projects.blog]
path = "~/Projects/blog"
permission_mode = "plan"
features = ["server", "resume-list"]
```

### Top level

| Key | Type | Rules |
| --- | --- | --- |
| `terminal` | text | The app tabs open in: `"warp"` or `"apple-terminal"` (Terminal). Required when any project has `tabs`; left out when `setup` is answered `None`. |
| `keep_awake` | text | Optional. When `keep-awake` holds the Mac awake: `"always"` (the default: on AC power and on battery) or `"plugged-in"` (on AC power only). One setting for the Mac. |
| `[defaults]` | table | Optional. What `init` starts from for a new project. |
| `[projects.<name>]` | table | One per project. |

### `[defaults]`

Each key is optional. Projects do not inherit these values: they only fill in the screens
of `init` for a folder linked from then on.

| Key | Type | Rules |
| --- | --- | --- |
| `permission_mode` | text | One word. |
| `preset` | text | `minimal` or `recommended`. Not together with `features`. |
| `features` | list of text | Feature names, including the features each one builds on. Not together with `preset`. |

### `[projects.<name>]`

The name has lowercase letters, digits and hyphens, starts with a letter or a digit, and is
at most 32 characters long.

| Key | Type | Required | Rules |
| --- | --- | --- | --- |
| `path` | text | yes | The repository's top folder, absolute or starting with `~/`; a relative path is refused, since the agents do not run from your folder. One project per folder. `init` writes the full path. |
| `permission_mode` | text | yes | One word: the mode Claude Code starts each of the project's sessions in. `doctor` checks it against the modes `claude --help` lists. |
| `preset` | text | one of the two | `minimal` or `recommended`. |
| `features` | list of text | one of the two | At least one feature, including the features each one builds on. |
| `base` | text | no | The branch new worktrees start from. Default: see [How it works](#the-life-of-a-session). |
| `session_prefix` | text | no | How ready sessions' names start in the app, and the start of tab titles. Letters, digits and hyphens, at most 32. Default: the project's name. No two projects share one. |

Unknown keys are errors. Every command that reads the file reports each problem by its key
and exits with 1:

```text
The configuration ~/Library/Application Support/porchlight/config.toml has problems:
projects.blog.features: "resume-list" needs "server"
projects.blog.colour: unknown key
terminal: required by "tabs" of the project "shop"
```

### After you edit the file

```sh
porchlight apply
porchlight doctor
```

The service reads the file on every pass, so a change to a project's features takes effect
at its next pass. `apply` is what adds or removes the background agents: run it after you
add or remove a project or its `server` feature. It also installs the session settings of
projects that have no running server. A server that is running keeps the permission mode it
started with until it starts again: see [Running and stopping](#running-and-stopping).

## Commands

Every command takes `--config <file>` (before or after its name) and `-h` or `--help`.
`porchlight --version` prints the version.

| Command | Flags | What it does |
| --- | --- | --- |
| `setup` | `--terminal warp\|apple-terminal\|none`, `--permission-mode <mode>`, `--preset <name>` or `--feature <feature>` (repeated), `--keep-awake always\|plugged-in`, `--yes` | Set up this Mac once: the terminal and what new projects start from. |
| `init [folder]` | as `setup`, plus `--name <name>`, `--base <branch>` | Link a folder's repository as a project, or replace the settings of one already linked. |
| `deinit [folder]` | `--yes` | Unlink a project's folder; sessions in use stay. |
| `status` | | Print the sessions of every project. |
| `reopen [name]` | `--project <name>` | Open a closed session again, back online in the app. Without a name, list the closed ones. |
| `retry` | `--project <name>` | After a free session failed to start, clear the wait before the next try, for every project with `ready-session` or the one named. The service tries at its next pass, within 20 seconds. |
| `doctor` | | Check this Mac (Claude Code signed in, the login agents loaded) and what each project needs on it, and say what to do about what is missing. |
| `view <project> <session>` | | Follow a session the server started (`cse_...`), read-only. What a `live-view` tab runs. |
| `resume-list [sync]` | | List the `/resume` copies of the server's sessions, with the command that resumes each. `sync` brings them up to date first. |
| `apply` | `--servers` | Make the background agents match the configuration. A server that runs is left as it is. |
| `start` | | Load every installed agent that is not loaded. |
| `stop` | `--servers` | Unload the service until `start` or the next login. Sessions already running keep running. |
| `uninstall` | `--servers`, `--purge` | Remove the agents and end the free sessions. Sessions in use keep running. |
| `run` | `--once` | The service itself, what its login agent runs. `--once` makes one pass and exits. |
| `server <project>` | `--permission-mode <mode>` | A project's Remote Control server, what its login agent runs, in the project's permission mode. `--permission-mode` names the mode its agent was written for; when the project's differs, it says so in the server's log. |

You do not need to type `run` or `server`: the login agents run them.

| Exit code | Meaning |
| --- | --- |
| 0 | It did what was asked. |
| 1 | It refused, or something needs attention: for example a check of `doctor` failed, a project's folder is missing in `status`, the configuration has problems, you quit a screen, or a running server was left in place by `uninstall`. |
| 2 | The command line is wrong (including a screen no flag answered when there is no terminal to ask on), or `PORCHLIGHT_LABEL` is not a reverse domain name. |

## Running and stopping

> [!IMPORTANT]
> **A running Remote Control server is never stopped or restarted unless you ask with
> `--servers`.** The sessions a server started run inside it, with no terminal. When the
> server ends they end too, and the Claude app cannot start them again. So `apply`, `stop`,
> `uninstall`, `setup` and `init` leave a running server as it is and say so. `deinit` ends
> only the server of the folder you unlink, and asks first when it has sessions.

| Command | The service | Running servers | Sessions |
| --- | --- | --- | --- |
| `apply` | loaded; restarted when its definition changed; removed when no project is left | left as they are; a server that is not running is loaded | keep running |
| `apply --servers` | the same | restarted when their definition changed; removed when the configuration no longer has them | those of a restarted or removed server end |
| `stop` | unloaded | keep running | keep running |
| `stop --servers` | unloaded | unloaded | those the servers started end |
| `start` | loaded | loaded | nothing changes |

- `stop` leaves the agents' files in place, so `start`, or your next login, loads them
  again.
- `apply` never loads a second server into a folder that a running server already serves.
  After renaming a project, for example, it says that the old name's server still runs
  there; `porchlight apply --servers` replaces it.
- A server's definition is its command, with the project's permission mode, its folder and
  its environment. After you change a project's permission mode, `apply` (and `init`) say
  that the running server was left as it is, though its definition changed: **it keeps the
  mode it started with** until it starts again, and every start takes the configuration's
  mode. To restart it now with the new mode and bring its agent up to date (its sessions
  end):

  ```sh
  porchlight apply --servers
  ```

  Ready sessions use the new mode from the next one prepared.

## Security and privacy

- **Every session is an ordinary `claude` process**, started as you, with your own Claude
  Code configuration and account. Ready sessions run
  `claude --session-id <id> --permission-mode <mode> --settings <file> --append-system-prompt <note> --remote-control-session-name-prefix <prefix> --remote-control`;
  a server runs
  `claude remote-control --spawn worktree --permission-mode <mode> --settings <file> --no-create-session-in-dir`.
- **porchlight never reads Claude Code's credentials and never calls Claude's servers.** It
  makes no network connection of its own. It reads the process list, git, its own files and
  the transcripts Claude Code writes in `~/.claude/projects` for the projects you linked.
  To say whether you are signed in, `doctor` asks `claude auth status` and keeps only its
  yes or no: no account detail is printed or stored.
- **It runs as the person who is logged in and refuses root.** `setup`, `init`, `deinit`,
  `apply`, `start`, `stop`, `uninstall`, `run` and `server` answer `Run this as the person
  who is logged in, without sudo: root has other agents. Nothing was changed.`
- **The permission mode is chosen per project; none is assumed.** It decides what a session
  may do on your Mac without asking first. When you drive sessions from the phone, nobody is
  at the Mac to watch: a mode that lets a session act without asking (`bypassPermissions` is
  the widest) lets it edit files and run commands as you, with your files, your keys and your
  network, while you only see it on the phone. Choose the narrowest mode the project needs.
  Remote Control connects these sessions to your Claude account: whoever can use that account
  in the app can write in them.
- **What porchlight adds to a session**: the settings file it passes holds only the
  permission mode (`{"permissions": {"defaultMode": "<mode>"}}`); every other setting is your
  own. Each ready session gets one note beside its system prompt: that it runs on your Mac
  and is driven from the app and, with `reopen`, the `porchlight reopen` command to run when
  you ask for a closed session.

### Files it writes

| Where | What |
| --- | --- |
| `~/Library/Application Support/porchlight/config.toml` | the configuration |
| `~/Library/Application Support/porchlight/projects/<project>/` | each project's state: `ready-sessions.json`, `view-tabs.json`, `resume-list.json`, `server-worktrees.json`, their locks, and `settings.json` (with `settings.json.next` while a change waits to be installed) |
| `~/Library/Application Support/porchlight/service.lock` | held by the running service |
| `~/Library/Logs/porchlight/` | `<project>.log`, `agent.service.log`, `agent.server.<project>.log` |
| `~/Library/LaunchAgents/` | the login agents' files (below) |
| `<repository>/.claude/worktrees/porchlight-<project>-<id>` | the ready sessions' worktrees, on branches of the same name |
| `~/.claude/projects/<repository's folder>/` | the `/resume` copies (`resume-list`) |
| `~/.warp/tab_configs/` | a tab's configuration, removed once the tab has opened |

The folders porchlight makes for its configuration, state and logs carry a `.porchlight` file; `--purge`
deletes only inside folders that have it. The worktrees of the server's sessions
(`.claude/worktrees/bridge-cse_...`) are made by Claude Code, not by porchlight; porchlight
removes one once its session ended, only when nothing in it would be lost (see
[How it works](#how-it-works)), and never deletes its branch.

### Login agents

| Label | Runs | When |
| --- | --- | --- |
| `io.github.alejandrovdev.porchlight` | `porchlight run` | while the configuration has at least one project |
| `io.github.alejandrovdev.porchlight.server.<project>` | `porchlight server <project> --permission-mode <mode>`, in the project's folder | for each project with `server` |

Both start at login and start again when they end (a server waits 30 seconds between two
starts). Their files carry the `PATH` folders of the tools porchlight found and any
`PORCHLIGHT_*` variable set when they were written.

## Troubleshooting

Start with:

```sh
porchlight doctor
porchlight status
```

`doctor` first checks this Mac: whether Claude Code is signed in (it asks
`claude auth status`, reads only whether someone is, and prints no account detail) and,
once a project is configured, whether the service's login agent is loaded. Then it checks,
for each project, only what its features need: the folder, Claude Code, git, tmux, the
terminal, the git repository, the base branch, the permission mode and, with `server`,
whether the server's login agent is loaded. An agent that is not loaded is fixed with
`porchlight start`; one whose file is missing, with `porchlight apply`. Each line is `ok`,
`missing`, `problem` or `unknown` (what could not be found out), with what to do; the exit
code is 1 when something is `missing` or a `problem`.

```text
This Mac
  ok       Claude Code sign-in
  ok       service agent io.github.alejandrovdev.porchlight

shop
  ok       folder ~/Projects/shop
  ok       Claude Code (claude) at ~/.local/bin/claude
  ok       git at /usr/bin/git
  ok       tmux at /opt/homebrew/bin/tmux
  ok       Warp, the terminal its tabs open in
  ok       git repository
  problem  base branch: none could be determined: set `base` for the project in the configuration
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

### No ready session appears in the app

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
  Remote Control session yet. Check that Claude Code is signed in and that your plan
  includes Remote Control.

### A tab does not open

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

### A closed tab leaves the session listed in the app

- Closing a session's tab ends the session on the Mac, but the app keeps it listed until you
  archive it there: porchlight cannot archive a session from the Mac.
- Unarchiving a session in the app reaches nothing on the Mac. To bring it back, ask a ready
  session to reopen it by name (the `reopen` feature), or run `porchlight reopen <name>` on
  the Mac.

### A session archived in the app keeps running

- porchlight ends only the sessions it started (ready and reopened ones), never a session
  you started yourself, and only while the service runs: it reads the archive in the
  session's transcript and ends the process at its next pass. Check that the service is
  loaded; once it runs again, it ends the session.
- A session the server started ends through the server itself, not through porchlight.

### `/resume` does not list the server's sessions

- The project needs `resume-list` (which needs `server`).
- The copies are kept in the session folder of the repository's top folder: run `claude` in
  that folder, not in a worktree, and use `/resume` there.
- That folder exists only once Claude Code has run a session in the repository's top folder.
  Until then porchlight makes no copy.
- `porchlight resume-list sync` brings the copies up to date and prints, for each one, the
  command that resumes it.

### The Mac sleeps

- Turn on `keep-awake` for a project. It works while the service runs, on AC power and on
  battery unless `setup` set it to `Only on AC power` (`keep_awake = "plugged-in"`); the
  display still sleeps. On battery, closing the lid still puts the Mac to sleep. `pmset -g assertions` lists `caffeinate` while it holds the Mac
  awake.
- While the Mac sleeps, nothing on it runs, so the app cannot reach its sessions.

### A server uses an old permission mode

A running server keeps the mode it started with. Restart it with `porchlight apply --servers`
(its sessions end). See [Running and stopping](#running-and-stopping).

## Uninstall

1. Unlink each folder, if you want to do it project by project:

   ```sh
   cd ~/Projects/shop
   porchlight deinit
   ```

2. Remove the background agents and end the free sessions:

   ```sh
   porchlight uninstall
   ```

   - Sessions in use keep running. With the service gone, archiving one in the app no
     longer ends it on the Mac: close its tab, or end it in its terminal.
   - A server that is running is left running, and the exit code is 1.
     `porchlight uninstall --servers` removes it too: the sessions it started end.
   - The configuration, the state and the logs are kept.
     `porchlight uninstall --purge` removes them too, only the files porchlight wrote, and
     refuses while a session or a server still runs. When it says that porchlight did not
     make a folder, it left that folder whole: look at what is in it and remove it yourself.

   To remove everything at once: `porchlight uninstall --servers --purge`.

3. Remove the command and the tap. Do this after `porchlight uninstall`: the login agents
   run the installed command.

   ```sh
   brew uninstall porchlight
   brew untap alejandrovdev/porchlight
   ```

Left in place: the worktrees in each repository that were not removed (the ready
sessions' and the server's sessions'), their branches, the branches of the server's
sessions, and the `/resume` copies in `~/.claude/projects`.

## Development

```sh
python3 -m unittest discover -s tests -t .
```

The code uses the Python standard library only (Python 3.11 or later). The tests stand in
for processes, folders, tmux, git and the tab opener: they need no network, no Claude
account and no terminal.

The package is built in layers. An atom knows nothing of features; a feature declares what
it needs and does nothing when it is off; presets name sets of features; a project picks a
preset or its own list.

```mermaid
flowchart BT
    atoms["<b>Atoms</b><br/>one job each: processes, transcripts, git worktrees,<br/>tmux, terminal tabs, launchd, state files, logs"]
    features["<b>Features</b><br/>what a project turns on or off"]
    presets["<b>Presets</b><br/>named sets of features"]
    projects["<b>Projects</b><br/>a repository with its preset or its own list"]

    atoms --> features --> presets --> projects
```

| Where | What |
| --- | --- |
| `porchlight/atoms/` | the atoms: processes, transcripts, worktrees, tmux, terminal tabs, launchd, state files, logs, file watching |
| `porchlight/features/` | `server`, `ready_sessions` (`ready-session`, `tabs`, `reopen`), `view_tabs` and `live_view` (`live-view`), `resume_list`, `keep_awake` |
| `porchlight/config.py` | the feature table, the presets and the configuration file |
| `porchlight/passes.py`, `service.py` | one pass over the projects, and the service that runs passes |
| `porchlight/agents.py` | the login agents: `apply`, `start`, `stop`, `uninstall` |
| `porchlight/linking.py`, `answers.py`, `screens.py`, `ui/` | `setup`, `init`, `deinit` and the terminal interface |
| `porchlight/doctor.py`, `cli.py`, `names.py`, `mac.py` | the checks, the command line, every name the tool creates, and the Mac as the features see it |

### A rehearsal apart from a real install

These variables move everything porchlight names, so a rehearsal never touches an installed
copy's files, agents or tmux server:

| Variable | Default |
| --- | --- |
| `PORCHLIGHT_CONFIG` | `~/Library/Application Support/porchlight/config.toml` |
| `PORCHLIGHT_STATE_DIR` | `~/Library/Application Support/porchlight` |
| `PORCHLIGHT_LOG_DIR` | `~/Library/Logs/porchlight` |
| `PORCHLIGHT_LAUNCH_AGENTS_DIR` | `~/Library/LaunchAgents` |
| `PORCHLIGHT_LABEL` | `io.github.alejandrovdev.porchlight`, the start of every label; a reverse domain name |
| `PORCHLIGHT_TMUX_SERVER` | `porchlight`, the tmux socket name |
| `PORCHLIGHT_TRANSCRIPTS_DIR` | `~/.claude/projects`, where transcripts are read |
| `PORCHLIGHT_WARP_TAB_CONFIGS` | `~/.warp/tab_configs`, where a tab's configuration is written |
| `PORCHLIGHT_CLAUDE`, `PORCHLIGHT_GIT`, `PORCHLIGHT_TMUX` | the program found in `PATH` or Homebrew's folders |

```sh
scratch=$(mktemp -d)
export PORCHLIGHT_CONFIG="$scratch/config.toml" PORCHLIGHT_STATE_DIR="$scratch/state" \
  PORCHLIGHT_LOG_DIR="$scratch/logs" PORCHLIGHT_LAUNCH_AGENTS_DIR="$scratch/agents" \
  PORCHLIGHT_LABEL=test.porchlight.rehearsal PORCHLIGHT_TMUX_SERVER=porchlight-rehearsal
python3 -m porchlight doctor
```

Whatever these variables say is handed on to the agents, tabs and sessions porchlight
starts, with folders and files made absolute. The rehearsal is still real where it acts: `init`, `apply` and
`start` load agents into your launchd under the label you chose, and its sessions use your
Claude Code account and the repository you link. End it with
`porchlight uninstall --servers --purge` under the same variables.
