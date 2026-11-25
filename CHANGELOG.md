# Changelog

Each release of porchlight, newest first. Versions follow `MAJOR.MINOR.PATCH`; while the
major version is 0, a minor release may change commands or the configuration file.

## [Unreleased]

## [0.1.4] - 2026-11-25

### Added

- `setup`, `init` and `deinit` draw each step as a whole screen in a terminal with 256
  colors and UTF-8: a status bar with a progress bar, the name in large pixels, the steps,
  options in a panel with a bar under the cursor, and a panel about the option the cursor
  is on. From 112 by 32 an animated porch lantern and the answers so far join them.
- `setup` offers to install missing prerequisites (Claude Code, git, tmux, Warp) with
  Homebrew, after a warning; they are installed only after the summary is confirmed.
  `--install-missing` answers that screen.
- Terminal.app as a second terminal for tabs, and `None` for a Mac where no tab opens.
- `doctor` checks Claude Code's sign-in and the login agents.
- `retry` clears a free session's back-off; `status` shows it.
- The server's ended sessions have their worktrees removed.

### Fixed

- `status` shows ready sessions only for projects that have them, and how to attach to a
  session whose tab was given up on.
- A relative project path is refused.
- After `uninstall`, `--purge` no longer advises archiving sessions in the app.
- Locked worktrees of the server's sessions are left alone, with the reason logged once.

## [0.1.3] - 2026-11-25

### Added

- `setup` asks whether keep-awake holds on battery too (`--keep-awake always|plugged-in`).

## [0.1.2] - 2026-11-25

### Fixed

- A server runs in the configuration's permission mode at every start, and
  `apply --servers` restarts a server whose mode changed.

## [0.1.1] - 2026-11-25

### Added

- `init` says when a new name renames a linked project.

### Fixed

- Keep-awake also keeps the Mac from idle sleep on battery.

## [0.1.0] - 2026-11-24

First release: a session always ready for the Claude mobile app, terminal tabs that open
and close with the phone's sessions, closed sessions reopened by name, the Remote Control
server's sessions followed and listed in `/resume`, keep-awake, and `setup`, `init`,
`deinit`, `apply`, `status`, `doctor`, `reopen`, `view`, `start`, `stop` and `uninstall`.

[Unreleased]: https://github.com/alejandrovdev/porchlight/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/alejandrovdev/porchlight/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/alejandrovdev/porchlight/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/alejandrovdev/porchlight/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/alejandrovdev/porchlight/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/alejandrovdev/porchlight/releases/tag/v0.1.0
