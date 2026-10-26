#!/usr/bin/env bash
# Run once on your own computer, inside the GitHub-connected checkout.
set -euo pipefail
cd "$(dirname -- "${BASH_SOURCE[0]}")/.."
gh auth status >/dev/null
task_owner="$(gh repo view --json owner --jq '.owner.login')"
if [[ ! "$task_owner" =~ ^[a-zA-Z0-9][a-zA-Z0-9-]{0,38}$ ]]; then echo "Invalid repository owner." >&2; exit 1; fi
read -r -p 'Path to the Oracle SSH private key on this computer: ' task_key
task_key="$(python3 -c 'import os,sys; print(os.path.expanduser(sys.argv[1]))' "$task_key")"
if [[ ! -f "$task_key" ]]; then echo 'Private key file not found.' >&2; exit 1; fi
read -r -p 'Oracle public IP [152.70.43.0]: ' task_host
task_host="${task_host:-152.70.43.0}"
if [[ ! "$task_host" =~ ^[0-9.]+$ ]]; then echo 'Enter the Oracle IPv4 address.' >&2; exit 1; fi
read -r -p 'Oracle HTTPS hostname [152-70-43-0.sslip.io]: ' task_domain
task_domain="${task_domain:-152-70-43-0.sslip.io}"
if [[ ! "$task_domain" =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?\.[a-zA-Z]{2,63}$ ]]; then echo 'Enter a valid hostname.' >&2; exit 1; fi
# Reuse the already trusted SSH connection to obtain the server's public host key.
task_public_host_key="$(ssh -i "$task_key" -o StrictHostKeyChecking=yes "ubuntu@$task_host" 'cat /etc/ssh/ssh_host_ed25519_key.pub')"
printf '%s %s\n' "$task_host" "$task_public_host_key" | gh secret set ORACLE_KNOWN_HOSTS
gh secret set ORACLE_SSH_KEY < "$task_key"
gh variable set ORACLE_HOST --body "$task_host"
gh variable set NORTHSTAR_API_URL --body "https://$task_domain"
# Sends a source-only archive once so the new HTTPS setup script exists on Oracle.
# Subsequent updates use the workflow, with tests, health checks and rollback.
git archive --format=tar.gz HEAD | ssh -i "$task_key" -o StrictHostKeyChecking=yes "ubuntu@$task_host" 'tar -xzf - -C ~/northstar'
printf '\nGitHub deployment credentials configured. No secrets were committed.\n'
printf 'Enable Pages → GitHub Actions in repository settings.\n'
ssh -i "$task_key" -o StrictHostKeyChecking=yes "ubuntu@$task_host" "cd ~/northstar && bash scripts/setup-pages-oracle.sh '$task_domain' '$task_owner'"
printf 'Oracle HTTPS and Pages access configured. Website key remains private on Oracle.\n'
printf 'Then push main (or run the Deploy Northstar workflow manually).\n'
