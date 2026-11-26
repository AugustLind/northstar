"""Annual reported company figures with explicit periods, currencies and missing data.

Unofficial Yahoo timeseries adapter; no paid API, dependencies, or inferred numbers.
Not a point-in-time filing database. Does not alter technical rankings.
"""
import datetime as dt
import json
import math
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

FIELDS = {
    'TotalRevenue': 'revenue', 'OperatingIncome': 'operating_income', 'NetIncome': 'net_income',
    'OperatingCashFlow': 'operating_cash_flow', 'CapitalExpenditure': 'capital_expenditure',
    'FreeCashFlow': 'free_cash_flow', 'TotalDebt': 'debt',
    'CashCashEquivalentsAndShortTermInvestments': 'cash', 'StockholdersEquity': 'equity',
    'OrdinarySharesNumber': 'ordinary_shares', 'DilutedAverageShares': 'diluted_shares',
    'DilutedEPS': 'diluted_eps',
}


def canonical(symbol):
    symbol = str(symbol).strip().upper()
    if not symbol.endswith('.OL'):
        symbol += '.OL'
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,16}\.OL', symbol):
        raise ValueError('Enter an Oslo stock symbol.')
    return symbol


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse(payload, symbol, now=None):
    now = time.time() if now is None else now
    today = dt.datetime.fromtimestamp(now, dt.timezone.utc).date()
    result = (payload.get('timeseries') or {}).get('result') or []
    series = {name: [] for name in FIELDS.values()}
    for record in result:
        for source, target in FIELDS.items():
            for entry in record.get('annual' + source, []) or []:
                if not isinstance(entry, dict) or entry.get('periodType') not in (None, '12M'):
                    continue
                try:
                    period = dt.date.fromisoformat(entry['asOfDate'])
                except (KeyError, ValueError, TypeError):
                    continue
                raw = (entry.get('reportedValue') or {}).get('raw')
                if period > today or not number(raw):
                    continue
                currency = entry.get('currencyCode')
                currency = currency.upper() if isinstance(currency, str) and re.fullmatch('[A-Za-z]{3}', currency) else None
                series[target].append({'period': period.isoformat(), 'value': raw, 'currency': currency})
    for name, rows in series.items():
        series[name] = sorted({row['period']: row for row in rows}.values(), key=lambda row: row['period'], reverse=True)[:4]
    if not any(series.values()):
        raise ValueError('Provider returned no usable annual financial statements.')
    return {'symbol': symbol, 'fetched': now, 'attempted': now, 'series': series, 'error': None,
            'source': 'Yahoo Finance annual timeseries (unofficial)',
            'source_url': 'https://finance.yahoo.com/quote/' + quote(symbol, safe='') + '/financials/',
            'method': 'Reported annual observations. Fiscal period end is not the publication date. Not point-in-time data.'}


def fetch(symbol):
    symbol = canonical(symbol)
    now = time.time()
    query = urlencode({'symbol': symbol, 'type': ','.join('annual' + key for key in FIELDS),
                       'period1': int(now - 5 * 366 * 86400), 'period2': int(now + 86400)})
    url = 'https://query2.finance.yahoo.com/ws/fundamentals-timeseries/v1/finance/timeseries/' + quote(symbol, safe='') + '?' + query
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(request, timeout=15) as response:
        return parse(json.load(response), symbol, now)


def error_message(error):
    if isinstance(error, HTTPError):
        if error.code == 429:
            return 'Provider rate limit. Cached figures retain their original dates.'
        return f'Annual financial data unavailable (provider HTTP {error.code}).'
    if isinstance(error, (URLError, TimeoutError)):
        return 'Financial-data provider could not be reached.'
    return 'Provider returned no usable annual financial data.'


