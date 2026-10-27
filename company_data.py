"""Source-backed company classification and supplementary annual-quality evidence."""
import json
import re
from html.parser import HTMLParser
import threading
import time
from urllib.request import Request,urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError
import fundamentals

SECTOR_MAP={'Technology':'Information technology','Basic Materials':'Materials','Consumer Cyclical':'Consumer discretionary',
            'Consumer Defensive':'Consumer staples','Healthcare':'Health care','Financial Services':'Financials',
            'Communication Services':'Communication services','Real Estate':'Real estate','Energy':'Energy',
            'Industrials':'Industrials','Utilities':'Utilities'}
BLOCKED={'yahoo':0.,'profile':0.}
ISSUERS={'WWIB.OL':'WWI.OL','ODFB.OL':'ODF.OL'}


def issuer(symbol,records=None):
    return ISSUERS.get(symbol,symbol)


def parse(payload,symbol,now=None):
    now=time.time() if now is None else now
    rows=[r for r in payload.get('quotes',[]) if r.get('symbol')==symbol and r.get('quoteType') in (None,'EQUITY')]
    if len(rows)!=1:
        raise ValueError('No unique company record for this exact Oslo symbol.')
    row=rows[0];sector=SECTOR_MAP.get(row.get('sector'))
    return {'symbol':symbol,'name':row.get('longname') or row.get('shortname') or symbol,
            'sector':sector,'issuer_source':'Reviewed share-class mapping' if symbol in ISSUERS or symbol in ISSUERS.values() else 'Ticker identity; other issuer relationships unverified','industry':str(row.get('industry') or '')[:150], 'issuer':issuer(symbol),
            'fetched':now,'attempted':now,'source':'Yahoo Finance exact-symbol search (unofficial)',
            'source_url':'https://finance.yahoo.com/quote/'+symbol+'/profile/',
            'status':'available' if sector else 'partial','error':None}


class ProfileTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.rows={};self.cells=[];self.cell=None;self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if tag=='tr':self.cells=[]
        if tag in ('td','th'):self.cell=[]
    def handle_data(self,data):
        if self.cell is not None and not self.skip:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
        if tag in ('td','th') and self.cell is not None:
            self.cells.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and len(self.cells)==2:self.rows[self.cells[0]]=self.cells[1]


def parse_profile(html,symbol,now=None):
    parser=ProfileTable();parser.feed(html);rows=parser.rows
    if rows.get('Ticker Symbol','').upper()!=symbol[:-3] or rows.get('Exchange') not in ('Oslo Børs','Oslo Stock Exchange','Euronext Oslo'):
        raise ValueError('Company profile does not identify the exact Oslo ticker/exchange.')
    choices={k.casefold():v for k,v in SECTOR_MAP.items()}
    choices.update({v.casefold():v for v in SECTOR_MAP.values()})
    sector=choices.get(rows.get('Sector','').casefold())
    if not sector:raise ValueError('Profile has no recognized sector classification.')
    isin=rows.get('ISIN Number')
    if not isin or not re.fullmatch(r'[A-Z]{2}[A-Z0-9]{9}[0-9]',isin):isin=None
    now=time.time() if now is None else now
    return {'symbol':symbol,'name':symbol,'sector':sector,'industry':rows.get('Industry','')[:150],
            'isin':isin,'share_class':rows.get('Share Class'),'issuer':issuer(symbol),
            'issuer_source':'Reviewed share-class mapping' if symbol in ISSUERS or symbol in ISSUERS.values() else 'Ticker identity; other issuer relationships unverified',
            'fetched':now,'attempted':now,'source':'Stock Analysis public Oslo company profile',
            'source_url':'https://stockanalysis.com/quote/osl/'+symbol[:-3]+'/company/','status':'available','error':None}


def fetch(symbol):
    symbol=fundamentals.canonical(symbol);primary=None
    if time.time()>=BLOCKED['yahoo']:
        url='https://query1.finance.yahoo.com/v1/finance/search?'+urlencode({'q':symbol,'quotesCount':10,'newsCount':0})
        try:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=12) as response:
                primary=parse(json.load(response),symbol)
            if primary.get('sector'):return primary
        except Exception as error:
            if isinstance(error,HTTPError) and error.code in (401,403,429):BLOCKED['yahoo']=time.time()+3600
    if time.time()>=BLOCKED['profile']:
        url='https://stockanalysis.com/quote/osl/'+symbol[:-3]+'/company/'
        try:
            with urlopen(Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=12) as response:
                raw=response.read(2000001)
            if len(raw)>2000000:raise ValueError('Company profile response is too large.')
            result=parse_profile(raw.decode('utf-8'),symbol)
            if primary and primary.get('name'):result['name']=primary['name']
            return result
        except Exception as error:
            if isinstance(error,HTTPError) and error.code in (401,403,429):BLOCKED['profile']=time.time()+3600
            if primary:return primary
            raise
    if primary:return primary
    raise ValueError('Public company classification sources are temporarily unavailable.')


