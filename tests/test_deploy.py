import io
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


class DeployTests(unittest.TestCase):
    def test_deploy_and_rollback_preserve_database(self):
        script=Path(__file__).resolve().parent.parent/'scripts/deploy-oracle.sh'
        for healthy in [True,False]:
            with self.subTest(healthy=healthy),tempfile.TemporaryDirectory() as tmp:
                home=Path(tmp);root=home/'northstar';root.mkdir()
                (root/'data').mkdir();(root/'data/portfolio.db').write_bytes(b'PRIVATE DATA')
                (root/'app.py').write_text('old_version=True\n')
                fakebin=home/'bin';fakebin.mkdir()
                for name,code in [('sudo','exit 0'),('curl','exit '+('0' if healthy else '1')),('sleep','exit 0')]:
                    p=fakebin/name;p.write_text('#!/bin/sh\n'+code+'\n');p.chmod(0o755)
                archive=home/'deploy.tar.gz'
                with tarfile.open(archive,'w:gz') as tar:
                    fixture_test = 'import unittest\n\nclass SmokeTest(unittest.TestCase):\n    def test_smoke(self):\n        self.assertTrue(True)\n'
                    for name,text in [('app.py','new_version=True\n'),('research.py',''),('tests/test_ok.py',fixture_test)]:
                        data=text.encode();info=tarfile.TarInfo(name);info.size=len(data);tar.addfile(info,io.BytesIO(data))
                result=subprocess.run(['bash',str(script),str(archive)],capture_output=True,text=True,
                    env={**os.environ,'HOME':str(home),'PATH':str(fakebin)+':'+os.environ['PATH']})
                self.assertEqual(result.returncode,0 if healthy else 1,result.stderr)
                self.assertEqual((root/'data/portfolio.db').read_bytes(),b'PRIVATE DATA')
                self.assertIn('new_version' if healthy else 'old_version',(root/'app.py').read_text())

    def test_archive_traversal_is_rejected_before_service_stop(self):
        script=Path(__file__).resolve().parent.parent/'scripts/deploy-oracle.sh'
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp);archive=home/'bad.tar.gz'
            with tarfile.open(archive,'w:gz') as tar:
                data=b'escape';info=tarfile.TarInfo('../escape');info.size=len(data);tar.addfile(info,io.BytesIO(data))
            result=subprocess.run(['bash',str(script),str(archive)],capture_output=True,text=True,env={**os.environ,'HOME':tmp})
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Unsafe deployment archive',result.stderr)
            self.assertFalse((home/'escape').exists())
