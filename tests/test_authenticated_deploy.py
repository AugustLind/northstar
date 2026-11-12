import contextlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import release_info

path=Path(__file__).resolve().parents[1]/'scripts/smoke-deployment.py'
spec=importlib.util.spec_from_file_location('deployment_smoke',path);smoke=importlib.util.module_from_spec(spec);spec.loader.exec_module(smoke)

class AuthenticatedDeploymentTests(unittest.TestCase):
    def test_reads_contracts_without_logging_private_data_or_key(self):
        secret='private-key-never-print';calls=[];origin='https://api.example.com'
        values={'/api/release':{'source_fingerprint':release_info.fingerprint(),'public_origin':origin},
                '/api/state':{'positions':[{'symbol':'PRIVATE-TICKER'}]},'/api/research':{'worker':{},'commentary':'PRIVATE-NOTE'},
                '/api/ledger':{'events':[]},'/api/account-performance':{'status':'unavailable'},'/api/archive':{'kinds':[]},'/api/system-status':{'components':[]}}
        def get(base,path,key=None):
            calls.append((base,path,key));return (401,b'') if key in (None,'not-the-northstar-access-key') else (200,json.dumps(values[path]).encode())
        stream=io.StringIO()
        with patch.object(smoke,'get',side_effect=get),contextlib.redirect_stdout(stream):self.assertTrue(smoke.check(origin,secret))
        for private in (secret,'PRIVATE-TICKER','PRIVATE-NOTE'):self.assertNotIn(private,stream.getvalue())
        self.assertEqual(calls[0][0],'http://127.0.0.1:8000')
        self.assertTrue(all(path.startswith('/api/') for base,path,key in calls))

    def test_untrusted_remote_origin_never_receives_the_key(self):
        calls=[]
        def get(base,path,key=None):calls.append((base,key));return 200,json.dumps({'public_origin':'https://trusted.example.com'}).encode()
        with patch.object(smoke,'get',side_effect=get),self.assertRaisesRegex(ValueError,'not sent remotely'):smoke.check('https://untrusted.example.com','private')
        self.assertEqual(calls,[('http://127.0.0.1:8000','private')])

    def test_anonymous_access_or_old_running_process_fail_closed(self):
        with patch.object(smoke,'get',return_value=(200,b'{"positions":[]}')),self.assertRaisesRegex(ValueError,'not denied'):smoke.check('http://127.0.0.1:8000','private')
        def old(base,path,key=None):return (401,b'') if key in (None,'not-the-northstar-access-key') else (200,b'{"source_fingerprint":"old"}')
        with patch.object(smoke,'get',side_effect=old),contextlib.redirect_stdout(io.StringIO()),self.assertRaisesRegex(ValueError,'does not match'):smoke.check('http://127.0.0.1:8000','private')


    def test_workflow_printf_preserves_private_multiline_files(self):
        import os,re,subprocess
        text=(Path(__file__).resolve().parents[1]/'.github/workflows/deploy.yml').read_text()
        formats=set(re.findall(r"printf ('[^']*')",text))
        self.assertTrue(formats)
        for format in formats:
            result=subprocess.run(['bash','-c','printf '+format+' "$SMOKE_VALUE"'],env={**os.environ,'SMOKE_VALUE':'first line\nsecond line'},capture_output=True,check=True)
            self.assertEqual(result.stdout,b'first line\nsecond line\n')


    def test_local_tls_keeps_public_sni_and_certificate_verification(self):
        import ssl
        from unittest.mock import Mock
        connection=smoke.LocalTLSConnection('api.example.com')
        self.assertTrue(connection._context.check_hostname)
        self.assertEqual(connection._context.verify_mode,ssl.CERT_REQUIRED)
        context=Mock();connection._context=context
        with patch.object(smoke.socket,'create_connection',return_value=Mock()) as connect:
            connection.connect()
        self.assertEqual(connect.call_args.args[0],('127.0.0.1',443))
        self.assertEqual(context.wrap_socket.call_args.kwargs['server_hostname'],'api.example.com')


    def test_public_browser_preflight_and_bearer_cors_are_verified(self):
        class Response:
            def __init__(self,method):
                self.status=204 if method=='OPTIONS' else 200
                self.headers={'Access-Control-Allow-Origin':'https://pages.example.com','Access-Control-Allow-Headers':'Authorization,Content-Type','Access-Control-Allow-Methods':'GET, POST, OPTIONS'}
            def __enter__(self):return self
            def __exit__(self,*args):pass
        requests=[]
        class Opener:
            def open(self,request,timeout):requests.append(request);return Response(request.get_method())
        with patch.object(smoke,'private_opener',return_value=Opener()),contextlib.redirect_stdout(io.StringIO()):
            smoke.check_cors('https://api.example.com','private','https://pages.example.com')
        self.assertEqual([r.get_method() for r in requests],['OPTIONS','GET'])
        self.assertNotIn('Authorization',requests[0].headers)
        self.assertEqual(requests[1].headers['Authorization'],'Bearer private')
