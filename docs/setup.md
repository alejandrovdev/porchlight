# Setting up porchlight

Part of [porchlight](../README.md): what `setup` and `init` ask, the flags that answer them
beforehand, unlinking a folder, upgrading, and removing porchlight.

## What `setup` asks

1. **Prerequisites**: Claude Code, git, tmux and each supported terminal app, each marked
   `ok` or `missing` with what to do about it. Nothing is installed from here. When Homebrew
   is there and something it installs is missing (Claude Code, git, tmux or Warp), the
   screen ends with a warning: the next screen can install them, which downloads software
   from the internet, a cask may ask for your password, and Claude Code still needs you to
   sign in by running `claude`.
   - **Install what is missing**: asked only then. `Install with Homebrew` lists the
     `brew install` commands it runs; `Skip` (where it starts) leaves them to you
     (`porchlight doctor` lists them). Nothing is installed yet: the summary lists the
     installs, and they run only after you answer `y` there, before the configuration is
     saved, each with Homebrew's own output. A failed install is said, the others go on,
     and `setup` exits with 1.
2. **Terminal**: the app tabs open in (Warp, or Terminal), marked installed or not
   installed, or `None`: no tab opens and sessions run hidden. `None` is offered only while
   no linked project has `tabs`; a project linked later with `tabs` asks for a terminal.
3. **Default permission mode**: one of the modes your installed `claude --help` lists. When
   they cannot be read, you type one.
4. **Default features**: a checklist of the [features](features.md). Turning one
   on turns on what it needs; turning one off turns off what needs it, and says why.
5. **Keep the Mac awake**: `On AC power and on battery` (the default) or `Only on AC
   power`. Asked only when the default features or a linked project have `keep-awake`.
6. **Summary**: what is about to be saved, and `Save this configuration?`. `y` saves it;
   `n` changes nothing.

## What `init` asks

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

In a terminal with 256 colors and UTF-8 that is at least 80 columns by 24 rows, every step
is a whole screen: a status bar with a progress bar, the name in large pixels, the steps,
the options in a panel with a bar under the cursor, and a panel about the option the
cursor is on (what it does, what it needs and what needs it). From 112 columns by 32 rows
an old porch lantern moves beside them and your answers so far are listed under the name.
A smaller terminal gets plain lines: the title, the keys and the options. With fewer
colors only the title and errors are colored. Set `NO_COLOR` to any value to draw plain
lines without colors.

## Setting up this Mac

`setup` changes the terminal and the `[defaults]` that new projects start from; linked
projects keep their own values. It takes the same flags as `init`, except `--name` and
`--base`, and also `--keep-awake always|plugged-in` and `--install-missing`; its
`--terminal` also takes `none`, which leaves `terminal` out of the configuration:

```sh
porchlight setup --terminal warp --permission-mode plan --preset recommended --yes
```

`--yes` alone installs nothing. Add `--install-missing` to install what is missing with
Homebrew, as the **Install what is missing** screen does:

```sh
porchlight setup --terminal warp --permission-mode plan --install-missing --yes
```

When nothing is missing it says so. When something is missing but Homebrew is not found,
it says that nothing was installed and why, saves the rest, and exits with 1.

When projects are already linked, it brings their agents up to date afterwards, as `apply`
does.

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
- ends its free ready session, if one waits, and removes its worktree when nothing in it
  would be lost;
- unloads and removes its server's background agent, if it has one: **the sessions that
  server started end**;
- unloads and removes the service too when no project is left;
- removes what it kept in its state, once nothing of the project runs, and only in a state
  folder porchlight made (when it says porchlight did not make that folder, it removed
  nothing there).

It leaves as they are: the sessions in use (it says how to reach each), the worktrees of
those sessions, its logs, and the running servers of other projects. The waiting session
ends, and its worktree is removed when nothing in it would be lost.

It asks for confirmation only when its server is running sessions, because they end and the
app cannot start them again. Where it cannot ask (no terminal), it refuses unless you give
`--yes`:

```sh
porchlight deinit ~/Projects/shop --yes
```

If the server cannot be unloaded, the project stays in the configuration and the exit code
is 1: run `deinit` again.

## Upgrade

```sh
brew update
HOMEBREW_NO_INSTALL_CLEANUP=1 brew upgrade alejandrovdev/porchlight/porchlight
porchlight stop
porchlight start
porchlight doctor
brew cleanup porchlight
```

1. `brew upgrade` installs the new version. Homebrew would remove the old one right away,
   but the service keeps running the old one, and the files that come with it, until it
   starts again: `HOMEBREW_NO_INSTALL_CLEANUP=1` keeps it until then.
2. `stop` and `start` restart the service alone, on the new version. The sessions keep
   running: the ready ones wait in tmux, and the ones in use keep their tabs.
   `porchlight --version` says which version is installed.
3. A running Remote Control server is left as it is, with its sessions: it runs Claude Code,
   which the upgrade does not change, and takes up the new version the next time it starts.
   To restart it now, `porchlight stop --servers` and then `porchlight start`; the sessions
   it started end (see [Running and stopping](commands.md#running-and-stopping)).
4. `brew cleanup porchlight` removes the old version once the service runs the new one.

The [changelog](../CHANGELOG.md) says what each release brings and, for a major release, how
to move.

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
     `porchlight uninstall --purge` removes them too (the logs of projects no longer linked
     included), only the files porchlight wrote, and
     refuses while a session or a server still runs. When it says that porchlight did not
     make a folder, it left that folder whole: look at what is in it and remove it yourself.

   To remove everything at once, once no session runs (close the tabs of the sessions you
   use first): `porchlight uninstall --servers --purge`.

3. Remove the command and the tap. Do this after `porchlight uninstall`: the login agents
   run the installed command.

   ```sh
   brew uninstall porchlight
   brew untap alejandrovdev/porchlight
   ```

Left in place: the worktrees in each repository that were not removed (the ready
sessions' and the server's sessions'), their branches, the branches of the server's
sessions, and the `/resume` copies in `~/.claude/projects`.
