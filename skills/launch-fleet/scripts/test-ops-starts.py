#!/usr/bin/env python3
"""OB5 (#1480) owning proofs: builder and initial-review starts in a finite ops pass.

Synthetic GitHub/CloudRoom facts and virtual time only; no live I/O. Every
start stays disabled under OB-A1, so the effect callback must never be called.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIX = HERE.parent / 'test/ops-starts'
# A synthetic consumer project: ops-starts.py reads its docs/agents/fleet.md from the working directory.
PROJECT = FIX / 'project'


FAKE_GH = """import os, sys
with open(os.environ['FAKE_GH_LOG'], 'a') as log:
    log.write(' '.join(sys.argv[1:]) + '\\n')
sys.stderr.write('gh: refused: this test serves fleet.md only through git\\n')
sys.exit(1)
"""
STALE = 'This checkout is stale: never read it.\n'


def serve(tmp, env, repo, default_branch):
    import shutil
    import subprocess
    origins = tmp / 'origins'
    shutil.rmtree(origins, ignore_errors=True)
    shutil.rmtree(tmp / 'cache', ignore_errors=True)
    work = origins / 'work'
    (work / 'docs/agents').mkdir(parents=True)
    (work / 'README.md').write_text('synthetic\n')
    if default_branch is not None:
        (work / 'docs/agents/fleet.md').write_text(default_branch)
    for args in (('init', '--quiet', '--initial-branch=main'), ('add', '-A'), ('commit', '--quiet', '-m', 'synthetic'),
                 ('clone', '--quiet', '--bare', '.', str(origins / f'{repo}.git'))):
        subprocess.run(['git', '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', *args],
                       cwd=work, env=env, check=True, capture_output=True, timeout=60)


def run_cli(tmp, default_branch, *args, repo='synthetic/ops', checkout=STALE, stdin=None):
    import os
    import subprocess
    tmp = Path(tmp)
    (tmp / 'bin').mkdir(exist_ok=True)
    (tmp / 'gh.py').write_text(FAKE_GH)
    gh = tmp / 'bin/gh'
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{tmp / "gh.py"}" "$@"\n')
    gh.chmod(0o755)
    (tmp / 'docs/agents').mkdir(parents=True, exist_ok=True)
    (tmp / 'docs/agents/fleet.md').write_text(checkout)
    log = tmp / 'gh.log'
    log.unlink(missing_ok=True)
    env = dict(os.environ, PATH=f'{tmp / "bin"}:{os.environ["PATH"]}', FAKE_GH_LOG=str(log),
               XDG_CACHE_HOME=str(tmp / 'cache'), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=str(tmp / 'gitconfig'),
               GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0=f'url.file://{tmp / "origins"}/.insteadOf',
               GIT_CONFIG_VALUE_0='https://github.com/')
    serve(tmp, env, repo, default_branch)
    run = subprocess.run([sys.executable, '-I', str(HERE / 'ops-starts.py'), *args], cwd=tmp, env=env,
                         capture_output=True, text=True, timeout=60, input=stdin)
    return run, (log.read_text().splitlines() if log.exists() else [])


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Starts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load(HERE / 'ops-starts.py', 'ops_starts')
        cls.protocol = load(HERE.parent / 'test/ops-protocol/protocol.py', 'ops_protocol_reference')
        cls.fleet = (PROJECT / 'docs/agents/fleet.md').read_text()
        cls.base = json.loads((FIX / 'world.json').read_text())

    def setUp(self):
        self.world = copy.deepcopy(self.base)
        self.calls = []

    def plan(self, world=None, fleet=None, **extra):
        return self.api.plan(self.world if world is None else world, self.fleet if fleet is None else fleet,
                             lambda *args: self.calls.append(args), **extra)

    def only(self, entries, action):
        found = [e for e in entries if e['action'] == action]
        self.assertEqual(len(found), 1, entries)
        return found[0]

    def record(self, entries):
        # What the finite pass persists on GitHub before ending: each new intent,
        # its admitted claim and the disabled outcome. The next pass reads them back.
        for e in entries:
            if e['decision'] != 'dispatch':
                continue
            intent = e['intent']
            if e['new']:
                self.world['history'].append(intent)
            self.world['history'].append(self.event(intent, 'admission', state='admitted'))
            self.world['history'].append(self.event(intent, 'completion', state='disabled'))

    def event(self, intent, kind, **fields):
        common = {k: intent[k] for k in ('schema', 'repository', 'spec', 'ticket', 'subject', 'operation_key',
                                          'approval', 'rule', 'evidence')}
        n = len(self.world['history']) + 1
        common.update(id=f'{kind}-{intent["id"]}-{n}', kind=kind, created_at=intent['created_at'] + n)
        if kind == 'admission':
            claim = self.api.claim_for(intent, 1, 'primary')
            common.update(claim_id=claim['id'], generation=1, ref=claim['ref'], record_commit='e' * 40)
        elif kind == 'transport':
            common.update(intent_id=intent['id'], generation=1, attempt=1, receipt_digest=None)
        elif kind == 'completion':
            common.update(intent_id=intent['id'], generation=1, superseded_by=None, result_digest=None)
        common.update(fields)
        return self.protocol.read_record(json.dumps(common))

    # P3: an approved, unblocked ticket gets one builder intent and an eligible
    # green head its initial reviewer intent, in one finite pass with no orchestrator.
    def test_finite_pass_records_one_builder_and_one_initial_review(self):
        entries = self.plan()
        builder, review = self.only(entries, 'builder_start'), self.only(entries, 'review_start')
        for e, subject, destination, head in ((builder, {'kind': 'issue', 'number': 9001}, 'builder', None),
                                             (review, {'kind': 'pull_request', 'number': 9101}, 'reviewer', 'c' * 40)):
            with self.subTest(action=e['action']):
                intent = e['intent']
                self.assertEqual(self.protocol.read_record(json.dumps(intent)), intent)
                self.assertEqual((e['decision'], e['new'], intent['subject'], intent['destination'], intent['head'],
                                  intent['prior_verdict'], intent['sequence']),
                                 ('dispatch', True, subject, destination, head, None, 1))
                self.assertEqual(intent['operation_key'], self.protocol.operation_key(intent))
                self.assertEqual(e['claim']['ref'], self.protocol.claim_ref(e['claim']))
                self.assertEqual((e['result']['state'], e['result']['reason'], e['result']['next'],
                                  e['result']['effects']), ('disabled', 'unfenced_effect', 'end', []))
        self.assertEqual(review['intent']['ticket'], 9002)
        self.assertEqual(self.calls, [])

    # P7: configured settings and the other-family reviewer table are the ones used.
    def test_configured_settings_and_reviewer_family_are_effective(self):
        default = dict(provider='claude-code', model='claude-opus-5-5', effort='high')
        codex = dict(provider='codex', model='gpt-6.1-sol', effort='high')
        entries = self.plan()
        self.assertEqual(self.only(entries, 'builder_start')['settings'], default)
        self.assertEqual(self.only(entries, 'review_start')['settings'], codex)
        self.world['builders'][0]['labels'].append('polish')
        self.world['reviews'][0]['builder']['providers'] = ['codex']
        entries = self.plan()
        self.assertEqual(self.only(entries, 'builder_start')['settings'], codex)
        self.assertEqual(self.only(entries, 'review_start')['settings'], default)
        # An edited settings file is read on the next pass and changes the operation's evidence.
        edited = self.fleet.replace('| Model | Opus 5.5 | `--model claude-opus-5-5` |',
                                    '| Model | Opus 9.9 | `--model claude-opus-9-9` |', 1)
        self.world = copy.deepcopy(self.base)
        before, after = self.only(self.plan(), 'builder_start'), self.only(self.plan(fleet=edited), 'builder_start')
        self.assertEqual(after['settings']['model'], 'claude-opus-9-9')
        self.assertNotEqual(before['intent']['evidence'], after['intent']['evidence'])
        for broken in (self.fleet.replace('## Reviewer for GPT-built', '## Reviewers for GPT-built'),
                       self.fleet.replace('| Effort | High | `--reasoning-level high` |', '| Effort | High | |', 1)):
            with self.subTest(broken=True), self.assertRaises(ValueError):
                self.plan(fleet=broken)

    # P7: every stale or ungated builder start is refused before any intent.
    def test_builder_refusals_start_nothing(self):
        cases = {
            'stale approval': ('fingerprint_now', 'f' * 64),
            'approval table unread': ('table_complete', False),
            'not approved ready': ('approved_ready', False),
            'held label': ('labels', ['ready-for-agent', 'held']),
            'unready': ('labels', ['needs-triage']),
            'question open': ('labels', ['ready-for-agent', 'needs-info']),
            'hold record': ('holds', [9010]),
            'other gate': ('gates', ['live gate']),
            'blocker unverified': ('blockers', [{'number': 8999, 'merged': False}]),
            'blockers unread': ('blockers_complete', False),
            'closed': ('open', False),
            'live builder': ('live_builders', 1),
            'builder unknown': ('live_builders', None),
            'unsettled claim': ('start_claims', [9011]),
            'open pull request': ('open_prs', [9102]),
            'capacity': ('admission', 'capacity'),
            'permission': ('admission', 'permission'),
            'admission unknown': ('admission', 'unknown'),
            'incomplete read': ('complete', False),
        }
        for name, (field, value) in cases.items():
            with self.subTest(name):
                self.world = copy.deepcopy(self.base)
                self.world['builders'][0][field] = value
                e = self.only(self.plan(), 'builder_start')
                self.assertEqual((e['decision'], e['intent'], e['result']), ('refused', None, None))
                self.assertTrue(e['reason'])
        self.assertEqual(self.calls, [])

    # P7: a stale head, red CI, unknown or conflicting family, or an unavailable
    # selected reviewer is an exception, never a swapped or stale review.
    def test_review_refusals_and_family_exceptions_start_nothing(self):
        cases = {
            'stale head': ('head_now', 'd' * 40),
            'ci on another head': ('ci', {'head': 'd' * 40, 'state': 'success', 'required_complete': True}),
            'ci red': ('ci', {'head': 'c' * 40, 'state': 'failure', 'required_complete': True}),
            'ci pending': ('ci', {'head': 'c' * 40, 'state': 'pending', 'required_complete': True}),
            'required checks unread': ('ci', {'head': 'c' * 40, 'state': 'success', 'required_complete': False}),
            'draft': ('draft', True),
            'closed': ('open', False),
            'stale approval': ('fingerprint_now', 'f' * 64),
            'held ticket': ('labels', ['held']),
            'hold record': ('holds', [9010]),
            'family unknown': ('builder', {'record_branch': 'room/9002-synthetic', 'providers': []}),
            'family conflicting': ('builder', {'record_branch': 'room/9002-synthetic',
                                               'providers': ['claude-code', 'codex']}),
            'family other provider': ('builder', {'record_branch': 'room/9002-synthetic', 'providers': ['other']}),
            'start record on another branch': ('builder', {'record_branch': 'room/9002-other',
                                                           'providers': ['claude-code']}),
            'no start record': ('builder', {'record_branch': None, 'providers': ['claude-code']}),
            'reviewer unavailable': ('reviewer_available', False),
            # R2: a reviewer started on this PR and not given up re-checks (OB6); no new start.
            'retained reviewer at this head': ('spans', [{'head': 'c' * 40, 'given_up': False}]),
            'retained reviewer at an earlier head': ('spans', [{'head': 'd' * 40, 'given_up': False}]),
            'one of two reviewers retained': ('spans', [{'head': 'd' * 40, 'given_up': True},
                                                        {'head': 'c' * 40, 'given_up': False}]),
            # R3: fleet-tick's first_review facts, each source-bound.
            'closes another ticket': ('closes', [9003]),
            'closes no ticket': ('closes', []),
            'closes two tickets': ('closes', [9002, 9003]),
            'not the default branch': ('base', 'release-1'),
            'head is not a hand-back': ('subject', '#9002: wip: synthetic'),
            'green only at the end of a word': ('subject', '#9002: evergreen synthetic'),
            'green only at the start of a word': ('subject', '#9002: GREENish synthetic'),
            'has a verdict': ('verdict', 'VERDICT: CHANGES at ' + 'c' * 40),
            'capacity': ('admission', 'capacity'),
            'incomplete read': ('complete', False),
        }
        for name, (field, value) in cases.items():
            with self.subTest(name):
                self.world = copy.deepcopy(self.base)
                self.world['reviews'][0][field] = value
                e = self.only(self.plan(), 'review_start')
                self.assertEqual((e['decision'], e['intent'], e['result'], e['settings']),
                                 ('refused', None, None, None))
                self.assertTrue(e['reason'])
        self.assertEqual(self.calls, [])

    def test_hand_back_accepts_green_as_a_whole_word_in_any_case(self):
        for word in ('green', 'Green', 'GREEN'):
            with self.subTest(word=word):
                self.world['reviews'][0]['subject'] = f'#9002: {word}: synthetic'
                entry = self.only(self.plan(), 'review_start')
                self.assertEqual(entry['decision'], 'dispatch', entry['reason'])
                self.assertEqual(entry['result']['state'], 'disabled')
        self.assertEqual(self.calls, [])

    # A reader takes only the exact shape: a missing or extra fact refuses that start alone.
    def test_malformed_candidates_are_refused_alone(self):
        for name, edit in (('missing', lambda c: c.pop('holds')), ('extra', lambda c: c.update(enabled=True)),
                           ('nested extra', lambda c: c['evidence'].update(complete=True)),
                           ('ticket as text', lambda c: c.update(ticket='9001'))):
            with self.subTest(name):
                self.world = copy.deepcopy(self.base)
                edit(self.world['builders'][0])
                edit(self.world['reviews'][0])
                broken = copy.deepcopy(self.world['builders'][0])
                self.world['builders'] = [broken, copy.deepcopy(self.base['builders'][0])]
                entries = self.plan()
                self.assertEqual([(e['action'], e['decision']) for e in entries],
                                 [('builder_start', 'refused'), ('builder_start', 'dispatch'),
                                  ('review_start', 'refused')])
                self.assertEqual(entries[0]['reason'], 'incomplete or malformed source')
        self.assertEqual(self.calls, [])

    # R6: a candidate that is not even an object, or whose evidence fails the
    # record schema, is refused alone; the unrelated eligible review still dispatches.
    def test_unreadable_candidates_do_not_abort_the_pass(self):
        bad_class = copy.deepcopy(self.base['builders'][0])
        bad_class['evidence']['evidence_class'] = 'unknown'
        for name, broken in (('null', None), ('list', []), ('bad evidence class', bad_class)):
            with self.subTest(name):
                self.world = copy.deepcopy(self.base)
                self.world['builders'] = [broken, copy.deepcopy(self.base['builders'][0])]
                entries = self.plan()
                self.assertEqual([(e['action'], e['decision']) for e in entries],
                                 [('builder_start', 'refused'), ('builder_start', 'dispatch'),
                                  ('review_start', 'dispatch')])
        self.assertEqual(self.calls, [])

    def test_malformed_current_evidence_refuses_reuse_of_a_persisted_intent(self):
        self.record([self.only(self.plan(), 'builder_start')])
        valid = self.world['builders'][0]['evidence'].copy()
        for field, value in (('evidence_class', 'unknown'), ('source', ''), ('source', []), ('source', 'x' * 513)):
            with self.subTest(field=field, value=value):
                self.world['builders'][0]['evidence'] = dict(valid, **{field: value})
                entries = self.plan()
                builder = self.only(entries, 'builder_start')
                self.assertEqual((builder['decision'], builder['intent'], builder['new'], builder['result']),
                                 ('refused', None, False, None))
                self.assertEqual(builder['reason'], 'incomplete or malformed source')
                self.assertEqual(self.only(entries, 'review_start')['result']['state'], 'disabled')
        self.world['builders'][0]['evidence'] = valid
        builder = self.only(self.plan(), 'builder_start')
        self.assertEqual((builder['decision'], builder['new']), ('dispatch', False))
        self.assertEqual(self.calls, [])

    # P7: a settings table that would give a Claude-built PR a Claude reviewer is refused.
    def test_same_family_reviewer_table_is_refused(self):
        same = self.fleet.replace('## Reviewer for Claude-built\n\n| Setting | Value | `room-cli thread spawn` flag |\n'
                                  '| --- | --- | --- |\n| Harness | Codex | `--provider codex` |',
                                  '## Reviewer for Claude-built\n\n| Setting | Value | `room-cli thread spawn` flag |\n'
                                  '| --- | --- | --- |\n| Harness | Claude Code | `--provider claude-code` |', 1)
        self.assertNotEqual(same, self.fleet)
        # R4: each reviewer table must name exactly the other family; anything else refuses the pass.
        other = self.fleet.replace('## Reviewer for Claude-built\n\n| Setting | Value | `room-cli thread spawn` flag |\n'
                                   '| --- | --- | --- |\n| Harness | Codex | `--provider codex` |',
                                   '## Reviewer for Claude-built\n\n| Setting | Value | `room-cli thread spawn` flag |\n'
                                   '| --- | --- | --- |\n| Harness | Other | `--provider other` |', 1)
        gpt = self.fleet.replace('## Reviewer for GPT-built\n\n| Setting | Value | `room-cli thread spawn` flag |\n'
                                 '| --- | --- | --- |\n| Harness | Claude Code | `--provider claude-code` |',
                                 '## Reviewer for GPT-built\n\n| Setting | Value | `room-cli thread spawn` flag |\n'
                                 '| --- | --- | --- |\n| Harness | Codex | `--provider codex` |', 1)
        builder = self.fleet.replace('| Harness | Claude Code | `--provider claude-code` |',
                                     '| Harness | Other | `--provider other` |', 1)
        for name, text in (('same family', same), ('unknown reviewer provider', other),
                           ('GPT-built reviewed by GPT', gpt), ('unknown builder provider', builder)):
            with self.subTest(name):
                self.assertNotEqual(text, self.fleet)
                with self.assertRaises(ValueError):
                    self.plan(fleet=text)
        self.assertEqual(self.calls, [])

    # R2: a fresh review is allowed only after every earlier reviewer was given up,
    # and it is a new assignment, never the retained one's.
    def test_fresh_review_after_every_reviewer_given_up(self):
        first = self.only(self.plan(), 'review_start')
        self.world['reviews'][0]['spans'] = [{'head': 'd' * 40, 'given_up': True},
                                             {'head': 'c' * 40, 'given_up': True}]
        fresh = self.only(self.plan(), 'review_start')
        self.assertEqual((fresh['decision'], fresh['result']['state']), ('dispatch', 'disabled'))
        self.assertNotEqual(fresh['intent']['assignment'], first['intent']['assignment'])
        self.assertNotEqual(fresh['intent']['operation_key'], first['intent']['operation_key'])

    def test_fresh_review_can_follow_a_verdict_on_an_older_head(self):
        review = self.world['reviews'][0]
        review['spans'] = [{'head': 'd' * 40, 'given_up': True}]
        for verdict in ('APPROVE', 'CHANGES'):
            with self.subTest(verdict=verdict):
                review['verdict'] = f'VERDICT: {verdict} at ' + 'd' * 40
                entry = self.only(self.plan(), 'review_start')
                self.assertEqual(entry['decision'], 'dispatch', entry['reason'])
                self.assertEqual(entry['result']['state'], 'disabled')
        self.assertEqual(self.calls, [])

    def test_fresh_review_refuses_current_or_malformed_verdicts_and_retained_reviewers(self):
        review = self.world['reviews'][0]
        review['spans'] = [{'head': 'd' * 40, 'given_up': True}]
        for verdict in ('VERDICT: APPROVE at ' + 'c' * 40,
                        'VERDICT: CHANGES at ' + 'c' * 40,
                        'VERDICT: APPROVE at ' + 'd' * 39,
                        'VERDICT: APPROVE at ' + 'd' * 40 + '\nextra',
                        42):
            with self.subTest(verdict=verdict):
                review['verdict'] = verdict
                entry = self.only(self.plan(), 'review_start')
                self.assertEqual((entry['decision'], entry['intent']), ('refused', None))
        review['verdict'] = 'VERDICT: CHANGES at ' + 'd' * 40
        review['spans'][0]['given_up'] = False
        entry = self.only(self.plan(), 'review_start')
        self.assertEqual((entry['decision'], entry['reason']),
                         ('refused', 'a retained reviewer re-checks (OB6), no new start'))
        self.assertEqual(self.calls, [])

    # R1: a re-approval allocates sequences afresh; intent ids stay unique and the
    # new start is not refused as a conflicting identity.
    def test_reapproval_keeps_intent_ids_unique(self):
        self.record(self.plan())
        old = [r for r in self.world['history'] if r['kind'] == 'intent']
        for candidate in self.world['builders'] + self.world['reviews']:
            candidate['approval'] = dict(candidate['approval'], revision=9, fingerprint='9' * 64)
            candidate['fingerprint_now'] = '9' * 64
        entries = self.plan()
        for e in entries:
            with self.subTest(e['action']):
                self.assertEqual((e['decision'], e['new'], e['intent']['sequence']), ('dispatch', True, 1))
                self.assertNotIn(e['intent']['id'], [r['id'] for r in old])
                self.assertEqual((e['result']['state'], e['result']['reason']), ('disabled', 'unfenced_effect'))
                self.assertLessEqual(len(e['intent']['id']), 80)

    # R7: a durable intent is reused only while its bound settings and rule still hold.
    def test_changed_settings_or_rule_after_persistence_are_not_reused(self):
        edited = self.fleet.replace('| Model | Opus 5.5 | `--model claude-opus-5-5` |',
                                    '| Model | Opus 9.9 | `--model claude-opus-9-9` |', 1)
        first = self.plan()
        self.record(first)
        old = self.only(first, 'builder_start')['intent']
        e = self.only(self.plan(fleet=edited), 'builder_start')
        self.assertEqual((e['decision'], e['new'], e['intent']['sequence'], e['settings']['model']),
                         ('dispatch', True, 2, 'claude-opus-9-9'))
        self.assertNotEqual(e['intent']['operation_key'], old['operation_key'])
        self.assertEqual(e['intent']['evidence'][0]['digest'],
                         self.api.binding_digest(e['intent'], e['settings'], self.world['rule']))
        self.assertEqual(e['result']['state'], 'disabled')
        # Unchanged settings still reuse the settled intent.
        self.assertEqual(self.only(self.plan(), 'builder_start')['new'], False)
        # A changed rule is a changed binding too.
        self.world['rule'] = dict(self.world['rule'], revision='e' * 64)
        e = self.only(self.plan(), 'builder_start')
        self.assertEqual((e['new'], e['intent']['rule']), (True, self.world['rule']))
        # An earlier intent with no settled outcome is never bypassed by a changed binding.
        self.world = copy.deepcopy(self.base)
        self.world['history'] = [old]
        e = self.only(self.plan(fleet=edited), 'builder_start')
        self.assertEqual((e['decision'], e['intent']), ('refused', None))
        self.assertEqual(self.calls, [])

    # P3: duplicate and overlapping checks reconcile to one operation.
    def test_duplicate_and_overlapping_checks_record_one_start(self):
        first = self.plan()
        again = self.plan()
        for action in ('builder_start', 'review_start'):
            self.assertEqual(self.only(first, action)['intent'], self.only(again, action)['intent'])
        # The project and spec ticks pass the same candidates in one view: one key, one result.
        self.world['builders'].append(copy.deepcopy(self.world['builders'][0]))
        both = [e for e in self.plan() if e['action'] == 'builder_start']
        self.assertEqual([e['result']['state'] for e in both], ['disabled', 'duplicate'])
        self.assertEqual(both[0]['intent']['operation_key'], both[1]['intent']['operation_key'])
        # After the first pass's records are read back, a later pass records no second intent.
        self.world = copy.deepcopy(self.base)
        self.record(self.plan())
        later = self.plan()
        for action in ('builder_start', 'review_start'):
            e = self.only(later, action)
            self.assertEqual((e['decision'], e['new'], e['intent']['sequence']), ('dispatch', False, 1))
        self.assertEqual(sum(r['kind'] == 'intent' for r in self.world['history']), 2)
        self.assertEqual(self.calls, [])

    # P3: a lost spawn reply, or a failure between the start and its record, is
    # reconciled, never retried blindly with a new key.
    def test_lost_reply_and_unrecorded_outcome_reconcile(self):
        first = self.plan()
        builder = self.only(first, 'builder_start')['intent']
        histories = {
            'transport uncertain': [builder, self.event(builder, 'admission', state='admitted'),
                                    self.event(builder, 'transport', state='uncertain')],
            'transport accepted, no outcome': [builder, self.event(builder, 'admission', state='admitted'),
                                               self.event(builder, 'transport', state='accepted')],
            'admitted, then nothing recorded': [builder, self.event(builder, 'admission', state='admitted')],
            'claim reply unknown': [builder, self.event(builder, 'admission', state='uncertain')],
            'completion uncertain': [builder, self.event(builder, 'admission', state='admitted'),
                                     self.event(builder, 'completion', state='uncertain')],
        }
        for name, history in histories.items():
            with self.subTest(name):
                self.world = copy.deepcopy(self.base)
                self.world['history'] = history
                entries = self.plan()
                e = self.only(entries, 'builder_start')
                self.assertEqual((e['new'], e['intent']['operation_key'], e['result']['state'], e['result']['reason']),
                                 (False, builder['operation_key'], 'reconcile', 'uncertain_outcome'))
                # Unrelated work on another ticket is not stalled by it.
                self.assertEqual(self.only(entries, 'review_start')['result']['state'], 'disabled')
        # An uncertain start under an older approval still blocks a new key for the ticket.
        self.world = copy.deepcopy(self.base)
        old = dict(builder, approval=dict(builder['approval'], revision=7, fingerprint='9' * 64), id='old-start')
        old['operation_key'] = self.protocol.operation_key(old)
        self.world['history'] = [old, self.event(old, 'transport', state='uncertain')]
        e = self.only(self.plan(), 'builder_start')
        self.assertEqual((e['result']['state'], e['result']['reason']), ('reconcile', 'uncertain_outcome'))
        self.assertEqual(self.calls, [])

    # P8: a slow or refused start does not stall unrelated eligible work; green CI
    # creates reviewer work and no builder wake.
    def test_refused_start_does_not_stall_unrelated_work_and_green_ci_wakes_no_builder(self):
        refused = copy.deepcopy(self.world['builders'][0])
        refused.update(ticket=9003, admission='capacity')
        slow = copy.deepcopy(self.world['reviews'][0])
        slow.update(pr=9103, ticket=9004, closes=[9004], reviewer_available=False)
        self.world['builders'].insert(0, refused)
        self.world['reviews'].insert(0, slow)
        entries = self.plan()
        decisions = {(e['action'], e['subject']['number']): e['decision'] for e in entries}
        self.assertEqual(decisions, {('builder_start', 9003): 'refused', ('builder_start', 9001): 'dispatch',
                                     ('review_start', 9103): 'refused', ('review_start', 9101): 'dispatch'})
        self.world['builders'] = []
        entries = self.plan()
        self.assertEqual(entries[0]['reason'], 'selected reviewer unavailable: waits, never swapped')
        self.assertEqual([(e['action'], e['decision'], e['intent'] and e['intent']['destination']) for e in entries],
                         [('review_start', 'refused', None), ('review_start', 'dispatch', 'reviewer')])

    # P5 (start portion): an executor whose generation was taken over is refused.
    def test_stale_generation_is_refused(self):
        taken = self.protocol.read_record(json.dumps(dict(
            self.world['generations'][0], id='generation-2', generation=2, previous_generation=1, owner='standby',
            ref='refs/heads/openwiz-ops/v1/s-9000/generations/g-2')))
        self.world['generations'].append(taken)
        entries = self.plan()
        self.assertEqual([e['action'] for e in entries], ['builder_start', 'review_start'])
        for e in entries:
            self.assertEqual((e['result']['state'], e['result']['reason']), ('refused', 'stale_claim'))
        self.assertEqual(self.calls, [])

    # TL3: an evidenced missed start goal reuses the same start path: one intent,
    # the miss recorded beside it; repeated overdue reads start nothing more.
    def test_missed_start_goals_reuse_the_start_path(self):
        bench = json.loads((FIX / 'bench-miss.json').read_text())
        limits = load(HERE / 'carried/limits.py', 'factory_limits').read(
            HERE / 'carried/limits.conf')
        plain = self.plan()
        missed = self.plan(bench=bench, limits=limits)
        for action, key in (('builder_start', 'builder_start:t9001'),
                            ('review_start', 'reviewer_start:p9101:' + 'c' * 40 + ':2030-03-01T10:00:00Z')):
            with self.subTest(action):
                p, m = self.only(plain, action), self.only(missed, action)
                self.assertEqual((p['missed'], m['missed']), (None, key))
                self.assertEqual(p['intent'], m['intent'])
        self.record(missed)
        again = self.plan(bench=bench, limits=limits)
        self.assertEqual([e['new'] for e in again], [False, False])
        self.assertEqual(sum(r['kind'] == 'intent' for r in self.world['history']), 2)
        # A miss grants nothing: an ineligible candidate stays refused.
        self.world = copy.deepcopy(self.base)
        self.world['builders'][0]['labels'] = ['ready-for-agent', 'held']
        e = self.only(self.plan(bench=bench, limits=limits), 'builder_start')
        self.assertEqual((e['decision'], e['missed'], e['intent']), ('refused', 'builder_start:t9001', None))
        # A miss whose wait already ended, or another head's miss, is not this start's.
        ended = copy.deepcopy(bench)
        for wait in ended['waits']:
            wait['end'] = 's9'
        self.world = copy.deepcopy(self.base)
        self.assertEqual([e['missed'] for e in self.plan(bench=ended, limits=limits)], [None, None])
        # Settings that differ from the shared reader's, or a bench claiming authority, are refused.
        for bad in (dict(bench, settings=dict(bench['settings'], minutes=dict(limits['minutes'], reviewer_start=6))),
                    dict(bench, authority='start'), dict(bench, schema='closedwiz.journey.stage-bench.v2')):
            with self.subTest(bad=True), self.assertRaises(ValueError):
                self.plan(bench=bad, limits=limits)
        with self.assertRaises(ValueError):
            self.plan(bench=bench)

    # Measurement: eligible green-to-dispatch delay with its denominators; gated
    # intervals never count as recoverable time. Uses TL2's own sanitized output.
    def test_report_green_to_dispatch_delay_with_denominators(self):
        bench = json.loads((HERE.parent / 'test/ops-inbox/stage-waits-bench.json').read_text())
        report = self.api.report(bench)
        self.assertEqual(report['reviewer_start'], {
            'limit_minutes': 5, 'intervals': 5,
            'results': {'missed': 1, 'not missed': 1, 'pending': 0, 'unknown': 1, 'gated': 1, 'stale': 1},
            'measured_ended': 2, 'p50_minutes': 4.0, 'p90_minutes': 6.0,
            'excess_minutes': 1.0, 'excluded': {'gated': 1, 'stale': 1, 'unknown': 1}})
        self.assertEqual(report['builder_start']['measured_ended'], 1)
        self.assertEqual(report['authority'], 'none')
        self.assertEqual(report['provenance']['initial_review_handoffs'], 10)
        self.assertEqual(report['provenance']['green_to_dispatch_pr_hours'], 2.5)
        self.assertIn('synthetic', report['provenance']['source'])
        with self.assertRaises(ValueError):
            self.api.report(dict(bench, authority='start'))
        # R5: an open miss has no dispatch time yet: it stays in the denominators only.
        open_misses = json.loads((FIX / 'bench-miss.json').read_text())
        report = self.api.report(open_misses)
        for stage in ('builder_start', 'reviewer_start'):
            self.assertEqual((report[stage]['intervals'], report[stage]['results']['missed'],
                              report[stage]['measured_ended'], report[stage]['p50_minutes'],
                              report[stage]['excess_minutes']), (1, 1, 0, None, 0.0))
        # A mixed cohort: the ended miss counts, the open one does not.
        mixed = copy.deepcopy(open_misses)
        ended = dict(mixed['waits'][1], key=mixed['waits'][1]['key'] + 'x', end='s3', wait_minutes=8.0,
                     wait_range_minutes=[8.0, 8.0])
        mixed['waits'].append(ended)
        row = next(r for r in mixed['stages'] if r['stage'] == 'reviewer_start')
        row['intervals'], row['results']['missed'] = 2, 2
        self.assertEqual(self.api.report(mixed)['reviewer_start']['measured_ended'], 1)
        self.assertEqual(self.api.report(mixed)['reviewer_start']['excess_minutes'], 3.0)

    def test_cli_pass_prints_records_and_ends(self):
        with tempfile.TemporaryDirectory() as tmp:
            import subprocess
            path = Path(tmp) / 'world.json'
            path.write_text(json.dumps(self.world))
            run, _ = run_cli(tmp, self.fleet, 'pass', str(path))
            self.assertEqual(run.returncode, 0, run.stderr)
            lines = [json.loads(line) for line in run.stdout.splitlines()]
            self.assertEqual([(e['action'], e['result']['state']) for e in lines],
                             [('builder_start', 'disabled'), ('review_start', 'disabled')])
            path.write_text('{"broken": ')
            run, _ = run_cli(tmp, self.fleet, 'pass', str(path))
            self.assertEqual((run.returncode, run.stdout), (2, ''))


MODELS = FIX / 'models'
STARTS = ('fleet_thread', 'builder', 'small_builder', 'review_of_claude_built', 'review_of_gpt_built',
          'fix_round_for_claude_builder', 'fix_round_for_gpt_builder')


def spawn(choice):
    return None if choice is None else (f'--provider {choice["provider"]} --model {choice["model"]} '
                                        f'--reasoning-level {choice["effort"]}')


def contract_starts(show):
    return dict(fleet_thread=spawn(show['roles']['orchestrator']['choice']),
                builder=spawn(show['roles']['builder']['choice']),
                small_builder=spawn(show['roles']['small_builder']['choice']),
                review_of_claude_built=spawn(show['reviews']['claude']['choice']),
                review_of_gpt_built=spawn(show['reviews']['gpt']['choice']),
                fix_round_for_claude_builder=spawn(show['fixers']['claude']['choice']),
                fix_round_for_gpt_builder=spawn(show['fixers']['gpt']['choice']))


class ModelsTable(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.api = load(HERE / 'ops-starts.py', 'ops_starts_models')
        cls.base = json.loads((FIX / 'world.json').read_text())
        cls.one = (MODELS / 'one-table/fleet.md').read_text()

    def flags(self, fleet, *start):
        with tempfile.TemporaryDirectory() as tmp:
            return run_cli(tmp, fleet, 'flags', '--repo', 'synthetic/ops', *start)[0]

    def starts(self, fleet):
        run = self.flags(fleet)
        return (run.returncode, json.loads(run.stdout) if run.returncode == 0 else run.stderr.strip())

    def pass_settings(self, fleet, small=False, built_by='claude-code'):
        world = copy.deepcopy(self.base)
        if small:
            world['builders'][0]['labels'].append('polish')
        world['reviews'][0]['builder']['providers'] = [built_by]
        try:
            entries = self.api.plan(world, fleet, lambda *_: self.fail('a start was attempted'))
        except ValueError as error:
            return 'refused: ' + str(error)
        return {e['action']: e['settings'] if e['decision'] == 'dispatch' else 'refused: ' + e['reason']
                for e in entries}

    def test_every_start_spawns_what_the_contract_fixtures_say(self):
        for case in sorted(p.name for p in MODELS.iterdir()):
            with self.subTest(case):
                fleet = MODELS / case / ('fleet.md' if (MODELS / case / 'fleet.md').exists() else 'after.md')
                show = json.loads((MODELS / case / 'show.json').read_text())
                self.assertEqual(self.starts(fleet.read_text()), (0, contract_starts(show)))

    def test_one_table_and_five_tables_start_alike(self):
        five = (MODELS / 'five-tables/fleet.md').read_text()
        self.assertEqual(self.starts(self.one), self.starts(five))
        opus = dict(provider='claude-code', model='claude-opus-5-5', effort='medium')
        sol = dict(provider='codex', model='gpt-6.2-sol', effort='medium')
        for small in (False, True):
            for built_by, reviewer in (('claude-code', sol), ('codex', opus)):
                with self.subTest(small=small, built_by=built_by):
                    want = {'builder_start': opus, 'review_start': reviewer}
                    self.assertEqual(self.pass_settings(self.one, small, built_by), want)
                    self.assertEqual(self.pass_settings(five, small, built_by), want)

    def test_a_changed_table_reaches_the_next_start_only(self):
        changed = self.one.replace(
            '| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 '
            '--reasoning-level medium` |',
            '| Builder | Claude Code | Sonnet 5.5 | Low | `--provider claude-code --model claude-sonnet-5-5 '
            '--reasoning-level low` |', 1)
        self.assertNotEqual(changed, self.one)
        before, after = self.flags(self.one, 'builder'), self.flags(changed, 'builder')
        self.assertEqual((before.returncode, before.stdout),
                         (0, '--provider claude-code --model claude-opus-5-5 --reasoning-level medium\n'))
        self.assertEqual((after.returncode, after.stdout),
                         (0, '--provider claude-code --model claude-sonnet-5-5 --reasoning-level low\n'))
        sonnet = dict(provider='claude-code', model='claude-sonnet-5-5', effort='low')
        self.assertEqual(self.pass_settings(changed)['builder_start'], sonnet)
        self.assertEqual(self.pass_settings(changed, small=True)['builder_start'], sonnet)
        world = copy.deepcopy(self.base)
        world['builders'][0]['live_builders'] = 1
        entry = self.api.plan(world, changed, lambda *_: self.fail('a start was attempted'))[0]
        self.assertEqual((entry['decision'], entry['settings']), ('refused', None))

    def test_a_fleet_thread_starts_on_the_orchestrator_row(self):
        orchestrator = self.one.replace(
            '| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 '
            '--reasoning-level medium` |',
            '| Orchestrator | Codex | Sol 6.2 | High | `--provider codex --model gpt-6.2-sol '
            '--reasoning-level high` |', 1)
        self.assertNotEqual(orchestrator, self.one)
        for fleet, want in ((orchestrator, '--provider codex --model gpt-6.2-sol --reasoning-level high\n'),
                            (self.one, '--provider claude-code --model claude-opus-5-5 --reasoning-level medium\n')):
            run = self.flags(fleet, 'fleet_thread')
            self.assertEqual((run.returncode, run.stdout), (0, want))
        self.assertEqual(self.flags(orchestrator, 'builder').stdout,
                         '--provider claude-code --model claude-opus-5-5 --reasoning-level medium\n')
        older = self.flags((PROJECT / 'docs/agents/fleet.md').read_text(), 'fleet_thread')
        self.assertEqual((older.returncode, older.stdout),
                         (0, '--provider claude-code --model claude-opus-5-5 --reasoning-level high\n'))

    def test_a_same_family_reviewer_falls_back_to_the_builder_then_waits(self):
        sol = dict(provider='codex', model='gpt-6.2-sol', effort='medium')
        opus_high = dict(provider='claude-code', model='claude-opus-5-5', effort='high')
        fallback = (self.one.replace('| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code '
                                     '--model claude-opus-5-5 --reasoning-level medium` |',
                                     '| Builder | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol '
                                     '--reasoning-level medium` |', 1)
                    .replace('| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol '
                             '--reasoning-level medium` |',
                             '| Reviewer | Claude Code | Opus 5.5 | High | `--provider claude-code '
                             '--model claude-opus-5-5 --reasoning-level high` |', 1))
        self.assertEqual(self.pass_settings(fallback, built_by='claude-code'),
                         {'builder_start': sol, 'review_start': sol})
        self.assertEqual(self.pass_settings(fallback, built_by='codex'),
                         {'builder_start': sol, 'review_start': opus_high})
        same = (MODELS / 'same-family/fleet.md').read_text()
        self.assertEqual(self.pass_settings(same, built_by='claude-code'), {
            'builder_start': dict(provider='claude-code', model='claude-opus-5-5', effort='medium'),
            'review_start': 'refused: no other-family reviewer: the review waits, never swapped'})
        self.assertEqual(self.pass_settings(same, built_by='codex')['review_start'], opus_high)
        run = self.flags(same, 'review_of_claude_built')
        self.assertEqual((run.returncode, run.stdout, run.stderr),
                         (1, '', 'ops-starts: review_of_claude_built waits: no other-family choice\n'))

    def test_a_broken_models_table_is_refused_never_guessed(self):
        both = (MODELS / 'both/fleet.md').read_text()
        breaks = (('| Reviewer | Codex', '| Reviewers | Codex'),
                  ('| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 '
                   '--reasoning-level medium` |', '| Builder | follows Builder | | | |'),
                  ('--reasoning-level medium` |\n| Reviewer', '--effort medium` |\n| Reviewer'),
                  ('| Small builder | follows Builder | | | |\n| Fixer',
                   '| Fixer | follows Builder | | | |\n| Small builder'),
                  ('`room-cli thread spawn` flags |', 'flags |'),
                  ('--model claude-opus-5-5 --reasoning-level medium` |\n| Reviewer',
                   '--model vendor//demo --reasoning-level medium` |\n| Reviewer'),
                  ('## Loop', '## Models\n\n## Loop'),
                  ('| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol '
                   '--reasoning-level medium` |\n', ''))
        for old, new in breaks:
            with self.subTest(new):
                broken = both.replace(old, new, 1)
                self.assertNotEqual(broken, both)
                run = self.flags(broken)
                self.assertEqual((run.returncode, run.stdout, run.stderr[:21]), (2, '', 'ops-starts: refused: '))
                refused = self.pass_settings(broken)
                self.assertIsInstance(refused, str)
                self.assertTrue(refused.startswith('refused: '), refused)
        for name in ('Builder', 'Fixer'):
            with self.subTest(older_without=name):
                five = (MODELS / 'five-tables/fleet.md').read_text().replace(f'## {name}\n', f'## Not {name}\n', 1)
                run = self.flags(five)
                self.assertEqual((run.returncode, run.stdout, run.stderr[:21]), (2, '', 'ops-starts: refused: '))

    def test_starts_read_the_default_branch_never_the_checkout(self):
        changed = self.one.replace('`--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |\n'
                                   '| Reviewer', '`--provider claude-code --model claude-sonnet-5-5 '
                                   '--reasoning-level low` |\n| Reviewer', 1)
        self.assertNotEqual(changed, self.one)
        read = []
        with tempfile.TemporaryDirectory() as tmp:
            run, calls = run_cli(tmp, changed, 'flags', '--repo', 'synthetic/ops', 'builder', checkout=self.one)
            self.assertEqual((run.returncode, run.stdout, calls),
                             (0, '--provider claude-code --model claude-sonnet-5-5 --reasoning-level low\n', read))
            path = Path(tmp) / 'world.json'
            path.write_text(json.dumps(self.base))
            run, calls = run_cli(tmp, changed, 'pass', str(path), checkout=self.one)
            self.assertEqual((run.returncode, calls), (0, read), run.stderr)
            self.assertEqual(json.loads(run.stdout.splitlines()[0])['settings'],
                             dict(provider='claude-code', model='claude-sonnet-5-5', effort='low'))
            for args in (('flags', '--repo', 'synthetic/ops', 'builder'), ('pass', str(path))):
                run, _ = run_cli(tmp, None, *args, checkout=self.one)
                self.assertEqual((run.returncode, run.stdout, run.stderr[:21]), (2, '', 'ops-starts: refused: '))
            for args in (('flags', 'builder'), ('flags', '--repo', '../ops', 'builder'),
                         ('flags', '--repo', 'synthetic/ops', '--repo', 'synthetic/ops')):
                run, calls = run_cli(tmp, self.one, *args, checkout=self.one)
                self.assertEqual((run.returncode, run.stdout, calls), (2, '', []))

    def test_an_older_table_is_read_whole_or_refused(self):
        five = (MODELS / 'five-tables/fleet.md').read_text()
        model = '| Model | Opus 5.5 | `--model claude-opus-5-5` |\n'
        claude = ('| Claude | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 '
                  '--reasoning-level medium` |\n')
        breaks = {
            'surplus conflicting Builder Model row': (
                '| Effort | Medium | `--reasoning-level medium` |\n\n## Builder for',
                '| Effort | Medium | `--reasoning-level medium` |\n' + model.replace('Opus 5.5', 'Sonnet 5.5')
                .replace('claude-opus-5-5', 'claude-sonnet-5-5') + '\n## Builder for'),
            'surplus row after Effort': ('| Effort | Medium | `--reasoning-level medium` |\n\n## Builder for',
                                         '| Effort | Medium | `--reasoning-level medium` |\n| Note | x | y |\n\n'
                                         '## Builder for'),
            'second table': ('| Effort | Medium | `--reasoning-level medium` |\n\n## Builder for',
                             '| Effort | Medium | `--reasoning-level medium` |\n\nText.\n\n| A | B | C |\n\n'
                             '## Builder for'),
            'one table split by text': ('| Model | Opus 5.5 | `--model claude-opus-5-5` |\n| Effort',
                                        '| Model | Opus 5.5 | `--model claude-opus-5-5` |\n\nText.\n\n| Effort'),
            'wrong header': ('## Builder\n\nOne per ticket, on its own branch.\n\n| Setting | Value | '
                             '`room-cli thread spawn` flag |', '## Builder\n\nOne per ticket, on its own branch.'
                             '\n\n| Setting | Value | Flag |'),
            'wrong separator': ('## Builder\n\nOne per ticket, on its own branch.\n\n| Setting | Value | '
                                '`room-cli thread spawn` flag |\n| --- | --- | --- |',
                                '## Builder\n\nOne per ticket, on its own branch.\n\n| Setting | Value | '
                                '`room-cli thread spawn` flag |\n| :-- | --- | --- |'),
            'value cell with a second flag': ('| Harness | Claude Code | `--provider claude-code` |',
                                              '| Harness | Claude Code | `--provider claude-code --x` |'),
            'repeated Claude Fixer row': (claude, claude + claude.replace('Opus 5.5 | Medium', 'Sonnet 5.5 | Low')
                                          .replace('claude-opus-5-5 --reasoning-level medium',
                                                   'claude-sonnet-5-5 --reasoning-level low')),
            'surplus Fixer row': (claude, claude + '| Other | Codex | Sol 6.2 | Medium | `--provider codex '
                                  '--model gpt-6.2-sol --reasoning-level medium` |\n'),
            'wrong Fixer header': ('| Builder family | Harness |', '| Family | Harness |'),
        }
        for name, (old, new) in breaks.items():
            with self.subTest(name):
                broken = five.replace(old, new, 1)
                self.assertNotEqual(broken, five)
                self.assertIsInstance(self.pass_settings(broken), str)
                run = self.flags(broken)
                self.assertEqual((run.returncode, run.stdout, run.stderr[:21]), (2, '', 'ops-starts: refused: '))
        gpt = ('| GPT | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` '
               '|\n')
        swapped = five.replace(claude + gpt, gpt + claude, 1)
        self.assertNotEqual(swapped, five)
        self.assertEqual(self.starts(swapped), self.starts(five))

    def test_an_older_fixer_of_another_family_waits(self):
        five = (MODELS / 'five-tables/fleet.md').read_text()
        claude = ('| Claude | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 '
                  '--reasoning-level medium` |')
        for name, row in (('Codex as the Claude fixer', '| Claude | Codex | Sol 6.2 | Medium | `--provider codex '
                                                         '--model gpt-6.2-sol --reasoning-level medium` |'),
                          ('an unknown provider', '| Claude | Other | Demo | Medium | `--provider other '
                                                  '--model demo --reasoning-level medium` |')):
            with self.subTest(name):
                wrong = five.replace(claude, row, 1)
                self.assertNotEqual(wrong, five)
                self.assertIsNone(self.api.spawn_flags(self.api.read_models(wrong))['fix_round_for_claude_builder'])
                run = self.flags(wrong, 'fix_round_for_claude_builder')
                self.assertEqual((run.returncode, run.stdout, run.stderr),
                                 (1, '', "ops-starts: fix_round_for_claude_builder waits: no choice of the "
                                         "builder's family\n"))
                self.assertEqual(self.flags(wrong, 'fix_round_for_gpt_builder').stdout,
                                 '--provider codex --model gpt-6.2-sol --reasoning-level medium\n')

    def test_a_spec_loop_follows_the_orchestrator_row_at_its_next_start(self):
        def loops(agent):
            return json.dumps({'automations': [
                {'id': 'loop-other', 'agent': None},
                {'id': 'loop-spec', 'agent': agent}]})
        opus = {'provider': 'claude-code', 'model': 'claude-opus-5-5', 'reasoning': 'medium'}
        sol = {'provider': 'codex', 'model': 'gpt-6.2-sol', 'reasoning': 'high'}
        changed = self.one.replace(
            '| Orchestrator | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 '
            '--reasoning-level medium` |',
            '| Orchestrator | Codex | Sol 6.2 | High | `--provider codex --model gpt-6.2-sol '
            '--reasoning-level high` |', 1)
        update = ('stale: room-cli loop update loop-spec --provider codex --model gpt-6.2-sol '
                  '--reasoning high\n')
        cases = (('saved agent is the row', self.one, opus, (0, 'current\n')),
                 ('the row changed on the default branch', changed, opus, (1, update)),
                 ('after the update', changed, sol, (0, 'current\n')),
                 ('no saved agent', changed, None, (1, update)),
                 ('another effort', changed, dict(sol, reasoning='medium'), (1, update)))
        with tempfile.TemporaryDirectory() as tmp:
            for name, fleet, agent, want in cases:
                with self.subTest(name):
                    run, _ = run_cli(tmp, fleet, 'loop-agent', '--repo', 'synthetic/ops', 'loop-spec', '-',
                                     checkout=self.one, stdin=loops(agent))
                    self.assertEqual((run.returncode, run.stdout), want, run.stderr)
            for name, stdin in (('loop missing', json.dumps({'automations': [{'id': 'loop-other', 'agent': None}]})),
                                ('loop twice', json.dumps({'automations': [{'id': 'loop-spec', 'agent': opus}] * 2})),
                                ('agent extra key', loops(dict(opus, extra='x'))),
                                ('unreadable', '{"automations": ')):
                with self.subTest(name):
                    run, _ = run_cli(tmp, self.one, 'loop-agent', '--repo', 'synthetic/ops', 'loop-spec', '-',
                                     stdin=stdin)
                    self.assertEqual((run.returncode, run.stdout), (2, ''))

    def test_reviewer_fallback_order_and_antigravity_flags_p1(self):
        fleet = (
            '# Fleet settings\n\n'
            '## Models\n\n'
            '| Role | Harness | Model | Effort | `room-cli thread spawn` flags |\n'
            '| --- | --- | --- | --- | --- |\n'
            '| Orchestrator | Claude Code | Opus 5.5 | Medium | '
            '`--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |\n'
            '| Builder | Antigravity | Gemini 4 Neon | Medium | '
            '`--provider antigravity --reasoning-level medium` |\n'
            '| Reviewer | Claude Code | Opus 5.5 | Medium | '
            '`--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |\n'
            '| Small builder | follows Builder | | | |\n'
            '| Fixer | follows Builder | | | |\n'
            '| Reviewer fall-back 1 | Antigravity | Gemini 4 Neon | High | '
            '`--provider antigravity --reasoning-level high` |\n'
            '| Reviewer fall-back 2 | Codex | Sol 6.2 | Medium | '
            '`--provider codex --model gpt-6.2-sol --reasoning-level medium` |\n'
        )
        run = self.flags(fleet, 'builder')
        self.assertEqual((run.returncode, run.stdout, run.stderr),
                         (0, '--provider antigravity --reasoning-level medium\n', ''))
        run = self.flags(fleet, 'small_builder')
        self.assertEqual((run.returncode, run.stdout, run.stderr),
                         (0, '--provider antigravity --reasoning-level medium\n', ''))
        with tempfile.TemporaryDirectory() as tmp:
            order, _ = run_cli(tmp, fleet, 'reviewer-order', '--repo', 'synthetic/ops')
            self.assertEqual(order.returncode, 0, order.stderr)
            self.assertEqual(
                order.stdout.splitlines(),
                [
                    '--provider claude-code --model claude-opus-5-5 --reasoning-level medium',
                    '--provider antigravity --reasoning-level high',
                    '--provider codex --model gpt-6.2-sol --reasoning-level medium',
                ],
            )
        bad_cases = (
            ('skipped fallback index', fleet.replace('Reviewer fall-back 1', 'Reviewer fall-back 2', 1)),
            ('duplicate fallback', fleet + '| Reviewer fall-back 1 | Codex | Sol 6.2 | Medium | '
                                           '`--provider codex --model gpt-6.2-sol --reasoning-level medium` |\n'),
            ('fallback follows builder', fleet.replace(
                '| Reviewer fall-back 1 | Antigravity | Gemini 4 Neon | High | '
                '`--provider antigravity --reasoning-level high` |',
                '| Reviewer fall-back 1 | follows Builder | | | |', 1)),
            ('missing reasoning-level flag', fleet.replace(
                '`--provider antigravity --reasoning-level medium`',
                '`--provider antigravity`', 1)),
        )
        for name, broken in bad_cases:
            with self.subTest(name):
                run = self.flags(broken, 'builder')
                self.assertEqual((run.returncode, run.stdout, run.stderr[:21]), (2, '', 'ops-starts: refused: '))

    def test_reviewer_fallback_advances_only_on_usage_limit_refusal_p2(self):
        fleet = (
            '# Fleet settings\n\n'
            '## Models\n\n'
            '| Role | Harness | Model | Effort | `room-cli thread spawn` flags |\n'
            '| --- | --- | --- | --- | --- |\n'
            '| Orchestrator | Claude Code | Opus 5.5 | Medium | '
            '`--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |\n'
            '| Builder | Antigravity | Gemini 4 Neon | Medium | '
            '`--provider antigravity --reasoning-level medium` |\n'
            '| Reviewer | Claude Code | Opus 5.5 | Medium | '
            '`--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |\n'
            '| Small builder | follows Builder | | | |\n'
            '| Fixer | follows Builder | | | |\n'
            '| Reviewer fall-back 1 | Antigravity | Gemini 4 Neon | High | '
            '`--provider antigravity --reasoning-level high` |\n'
            '| Reviewer fall-back 2 | Codex | Sol 6.2 | Medium | '
            '`--provider codex --model gpt-6.2-sol --reasoning-level medium` |\n'
        )
        commit = 'a' * 40
        other_commit = 'b' * 40
        self.assertEqual(
            self.api.refused_families_for_commit([
                f'launch-fleet: review refused {commit}: claude usage limit',
                f'launch-fleet: review started {commit}',
                f'launch-fleet: review refused {commit}: network timeout',
                f'launch-fleet: review refused {other_commit}: antigravity usage limit',
            ], commit),
            ('claude',),
        )
        self.assertEqual(
            self.api.refused_families_for_commit([
                f'launch-fleet: review refused {commit}: claude usage limit',
                f'launch-fleet: review refused {commit}: antigravity usage limit',
            ], commit),
            ('claude', 'antigravity'),
        )
        with tempfile.TemporaryDirectory() as tmp:
            first, _ = run_cli(tmp, fleet, 'reviewer-order', '--repo', 'synthetic/ops')
            self.assertEqual((first.returncode, first.stdout.splitlines()[0]),
                             (0, '--provider claude-code --model claude-opus-5-5 --reasoning-level medium'))
            fb1, _ = run_cli(tmp, fleet, 'reviewer-order', '--repo', 'synthetic/ops', '--refused', 'claude')
            self.assertEqual((fb1.returncode, fb1.stdout.splitlines()), (0, [
                '--provider antigravity --reasoning-level high',
                '--provider codex --model gpt-6.2-sol --reasoning-level medium',
            ]))
            fb2, _ = run_cli(tmp, fleet, 'reviewer-order', '--repo', 'synthetic/ops',
                             '--refused', 'claude', '--refused', 'antigravity')
            self.assertEqual((fb2.returncode, fb2.stdout.splitlines()),
                             (0, ['--provider codex --model gpt-6.2-sol --reasoning-level medium']))
            exhausted, _ = run_cli(tmp, fleet, 'reviewer-order', '--repo', 'synthetic/ops',
                                   '--refused', 'claude', '--refused', 'antigravity', '--refused', 'codex')
            self.assertEqual((exhausted.returncode, exhausted.stdout), (1, ''))

    def test_gemini_antigravity_cross_family_reviews_both_ways(self):
        claude = dict(provider='claude-code', model='claude-opus-5-5', effort='medium')
        gemini = dict(provider='antigravity', model='gemini-4-neon', effort='medium')
        claude_builder_gemini_reviewer = self.one.replace(
            '| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |',
            '| Reviewer | Antigravity | Gemini 4 Neon | Medium | `--provider antigravity --model gemini-4-neon --reasoning-level medium` |',
        )
        self.assertEqual(
            self.pass_settings(claude_builder_gemini_reviewer, built_by='claude-code')['review_start'],
            gemini,
        )
        self.assertEqual(
            self.pass_settings(claude_builder_gemini_reviewer, built_by='antigravity')['review_start'],
            claude,
        )
        gemini_builder_claude_reviewer = self.one.replace(
            '| Builder | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |',
            '| Builder | Antigravity | Gemini 4 Neon | Medium | `--provider antigravity --model gemini-4-neon --reasoning-level medium` |',
        ).replace(
            '| Reviewer | Codex | Sol 6.2 | Medium | `--provider codex --model gpt-6.2-sol --reasoning-level medium` |',
            '| Reviewer | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |',
        )
        self.assertEqual(
            self.pass_settings(gemini_builder_claude_reviewer, built_by='antigravity')['review_start'],
            claude,
        )
        self.assertEqual(
            self.pass_settings(gemini_builder_claude_reviewer, built_by='claude-code')['review_start'],
            gemini,
        )
        same_gemini = gemini_builder_claude_reviewer.replace(
            '| Reviewer | Claude Code | Opus 5.5 | Medium | `--provider claude-code --model claude-opus-5-5 --reasoning-level medium` |',
            '| Reviewer | Antigravity | Gemini 4 Neon | Medium | `--provider antigravity --model gemini-4-neon --reasoning-level medium` |',
        )
        self.assertEqual(
            self.pass_settings(same_gemini, built_by='antigravity')['review_start'],
            'refused: no other-family reviewer: the review waits, never swapped',
        )
        five = (MODELS / 'five-tables/fleet.md').read_text()
        self.assertEqual(
            self.pass_settings(five, built_by='antigravity')['review_start'],
            'refused: no other-family reviewer: the review waits, never swapped',
        )
        older_with_gemini = five.replace(
            '| Harness | Codex | `--provider codex` |\n| Model | Sol 6.2 | `--model gpt-6.2-sol` |',
            '| Harness | Antigravity | `--provider antigravity` |\n| Model | Gemini 4 Neon | `--model gemini-4-neon` |',
            1,
        ) + (
            '\n## Reviewer for Gemini-built\n\n'
            '| Setting | Value | `room-cli thread spawn` flag |\n'
            '| --- | --- | --- |\n'
            '| Harness | Claude Code | `--provider claude-code` |\n'
            '| Model | Opus 5.5 | `--model claude-opus-5-5` |\n'
            '| Effort | Medium | `--reasoning-level medium` |\n'
        )
        self.assertEqual(
            self.pass_settings(older_with_gemini, built_by='claude-code')['review_start'],
            gemini,
        )
        self.assertEqual(
            self.pass_settings(older_with_gemini, built_by='antigravity')['review_start'],
            claude,
        )
        run = self.flags(claude_builder_gemini_reviewer, 'review_of_gemini_built')
        self.assertEqual(
            (run.returncode, run.stdout),
            (0, '--provider claude-code --model claude-opus-5-5 --reasoning-level medium\n'),
        )
        run = self.flags(gemini_builder_claude_reviewer, 'fix_round_for_gemini_builder')
        self.assertEqual(
            (run.returncode, run.stdout),
            (0, '--provider antigravity --model gemini-4-neon --reasoning-level medium\n'),
        )


if __name__ == '__main__':
    unittest.main()
