"""Run interactively on Oracle: private SMTP configuration, no secrets in command arguments."""
import getpass
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import email_alerts


def environment_text(values):
    lines = []
    for key, value in values.items():
        if any(c in value for c in '\r\n\x00'):
            raise ValueError('Settings cannot contain line breaks or null characters.')
        # systemd EnvironmentFile syntax; this file is never sourced by a shell.
        quoted = value.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(key+'="'+quoted+'"')
    return '\n'.join(lines)+'\n'


def main():
    print('Configure Northstar email on this Oracle server. Password input is hidden.')
    print('Use your provider\'s SMTP credentials or app password. Keep them out of GitHub and chat.')
    host = input('SMTP host: ').strip()
    security = input('Security [starttls / ssl] (starttls): ').strip() or 'starttls'
    port = input('SMTP port ('+('465' if security == 'ssl' else '587')+'): ').strip() or ('465' if security == 'ssl' else '587')
    username = input('SMTP username: ').strip()
    sender = input('From email address: ').strip()
    recipient = input('Send alerts to: ').strip()
    password = getpass.getpass('SMTP app password / SMTP password: ')
    values = {'NORTHSTAR_EMAIL_ENABLED': '1', 'NORTHSTAR_SMTP_HOST': host,
              'NORTHSTAR_SMTP_PORT': port, 'NORTHSTAR_SMTP_SECURITY': security,
              'NORTHSTAR_SMTP_USERNAME': username, 'NORTHSTAR_SMTP_PASSWORD': password,
              'NORTHSTAR_EMAIL_FROM': sender, 'NORTHSTAR_EMAIL_TO': recipient}
    config = email_alerts.configuration(values)
    if config['errors']:
        raise SystemExit('\n'.join(config['errors']))
    with tempfile.TemporaryDirectory(prefix='northstar-email-') as temp:
        env_path = Path(temp)/'email.env'
        # TemporaryDirectory is private; chmod before writing secrets as well.
        fd = os.open(env_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            stream.write(environment_text(values))
        subprocess.run(['sudo', 'install', '-m', '600', str(env_path), '/etc/northstar-email.env'], check=True)
        # A drop-in also enables email on existing installed service units.
        dropin = Path(temp)/'email.conf'
        dropin.write_text('[Service]\nEnvironmentFile=-/etc/northstar-email.env\n')
        subprocess.run(['sudo', 'install', '-d', '/etc/systemd/system/northstar.service.d'], check=True)
        subprocess.run(['sudo', 'install', '-m', '644', str(dropin), '/etc/systemd/system/northstar.service.d/email.conf'], check=True)
    subprocess.run(['sudo', 'systemctl', 'daemon-reload'], check=True)
    subprocess.run(['sudo', 'systemctl', 'restart', 'northstar'], check=True)
    print('SMTP configuration installed privately. Open Daily overview, enable email alerts if paused, and select Send test email.')


if __name__ == '__main__':
    main()
