#!/usr/bin/env bash
set -euo pipefail
if ! command -v ollama >/dev/null 2>&1; then
  printf 'Install Ollama using its official Linux instructions first:\nhttps://docs.ollama.com/linux\n'
  exit 1
fi
ollama pull qwen2.5:3b
printf '\nModel downloaded. Keep Ollama running, then enable Generate local AI briefings in Research settings.\n'
