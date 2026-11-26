"""Read-only source fingerprint; no deployment key or runtime database is included."""
import hashlib
from pathlib import Path
import ui_assets
ROOT=Path(__file__).resolve().parent

def fingerprint(root=ROOT):
    digest=hashlib.sha256()
    paths = sorted([*root.glob('*.py'), *(root/'static'/name for name in ui_assets.public_files(root))])
    for path in paths:
        digest.update(str(path.relative_to(root)).encode());digest.update(path.read_bytes())
    return digest.hexdigest()
