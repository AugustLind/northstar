"""Print a user systemd unit using this checkout's absolute path."""
from pathlib import Path
import sys
import getpass
import grp
import os

root = Path(__file__).resolve().parent.parent

def quoted(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'

system = '--system' in sys.argv
service_options = ''
if system:
    service_options = f'''User={getpass.getuser()}
Group={grp.getgrgid(os.getgid()).gr_name}
EnvironmentFile=-/etc/northstar.env
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=read-only
ReadWritePaths={quoted(root / 'data')}
'''

print(f'''[Unit]
Description=Northstar local investment research
After=network-online.target{' ollama.service' if system else ''}
Wants=network-online.target

[Service]
Type=simple
{service_options.rstrip()}
WorkingDirectory={str(root).replace('%', '%%')}
ExecStart={quoted(sys.executable)} {quoted(root / 'app.py')}
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1
UMask=0077

[Install]
WantedBy={'multi-user.target' if system else 'default.target'}
''')
