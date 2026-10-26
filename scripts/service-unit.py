"""Print a user systemd unit using this checkout's absolute path."""
from pathlib import Path
import sys

root = Path(__file__).resolve().parent.parent

def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'

print(f'''[Unit]
Description=Northstar local investment research
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={quoted(root)}
ExecStart={quoted(sys.executable)} {quoted(root / 'app.py')}
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1
UMask=0077

[Install]
WantedBy=default.target
''')
