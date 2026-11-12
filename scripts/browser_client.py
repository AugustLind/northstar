"""Minimal Chrome DevTools client for isolated browser smoke checks; stdlib only."""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

class Browser:
    def __enter__(self):
        self.profile=tempfile.TemporaryDirectory(prefix='northstar-browser-');self.log=tempfile.TemporaryFile();self.errors=[];self.seq=0
        chrome=shutil.which('google-chrome') or shutil.which('chromium') or ('/opt/google/chrome/chrome' if Path('/opt/google/chrome/chrome').is_file() else None)
        if not chrome:raise RuntimeError('Chrome is required for the browser smoke check.')
        self.process=subprocess.Popen([chrome,'--headless','--no-sandbox','--disable-dev-shm-usage','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-sync','--remote-debugging-port=0','--user-data-dir='+self.profile.name,'about:blank'],stdout=self.log,stderr=self.log,start_new_session=True)
        try:
            info=Path(self.profile.name)/'DevToolsActivePort'
            for _ in range(100):
                if info.exists():break
                time.sleep(.1)
            else:raise RuntimeError('Chrome DevTools did not start.')
            port=int(info.read_text().splitlines()[0])
            with urlopen('http://127.0.0.1:'+str(port)+'/json',timeout=10) as response:targets=json.load(response)
            target=next(t for t in targets if t['type']=='page');u=urlsplit(target['webSocketDebuggerUrl'])
            self.sock=socket.create_connection((u.hostname,u.port));self.sock.settimeout(30)
            key=base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall(('GET '+u.path+' HTTP/1.1\r\nHost: '+u.netloc+'\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: '+key+'\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
            response=b''
            while b'\r\n\r\n' not in response:response+=self.sock.recv(1)
            if not response.startswith(b'HTTP/1.1 101 '):raise RuntimeError('Chrome protocol connection failed.')
            self.call('Page.enable');self.call('Runtime.enable');return self
        except Exception:self.__exit__(None,None,None);raise
    def __exit__(self,*args):
        if hasattr(self,'sock'):self.sock.close()
        if hasattr(self,'process') and self.process.poll() is None:
            os.killpg(self.process.pid,signal.SIGTERM);self.process.wait(timeout=10)
        self.log.close();self.profile.cleanup()
    def exact(self,n):
        out=b''
        while len(out)<n:
            data=self.sock.recv(n-len(out))
            if not data:raise RuntimeError('Chrome closed the connection.')
            out+=data
        return out
    def call(self,method,params=None):
        if os.environ.get('NORTHSTAR_SMOKE_DEBUG'):print('Browser command: '+method,flush=True)
        self.seq+=1;data=json.dumps({'id':self.seq,'method':method,'params':params or {}}).encode();n=len(data);mask=os.urandom(4)
        header=bytes([0x81,0x80|n]) if n<126 else bytes([0x81,0xfe])+struct.pack('!H',n) if n<65536 else bytes([0x81,0xff])+struct.pack('!Q',n)
        self.sock.sendall(header+mask+bytes(v^mask[i%4] for i,v in enumerate(data)))
        while True:
            first,second=self.exact(2);size=second&127
            if size==126:size=struct.unpack('!H',self.exact(2))[0]
            elif size==127:size=struct.unpack('!Q',self.exact(8))[0]
            if size>64*1024*1024:raise RuntimeError('Browser protocol frame exceeds the safety limit.')
            mask=self.exact(4) if second&128 else None;raw=self.exact(size)
            if mask:raw=bytes(v^mask[i%4] for i,v in enumerate(raw))
            if first&15!=1:continue
            message=json.loads(raw)
            if message.get('method')=='Runtime.exceptionThrown':self.errors.append('Uncaught browser exception')
            if message.get('id')==self.seq:
                if 'error' in message:raise RuntimeError('Chrome command failed: '+method)
                return message.get('result',{})
    def evaluate(self,expression):
        result=self.call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
        if 'exceptionDetails' in result:raise RuntimeError('Browser evaluation failed.')
        return result['result'].get('value')
    def fill_key(self,key):
        target=self.call('Runtime.evaluate',{'expression':'window'})['result']['objectId']
        result=self.call('Runtime.callFunctionOn',{'objectId':target,'functionDeclaration':"function(key){document.querySelector('#backendAddress').value='';document.querySelector('#accessKey').value=key;document.querySelector('#connectionForm').requestSubmit();}",'arguments':[{'value':key}]})
        if 'exceptionDetails' in result:raise RuntimeError('Browser sign-in failed.')
    def wait(self,expression,label,seconds=30):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            if self.evaluate(expression):return
            time.sleep(.1)
        raise RuntimeError('Timed out: '+label)
