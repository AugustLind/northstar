import copy
import datetime as dt
import io
import json
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import announcements as a
import research
from test_research import quote

NOW=dt.datetime(2026,10,27,12,tzinfo=dt.timezone.utc).timestamp()


def row(identifier=1,title='Q3 2026 results',ticker='KOG',published='2026-10-27T10:00:00Z',**extra):
    return {'messageId':identifier,'issuerSign':ticker,'issuerName':'Example issuer','title':title,
            'publishedTime':published,'category':[{'category_en':'Inside information'}],**extra}


def notice(identifier=1,title='Q3 2026 results',**extra):
    return a.normalise([row(identifier,title,**extra)],NOW)[0][0]


def feed(items,**extra):
    return {'items':items,'fetched':NOW,'attempted':NOW,'from':'2026-10-21','to':'2026-10-27','partial':False,'error':None,**extra}


class NoticeParsingTests(unittest.TestCase):
    def test_exact_ticker_and_source_publication(self):
        items,skipped=a.normalise([row(),row(ticker='BOUV',identifier=2)],NOW)
        self.assertEqual(skipped,0)
        self.assertEqual(items[0]['symbol'],'KOG.OL')
        self.assertEqual(items[0]['url'],'https://newsweb.oslobors.no/message/1')
        self.assertEqual(items[0]['published'],NOW-2*3600)
        self.assertEqual(a.view(feed(items),['KOG.OL'],NOW)['total'],1)
        self.assertEqual(a.view(feed(items),['KOGX.OL'],NOW)['total'],0)

    def test_future_undated_and_test_items_are_not_news(self):
        items,skipped=a.normalise([row(published='2026-10-28T10:00:00Z'),row(published=None),
                                   row(published='2026-10-27T10:00:00'),row(test=True)],NOW)
        self.assertEqual(items,[])
        self.assertEqual(skipped,3)

    def test_duplicate_ids_are_deduplicated(self):
        items,_=a.normalise([row(),row()],NOW)
        self.assertEqual(len(items),1)

    def test_reviewed_share_class_alias_does_not_duplicate_notices(self):
        item=notice(ticker='WWI')
        result=a.view(feed([item]),['WWI.OL','WWIB.OL'],NOW)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['symbol'],'WWI.OL')
        self.assertEqual(result['issuer_aliases'],{'WWIB.OL':'WWI.OL'})

    def test_invitation_is_not_an_earnings_result(self):
        result=a.classify('Invitation to Q3 2026 results',[])
        self.assertEqual(result['kind'],'calendar')
        self.assertIn('not an earnings result',result['why'])
        self.assertEqual(a.classify('Q3 2026 results',[])['kind'],'earnings')

    def test_norwegian_tags_and_buyback_are_not_acquisitions(self):
        self.assertEqual(a.classify('Invitasjon til presentasjon av kvartalsresultater',[])['kind'],'calendar')
        self.assertEqual(a.classify('Tilbakekjøp av egne aksjer',[])['kind'],'distribution')
        self.assertEqual(a.classify('Acquisition or disposal of issuer\'s own shares',[])['kind'],'distribution')
        self.assertEqual(a.classify('Meldepliktig handel for primærinnsidere',[])['kind'],'insider')
        self.assertEqual(a.classify('Profit warning: reduced outlook',[])['priority'],3)

    def test_review_flags_do_not_claim_insider_direction_or_earnings_beat(self):
        insider=a.classify('Mandatory notification of trade by primary insider',[])
        self.assertIn('does not show',insider['why'])
        earnings=a.classify('Q3 results',[])
        self.assertIn('does not establish a beat or miss',earnings['why'])

    def test_first_seen_and_corrections_are_preserved_without_mutating_old(self):
        original=notice();old=a.merge({},feed([original]),NOW-10)
        before=copy.deepcopy(old)
        corrected=notice(2,'Correction to Q3 results',correctionForMessageId=1)
        merged=a.merge(old,feed([original,corrected]),NOW)
        byid={i['id']:i for i in merged['items']}
        self.assertEqual(byid['1']['first_seen'],NOW-10)
        self.assertEqual(byid['1']['corrected_by'],2)
        self.assertEqual(old,before)
        visible=a.view(merged,['KOG.OL'],NOW)
        self.assertEqual([i['id'] for i in visible['last24h']],['2'])

    def test_stale_and_failed_feeds_do_not_claim_silence(self):
        value=a.view(feed([notice()],fetched=NOW-3*3600),['KOG.OL'],NOW)
        self.assertEqual(value['status'],'stale')
        self.assertIn('absence of headlines',value['summary'])
        self.assertEqual(a.view(feed([notice()],error='network'),['KOG.OL'],NOW)['status'],'degraded')
        self.assertEqual(a.view(None,['KOG.OL'],NOW)['status'],'unavailable')


