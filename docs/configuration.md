# Configuration

Part of [porchlight](../README.md): the configuration file, its keys, and the environment
variables.

## The file

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

## Top level

| Key | Type | Rules |
| --- | --- | --- |
| `terminal` | text | The app tabs open in: `"warp"` or `"apple-terminal"` (Terminal). Required when any project has `tabs`; left out when `setup` is answered `None`. |
| `keep_awake` | text | Optional. When `keep-awake` holds the Mac awake: `"always"` (the default: on AC power and on battery) or `"plugged-in"` (on AC power only). One setting for the Mac. |
| `[defaults]` | table | Optional. What `init` starts from for a new project. |
| `[projects.<name>]` | table | One per project. |

## `[defaults]`

Each key is optional. Projects do not inherit these values: they only fill in the screens
of `init` for a folder linked from then on.

| Key | Type | Rules |
| --- | --- | --- |
| `permission_mode` | text | One word. |
| `preset` | text | `minimal` or `recommended`. Not together with `features`. |
| `features` | list of text | Feature names, including the features each one builds on. Not together with `preset`. |

## `[projects.<name>]`

The name has lowercase letters, digits and hyphens, starts with a letter or a digit, and is
at most 32 characters long.

| Key | Type | Required | Rules |
| --- | --- | --- | --- |
| `path` | text | yes | The repository's top folder, absolute or starting with `~/`; a relative path is refused, since the agents do not run from your folder. One project per folder. `init` writes the full path. |
| `permission_mode` | text | yes | One word: the mode Claude Code starts each of the project's sessions in. `doctor` checks it against the modes `claude --help` lists. |
| `preset` | text | one of the two | `minimal` or `recommended`. |
| `features` | list of text | one of the two | At least one feature, including the features each one builds on. |
| `base` | text | no | The branch new worktrees start from; it cannot start with `-`. Default: see [How it works](how-it-works.md#the-life-of-a-session). |
| `session_prefix` | text | no | How ready sessions' names start in the app, and the start of tab titles. Letters, digits and hyphens, at most 32. Default: the project's name. No two projects share one. |

Unknown keys are errors. Every command that reads the file reports each problem by its key
and exits with 1:

```text
The configuration ~/Library/Application Support/porchlight/config.toml has problems:
projects.notes.features: "resume-list" needs "server"
projects.notes.colour: unknown key
terminal: required by "tabs" of the project "shop"
```

## After you edit the file

```sh
porchlight apply
porchlight doctor
```

The service reads the file on every pass, so a change to a project's features takes effect
at its next pass. `apply` is what adds or removes the background agents: run it after you
add or remove a project or its `server` feature. It also installs the session settings of
projects that have no running server. A server that is running keeps the permission mode it
started with until it starts again: see [Running and stopping](commands.md#running-and-stopping).

## Environment variables

These variables move what porchlight names. Whatever they say is handed on to the agents,
tabs and sessions porchlight starts, with folders and files made absolute.

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

Keep `PORCHLIGHT_TRANSCRIPTS_DIR` at its default, or porchlight cannot find Claude Code's
transcripts.
