"""Read-only authenticated release checks. Access key is read privately on Oracle."""
import argparse
import hashlib
import http.client
import socket
import json
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError,URLError
from urllib.parse import urlsplit,urljoin
from urllib.request import Request,urlopen,build_opener,HTTPSHandler,HTTPRedirectHandler,ProxyHandler
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import release_info
import ui_assets


class PrivateRedirects(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class LocalTLSConnection(http.client.HTTPSConnection):
    """Verify the configured public TLS name through nginx without public-IP hairpinning."""
    def connect(self):
        if self._tunnel_host:raise ValueError('Private smoke checks do not use proxy tunnels.')
        self.sock=socket.create_connection(('127.0.0.1',self.port),self.timeout)
        self.sock=self._context.wrap_socket(self.sock,server_hostname=self.host)

class LocalTLSHandler(HTTPSHandler):
    def https_open(self,request):return self.do_open(LocalTLSConnection,request,context=self._context)

def private_opener():return build_opener(ProxyHandler({}),PrivateRedirects(),LocalTLSHandler())

def check_cors(origin,key,page_origin):
    opener=private_opener()
    for method in ('OPTIONS','GET'):
        headers={'Origin':page_origin}
        if method=='OPTIONS':headers.update({'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
        else:headers['Authorization']='Bearer '+key
        try:
            with opener.open(Request(origin+'/api/state',headers=headers,method=method),timeout=20) as response:
                if response.status!=(204 if method=='OPTIONS' else 200) or response.headers.get('Access-Control-Allow-Origin')!=page_origin:
                    raise ValueError('Public dashboard CORS contract failed.')
                if method=='OPTIONS':
                    allowed={h.strip().lower() for h in response.headers.get('Access-Control-Allow-Headers','').split(',')}
                    if not {'authorization','content-type'}.issubset(allowed) or 'POST' not in response.headers.get('Access-Control-Allow-Methods',''):
                        raise ValueError('Public dashboard preflight contract failed.')
        except (HTTPError,URLError,TimeoutError,OSError):raise ValueError('Public dashboard CORS request failed.')
    print('Public dashboard preflight and authenticated CORS passed.')

def get(origin,path,key=None):
    headers={'Cache-Control':'no-cache'}
    if key:headers['Authorization']='Bearer '+key
    opener=private_opener()
    try:
        with opener.open(Request(origin+path,headers=headers),timeout=20) as response:return response.status,response.read()
    except HTTPError as error:return error.code,b''
    except (URLError,TimeoutError,OSError):raise ValueError('Service could not be reached securely.')


def check(origin,key,page_url=None,root=release_info.ROOT):
    parsed=urlsplit(origin)
    if parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment or parsed.scheme not in ('http','https'):
        raise ValueError('Use a plain service origin.')
    if parsed.scheme!='https' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Remote checks require HTTPS.')
    origin=origin.rstrip('/')
    if parsed.scheme=='https':
        status,local=get('http://127.0.0.1:8000','/api/release',key)
        try:trusted=json.loads(local) if status==200 else {}
        except (ValueError,UnicodeError):trusted={}
        if trusted.get('public_origin')!=origin:raise ValueError('Remote origin does not match the running service; access key was not sent remotely.')
    status,body=get(origin,'/api/state')
    if status!=401:raise ValueError('Anonymous private-data read was not denied.')
    print('Anonymous private-data read denied.')
    status,_=get(origin,'/api/state','not-the-northstar-access-key')
    if status!=401:raise ValueError('Invalid bearer key was not denied.')
    print('Invalid bearer key denied.')
    expected=release_info.fingerprint(root)
    paths={'/api/release':('source_fingerprint',str),'/api/state':('positions',list),'/api/research':('worker',dict),'/api/ledger':('events',list),
           '/api/account-performance':('status',str),'/api/archive':('kinds',list),'/api/system-status':('components',list)}
    for path,(required,kind) in paths.items():
        status,body=get(origin,path,key)
        if status!=200:raise ValueError('Authenticated check failed for '+path+' (HTTP '+str(status)+').')
        try:value=json.loads(body)
        except (ValueError,UnicodeError):raise ValueError('Invalid JSON for '+path+'.')
        if required not in value or not isinstance(value[required],kind):raise ValueError('Response contract failed for '+path+'.')
        if path=='/api/release' and value[required]!=expected:raise ValueError('Running process does not match deployed source.')
        print('Authenticated '+path+' passed.')
    if page_url:
        p=urlsplit(page_url)
        if p.scheme!='https' or p.username or p.password or p.query or p.fragment:raise ValueError('Use the HTTPS public Pages URL.')
        check_cors(origin,key,p.scheme+'://'+p.netloc)
        page_url=page_url.rstrip('/')+'/'
        try:
            with urlopen(Request(page_url+'?release='+expected[:12],headers={'Cache-Control':'no-cache'}),timeout=20) as response:html=response.read().decode()
        except (URLError,TimeoutError,OSError):raise ValueError('Public dashboard could not be read.')
        from html.parser import HTMLParser
        class Assets(HTMLParser):
            def __init__(self):super().__init__();self.scripts=[];self.styles=[];self.tabs=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='script' and attrs.get('src'):self.scripts.append(attrs['src'])
                if tag=='link' and attrs.get('rel')=='stylesheet':self.styles.append(attrs['href'])
                if 'data-tab' in attrs:self.tabs.append(attrs['data-tab'])
        parsed_html=Assets();parsed_html.feed(html);manifest=ui_assets.manifest(root)
        if parsed_html.tabs!=['daily','recommendations','portfolio','validation']:raise ValueError('Public workspace contract failed.')
        if [Path(urlsplit(p).path).name for p in parsed_html.scripts]!=manifest['scripts']:raise ValueError('Public script manifest is stale or incomplete.')
        if [Path(urlsplit(p).path).name for p in parsed_html.styles]!=manifest['styles']:raise ValueError('Public style manifest is stale or incomplete.')
        for relative in parsed_html.scripts+parsed_html.styles:
            name=Path(urlsplit(relative).path).name
            url=urljoin(page_url,relative)
            if urlsplit(url).netloc!=urlsplit(page_url).netloc:raise ValueError('Unexpected public asset origin.')
            try:
                with urlopen(Request(url,headers={'Cache-Control':'no-cache'}),timeout=20) as response:content=response.read()
            except (URLError,TimeoutError,OSError):raise ValueError('Public asset unavailable: '+name)
            if name=='config.js':
                match=re.search(rb'window.NORTHSTAR_CONFIG\s*=\s*(\{.*?\})',content)
                if not match or json.loads(match[1])!={'apiBase':origin}:raise ValueError('Public API configuration does not match the checked service.')
            elif hashlib.sha256(content).digest()!=hashlib.sha256((root/'static'/name).read_bytes()).digest():raise ValueError('Public asset does not match deployed code: '+name)
        print('Public dashboard and every script/style match the authenticated service.')
    return True


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--origin',default='http://127.0.0.1:8000');parser.add_argument('--page-url');parser.add_argument('--origin-stdin',action='store_true')
    parser.add_argument('--key-file',type=Path,default=Path.home()/'.config/northstar/access-key');parser.add_argument('--attempts',type=int,default=1)
    args=parser.parse_args()
    if args.origin_stdin:args.origin=sys.stdin.readline().strip()
    try:key=args.key_file.read_text().strip()
    except OSError:raise SystemExit('Private server access-key file is unavailable; authenticated verification cannot run.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{40,100}',key):raise SystemExit('Private server access-key file is invalid.')
    attempts=max(1,min(12,args.attempts))
    for attempt in range(attempts):
        try:check(args.origin,key,args.page_url);return
        except ValueError as error:
            if attempt+1==attempts:raise SystemExit(str(error))
            time.sleep(3)
if __name__=='__main__':main()
