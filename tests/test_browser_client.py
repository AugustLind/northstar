import importlib.util
import io
import json
from pathlib import Path
import struct
import unittest
path=Path(__file__).resolve().parents[1]/'scripts/browser_client.py'
spec=importlib.util.spec_from_file_location('browser_client_test',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class BrowserProtocolTests(unittest.TestCase):
    def test_extended_payload_lengths_do_not_consume_json_as_a_second_header(self):
        class Socket:
            def __init__(self,packet):self.data=io.BytesIO(packet)
            def recv(self,n):return self.data.read(min(n,1000))
            def sendall(self,data):pass
        for length in (127,65536):
            baseline=len(json.dumps({'id':1,'result':{'value':''}}).encode())
            payload=json.dumps({'id':1,'result':{'value':'x'*(length-baseline)}}).encode()
            header=b'\x81\x7e'+struct.pack('!H',length) if length<65536 else b'\x81\x7f'+struct.pack('!Q',length)
            browser=module.Browser.__new__(module.Browser);browser.sock=Socket(header+payload);browser.seq=0;browser.errors=[]
            result=browser.call('Runtime.evaluate',{'expression':'window'})
            self.assertEqual(len(result['value']),length-baseline)
