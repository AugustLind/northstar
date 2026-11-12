"""Read-only source fingerprint; no deployment key or runtime database is included."""
import hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def fingerprint(root=ROOT):
    digest=hashlib.sha256()
    paths=sorted(list(root.glob('*.py'))+list((root/'static').glob('*.js'))+list((root/'static').glob('*.css')))+[root/'static/index.html',root/'static/assets.json']
    for path in paths:
        digest.update(str(path.relative_to(root)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()
