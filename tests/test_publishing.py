import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parent.parent/'scripts/wait-for-default-pages.py'
spec=importlib.util.spec_from_file_location('pages_wait',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublishingOrderTests(unittest.TestCase):
    def test_waits_only_for_default_publisher_for_current_commit(self):
        runs=[{'head_sha':'current','name':'pages build and deployment','status':'in_progress'},
              {'head_sha':'old','name':'pages build and deployment','status':'queued'},
              {'head_sha':'current','name':'Deploy Northstar','status':'in_progress'},
              {'head_sha':'current','name':'pages build and deployment','status':'completed'}]
        self.assertEqual(module.pending_default_builds(runs,'current'),runs[:1])

    def test_actions_only_configuration_does_not_wait(self):
        self.assertEqual(module.pending_default_builds([
            {'head_sha':'current','path':'.github/workflows/deploy.yml','status':'in_progress'}],'current'),[])
