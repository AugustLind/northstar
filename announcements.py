"""Read-only NewsWeb discovery, correction-aware metadata and dated calendar facts.

Only headline metadata and extracted calendar dates are retained. Notice bodies and
attachments are not stored, summarised, or treated as trading instructions.
"""
import datetime as dt
import html
from html.parser import HTMLParser
import json
import re
import threading
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API = 'https://api3.oslo.oslobors.no/v1/newsreader'
SITE = 'https://newsweb.oslobors.no'
OSLO = ZoneInfo('Europe/Oslo')
# Reviewed share classes, not fuzzy company-name matching. Notices remain labelled
# with the issuer ticker supplied by NewsWeb.
ISSUER_ALIASES = {'WWIB.OL':'WWI.OL','ODFB.OL':'ODF.OL'}

def issuer_group(symbol):
    return ISSUER_ALIASES.get(symbol,symbol)

RULES = [
 ('risk', 'Guidance / financial risk', 3, r'profit warning|resultatvarsel|bankrupt|insolven|konkurs|lower\w* guidance|downgrad\w*.*guidance|nedjuster\w*.*(?:forvent|utsikt|guid)|recovery box',
  'Read the revised outlook or financial-risk disclosure and revisit the investment thesis. The headline alone does not quantify the impact.'),
 ('calendar', 'Earnings calendar / invitation', 2, r'financial calendar|finansiell kalender|reporting date|new date.*report|invitation.*(?:result|quarter|earnings)|invitasjon.*(?:result|kvartal)|(?:result|quarter|earnings).*invitation',
  'Check the confirmed reporting or presentation date. An invitation is not an earnings result.'),
 ('earnings', 'Earnings / business update', 3, r'quarter\w*.*(?:result|report)|(?:q[1-4]|half.year|annual).*(?:result|report)|trading update|business update|arsresultat|arsrapport|kvartalsrapport|resultat.*kvartal',
  'Review revenue, margins, cash flow and guidance in the linked report. A generic results headline does not establish a beat or miss.'),
 ('distribution', 'Dividend / buyback', 1, r'dividend|utbytte|buy.?back|tilbakekjop|issuer.s own shares|egne aksjer',
  'Check the distribution, dates and funding. Buybacks and dividends do not by themselves establish an attractive valuation.'),
 ('capital', 'Capital / financing', 3, r'private placement|rights issue|capital rais|capital increase|share issuance|issuance of shares|share capital|emisjon|kapitalforh|fortrinnsrett|tap issue|bond issue|obligasjonslan',
  'Check funding needs, issue price and possible ownership dilution. Announced financing is not automatically evidence of distress.'),
 ('corporate', 'Acquisition / corporate action', 2, r'acquisition|merger|tender offer|takeover|oppkjop|fusjon|demerger|fisjon|delisting|avnotering',
  'Review transaction terms, funding, approvals and changes to the business you own.'),
 ('contract', 'Contract / operations', 2, r'contract|kontrakt|awarded|tildelt|order intake|ordreinngang|production update|operational update',
  'Check the contract or operational update for size, timing and profitability; a headline does not establish its earnings contribution.'),
 ('insider', 'Insider / ownership disclosure', 1, r'insider|primary insider|primaerinnsider|major holding|shareholding|substantial holding|flagg|meldepliktig handel',
  'Check who traded, direction and size. A notification headline alone does not show whether insiders bought or sold.'),
 ('governance', 'Governance / meeting', 1, r'general meeting|generalforsamling|board of directors|styre|ceo|chief executive',
  'Review the management or shareholder decision and whether it changes your investment thesis.'),
]


