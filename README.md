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

This remains an **unvalidated technical ranking**. Annual company-financial snapshots are supplementary; they do not yet change ranks or establish complete business quality. NewsWeb headline metadata is presented separately; full-report interpretation and suitability are not assessed, and rankings have not been backtested.

## Company fundamentals (first improvement)

Explore a stock to see annual revenue/growth, operating and net margin, operating and free cash flow, debt, cash, equity, share-count changes and a price/annual-EPS proxy when compatible inputs exist. A separate low-concurrency worker checks the configured universe and holdings, prioritising an explicitly requested refresh. Successful records are cached for 24 hours; failed attempts back off for six hours. HTTP 401/403/429 defers remaining requests rather than repeatedly calling a blocked provider.

Data comes from Yahoo's unofficial annual financial timeseries endpoint, the same endpoint family used by yfinance. No new dependency, API key or paid service is required. Coverage varies across Oslo stocks. Each field retains its currency and fiscal period end; retrieval time is separate. Fiscal period end is **not** filing publication time, and the data is **not point-in-time** or suitable for historical validation without additional filing records.

Missing numbers remain unavailable, including when some other fields are known. Ratios require matching fiscal dates and known matching currencies. Annual growth requires a comparable adjacent year. Free cash flow is reported where available; otherwise derived from operating cash flow minus absolute capex only for matching dates/currencies. Price divided by positive annual diluted EPS is labelled an annual P/E proxy, never TTM P/E; it is omitted for stale quotes or currency mismatch. Debt-to-equity is omitted for non-positive equity and must be interpreted in sector context. Share-count increases are flagged for review, not declared dilution, because splits and acquisitions can change counts.

The panel exposes Available / Partial / Stale / Unavailable coverage and the provider link. Annual periods older than 550 days or records not successfully retrieved in seven days are marked stale. Refresh errors retain the original successful data and dates. Records are private entries in the existing SQLite metadata table and survive deployments. AI receives only a compact, dated financial summary where available and cannot invent missing metrics. No financial score is silently blended into technical rankings.

## Company announcements and earnings updates (second improvement)

The **Announcements** tab shows exchange-hosted issuer notices from Oslo Børs NewsWeb, with publication times in Europe/Oslo, original source links, correction relationships, and topic labels. It defaults to your NOK holdings plus the current top 20; switch to holdings only or the configured universe. Each stock’s explorer also shows its latest covered notices and extracted reporting dates.

A separate worker refreshes every 30 minutes. It fetches seven calendar days of NewsWeb metadata, splitting overflowing date windows until daily granularity. A single-day overflow is marked partial rather than silently treated as complete. Notice IDs deduplicate updates; retained metadata is bounded to 30 days and 3,000 notices. Coverage/status, latest successful retrieval and errors stay visible. Failed refreshes preserve the original data and dates. The API returns at most the newest 100 matching retained notices; this is not a complete announcement archive.

The daily summary counts notices published in the last 24 hours and highlights earnings/business updates and headline review flags. Labels are deterministic rules for guidance/risk, reporting calendars, earnings, capital/financing, corporate actions, contracts, ownership, distributions and governance. They do not establish sentiment, an earnings beat/miss or future price impact. Superseded notices are excluded from the daily digest. You can mark notices reviewed; this does not delete them.

Upcoming report/presentation dates are extracted only from explicit full dates on the same text line as a reporting/results label. Missing years, ambiguous multi-date sentences and invalid dates are ignored. At most eight relevant new calendar notices are checked per cycle. Bodies are processed in memory for calendar facts only; full text and attachments are not retained, downloaded or summarised. A newer full financial calendar replaces previously extracted calendar entries. All displayed dates link to the issuer notice and remain subject to subsequent corrections. No extracted event does not mean no event is scheduled.

