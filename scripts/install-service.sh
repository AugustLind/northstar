#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
task_unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$task_unit_dir"
if [[ -e "$task_unit_dir/northstar.service" ]]; then
  echo 'northstar.service already exists. Review it before replacing it.' >&2
  exit 1
fi
python3 "$task_root/scripts/service-unit.py" > "$task_unit_dir/northstar.service"
systemctl --user daemon-reload
systemctl --user enable --now northstar.service
systemctl --user --no-pager status northstar.service
printf '\nNorthstar runs while your user session and computer are active.\n'
printf 'For boot/logout operation, enable user lingering: loginctl enable-linger "$USER"\n'
