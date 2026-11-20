# Northstar mathematical models

This is a short guide to the calculations behind Northstar's research and
portfolio views. The accompanying [LaTeX paper](strategy-mathematics.pdf) gives
the definitions, assumptions, worked examples, and testing protocol in one
place. Its source is [strategy-mathematics.tex](strategy-mathematics.tex).

## Decisions

The research score is a weighted ordering of five technical components:
trend (30%), momentum (25%), risk (20%), timing (15%), and liquidity (10%). A
high score does not waive the shared entry requirements: complete fresh data,
all four trend conditions, annualised volatility below 50%, price less than
15% above its 50-session average, and enough turnover observations above the
configured NOK floor. A qualifying stock is a research candidate, not an
order. Personal cash, fees, allocation limits, confirmation, and cooldowns
still apply to a share plan.

Held positions are reviewed using the combination of negative three-month
momentum and price below the 200-session average, plus any saved lower or upper
review price. Losing entry eligibility alone is not a sell signal. Suggested
quantities are review scenarios; Northstar never places an order.

For a budget `B`, price `P`, and buy fee `F`, a preview buys
`max(0, floor((B − F) / P))` whole shares. Sale proceeds subtract a fee only
when the investor has supplied that assumption. A displayed break-even is a
fee estimate, not a forecast or reason to hold.

## Risk and account performance

The portfolio risk view combines current weights with up to 252 matching daily
return intervals. It estimates covariance-based volatility, historical 95%
tail losses, drawdown, and explicit equity/FX shocks. It requires at least 60
shared intervals for every held asset; missing observations are not filled.
These measures describe past data or hypothetical shocks, not future loss
limits.

Account performance is separate: it values a verified opening snapshot plus a
reconciled transaction ledger. NOK investment P&L equals ending value minus
opening value minus net deposits and withdrawals. Daily-linked return assumes
external cash flows occur at each day's end; Modified Dietz weights them by
remaining calendar time. Incomplete prices, unsupported activity, or ledger
mismatches suppress the return rather than being treated as zero.

## Strategy evidence

The fixed strategy simulation makes monthly decisions from bars known at that
date and executes at the next common close. It keeps holdings until an explicit
technical exit, fills vacant slots in score order, and applies the stated buy
fee, optional slippage, and configured experiment sale fee. Its matched-date
OSEBX comparison is gross of index costs; percentage-point excess is not
risk-adjusted alpha. Strategy wealth starts before the first execution's costs:
a flat NOK 100,000 account paying one NOK 79 entry fee returns −0.079%, even
when the index return is zero.

The DNB OBX ETF comparison uses adjusted NOK market closes on the same sessions.
For initial capital `C`, entry fee `F`, fractional slippage `s`, and adjusted
entry/end prices `P0`, `PT`, ending wealth relative to initial capital is
`(1 − F/C) × (PT/P0) / (1 + s)`. Fund expenses already affect the fund price;
they are not deducted a second time. The fund tracks OBX rather than OSEBX GR.
Missing adjusted history or matching dates withholds the comparison.

Parameter selection uses training metrics in a retrospective chronological
split. Forward recommendation cohorts are a separate paper record: they use
the first later close as hypothetical entry, preserve the fee and budget
assumptions captured at the time, and cannot change advice unless the investor
explicitly promotes a model. Neither experiment is evidence of future returns.

For implementation details and limitations, see the [technical reference](REFERENCE.md#broad-scan-top-20-and-interactive-charts), especially its
[portfolio risk](REFERENCE.md#portfolio-risk-and-hypothetical-scenarios),
[strategy testing](REFERENCE.md#historical-experiments-and-forward-tracking),
[chronological holdout](REFERENCE.md#chronological-holdout-and-execution-sensitivity),
[share plans](REFERENCE.md#clear-buy-and-sell-quantities), and
[account performance](REFERENCE.md#ledger-derived-account-performance)
sections.