class CalendarTests(unittest.TestCase):
    def setUp(self):self.notice=notice(title='Financial calendar')

    def test_explicit_reporting_dates_only(self):
        body='<p>29.10.2026 - Quarterly Report Q3</p><p>31.03.2027 - Annual General Meeting</p><p>Q4 results: 12 February 2027</p>'
        events=a.calendar_events(body,self.notice,NOW)
        self.assertEqual([e['date'] for e in events],['2026-10-29','2027-02-12'])
        self.assertTrue(all(e['source_url']==self.notice['url'] for e in events))
        self.assertIn('Q3',events[0]['label'])

    def test_no_year_no_guessed_date(self):
        body='Q3 results 29 October\nQ3 results 2026-10-29 and 2026-10-30\nQ3 results 31.02.2027'
        self.assertEqual(a.calendar_events(body,self.notice,NOW),[])

    def test_hidden_script_dates_are_ignored(self):
        self.assertEqual(a.calendar_events('<script>Q3 results 29.10.2026</script>',self.notice,NOW),[])

    def test_new_calendar_replaces_old_dates(self):
        first=notice(1,'Financial calendar',published='2026-10-26T10:00:00Z')
        first['events']=a.calendar_events('Quarterly Report Q3 - 2026-10-29',first,NOW)
        second=notice(2,'Financial calendar')
        second['events']=a.calendar_events('Quarterly Report Q3 - 2026-11-05',second,NOW)
        result=a.view(feed([first,second]),['KOG.OL'],NOW)
        self.assertEqual([e['date'] for e in result['events']],['2026-11-05'])

    def test_pending_new_calendar_hides_previously_confirmed_dates(self):
        first=notice(1,'Financial calendar',published='2026-10-26T10:00:00Z')
        first['events']=a.calendar_events('Q3 results 2026-10-29',first,NOW)
        second=notice(2,'Financial calendar')
        self.assertEqual(a.view(feed([first,second]),['KOG.OL'],NOW)['events'],[])


class FeedFetchingTests(unittest.TestCase):
    def test_inclusive_date_window_splits_without_losing_day(self):
        start=dt.date(2026,10,26);end=dt.date(2026,10,27);calls=[]
        def fake(endpoint,params):
            calls.append(params)
            overflow=params['fromDate']!=params['toDate']
            return {'data':{'messages':[{'day':params['fromDate']}],'overflow':overflow}}
        with patch.object(a,'request',side_effect=fake):
            items,partial=a.fetch_window(start,end)
        self.assertFalse(partial)
        self.assertEqual([i['day'] for i in items],['2026-10-26','2026-10-27'])
        self.assertEqual(len(calls),3)

    def test_single_day_overflow_is_reported_not_recursed(self):
        with patch.object(a,'request',return_value={'data':{'messages':[{}],'overflow':True}}) as request:
            _,partial=a.fetch_window(dt.date(2026,10,27),dt.date(2026,10,27))
        self.assertTrue(partial);self.assertEqual(request.call_count,1)

    def test_read_endpoint_method_fallback_keeps_query_and_empty_body(self):
        err=HTTPError('https://example.com',405,'method',None,None)
        response=io.BytesIO(b'{"data":{"messages":[]}}')
        with patch.object(a,'urlopen',side_effect=[err,response]) as open_url:
            a.request('list',{'fromDate':'2026-10-27'})
        request=open_url.call_args.args[0]
        self.assertEqual(request.method,'POST');self.assertEqual(request.data,b'')
        self.assertTrue(request.full_url.startswith(a.API+'/list?'))
        self.assertIn('fromDate=2026-10-27',request.full_url)

    def test_worker_failure_retains_original_dates(self):
        original=feed([notice()]);values={'announcements_feed':original}
        worker=a.Worker(lambda k,d=None:values.get(k,d),lambda k,v:values.update({k:v}),lambda:['KOG.OL'])
        with patch.object(a,'fetch_recent',side_effect=URLError('offline')),patch.object(a.time,'time',return_value=NOW+3600):
            self.assertFalse(worker.run_once())
        saved=values['announcements_feed']
        self.assertEqual(saved['fetched'],NOW);self.assertEqual(saved['items'],original['items'])
        self.assertIn('could not be reached',saved['error'])
        self.assertFalse(values['announcements_progress']['running'])

    def test_cached_feed_can_extract_dates_for_new_focus_without_refetching(self):
        item=notice(title='Financial calendar');values={'announcements_feed':feed([item],fetched=time.time())}
        worker=a.Worker(lambda k,d=None:values.get(k,d),lambda k,v:values.update({k:v}),lambda:['KOG.OL'])
        with patch.object(a,'fetch_recent') as fetch,patch.object(a,'fetch_calendar',return_value=[{'date':'2026-10-29'}]) as calendar:
            self.assertTrue(worker.run_once())
        fetch.assert_not_called();calendar.assert_called_once()
        self.assertTrue(values['announcements_feed']['items'][0]['calendar_checked'])

    def test_news_metadata_does_not_change_stock_rank(self):
        q=quote();q['currency']='NOK'
        snapshot={'positions':[],'quotes':{'KOG.OL':q}}
        before=research.build_report(snapshot,['KOG.OL'])
        snapshot['announcements']=feed([notice(title='Profit warning')],fetched=time.time())
        after=research.build_report(snapshot,['KOG.OL'])
        self.assertEqual(before['top20'],after['top20'])
        self.assertEqual(before['cards'][0]['composite'],after['cards'][0]['composite'])
        self.assertEqual(after['cards'][0]['announcements']['headlines'][0]['title'],'Profit warning')
