"""Experimental, signal-conditioned return ranges from recorded Oslo price history."""
import bisect
import datetime as dt
import math

import decision_policy as policy

HORIZON_SESSIONS = 63
MIN_SIGNAL_SAMPLES = 20
MIN_HOLDOUT_FORECASTS = 20
HISTORY_BASIS = 'Dividend/split adjusted close'
METHOD = (
    'Experimental historical scenario range. At month end, the current technical '
    'entry policy is replayed using only prices available through that session. '
    'For this stock, completed returns from prior qualifying signals over the next '
    '63 Oslo sessions form the median and 10th–90th percentile range. '
    'The range is descriptive, not a probability guarantee, target price or advice. '
    'It uses today’s configured universe and provider history, which may omit delisted '
    'stocks and contain revised adjusted prices. Monthly 63-session outcomes overlap.'
)


def _valid_history(quote):
    if not quote or quote.get('currency') != 'NOK':
        return []
    points = {}
    for row in quote.get('history', []):
        stamp, close = row.get('time'), row.get('close')
        if (isinstance(stamp, (int, float)) and math.isfinite(stamp) and stamp > 0
                and isinstance(close, (int, float)) and math.isfinite(close) and close > 0):
            points[int(stamp // 86400)] = row
    return [points[day] for day in sorted(points)]


def _quantile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _month_ends(days):
    result = []
    for index, day in enumerate(days):
        current = dt.datetime.fromtimestamp(day * 86400, dt.timezone.utc)
        following = dt.datetime.fromtimestamp(days[index + 1] * 86400, dt.timezone.utc) if index + 1 < len(days) else None
        if following is None or (current.year, current.month) != (following.year, following.month):
            result.append(index)
    return result


def _turnover(history):
    values = []
    for point in history[-20:]:
        volume = point.get('volume')
        if isinstance(volume, (int, float)) and math.isfinite(volume) and volume >= 0:
            values.append(point['close'] * volume)
    return (sum(values) / len(values) if values else None, len(values))


def _historical_samples(quotes, symbols, floor, screen):
    symbols = sorted({symbol for symbol in symbols if isinstance(symbol, str) and symbol.endswith('.OL')})
    histories = {symbol: _valid_history(quotes.get(symbol, {})) for symbol in symbols}
    histories = {symbol: rows for symbol, rows in histories.items() if rows}
    market = _valid_history(quotes.get('OSEBX.OL', {}))
    if not market and histories:
        market = max(histories.values(), key=len)
    market_days = [int(point['time'] // 86400) for point in market]
    if len(market_days) <= HORIZON_SESSIONS:
        return {}, {}

    by_day = {symbol: {int(point['time'] // 86400): point for point in rows}
              for symbol, rows in histories.items()}
    day_lists = {symbol: [int(point['time'] // 86400) for point in rows]
                 for symbol, rows in histories.items()}
    signal_samples = {symbol: [] for symbol in symbols}
    baseline_samples = {symbol: [] for symbol in symbols}
    for origin_index in _month_ends(market_days):
        target_index = origin_index + HORIZON_SESSIONS
        if origin_index < 199 or target_index >= len(market_days):
            continue
        origin_day, target_day = market_days[origin_index], market_days[target_index]
        for symbol, rows in histories.items():
            daily = by_day[symbol]
            origin = daily.get(origin_day)
            if origin is None:
                continue
            end = daily.get(target_day)
            if end is not None and quotes[symbol].get('history_basis') == HISTORY_BASIS:
                baseline_samples[symbol].append({
                    'origin_day': origin_day, 'end_day': target_day,
                    'return_pct': (end['close'] / origin['close'] - 1) * 100,
                })
            if quotes[symbol].get('history_basis') != HISTORY_BASIS:
                continue
            cut = bisect.bisect_right(day_lists[symbol], origin_day)
            prior = rows[:cut]
            if len(prior) < 200:
                continue
            turnover, turnover_days = _turnover(prior)
            quote = {
                'price': origin['close'], 'currency': 'NOK', 'asof': origin['time'],
                'history': prior, 'turnover20': turnover, 'turnover_days': turnover_days,
                'history_basis': HISTORY_BASIS, 'source': quotes[symbol].get('source'),
                'name': quotes[symbol].get('name', symbol),
            }
            card = screen(symbol, quote, min_turnover_nok=floor, as_of=origin['time'] + 1)
            if end is not None and card.get('rank_eligible') and card.get('action') == 'Consider buying':
                signal_samples[symbol].append({
                    'origin_day': origin_day, 'end_day': target_day,
                    'return_pct': (end['close'] / origin['close'] - 1) * 100,
                    'score': card.get('composite'),
                })
    return signal_samples, baseline_samples


def _walk_forward(signal_samples, baseline_samples):
    outcomes = []
    for symbol, events in signal_samples.items():
        baseline = baseline_samples.get(symbol, [])
        for event in events:
            prior_signal = [row['return_pct'] for row in events
                            if row['origin_day'] < event['origin_day'] and row['end_day'] < event['origin_day']]
            prior_baseline = [row['return_pct'] for row in baseline
                              if row['origin_day'] < event['origin_day'] and row['end_day'] < event['origin_day']]
            if len(prior_signal) < MIN_SIGNAL_SAMPLES or len(prior_baseline) < MIN_SIGNAL_SAMPLES:
                continue
            low, median, high = (_quantile(prior_signal, .1), _quantile(prior_signal, .5),
                                 _quantile(prior_signal, .9))
            base_median = _quantile(prior_baseline, .5)
            outcomes.append({
                'symbol': symbol,
                'covered': low <= event['return_pct'] <= high,
                'median_error': abs(median - event['return_pct']),
                'baseline_error': abs(base_median - event['return_pct']),
            })
    count = len(outcomes)
    if not count:
        return {'status': 'insufficient_holdout', 'forecasts': 0, 'coverage_pct': None,
                'median_forecast_mae_pct': None, 'baseline_median_forecast_mae_pct': None,
                'beats_baseline': None}
    median_error = sum(row['median_error'] for row in outcomes) / count
    baseline_error = sum(row['baseline_error'] for row in outcomes) / count
    coverage = sum(row['covered'] for row in outcomes) / count * 100
    supported = count >= MIN_HOLDOUT_FORECASTS and 70 <= coverage <= 90 and median_error < baseline_error
    return {
        'status': 'initial_support' if supported else 'experimental', 'forecasts': count,
        'coverage_pct': round(coverage, 1), 'median_forecast_mae_pct': round(median_error, 2),
        'baseline_median_forecast_mae_pct': round(baseline_error, 2),
        'beats_baseline': median_error < baseline_error,
    }


def _estimate(symbol, signal_samples, baseline_samples, current_day):
    samples = [row for row in signal_samples.get(symbol, []) if row['end_day'] <= current_day]
    validation = _walk_forward({symbol: signal_samples.get(symbol, [])},
                               {symbol: baseline_samples.get(symbol, [])})
    base = {
        'status': 'insufficient_history', 'horizon_sessions': HORIZON_SESSIONS,
        'sample_count': len(samples), 'minimum_samples': MIN_SIGNAL_SAMPLES,
        'history_basis': HISTORY_BASIS, 'method': METHOD, 'source': 'Yahoo Finance (unofficial)',
        'source_url': 'https://finance.yahoo.com/quote/' + symbol + '/history/',
        'validation': validation,
        'samples': [
            {'from_day': row['origin_day'], 'to_day': row['end_day'],
             'return_pct': round(row['return_pct'], 2),
             'score': row.get('score')}
            for row in samples[-12:]
        ],
    }
    if len(samples) < MIN_SIGNAL_SAMPLES:
        return base
    values = [row['return_pct'] for row in samples]
    base.update(status='experimental', p10_pct=round(_quantile(values, .1), 2),
                median_pct=round(_quantile(values, .5), 2), p90_pct=round(_quantile(values, .9), 2))
    return base


def attach(cards, quotes, top_symbols, now, floor, screen):
    """Attach ranges only to current top-ranked stocks and eligible holdings."""
    from fundamentals import canonical

    selected = {canonical(symbol) for symbol in top_symbols}
    selected.update(canonical(card['symbol']) for card in cards if card.get('held'))
    if not selected:
        return
    by_symbol = {canonical(card['symbol']): card for card in cards}
    estimate_symbols = []
    for symbol in selected:
        card = by_symbol.get(symbol)
        if card is None:
            continue
        if not policy.buy_signal(card):
            card['return_estimate'] = {
                'status': 'not_applicable', 'reason': 'Current entry screen not passed.',
                'method': METHOD,
            }
            continue
        quote = quotes.get(card['symbol']) or quotes.get(symbol)
        if not quote or quote.get('history_basis') != HISTORY_BASIS:
            card['return_estimate'] = {
                'status': 'unavailable', 'reason': 'Dividend/split adjusted price history is unavailable.',
                'method': METHOD,
            }
            continue
        estimate_symbols.append(symbol)
    if not estimate_symbols:
        return
    signal_samples, baseline_samples = _historical_samples(
        quotes, estimate_symbols, floor, screen)
    current_day = int(now // 86400)
    for symbol in estimate_symbols:
        by_symbol[symbol]['return_estimate'] = _estimate(
            symbol, signal_samples, baseline_samples, current_day)
