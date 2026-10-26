#!/usr/bin/env bash
# Run on the Oracle Ubuntu server as the ubuntu SSH user.
set -euo pipefail
if [[ $EUID -eq 0 ]]; then
  echo 'Run as your normal Ubuntu user, not root.' >&2
  exit 1
fi
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
sudo -n true
sudo apt-get update
sudo apt-get install -y python3 curl ca-certificates zstd
task_installer="$(mktemp)"
task_unit="$(mktemp)"
trap 'rm -f "$task_installer" "$task_unit"' EXIT
if ! command -v ollama >/dev/null 2>&1; then
  curl --fail --show-error --location --retry 3 https://ollama.com/install.sh -o "$task_installer"
  sh "$task_installer"
fi
sudo systemctl enable --now ollama
# Bound memory use: only one model and one generation request at a time.
sudo mkdir -p /etc/systemd/system/ollama.service.d
printf '%s\n' '[Service]' 'Environment="OLLAMA_HOST=127.0.0.1:11434"' 'Environment="OLLAMA_NUM_PARALLEL=1"' 'Environment="OLLAMA_MAX_LOADED_MODELS=1"' |
  sudo tee /etc/systemd/system/ollama.service.d/northstar.conf >/dev/null
sudo systemctl daemon-reload
sudo systemctl restart ollama
for task_attempt in {1..30}; do
  if curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null; then break; fi
  sleep 1
done
ollama pull qwen2.5:1.5b
if systemctl --user is-active --quiet northstar.service 2>/dev/null; then
  echo 'Stop the earlier user service first: systemctl --user disable --now northstar' >&2
  exit 1
fi
if sudo systemctl is-active --quiet northstar.service; then
  sudo systemctl stop northstar.service
fi
mkdir -p data
chmod 700 data
# Keep any existing portfolio, universe and thresholds; only enable local AI.
python3 - <<'PY'
import app
config = app.settings()
config.update(llm_enabled=True, model='qwen2.5:1.5b')
app.save_settings(config)
PY
python3 scripts/service-unit.py --system > "$task_unit"
sudo install -m 644 "$task_unit" /etc/systemd/system/northstar.service
sudo systemctl daemon-reload
sudo systemctl enable --now northstar
for task_attempt in {1..30}; do
  if curl --silent --fail http://127.0.0.1:8000/api/state >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:8000/api/state >/dev/null
printf '\nNorthstar is running privately on 127.0.0.1:8000.\n'
printf 'On your own computer, open an SSH tunnel to port 8000, then visit http://127.0.0.1:18080/recommendations\n'
sudo systemctl --no-pager --full status northstar
