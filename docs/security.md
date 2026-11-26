# Security and privacy

Part of [porchlight](../README.md): what porchlight runs and reads, what it adds to a
session, the files it writes and its login agents. To report a vulnerability, follow
[the security policy](../SECURITY.md).

## What it runs and reads

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
  network, while you only see it on the phone. What the session reads (a file in the
  repository, a web page, a command's output) can steer it too, and nobody at the Mac would
  see it happen. Choose the narrowest mode the project needs. Remote Control connects these
  sessions to your Claude account: whoever can use that account in the app can write in
  them.
- **Its tmux server lets a session reach your terminal and clipboard**, as Claude Code asks
  of tmux: a program in a session can set the clipboard and send codes to the terminal it is
  shown in (`set-clipboard` and `allow-passthrough` in its tmux configuration).
- **What porchlight adds to a session**: the settings file it passes holds only the
  permission mode (`{"permissions": {"defaultMode": "<mode>"}}`); every other setting is your
  own. Each ready session gets one note beside its system prompt: that it runs on your Mac
  and is driven from the app and, with `reopen`, the `porchlight reopen` command to run when
  you ask for a closed session.

## Files it writes

The logs keep sessions' titles and first prompts, and the server's logs its Remote Control
link; they are not rotated. They sit under `~/Library`, which only you can open; if a
`PORCHLIGHT_*_DIR` variable moves them, choose a folder others cannot read.

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
[How porchlight works](how-it-works.md#the-life-of-a-session)), and deletes its branch
only when every commit of it is already on the base branch.

## Login agents

| Label | Runs | When |
| --- | --- | --- |
| `io.github.alejandrovdev.porchlight` | `porchlight run` | while the configuration has at least one project |
| `io.github.alejandrovdev.porchlight.server.<project>` | `porchlight server <project> --permission-mode <mode>`, in the project's folder | for each project with `server` |

Both start at login and start again when they end (a server waits 30 seconds between two
starts). Their files carry the `PATH` folders of the tools porchlight found and any
`PORCHLIGHT_*` variable set when they were written.