def plain(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


def classify(title, categories):
    text = unicodedata.normalize('NFKD', (title+' '+' '.join(categories)).lower()).translate(str.maketrans({'ø':'o','æ':'ae'}))
    text = ''.join(c for c in text if not unicodedata.combining(c))
    for kind, label, priority, pattern, why in RULES:
        if re.search(pattern, text):
            return {'kind':kind,'label':label,'priority':max(priority,3 if 'inside information' in text else 1),'why':why}
    return {'kind':'other','label':'Other issuer notice','priority':2 if 'inside information' in text else 1,
            'why':'Read the source notice to assess whether it changes the investment thesis.'}


def published_timestamp(value):
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        return value/1000 if value>10**12 else float(value)
    parsed=dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Publication timezone is missing')
    return parsed.timestamp()


def normalise(rows, now=None):
    now=time.time() if now is None else now
    result={}; skipped=0
    for row in rows:
        try:
            if row.get('test') is True or str(row.get('test','')).lower() in ('1','true'):
                continue
            identifier=int(row['messageId'])
            ticker=plain(row['issuerSign']).upper()
            if not re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,16}',ticker) or identifier<=0:
                raise ValueError('Not a supported issuer')
            stamp=published_timestamp(row['publishedTime'])
            if not 0<stamp<=now+300:
                raise ValueError('Invalid/future publication')
            title=plain(row['title'])
            if not title:
                raise ValueError('Missing title')
            categories=[]
            raw_categories=row.get('category') or []
            if isinstance(raw_categories,dict): raw_categories=[raw_categories]
            for category in raw_categories:
                if isinstance(category,dict):
                    label=plain(category.get('category_en') or category.get('category_no') or '')
                    if label: categories.append(label)
            def corrected(key):
                v=row.get(key)
                return int(v) if str(v or '').isdigit() and int(v)>0 else None
            result[str(identifier)]={
                'id':str(identifier),'symbol':ticker+'.OL','issuer':plain(row.get('issuerName')),
                'title':title[:500],'published':stamp,'url':f'{SITE}/message/{identifier}',
                'source':'Oslo Børs NewsWeb','source_type':'exchange_announcement',
                'categories':categories,'correction_for':corrected('correctionForMessageId'),
                'corrected_by':corrected('correctedByMessageId'), 'classification':classify(title,categories),
            }
        except (KeyError,ValueError,TypeError,OverflowError):
            skipped+=1
    return list(result.values()),skipped


def request(endpoint, params):
    if endpoint not in ('list','message'):
        raise ValueError('Unsupported read endpoint')
    url=API+'/'+endpoint+'?'+urlencode(params)
    headers={'User-Agent':'Northstar/1.0 personal investment research','Accept':'application/json',
             'Origin':SITE,'Referer':SITE+'/'}
    try:
        response=urlopen(Request(url,headers=headers),timeout=20)
    except HTTPError as error:
        if error.code not in (400,405):
            raise
        response=urlopen(Request(url,data=b'',headers={**headers,'Content-Type':'application/json'},method='POST'),timeout=20)
    with response:
        content=response.read(5_000_001)
    if len(content)>5_000_000:
        raise ValueError('Announcement response exceeds size limit')
    return json.loads(content)


