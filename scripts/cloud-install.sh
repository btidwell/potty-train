#!/usr/bin/env bash
# Idempotent dependency install for Cursor cloud agent Builds.
# Runs from any cwd. Safe to re-run on a disk that already has .venv and node_modules.
set -euo pipefail

cd "$(dirname "$0")/.."

node -e '
  const [major, minor] = process.versions.node.split(".").map(Number);
  const ok = (major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major >= 24;
  if (!ok) {
    console.error(`Node ${process.version} is too old. Angular 21 needs ^20.19 || ^22.12 || >=24.`);
    process.exit(1);
  }
'

sys_ver="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
if [[ "$sys_ver" != "3.12" ]]; then
  echo "Python ${sys_ver} does not match the Lambda runtime (3.12)." >&2
  exit 1
fi

venv_ver=""
if [[ -x .venv/bin/python ]]; then
  venv_ver="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
fi
if [[ "$venv_ver" != "$sys_ver" ]]; then
  rm -rf .venv
  python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r backend/requirements-dev.txt
npm ci --prefix frontend

echo "Ready: Python $(.venv/bin/python --version) , Node $(node --version)"
