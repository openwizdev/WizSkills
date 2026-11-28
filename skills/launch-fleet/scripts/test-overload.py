#!/usr/bin/env python3
import base64
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
FLEET = HERE / 'fleet.sh'
SUPPLIER = HERE / 'overload-supply.py'
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


def load_supplier():
    spec = importlib.util.spec_from_file_location('overload_supply_under_test', SUPPLIER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_fake_gh(bin_dir, state_file):
    gh = bin_dir / 'gh'
    gh.write_text(
        '#!/usr/bin/env python3\n'
        'import base64, json, os, subprocess, sys, time\n'
        'cfg = json.loads(open(%r).read())\n'
        'if cfg.get("fail"):\n'
        '    sys.stderr.write("gh failed\\n")\n'
        '    sys.exit(1)\n'
        'args = sys.argv[1:]\n'
        'if args[:2] != ["api", "--include"]:\n'
        '    sys.stderr.write("unexpected gh args: " + repr(args) + "\\n")\n'
        '    sys.exit(2)\n'
        'target = args[2]\n'
        'for needle, delay in cfg.get("sleep", {}).items():\n'
        '    if needle in target:\n'
        '        if cfg.get("spawn_child"):\n'
        '            subprocess.Popen(["sh", "-c", "sleep " + str(delay) + "; echo done"])\n'
        '        time.sleep(delay)\n'
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
        '    sys.stdout.flush()\n'
        '    if status >= 400:\n'
        '        sys.exit(1)\n'
        'if target == "rate_limit":\n'
        '    rest = cfg.get("rest", {"remaining": 4500, "limit": 5000, "reset": 1800003600})\n'
        '    gql = cfg.get("graphql", {"remaining": 4500, "limit": 5000, "reset": 1800003600})\n'
        '    emit({"resources": {"core": rest, "graphql": gql}})\n'
        'elif target == "graphql":\n'
        '    gql = cfg.get("graphql", {"remaining": 4500, "limit": 5000, "reset": 1800003600})\n'
        '    gql_status = cfg.get("graphql_status", 200)\n'
        '    if "graphql_body" in cfg:\n'
        '        emit(cfg["graphql_body"], resource="graphql",\n'
        '             remaining=gql["remaining"], limit=gql["limit"], reset=gql["reset"], status=gql_status)\n'
        '    elif cfg.get("graphql_rate_limited"):\n'
        '        emit({"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]},\n'
        '             resource="graphql", remaining=gql["remaining"], limit=gql["limit"], reset=gql["reset"],\n'
        '             status=200)\n'
        '    else:\n'
        '        emit({"data": {"rateLimit": {"remaining": gql["remaining"]}}}, resource="graphql",\n'
        '             remaining=gql["remaining"], limit=gql["limit"], reset=gql["reset"], status=gql_status)\n'
        'elif target == "repos/" + cfg.get("repo", %r):\n'
        '    status = cfg.get("repo_status", 200)\n'
        '    emit({"default_branch": cfg.get("default_branch", "main")}, status=status)\n'
        'elif "/rules/branches/" in target:\n'
        '    status = cfg.get("rules_status", 200)\n'
        '    if "rules_pages" in cfg:\n'
        '        page = int(target.split("page=")[1].split("&")[0]) if "page=" in target else 1\n'
        '        pages = cfg["rules_pages"]\n'
        '        extra = {"Link": f"<https://api.github.com/{target}&page={page + 1}>; rel=\\"next\\""} if page < len(pages) else None\n'
        '        emit(pages[page - 1], status=status, extra=extra)\n'
        '    elif "rules" in cfg:\n'
        '        emit(cfg["rules"], status=status)\n'
        '    else:\n'
        '        emit([{"type": "required_status_checks", "parameters": {"required_status_checks": [{"context": "check"}]}}], status=status)\n'
        'elif target.endswith("/contents/docs/agents/fleet.md"):\n'
        '    if "fleet_md_status" in cfg:\n'
        '        emit({"message": "error"}, status=cfg["fleet_md_status"])\n'
        '    elif "fleet_md" in cfg:\n'
        '        encoded = base64.b64encode(cfg["fleet_md"].encode("utf-8")).decode("ascii")\n'
        '        emit({"type": "file", "encoding": "base64", "content": encoded + "\\n"})\n'
        '    else:\n'
        '        emit({"message": "Not Found"}, status=404)\n'
        'elif "/protection/required_status_checks" in target:\n'
        '    if "classic_status" in cfg:\n'
        '        emit({"message": "error"}, status=cfg["classic_status"])\n'
        '    elif "classic_checks" in cfg:\n'
        '        emit(cfg["classic_checks"])\n'
        '    else:\n'
        '        emit({"message": "Branch not protected"}, status=404)\n'
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
        '    sys.exit(2)\n' % (str(state_file), REPO)
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
                'id': 501, 'run_id': 101, 'run_attempt': 1, 'name': 'check', 'status': 'queued',
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

    def test_required_classification_uses_branch_rules_and_fleet_md_not_workflow_event(self):
        with self.subTest('optional job in pull_request workflow does not pause'):
            self.state.unlink(missing_ok=True)
            self.gh_state.write_text(json.dumps({
                'runs': [{'id': 201, 'run_attempt': 1, 'event': 'pull_request', 'status': 'queued'}],
                'jobs': {'201': [{
                    'id': 601, 'run_id': 201, 'run_attempt': 1, 'name': 'optional-lint', 'status': 'queued',
                    'created_at': '2027-01-15T07:53:20Z', 'started_at': None,
                }]},
            }))
            r = self.run_fleet('merge-batch')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            ans = json.loads(r.stdout)
            self.assertTrue(ans['allowed'])
            self.assertEqual(ans['level'], 'healthy')
            self.assertFalse(self.state.exists())

        with self.subTest('required job in pull_request_target workflow pauses'):
            self.state.unlink(missing_ok=True)
            self.gh_state.write_text(json.dumps({
                'runs': [{'id': 202, 'run_attempt': 1, 'event': 'pull_request_target', 'status': 'queued'}],
                'jobs': {'202': [{
                    'id': 602, 'run_id': 202, 'run_attempt': 1, 'name': 'check', 'status': 'queued',
                    'created_at': '2027-01-15T07:53:20Z', 'started_at': None,
                }]},
            }))
            r = self.run_fleet('merge-batch')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            ans = json.loads(r.stdout)
            self.assertFalse(ans['allowed'])
            self.assertEqual(ans['level'], 'alarm')
            self.assertIn('required_job_wait', ans['causes'])
            self.assertTrue(self.state.exists())

        with self.subTest('fleet.md CI checks classifies jobs when branch rules are empty'):
            fleet_md = '# Fleet settings\n\n## CI checks\n\n| Check | Runs |\n| --- | --- |\n| `build` | main |\n'
            self.state.unlink(missing_ok=True)
            self.gh_state.write_text(json.dumps({
                'rules': [],
                'fleet_md': fleet_md,
                'runs': [{'id': 203, 'run_attempt': 1, 'event': 'pull_request', 'status': 'queued'}],
                'jobs': {'203': [{
                    'id': 603, 'run_id': 203, 'run_attempt': 1, 'name': 'optional-docs', 'status': 'queued',
                    'created_at': '2027-01-15T07:53:20Z', 'started_at': None,
                }]},
            }))
            r = self.run_fleet('merge-batch')
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue(json.loads(r.stdout)['allowed'])

            self.gh_state.write_text(json.dumps({
                'rules': [],
                'fleet_md': fleet_md,
                'runs': [{'id': 204, 'run_attempt': 1, 'event': 'pull_request_target', 'status': 'queued'}],
                'jobs': {'204': [{
                    'id': 604, 'run_id': 204, 'run_attempt': 1, 'name': 'build', 'status': 'queued',
                    'created_at': '2027-01-15T07:53:20Z', 'started_at': None,
                }]},
            }))
            r = self.run_fleet('merge-batch')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            ans = json.loads(r.stdout)
            self.assertEqual(ans['level'], 'alarm')
            self.assertIn('required_job_wait', ans['causes'])

        with self.subTest('classic branch protection fallback classifies jobs when rulesets and fleet.md are absent'):
            self.state.unlink(missing_ok=True)
            self.gh_state.write_text(json.dumps({
                'rules': [],
                'classic_checks': {'checks': [{'context': 'ci'}], 'contexts': ['ci']},
                'runs': [{'id': 205, 'run_attempt': 1, 'event': 'pull_request_target', 'status': 'queued'}],
                'jobs': {'205': [{
                    'id': 605, 'run_id': 205, 'run_attempt': 1, 'name': 'ci', 'status': 'queued',
                    'created_at': '2027-01-15T07:53:20Z', 'started_at': None,
                }]},
            }))
            r = self.run_fleet('merge-batch')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            ans = json.loads(r.stdout)
            self.assertEqual(ans['level'], 'alarm')
            self.assertIn('required_job_wait', ans['causes'])

        with self.subTest('paginated branch rules include checks from later pages'):
            self.state.unlink(missing_ok=True)
            self.gh_state.write_text(json.dumps({
                'rules_pages': [
                    [{'type': 'deletion'}],
                    [{'type': 'required_status_checks',
                      'parameters': {'required_status_checks': [{'context': 'privacy'}]}}],
                ],
                'runs': [{'id': 206, 'run_attempt': 1, 'event': 'pull_request_target', 'status': 'queued'}],
                'jobs': {'206': [{
                    'id': 606, 'run_id': 206, 'run_attempt': 1, 'name': 'privacy', 'status': 'queued',
                    'created_at': '2027-01-15T07:53:20Z', 'started_at': None,
                }]},
            }))
            r = self.run_fleet('merge-batch')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            ans = json.loads(r.stdout)
            self.assertEqual(ans['level'], 'alarm')
            self.assertIn('required_job_wait', ans['causes'])

    def test_unestablished_required_check_classification_marks_observation_incomplete(self):
        cases = (
            ('branch rules error', {'rules_status': 500}),
            ('fleet.md error', {'fleet_md_status': 500}),
            ('classic protection forbidden', {'rules': [], 'classic_status': 403}),
            ('no required checks configured anywhere', {
                'rules': [],
                'runs': [{'id': 301, 'run_attempt': 1, 'event': 'pull_request', 'status': 'queued'}],
                'jobs': {'301': [{
                    'id': 701, 'run_id': 301, 'run_attempt': 1, 'name': 'some-job', 'status': 'queued',
                    'created_at': '2027-01-15T07:59:50Z', 'started_at': None,
                }]},
            }),
            ('job missing name', {
                'runs': [{'id': 302, 'run_attempt': 1, 'event': 'pull_request', 'status': 'queued'}],
                'jobs': {'302': [{
                    'id': 702, 'run_id': 302, 'run_attempt': 1, 'status': 'queued',
                    'created_at': '2027-01-15T07:59:50Z', 'started_at': None,
                }]},
            }),
        )
        for label, cfg in cases:
            with self.subTest(label):
                self.state.unlink(missing_ok=True)
                self.gh_state.write_text(json.dumps(cfg))
                r = self.run_fleet('merge-batch')
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                ans = json.loads(r.stdout)
                self.assertFalse(ans['allowed'])
                self.assertEqual(ans['level'], 'unknown')
                self.assertIn('observation_unknown', ans['causes'])

    def test_graphql_failure_preserves_complete_queue_escalation(self):
        escalating_queue = {
            'runs': [{'id': 401, 'run_attempt': 1, 'event': 'pull_request', 'status': 'queued'}],
            'jobs': {'401': [{
                'id': 801, 'run_id': 401, 'run_attempt': 1, 'name': 'check', 'status': 'queued',
                'created_at': '2027-01-15T07:43:20Z', 'started_at': None,
            }]},
        }
        for label, extra in (
            ('graphql HTTP 500', {'graphql_status': 500}),
            ('graphql error body', {'graphql_body': {'errors': [{'message': 'boom'}]}}),
            ('graphql RATE_LIMITED', {'graphql_rate_limited': True}),
        ):
            with self.subTest(label):
                self.state.unlink(missing_ok=True)
                self.gh_state.write_text(json.dumps(dict(escalating_queue, **extra)))
                r = self.run_fleet('merge-batch')
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                ans = json.loads(r.stdout)
                self.assertFalse(ans['allowed'])
                self.assertEqual(ans['level'], 'escalate')
                self.assertEqual(ans['escalation'], 'due_not_sent')
                self.assertIn('required_job_wait', ans['causes'])
                self.assertIn('observation_unknown', ans['causes'])
                if extra.get('graphql_rate_limited'):
                    self.assertIn('graphql_backoff', ans['causes'])

        with self.subTest('healthy queue with graphql failure still refuses'):
            self.state.unlink(missing_ok=True)
            self.gh_state.write_text(json.dumps({'graphql_status': 500}))
            r = self.run_fleet('merge-batch')
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            ans = json.loads(r.stdout)
            self.assertFalse(ans['allowed'])
            self.assertEqual(ans['level'], 'unknown')
            self.assertEqual(ans['escalation'], 'not_due')
            self.assertIn('observation_unknown', ans['causes'])

    def test_stalled_gh_respects_remaining_observation_deadline(self):
        mod = load_supplier()
        env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ.get('PATH', ''),
                   LAUNCH_FLEET_NOW=str(NOW))

        with self.subTest('stalled first read fails within window and kills child group'):
            self.gh_state.write_text(json.dumps({'sleep': {'rate_limit': 6}, 'spawn_child': True}))
            out = self.root / 'obs-first.json'
            t0 = time.monotonic()
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(mod, 'WINDOW', 1.0):
                code = mod.main(['--repository', REPO, '--output', str(out)])
            elapsed = time.monotonic() - t0
            self.assertEqual(code, 1)
            self.assertLess(elapsed, 4.0)
            self.assertFalse(out.exists())

        with self.subTest('remaining monotonic deadline applies across consecutive calls'):
            self.gh_state.write_text(json.dumps({'sleep': {'rate_limit': 0.6, '/actions/runs?': 6}}))
            out = self.root / 'obs-second.json'
            t0 = time.monotonic()
            with mock.patch.dict(os.environ, env, clear=False), mock.patch.object(mod, 'WINDOW', 1.4):
                code = mod.main(['--repository', REPO, '--output', str(out)])
            elapsed = time.monotonic() - t0
            self.assertEqual(code, 0)
            self.assertLess(elapsed, 4.0)
            obs = json.loads(out.read_text())
            self.assertFalse(obs['complete'])
            self.assertFalse(obs['queue']['complete'])

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
