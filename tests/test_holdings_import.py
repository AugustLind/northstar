import base64
import copy
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import holdings_import as hi

HEADER='Navn\tValuta\tAntall\tGAV\tI dag %\tSiste kurs\tBelåningsverdi\tVerdi\tVerdi NOK\tAvkast. %\tAvkast.\u00a0NOK\n'

def export(rows='Example Industries ASA\tNOK\t5\t306,00\t0\t300,00\t0\t1500\t1500\t0\t0\n',encoding='utf-16'):
    return (HEADER+rows).encode(encoding)

def upload(raw=None):
    return {'file_b64':base64.b64encode(export() if raw is None else raw).decode()}

class ParserTests(unittest.TestCase):
    def test_actual_nordnet_encoding_and_headers_with_synthetic_values(self):
        rows=hi.parse(export())
        self.assertEqual(rows[0]['name'],'Example Industries ASA')
        self.assertEqual(rows[0]['shares'],5)
        self.assertEqual(rows[0]['cost'],306)
        self.assertIsNone(rows[0]['error'])

    def test_unicode_number_spaces_and_decimal_comma(self):
        for value in ('1 234,56','1\u00a0234,56','1\u202f234,56','1.234,56','1234.56'):
            self.assertEqual(hi.amount(value,'GAV'),1234.56)
        for value in ('-1','NaN','inf','','1,234.56','1e3','=1+1','1,2,3','1000000000001'):
            with self.assertRaises(ValueError):
                hi.amount(value,'GAV')

    def test_utf8_semicolon_and_cp1252(self):
        text='Navn;Valuta;Antall;GAV\nEksempel Øst AS;NOK;2;4,25\n'
        for encoding in ('utf-8-sig','cp1252'):
            self.assertEqual(hi.parse(text.encode(encoding))[0]['cost'],4.25)

    def test_wrong_file_type_and_limits(self):
        for raw in (b'',b'x'*(hi.MAX_BYTES+1),b'\x00\x01\x00',b'Dato;Type;Belop\n2026;Kjop;100\n',
                    ('Navn;Navn;Valuta;Antall;GAV\nx;x;NOK;1;2').encode()):
            with self.assertRaises(ValueError):
                hi.parse(raw)

    def test_bad_and_unsupported_rows_do_not_become_zero(self):
        rows=hi.parse('Navn;Valuta;Antall;GAV\nA;USD;2;4,25\nB;NOK;NaN;1\nC;NOK;1;3,14\n'.encode())
        self.assertTrue(rows[0]['error']);self.assertTrue(rows[1]['error'])
        self.assertIsNone(rows[1]['shares']);self.assertEqual(rows[2]['cost'],3.14)

    def test_only_unambiguous_names_match_and_legal_suffix_is_labelled(self):
        rows=hi.parse(export())
        companies=[{'symbol':'EXA.OL','name':'Example Industries'}]
        match=hi.suggest(rows,companies,{})[0]
        self.assertEqual(match['symbol'],'EXA.OL')
        self.assertIn('legal suffix',match['match'])
        companies.append({'symbol':'EXB.OL','name':'Example Industries ASA'})
        # One exact name is still unambiguous even if the stripped name has two classes.
        self.assertEqual(hi.suggest(rows,companies,{})[0]['symbol'],'EXB.OL')
        companies[0]['name']='Example Industries ASA'
        self.assertFalse(hi.suggest(rows,companies,{})[0]['selected'])
        self.assertEqual(hi.suggest(rows,[],{hi.name_key(rows[0]['name']):'EXA.OL'})[0]['symbol'],'EXA.OL')

    def test_explicit_ticker_checked(self):
        rows=hi.parse(b'Navn;Valuta;Antall;GAV;Ticker\nA;NOK;2;3;EXA\nB;NOK;2;3;AAPL.US\n')
        self.assertEqual(rows[0]['symbol_hint'],'EXA.OL')
        self.assertTrue(rows[1]['error'])

class ImportTransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db_patch=patch.object(app,'DB',Path(self.tmp.name)/'portfolio.db');self.db_patch.start()
        self.worker=patch.object(app,'WORKER',None);self.worker.start()
        app.save_position({'symbol':'EXA','currency':'NOK','shares':1,'cost':12,'thesis':'Keep my notes','review':'Review debt','below':9,'above':20})

    def tearDown(self):
        self.worker.stop();self.db_patch.stop();self.tmp.cleanup()

    def preview(self):
        return app.import_preview(upload())

    def apply(self,p,symbol='EXA.OL'):
        return app.apply_import({'token':p['token'],'selections':[{'id':p['rows'][0]['id'],'symbol':symbol}]})

    def test_preview_changes_no_holdings_and_apply_preserves_notes_and_cost(self):
        before=app.state()['positions']
        p=self.preview()
        self.assertEqual(app.state()['positions'],before)
        self.assertNotIn('file_b64',app.read_meta('pending_holdings_import'))
        result=self.apply(p)
        self.assertEqual(result['updated'],1)
        positions=app.state()['positions'];self.assertEqual(len(positions),1)
        row=positions[0]
        self.assertEqual(row['symbol'],'EXA')
        self.assertEqual(row['shares'],5)
        self.assertEqual(row['cost'],306)  # No additional 79 NOK added to GAV.
        for key in ('thesis','review','below','above'):
            self.assertEqual(row[key],before[0][key])
        self.assertEqual(app.read_meta('holdings_import_status')['updated'],1)

    def test_repeat_upload_replaces_instead_of_adds_and_remembers_ticker(self):
        self.apply(self.preview())
        p=self.preview()
        self.assertEqual(p['rows'][0]['symbol'],'EXA.OL')
        self.assertEqual(p['rows'][0]['match'],'Your saved name match')
        self.apply(p)
        self.assertEqual(app.state()['positions'][0]['shares'],5)

    def test_replay_expired_and_superseded_previews_fail(self):
        p=self.preview();new=self.preview()
        with self.assertRaises(ValueError):
            self.apply(p)
        pending=app.read_meta('pending_holdings_import');pending['expires']=time.time()-1
        app.write_meta('pending_holdings_import',pending)
        with self.assertRaises(ValueError):
            self.apply(new)
        p=self.preview();self.apply(p)
        with self.assertRaises(ValueError):
            self.apply(p)

    def test_manual_changes_after_preview_are_not_overwritten(self):
        p=self.preview()
        with app.connect() as db:
            db.execute("UPDATE positions SET thesis='New notes' WHERE symbol='EXA'")
        with self.assertRaises(ValueError):
            self.apply(p)
        self.assertEqual(app.state()['positions'][0]['thesis'],'New notes')
        self.assertEqual(app.state()['positions'][0]['shares'],1)

    def test_duplicate_selections_are_atomic_and_omitted_holdings_stay(self):
        raw='Navn;Valuta;Antall;GAV\nExample Industries ASA;NOK;5;306\nOther Example ASA;NOK;4;20\n'.encode()
        p=app.import_preview(upload(raw));ids=[r['id'] for r in p['rows']]
        before=copy.deepcopy(app.state()['positions'])
        with self.assertRaises(ValueError):
            app.apply_import({'token':p['token'],'selections':[{'id':i,'symbol':'EXB'} for i in ids]})
        self.assertEqual(app.state()['positions'],before)
        result=app.apply_import({'token':p['token'],'selections':[{'id':ids[1],'symbol':'EXB'}]})
        self.assertEqual(result['updated'],1)
        positions=app.state()['positions']
        self.assertEqual(len(positions),2)
        self.assertEqual(next(r for r in positions if r['symbol']=='EXA')['shares'],1)

    def test_duplicate_existing_aliases_must_be_resolved(self):
        app.save_position({'symbol':'EXA.OL','currency':'NOK','shares':2,'cost':10})
        with self.assertRaises(ValueError):
            self.apply(self.preview())
        self.assertEqual(len(app.state()['positions']),2)

    def test_tampering_and_invalid_inputs_rejected(self):
        p=self.preview()
        for selections in ([],[{'id':999,'symbol':'EXA'}],[{'id':True,'symbol':'EXA'}],[{'id':2,'symbol':'<script>'}]):
            with self.assertRaises(ValueError):
                app.apply_import({'token':p['token'],'selections':selections})
        for encoded in ('not base64!',None,'A'*350001):
            with self.assertRaises(ValueError):
                app.import_preview({'file_b64':encoded})
        self.assertEqual(app.state()['positions'][0]['shares'],1)
