#!/bin/bash
# SessionStart hook: install project dependencies so tests and linters are
# runnable the moment a Claude Code on the web session starts.
#
# Runs synchronously, so the session does not begin until this finishes.
# Every branch is idempotent and non-interactive; the whole script no-ops
# cleanly when a manifest is absent, which is what happens today because the
# repository has no project code yet. Add code and the matching branch starts
# doing real work with no edit here.
set -euo pipefail

# Local runs (your own machine) already have a dev environment; only bootstrap
# the ephemeral remote container.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  echo "session-start: not a remote session, skipping bootstrap"
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"

installed=0

# --- Node -------------------------------------------------------------------
if [ -f package.json ]; then
  installed=1
  if [ -f pnpm-lock.yaml ] && command -v pnpm >/dev/null; then
    echo "session-start: pnpm install"
    pnpm install
  elif [ -f yarn.lock ] && command -v yarn >/dev/null; then
    echo "session-start: yarn install"
    yarn install
  else
    # install, not ci: the container image is cached after this hook completes,
    # and install reuses an existing node_modules instead of deleting it.
    echo "session-start: npm install"
    npm install
  fi
fi

# --- Python -----------------------------------------------------------------
if [ -f uv.lock ] && command -v uv >/dev/null; then
  installed=1
  echo "session-start: uv sync"
  uv sync
elif [ -f pyproject.toml ] && command -v uv >/dev/null; then
  installed=1
  echo "session-start: uv pip install -e ."
  uv pip install --system -e '.[dev]' 2>/dev/null || uv pip install --system -e .
elif [ -f requirements.txt ]; then
  installed=1
  echo "session-start: pip install -r requirements.txt"
  pip3 install --user -r requirements.txt
fi

# --- Rust -------------------------------------------------------------------
if [ -f Cargo.toml ]; then
  installed=1
  echo "session-start: cargo fetch"
  cargo fetch
fi

# --- Go ---------------------------------------------------------------------
if [ -f go.mod ]; then
  installed=1
  echo "session-start: go mod download"
  go mod download
fi

# --- Ruby -------------------------------------------------------------------
if [ -f Gemfile ] && command -v bundle >/dev/null; then
  installed=1
  echo "session-start: bundle install"
  bundle install
fi

if [ "$installed" -eq 0 ]; then
  echo "session-start: no dependency manifest found, nothing to install"
fi
