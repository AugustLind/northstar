# Push once, update both Oracle and GitHub Pages

After a one-time setup, pushing to `main` performs:

1. Python tests, generated-UI consistency, JS checks and an authenticated synthetic Chrome workflow.
2. Source-only upload to Oracle, restart, health and authenticated private-API checks. On failure it restores previous source. The portfolio database, Ollama models and server credentials remain on Oracle.
3. Dashboard deployment to GitHub Pages, followed by authenticated API/source and public-asset verification. The site calls the protected Oracle HTTPS API; Python and Ollama keep running on Oracle.

No local app process or SSH tunnel is needed to use the site. The expected UI address is `https://augustlind.github.io/northstar/`.

## One-time setup

First allow inbound **TCP 80 and 443** for the Oracle VM in its security list/NSG and in the VM firewall if enabled. Leave Python port 8000 and Ollama port 11434 closed. SSH port 22 must be reachable from the GitHub-hosted Actions runner for automated deployment. If SSH is restricted to your home IP, the runner will not connect; use suitable networking or a self-hosted runner rather than disabling the firewall.

From your own computer, in the repository containing these files:

```bash
cd /path/to/northstar
gh auth login -h github.com
bash scripts/setup-github-deploy.sh
```

The helper asks for the SSH key path, Oracle IP and API hostname. It obtains the server's public host key through your already trusted SSH connection, stores deployment secrets in GitHub Actions, uploads tracked source once, and runs the HTTPS setup on Oracle. Your private key is not printed or committed. This key grants the workflow the same server access as that SSH account; use a dedicated key if you want to revoke deployment independently.

If you have no domain, the helper suggests **`<your-ip-with-dashes>.sslip.io`**, derived from the server IP you enter. This service resolves names containing the IP to that IP; you do not register a domain. It is a third-party DNS service and certificate issuance/availability are not guaranteed. [Service documentation](https://sslip.io/). If your VM IP changes, update DNS/configuration and the GitHub variables.

In GitHub, open **Settings → Pages → Source → GitHub Actions**. GitHub Free requires a public repository for Pages; supported paid plans also support private source repositories. The workflow does not change repository visibility. The dashboard's static files are public, but API records require your access key.

Push these committed changes:

```bash
git push origin main
```

If that commit was already pushed before setup, run the **Deploy Northstar** workflow manually from the Actions tab. Wait for the workflow to succeed, then open the Pages URL.

On the first visit, select **Connection** and enter the Northstar access key. Read it in your Oracle SSH terminal:

```bash
cat ~/.config/northstar/access-key
```

Paste it only into your dashboard. Do not put it into GitHub variables, source files, screenshots or chat. The server address is configured by the Pages build. Connection details are saved only for the current browser tab session. Sign out clears the key and displayed portfolio.

## Normal updates

```bash
git add .
git commit -m "Describe your changes"
git push origin main
```

Watch the Actions tab for success or failure. No manual scp, remote pull or restart is needed. The workflow updates application source, not OS packages, nginx configuration or Ollama models. A failed Oracle deployment prevents the new Pages UI from publishing. GitHub-hosted deployment has not been verified until the first workflow succeeds.

## GitHub configuration set by the helper

| Kind | Name | Purpose |
|---|---|---|
| Secret | `ORACLE_SSH_KEY` | Private key for the Ubuntu deployment account |
| Secret | `ORACLE_KNOWN_HOSTS` | Pinned public host key; SSH verification stays enabled |
| Variable | `ORACLE_HOST` | VM IPv4 address |
| Variable | `NORTHSTAR_API_URL` | HTTPS Oracle origin, no `/api` suffix |

The workflow publishes only an allowlist of static assets. No holdings database, report, access key, Python file or SSH credential is included in the Pages artifact. CORS permits the configured Pages origin and Oracle origin; every portfolio/research API call additionally needs the access key. `/api/health` exposes only a health boolean for deployments.

## Troubleshooting

- **Pages workflow unavailable:** push the workflow to `main`, enable Pages Actions, and check repository/plan eligibility.
- **SSH verification fails:** compare host keys through a trusted Oracle console before updating `ORACLE_KNOWN_HOSTS`; do not disable verification.
- **Oracle deploy cannot connect:** check port 22 access from the runner and SSH key/host variables.
- **Certificate issuance fails:** check hostname resolution and inbound 80/443; shared DNS providers can encounter CA rate limits. The setup initially exposes only ACME challenge files, never the portfolio.
- **Dashboard cannot connect:** inspect the API hostname's HTTPS certificate and the exact `NORTHSTAR_PAGES_ORIGIN` in `/etc/northstar.env`. The origin is lowercased and has no repository path.
- **401:** enter the access key from Oracle; it is separate from your SSH key and Ubuntu account.

After enabling access-key authentication, legacy local/tunnel clients also need to connect using the key. The older Basic Auth HTTPS setup is superseded by `setup-pages-oracle.sh` when using Pages.

## Optional email alerts

After deploying the email-enabled version, run `python3 scripts/setup-email.py` in the Oracle checkout. It prompts privately for your SMTP settings, stores them in `/etc/northstar-email.env` with mode 600, installs a service drop-in and restarts Northstar. Existing API credentials and portfolio data are preserved. These settings stay on Oracle and are never part of the Pages build or GitHub Actions variables. Deployments preserve both service environment files.

Open **Daily overview → Email alerts**, enable delivery if paused, and select **Send test email**. Alerts require a valid confirmed share-count plan; the server sends them with the browser closed. An authentication/connectivity error appears in delivery status. Follow your provider's SMTP settings and verify Oracle can reach its submission port. Acceptance by the mail server is not proof of inbox delivery. Full behavior and manual environment settings are documented in [the email reference](docs/REFERENCE.md#email-alerts).


## Authenticated release verification

No additional access-key secret is required in GitHub. The private server key stays
in `~/.config/northstar/access-key` on Oracle. The rollback gate runs
`python3 scripts/smoke-deployment.py --attempts 3` locally after health succeeds.
A missing/invalid key or failed private contract/source check fails closed and
restores the previous source. The checker prints operation labels, never the key
or portfolio response bodies. It does not send a test email or run a real experiment.

After Pages publication the verification job checks the configured TLS virtual host
and all public scripts/styles against the deployed manifest, including the browser preflight and bearer CORS contract. TLS routes locally on
Oracle with normal certificate/SNI verification, avoiding a dependency on reaching
the instance's own public IP. The configured origin is obtained from the trusted
local process before any remote-origin check can use the key. Credentialed redirects
and proxy environment variables are disabled for these private checks.

The Chrome sign-in/portfolio/research/experiment/sign-out flow runs in CI against a
temporary synthetic account using the real code. This exercises write-heavy flows
without replacing your production experiment or mutating your actual portfolio.
The default public `/api/health` stays a boolean and is not sufficient evidence of
an authenticated deployment by itself.
