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
        app.save_settings({'universe':['SYNTH.OL'],'llm_enabled':False})
        app.save_position({'symbol':'SYNTH.OL','currency':'NOK','shares':3,'cost':100,'thesis':'Synthetic test only'})
        app.write_meta('portfolio_preferences',{'cash_nok':1000,'purchase_nok':0,'sectors':{'SYNTH.OL':'Industrials'}})
        cutoff=time.strftime('%Y-%m-%d',time.gmtime(now-60*86400));app.ledger_initialize({'date':cutoff})
        event={'id':1,'uid':'synthetic-income','error':None,'date':time.strftime('%Y-%m-%d',time.gmtime(now-20*86400)),'type':'dividend','symbol':'','name':'Synthetic income','currency':'NOK','quantity':0,'net_cash':10.,'fee':None}
        snapshot=app.state()
        with app.connect() as db:
            result=transactions.apply(db,[event],[{'id':1}],app.read_meta('ledger_state'),snapshot['manual_portfolio_preferences'],snapshot['positions'])
            for key,value in [('ledger_state',result['ledger']),('portfolio_preferences',result['profile'])]:db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,json.dumps(value)))
        snapshot=app.state(True);report=research.build_report(snapshot,['SYNTH.OL']);report['archive_run_id']=app.archive_run(report,snapshot,app.settings());app.write_meta('report',report)
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
