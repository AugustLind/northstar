# Oracle Ubuntu deployment

Target: Ubuntu 24.04 aarch64 VM, 1 OCPU, 6 GB RAM. SSH user: ubuntu.

## Copy the code from your own computer

No GitHub authentication is needed to transfer source with SSH. On your **own computer**, replace `/path/to/key` with the SSH key you already use:

```bash
cd ~/repos/stockPredicter/northstar
tar --exclude='data' --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' -czf /tmp/northstar-source.tar.gz .
scp -i /path/to/key /tmp/northstar-source.tar.gz ubuntu@152.70.43.0:/home/ubuntu/
```

This archive excludes your existing portfolio. To migrate it, stop the local app and separately copy `data/portfolio.db` into the server checkout's `data/` directory before running the installer. It stays private and ignored by Git. Do not overwrite a server database after adding holdings there.

## Install on the Oracle server

In your **Oracle SSH terminal**:

```bash
mkdir -p ~/northstar
tar -xzf ~/northstar-source.tar.gz -C ~/northstar
cd ~/northstar
bash scripts/install-oracle.sh
```

The script uses sudo to install Python prerequisites and, if missing, Ollama from its official installer. It downloads the approximately 986 MB Qwen 2.5 1.5B model, limits simultaneous model requests, enables local AI in Northstar and installs a system service running under your Ubuntu user. Existing records/settings are retained. The app and Ollama remain bound to loopback. Both services restart automatically after a reboot. The computer you connect from can be turned off.

## Open the full app privately

From **your own computer**, keep this tunnel open:

```bash
ssh -i /path/to/key -N -L 18080:127.0.0.1:8000 ubuntu@152.70.43.0
```

Open **http://127.0.0.1:18080/recommendations**. This is the full remote application, not a static report. SSH encrypts traffic to the server; no application ports need exposing. Ollama generation on one CPU can be slow. Charts and computed advice publish before the model finishes; inference has a three-minute timeout.

## Optional public website

Use a domain/subdomain you control and point its DNS A record to the VM public IP. Allow inbound TCP 80 and 443 in Oracle's NSG/security list and the VM firewall if enabled. Keep 8000 and 11434 closed. Only enable SSH port 22 for administrative access, preferably restricted to your IP.

After DNS resolves correctly, run on the server:

```bash
cd ~/northstar
bash scripts/enable-public-https.sh northstar.example.com
```

Replace the example domain with yours. This installs nginx, obtains a Let's Encrypt certificate, prompts for a password for website user `northstar`, and proxies HTTPS to the private Python process. Passwords are entered directly in the terminal and stored as hashes. The app accepts browser writes only from the configured HTTPS origin. Plain HTTP redirects to HTTPS; Ollama has no public route. The public setup refuses to replace an existing Northstar nginx configuration. If certificate issuance fails, fix DNS/networking and review the challenge-only configuration before retrying. The app remains private on failure.

## Operations

```bash
sudo systemctl status northstar ollama
sudo journalctl -u northstar -f
sudo journalctl -u ollama -n 50 --no-pager
curl -fsS http://127.0.0.1:11434/api/tags
```

After uploading updated code: `sudo systemctl restart northstar`.

To back up: stop Northstar, copy `~/northstar/data/portfolio.db` to a private backup destination, then start Northstar again. Keep backups off the VM too, because the free instance can be reclaimed. Deployment is not verified until the scripts have run successfully on the VM; the development environment cannot start services or reach this server.
