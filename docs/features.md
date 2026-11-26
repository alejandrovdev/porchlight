# Features

Part of [porchlight](../README.md): what each feature does, in detail. The [table in the
README](../README.md#features-and-presets) says what each one needs.

## `server`

The app creates sessions in the repository through Claude Code's Remote Control server, each
in its own worktree, `.claude/worktrees/bridge-cse_<id>`. Once a session ended, porchlight
removes its worktree if it is clean, its HEAD is on the base branch and no file
`.worktreeinclude` lists was changed in it, and leaves it otherwise, saying why in the
project's log; a worktree locked by anything but an ended Claude Code process is left locked
(see [How porchlight works](how-it-works.md#the-life-of-a-session)). The worktree's branch
is deleted with `git branch -d` only when every commit of it is on the base branch.

## `ready-session`

The session waits hidden in porchlight's own tmux server (`tmux -L porchlight`), apart from
any tmux you run. Its name in the app starts with the project's session prefix, which is the
project's name unless you set `session_prefix`. Turning the feature off ends the session
that waits; sessions in use are followed until they end.

## `tabs`

Tabs open in the terminal you chose, and only while it is running: porchlight never starts
it. In Warp each session gets a tab; in Terminal, a window. A tab's title is the session
prefix and the session's title or first prompt; a Terminal window shows instead the title
the shell or the program sets (oh-my-zsh, Claude Code, tmux), as Terminal does for any
window. Without `tabs`, a session in use keeps running hidden, and `porchlight status`
prints the command that shows it in a terminal.

## `live-view`

The tab runs `porchlight view <project> <session>`. Nothing typed there reaches the session;
it closes by itself when the session is archived. A view tab you close is not opened again.

## `reopen`

Each ready session is told, beside its system prompt, how to run `porchlight reopen`. Write
"reopen" and the session's name in a ready session and it reopens that one, in a new tab,
back online in the app. On the Mac, `porchlight reopen` lists the closed sessions and
`porchlight reopen <name>` reopens one (by its title, its first prompt, part of either, or
its id). The session runs that command itself, so its permission mode may ask you first. A
closed session is remembered for 30 days. In a project without `tabs`, it comes back hidden
in tmux.

## `resume-list`

Claude Code's `/resume` leaves out the sessions that did not start in a terminal, the
server's among them. porchlight keeps a copy of each in the session folder of the
repository's top folder, where `/resume` lists it. A copy is a separate session: continuing
it in the terminal does not reach the phone. A copy you continued is never overwritten; what
the phone adds afterwards goes to a new one.

## `keep-awake`

While the service runs and any project has this feature, the Mac does not go to sleep while
idle, on AC power or on battery (`caffeinate -i -s`). The display still sleeps. On battery,
closing the lid still puts the Mac to sleep: macOS decides that, so keep the lid open or the
Mac plugged in. On battery it drains the battery faster. To keep it awake on AC power only
(`caffeinate -s`), choose `Only on AC power` in `setup`, or set `keep_awake = "plugged-in"`;
the service picks up the change by itself.
