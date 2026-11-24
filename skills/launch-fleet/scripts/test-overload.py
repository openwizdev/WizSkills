#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
FLEET = HERE / 'fleet.sh'
NOW = 1800000000
REPO = 'synthetic-owner/synthetic-repo'


def healthy(now=NOW, repo=REPO):
    return {
        'repository': repo,
        'observed_at': now,
        'complete': True,
        'queue': {'complete': True, 'jobs': []},
        'budgets': {
            'rest': {'remaining': 4500, 'limit': 5000, 'reset_at': now + 3600, 'retry_after': 0},
            'graphql': {'remaining': 4500, 'limit': 5000, 'reset_at': now + 3600, 'retry_after': 0},
        },
    }


def make_fake_gh(bin_dir, state_file):
    gh = bin_dir / 'gh'
    gh.write_text(
        '#!/usr/bin/env python3\n'
        'import json, os, sys\n'
        'cfg = json.loads(open(%r).read())\n'
        'if cfg.get("fail"):\n'
        '    sys.stderr.write("gh failed\\n")\n'
        '    sys.exit(1)\n'
        'args = sys.argv[1:]\n'
        'if args[:2] != ["api", "--include"]:\n'
        '    sys.stderr.write("unexpected gh args: " + repr(args) + "\\n")\n'
        '    sys.exit(2)\n'
        'target = args[2]\n'
        'def emit(body, resource="core", remaining=4500, limit=5000, reset=1800003600, status=200, extra=None):\n'
        '    lines = [\n'
        '        f"HTTP/2.0 {status} OK",\n'
        '        f"x-ratelimit-resource: {resource}",\n'
        '        f"x-ratelimit-remaining: {remaining}",\n'
        '        f"x-ratelimit-limit: {limit}",\n'
        '        f"x-ratelimit-reset: {reset}",\n'
        '    ]\n'
        '    for k, v in (extra or {}).items():\n'
        '        lines.append(f"{k}: {v}")\n'
        '    sys.stdout.write("\\r\\n".join(lines) + "\\r\\n\\r\\n" + json.dumps(body))\n'
        'if target == "rate_limit":\n'
        '    rest = cfg.get("rest", {"remaining": 4500, "limit": 5000, "reset": 1800003600})\n'
        '    gql = cfg.get("graphql", {"remaining": 4500, "limit": 5000, "reset": 1800003600})\n'
        '    emit({"resources": {"core": rest, "graphql": gql}})\n'
        'elif target == "graphql":\n'
        '    gql = cfg.get("graphql", {"remaining": 4500, "limit": 5000, "reset": 1800003600})\n'
        '    emit({"data": {"rateLimit": {"remaining": gql["remaining"]}}}, resource="graphql",\n'
        '         remaining=gql["remaining"], limit=gql["limit"], reset=gql["reset"])\n'
        'elif "/actions/runs?" in target:\n'
        '    status = target.split("status=")[1].split("&")[0]\n'
        '    runs = [r for r in cfg.get("runs", []) if r["status"] == status]\n'
        '    emit({"total_count": len(runs), "workflow_runs": runs})\n'
        'elif "/jobs?" in target:\n'
        '    rid = int(target.split("/runs/")[1].split("/jobs")[0])\n'
        '    jobs = cfg.get("jobs", {}).get(str(rid), [])\n'
        '    emit({"total_count": len(jobs), "jobs": jobs})\n'
        'else:\n'
        '    sys.stderr.write("unhandled target: " + target + "\\n")\n'
        '    sys.exit(2)\n' % str(state_file)
    )
    gh.chmod(0o755)


class OverloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'pause.json'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.gh_state = self.root / 'gh.json'
        self.gh_state.write_text(json.dumps({}))
        make_fake_gh(self.bin, self.gh_state)

    def run_fleet(self, action, **extra_env):
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('LAUNCH_FLEET_OVERLOAD_')}
        env.update(
            PATH=str(self.bin) + os.pathsep + env.get('PATH', ''),
            GH_REPO=REPO,
            LAUNCH_FLEET_NOW=str(NOW),
            LAUNCH_FLEET_OVERLOAD_STATE=str(self.state),
        )
        for k, v in extra_env.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        return subprocess.run(
            ['sh', str(FLEET), 'overload', action],
            env=env, capture_output=True, text=True, timeout=10,
        )

    def test_fresh_install_admits_healthy_merge_batch_without_configured_supplier(self):
        r = self.run_fleet('merge-batch')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        answer = json.loads(r.stdout)
        self.assertTrue(answer['allowed'])
        self.assertFalse(answer['paused'])
        self.assertEqual(answer['level'], 'healthy')
        self.assertFalse(self.state.exists())

    def test_fresh_install_pauses_on_overloaded_queue_and_resumes_explicitly(self):
        self.gh_state.write_text(json.dumps({
            'runs': [{'id': 101, 'run_attempt': 1, 'event': 'pull_request', 'status': 'queued'}],
            'jobs': {'101': [{
                'id': 501, 'run_id': 101, 'run_attempt': 1, 'status': 'queued',
                'created_at': '2027-01-15T07:53:20Z', 'started_at': None,
            }]},
        }))
        paused = self.run_fleet('merge-batch')
        self.assertEqual(paused.returncode, 1, paused.stdout + paused.stderr)
        ans = json.loads(paused.stdout)
        self.assertFalse(ans['allowed'])
        self.assertEqual(ans['level'], 'alarm')
        self.assertIn('required_job_wait', ans['causes'])
        self.assertTrue(self.state.exists())

        self.gh_state.write_text(json.dumps({}))
        still_paused = self.run_fleet('merge-batch')
        self.assertEqual(still_paused.returncode, 1, still_paused.stdout + still_paused.stderr)
        self.assertTrue(json.loads(still_paused.stdout)['paused'])

        resumed = self.run_fleet('resume')
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        res_ans = json.loads(resumed.stdout)
        self.assertTrue(res_ans['resumed'])
        self.assertFalse(res_ans['paused'])
        self.assertFalse(self.state.exists())

        admitted = self.run_fleet('merge-batch')
        self.assertEqual(admitted.returncode, 0, admitted.stdout + admitted.stderr)
        self.assertTrue(json.loads(admitted.stdout)['allowed'])

    def test_missing_input_refuses_without_latching_durable_pause(self):
        missing = str(self.root / 'does-not-exist.json')
        r = self.run_fleet('merge-batch', LAUNCH_FLEET_OVERLOAD_INPUT=missing)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ans = json.loads(r.stdout)
        self.assertEqual(ans['level'], 'unknown')
        self.assertIn('observation_unknown', ans['causes'])
        self.assertFalse(ans['allowed'])
        self.assertIsNone(ans['pause'])
        self.assertFalse(self.state.exists())
        pending = Path(str(self.state) + '.pending')
        self.assertEqual(list(pending.iterdir()) if pending.exists() else [], [])

        for essential in ('completion', 'reconciliation'):
            er = self.run_fleet(essential, LAUNCH_FLEET_OVERLOAD_INPUT=missing)
            self.assertEqual(er.returncode, 0, er.stdout + er.stderr)
            self.assertFalse(self.state.exists())

        good = self.root / 'healthy.json'
        good.write_text(json.dumps(healthy()))
        ok = self.run_fleet('merge-batch', LAUNCH_FLEET_OVERLOAD_INPUT=str(good))
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue(json.loads(ok.stdout)['allowed'])

    def test_fresh_install_failed_gh_refuses_without_latching_durable_pause(self):
        self.gh_state.write_text(json.dumps({'fail': True}))
        r = self.run_fleet('merge-batch')
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        ans = json.loads(r.stdout)
        self.assertEqual(ans['level'], 'unknown')
        self.assertFalse(self.state.exists())

        self.gh_state.write_text(json.dumps({}))
        ok = self.run_fleet('merge-batch')
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.assertTrue(json.loads(ok.stdout)['allowed'])

    def test_resume_is_idempotent_clears_pending_and_refuses_corrupt_or_foreign_state(self):
        r = self.run_fleet('resume')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        ans = json.loads(r.stdout)
        self.assertFalse(ans['paused'])
        self.assertFalse(ans['resumed'])

        bad = self.root / 'alarm.json'
        data = healthy()
        data['budgets']['rest']['remaining'] = 0
        bad.write_text(json.dumps(data))
        with Path(str(self.state) + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.run_fleet('merge-batch', LAUNCH_FLEET_OVERLOAD_INPUT=str(bad))
            busy = self.run_fleet('resume')
            self.assertEqual(busy.returncode, 1, busy.stdout + busy.stderr)
            self.assertFalse(json.loads(busy.stdout)['resumed'])
        pending = Path(str(self.state) + '.pending')
        self.assertEqual(len(list(pending.iterdir())), 1)

        cleared = self.run_fleet('resume')
        self.assertEqual(cleared.returncode, 0, cleared.stdout + cleared.stderr)
        c_ans = json.loads(cleared.stdout)
        self.assertTrue(c_ans['resumed'])
        self.assertEqual(c_ans['cleared_pending'], 1)
        self.assertEqual(list(pending.iterdir()), [])
        self.assertFalse(self.state.exists())

        self.state.write_text('{"paused":true}')
        corrupt = self.run_fleet('resume')
        self.assertEqual(corrupt.returncode, 1, corrupt.stdout + corrupt.stderr)
        self.assertEqual(self.state.read_text(), '{"paused":true}')

        foreign = {
            'repository': 'other-owner/other-repo',
            'paused': True,
            'since': NOW,
            'level': 'alarm',
            'causes': ['rest_below_ten_percent'],
            'observed_at': NOW,
            'evidence_sha256': '0' * 64,
        }
        self.state.write_text(json.dumps(foreign))
        wrong = self.run_fleet('resume')
        self.assertEqual(wrong.returncode, 1, wrong.stdout + wrong.stderr)
        self.assertEqual(json.loads(self.state.read_text())['repository'], 'other-owner/other-repo')


if __name__ == '__main__':
    unittest.main()
