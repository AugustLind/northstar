#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
if ! gh auth status >/dev/null 2>&1; then
  printf 'GitHub login is required. Run: gh auth login -h github.com\n' >&2
  exit 1
fi
if git remote get-url origin >/dev/null 2>&1; then
  printf 'An origin remote already exists. Review it, then run git push -u origin main.\n' >&2
  exit 1
fi
gh repo create northstar --private --source=. --remote=origin --push
