"""One explicit public asset manifest shared by serving, packaging and checks."""
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def manifest(root=ROOT):
    value=json.loads((root/'static/assets.json').read_text())
    if set(value)!={'scripts','styles','images'}:raise ValueError('Unexpected public asset manifest fields.')
    names=[]
    for group,suffix in [('scripts','.js'),('styles','.css'),('images','.svg')]:
        for name in value[group]:
            if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*'+re.escape(suffix),name):raise ValueError('Only named public assets may be published.')
            if name in names:raise ValueError('Duplicate public asset.')
            names.append(name)
    return value

def public_files(root=ROOT):
    m=manifest(root)
    names=['index.html','assets.json']+m['styles']+m['scripts']+m['images']
    for name in names:
        path=root/'static'/name
        if path.is_symlink() or path.resolve().parent!=(root/'static').resolve():raise ValueError('Public assets cannot link to private or external files.')
    return names
