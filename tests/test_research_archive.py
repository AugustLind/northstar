import copy
import sqlite3
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import app
import research
import research_archive as ar
from test_research import quote

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row;ar.schema(self.db)
    def tearDown(self):self.db.close()
    def test_revised_bars_do_not_replace_known_earlier_values(self):
        a={'asof':10,'fetched':100,'history':[{'time':10,'close':100},{'time':20,'close':101}]}
        first=ar.capture(self.db,'quote','A.OL',a,now=100)
        b=copy.deepcopy(a);b['history'][0]['close']=90;b['fetched']=200
        second=ar.capture(self.db,'quote','A.OL',b,now=200)
        self.assertEqual(ar.read(self.db,first)['value'],a)
        self.assertEqual(ar.read(self.db,second)['value'],b)
        self.assertEqual(ar.latest(self.db,'quote','A.OL',150)['id'],first)
        self.assertIsNone(ar.latest(self.db,'quote','A.OL',99))
        with self.assertRaises(ValueError):ar.read(self.db,second,before=150)
    def test_unchanged_bars_share_versions_and_sparse_frames_remain_exact(self):
        q={'fetched':100,'history':[{'time':10,'close':100},{'time':20,'close':101}]}
        first=ar.capture(self.db,'quote','A.OL',q,now=100)
        q['fetched']=200;ar.capture(self.db,'quote','A.OL',q,now=200)
        self.assertEqual(ar.stats(self.db)['price_versions'],2)
        q['history']=q['history'][1:];third=ar.capture(self.db,'quote','A.OL',q,now=300)
        self.assertEqual(ar.read(self.db,third)['value']['history'],q['history'])
        self.assertEqual(len(ar.read(self.db,first)['value']['history']),2)
    def test_archive_is_append_only_and_captures_never_use_provider_dates(self):
        id=ar.capture(self.db,'financial','A.OL',{'period':'2001-12-31'},now=500,source_asof=1)
        self.assertEqual(ar.read(self.db,id)['captured'],500)
        self.assertEqual(ar.stats(self.db,before=499)['runs'],[])
        for sql in ('UPDATE research_snapshots SET captured=1','DELETE FROM research_snapshots','UPDATE research_blobs SET original_bytes=0'):
            with self.assertRaises(sqlite3.IntegrityError):self.db.execute(sql)
    def test_recorded_inputs_replay_without_future_data_or_live_state(self):
        now=time.time();q=quote();q['currency']='NOK'
        snapshot={'positions':[],'quotes':{'A.OL':q},'fundamentals':{},'portfolio_preferences':{}}
        report=research.build_report(snapshot,['A.OL']);saved=copy.deepcopy(snapshot)
        id=ar.capture_run(self.db,report,snapshot,{'universe':['A.OL']},ar.analysis_fingerprint(app.ROOT),now=now+1)
        q['history'][-1]['close']*=2
        ar.capture(self.db,'quote','A.OL',q,now=now+2)
        value=ar.replay(self.db,id,app.ROOT)
        self.assertEqual(value['differences'],0);self.assertTrue(value['same_analysis_code'])
        self.assertEqual(ar.read(self.db,ar.read(self.db,id)['value']['quote_ids']['A.OL'])['value'],saved['quotes']['A.OL'])
