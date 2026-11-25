"""Isolated authenticated server for browser checks. No real account or provider access."""
from datetime import datetime, timezone
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
            def do_GET(self):
                if self.path.startswith('/api/'):fixture.requests.append(('GET',self.path,bool(self.headers.get('Authorization'))))
                return super().do_GET()
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


class SessionFixture(Fixture):
    """A fixed Oslo reporting clock with known opening balances and cache states."""

    def __enter__(self):
        self.account_now = self.stamp('2025-04-16T20:30')
        super().__enter__()
        # Use a second temporary database so the general smoke fixture remains independent.
        app.DB = Path(self.temp.name) / 'session.db'
        app.save_position({'symbol':'SYNTH.OL','currency':'NOK','shares':100,'cost':100})
        app.save_position({'symbol':'US','currency':'USD','shares':10,'cost':100})
        app.write_meta('portfolio_preferences',{'cash_nok':80000})
        app.ledger_initialize({'date':'2025-04-14'})
        self.quotes('2025-04-16')
        self.events([('deposit',10000,0)])
        return self

    @staticmethod
    def stamp(value):
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()

    def events(self, rows):
        events = [
            {'id':index,'uid':'session-'+kind,'error':None,'date':'2025-04-16',
             'type':kind,'symbol':'SYNTH.OL' if kind == 'buy' else '', 'name':kind,
             'currency':'NOK','quantity':quantity,'net_cash':value,'fee':None}
            for index,(kind,value,quantity) in enumerate(rows, 1)
        ]
        snapshot = app.state()
        with app.connect() as db:
            result = transactions.apply(db,events,[{'id':row['id']} for row in events],
                                        app.read_meta('ledger_state'),snapshot['manual_portfolio_preferences'],snapshot['positions'])
            for key,value in [('ledger_state',result['ledger']),('portfolio_preferences',result['profile'])]:
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,json.dumps(value)))

    def quotes(self, date, fx=10, missing_oslo=False):
        prices = {
            'SYNTH.OL': ('NOK', {'2025-04-14':90, '2025-04-15':100, '2025-04-16':110}),
            'US': ('USD', {'2025-04-14':100, '2025-04-15':100, '2025-04-16':100, '2025-04-17':100}),
            'NOK=X': ('NOK', {'2025-04-14':10, '2025-04-15':10, '2025-04-16':fx, '2025-04-17':fx}),
        }
        with app.connect() as db:
            for symbol,(currency, closes) in prices.items():
                through = '2025-04-15' if missing_oslo and symbol == 'SYNTH.OL' else date
                hour = '14:25' if symbol == 'SYNTH.OL' else '20:00'
                history = [{'time':self.stamp(d+'T'+hour),'account_close':v}
                           for d,v in closes.items() if d <= through]
                bar = history[-1]
                quote = {'price':bar['account_close'],'asof':bar['time'],'currency':currency,
                         'account_history_version':1,'history':history,'source':'Synthetic session quotes'}
                db.execute('INSERT OR REPLACE INTO quotes VALUES (?,?)',(symbol,json.dumps(quote)))
