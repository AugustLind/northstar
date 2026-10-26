# Northstar

A local Oslo stock research dashboard for a long-term investor using Nordnet Norway. You place every trade yourself. Python 3.10+; no Python dependencies or paid AI API.

For **automatic Oracle + GitHub Pages deployment on every push**, see [GITHUB-DEPLOY.md](GITHUB-DEPLOY.md).

For the Oracle Ubuntu server installer, private SSH access, and optional password-protected HTTPS hosting, see [DEPLOY.md](DEPLOY.md).

## Open the app

```bash
python3 app.py
```

Visit **http://127.0.0.1:8000/recommendations**. If another copy is running on port 8000, stop it with Ctrl+C first. Hard refresh the browser after updating the code.

The background worker starts with the app, refreshes quotes, builds recommendations and repeats every six hours by default. Results appear automatically; the browser polls every 15 seconds. The browser can be closed without stopping research. Interval and universe are editable on the Recommendations page.

## Broad scan, top 20 and interactive charts

- The default scan covers **180 Oslo tickers**, from a dated 26 October 2026 listing snapshot, rather than the earlier 34-name sample. It is a broad subset, not a complete/live exchange directory. [Snapshot source](https://stockanalysis.com/list/oslo-bors/). Settings accept up to 500 tickers. Older settings migrate to the broader default while retaining custom Oslo symbols and portfolio records.
- Every stock with sufficient fresh history gets five technical analyses: Trend, Momentum, Risk, Timing and Liquidity. The default view shows up to 20 eligible stocks by weighted overall score. If fewer qualify, it shows fewer; it never fills missing places with illiquid or unpriced stocks.
- Rank any view by an individual component, search names/tickers, switch to all stocks or holdings, and open **Explore** for the full breakdown and reasons. A stock can rank in the top 20 and still say Wait / watch. Ranking is separate from passing the stricter buy screen.

| Component | Weight | Calculation |
|---|---:|---|
| Trend | 30% | 25 points each for close above MA50, close above MA200, MA50 above MA200, positive 63-session return |
| Momentum | 25% | Clamp 0–100 of `50 + 25 × (0.6 × 3-month return + 0.4 × 6-month return) / max(volatility, 10)` |
| Risk | 20% | Clamp 0–100 of `100 − 0.8 × volatility + 0.5 × maximum drawdown` (drawdown is negative) |
| Timing | 15% | RSI(14) region score, plus/minus MACD versus its signal, minus a price-extension penalty |
| Liquidity | 10% | Clamp 0–100 of `50 + 25 × log10(turnover / turnover floor)`; missing turnover coverage scores zero |

All percentage inputs above are percentage points. Overall is the weighted sum, rounded to one decimal. Ties break by ticker. Components overlap; they are neither independent evidence nor a probability of profit.

Top-20 eligibility requires at least 200 fresh daily observations, a matching currency, annualised volatility below 80%, at least 15 valid turnover observations out of 20, and average daily turnover at or above the configurable NOK 250,000 floor. Market capitalisation does not determine the score.

The **Consider buying** action retains stricter conditions: all four trend rules pass, volatility below 50%, close less than 15% above MA50, and sufficient turnover. Held stock sell reviews use the existing lower/upper review prices and the combination of negative three-month momentum plus close below MA200. Concentration above 25% remains context rather than a mechanical sell instruction.

The explorer supports two years of history; line/candlestick views; 1/3/6/12/24-month presets; custom dates; wheel zoom; drag pan; keyboard +/− and arrows; MA50/MA200 and Bollinger overlays; volume/RSI/MACD lower panels; and comparison against another stock normalised to the visible period. Hover/tap shows the daily observations. Candles use OHLC scaled to the adjusted close basis. If OHLC is missing, the chart falls back to a line. Volume remains the provider's share count.

Charts are drawn locally with native SVG and no third-party chart scripts. Full histories load on demand; normal polling sends summaries only. Scan progress reports downloaded/failed counts. Repeated background scans reuse quotes fetched within 20 minutes when they already have the new history format. Throttled provider calls get one bounded retry.

This remains an **unvalidated technical screen**. It does not assess company finances, valuation, earnings, news or suitability. More indicators do not establish better investment performance. No stock rankings have been backtested yet.

## Free local AI

Ollama is an optional local model runtime. [Official Linux installation](https://docs.ollama.com/linux) and [API documentation](https://docs.ollama.com/api/generate).

After installing and starting Ollama:

```bash
bash scripts/setup-local-ai.sh
```

This downloads `qwen2.5:3b` (approximately 1.9 GB; [model details and licence](https://ollama.com/library/qwen2.5:3b)). Enable **Generate local AI briefings** in Research settings. Choose a different installed Ollama model there if preferred. Hardware and electricity are your costs; no paid API is used.

Northstar calls only `http://127.0.0.1:11434/api/generate`, with a three-minute timeout. It generates a briefing on each research cycle, and you can ask questions on the page. Only the measured report and your notebook notes are supplied; the model has no live web/news tool. AI text is labelled separately from computed signals and cannot change actions. If Ollama is unavailable, the deterministic screen still runs and the page explains the missing AI connection.

AI input is limited to eight selected stocks (named stocks in your question first, then holdings, then ranked candidates), with short notes and rounded metrics. Coverage is included in the prompt; the model does not receive the entire scan’s full records or chart histories. Responses are capped at 300 generated tokens using a 4096-token context. While inference runs, the page disables additional questions. Connection failures, missing models, busy inference and timeouts have separate messages.

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
node --check static/charts.js
node tests/test_charts.js
node tests/test_ui.js
```

Tests use temporary databases and mocked providers. They cover indicator actions, missing/stale data, currency checks, Oslo suffix handling, liquidity, settings, provider parsing, background analysis persistence and local AI requests. External Yahoo/Ollama connectivity, browser rendering, GitHub push and service startup must be checked on the host where those services are available.
