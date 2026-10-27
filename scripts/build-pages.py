"""Build only static UI files. Never publish data, Python code or credentials."""
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

root = Path(__file__).resolve().parent.parent
api = os.environ.get('NORTHSTAR_API_URL', '').rstrip('/')
parsed = urlsplit(api)
if not api or parsed.scheme != 'https' or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
    raise SystemExit('Set repository variable NORTHSTAR_API_URL to your HTTPS Oracle origin.')
out = root / 'pages-dist'
if out.exists():
    shutil.rmtree(out)
out.mkdir()
for name in ['index.html', 'style.css', 'app.js', 'advice.js', 'charts.js', 'news.js', 'validation.js', 'portfolio-fit.js', 'holdings-import.js', 'favicon.svg']:
    shutil.copy2(root / 'static' / name, out / name)
(out / 'config.js').write_text('window.NORTHSTAR_CONFIG = ' + json.dumps({'apiBase': api}) + ';\n')
(out / '.nojekyll').touch()
print('Built dashboard for GitHub Pages; only public UI assets and API address included.')
