"""Let an existing branch-based Pages publisher finish before our UI publishes."""
import json
import os
import time
from urllib.request import Request, urlopen


def pending_default_builds(runs, sha):
    return [r for r in runs if r.get('head_sha') == sha and
            (r.get('path', '').startswith('dynamic/pages/') or r.get('name') == 'pages build and deployment')
            and r.get('status') != 'completed']


def wait_for_default_builds():
    token = os.environ['GH_TOKEN']
    repo = os.environ['GITHUB_REPOSITORY']
    sha = os.environ['GITHUB_SHA']
    request = Request(f'https://api.github.com/repos/{repo}/actions/runs?per_page=100',
                      headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json'})
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        with urlopen(request, timeout=20) as response:
            runs = json.load(response)['workflow_runs']
        if not pending_default_builds(runs, sha):
            print('No competing default Pages publisher is running. Publishing the dashboard next.')
            return
        print('Waiting for the default Pages publisher to finish so it cannot overwrite the dashboard.', flush=True)
        time.sleep(10)
    raise SystemExit('Default Pages publisher did not finish in five minutes. Set Pages Source to GitHub Actions, then retry.')


if __name__ == '__main__':
    wait_for_default_builds()
