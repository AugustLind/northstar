"""Isolated authenticated server for browser checks. No real account or provider access."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
import app
import research
import transactions

class Fixture:
    def __enter__(self):
        self.temp=tempfile.TemporaryDirectory(prefix='northstar-auth-smoke-');self.old_db=app.DB;app.DB=Path(self.temp.name)/'account.db'
        self.key=secrets.token_urlsafe(32)
        names=('NORTHSTAR_ACCESS_KEY_HASH','NORTHSTAR_PUBLIC_ORIGIN','NORTHSTAR_PAGES_ORIGIN','NORTHSTAR_EMAIL_ENABLED')
        self.environment={k:os.environ.get(k) for k in names}
        os.environ.update(NORTHSTAR_ACCESS_KEY_HASH=hashlib.sha256(self.key.encode()).hexdigest(),NORTHSTAR_EMAIL_ENABLED='0')
        os.environ.pop('NORTHSTAR_PAGES_ORIGIN',None);os.environ.pop('NORTHSTAR_PUBLIC_ORIGIN',None)
        now=time.time();history=[{'time':now-(650-i)*86400,'close':100+i*.05,'raw_close':100+i*.05,'account_close':100+i*.05,'open':99.9+i*.05,'high':100.2+i*.05,'low':99.8+i*.05,'volume':100000} for i in range(650)]
        quote={'price':history[-1]['close'],'currency':'NOK','asof':history[-1]['time'],'fetched':now,'history':history,'source':'Synthetic authenticated smoke fixture','history_basis':'Synthetic daily close','account_history_version':1,'account_price_basis':'Synthetic historical share-unit close','history_version':3,'events_version':1,'events':[],'turnover20':2000000,'turnover_days':20,'name':'Synthetic smoke company'}
        with app.connect() as db:
            db.execute('INSERT INTO quotes VALUES (?,?)',('SYNTH.OL',json.dumps(quote)))
            db.execute('INSERT INTO quotes VALUES (?,?)',('OSEBX.OL',json.dumps(quote)))
            db.execute('INSERT INTO quotes VALUES (?,?)',('OBXD.OL',json.dumps({**quote,'history_basis':'Dividend/split adjusted close'})))
        app.save_settings({'universe':['SYNTH.OL'],'llm_enabled':False})
        app.save_position({'symbol':'SYNTH.OL','currency':'NOK','shares':3,'cost':100,'thesis':'Synthetic test only'})
        app.write_meta('portfolio_preferences',{'cash_nok':1000,'purchase_nok':0,'sectors':{'SYNTH.OL':'Industrials'}})
        cutoff=time.strftime('%Y-%m-%d',time.gmtime(now-60*86400));app.ledger_initialize({'date':cutoff})
        events=[
            {'id':1,'uid':'synthetic-income','error':None,'date':time.strftime('%Y-%m-%d',time.gmtime(now-30*86400)),'type':'dividend','symbol':'','name':'Synthetic income','currency':'NOK','quantity':0,'net_cash':10.,'fee':None},
            {'id':2,'uid':'synthetic-deposit','error':None,'date':time.strftime('%Y-%m-%d',time.gmtime(now-20*86400)),'type':'deposit','symbol':'','name':'Synthetic contribution','currency':'NOK','quantity':0,'net_cash':100.,'fee':None},
            {'id':3,'uid':'synthetic-withdrawal','error':None,'date':time.strftime('%Y-%m-%d',time.gmtime(now-10*86400)),'type':'withdrawal','symbol':'','name':'Synthetic withdrawal','currency':'NOK','quantity':0,'net_cash':-40.,'fee':None},
        ]
        snapshot=app.state()
        with app.connect() as db:
            result=transactions.apply(db,events,[{'id':row['id']} for row in events],app.read_meta('ledger_state'),snapshot['manual_portfolio_preferences'],snapshot['positions'])
            for key,value in [('ledger_state',result['ledger']),('portfolio_preferences',result['profile'])]:db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,json.dumps(value)))
        snapshot=app.state(True);report=research.build_report(snapshot,['SYNTH.OL']);report['archive_run_id']=app.archive_run(report,snapshot,app.settings());app.write_meta('report',report)
        self.expected_current_value_nok=3*quote['price']+1070
        self.requests=[];fixture=self
        class Handler(app.Handler):
            def log_message(self,*args):pass
            def handle(self):
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError):
                    # Chrome can close while parallel startup requests are in flight.
                    pass
            def do_GET(self):
                if self.path.startswith('/api/'):fixture.requests.append(('GET',self.path,bool(self.headers.get('Authorization'))))
                try:
                    return super().do_GET()
                except (BrokenPipeError, ConnectionResetError):
                    # The browser can cancel in-flight reads during navigation or sign-out.
                    pass
            def do_POST(self):
                fixture.requests.append(('POST',self.path,bool(self.headers.get('Authorization'))));return super().do_POST()
        self.server=app.ThreadingHTTPServer(('127.0.0.1',0),Handler);self.origin='http://127.0.0.1:'+str(self.server.server_port)
        os.environ['NORTHSTAR_PUBLIC_ORIGIN']=self.origin
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();return self
    def __exit__(self,*args):
        if hasattr(self,'server'):self.server.shutdown();self.server.server_close();self.thread.join(timeout=5)
        app.DB=self.old_db
        for k,v in self.environment.items():
            if v is None:os.environ.pop(k,None)
            else:os.environ[k]=v
        self.temp.cleanup()


def seed_candidates():
    """Six confirmed buys compete in the real shared-budget trade plan."""
    import decision_policy

    now = time.time()
    symbols = [f'IDEA{rank}.OL' for rank in range(1, 7)]
    report = app.read_meta('report')
    report.update(generated=now, policy_version=decision_policy.VERSION,
                  coverage={'requested': 6, 'analysed': 6, 'eligible': 6, 'unavailable': 0})
    base_card = report['cards'][0]
    report['cards'] = [
        {**base_card, 'symbol': symbol, 'name': f'Synthetic idea {rank}', 'rank': rank,
         'action': 'Consider buying', 'rank_eligible': True, 'composite': 100-rank,
         'price': 10, 'asof': now}
        for rank, symbol in reversed(list(enumerate(symbols, 1)))
    ]
    prefs = app.read_meta('portfolio_preferences')
    sectors = ['Energy', 'Materials', 'Health care', 'Financials', 'Utilities', 'Real estate']
    prefs['sectors'].update(zip(symbols, sectors))
    prefs.update(purchase_nok=1000, buy_fee_nok=0, max_stock_pct=10, reserve_pct=0)
    app.write_meta('portfolio_preferences', prefs)
    app.write_meta('signal_state', {
        symbol: {'policy_version': decision_policy.VERSION, 'intent': 'buy',
                 'since': now-3*86400, 'sessions': ['2026-01-02', '2026-01-05']}
        for symbol in symbols
    })
    with app.connect() as db:
        db.executemany('INSERT INTO quotes VALUES (?,?)', [
            (symbol, json.dumps({'price': 10, 'asof': now, 'currency': 'NOK'}))
            for symbol in symbols
        ])
    app.write_meta('report', report)
    return report


def session_timestamp(value):
    from datetime import datetime
    return datetime.fromisoformat(value).replace(tzinfo=app.account_performance.OSLO).timestamp()


def seed_today(stock_price, cash_events, quote_date='2025-01-06', quote_time='11:00'):
    """Start at NOK 100,000, with both NOK and USD exposure."""
    opening = [
        {'symbol': 'SYNTH.OL', 'currency': 'NOK', 'shares': 3, 'cost': 1000},
        {'symbol': 'USDTEST', 'currency': 'USD', 'shares': 1, 'cost': 100},
    ]
    held = {row['symbol']: dict(row) for row in opening}
    events = []
    for number, (kind, amount, quantity) in enumerate(cash_events, 1):
        row = {'uid': f'session-{number}', 'id': number, 'type': kind,
               'date': '2025-01-06', 'currency': 'NOK', 'net_cash': amount,
               'symbol': 'SYNTH.OL' if kind == 'buy' else '', 'quantity': quantity}
        events.append(row)
        app.account_performance.apply_event(held, row)
    for row in held.values():
        app.save_position(row)
    cash = 96000.0 + sum(row['net_cash'] for row in events)
    prefs = app.read_meta('portfolio_preferences')
    app.write_meta('portfolio_preferences', {**prefs, 'cash_nok': cash})
    positions = app.state()['positions']
    app.write_meta('ledger_state', {'cutoff_date': '2025-01-02', 'opening_cash_nok': 96000,
                                    'opening_positions': opening,
                                    'fingerprint': transactions.fingerprint(positions, cash)})
    rows = [('SYNTH.OL', 'NOK', stock_price, 1000), ('USDTEST', 'USD', 100, 100),
            ('NOK=X', 'NOK', 11, 10)]
    with app.connect() as db:
        db.execute('DELETE FROM ledger_events')
        db.executemany('INSERT INTO ledger_events VALUES (?,?,?)', [
            (row['uid'], row['date'], json.dumps(row)) for row in events
        ])
        for symbol, currency, latest, close in rows:
            quote = {'price': latest if quote_date == '2025-01-06' else close,
                     'currency': currency, 'asof': session_timestamp(quote_date+'T'+quote_time),
                     'account_history_version': 1, 'history': [
                         {'time': session_timestamp(date+'T16:30'), 'account_close': close, 'close': close}
                         for date in ('2025-01-02', '2025-01-03')
                     ]}
            db.execute('INSERT OR REPLACE INTO quotes VALUES (?,?)', (symbol, json.dumps(quote)))
