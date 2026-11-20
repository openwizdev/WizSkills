#!/usr/bin/env python3
"""EB3-C synthetic conformance proofs, not helper invocation or a hand-back hook.

Claims, plausible bugs and the existing coverage gap: the ticket proof plan.
Run without arguments for the suite; --check reads explicit local JSON only.
"""
import copy
from datetime import timedelta
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def openwiz(rel):
    """A file of the OpenWiz checkout at the pinned commit, passed in as OPENWIZ_CHECKOUT (#1487)."""
    root = os.environ.get('OPENWIZ_CHECKOUT')
    path = Path(root) / rel if root else None
    if path is None or not path.is_file():
        print(f'OPENWIZ_CHECKOUT: {path} is missing' if root else
              f'OPENWIZ_CHECKOUT is not set: pass an OpenWiz checkout at the pinned commit (it reads {rel})',
              file=sys.stderr)
        raise SystemExit(2)
    return path


FIX = HERE / 'contract-fixtures'
_spec = importlib.util.spec_from_file_location(
    'eb5_contract', openwiz('tools/collector/experiment_contract.py'))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def validate_check(value):
    """Candidate self-check shape consumed by EB4; never an approved rule."""
    C.fields(value, 'id kind check instruction', 'candidate check')
    C.require(type(value['id']) is str and re.fullmatch(r'[a-z0-9][a-z0-9-]*', value['id']), 'invalid check id')
    C.require(type(value['kind']) is str and value['kind'] in C.J.KINDS, 'invalid kind')
    C.require(value['kind'] != 'unknown', 'unknown cannot be promoted')
    C.choice(value['check'], ('Standards', 'Spec', 'Sweep'), 'check')
    C.text(value['instruction'], 'check instruction')