This is the public NewsWeb website’s undocumented data service, not a licensed completeness guarantee. General publisher news is not ingested. The existing access key protects these API responses. Headlines, dates and limited classifications can be supplied to local AI as evidence, with explicit instructions that headlines are not full reports and cannot override computed ranks. AI input remains bounded to avoid overloading the one-CPU server.

## Free local AI

Ollama is an optional local model runtime. [Official Linux installation](https://docs.ollama.com/linux) and [API documentation](https://docs.ollama.com/api/generate).

After installing and starting Ollama:

```bash
bash scripts/setup-local-ai.sh
```

This downloads `qwen2.5:3b` (approximately 1.9 GB; [model details and licence](https://ollama.com/library/qwen2.5:3b)). Enable **Generate local AI briefings** in Research settings. Choose a different installed Ollama model there if preferred. Hardware and electricity are your costs; no paid API is used.

Northstar calls only `http://127.0.0.1:11434/api/generate`, with a three-minute timeout. It generates a briefing on each research cycle, and you can ask questions on the page. Only the measured report and your notebook notes are supplied; the model has no live web tool. It can use cached NewsWeb headline metadata, not full notice text. AI text is labelled separately from computed signals and cannot change actions. If Ollama is unavailable, the deterministic screen still runs and the page explains the missing AI connection.

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

### Historical experiments and forward tracking

The Validation & paper tracking tab runs a monthly, equal-weight top-20 technical-ranking experiment on cached Oslo histories. Decisions use only bars available through each decision date and execute at the next common session close. Empty selections remain cash. One-way costs default to an illustrative 20 basis points and are configurable; these are not Nordnet fee estimates. Results include return, drawdown, simulated weight changes, cost drag and daily strategy/benchmark values. The benchmark buys and holds the same complete-history stock basket. Neither side assumes terminal liquidation.

This is a survivor-biased, complete-case experiment on today's universe, not validated market performance or a point-in-time fundamental/news backtest. Adjusted historical prices can change; adjusted close times raw volume approximates historical turnover. Incomplete histories and missing common sessions are excluded. Taxes, cash interest, minimum fees and market impact are omitted. Histories cover roughly two years with a 200-observation warm-up.

Every newly completed scan automatically appends an immutable recommendation cohort to SQLite, including capture time, ranks, actions, scores and quote timestamps. No existing report is backdated. Paper tracking uses the first later daily close as hypothetical entry and only reports returns after another later observation, with 20 basis points charged each way. Missing members prevent cohort totals. Independent cohorts overlap; they are not a funded, rebalanced account and never modify real holdings. The UI shows the latest 60 cohorts; earlier rows remain in the server database.

### Portfolio fit (step 4)

The Portfolio fit page evaluates the current technical top 20 against manually tracked cash, a purchase budget, maximum stock and sector weights, a cash reserve and proportional cost assumptions. Defaults are illustrative, not allocation advice or Nordnet fee estimates. All settings and user-entered sector classifications are persisted privately in Oracle SQLite, included in notebook JSON exports, and preserved across deployments. No sector data feed is connected; unclassified held stocks prevent sector clearance. The page supports cash-only starting portfolios. Legacy USD holdings require fresh USD/NOK for valuation but are excluded from correlation comparisons.

Purchase previews use whole shares, include assumed costs within the entered budget, and calculate weights using holdings plus cash after estimated costs. The displayed maximum purchase value is the pre-cost stock-value ceiling, not a suggested investment amount. Missing/stale prices block sizing. Existing exposure warnings, sector bars and each candidate's strongest measured correlation to another NOK holding are visible. Correlations require 60 matching daily return intervals (up to 126); unavailable or constant series remain unknown. They are historical context, not a diversification guarantee.

Market ranks, historical experiments and paper cohorts remain unchanged by these constraints. A candidate clears the page only if its current technical buy signal and its hypothetical purchase both pass. Previews do not place orders or change cash, shares or cost basis. Update these manually after Nordnet trades. Local AI receives bounded portfolio context and calculated allocation previews, with unknown-data limitations.
