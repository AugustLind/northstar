"""Exercise setup prompts with fake deployment tools; no network or secrets used."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class SetupInputTests(unittest.TestCase):
    def run_setup(self, host, domain=''):
        script = Path(__file__).resolve().parents[1] / 'scripts/setup-github-deploy.sh'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key = root / 'test-key'
            key.write_text('synthetic test fixture')
            fakebin = root / 'bin'
            fakebin.mkdir()
            log = root / 'calls.log'
            commands = {
                'gh': '''case "$1 $2" in
"auth status") exit 0 ;;
"repo view") printf 'ExampleOwner\\n' ;;
"secret set") cat >/dev/null ;;
"variable set") printf '%s\\n' "$*" >> "$NORTHSTAR_TEST_LOG" ;;
*) exit 1 ;;
esac
''',
                'ssh': '''case "$*" in
*ssh_host_ed25519_key.pub*) printf 'ssh-ed25519 TEST_PUBLIC_KEY\\n' ;;
*) cat >/dev/null ;;
esac
''',
                'git': "printf 'synthetic source archive'\n",
            }
            for name, body in commands.items():
                path = fakebin / name
                path.write_text('#!/bin/sh\n' + body)
                path.chmod(0o755)
            result = subprocess.run(['bash', str(script)],
                input=f'{key}\n{host}\n{domain}\n', capture_output=True, text=True,
                env={**os.environ, 'PATH':str(fakebin) + ':' + os.environ['PATH'],
                     'NORTHSTAR_TEST_LOG':str(log)})
            return result, log.read_text() if log.exists() else ''

    def test_missing_or_invalid_host_does_not_configure_deployment(self):
        for host in ['', '999.10.20.30', 'example.com', '127.0.0.1;echo unsafe']:
            with self.subTest(host=host):
                result, log = self.run_setup(host)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('valid Oracle IPv4', result.stderr)
                self.assertEqual(log, '')

    def test_default_domain_comes_from_entered_host(self):
        result, log = self.run_setup('203.0.113.10')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ORACLE_HOST --body 203.0.113.10', log)
        self.assertIn('NORTHSTAR_API_URL --body https://203-0-113-10.sslip.io', log)

    def test_custom_domain_is_kept(self):
        result, log = self.run_setup('203.0.113.10', 'northstar.example.com')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('NORTHSTAR_API_URL --body https://northstar.example.com', log)