def validate_request(value):
    C.fields(value, 'schema change binding skills inputs experiment', 'request')
    C.require(value['schema'] == 'openwiz.precheck.request.v1', 'unsupported request schema')
    C.choice(value['change'], ('ordinary', 'skill', 'model', 'brief'), 'change')
    b = value['binding']
    C.fields(b, 'repo ticket pr base head diff_hash', 'binding')
    C.require(type(b['repo']) is str and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', b['repo']), 'invalid repo')
    for key in ('ticket', 'pr'): C.integer(b[key], 1)
    for key in ('base', 'head'): C.hex_value(b[key], 40, key)
    C.hex_value(b['diff_hash'], 64, 'diff hash')
    skills = value['skills']
    C.fields(skills, 'revision build_hash review_hash brief_hash', 'skills')
    C.revision(skills['revision'])
    for key in ('build_hash', 'review_hash', 'brief_hash'): C.hex_value(skills[key], 64, key)
    C.fields(value['inputs'], 'checklist week', 'inputs')
    checklist = value['inputs']['checklist']
    C.fields(checklist, 'path revision hash', 'checklist')
    C.require(checklist['path'] == 'skills/build-ticket/checklist.md', 'invalid checklist path')
    C.hex_value(checklist['revision'], 40, 'checklist revision')
    C.hex_value(checklist['hash'], 64, 'checklist hash')
    week = value['inputs']['week']
    C.fields(week, 'start end history known_kinds checks', 'week')
    C.require(C.time(week['end']) - C.time(week['start']) == timedelta(days=7), 'invalid week interval')
    C.choice(week['history'], ('available', 'unknown'), 'history')
    seen = set()
    for row in C.array(week['known_kinds'], 'known kinds'):
        C.fields(row, 'kind count', 'known kind')
        C.require(type(row['kind']) is str and row['kind'] in C.J.KINDS, 'invalid kind')
        C.require(row['kind'] not in seen, 'duplicate kind'); seen.add(row['kind'])
        C.integer(row['count'], 1)
    ids = set()
    for row in C.array(week['checks'], 'checks'):
        validate_check(row)
        C.require(row['id'] not in ids, 'duplicate check'); ids.add(row['id'])
        C.require(row['kind'] in seen, 'candidate kind absent from weekly inputs')
    if week['history'] == 'unknown':
        C.require(not week['known_kinds'] and not week['checks'], 'unknown history has invented findings')
    e = value['experiment']
    C.require(value['change'] == 'ordinary' or e is not None, 'change requires experiment')
    if e is not None:
        C.fields(e, 'tag experiment_hash arm cf4_refs', 'experiment reference')
        C.require(type(e['tag']) is str and re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,63}', e['tag']), 'invalid experiment tag')
        C.hex_value(e['experiment_hash'], 64, 'experiment hash')
        C.choice(e['arm'], C.ARMS, 'experiment arm')
        if e['cf4_refs'] is not None:
            C.fields(e['cf4_refs'], 'old candidate', 'CF4 references')
            for ref in e['cf4_refs'].values(): C.text(ref, 'CF4 reference')


def validate_result(value):
    C.fields(value, 'schema request_hash status finished_at findings error no_push independent review_round', 'result')
    C.require(value['schema'] == 'openwiz.precheck.result.v1', 'unsupported result schema')
    C.hex_value(value['request_hash'], 64, 'request hash')
    C.choice(value['status'], ('complete', 'failed'), 'result status')
    C.time(value['finished_at'])
    C.require(value['independent'] is False and value['review_round'] is False, 'helper cannot be independent review')
    C.choice(value['no_push'], ('clean', 'hit', 'unavailable'), 'no-push status')
    if value['status'] == 'failed':
        C.require(value['error'] in ('read-failed', 'tool-failed', 'incomplete', 'unavailable'), 'failure needs typed error')
    else:
        C.require(value['error'] is None, 'complete result cannot hide failure')
    ids = set()
    for f in C.array(value['findings'], 'findings'):
        C.fields(f, 'id kind kind_evidence severity check path line summary', 'finding')
        C.require(type(f['id']) is str and re.fullmatch(r'F[1-9][0-9]*', f['id']), 'invalid finding id')
        C.require(f['id'] not in ids, 'duplicate finding'); ids.add(f['id'])
        C.require(type(f['kind']) is str and f['kind'] in C.J.KINDS, 'invalid kind')
        C.choice(f['kind_evidence'], ('marker', 'no marker', 'unrecognised marker'), 'kind evidence')
        C.require(f['kind_evidence'] == 'marker' or f['kind'] == 'unknown', 'kind evidence must retain unknown')
        C.choice(f['severity'], ('high', 'medium', 'low'), 'severity')
        C.choice(f['check'], ('Standards', 'Spec', 'Sweep'), 'check')
        C.require(type(f['path']) is str and all(re.fullmatch(r'[A-Za-z0-9_.-]+', part)
                  and part not in ('.', '..') for part in f['path'].split('/')), 'invalid finding path')
        C.integer(f['line'], 1); C.text(f['summary'], 'finding summary')


def assess(record, current, bundle=None, journey=None, *, at):
    """Conformance only. The caller supplies independently verified current facts."""
    C.fields(record, 'request result', 'record')
    validate_request(record['request']); validate_request(current)
    for value in (record, current):
        C.require(not re.search(r'\b(?:thr_|cr_child_|cr_launch_)[A-Za-z0-9]', json.dumps(value)),
                  'operational identity forbidden')
    result = record['result']
    if result is not None: validate_result(result)
    request = record['request']
    if request != current: return 'blocked-stale'
    week = request['inputs']['week']
    now = C.time(at)
    if not C.time(week['start']) <= now < C.time(week['end']): return 'blocked-stale'
    if result is None: return 'blocked-missing'
    if (result['request_hash'] != C.digest(current) or
        not C.time(week['start']) <= C.time(result['finished_at']) <= now):
        return 'blocked-stale'
    if result['status'] == 'failed': return 'blocked-failed'
    if result['no_push'] != 'clean': return 'blocked-no-push'
    if result['findings']: return 'blocked-findings'
    ref = request['experiment']
    if ref is not None:
        if bundle is None or journey is None: return 'blocked-evidence'
        C.validate(bundle, journey)
        e = bundle['experiment']
        C.require((request['binding']['repo'], ref['tag'], ref['experiment_hash']) ==
                  (e['repo'], e['tag'], bundle['experiment_hash']), 'experiment identity mismatch')
        C.require(request['change'] in ('ordinary', e['change_kind']), 'experiment change mismatch')
        arm = e['arms'][ref['arm']]
        C.require(all(request['skills'][key] == arm[key] for key in request['skills']), 'experiment skill mismatch')
        C.require(any(t['ticket'] == request['binding']['ticket'] and request['binding']['pr'] in t['pull_requests']
                      for t in journey['tickets']), 'experiment ticket/PR join mismatch')
        if ref['cf4_refs'] is None: return 'blocked-cf4'
        try:
            runs = C.cf4_passes(ref['cf4_refs'], bundle['cf4_runs'])
        except ValueError:
            return 'blocked-cf4'
        if any(C.time(run['at']) > C.time(result['finished_at']) for run in runs): return 'blocked-cf4'
    return 'ready'


class Contract(unittest.TestCase):
    def setUp(self):
        self.record = C.read(FIX / 'complete.json')
        self.current = copy.deepcopy(self.record['request'])
        self.bundle = C.read(openwiz('tools/collector/fixtures/bottlenecks-contract/accepted.json'))
        self.journey = C.read(openwiz('tools/collector/fixtures/journey/journeys.json'))

    def check(self):
        return assess(self.record, self.current, self.bundle, self.journey, at='2030-01-03T14:00:00Z')

    def tagged(self):
        self.record['request']['change'] = 'skill'
        self.record['request']['experiment'] = {
            'tag': 'synthetic-skills-1',
            'experiment_hash': 'ef3d5d8fb903d34c132d2123a5ffaeaed3f124dd7f3612de0e6fbfc02a85da61',
            'arm': 'candidate',
            'cf4_refs': {'old': 'old-cf4-1', 'candidate': 'candidate-cf4-1'}}
        self.current = copy.deepcopy(self.record['request'])
        self.record['result']['request_hash'] = C.digest(self.current)

    def test_literal_controls(self):
        for control in C.read(FIX / 'controls.json'):
            with self.subTest(control=control['name']):
                self.setUp()
                target = self.record
                for key in control['path'][:-1]:
                    target = target[key]
                target[control['path'][-1]] = control['value']
                if control['expect'].startswith('invalid:'):
                    with self.assertRaisesRegex(ValueError, control['expect'][8:]):
                        self.check()
                else:
                    self.assertEqual(self.check(), control['expect'])

    def test_complete_and_tagged(self):
        self.assertEqual(self.check(), 'ready')
        self.tagged()
        self.assertEqual(self.check(), 'ready')

    def test_every_current_input_invalidates_the_old_result(self):
        for path, value in [
            (('binding', 'head'), 'f' * 40),
            (('binding', 'base'), 'f' * 40),
            (('binding', 'diff_hash'), 'f' * 64),
            (('binding', 'ticket'), 4103),
            (('binding', 'pr'), 4202),
            (('binding', 'repo'), 'example/other'),
            (('skills', 'revision', 'commit'), 'f' * 40),
            (('skills', 'revision', 'tree'), 'f' * 40),
            (('skills', 'build_hash'), 'f' * 64),
            (('skills', 'review_hash'), 'f' * 64),
            (('skills', 'brief_hash'), 'f' * 64),
            (('inputs', 'checklist', 'hash'), 'f' * 64),
            (('inputs', 'checklist', 'revision'), 'f' * 40),
            (('inputs', 'week', 'history'), 'unknown'),
            (('inputs', 'week', 'known_kinds', 0, 'count'), 4),
            (('inputs', 'week', 'checks', 0, 'instruction'), 'Check the new public boundary.'),
            (('inputs', 'week', 'checks'), []),
        ]:
            with self.subTest(path=path):
                self.setUp()
                target = self.current
                for key in path[:-1]: target = target[key]
                target[path[-1]] = value
                if path[-1] == 'history':
                    self.current['inputs']['week']['known_kinds'] = []
                    self.current['inputs']['week']['checks'] = []
                self.assertEqual(self.check(), 'blocked-stale')

    def test_stale_experiment_reference(self):
        for key, value in [('tag', 'another-tag'), ('experiment_hash', '0'*64),
                           ('arm', 'old'), ('cf4_refs', None),
                           ('cf4_refs', {'old': 'old-cf4-2', 'candidate': 'candidate-cf4-1'})]:
            with self.subTest(key=key):
                self.setUp(); self.tagged()
                self.current['experiment'][key] = value
                self.assertEqual(self.check(), 'blocked-stale')

    def test_experiment_and_cf4_refusals(self):
        for mutation, reason in [
            (lambda: self.record['request']['experiment'].update(tag='other'), 'experiment'),
            (lambda: self.record['request']['experiment'].update(experiment_hash='0'*64), 'experiment'),
            (lambda: self.record['request']['skills']['revision'].update(tree='f'*40), 'skill'),
            (lambda: self.record['request']['skills'].update(build_hash='f'*64), 'skill'),
        ]:
            with self.subTest(reason=reason):
                self.setUp(); self.tagged(); mutation()
                self.current = copy.deepcopy(self.record['request'])
                self.record['result']['request_hash'] = C.digest(self.current)
                with self.assertRaisesRegex(ValueError, reason): self.check()
        for mutation in [
            lambda: self.bundle['cf4_runs'].update(candidate=[]),
            lambda: self.bundle['cf4_runs']['candidate'][0].update(status='fail', passed=59),
            lambda: self.bundle['cf4_runs']['candidate'][0].update(at='2030-01-07T00:00:00Z'),
            lambda: self.record['request']['experiment'].update(cf4_refs=None),
        ]:
            self.setUp(); self.tagged(); mutation()
            self.current = copy.deepcopy(self.record['request'])
            self.record['result']['request_hash'] = C.digest(self.current)
            self.assertEqual(self.check(), 'blocked-cf4')
        self.setUp(); self.tagged()
        self.bundle['experiment']['arms']['candidate']['cf4']['cases_hash'] = 'f'*64
        with self.assertRaisesRegex(ValueError, 'compatible'): self.check()
        self.setUp(); self.tagged()
        self.assertEqual(assess(self.record, self.current, at='2030-01-03T14:00:00Z'), 'blocked-evidence')

    def test_failed_and_findings_examples(self):
        for name, expected in [('failed.json', 'blocked-failed'), ('findings.json', 'blocked-findings')]:
            self.record = C.read(FIX / name)
            self.assertEqual(self.check(), expected)
        finding = self.record['result']['findings'][0]
        finding.update(kind='unknown', kind_evidence='no marker')
        self.assertEqual(self.check(), 'blocked-findings')
        finding.update(kind='missing-proof')
        with self.assertRaisesRegex(ValueError, 'unknown'): self.check()

    def test_time_staleness_at_cli_boundary(self):
        # Claim 1/2: identical hashes cannot make an expired/future report current.
        # Existing tests change bytes; they miss staleness from time alone.
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / 'record.json'; current = Path(tmp) / 'current.json'
            record.write_text(json.dumps(self.record)); current.write_text(json.dumps(self.current))
            for at in ('2030-01-07T08:00:00Z', '2030-01-03T12:59:59Z'):
                run = subprocess.run([sys.executable, '-I', __file__, '--check', str(record),
                    '--current', str(current), '--at', at], capture_output=True, text=True)
                self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
                self.assertTrue(run.stdout.startswith('blocked-stale:'), run.stdout + run.stderr)

    def test_strict_json(self):
        for value in ['{"request":null,"request":null}', '{"x":NaN}']:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'record.json'; path.write_text(value)
                with self.assertRaises(ValueError): C.read(path)

    def test_cli_reads_and_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / 'record.json'; current = Path(tmp) / 'current.json'
            current.write_text(json.dumps(self.current))
            for result, expected in [(self.record['result'], 0), (None, 1)]:
                self.record['result'] = result; record.write_text(json.dumps(self.record))
                before = sorted(Path(tmp).iterdir())
                run = subprocess.run([sys.executable, '-I', __file__, '--check', str(record),
                                      '--current', str(current), '--at', '2030-01-03T14:00:00Z'], capture_output=True, text=True)
                self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
                self.assertEqual(sorted(Path(tmp).iterdir()), before)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--check':
        import argparse
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--check', required=True)
        parser.add_argument('--current', required=True)
        parser.add_argument('--at', required=True)
        parser.add_argument('--experiment')
        parser.add_argument('--journey')
        args = parser.parse_args()
        if bool(args.experiment) != bool(args.journey): parser.error('experiment and journey go together')
        try:
            outcome = assess(C.read(args.check), C.read(args.current),
                             C.read(args.experiment) if args.experiment else None,
                             C.read(args.journey) if args.journey else None, at=args.at)
            print(outcome + ': conformance only; independent review and CI still required')
            sys.exit(0 if outcome == 'ready' else 1)
        except (OSError, ValueError, OverflowError) as error:
            print(str(error), file=sys.stderr); sys.exit(1)
    unittest.main()
