"""Package only explicit public assets; no private data, code archive or credentials."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
import ui_assets
api=os.environ.get('NORTHSTAR_API_URL','').rstrip('/')
u=urlsplit(api)
if not api or u.scheme!='https' or not u.netloc or u.path or u.query or u.fragment or u.username or u.password:
    raise SystemExit('Set repository variable NORTHSTAR_API_URL to your HTTPS Oracle origin.')
out=root/'pages-dist'
if out.exists():shutil.rmtree(out)
out.mkdir()
for name in ui_assets.public_files(root):shutil.copy2(root/'static'/name,out/name)
config='window.NORTHSTAR_CONFIG = '+json.dumps({'apiBase':api})+';\n'
(out/'config.js').write_text(config)
html=(out/'index.html').read_text()
html=re.sub(r'config\.js(?:\?v=[a-f0-9]+)?', 'config.js?v='+hashlib.sha256(config.encode()).hexdigest()[:12],html)
(out/'index.html').write_text(html);(out/'.nojekyll').touch()
print('Built public dashboard assets; private data and credentials excluded.')