def effective(profile,records,now=None):
    """User overrides win; expired provider classifications are never silently reused."""
    now=time.time() if now is None else now
    result={**profile,'sectors':dict(profile.get('sectors',{}))}
    provenance={s:'User classification' for s in result['sectors']}
    for symbol,r in records.items():
        if symbol not in result['sectors'] and r.get('sector') and 0<=now-r.get('fetched',0)<=30*86400:
            result['sectors'][symbol]=r['sector'];provenance[symbol]=r.get('source','Company data')
    result['sector_sources']=provenance
    return result


def assessment(financial,sector=None):
    m=financial.get('metrics',{});checks=[]
    def check(key,label,predicate):
        metric=m.get(key)
        if metric and fundamentals.number(metric.get('value')):
            checks.append({'label':label,'passes':bool(predicate(metric['value'])),'value':metric['value'],
                           'period':metric['period'],'metric':key})
    if financial.get('status') not in ('stale','unavailable'):
        check('revenue_growth','Revenue grew year on year',lambda v:v>0)
        check('net_income','Annual net income is positive',lambda v:v>0)
        if sector!='Financials':check('free_cash_flow','Annual free cash flow is positive',lambda v:v>0)
        if sector!='Financials':check('operating_cash_flow','Annual operating cash flow is positive',lambda v:v>0)
        if sector and sector!='Financials':
            check('operating_margin','Operating margin is positive',lambda v:v>0)
            check('net_cash','Cash covers reported debt',lambda v:v>=0)
        check('equity','Reported equity is positive',lambda v:v>0)
    passed=sum(c['passes'] for c in checks)
    label=('Unavailable / stale' if not checks else 'Limited coverage / sector unknown' if not sector or len(checks)<3 else
           'Mostly positive reported conditions' if passed/len(checks)>=.75 else
           'Mixed reported conditions' if passed/len(checks)>=.4 else 'Several reported weaknesses')
    return {'label':label,'passed':passed,'covered':len(checks),'checks':checks,'period':financial.get('period'),
            'status':financial.get('status'),'source_url':financial.get('source_url'),
            'annual_pe_proxy':m.get('annual_pe_proxy'),
            'method':'Descriptive annual accounting checks, not a probability, full business assessment or buy signal. '
                     'Financial-sector comparisons omit industrial margin/net-cash checks. Annual P/E is not TTM or evidence of cheapness. '
                     'Missing observations do not pass; stale data receives no grade. These data are not point-in-time and never enter historical ranking tests.'}


class Worker:
    def __init__(self,read,write,symbols):
        self.read,self.write,self.symbols=read,write,symbols
        self.stop=threading.Event();self.wake=threading.Event()
    def loop(self):
        while not self.stop.is_set():
            for s in self.symbols():
                if self.stop.is_set():break
                old=self.read('company:'+s,{})
                if time.time()-old.get('attempted',0)<86400:continue
                try:
                    self.write('company:'+s,fetch(s))
                except Exception as error:
                    self.write('company:'+s,{**old,'symbol':s,'attempted':time.time(),'error':'Company metadata lookup unavailable; manual overrides remain available.'})
                    if isinstance(error,HTTPError) and error.code in (401,403,429):break
                self.stop.wait(1)
            self.wake.wait(3600);self.wake.clear()
    def start(self):
        threading.Thread(target=self.loop,name='northstar-company-data',daemon=True).start()


def peer_valuation(symbol,financial,records,quotes,sectors,now=None):
    import statistics
    now=time.time() if now is None else now
    subject=financial.get('metrics',{}).get('annual_pe_proxy');sector=sectors.get(symbol)
    peers=[];seen=set()
    if subject and sector and financial.get('status') not in ('stale','unavailable'):
        for s,r in records.items():
            if s==symbol or issuer(s)==issuer(symbol) or sectors.get(s)!=sector or issuer(s) in seen:continue
            f=fundamentals.analyse(r,quotes.get(s),now)
            pe=f['metrics'].get('annual_pe_proxy')
            if f['status'] in ('stale','unavailable') or not pe or pe['period']!=subject['period']:continue
            peers.append({'symbol':s,'value':pe['value'],'period':pe['period']});seen.add(issuer(s))
    median=statistics.median(p['value'] for p in peers) if len(peers)>=3 else None
    return {'sector':sector,'peer_count':len(peers),'median_annual_pe_proxy':median,'peers':peers,
            'subject_annual_pe_proxy':subject['value'] if subject else None,
            'relative_pct':(subject['value']/median-1)*100 if median else None,
            'method':'At least three other companies, same sector and fiscal year, fresh matching-currency quote/EPS. '
                     'A lower annual P/E proxy does not establish undervaluation. Not TTM or a forecast.'}
