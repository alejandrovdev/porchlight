# ![porchlight](docs/images/header.png)

Leave a light on for your phone: porchlight keeps Claude Code sessions ready on your Mac so
you can start, follow and close them from the Claude mobile app.

> **Status: stable.** From 1.0.0, what [Compatibility](#compatibility) lists changes only
> in a major release; the [changelog](CHANGELOG.md) says what each release brings.

![porchlight setup: the lantern, the steps, the features panel and the details of the option under the cursor](docs/images/setup.png)

Contents: [The problem it solves](#the-problem-it-solves) · [Requirements](#requirements) ·
[Install](#install) · [Quick start](#quick-start) · [Features and presets](#features-and-presets) ·
[Documentation](#documentation) · [Compatibility](#compatibility) ·
[Contributing](#contributing) · [License](#license)

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
- Claude Code 2.1.92 or later (2.1.327 or later recommended: it stops a server without
  touching its sessions' ignored files), with `claude` in your `PATH` and signed in with a
  claude.ai account whose plan includes Remote Control: Pro, Max, Ultra, Team or Enterprise
  (on Team and Enterprise an owner turns it on first). When it is missing, `setup` can
  install it with Homebrew; you sign in by running `claude` once.
- The Claude mobile app, signed in to the same account.
- git: the one in Apple's Command Line Tools or Homebrew's.
- tmux and Python 3.11 or later: the Homebrew formula installs both.
- For the features that open tabs (`tabs` and `live-view`): [Warp](https://www.warp.dev), or
  Terminal, the app macOS comes with.

> [!NOTE]
> Remote Control does not work with an API key: with `ANTHROPIC_API_KEY`, `apiKeyHelper` or
> `ANTHROPIC_AUTH_TOKEN` set, it stays off.

## Install

```sh
brew install alejandrovdev/porchlight/porchlight
porchlight --version
```

The tap is `alejandrovdev/porchlight`. Installing adds the `porchlight` command; nothing
runs in the background until you link a folder with `porchlight init`. To move to a new
release, follow [Upgrade](docs/setup.md#upgrade): the service needs a restart.

## Quick start

1. Set up this Mac once:

   ```sh
   porchlight setup
   ```

   Keep the recommended features it starts with: the next steps need `ready-session` and
   `tabs`. Its screens, and the flags that answer them beforehand, are in
   [Setting up porchlight](docs/setup.md).

2. Link a project. Claude Code asks once per folder whether you trust it, and a ready
   session cannot answer that from the phone: if you have never run `claude` in this
   repository, do it once and choose "Yes, I trust this folder". Then, in its folder (a git
   repository), run `init`:

   ```sh
   cd ~/Projects/shop
   porchlight init
   ```

   Then run `porchlight doctor`: each line should say `ok`. The service looks at every
   project every 20 seconds, so the ready session follows within about half a minute.

3. **On the phone**, open the Claude app and tap **Code**. The ready session is in the
   session list, with a computer icon and a green dot while it is online; its name starts
   with the project's name (`shop`). Write in it and work starts.
4. **On the Mac**, with your terminal running, a tab opens on that session soon after your
   first message, and porchlight prepares the next ready session. Archiving the session in
   the app ends it and closes its tab (in Terminal, when its profile closes windows: see
   [A tab does not open](docs/troubleshooting.md#a-tab-does-not-open)).
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

   Each line is one session: its id, its state (`free`, `used` or `closed`), when it last
   changed, its name in the app and where it runs.
   [Reading `status`](docs/commands.md#reading-status) says what each part means.

With the `server` feature on, you can also create new sessions on this Mac from the app.

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

[Features](docs/features.md) says what each one does in detail.

## Documentation

| Page | What it covers |
| --- | --- |
| [Setting up porchlight](docs/setup.md) | What `setup` and `init` ask and the flags that answer them, unlinking a folder, upgrading, and uninstalling. |
| [Features](docs/features.md) | What each feature does, in detail. |
| [Configuration](docs/configuration.md) | The configuration file, its keys, what to run after you edit it, and the environment variables. |
| [Commands](docs/commands.md) | Every command, its flags and exit codes, how to read `status`, and what starts and stops the background agents. |
| [How porchlight works](docs/how-it-works.md) | What runs on your Mac, the life of a session, and where its work goes. |
| [Security and privacy](docs/security.md) | What porchlight runs and reads, what it adds to a session, the files it writes and its login agents. |
| [Troubleshooting](docs/troubleshooting.md) | What `doctor`, `status` and the logs tell you, and the common problems with their fixes. |

When something does not work, start with `porchlight doctor`: it checks this Mac and what
each project needs, and says what to do about each problem.

## Compatibility

From 1.0.0, porchlight follows [Semantic Versioning](https://semver.org): a minor or patch
release keeps working with whatever you built on the following, and only a major release
changes them, with the changelog saying how to move:

- the [commands](docs/commands.md), their options and what they do, and the exit codes: 0
  when a command did what was asked, 1 when it refused or something needs attention, 2 when
  the command line is wrong;
- the [configuration file](docs/configuration.md): where it is, its keys and what they mean
  (a minor release may add an optional key);
- the [files and folders porchlight writes](docs/security.md#files-it-writes), and the labels
  of its [login agents](docs/security.md#login-agents);
- the `PORCHLIGHT_*` environment variables that
  [Configuration](docs/configuration.md#environment-variables) lists.

Not part of it: `porchlight run` and `porchlight server`, which the login agents call; the
wording and layout of what the commands print and of the logs (read them, do not parse
them); and the look of the setup screens.

## Contributing

Bug reports and pull requests are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md). Report a
vulnerability privately, as [SECURITY.md](SECURITY.md) says.

## License

porchlight is released under the [MIT License](LICENSE).
