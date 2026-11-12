# Development guide

Return to the [README](../README.md). Run commands from the repository root.

## Architecture

| Area | Files |
|---|---|
| HTTP API, workers, SQLite orchestration | `app.py` |
| Screening and indicators | `research.py`, `decision_policy.py`, `indicators.py`, `universe.py` |
| Financial, announcement, and company data | `fundamentals.py`, `announcements.py`, `company_data.py` |
| Portfolio covariance, scenarios and decision summaries | `portfolio_risk.py`, `stock_summary.py` |
| Multi-year financial/peer context | `financial_analysis.py` |
| Private operational health | `system_status.py` |
| Historical experiments and forward cohorts | `validation.py` |
| Portfolio sizing, plans, imports, and ledger | `portfolio_fit.py`, `trade_plan.py`, `holdings_import.py`, `transactions.py` |
| Dashboard summaries and shared state | `daily_board.py`, `advice_state.py`, `broker_costs.py` |
| Persistent email delivery | `email_alerts.py` |
| Browser UI | `static/` |
| Deployment and diagnostic helpers | `scripts/` |
| Python and JavaScript regression checks | `tests/` |

The Python application uses only the standard library. The UI uses native
JavaScript and SVG; there is no npm install or bundler step. Node is required
for JavaScript checks, not to serve the application.

## Validation

```bash
python3 -m unittest discover -s tests -v
node tests/test_charts.js
node tests/test_ui.js
for file in static/*.js; do node --check "$file"; done
for file in scripts/*.sh; do bash -n "$file"; done
```

Tests use temporary databases and synthetic/mocked inputs. Live data probes in
`scripts/probe-*.py` contact upstream services and are separate from unit tests.
Do not describe an unexecuted provider probe or deployment as verified.

## Local files

Do not commit `data/`, database files, credentials, private keys, portfolio
exports, or backup directories. `.gitignore` covers these common local outputs,
but review `git diff --cached` before committing. Ignore rules do not remove
files from earlier commits or protect files that were already tracked.

The app reads its hosting/authentication settings from the process environment;
it does not automatically load a root `.env` file. The system service can read
`/etc/northstar.env`, as configured by the hosting scripts. Keep access keys in
the documented private location rather than browser source or GitHub variables.

## Publishing and deployment

The existing `Deploy Northstar` workflow runs checks, deploys application source
to Oracle, and publishes an allowlist of static assets to GitHub Pages when
its required credentials and variables are configured. A normal push to `main`
can therefore affect the deployed application.

Source deployment and rollback preserve server-side `data/`. Review the
[deployment guide](../GITHUB-DEPLOY.md) before changing this pipeline. Installing
services, changing firewall/DNS settings, and initial HTTPS setup are explicit
host operations, not steps needed for local development.

The `scripts/publish-github.sh` helper is only for an initial checkout with no
`origin`: it creates a private `northstar` repository. Existing GitHub checkouts
should use their configured remote instead.

For documentation-only maintenance that should not trigger the deployment
workflow, GitHub's supported skip-workflow commit markers can be used after
running relevant checks locally. The workflow can still be dispatched manually.
