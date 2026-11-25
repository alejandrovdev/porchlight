# Contributing to porchlight

Thank you for helping. porchlight is small on purpose: the Python standard library only, a
macOS tool installed with Homebrew, and behavior a person can predict from the README.

## Before you write code

- For a bug, open an issue with the bug report template: `porchlight --version`, and the
  output of `porchlight doctor` and `porchlight status`, say most of what is needed.
- For a new feature or a change of behavior, open an issue first and describe the problem
  it solves for someone driving sessions from the phone.
- Security problems go through [SECURITY.md](SECURITY.md), not public issues.

## Working on the code

```sh
git clone https://github.com/alejandrovdev/porchlight.git
cd porchlight
python3 -m unittest discover -s tests -t .
python3 -m porchlight --help
```

Python 3.11 or later, nothing to install. The tests stand in for processes, folders, tmux,
git and the tab opener: they need no network, no Claude account and no terminal of yours,
and they run in a few seconds, apart from `tests/test_terminal.py`, which runs `setup` in a
pseudo-terminal it makes (its screens, keys, colors and resizes) and takes about ten.

To try a change against the real Mac without touching an install you use, follow
[A rehearsal apart from a real install](README.md#a-rehearsal-apart-from-a-real-install).

The package is built in layers (see [Development](README.md#development)): an atom knows
nothing of features, and a feature declares what it needs and does nothing when it is off.
Keep a new piece in the lowest layer that can hold it.

## How a change is made

- **Test first.** Write the test that shows the problem or the new rule, see it fail, then
  make it pass. Test through the public functions and assert every observable effect:
  output, exit code, files written.
- **Keep what exists.** A change that touches a command or option others use keeps a test
  proving its old behavior still holds.
- **Docs travel with the code.** A new command, option, message or configuration key
  updates the help text, the README or `docs/`, and the `Unreleased` section of
  [CHANGELOG.md](CHANGELOG.md).
- **No dependencies.** Only the standard library, so Homebrew installs porchlight with its
  Python and nothing else.

## Commits and pull requests

- Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `feat(doctor): ...`,
  `fix(server): ...`, `docs: ...`, written in English, in the imperative, saying what changes
  for the person using porchlight.
- One pull request per unit of behavior, with its tests and docs. Over about 400 changed
  lines, split it into pull requests that build on each other.
- Continuous integration runs the tests on macOS with Python 3.11 and 3.15; both must pass.
  On 3.15 it also measures which lines the tests run, with the standard library's `trace`,
  lists the least covered modules, and fails under 90 percent.

## Compatibility

From 1.0.0 the interface in [Compatibility](README.md#compatibility) changes only in a major
release. A pull request that would break it says so in its title and in the changelog.

By contributing you agree that your contribution is licensed under the
[MIT License](LICENSE).
