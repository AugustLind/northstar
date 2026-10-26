#!/usr/bin/env bash
# Run by GitHub Actions on Oracle. Preserves data, settings, models and host config.
set -euo pipefail
umask 077
task_archive="${1:?Supply the uploaded deployment archive}"
task_root="$HOME/northstar"
task_stage="$(mktemp -d)"
task_backup="$HOME/.cache/northstar-previous-source.tar.gz"
mkdir -p "$HOME/.cache"
trap 'rm -rf "$task_stage"' EXIT
# Reject links/traversal before extraction. Artifacts are produced from tracked files.
python3 - "$task_archive" "$task_stage" <<'PY'
import sys, tarfile
from pathlib import PurePosixPath
with tarfile.open(sys.argv[1]) as archive:
    for member in archive.getmembers():
        path=PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise SystemExit('Unsafe deployment archive entry')
        if path.parts and path.parts[0] in ('data', '.git', '.env'):
            raise SystemExit('Runtime data must not be included in source deployments')
    archive.extractall(sys.argv[2])
PY
cd "$task_stage"
python3 -m unittest discover -s tests -q
python3 -m py_compile app.py research.py
mkdir -p "$task_root"
if [[ -f "$task_root/app.py" ]]; then
  tar --exclude=data --exclude=.git --exclude=__pycache__ --exclude=pages-dist --exclude=.env -czf "$task_backup" -C "$task_root" .
fi
# Stop before replacing source files. Database and service environment stay untouched.
sudo -n systemctl stop northstar
if ! tar -xzf "$task_archive" -C "$task_root"; then
  if [[ -f "$task_backup" ]]; then tar -xzf "$task_backup" -C "$task_root"; fi
  sudo -n systemctl start northstar
  exit 1
fi
sudo -n systemctl start northstar
for task_attempt in {1..30}; do
  if curl --silent --fail http://127.0.0.1:8000/api/health >/dev/null; then
    echo 'Oracle deployment healthy. Portfolio database preserved.'
    exit 0
  fi
  sleep 1
 done
printf 'Health check failed; restoring previous source.\n' >&2
sudo -n systemctl stop northstar
if [[ -f "$task_backup" ]]; then tar -xzf "$task_backup" -C "$task_root"; fi
sudo -n systemctl start northstar
exit 1
