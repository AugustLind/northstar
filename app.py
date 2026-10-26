"""Local investment research notebook. Run: python3 app.py"""
import json
import math
import re
import sqlite3
import time
import threading
import os
import research
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).parent
DB = ROOT / 'data' / 'portfolio.db'
REFRESH_LOCK = threading.Lock()
WORKER = None
MODEL_LOCK = threading.Lock()

def request_origin_allowed(origin, host):
    allowed = os.environ.get('NORTHSTAR_PUBLIC_ORIGIN') or 'http://' + host
    return not origin or origin == allowed

def connect():
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, currency TEXT, shares REAL, cost REAL, thesis TEXT, review TEXT, below REAL, above REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS quotes (symbol TEXT PRIMARY KEY, payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, payload TEXT)')
    return db

def read_meta(key, default=None):
    with connect() as db:
        row = db.execute('SELECT payload FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row['payload']) if row else default

def write_meta(key, value):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value, allow_nan=False)))

def settings():
    saved = read_meta('settings', {})
    # Migrate the earlier US/large-cap screen once without changing holdings.
    if saved.get('market_scope') != research.SCOPE:
        saved = {k: v for k, v in saved.items() if k in ('model', 'llm_enabled', 'interval_minutes')}
    return {**research.DEFAULT_SETTINGS, **saved}

def save_settings(data):
    universe = data.get('universe', [])
    if not isinstance(universe, list) or not 1 <= len(universe) <= 100:
        raise ValueError('Choose between 1 and 100 Oslo stock symbols.')
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in universe))
    symbols = [s if s.endswith('.OL') else s + '.OL' for s in symbols]
    symbols = list(dict.fromkeys(symbols))
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,16}\.OL', s) for s in symbols):
        raise ValueError('Only Oslo candidates are supported. Use symbols such as NORBT.OL or BOUV.OL.')
    interval = int(data.get('interval_minutes', 360))
    if not 60 <= interval <= 1440:
        raise ValueError('Refresh interval must be 60–1440 minutes.')
    model = str(data.get('model', 'qwen2.5:3b'))
    if not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,100}', model):
        raise ValueError('Invalid Ollama model name.')
    if not isinstance(data.get('llm_enabled', False), bool):
        raise ValueError('LLM enabled must be true or false.')
    turnover = positive(data.get('min_turnover_nok', 250000))
    write_meta('settings', {'universe': symbols, 'interval_minutes': interval,
                           'model': model, 'llm_enabled': data.get('llm_enabled', False),
                           'min_turnover_nok': turnover, 'market_scope': research.SCOPE})

def positive(value, optional=False):
    if optional and value in ('', None):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Numbers must be finite and nonnegative.')
    return value

def save_position(data):
    symbol = str(data.get('symbol', '')).strip().upper()
    if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.\-^]{0,19}', symbol):
        raise ValueError('Enter a valid ticker, such as MSFT or EQNR.OL.')
    currency = data.get('currency')
    if currency not in ('USD', 'NOK'):
        raise ValueError('Choose USD or NOK.')
    values = (symbol, currency, positive(data.get('shares')), positive(data.get('cost')),
              str(data.get('thesis', ''))[:5000], str(data.get('review', ''))[:5000],
              positive(data.get('below'), True), positive(data.get('above'), True))
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?,?)', values)

def fetch_quote(symbol):
    # Unofficial public endpoint: errors are surfaced, never replaced with sample prices.
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe='') + '?range=1y&interval=1d'
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=12) as response:
        result = json.load(response)['chart']['result'][0]
    meta = result['meta']
    close = [v for v in result['indicators']['quote'][0]['close'] if v is not None and math.isfinite(v)]
    series = result['indicators'].get('adjclose', [{}])[0].get('adjclose')
    adjusted = series is not None
    if series is None:
        series = result['indicators']['quote'][0]['close']
    history = [{'time': t, 'close': v} for t, v in zip(result.get('timestamp', []), series)
               if isinstance(v, (int, float)) and math.isfinite(v) and v > 0]
    raw = result['indicators']['quote'][0]
    turnover = [p * v for p, v in zip(raw['close'][-20:], raw.get('volume', [])[-20:])
                if isinstance(p, (int, float)) and isinstance(v, (int, float)) and
                math.isfinite(p) and math.isfinite(v) and p > 0 and v >= 0]
    price = float(meta['regularMarketPrice'])
    if price <= 0 or not math.isfinite(price):
        raise ValueError('Provider returned an invalid price.')
    return {'price': price, 'currency': meta['currency'], 'asof': meta['regularMarketTime'],
            'fetched': time.time(), 'source': 'Yahoo Finance (unofficial)',
            'history': history, 'history_basis': 'Dividend/split adjusted close' if adjusted else 'Provider daily close',
            'name': meta.get('longName') or meta.get('shortName') or symbol,
            'turnover20': sum(turnover)/len(turnover) if turnover else None, 'turnover_days': len(turnover),
            'ma200': sum(close[-200:])/200 if len(close) >= 200 else None,
            'previous': close[-2] if len(close) >= 2 else None}

