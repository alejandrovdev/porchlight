# porchlight

Leave a light on for your phone: porchlight keeps Claude Code sessions ready on your Mac so
you can start, follow and close them from the Claude mobile app.

> **Status: in development.** Nothing here is ready to install yet.

## What it will do

- Keep a session with Claude Code's own interface always ready. Write in it from the app and
  work starts; another one is prepared for the next task.
- Open a terminal tab on a session when you start using it, and close the tab when you
  archive the session in the app.
- Bring a closed session back by name, asked from the phone.
- Let the app create sessions on the Mac, each in its own git worktree.
- Serve one project or several, each with only the features you turn on.

## Requirements

- A Mac with [Homebrew](https://brew.sh).
- Claude Code, signed in with a plan that includes Remote Control, and the Claude mobile
  app.
- git, tmux and Python 3.11 or later (Homebrew installs them).

## Development

```sh
python3 -m unittest discover -s tests -t .
```

The code uses the Python standard library only. Tests need no network, no Claude account
and no terminal.
