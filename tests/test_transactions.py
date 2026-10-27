import base64
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import transactions as tx


def raw(rows):
    return ('Dato;Type;Navn;Ticker;Antall;Beløp;Valuta;ID;Kurtasje\n'+rows).encode('utf-16')


def mapping():
    return {'date':'Dato','type':'Type','name':'Navn','symbol':'Ticker','quantity':'Antall','net_cash':'Beløp','currency':'Valuta','trade_id':'ID','fee':'Kurtasje'}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.patch=patch.object(app,'DB',Path(self.tmp.name)/'db');self.patch.start()
        self.worker=patch.object(app,'WORKER',None);self.worker.start()
        app.save_position({'symbol':'EXA','currency':'NOK','shares':1,'cost':100,'thesis':'Keep notes'})
        app.write_meta('portfolio_preferences',{'cash_nok':10000})
        app.ledger_initialize({'date':'2025-01-01'})
    def tearDown(self):self.worker.stop();self.patch.stop();self.tmp.cleanup()
    def preview(self,rows):
        table=app.ledger_inspect({'file_b64':base64.b64encode(raw(rows)).decode()})
        return app.ledger_preview({'token':table['token'],'mapping':mapping(),'scope':'test'})
    def apply(self,p):
        return app.ledger_apply({'token':p['token'],'selections':[{'id':r['id'],'symbol':r.get('symbol','')} for r in p['rows'] if not r['error']]})

    def test_net_cash_is_booked_once_and_duplicates_do_not_change_balances(self):
        rows='2025-01-02;Kjøp;Example;EXA;2;-279;NOK;b1;79\n2025-01-03;Salg;Example;EXA;1;100;NOK;s1;0\n2025-01-04;Utbytte;Example;;;10;NOK;d1;\n2025-01-05;Gebyr;;;;-5;NOK;f1;\n2025-01-06;Innskudd;;;;500;NOK;i1;\n2025-01-07;Uttak;;;;-100;NOK;w1;\n'
        before=copy.deepcopy(app.state()['positions']);p=self.preview(rows)
        self.assertEqual(app.state()['positions'],before)
        result=self.apply(p);self.assertEqual(result['imported'],6)
        self.assertEqual(app.read_meta('portfolio_preferences')['cash_nok'],10226)
        position=app.state()['positions'][0];self.assertEqual(position['shares'],2)
        self.assertAlmostEqual(position['cost'],379/3);self.assertEqual(position['thesis'],'Keep notes')
        self.assertTrue(app.ledger_view()['reconciled'])
        result=self.apply(self.preview(rows));self.assertEqual(result['imported'],0)
        self.assertEqual(result['duplicates'],6);self.assertEqual(app.read_meta('portfolio_preferences')['cash_nok'],10226)
        self.assertIn('EXA.OL',app.read_meta('last_trades'))

    def test_opening_snapshot_prevents_double_counting_history(self):
        p=self.preview('2024-12-31;Kjøp;Example;EXA;1;-179;NOK;old;79\n')
        self.apply(p)
        self.assertEqual(app.state()['positions'][0]['shares'],1)
        self.assertEqual(app.read_meta('portfolio_preferences')['cash_nok'],10000)
        self.assertIn('EXA.OL',app.read_meta('last_trades'))

    def test_manual_financial_edits_block_but_note_edits_are_preserved(self):
        p=self.preview('2025-01-02;Kjøp;Example;EXA;2;-279;NOK;b1;79\n')
        with app.connect() as db:db.execute("UPDATE positions SET thesis='New note'")
        self.apply(p);self.assertEqual(app.state()['positions'][0]['thesis'],'New note')
        profile=app.read_meta('portfolio_preferences');profile['cash_nok']+=1;app.write_meta('portfolio_preferences',profile)
        self.assertFalse(app.ledger_view()['reconciled'])
        self.assertFalse(app.state()['ledger_reconciled'])
        p=self.preview('2025-01-03;Kjøp;Example;EXA;1;-179;NOK;b2;79\n')
        with self.assertRaises(ValueError):self.apply(p)

    def test_overselling_negative_cash_and_conflicting_ids_are_atomic(self):
        for row in ('2025-01-02;Salg;Example;EXA;2;200;NOK;s1;\n','2025-01-02;Kjøp;Example;EXA;200;-20000;NOK;b1;\n'):
            before=app.state()['positions'];p=self.preview(row)
            with self.assertRaises(ValueError):self.apply(p)
            self.assertEqual(app.state()['positions'],before);self.assertEqual(app.ledger_view()['count'],0)
        self.apply(self.preview('2025-01-02;Kjøp;Example;EXA;1;-179;NOK;b1;79\n'))
        with self.assertRaises(ValueError):self.apply(self.preview('2025-01-02;Kjøp;Example;EXA;2;-279;NOK;b1;79\n'))

    def test_same_file_broker_duplicates_are_skipped(self):
        row='2025-01-02;Kjøp;Example;EXA;1;-179;NOK;b1;79\n'
        result=self.apply(self.preview(row+row))
        self.assertEqual(result['imported'],1);self.assertEqual(result['duplicates'],1)

    def test_new_baseline_cannot_precede_recorded_activity(self):
        self.apply(self.preview('2025-02-01;Kjøp;Example;EXA;1;-179;NOK;b1;79\n'))
        with self.assertRaises(ValueError):app.ledger_initialize({'date':'2025-01-01'})
        app.ledger_initialize({'date':'2025-02-01'});self.assertTrue(app.ledger_view()['reconciled'])

    def test_broker_cash_mismatch_withholds_plan_until_verified(self):
        result=app.broker_cash_check({'cash_nok':9999})
        self.assertTrue(result['mismatch_active']);self.assertEqual(result['difference'],-1)
        self.assertFalse(app.state()['ledger_reconciled'])
        self.assertFalse(app.ledger_view()['reconciled'])
        self.assertEqual(app.read_meta('portfolio_preferences')['cash_nok'],10000)
        app.broker_cash_check({'cash_nok':10000})
        self.assertTrue(app.state()['ledger_reconciled'])

    def test_invalid_mapping_unsupported_types_and_ambiguous_signs(self):
        parsed=tx.table(raw('2025-01-02;Overføring;Example;EXA;1;100;NOK;a;\n'))
        rows=tx.events(parsed,mapping(),'test');self.assertTrue(rows[0]['error'])
        with self.assertRaises(ValueError):tx.events(parsed,{},'test')
        parsed=tx.table(raw('2025-01-02;Kjøp;Example;EXA;1;179;NOK;a;79\n'))
        self.assertTrue(tx.events(parsed,mapping(),'test')[0]['error'])
