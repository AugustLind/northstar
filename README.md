# Northstar

A personal stock-research dashboard focused on Oslo-listed companies, with
portfolio tracking, interactive charts, company-data summaries, and optional
local AI briefings. It runs with Python's standard library and a browser.

Northstar does not connect to a broker or place orders. Rankings are experimental
research signals, not validated forecasts or a substitute for your own review.

## Quick start

Requirements: **Python 3.10+**, a browser, and internet access for market data.
No pip installation, Node build step, paid AI API, or broker credentials are
required for the local app.

```bash
git clone https://github.com/AugustLind/northstar.git
cd northstar
python3 app.py
```

Open **http://127.0.0.1:8000/recommendations**. Keep the Python process running;
closing the browser does not stop its background workers. Stop the app with
Ctrl+C. Only one instance should use this checkout's database/port at a time.

The first research cycle runs in the background. Missing data or provider errors
are shown rather than replaced with sample prices. The default research refresh
interval is six hours and can be changed in the app. Provider availability is
not guaranteed; offline operation depends on previously cached data.

## What it does

- Screens an editable universe of Oslo stocks using technical signals and
  liquidity checks, with a top-20 view passing the shared entry policy.
- Draws interactive price, volume, and indicator charts in the browser.
- Shows available annual financial data, company metadata, and issuer notices
  with coverage and freshness information.
- Tracks manually entered holdings, cash, review notes, and transaction records,
  with previewed CSV imports and hypothetical allocation/share-count plans.
- Supports historical experiments and forward paper cohorts with explicit
  missing-data and methodology limitations.
- Optionally generates briefings through a locally running Ollama model.
- Emails confirmed share-plan changes through privately configured SMTP, with
  retries, duplicate suppression, and dashboard pause/test controls.

Read the [technical reference](docs/REFERENCE.md) for scoring rules, data
sources, import behavior, fee assumptions, historical methodology, and feature
limitations. Those details have been preserved outside this introduction.

## Your data

Portfolio records, cached market data, settings, and reports are stored in
**`data/portfolio.db`**, which Git ignores. A fresh checkout creates its own
local database. Stop the app before copying the database to a private backup;
keep backups and portfolio exports outside tracked source.

The local application binds to `127.0.0.1:8000`. Remote hosting and authentication
require separate setup. The GitHub Pages dashboard is a static UI connected to
an authenticated API; Pages alone cannot run Python, research workers, or Ollama.
Do not put access keys or portfolio data in `static/config.js`.

## Optional setup

| Goal | Instructions |
|---|---|
| Explain signals and review data limitations | [Technical reference](docs/REFERENCE.md) |
| Configure server-side email alerts | [Email setup](#email-alerts) |
| Enable local AI or a Linux user service | [Local services](docs/LOCAL-SERVICES.md) |
| Run on an Oracle Ubuntu server, with private SSH access | [Oracle deployment](DEPLOY.md) |
| Deploy the API and GitHub Pages UI automatically | [GitHub deployment](GITHUB-DEPLOY.md) |
| Understand modules, checks, and contribution workflow | [Development guide](docs/DEVELOPMENT.md) |

Ollama is optional and installed separately. If it is unavailable, deterministic
research still works. Remote market-data providers remain external services even
when model inference is local. No server address or credential is required just
to try the local application.

## Email alerts

After deploying the updated code, run this from the checkout in your Oracle SSH
terminal:

```bash
python3 scripts/setup-email.py
```

The helper prompts privately for SMTP settings, installs the server configuration
and restarts Northstar. Open **Daily overview → Email alerts → Send test email**
after setup. Keep passwords out of source files, GitHub and chat. Email works
without an open browser, but requires valid confirmed share-plan quantities.
See the [email reference](docs/REFERENCE.md#email-alerts) for delivery behavior,
manual settings, and limitations.

## Checks

The app has no third-party Python runtime dependencies. Node.js is needed only
for JavaScript checks, and Bash for deployment-script checks:

```bash
python3 -m unittest discover -s tests -v
node tests/test_charts.js
node tests/test_ui.js
for file in static/*.js; do node --check "$file"; done
for file in scripts/*.sh; do bash -n "$file"; done
```

Tests use synthetic data, temporary databases, and mocked providers. Passing
checks do not establish live provider availability, deployment success, or
investment performance.

## Status and limitations

This is a personal research application. Historical analysis has limitations
including today's stock universe, missing delisted securities, revised data,
and incomplete coverage. Computed scores are not probabilities of profit.
Review provider dates, assumptions, costs, and missing-data states before using
any result. AI output is separate from computed signals and can be wrong.

No project license is currently specified in this repository. Third-party data,
models, and services have their own terms.
