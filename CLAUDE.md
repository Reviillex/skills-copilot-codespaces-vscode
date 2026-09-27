# CLAUDE.md

Guidance for Claude Code working in this repository.

## Status

Python CLI (`carousel`) that turns one PubMed paper into a source-checked
Indonesian Instagram carousel. See README.md for the workflow and the accuracy
guards. Nothing is posted automatically; a doctor reviews every draft.

## Repository layout

```
.claude/
  settings.json        Permissions, hooks (checked in, shared with the team)
  settings.local.json  Personal overrides (gitignored, never commit)
  hooks/
    session-start.sh   Dependency bootstrap, runs at session start
src/carousel/
  cli.py               Commands: discover, draft, check, review, render, sample
  pubmed.py            NCBI E-utilities search/fetch + XML parsing
  llm.py               Claude draft + fact-check calls (structured output)
  schema.py            Pydantic output schemas
  checks.py            Deterministic checks (verbatim quotes, sourced numbers)
  render.py            Jinja2 + Playwright -> 1080x1350 PNGs
  prompts/, templates/, sample/
tests/                 Offline pytest suite (fixtures are synthetic)
carousel.toml          User settings (brand, writing limits, PubMed filters)
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

```
Install: pip install -e '.[dev]' && playwright install chromium
Test:    python3 -m pytest -q
Demo:    carousel sample          (no API key needed)
Lint:    (none yet)
```

In Claude Code on the web, Chromium lives at `/opt/pw-browsers/chromium`; set
`CAROUSEL_CHROMIUM=/opt/pw-browsers/chromium` so the render test runs instead of
skipping. NCBI E-utilities is blocked by the web sandbox proxy, so PubMed calls
can only be tested against the fixtures there.

## Conventions

- Work on a feature branch; do not commit directly to the default branch.
- Keep `.claude/settings.json` in version control — it is shared configuration.
  Personal tweaks belong in `.claude/settings.local.json`, which is gitignored.
- Secrets stay out of the repo. `.env` files and key material are denied to
  Claude by `permissions.deny` in `.claude/settings.json` and ignored by git;
  a deny rule is a guardrail, not a reason to put a secret in the tree.