def fetch_window(start, end):
    response=request('list',{'fromDate':start.isoformat(),'toDate':end.isoformat()})
    data=response.get('data')
    if not isinstance(data,dict) or not isinstance(data.get('messages'),list):
        raise ValueError('Announcement list format unavailable')
    rows=data['messages']
    overflow=bool(data.get('overflow')) or len(rows)>=601
    if overflow and start<end:
        middle=start+dt.timedelta(days=(end-start).days//2)
        left,partial_left=fetch_window(start,middle)
        right,partial_right=fetch_window(middle+dt.timedelta(days=1),end)
        return left+right, partial_left or partial_right
    return rows,overflow


def fetch_recent(now=None):
    now=time.time() if now is None else now
    today=dt.datetime.fromtimestamp(now,OSLO).date()
    start=today-dt.timedelta(days=6)
    raw,partial=fetch_window(start,today)
    items,skipped=normalise(raw,now)
    if raw and not items and skipped:
        raise ValueError('No dated issuer notices could be parsed')
    lower=dt.datetime.combine(start,dt.time.min,OSLO).timestamp()
    upper=dt.datetime.combine(today+dt.timedelta(days=1),dt.time.min,OSLO).timestamp()
    items=[item for item in items if lower<=item['published']<upper]
    return {'items':items,'fetched':now,'attempted':now,'from':start.isoformat(),'to':today.isoformat(),
            'partial':partial or skipped>0,'skipped':skipped,'error':None,'source':'Oslo Børs NewsWeb',
            'scope':'Seven calendar days of list metadata; publication times are supplied by NewsWeb. Notice bodies and attachments are not retained.'}


class CalendarText(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag.lower() in ('script','style'):self.hidden+=1
        if tag.lower() in ('br','p','div','li','tr','h1','h2','h3'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag.lower() in ('script','style'):self.hidden=max(0,self.hidden-1)
        if tag.lower() in ('p','div','li','tr'):self.parts.append('\n')
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)


MONTHS={name:i for i,names in enumerate([
    ('january','januar'),('february','februar'),('march','mars'),('april',),('may','mai'),('june','juni'),
    ('july','juli'),('august',),('september',),('october','oktober'),('november',),('december','desember')],1) for name in names}
DATE=re.compile(r'(?<!\d)(?:(\d{4})-(\d{2})-(\d{2})|(\d{1,2})[./](\d{1,2})[./](20\d{2})|(\d{1,2})\.?\s+('+ '|'.join(MONTHS) +r')\s+(20\d{2}))(?!\d)',re.I)
EVENT_WORDS=re.compile(r'quarter|half.year|annual report|results|earnings|kvartal|arsrapport|halvarsrapport',re.I)


def calendar_events(body, notice, now=None):
    now=time.time() if now is None else now
    parser=CalendarText();parser.feed(str(body or '')[:200000]);text=''.join(parser.parts)
    events=[];seen=set()
    # A date and an earnings/reporting label must be on the same textual line.
    for line in text.splitlines():
        if not EVENT_WORDS.search(line):continue
        matches=list(DATE.finditer(line))
        if len(matches)!=1:continue  # Do not guess which date a multi-date sentence refers to.
        match=matches[0];g=match.groups()
        try:
            date=dt.date(int(g[0]),int(g[1]),int(g[2])) if g[0] else dt.date(int(g[5]),int(g[4]),int(g[3])) if g[3] else dt.date(int(g[8]),MONTHS[g[7].lower()],int(g[6]))
        except (ValueError,KeyError):continue
        today=dt.datetime.fromtimestamp(now,OSLO).date()
        if not today<=date<=today+dt.timedelta(days=550) or date.isoformat() in seen:continue
        seen.add(date.isoformat())
        quarter=re.search(r'\bQ([1-4])\b',line,re.I)
        label=('Q'+quarter[1]+' financial-report event') if quarter else ('Half-year financial-report event' if re.search(r'half.year|halvars',line,re.I) else 'Annual financial-report event' if re.search(r'annual|arsrapport',line,re.I) else 'Earnings / results presentation')
        events.append({'date':date.isoformat(),'symbol':notice['symbol'],'notice_id':notice['id'],
                       'label':label,'source_url':notice['url'],
                       'announced':notice['published'],'confirmation':'Date explicitly stated in issuer notice; subject to later corrections.'})
    return events[:12]


def fetch_calendar(notice, now=None):
    result=request('message',{'messageId':notice['id']})
    message=(result.get('data') or {}).get('message') or {}
    if str(message.get('messageId',notice['id']))!=notice['id']:
        raise ValueError('Notice ID mismatch')
    return calendar_events(message.get('body',''),notice,now)


def merge(old, new, now=None):
    now=time.time() if now is None else now
    items={item['id']:{**item} for item in (old or {}).get('items',[]) if item['published']>=now-30*86400}
    for fresh in new['items']:
        previous=items.get(fresh['id'],{})
        items[fresh['id']]={**fresh,'first_seen':previous.get('first_seen',now),
                            'events':previous.get('events',[]),'calendar_checked':previous.get('calendar_checked')}
    for item in list(items.values()):
        original=items.get(str(item.get('correction_for')))
        if original:original['corrected_by']=int(item['id'])
    return {**new,'items':sorted(items.values(),key=lambda item:item['published'],reverse=True)[:3000]}


def view(record, symbols=None, now=None):
    now=time.time() if now is None else now
    record=record or {}
    fetched=record.get('fetched')
    stale=not fetched or now-fetched>2*3600
    wanted={issuer_group(symbol) for symbol in symbols} if symbols is not None else None
    items=[item for item in record.get('items',[]) if wanted is None or issuer_group(item['symbol']) in wanted]
    recent=[item for item in items if now-24*3600<=item['published']<=now and not item.get('corrected_by')]
    relevant=sorted(recent,key=lambda item:(-item['classification']['priority'],-item['published']))
    events={}
    for item in sorted(items,key=lambda x:x['published']):
        if item.get('corrected_by'):continue
        if item['classification']['kind']=='calendar' and re.search(r'financial calendar|finansiell kalender',item['title'],re.I):
            # A newer full calendar supersedes previously extracted calendar entries.
            events={key:value for key,value in events.items() if value['symbol']!=item['symbol']}
        for event in item.get('events',[]):
            if event['date']>=dt.datetime.fromtimestamp(now,OSLO).date().isoformat():
                key=(event['symbol'],event['label'],event['date'][:4]) if event['label']!='Earnings / results presentation' else (event['symbol'],event['label'],event['date'])
                events[key]=event
    return {'status':'unavailable' if not fetched else 'stale' if stale else 'degraded' if record.get('error') else 'partial' if record.get('partial') else 'available',
            'fetched':fetched,'attempted':record.get('attempted'),'error':record.get('error'),
            'from':record.get('from'),'to':record.get('to'),'partial':record.get('partial',False),
            'source':'Oslo Børs NewsWeb','scope':'Exchange-hosted issuer announcements only; general publisher news is not included.',
            'issuer_aliases':{s:ISSUER_ALIASES[s] for s in (symbols or []) if s in ISSUER_ALIASES},
            'items':items[:100], 'total':len(items),'last24h':relevant[:20],
            'calendar_pending':sum(item['classification']['kind']=='calendar' and not item.get('calendar_checked') and not item.get('corrected_by') for item in items),
            'counts':{'last24h':len(recent),'priority_review':sum(i['classification']['priority']>=3 for i in recent),
                      'earnings':sum(i['classification']['kind']=='earnings' for i in recent)},
            'events':sorted(events.values(),key=lambda e:(e['date'],e['symbol']))[:50],
            'summary':('Feed unavailable or stale; absence of headlines is not evidence of no company announcements.' if stale else
                f'{len(recent)} notices in the last 24 hours; {sum(i["classification"]["priority"]>=3 for i in recent)} flagged for closer review. Labels are headline rules, not sentiment or price-impact predictions.')}


def error_message(error):
    if isinstance(error,HTTPError):return f'NewsWeb returned HTTP {error.code}. Cached notices retain their original publication and retrieval dates.'
    if isinstance(error,(URLError,TimeoutError)):return 'NewsWeb could not be reached. Cached notices are retained.'
    return 'NewsWeb returned an unusable response. Coverage could not be confirmed.'


class Worker:
    def __init__(self,read,write,focus):
        self.read,self.write,self.focus=read,write,focus
        self.stop=threading.Event();self.wake=threading.Event();self.lock=threading.Lock()

    def trigger(self):self.wake.set()

    def run_once(self):
        if not self.lock.acquire(blocking=False):return False
        self.write('announcements_progress',{'running':True,'started':time.time()})
        try:
            old=self.read('announcements_feed',{})
            try:
                record=old if old.get('fetched') and time.time()-old['fetched']<300 and not old.get('error') else merge(old,fetch_recent())
            except Exception as error:
                self.write('announcements_feed',{**old,'attempted':time.time(),'error':error_message(error)})
                return False
            self.write('announcements_feed',record)
            focused={issuer_group(s) for s in self.focus()}
            pending=[item for item in record['items'] if issuer_group(item['symbol']) in focused and
                     item['classification']['kind']=='calendar' and not item.get('calendar_checked') and not item.get('corrected_by')]
            for item in pending[:8]:
                if self.stop.is_set():break
                try:
                    item['events']=fetch_calendar(item)
                    item['calendar_error']=None
                    item['calendar_checked']=time.time()
                except Exception as error:
                    item['calendar_error']=error_message(error)
            self.write('announcements_feed',record)
            return True
        finally:
            self.write('announcements_progress',{'running':False,'finished':time.time()})
            self.lock.release()

    def loop(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:self.run_once()
            except Exception:self.write('announcements_progress',{'running':False,'error':'Announcement scan failed; cached data retained.'})
            self.wake.wait(30*60)

    def start(self):threading.Thread(target=self.loop,name='northstar-announcements',daemon=True).start()
