# Northstar

A local Oslo stock research dashboard for a long-term investor using Nordnet Norway. You place every trade yourself. Python 3.10+; no Python dependencies or paid AI API.

For the Oracle Ubuntu server installer, private SSH access, and optional password-protected HTTPS hosting, see [DEPLOY.md](DEPLOY.md).

## Open the app

```bash
python3 app.py
```

Visit **http://127.0.0.1:8000/recommendations**. If another copy is running on port 8000, stop it with Ctrl+C first. Hard refresh the browser after updating the code.

The background worker starts with the app, refreshes quotes, builds recommendations and repeats every six hours by default. Results appear automatically; the browser polls every 15 seconds. The browser can be closed without stopping research. Interval and universe are editable on the Recommendations page.

## Recommendations and charts

- Default candidates: 34 Oslo names from the publicly visible subset of Euronext's OSESX small-cap composition, snapshot **30 September 2026**. This is not the complete market/index or a guarantee of current membership. No market-cap weighting. [Universe source](https://live.euronext.com/sites/default/files/documentation/index-composition/Oslo_Bors_Small_Cap_Index_Composition.pdf).
- Candidate list accepts up to 100 Oslo tickers. Bare tickers receive `.OL`. Previous US/large-cap research settings migrate to this default once; existing holdings remain intact. Only NOK holdings appear in research advice.
- Buy screen: daily close above 50/200-session averages, 50-session average above 200-session average, positive 63-session momentum, annualised daily volatility below 50%, price less than 15% above its 50-session average. At least 15 turnover observations in 20 sessions and average daily traded value above a configurable NOK 250,000 floor are required.
- Trend score counts the four trend conditions at 25 points each. It is **not a probability or return forecast**. Eligible candidates rank first, then score, then momentum divided by volatility (minimum volatility denominator 10%). Market size does not determine rank.
- Held stock sell review: close below 200-session average and negative momentum. User price thresholds take priority for sell/profit review labels. Concentration above 25% is context, not an instruction to sell. No optimal sale date is predicted.
- Charts show 1/3/12 months of daily observations, with axes and hover values. Adjusted close is used where available; chart basis is labelled. Live quote and chart close can differ.

This is an **unvalidated price-based screen**, not a completed investment adviser. It does not assess business fundamentals, valuation, earnings, news, suitability, taxes or optimal position sizing. A free LLM explains the report; it does not supply missing facts or validate the strategy. Smaller stocks can be volatile, illiquid and speculative. Thresholds need point-in-time backtesting before relying on them for trading decisions.

## Free local AI

Ollama is an optional local model runtime. [Official Linux installation](https://docs.ollama.com/linux) and [API documentation](https://docs.ollama.com/api/generate).

After installing and starting Ollama:

```bash
bash scripts/setup-local-ai.sh
```

This downloads `qwen2.5:3b` (approximately 1.9 GB; [model details and licence](https://ollama.com/library/qwen2.5:3b)). Enable **Generate local AI briefings** in Research settings. Choose a different installed Ollama model there if preferred. Hardware and electricity are your costs; no paid API is used.

Northstar calls only `http://127.0.0.1:11434/api/generate`, with a three-minute timeout. It generates a briefing on each research cycle, and you can ask questions on the page. Only the measured report and your notebook notes are supplied; the model has no live web/news tool. AI text is labelled separately from computed signals and cannot change actions. If Ollama is unavailable, the deterministic screen still runs and the page explains the missing AI connection.

## Run continuously on Ubuntu

Stop any foreground copy, then install the user service:

```bash
bash scripts/install-service.sh
```

This writes a unit under your user systemd configuration and enables it. It does not require root. Existing units are not overwritten. To continue across logout and start at boot, enable user lingering if your system permits it:

```bash
loginctl enable-linger "$USER"
```

```bash
systemctl --user status northstar
journalctl --user -u northstar -f
systemctl --user restart northstar
systemctl --user disable --now northstar
```

The computer must be awake and connected to fetch data. This service does not install/start Ollama; its official Linux installation supports a separate Ollama service. No email, mobile push or broker execution is implemented.

## Portfolio and storage

Enter current shares, weighted average cost, trading currency, thesis and review prices. Zero shares makes a watchlist entry. Norwegian bare tickers such as `KOG` resolve to `KOG.OL`. Shares, average costs and corporate actions need manual maintenance.

- SQLite records, quotes, settings and latest report persist in `data/portfolio.db`, ignored by Git. Stop the app before copying the file for backups. JSON portfolio export is available; JSON import is not implemented.
- Yahoo's unofficial chart endpoint supplies prices and FX. Availability and data-use terms can change. Provider timestamps are visible; stale values retain their timestamps after a failed refresh.
- Quotes/FX older than four calendar days are excluded from NOK valuation. The dashboard labels incomplete totals. Holidays affect freshness.
- Percentage gains are local-currency price returns, excluding fees/dividends/tax/currency effects. NOK totals are current stock values, not cash balance or total portfolio return.
- Bind only to localhost. There is no remote-access login. Cross-origin browser writes are rejected.

## GitHub

The local repository is named `northstar`. Commits use the configured human Git author and contain no assistant co-author trailer. Portfolio data and local model files are excluded.

If GitHub authentication is missing or invalid:

```bash
gh auth login -h github.com
bash scripts/publish-github.sh
```

The helper creates a **private** GitHub repository named `northstar` and pushes the existing main branch. It refuses to overwrite an existing origin remote.

## Verification

```bash
python3 -m unittest discover -s tests -v
node --check static/app.js
node --check static/advice.js
node tests/test_ui.js
```

Tests use temporary databases and mocked providers. They cover indicator actions, missing/stale data, currency checks, Oslo suffix handling, liquidity, settings, provider parsing, background analysis persistence and local AI requests. External Yahoo/Ollama connectivity, browser rendering, GitHub push and service startup must be checked on the host where those services are available.