def refresh(extra_symbols=None):
    with REFRESH_LOCK:
        return _refresh(extra_symbols)

def _refresh(extra_symbols=None):
    with connect() as db:
        positions = list(db.execute('SELECT symbol, currency FROM positions'))
    lookups = {r['symbol']: (r['symbol'] + '.OL' if r['currency'] == 'NOK' and '.' not in r['symbol'] else r['symbol']) for r in positions}
    for symbol in extra_symbols or []:
        lookups.setdefault(symbol, symbol)
    lookups['NOK=X'] = 'NOK=X'
    symbols = list(dict.fromkeys(lookups.values()))
    def one(symbol):
        try:
            payload = fetch_quote(symbol)
            with connect() as db:
                for key, lookup in lookups.items():
                    if lookup == symbol:
                        db.execute('INSERT OR REPLACE INTO quotes VALUES (?,?)', (key, json.dumps(payload)))
            return None
        except Exception as error:
            if isinstance(error, HTTPError):
                reason = ('ticker not found' if error.code == 404 else
                          'provider rate limit; try again later' if error.code == 429 else
                          'provider returned HTTP ' + str(error.code))
            elif isinstance(error, (URLError, TimeoutError)):
                reason = 'provider could not be reached; check connection and try again'
            else:
                reason = 'provider returned unusable data; check ticker and retry'
            return f'{symbol}: {reason}. Any previous quote retains its original timestamp.'
    with ThreadPoolExecutor(max_workers=4) as pool:
        return [error for error in pool.map(one, symbols) if error]

def state():
    with connect() as db:
        return {'positions': [dict(r) for r in db.execute('SELECT * FROM positions ORDER BY symbol')],
                'quotes': {r['symbol']: json.loads(r['payload']) for r in db.execute('SELECT * FROM quotes')}}

class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        payload = json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/api/research':
            return self.send_json(WORKER.view() if WORKER else {'report': read_meta('report'), 'settings': settings(), 'worker': {}})
        if self.path == '/api/state':
            return self.send_json(state())
        files = {'/': ('index.html', 'text/html'), '/recommendations': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css'), '/advice.js': ('advice.js', 'text/javascript'), '/favicon.ico': ('favicon.svg', 'image/svg+xml')}
        if self.path not in files:
            return self.send_error(404)
        name, mime = files[self.path]
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.end_headers()
        self.wfile.write((ROOT / 'static' / name).read_bytes())

    def do_POST(self):
        # Reject browser cross-origin writes to this local service.
        origin = self.headers.get('Origin')
        if not request_origin_allowed(origin, self.headers.get('Host', '')):
            return self.send_json({'error': 'Cross-origin request rejected.'}, 403)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json({'error': 'JSON required.'}, 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 50000:
                raise ValueError('Invalid request size.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('JSON object required.')
            if self.path == '/api/position':
                save_position(data)
                if WORKER:
                    WORKER.trigger()
            elif self.path == '/api/delete':
                with connect() as db:
                    db.execute('DELETE FROM positions WHERE symbol=?', (data['symbol'],))
                if WORKER:
                    WORKER.trigger()
            elif self.path == '/api/refresh':
                return self.send_json({'errors': refresh()})
            elif self.path == '/api/analyze':
                if not WORKER:
                    return self.send_json({'error': 'Background worker is not started.'}, 503)
                WORKER.trigger()
                return self.send_json({'queued': True})
            elif self.path == '/api/settings':
                save_settings(data)
                if WORKER:
                    WORKER.trigger()
            elif self.path == '/api/ask':
                config = settings()
                if not config['llm_enabled']:
                    return self.send_json({'error': 'Enable local AI in Research settings first.'}, 400)
                question = str(data.get('question', '')).strip()
                if not 1 <= len(question) <= 2000:
                    raise ValueError('Enter a question of 1–2000 characters.')
                if not MODEL_LOCK.acquire(blocking=False):
                    return self.send_json({'error': 'A question is already being answered. Please wait.'}, 429)
                try:
                    report = research.build_report(state(), config['universe'], config['min_turnover_nok'])
                    answer = research.local_answer(config['model'], report, question)
                    return self.send_json({'answer': answer, 'model': config['model'], 'generated': time.time()})
                except research.ModelBusy as error:
                    return self.send_json({'error': research.llm_error(error, config['model'])}, 429)
                except Exception as error:
                    return self.send_json({'error': research.llm_error(error, config['model'])}, 503)
                finally:
                    MODEL_LOCK.release()
            else:
                return self.send_error(404)
            self.send_json({'ok': True})
        except (ValueError, TypeError, KeyError) as error:
            self.send_json({'error': str(error)}, 400)

if __name__ == '__main__':
    connect().close()
    WORKER = research.ResearchWorker(refresh, state, read_meta, write_meta, settings)
    # Bind first so a second process cannot start a competing background worker.
    server = ThreadingHTTPServer(('127.0.0.1', 8000), Handler)
    WORKER.start()
    print('Open http://127.0.0.1:8000 — press Ctrl+C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        WORKER.stop.set()
        WORKER.wake.set()
    finally:
        server.server_close()
