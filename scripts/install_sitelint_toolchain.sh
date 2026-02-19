#!/usr/bin/env bash
set -euo pipefail

if [ ! -d .venv ]; then
  echo "Expected .venv to exist. Create it first with: uv venv .venv"
  exit 1
fi

uv pip install --python .venv/bin/python '.[sitelint]'
.venv/bin/playwright install chromium

if command -v npm >/dev/null 2>&1; then
  npm install --no-save lighthouse axe-core
else
  echo "npm not found; skipping Lighthouse/axe installation"
fi

echo "SiteLint toolchain installed."
