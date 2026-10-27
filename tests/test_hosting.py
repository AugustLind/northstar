import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
import app


class HostingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=patch.object(app,'DB',Path(self.temp.name)/'db.sqlite')
        self.db.start()
        self.env=patch.dict(os.environ,{
            'NORTHSTAR_ACCESS_KEY_HASH': hashlib.sha256(b'test-key').hexdigest(),
            'NORTHSTAR_PUBLIC_ORIGIN': 'https://api.example.com',
            'NORTHSTAR_PAGES_ORIGIN': 'https://owner.github.io'})
        self.env.start()

    def tearDown(self):
        self.env.stop(); self.db.stop(); self.temp.cleanup()

    def request(self, method, path, headers=None, body=None):
        h=app.Handler.__new__(app.Handler)
        h.path=path
        h.headers=Message()
        for k,v in (headers or {}).items():
            h.headers[k]=v
        payload=json.dumps(body or {}).encode()
        h.headers['Content-Length']=str(len(payload))
        h.rfile=io.BytesIO(payload);h.wfile=io.BytesIO()
        result={'headers':{}}
        h.send_response=lambda code: result.update(status=code)
        h.send_header=lambda k,v:result['headers'].update({k:v})
        h.end_headers=lambda:None
        getattr(h,'do_'+method)()
        result['body']=json.loads(h.wfile.getvalue()) if h.wfile.getvalue() else None
        return result

    def test_portfolio_requires_access_key(self):
        headers={'Origin':'https://owner.github.io','Host':'api.example.com'}
        denied=self.request('GET','/api/state',headers)
        self.assertEqual(denied['status'],401)
        self.assertEqual(denied['headers']['Access-Control-Allow-Origin'],'https://owner.github.io')
        headers['Authorization']='Bearer test-key'
        allowed=self.request('GET','/api/state',headers)
        self.assertEqual(allowed['status'],200)
        self.assertEqual(allowed['body']['positions'],[])

    def test_preflight_is_allowed_only_for_configured_origins(self):
        allowed=self.request('OPTIONS','/api/state',{'Origin':'https://owner.github.io'})
        self.assertEqual(allowed['status'],204)
        self.assertIn('Authorization',allowed['headers']['Access-Control-Allow-Headers'])
        denied=self.request('OPTIONS','/api/state',{'Origin':'https://attacker.example'})
        self.assertEqual(denied['status'],403)
        self.assertNotIn('Access-Control-Allow-Origin',denied['headers'])

    def test_health_is_public_but_discloses_no_portfolio(self):
        response=self.request('GET','/api/health')
        self.assertEqual(response['body'],{'ok':True})

    def test_authentication_fails_closed_if_pages_is_enabled_without_key(self):
        with patch.dict(os.environ,{'NORTHSTAR_ACCESS_KEY_HASH':''}):
            self.assertFalse(app.api_authorized(None))
        self.assertFalse(app.api_authorized('Bearer wrong-key'))

    def test_write_requires_key_and_allowed_origin(self):
        headers={'Origin':'https://owner.github.io','Content-Type':'application/json'}
        self.assertEqual(self.request('POST','/api/position',headers)['status'],401)
        headers.update(Authorization='Bearer test-key',Origin='https://attacker.example')
        self.assertEqual(self.request('POST','/api/position',headers)['status'],403)

    def test_announcement_records_and_review_state_require_authentication(self):
        self.assertEqual(self.request('GET','/api/announcements?symbol=KOG')['status'],401)
        headers={'Authorization':'Bearer test-key','Content-Type':'application/json'}
        response=self.request('GET','/api/announcements?symbol=KOG',headers)
        self.assertEqual(response['status'],200)
        self.assertEqual(response['body']['focus_symbols'],['KOG.OL'])
        self.assertEqual(response['body']['status'],'unavailable')
        self.assertEqual(self.request('POST','/api/announcements/reviewed',headers)['status'],200)
        self.assertGreater(app.read_meta('announcements_reviewed_at'),0)

    def test_pages_build_contains_only_static_assets(self):
        import shutil
        root=Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            staged=Path(tmp)
            (staged/'scripts').mkdir();(staged/'static').mkdir();(staged/'data').mkdir()
            shutil.copy2(root/'scripts/build-pages.py',staged/'scripts/build-pages.py')
            for name in ['index.html','style.css','app.js','advice.js','charts.js','news.js', 'validation.js','favicon.svg']:
                shutil.copy2(root/'static'/name,staged/'static'/name)
            (staged/'data/private.db').write_text('private portfolio')
            subprocess.run([sys.executable,str(staged/'scripts/build-pages.py')],check=True,capture_output=True,
                env={**os.environ,'NORTHSTAR_API_URL':'https://api.example.com'})
            output=staged/'pages-dist'
            self.assertEqual(set(p.name for p in output.iterdir()),{'index.html','style.css','app.js','advice.js','charts.js','news.js', 'validation.js','favicon.svg','config.js','.nojekyll'})
            self.assertIn('https://api.example.com',(output/'config.js').read_text())
            self.assertNotIn('private portfolio',''.join(p.read_text() for p in output.iterdir()))
            self.assertNotIn('href="/style.css"',(output/'index.html').read_text())


if __name__=='__main__':
    unittest.main()