def analyse(record, market_quote=None, now=None):
    now = time.time() if now is None else now
    base = {'status': 'unavailable', 'metrics': {}, 'signals': [], 'missing': [],
            'fetched': (record or {}).get('fetched'), 'error': (record or {}).get('error'),
        'source': (record or {}).get('source'), 'source_url': (record or {}).get('source_url'),
            'period': None, 'history': {}, 'changes_ranking': False}
    if not record or not record.get('series'):
        return base
    series = record['series']
    dates = [row['period'] for rows in series.values() for row in rows]
    if not dates:
        return base
    # Anchor income/CF to the latest reported revenue year; do not silently mix dates.
    anchor = next((series[name][0]['period'] for name in ('revenue', 'net_income', 'operating_cash_flow') if series.get(name)), max(dates))
    period_date = dt.date.fromisoformat(anchor)
    age = (dt.datetime.fromtimestamp(now, dt.timezone.utc).date() - period_date).days
    stale = age > 550 or now - record.get('fetched', 0) > 7 * 86400
    base.update(period=anchor, status='stale' if stale else 'partial', history=series)
    metrics = base['metrics']
    def row(name):
        return next((r for r in series.get(name, []) if r['period'] == anchor), None)
    def put(name, value, unit, period=anchor, currency=None, note=None):
        if number(value):
            metrics[name] = {'value': value, 'unit': unit, 'period': period, 'currency': currency, 'note': note}
    def amount(name):
        item = row(name)
        if item:
            put(name, item['value'], 'shares' if name in ('ordinary_shares', 'diluted_shares') else 'amount', currency=item['currency'])
        return item
    def same_currency(*items):
        return all(item and item.get('currency') for item in items) and len({item['currency'] for item in items}) == 1
    for name in FIELDS.values():
        amount(name)
    revenue, income, ocf, capex = row('revenue'), row('operating_income'), row('operating_cash_flow'), row('capital_expenditure')
    if not row('free_cash_flow') and same_currency(ocf, capex):
        put('free_cash_flow', ocf['value'] - abs(capex['value']), 'amount', currency=ocf['currency'],
            note='Derived: operating cash flow minus absolute capital expenditure.')
    if revenue and revenue['value'] > 0:
        if same_currency(revenue, income):
            put('operating_margin', income['value'] / revenue['value'] * 100, 'percent')
        net = row('net_income')
        if same_currency(revenue, net):
            put('net_margin', net['value'] / revenue['value'] * 100, 'percent')
        older = [r for r in series.get('revenue', []) if r['period'] < anchor]
        if older:
            prior = older[0]
            gap = (period_date - dt.date.fromisoformat(prior['period'])).days
            if 300 <= gap <= 430 and prior['value'] > 0 and same_currency(revenue, prior):
                put('revenue_growth', (revenue['value'] / prior['value'] - 1) * 100, 'percent',
                    note='Compared with annual period ending ' + prior['period'])
    cash, debt, equity = row('cash'), row('debt'), row('equity')
    if same_currency(cash, debt):
        put('net_cash', cash['value'] - debt['value'], 'amount', currency=cash['currency'])
    if same_currency(debt, equity) and equity['value'] > 0:
        put('debt_to_equity', debt['value'] / equity['value'], 'ratio', note='Sector-dependent; not comparable across banks and industrial companies.')
    for name in ('diluted_shares', 'ordinary_shares'):
        latest = row(name)
        older = [r for r in series.get(name, []) if r['period'] < anchor]
        if latest and older and older[0]['value'] > 0 and 300 <= (period_date-dt.date.fromisoformat(older[0]['period'])).days <= 430:
            put('share_count_change', (latest['value']/older[0]['value']-1)*100, 'percent',
                note=f'Uses {name}. Splits and acquisitions can change shares; this does not prove dilution.')
            break
    eps = row('diluted_eps')
    if (eps and eps['value'] > 0 and market_quote and same_currency(eps, market_quote)
            and number(market_quote.get('price')) and market_quote['price'] > 0
            and number(market_quote.get('asof'))
            and -300 <= now-market_quote.get('asof', 0) < 4*86400):
        put('annual_pe_proxy', market_quote['price']/eps['value'], 'ratio',
            note='Latest quote divided by latest annual diluted EPS; not trailing-twelve-month P/E. EPS and quote currencies match.')
    signals = base['signals']
    if 'revenue_growth' in metrics:
        value = metrics['revenue_growth']['value']
        signals.append(f'Annual revenue {"increased" if value >= 0 else "decreased"} {abs(value):.1f}% versus the previous comparable year.')
    if 'operating_margin' in metrics:
        signals.append(f'Operating margin was {metrics["operating_margin"]["value"]:.1f}% for this fiscal year.')
    if 'operating_cash_flow' in metrics:
        signals.append('Reported operating cash flow was ' + ('negative.' if metrics['operating_cash_flow']['value'] < 0 else 'positive.' if metrics['operating_cash_flow']['value'] > 0 else 'zero.'))
    if equity and equity['value'] <= 0:
        signals.append('Reported equity was non-positive; a debt-to-equity ratio is not shown.')
    if 'share_count_change' in metrics and metrics['share_count_change']['value'] > 2:
        signals.append('Reported share count rose; check splits, acquisitions and new issuance before interpreting this as dilution.')
    for name in ('revenue', 'net_income', 'operating_cash_flow', 'debt', 'cash', 'diluted_eps'):
        if name not in metrics:
            base['missing'].append(name)
    if not stale:
        base['status'] = 'available' if not base['missing'] else 'partial'
    if stale:
        signals.insert(0, 'Financial data is old; refresh and verify newer company reports before relying on it.')
    if market_quote and eps and eps.get('currency') != market_quote.get('currency'):
        signals.append('Quote and EPS currencies differ or are unknown; no P/E proxy is calculated.')
    return base


