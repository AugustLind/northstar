"""Shared technical entry/exit policy; scores order qualifying entries only."""
import math

VERSION = 'technical-entry-exit-v1'
MAX_CANDIDATES = 20
SELL_SIGNALS = frozenset({'Consider reducing / selling', 'Review sell threshold',
                          'Consider taking profits'})


def trend_score(metrics):
    return 25 * sum((metrics['close'] > metrics['ma200'], metrics['close'] > metrics['ma50'],
                     metrics['ma50'] > metrics['ma200'], metrics['momentum3m'] > 0))


def decide(metrics, price, position=None, min_turnover_nok=250000):
    """Use measured daily-close inputs; personal review prices use the latest quote."""
    held = bool(position and position.get('shares', 0) > 0)
    required = ('close', 'ma50', 'ma200', 'momentum3m', 'volatility', 'extension50')
    if not all(isinstance(metrics.get(k), (int, float)) and math.isfinite(metrics[k]) for k in required):
        return {'action': 'Insufficient data', 'rank_eligible': False,
                'policy_reasons': ['Complete finite technical measurements required.']}
    trend = trend_score(metrics) == 100
    turnover = metrics.get('turnover20')
    known = (metrics.get('turnover_days', 0) >= 15 and isinstance(turnover, (int, float))
             and math.isfinite(turnover) and turnover >= 0)
    reasons = []
    if not known:
        reasons.append('Too little valid turnover data to assess liquidity.')
    elif turnover < min_turnover_nok:
        reasons.append(f'Average daily traded value is below the NOK {min_turnover_nok:,.0f} liquidity floor.')
    if not trend:
        reasons.append('The complete four-condition trend screen is not met.')
    if metrics['volatility'] >= 50:
        reasons.append('Annualised volatility must be below 50%.')
    if metrics['extension50'] >= 15:
        reasons.append('Daily close must be less than 15% above its 50-session average.')
    entry = not reasons
    if held:
        action = 'Hold / monitor'
        if metrics['close'] < metrics['ma200'] and metrics['momentum3m'] < 0:
            action = 'Consider reducing / selling'
            reasons.insert(0, 'Both the long-term price trend and three-month momentum are negative.')
        if position.get('below') is not None and price <= position['below']:
            action = 'Review sell threshold'
            reasons.insert(0, 'Your lower review price has been reached.')
        elif position.get('above') is not None and price >= position['above']:
            action = 'Consider taking profits'
            reasons.insert(0, 'Your upper review price has been reached.')
    elif not known:
        action = 'Wait / liquidity unknown'
    elif turnover < min_turnover_nok:
        action = 'Wait / low liquidity'
    else:
        action = 'Consider buying' if entry else 'Wait / watch'
    entry = entry and action not in SELL_SIGNALS
    if entry:
        reasons.insert(0, 'All four trend conditions, liquidity, volatility and price-extension filters pass.'
                       + (' Eligible for an additional purchase, subject to portfolio limits.' if held else ''))
    return {'action': action, 'rank_eligible': entry, 'policy_reasons': reasons}


def buy_signal(card):
    return bool(card.get('rank_eligible') and card.get('action') in ('Consider buying', 'Hold / monitor'))


def rank_key(card):
    return (-card.get('composite', -1), card['symbol'])


def entries(cards, limit=MAX_CANDIDATES):
    return sorted((c for c in cards if buy_signal(c)), key=rank_key)[:limit]
