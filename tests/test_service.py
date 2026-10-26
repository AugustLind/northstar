import subprocess
import sys
import unittest
from pathlib import Path


class ServiceUnitTests(unittest.TestCase):
    def test_working_directory_is_an_unquoted_absolute_path(self):
        root = Path(__file__).resolve().parent.parent
        for mode in [[], ['--system']]:
            unit = subprocess.check_output(
                [sys.executable, str(root / 'scripts/service-unit.py'), *mode], text=True)
            working = next(line for line in unit.splitlines() if line.startswith('WorkingDirectory='))
            self.assertEqual(working, 'WorkingDirectory=' + str(root).replace('%', '%%'))
            self.assertTrue(working.split('=', 1)[1].startswith('/'))
