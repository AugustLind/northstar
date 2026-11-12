# Recovering Northstar

Use this guide on the server that owns the private database. For normal releases,
use [GitHub deployment](../GITHUB-DEPLOY.md). Never copy private data into Git or Pages.

## Preserve data before changing anything

For the Oracle system service, stop writes and make a dated private copy:

```bash
sudo systemctl stop northstar
install -d -m 700 ~/.local/share/northstar-backups
cp -p ~/northstar/data/portfolio.db ~/.local/share/northstar-backups/portfolio-$(date -u +%Y%m%dT%H%M%SZ).db
sudo systemctl start northstar
```

If copying fails, retain the original database and resolve the error before any
restore. Keep another private copy off the VM. Notebook JSON is a partial export;
it cannot restore the ledger, archive, settings or delivery history.

For a foreground local app, stop it with Ctrl+C before copying `data/portfolio.db`.
For a Linux user service, use `systemctl --user stop/start northstar` instead.

## Validate a backup without replacing production

Replace the path with your backup. This reads it without opening a writable database:

```bash
python3 - /absolute/path/to/backup.db <<'PYTHON'
import sqlite3, sys
from pathlib import Path
path = Path(sys.argv[1]).resolve(strict=True)
with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
    result = db.execute('PRAGMA integrity_check').fetchone()[0]
    print(result)
    if result != 'ok':
        raise SystemExit(1)
PYTHON
```

An integrity check verifies SQLite structure, not correctness of portfolio records.
Inspect a restored copy in a separate checkout on a separate machine before using it.
Disable email credentials there and avoid running two app instances on one database.

## Restore a verified database

Stop the owning service first. Preserve the current database using the backup steps
above. Install the chosen verified backup as `~/northstar/data/portfolio.db` under
the same service user, then restart. Do not restore a database while the app runs.
Check holdings, cash, ledger reconciliation, archive coverage and email settings
before relying on results. An older backup can repeat email suggestions already sent
after that backup; keep delivery paused while reviewing the restored state.

## Failed release

Inspect the failed Actions job. The Oracle deployment script restores previous source
when its health/authenticated gate fails; it preserves the database. The previous
source archive is `~/.cache/northstar-previous-source.tar.gz`, not a data backup.

A failure after Pages publication does not automatically restore a compatible
frontend/backend pair. Fix the failed verification or revert the offending source
commit and deploy that committed revision through the full workflow. Preserve private
data first and review schema compatibility before downgrading code. Do not rerun the
initial installer to repair a configured Pages server.

Recovery is complete only after service status, authenticated release verification,
and your portfolio/ledger records have been checked. Scheduled backups and automatic
restore drills are not currently implemented.
