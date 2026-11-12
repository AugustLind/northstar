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
| Ledger performance and dated input archive | `account_performance.py`, `research_archive.py` |
| Public assets and HTML composition | `ui_assets.py`, `ui_templates.py`, `static/assets.json`, `web/templates/` |
| Browser views and startup | `static/`, with `bootstrap.js` last |
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
python3 scripts/build-ui.py --check
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


## Frontend ownership and build contract

The browser uses plain scripts in a single explicit order, without a runtime npm
installation or bundler. `static/assets.json` is the allowlist used by Python
serving, Pages packaging, HTML composition and UI checks. It contains only named
public JS/CSS/SVG assets; do not add runtime records, templates or private exports.

| Responsibility | Source |
|---|---|
| Safe presentation helpers | `static/ui-common.js` |
| API connection, session key and sign-in | `static/app.js` |
| Holdings editor and notebook export | `static/portfolio.js` |
| Four-workspace routing and legacy hashes | `static/navigation.js` |
| Research ranks and controls | `static/advice.js` |
| Chart state, windows, pointer/keyboard interaction | `static/explorer.js` |
| Annual statements, trends and peers | `static/financial-view.js` |
| Portfolio covariance/scenarios and stock explanation | `static/portfolio-risk.js`, `static/stock-summary.js` |
| Operational health and validation presentation | `static/system-status.js`, `static/validation-view.js` |
| Chart appearance, event sources and exports | `static/chart-tools.js` |
| Account performance and archived-input replay | `static/account-performance.js`, `static/archive-view.js` |
| Startup requests after all views are registered | `static/bootstrap.js` |

Existing classic-script function contracts remain explicit and are exercised by
`tests/test_ui.js`. Loading order lives in the manifest rather than duplicated HTML,
server and build-script lists. Do not start initial research requests from a view
module before the other views exist; use the bootstrap entrypoint.

Edit HTML in `web/templates/`: the shell, four workspace fragments, stock explorer
and position editor. Run `python3 scripts/build-ui.py` after template or asset edits
and commit the generated `static/index.html`. The app serves that checked-in output
without compiling templates at runtime. `--check` fails CI if output is stale.
Script/style URLs contain content hashes; Pages regenerates the config hash for its
public API origin. No access key is included in source or version strings.

The frontend is formatted with the pinned development tool Prettier 2.8.8, compatible
with the repository's older local Node installation. It is optional for running the app:

```bash
npm exec --yes --package=prettier@2.8.8 -- prettier --write "static/*.js" "static/*.css" "web/templates/*.html"
python3 scripts/build-ui.py
```

## Authenticated release checks

`python3 scripts/smoke-browser.py` runs the actual application with a temporary SQLite
account and an ephemeral in-memory access key. Chrome checks sign-in, holdings,
account performance, research charts, a newly completed experiment, archived replay
and sign-out at desktop/mobile widths. It never sends email, invokes Ollama, fetches
live provider data or mutates your real portfolio. Chrome is a test requirement only;
GitHub's Ubuntu runner provides it. The browser client has explicit frame-size limits
and regression checks for extended protocol frames.

`scripts/smoke-deployment.py` runs **on Oracle** and reads the existing private
`~/.config/northstar/access-key` locally. There is no key CLI argument and no new
GitHub access-key secret. It denies anonymous reads, checks authenticated response
contracts, and compares the process-start source fingerprint with deployed files.
Public-origin verification first reads the trusted loopback release response; it
will not send the key to an arbitrary supplied remote origin. TLS verification of
the configured nginx host uses loopback transport with its public SNI/Host name,
normal certificate verification, no proxy environment and no redirects. This avoids
public-IP hairpin assumptions without weakening TLS. Only route/check labels are
printed, not portfolios, keys, addresses or response bodies.

The source-deploy rollback gate includes authenticated local checks. After Pages,
a separate verification job reads the private API through its TLS virtual host and
compares every published JS/style with the deployed manifest and verifies the public browser’s preflight/bearer CORS contract. Actual experiments
run only in the isolated browser fixture, not in the production smoke step.

## Archive and account data boundaries

Research snapshots and account opening checkpoints stay in the existing private
`data/portfolio.db`. Do not commit or publish the database. Archive input tables reject
UPDATE/DELETE, use canonical JSON checksums, and compress payloads. Historical price
bars are versioned independently; unchanged bars and unchanged inputs are shared.
A mutable latest-reference index is only a lookup cache, not historical evidence.
Run manifests reference immutable input IDs, source fingerprints and capture clocks.
Replay uses the original report clock and recorded inputs; it does not update live
metadata, quantities, alerts or holdings.

The performance engine is read-only. Verified opening quantities/costs are retained
on new ledger initialisations. Legacy quantities can be reversed from a reconciled
ledger, but unknown opening cost bases remain unknown. A mapped split ratio is an
explicit accounting event; broker quantity deltas are not guessed into ratios.
