# CLAUDE.md

Guidance for Claude Code working in this repository.

## Status

This repository is currently empty — no application code, tests, or build
tooling yet. The files here are the Claude Code configuration scaffold. When
real code lands, update the sections below (or re-run `/init`) so this file
describes the actual project rather than the scaffold.

## Repository layout

```
.claude/
  settings.json        Permissions, hooks (checked in, shared with the team)
  settings.local.json  Personal overrides (gitignored, never commit)
  hooks/
    session-start.sh   Dependency bootstrap, runs at session start
CLAUDE.md              This file
```

## Session bootstrap

`.claude/hooks/session-start.sh` runs on every Claude Code on the web session
before the session begins. It detects a dependency manifest (`package.json`,
`pyproject.toml`, `uv.lock`, `requirements.txt`, `Cargo.toml`, `go.mod`,
`Gemfile`) and installs from it. With no manifest present it prints a notice
and exits 0.

It exits immediately outside a remote session (`CLAUDE_CODE_REMOTE != true`),
so it never touches a local dev environment.

To test it by hand:

```bash
CLAUDE_CODE_REMOTE=true ./.claude/hooks/session-start.sh
```

The hook is synchronous: the session waits for it. That guarantees
dependencies exist before any test or lint command runs, at the cost of slower
session startup. To trade that guarantee for speed, make it async by adding
`echo '{"async": true, "asyncTimeout": 300000}'` as the first statement after
`set -euo pipefail`.

Adding a new language to the project means adding its install branch to the
hook — one `if [ -f <manifest> ]` block alongside the existing ones.

## Commands

No build, test, or lint commands exist yet. Record them here as they are
added, so sessions do not have to rediscover them:

```
Build:   (none yet)
Test:    (none yet)
Lint:    (none yet)
```

## Conventions

- Work on a feature branch; do not commit directly to the default branch.
- Keep `.claude/settings.json` in version control — it is shared configuration.
  Personal tweaks belong in `.claude/settings.local.json`, which is gitignored.
- Secrets stay out of the repo. `.env` files and key material are denied to
  Claude by `permissions.deny` in `.claude/settings.json` and ignored by git;
  a deny rule is a guardrail, not a reason to put a secret in the tree.