class Worker:
    def __init__(self, read, write, symbols):
        self.read, self.write, self.symbols = read, write, symbols
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.priority = []

    def request(self, symbol):
        symbol = canonical(symbol)
        with self.lock:
            if symbol not in self.priority:
                self.priority.append(symbol)
        self.wake.set()

    def run_scan(self):
        pending = list(dict.fromkeys(canonical(s) for s in self.symbols()))
        all_symbols, counted = set(pending), set()
        progress = {'done': 0, 'total': len(pending), 'running': True, 'started': time.time(), 'failed': 0}
        self.write('fundamentals_progress', progress.copy())
        while not self.stop.is_set():
            with self.lock:
                symbol = self.priority.pop(0) if self.priority else None
            force = symbol is not None
            if not force:
                if not pending:
                    break
                symbol = pending.pop(0)
            elif symbol in pending:
                pending.remove(symbol)
            if symbol not in all_symbols:
                all_symbols.add(symbol)
                progress['total'] += 1
            key = 'fundamentals:' + symbol
            old = self.read(key, {})
            ttl = 6*3600 if old.get('error') else 24*3600
            if not force and time.time() - old.get('attempted', 0) < ttl:
                if symbol not in counted:
                    counted.add(symbol)
                    progress['done'] += 1
                continue
            try:
                result = fetch(symbol)
            except Exception as error:
                result = {**old, 'symbol': symbol, 'attempted': time.time(), 'error': error_message(error)}
                progress['failed'] += 1
                if isinstance(error, HTTPError) and error.code in (401, 403, 429):
                    progress['error'] = error_message(error) + ' Remaining requests are deferred to the next scheduled scan.'
            self.write(key, result)
            if symbol not in counted:
                counted.add(symbol)
                progress['done'] += 1
            self.write('fundamentals_progress', progress.copy())
            if progress.get('error'):
                break
        progress.update(running=False, finished=time.time())
        self.write('fundamentals_progress', progress.copy())

    def loop(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:
                self.run_scan()
            except Exception:
                self.write('fundamentals_progress', {'running': False, 'error': 'Financial scan failed; existing data retained.'})
            self.wake.wait(6*3600)

    def start(self):
        threading.Thread(target=self.loop, name='northstar-fundamentals', daemon=True).start()
