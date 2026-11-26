# Security policy

porchlight runs Claude Code sessions on your Mac and lets text typed on your phone reach
them, so a flaw in it can matter. Thank you for reporting one privately.

## Reporting a vulnerability

Use GitHub's private reporting: on the repository's **Security** tab, choose **Report a
vulnerability**. Please include the version (`porchlight --version`), what an attacker
controls (a message typed in the app, a folder or branch name, the configuration), what
they gain, and the steps to reproduce it.

Please do not open a public issue for a vulnerability. You can expect an answer within a
week, and a fix released as soon as it is ready; the changelog credits you unless you ask
otherwise.

## Supported versions

Only the latest release gets security fixes. Upgrade with `brew upgrade porchlight`.

## What porchlight itself guards

What porchlight writes, what it runs and how a session's permission mode reaches Claude
Code are described in [Security and privacy](docs/security.md). Choosing a
session's permission mode, and what Claude Code may do under it, is up to you.
