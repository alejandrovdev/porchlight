# Commands

Part of [porchlight](../README.md): every command and its flags, the exit codes, how to read
`status`, and what starts and stops the background agents.

## Every command

Every command takes `--config <file>` (before or after its name) and `-h` or `--help`.
`porchlight --version` prints the version.

| Command | Flags | What it does |
| --- | --- | --- |
| `setup` | `--terminal warp\|apple-terminal\|none`, `--permission-mode <mode>`, `--preset <name>` or `--feature <feature>` (repeated), `--keep-awake always\|plugged-in`, `--install-missing`, `--yes` | Set up this Mac once: the terminal and what new projects start from. |
| `init [folder]` | `--terminal warp\|apple-terminal`, `--permission-mode <mode>`, `--preset <name>` or `--feature <feature>` (repeated), `--name <name>`, `--base <branch>`, `--yes` | Link a folder's repository as a project, or replace the settings of one already linked. |
| `deinit [folder]` | `--yes` | Unlink a project's folder; sessions in use stay. |
| `status` | | Print the sessions of every project. |
| `reopen [name]` | `--project <name>` | Open a closed session again, back online in the app. Without a name, list the closed ones. |
| `retry` | `--project <name>` | After a free session failed to start, clear the wait before the next try, for every project with `ready-session` or the one named. The service tries at its next pass, within 20 seconds. |
| `doctor` | | Check this Mac (Claude Code signed in and recent enough, the login agents loaded) and what each project needs on it, and say what to do about what is missing. |
| `view <project> <session>` | | Follow a session the server started (`cse_...`), read-only. What a `live-view` tab runs. |
| `resume-list [sync]` | | List the `/resume` copies of the server's sessions, with the command that resumes each. `sync` brings them up to date first. |
| `apply` | `--servers` | Make the background agents match the configuration. A server that runs is left as it is. |
| `start` | | Load every installed agent that is not loaded. |
| `stop` | `--servers` | Unload the service until `start` or the next login. Sessions already running keep running. |
| `uninstall` | `--servers`, `--purge` | Remove the agents and end the free sessions. Sessions in use keep running. |
| `run` | `--once` | The service itself, what its login agent runs. `--once` makes one pass and exits. |
| `server <project>` | `--permission-mode <mode>` | A project's Remote Control server, what its login agent runs, in the project's permission mode. `--permission-mode` names the mode its agent was written for; when the project's differs, it says so in the server's log. |

You do not need to type `run` or `server`: the login agents run them.

## Exit codes

| Exit code | Meaning |
| --- | --- |
| 0 | It did what was asked. |
| 1 | It refused, or something needs attention: for example a check of `doctor` failed, a project's folder is missing in `status`, the configuration has problems, you quit a screen, or a running server was left in place by `uninstall`. |
| 2 | The command line is wrong (including a screen no flag answered when there is no terminal to ask on), or `PORCHLIGHT_LABEL` is not a reverse domain name. |

## Reading `status`

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

Each line is one session: its short id; its state (`free` waits for you, `used` is one
you wrote in, `closed` ended and `porchlight reopen` brings it back); when it last
changed; its name in the app; and where it runs: the process id and its Remote Control
session (`not in the app yet` until the app has it), plus `hidden` while it has no tab,
or `not running`. A free session always waits hidden; a session in use gets a tab, unless
its tab failed three times. When no tab will open for a running session (the project has
no `tabs`, or its tab was given up on), `status` prints below it the command that
attaches to it, for a free session too.

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
