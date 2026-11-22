#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_first_fleet import (CLAUDE, FIXTURES, GRILL, Journey, SKILL_DIR,  # noqa: E402 -- it follows the sys.path line that finds it
                              demo_repository, fleet_md, github, setup_state, skill_steps)

ROAD = json.loads((FIXTURES / 'onboarding.json').read_text())
TEACH = (SKILL_DIR / 'teach.md').read_text()
IDEAS = (SKILL_DIR / 'ideas.md').read_text()
OTHER_GRILL = 'https://github.com/synthetic-owner/synthetic-private/issues/1#issuecomment-72'
MOMENTS = {'up-front': ('Up front', None), 'install-done': ('Install done', 0), 'where': ('Where agents run', 0),
           'missing': ('Where agents run', 1), 'grill-start': ('The grill', 0), 'grill-summary': ('The grill', 1),
           'spec': ('The spec and its video', 0), 'fleet-start': ('The fleet starting', 0),
           'pr-opened': ('A pull request opened', 0), 'reviewed': ('Reviewed', 0), 'merged': ('Merged', 0),
           'offer': ('The closing offer', 0)}
ORDER = ['up-front', 'up-front', 'up-front', 'install-done', 'where', 'grill-start', 'grill-summary', 'spec',
         'fleet-start', 'pr-opened', 'reviewed', 'merged', 'offer']


def fake_driver(path, folder, **values):
    values = dict(FAKE_DRIVER_LOG=str(folder / 'driver.log'), FAKE_DRIVER_SEEN=str(folder / 'driver-seen.log'),
                  **values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\nexec env %s "%s" -I "%s" "$@"\n' % (
        ' '.join('%s=%s' % (k, shlex.quote(v)) for k, v in values.items()), sys.executable,
        FIXTURES / 'fake_driver.py'))
    path.chmod(0o755)


def teach_lines():
    found = {}
    for section in TEACH.split('\n## ')[1:]:
        found[section.split('\n')[0]] = [line[2:] for line in section.split('\n') if line.startswith('> ')]
    return found


def pattern(template):
    out, at = '', 0
    for match in re.finditer(r'`?<([^>]+)>`?', template):
        out += re.escape(template[at:match.start()])
        options = match[1].split(' | ')
        out += '(?:%s)' % '|'.join(map(re.escape, options)) if len(options) > 1 else r'([^<>`]+?)'
        at = match.end()
    return re.compile(out + re.escape(template[at:]))


def says(line, moment, lines=None):
    heading, index = MOMENTS[moment]
    candidates = (lines or teach_lines())[heading]
    return any(pattern(t).fullmatch(line) for t in (candidates if index is None else [candidates[index]]))


def idea_group(choice):
    groups = {}
    for section in IDEAS.split('\n## ')[1:]:
        groups[section.split('\n')[0]] = re.findall(r'^- \*\*(.+?)\*\*', section, re.M)
    return {'A small change in a repository I have.': groups['A small change in a repository they have'],
            'A fresh project from my idea.': groups['A fresh project from an idea'],
            "Something I've always wanted to build.": groups["Something they've always wanted"]}[choice]


class Road(Journey):

    def __init__(self, case, journey):
        super().__init__(case)
        self.journey = journey
        self.repo = journey['repo']
        self.world['repo'] = self.repo
        self.world['files'] = {**self.world['files'], 'docs/agents/fleet.md': fleet_md(builder=CLAUDE, small=CLAUDE)}
        self.save_world()
        self.origin_write({'docs/agents/fleet.md': self.world['files']['docs/agents/fleet.md']})
        self.settings = {'harness': 'claude-code', 'model': 'syn-claude-model-01', 'effort': 'high'}
        repos = [demo_repository(self.repo)] if journey['existing'] else []
        self.repos.write_text(github(repos))
        fake_driver(self.dir / 'adapters/local/driver', self.dir)
        harness = self.dir / 'bin/claude'
        harness.write_text('#!/bin/sh\necho "$0 $*" >> "%s"\nexit 97\n' % (self.dir / 'harness.log'))
        harness.chmod(0o755)
        self.host_state = Path(tempfile.mkdtemp(prefix='host-state-'))
        case.addCleanup(shutil.rmtree, self.host_state, True)
        self.extra_env.update(OPENWIZ_ADAPTERS=str(self.dir / 'adapters'), OPENWIZ_LOCAL_STATE=str(self.host_state),
                              FAKE_DRIVER_LOG=str(self.dir / 'driver.log'), FAKE_GH_ARGV_LOG=str(self.dir / 'gh-argv.log'))

    def helper(self, args):
        host = self.saved().get('host', {}).get('agents', 'cloud')
        if host == 'cloud' or args[0] not in ('launch', 'progress'):
            return super().helper(args)
        home = self.dir / 'skills'
        helper = home / 'install/scripts/first_fleet.py'
        if not helper.exists():
            helper.parent.mkdir(parents=True)
            shutil.copyfile(SKILL_DIR / 'scripts/first_fleet.py', helper)
            (home / 'install/teach.md').symlink_to(SKILL_DIR / 'teach.md')
            (home / 'setup').symlink_to(SKILL_DIR.parent / 'setup', target_is_directory=True)
            (home / 'to-tickets').symlink_to(SKILL_DIR.parent / 'to-tickets', target_is_directory=True)
            shutil.copytree(SKILL_DIR.parent / 'launch-fleet', home / 'launch-fleet')
            (home / 'launch-fleet/scripts/heartbeat.py').write_text(
                "from pathlib import Path\nimport sys\n"
                f"assert sys.argv[1:] == ['status', {self.repo!r}, '900'], sys.argv[1:]\n"
                "path = Path('heartbeat-status')\n"
                "print(path.read_text() if path.exists() else 'heartbeat: not installed')\n")
        with patch('test_first_fleet.HELPER', helper):
            return super().helper(args)

    def approvals(self):
        path = self.host_state / 'approvals.json'
        return json.loads(path.read_text()) if path.exists() else None

    def machine_approve(self, grill=GRILL, comment=90001):
        self.approve(comment=comment, grill=grill)

    def change(self, turn):
        self.world = json.loads(self.world_path.read_text())
        what = turn['world']
        if what in ('signed_out', 'signed_in'):
            repos = json.loads(self.repos.read_text())
            repos['signed_out'] = what == 'signed_out'
            self.repos.write_text(json.dumps(repos))
        elif what == 'merge_setting':
            merged = {path: self.world['branches']['openwiz/host-setting'][path]
                      for path in ('docs/agents/host.md', 'docs/agents/fleet.md')}
            self.origin_write(merged)
            self.world['files'].update(merged)
            self.world['host_pulls'][0]['state'] = 'MERGED'
            self.save_world()
        elif what == 'fleet_record':
            self.fleet_record()
        elif what == 'heartbeat_active':
            (self.dir / 'heartbeat-status').write_text('heartbeat: active (cron)')
        elif what == 'merged':
            pull = turn['pull']
            self.world.setdefault('onboard_pulls', []).append({
                'number': pull['number'], 'url': 'https://github.com/%s/pull/%d' % (self.repo, pull['number']),
                'title': pull['title'], 'state': 'MERGED', 'mergedAt': '2026-11-01T12:40:00Z',
                'closingIssuesReferences': [closing(self.repo, pull['closes'])]})
            self.save_world()

    def replay_road(self, stop=None, skip=None):
        results = []
        for turn in self.journey['turns']:
            if stop and stop(turn):
                break
            if skip and skip(turn):
                continue
            if 'world' in turn:
                self.change(turn)
            if 'plan' in turn:
                self.plan(turn['plan'])
            elif turn.get('approve') == 'machine':
                self.machine_approve()
            elif 'setup' in turn:
                state = setup_state(turn['setup'], repository=self.repo,
                                    settings=('claude-code', 'syn-claude-model-01', 'high'))
                host = self.saved().get('host', {}).get('agents', 'cloud')
                if host != 'cloud':
                    state['project'].update(host=host, project=None, answer_thread=None)
                    state['observations']['cloudroom']['code'] = 'cloudroom_not_needed'
                    self.options.write_text(json.dumps(dict(json.loads(self.options.read_text()), source='local')))
                self.write_setup(state)
            elif 'tool' in turn:
                results.append((turn, self.tool(turn)))
        return results

    def gh_calls(self):
        path = self.dir / 'gh-argv.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def driver_seen(self):
        path = self.dir / 'driver-seen.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def driver_calls(self):
        path = self.dir / 'driver.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def saved(self):
        return json.loads(self.state.read_text()) if self.state.exists() else {}


def closing(repo, number):
    owner, name = repo.split('/')
    return {'number': number, 'repository': {'name': name, 'owner': {'login': owner}}}


def until(step):
    return lambda turn: turn['step'] == step


class Conversation(unittest.TestCase):

    def test_the_skill_says_each_moment_in_order_and_asks_no_plan_approval(self):
        text = (SKILL_DIR / 'SKILL.md').read_text()
        headings = ['Up front', 'Install done', 'Where agents run', 'The grill', 'The spec and its video',
                    'The fleet starting', 'A pull request opened', 'Reviewed', 'Merged', 'The closing offer']
        at = [text.find('**%s**' % h) for h in headings]
        self.assertNotIn(-1, at, dict(zip(headings, at)))
        self.assertEqual(at, sorted(at))
        for words in ('ideas.md', 'teach.md', 'grill --confirmed', 'first-merge'):
            self.assertIn(words, text)
        self.assertNotRegex(text, r'(?i)exact-plan approval|approve the plan|demo repository \(recommended\)')

    def test_the_owner_steers_through_the_orchestrator_never_by_video_comment(self):
        text = (SKILL_DIR / 'SKILL.md').read_text()
        plan = text.split('### 7. Plan\n', 1)[1].split('\n### ', 1)[0]
        self.assertIn('steers through the orchestrator', plan)
        for name, words in (('SKILL.md', text), ('teach.md', TEACH)):
            self.assertNotRegex(words, r'(?i)comment[^.\n]*\bto steer\b|\bsteer[^.\n]*\bby comment|stop, reset, or anything else',
                                name)
        for journey in ROAD['journeys']:
            said = ' '.join(t.get('agent', '') for t in journey['turns'])
            self.assertNotRegex(said, r'(?i)comment[^.]*\bsteer|\bsteer[^.]*comment', journey['name'])

    def test_each_road_follows_the_skills_steps_in_order(self):
        steps = skill_steps()
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                seen = [turn['step'] for turn in journey['turns']]
                self.assertEqual(sorted(set(seen), key=steps.index), steps)
                self.assertEqual(seen, sorted(seen, key=steps.index))

    def test_every_moment_says_its_teach_line_in_order(self):
        lines = teach_lines()
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                said = [t for t in journey['turns'] if 'say' in t]
                spoken = [t['say'] for t in said if t['say'] != 'missing']
                self.assertEqual(spoken, ORDER)
                for turn in said:
                    if journey['host'] == 'local' and turn['say'] == 'fleet-start':
                        self.assertIn('local heartbeat is active', turn['agent'])
                    else:
                        self.assertTrue(says(turn['agent'], turn['say'], lines), (turn['say'], turn['agent']))
                    self.assertNotRegex(turn['agent'], r'<[^>]+>')
                self.assertEqual([t['agent'] for t in said[:3]], lines['Up front'])
        self.assertTrue(any(t.get('say') == 'missing' for j in ROAD['journeys'] for t in j['turns']))

    def test_after_the_grills_yes_only_the_gates_and_the_mode_ask_until_the_closing_offer(self):
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                turns = journey['turns']
                yes = next(i for i, t in enumerate(turns) if t.get('say') == 'grill-summary') + 1
                self.assertEqual(turns[yes].get('user'), 'Yes.')
                offer = next(i for i, t in enumerate(turns) if t.get('say') == 'offer')
                asked = [t for t in turns[yes + 1:offer] if '?' in t.get('agent', '')]
                local = journey['host'] == 'local'
                self.assertEqual([t.get('gate') or t.get('asks') for t in asked],
                                 ['permission_mode', 'write', 'start_fleet'] if local else ['start_fleet'])
                where = 'on this machine' if local else 'in Cloudroom'
                self.assertTrue(asked[-1]['agent'].startswith('Start the fleet %s now? It can cost money: ' % where))
                self.assertFalse([t for t in turns if re.search(r'(?i)\bapprove\b', t.get('agent', ''))])
                launch = [t['tool'] for t in turns if t.get('tool', [''])[0] == 'launch']
                self.assertEqual(launch, [['launch', '--spec', '900'],
                                          ['launch', '--spec', '900', '--yes', '--confirm', '@preview'],
                                          ['launch', '--spec', '900']])

    def test_every_gate_is_asked_before_its_effect(self):
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                turns, granted = journey['turns'], set()
                for i, turn in enumerate(turns):
                    granted.update(turn.get('permits', []))
                    args = turn.get('tool', [])
                    if args[:1] == ['create-repo'] and '--yes' in args:
                        self.assertIn('create_repository', granted)
                    if args[:1] == ['setting'] and '--yes' in args:
                        self.assertIn('write', granted)
                    if args[:1] == ['launch'] and '--yes' in args:
                        self.assertEqual(turns[i - 1].get('permits'), ['start_fleet'])
                    if args[:1] == ['continue']:
                        self.assertIn('setup', granted)
                    if 'gate' in turn:
                        self.assertIn('?', turn['agent'])
                        self.assertEqual(turns[i + 1].get('permits'), [turn['gate']])

    def test_ideas_come_from_the_chosen_group_and_the_user_picks(self):
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                offer = next(t for t in journey['turns'] if 'ideas' in t)
                self.assertTrue(set(offer['ideas']) <= set(idea_group(journey['choice'])))
                self.assertTrue(2 <= len(offer['ideas']) <= 3)


class Replay(unittest.TestCase):

    def test_each_choice_reaches_its_first_merge_and_the_closing_offer(self):
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                road = Road(self, journey)
                if journey['host'] == 'local':
                    (road.dir / 'bin/room-cli').unlink()
                    self.assertIsNone(shutil.which('room-cli', path=road.env()['PATH']))
                for turn, result in road.replay_road():
                    self.assertEqual(result.returncode, turn['exit'], (turn['tool'], result.stdout, result.stderr))
                self.assertEqual(road.spawns(), [], "the start is launch-fleet's own path, never a one-off thread")
                outputs = {tuple(args): result.stdout for args, result in road.calls}
                launches = [result.stdout for args, result in road.calls if args == ['launch', '--spec', '900']]
                ask = next(t['agent'] for t in journey['turns'] if t.get('gate') == 'start_fleet')
                self.assertIn(ask, launches[0].splitlines())
                yes = next(result.stdout for args, result in road.calls if args[:4] == ['launch', '--spec', '900', '--yes'])
                fleet = next(t['agent'] for t in journey['turns'] if t.get('say') == 'fleet-start')
                self.assertNotIn(fleet, yes.splitlines(), 'not before the activation record reads back')
                self.assertIn(fleet, launches[-1].splitlines())
                if journey['host'] == 'local':
                    self.assertIn("launch-fleet's Launch section", yes)
                    self.assertIn('local heartbeat', yes)
                    self.assertIn('driver harness `claude`', yes)
                    self.assertNotIn('Starting one', yes)
                    self.assertEqual(sum(args == ['mode'] for args, _ in road.calls), 1)
                    self.assertEqual(road.saved()['mode']['mode'], 'acceptEdits')
                    self.assertIn('Host: local', road.world['files']['docs/agents/host.md'])
                adapters = 'OPENWIZ_ADAPTERS=%s' % (road.dir / 'adapters')
                self.assertEqual(adapters in yes, journey['host'] == 'local', 'the loop finds the local driver (R2)')
                merged = outputs[('first-merge', '--pr', '911')].splitlines()
                for moment in ('merged', 'offer'):
                    said = next(t['agent'] for t in journey['turns'] if t.get('say') == moment)
                    self.assertIn(said, merged)
                self.assertEqual(road.saved()['grill'], GRILL)
                self.assertFalse((road.dir / 'harness.log').exists())
                self.assertTrue(road.driver_calls())
                self.assertEqual({tuple(c) for c in road.driver_calls()}, {('version',)})


class Where(unittest.TestCase):
    def road(self, name='small-change'):
        return Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))

    def test_a_missing_github_sign_in_is_walked_through_and_no_login_is_touched(self):
        road = self.road()
        road.change({'world': 'signed_out'})
        result = road.helper(['where', '--agents', 'local', '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        missing = [line for line in result.stdout.splitlines() if says(line, 'missing')]
        self.assertEqual(len(missing), 1, result.stdout)
        self.assertIn('https://github.com/login', missing[0])
        self.assertNotIn('host', road.saved())
        self.assertFalse([c for c in road.gh_calls() if c[:1] == ['auth']])

    def test_this_machine_needs_the_local_driver_and_a_harness_here(self):
        road = self.road()
        (road.dir / 'bin/claude').unlink()
        result = road.helper(['where', '--agents', 'local', '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertTrue([line for line in result.stdout.splitlines() if says(line, 'missing')], result.stdout)
        self.assertNotIn('host', road.saved())
        road = self.road()
        (road.dir / 'adapters/local/driver').unlink()
        result = road.helper(['where', '--agents', 'local', '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('local driver', result.stdout)
        self.assertNotIn('host', road.saved())

    def test_the_answer_is_recorded_only_on_yes_with_its_cost(self):
        road = self.road()
        preview = road.helper(['where', '--agents', 'cloud'])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        self.assertIn('Cloud Credits', preview.stdout)
        self.assertNotIn('host', road.saved())
        local = road.helper(['where', '--agents', 'local', '--yes'])
        self.assertEqual(local.returncode, 0, local.stdout)
        self.assertEqual(road.saved()['host'], {'agents': 'local', 'harnesses': ['claude-code'],
                                                'adapters': str(road.dir / 'adapters')})
        self.assertEqual(road.driver_calls(), [['version'], ['version']])


class Setting(unittest.TestCase):
    def connected(self, name='small-change'):
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        return road

    def test_this_machine_opens_one_host_setting_pull_request_only_on_yes(self):
        road = self.connected()
        preview = road.helper(['setting'])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        self.assertEqual(json.loads(road.world_path.read_text()).get('host_pulls', []), [])
        for _ in range(2):
            result = road.helper(['setting', '--yes'])
            self.assertEqual(result.returncode, 0, result.stdout)
        world = json.loads(road.world_path.read_text())
        self.assertEqual(len(world['host_pulls']), 1)
        text = world['branches']['openwiz/host-setting']['docs/agents/host.md']
        self.assertEqual(re.findall(r'(?m)^Host:.*$', text), ['Host: local'])
        self.assertEqual(road.saved()['setting']['state'], 'opened')

    def test_cloudroom_writes_no_host_file_and_a_conflicting_one_is_never_overwritten(self):
        road = self.connected('fresh-project')
        result = road.helper(['setting'])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('branches', json.loads(road.world_path.read_text()))
        road = self.connected('fresh-project')
        road.origin_write({'docs/agents/host.md': '# Host\n\nHost: local\n'})
        result = road.helper(['setting', '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('Host: local', result.stdout)
        self.assertNotIn('host_pulls', json.loads(road.world_path.read_text()))


class Launch(unittest.TestCase):
    def planned(self, name='fresh-project', grill=GRILL):
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))
        road.replay_road(stop=lambda t: t.get('approve'))
        road.machine_approve(grill=grill)
        self.assertEqual(road.helper(['spec', '--spec', '900', '--repo', road.repo]).returncode, 0)
        return road

    def test_only_the_machine_approval_of_this_grill_starts_the_fleet(self):
        road = self.planned(grill=OTHER_GRILL)
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('grill', result.stdout)
        road.approve(comment=90003, human=True)
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertEqual(road.spawns(), [])

    def test_no_launch_without_the_grills_yes_or_the_hosts_answer(self):
        road = self.planned()
        saved = road.saved()
        self.assertEqual(saved.pop('grill', None), GRILL)
        road.state.write_text(json.dumps(saved))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        saved.pop('host')
        saved['grill'] = GRILL
        road.state.write_text(json.dumps(saved))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertEqual(road.spawns(), [])

    def test_this_machine_waits_for_the_merged_host_setting(self):
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == 'always-wanted'))
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch', skip=lambda t: t.get('world') == 'merge_setting')
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('host setting', result.stdout)
        road.origin_write({'docs/agents/host.md': 'Host: local\nHost: boat\n'})
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('exactly one `Host: <name>` line', result.stdout)
        self.assertEqual(road.spawns(), [])


class SteeringOff(unittest.TestCase):

    def test_a_spec_with_its_video_and_the_one_time_notice_still_launches(self):
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == 'fresh-project'))
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
        road.world = json.loads(road.world_path.read_text())
        road.world['issues'][0]['comments'] += [
            {'id': 90010, 'at': '2026-11-01T10:30:00Z', 'body': '[Watch the narrated spec](https://openwiz.dev/app/'
             'videos/syn-900)\n\nComment here to steer: stop, reset, or anything else.'},
            {'id': 90011, 'at': '2026-11-01T10:40:00Z', 'body': 'stop'}]
        road.save_world()
        notice = subprocess.run(['sh', str(SKILL_DIR.parent / 'launch-fleet/scripts/fleet.sh'), 'spec', '900'],
                                env=road.env(), cwd=road.dir, capture_output=True, text=True, timeout=300)
        self.assertEqual([line for line in notice.stdout.splitlines() if 'steer' in line],
                         ['look #900: comments on the video steer nothing until the identity separation of OpenWiz '
                          '#1402 is verified; the owner steers through the orchestrator'], notice.stdout + notice.stderr)
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        preview = road.helper(['launch', '--spec', '900'])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        yes = road.helper(['launch', '--spec', '900', '--yes', '--confirm',
                           re.findall(r'(?m)^Confirmation: ([0-9a-f]{64})$', preview.stdout)[0]])
        self.assertEqual(yes.returncode, 0, yes.stdout)
        road.change({'world': 'fleet_record'})
        started = road.helper(['launch', '--spec', '900'])
        self.assertEqual(started.returncode, 0, started.stdout)
        self.assertEqual(road.saved()['launch']['state'], 'started')
        self.assertEqual(road.spawns(), [])


class LaunchYes(unittest.TestCase):

    def test_no_fleet_starts_without_the_yes_that_names_the_host_and_its_cost(self):
        for name, where in (('fresh-project', 'in Cloudroom'), ('always-wanted', 'on this machine')):
            with self.subTest(name):
                road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))
                road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
                road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
                preview = road.helper(['launch', '--spec', '900'])
                self.assertEqual(preview.returncode, 12, preview.stdout)
                self.assertEqual(road.spawns(), [])
                ask = [line for line in preview.stdout.splitlines() if '?' in line]
                self.assertEqual(len(ask), 1, preview.stdout)
                self.assertIn(where, ask[0])
                self.assertIn('can cost money', ask[0])
                digest = re.findall(r'(?m)^Confirmation: ([0-9a-f]{64})$', preview.stdout)
                self.assertEqual(len(digest), 1, preview.stdout)
                bare = road.helper(['launch', '--spec', '900', '--yes'])
                self.assertEqual(bare.returncode, 2, bare.stdout)
                other = road.helper(['launch', '--spec', '900', '--yes', '--confirm', '0' * 64])
                self.assertEqual(other.returncode, 5, other.stdout)
                self.assertEqual(road.spawns(), [], 'no fleet starts without the yes to this preview')
                said_yes = road.helper(['launch', '--spec', '900', '--yes', '--confirm', digest[0]])
                self.assertEqual(said_yes.returncode, 0, said_yes.stdout)
                self.assertEqual(road.saved()['launch']['state'], 'authorized', 'only that yes hands the start over')
                self.assertEqual(road.spawns(), [])


class Drivers(unittest.TestCase):

    def road(self, name='fresh-project', boat=None):
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))
        fake_driver(road.dir / 'adapters/cloudroom/driver', road.dir, FAKE_DRIVER_NAME='cloudroom')
        fake_driver(road.dir / 'adapters/boat/driver', road.dir, **(boat or {'FAKE_DRIVER_NAME': 'boat'}))
        boat = road.dir / 'bin/boat'
        boat.write_text('#!/bin/sh\necho "$0 $*" >> "%s"\nexit 97\n' % (road.dir / 'boat.log'))
        boat.chmod(0o755)
        return road

    def test_a_build_with_the_local_cloudroom_and_boat_drivers_offers_all_three(self):
        road = self.road()
        offer = road.helper(['where'])
        self.assertEqual(offer.returncode, 12, offer.stdout)
        offered = re.findall(r'(?m)^- (\S+): (.+)$', offer.stdout)
        self.assertEqual([name for name, _ in offered], ['local', 'cloud', 'boat'], offer.stdout)
        self.assertIn('boat.dev', dict(offered)['boat'])
        self.assertNotIn('Not offered', offer.stdout)
        self.assertNotIn('host', road.saved())
        self.assertFalse((road.dir / 'boat.log').exists(), 'only version is called: nothing starts on boat.dev')

    def test_a_driver_whose_version_fails_is_not_offered_and_the_road_says_why(self):
        for boat, why in (({'FAKE_DRIVER_NAME': 'boat', 'FAKE_DRIVER_FAIL': '1'}, 'failed (exit 1)'),
                          ({'FAKE_DRIVER_NAME': 'local'}, 'names another driver')):
            with self.subTest(why):
                road = self.road(boat=boat)
                offer = road.helper(['where'])
                self.assertEqual(offer.returncode, 12, offer.stdout)
                self.assertEqual(re.findall(r'(?m)^- (\S+):', offer.stdout), ['local', 'cloud'], offer.stdout)
                refused = [line for line in offer.stdout.splitlines() if line.startswith('Not offered: ')]
                self.assertEqual(len(refused), 1, offer.stdout)
                self.assertTrue(refused[0].startswith('Not offered: boat: '), refused[0])
                self.assertIn(why, refused[0])
                self.assertNotIn('synthetic: not signed in', offer.stdout, "the driver's own words stay off the road")
                picked = road.helper(['where', '--agents', 'boat', '--yes'])
                self.assertEqual(picked.returncode, 5, picked.stdout)
                self.assertNotIn('host', road.saved())

    def test_picking_boat_writes_the_host_line_launch_fleet_reads_after_the_same_preview_and_yes(self):
        road = self.road()
        preview = road.helper(['where', '--agents', 'boat'])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        self.assertIn('boat.dev', preview.stdout)
        self.assertIn('bills', preview.stdout)
        self.assertNotIn('host', road.saved())
        self.assertEqual(road.helper(['where', '--agents', 'boat', '--yes']).returncode, 0)
        self.assertEqual(road.saved()['host'], {'agents': 'boat', 'harnesses': [],
                                                'adapters': str(road.dir / 'adapters')})
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting',
                         skip=lambda t: t.get('tool', [''])[0] == 'where')
        self.assertEqual(road.saved()['choices']['agents'], 'boat')
        self.assertEqual(road.helper(['mode']).returncode, 5, 'a permission mode is for this machine only')
        preview = road.helper(['setting'])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        self.assertIn('`Host: boat`', preview.stdout)
        self.assertNotIn('host_pulls', json.loads(road.world_path.read_text()))
        wrote = road.helper(['setting', '--yes'])
        self.assertEqual(wrote.returncode, 0, wrote.stdout + wrote.stderr)
        world = json.loads(road.world_path.read_text())
        self.assertEqual(len(world['host_pulls']), 1)
        branch = world['branches']['openwiz/host-setting']
        changed = sorted(p for p in set(branch) | set(world['files']) if branch.get(p) != world['files'].get(p))
        self.assertEqual(changed, ['docs/agents/host.md'], 'only the host line; no permission mode row')
        self.assertEqual(re.findall(r'(?m)^Host:.*$', branch['docs/agents/host.md']), ['Host: boat'])
        road.origin_write({'docs/agents/host.md': branch['docs/agents/host.md']})
        world['host_pulls'][0]['state'] = 'MERGED'
        road.world = world
        road.save_world()
        which = subprocess.run([sys.executable, '-I', str(SKILL_DIR.parent / 'launch-fleet/scripts/host.py'), 'which'],
                               env=road.env(), capture_output=True, text=True, cwd=road.dir, timeout=60)
        self.assertEqual(which.stdout.strip(), 'host: boat', which.stderr)
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch',
                         skip=lambda t: 'world' in t or t.get('tool', [''])[0] != 'spec' and 'tool' in t
                         or 'setup' in t)
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        launch = road.helper(['launch', '--spec', '900'])
        self.assertEqual(launch.returncode, 12, launch.stdout)
        ask = [line for line in launch.stdout.splitlines() if '?' in line]
        self.assertEqual(len(ask), 1, launch.stdout)
        self.assertIn('on boat.dev', ask[0])
        self.assertIn('can cost money', ask[0])
        self.assertIn('bills', ask[0])
        digest = re.findall(r'(?m)^Confirmation: ([0-9a-f]{64})$', launch.stdout)[0]
        said_yes = road.helper(['launch', '--spec', '900', '--yes', '--confirm', digest])
        self.assertEqual(said_yes.returncode, 0, said_yes.stdout)
        self.assertIn('OPENWIZ_ADAPTERS=%s' % (road.dir / 'adapters'), said_yes.stdout)
        self.assertIn('local heartbeat', said_yes.stdout)
        self.assertNotIn('Starting one', said_yes.stdout)
        self.assertEqual(road.spawns(), [])
        self.assertFalse((road.dir / 'boat.log').exists(), 'the road itself never runs boat')


    def test_r1_a_version_probe_gets_no_caller_variable_and_no_stdin(self):
        road = self.road()
        road.extra_env.update(SYNTHETIC_ONBOARD_TOKEN='synthetic-marker-not-a-credential',
                              SYNTHETIC_CALLER_MARKER='synthetic-marker')
        argv = [sys.executable, '-I', str(SKILL_DIR / 'scripts/first_fleet.py'), 'where', '--state', str(road.state)]
        offer = subprocess.run(argv, env=road.env(), input='', capture_output=True, text=True, cwd=road.dir,
                               timeout=120)
        self.assertEqual(offer.returncode, 12, offer.stdout)
        seen = road.driver_seen()
        self.assertEqual(sorted(s['name'] for s in seen), ['boat', 'local'], 'cloudroom is offered as cloud, unprobed')
        for call in seen:
            self.assertEqual(call['argv'], ['version'])
            self.assertNotIn('SYNTHETIC_ONBOARD_TOKEN', call['env'])
            self.assertNotIn('SYNTHETIC_CALLER_MARKER', call['env'])
            self.assertIn('PATH', call['env'])
            self.assertTrue(call['stdin_null'], call)

    def test_r2_a_version_answer_outside_driver_v1s_schema_is_not_offered(self):
        good = {'driver': 'boat', 'records': ['openwiz:records v1'], 'can': ['start', 'wake', 'stop', 'own-sandbox']}
        bad = [dict(good, records=[1]), dict(good, records=[]), dict(good, records=['openwiz:records v2']),
               dict(good, records=['openwiz:records v1', 'openwiz:records v1']),
               dict(good, can=['start', 'wake', 'stop', 'fly']), dict(good, can=['start', 'start', 'wake', 'stop']),
               dict(good, can=['start', 'wake']), dict(good, extra=True), dict(good, driver=7), ['boat']]
        for answer in [good] + bad:
            with self.subTest(answer=answer):
                road = self.road(boat={'FAKE_DRIVER_NAME': 'boat', 'FAKE_DRIVER_ANSWER': json.dumps(answer)})
                offer = road.helper(['where'])
                self.assertEqual(offer.returncode, 12, offer.stdout)
                offered = re.findall(r'(?m)^- (\S+):', offer.stdout)
                if answer is good:
                    self.assertEqual(offered, ['local', 'cloud', 'boat'], offer.stdout)
                    continue
                self.assertEqual(offered, ['local', 'cloud'], offer.stdout)
                self.assertEqual(re.findall(r'(?m)^Not offered: (\S+): ', offer.stdout), ['boat'], offer.stdout)

    def test_r3_each_driver_host_says_where_its_login_lives_even_with_its_cli_installed(self):
        road = self.road()
        fake_driver(road.dir / 'adapters/acme/driver', road.dir, FAKE_DRIVER_NAME='acme')
        boat = road.helper(['where', '--agents', 'boat'])
        self.assertEqual(boat.returncode, 12, boat.stdout)
        self.assertIn('Login: held by boat.dev', boat.stdout)
        self.assertIn('dashboard', boat.stdout)
        ask = [line for line in boat.stdout.splitlines() if line.endswith('?')]
        self.assertEqual(len(ask), 1, boat.stdout)
        self.assertIn('signed in', ask[0])
        self.assertFalse((road.dir / 'boat.log').exists(), 'the user signs in; the road never runs boat')
        acme = road.helper(['where', '--agents', 'acme'])
        self.assertEqual(acme.returncode, 12, acme.stdout)
        self.assertIn('https://github.com/openwizdev/OpenWiz/blob/main/adapters/acme/README.md', acme.stdout)
        self.assertIn('Login:', acme.stdout)

    def test_r4_resuming_before_the_host_lists_from_the_build_and_previews_before_the_yes(self):
        road = self.road()
        out = road.helper(['next']).stdout
        self.assertIn('where --build <build>', out)
        preview = 'where --agents <the pick> --build <build>'
        self.assertIn(preview, out)
        self.assertLess(out.index(preview), out.index('--yes'), out)
        self.assertNotRegex(out, r'<the pick>[^.;]*--yes')


class PermissionMode(unittest.TestCase):

    def road(self, name):
        return Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))

    def test_the_question_explains_each_mode_and_picks_none_for_the_owner(self):
        road = self.road('small-change')
        road.replay_road(stop=lambda t: t.get('tool') == ['mode'])
        asked = road.helper(['mode'])
        self.assertEqual(asked.returncode, 12, asked.stdout)
        listed = re.findall(r'(?m)^- (\S+): (.+)$', asked.stdout)
        self.assertEqual([m for m, _ in listed], ['default', 'acceptEdits', 'bypassPermissions'], asked.stdout)
        self.assertTrue(all(len(why.split()) >= 5 for _, why in listed), 'each mode explained in plain words')
        self.assertNotRegex(asked.stdout, r'(?i)recommend|default choice|\(suggested\)')
        self.assertNotIn('mode', road.saved())
        wider = road.helper(['mode', '--mode', 'danger-full-access'])
        self.assertEqual(wider.returncode, 5, wider.stdout)
        self.assertNotIn('mode', road.saved())
        picked = road.helper(['mode', '--mode', 'acceptEdits'])
        self.assertEqual(picked.returncode, 0, picked.stdout)
        self.assertEqual(road.saved()['mode'], {'harness': 'claude-code', 'mode': 'acceptEdits'})
        self.assertFalse([c for c in road.gh_calls() if c[:1] == ['auth']])
        road = self.road('fresh-project')
        road.replay_road(stop=until('setting'))
        self.assertEqual(road.helper(['mode']).returncode, 5, 'Cloudroom asks no local permission mode')

    def test_no_fleet_starts_on_this_machine_before_the_mode_is_saved(self):
        road = self.road('always-wanted')
        road.replay_road(stop=lambda t: t.get('tool') == ['mode'])
        unpicked = road.helper(['setting', '--yes'])
        self.assertEqual(unpicked.returncode, 5, unpicked.stdout)
        self.assertNotIn('host_pulls', json.loads(road.world_path.read_text()))
        road = self.road('always-wanted')
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
        road.origin_write({'docs/agents/host.md': '# Where agents run\n\nHost: local\n\nPermission mode: acceptEdits\n',
                           'docs/agents/fleet.md': fleet_md(builder=CLAUDE, small=CLAUDE)})
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('| Harness permission mode | `acceptEdits` |', result.stdout, 'names the exact row to save')
        self.assertIn('docs/agents/fleet.md', result.stdout)
        self.assertIn('run mode, then setting, and merge it', result.stdout, 'and how the owner saves it')
        self.assertEqual(road.spawns(), [])

    def test_the_mode_is_one_fleet_md_row_and_an_owners_row_is_never_overwritten(self):
        road = self.road('small-change')
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        before = road.world['files']['docs/agents/fleet.md']
        for _ in range(2):
            result = road.helper(['setting', '--yes'])
            self.assertEqual(result.returncode, 0, result.stdout)
        world = json.loads(road.world_path.read_text())
        self.assertEqual(len(world['host_pulls']), 1)
        fleet = world['branches']['openwiz/host-setting'].get('docs/agents/fleet.md', '')
        self.assertEqual(re.findall(r'(?m)^\| Harness permission mode \|.*$', fleet),
                         ['| Harness permission mode | `acceptEdits` |'])
        self.assertTrue(fleet.startswith(before.rstrip('\n')), 'every other line of fleet.md stays')
        road = self.road('small-change')
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        owned = road.world['files']['docs/agents/fleet.md'] + '\n| Harness permission mode | `default` |\n'
        road.world['files']['docs/agents/fleet.md'] = owned
        road.save_world()
        road.origin_write({'docs/agents/fleet.md': owned})
        refused = road.helper(['setting', '--yes'])
        self.assertEqual(refused.returncode, 5, refused.stdout)
        self.assertIn('`default`', refused.stdout)
        self.assertNotIn('host_pulls', json.loads(road.world_path.read_text()))


class HostApproval(unittest.TestCase):

    def road(self, name='always-wanted'):
        return Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))

    def test_the_pick_writes_this_machines_approval_once_and_never_widens_it(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool') == ['mode'])
        self.assertIsNone(road.approvals())
        self.assertEqual(road.helper(['mode', '--mode', 'acceptEdits']).returncode, 0)
        self.assertEqual(road.approvals(), {road.repo: {'claude': 'acceptEdits'}})
        path = road.host_state / 'approvals.json'
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertFalse(str(path.resolve()).startswith(str(road.dir.resolve())), 'outside the repository')
        wider = road.helper(['mode', '--mode', 'bypassPermissions'])
        self.assertEqual(wider.returncode, 5, wider.stdout)
        self.assertEqual(road.approvals(), {road.repo: {'claude': 'acceptEdits'}}, 'never widened')
        self.assertFalse([c for c in road.gh_calls() if c[:1] == ['auth']])

    def test_the_approval_adds_only_this_entry_keeps_every_other_byte_and_is_owner_only_600(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool') == ['mode'])
        others = ('{\n  "synthetic-owner/other": {\n    "codex": "read-only"\n  },\n  "%s": {\n    "codex": '
                  '"workspace-write"\n  }\n}\n' % road.repo)
        path = road.host_state / 'approvals.json'
        path.write_text(others)
        path.chmod(0o600)
        picked = road.helper(['mode', '--mode', 'acceptEdits'])
        self.assertEqual(picked.returncode, 0, picked.stdout)
        text = path.read_text()
        for kept in ('"synthetic-owner/other": {\n    "codex": "read-only"\n  }', '"codex": "workspace-write"\n  }'):
            self.assertIn(kept, text, 'every other entry byte for byte')
        self.assertEqual(json.loads(text), {'synthetic-owner/other': {'codex': 'read-only'},
                                            road.repo: {'codex': 'workspace-write', 'claude': 'acceptEdits'}})
        info = path.stat()
        self.assertEqual(info.st_uid, os.getuid())
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in road.host_state.iterdir()), ['approvals.json', 'approvals.json.lock'],
                         'no temporary file left; the lock every onboarding session shares stays')

    def test_an_approvals_file_others_can_change_is_refused_never_fixed(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool') == ['mode'])
        path = road.host_state / 'approvals.json'
        path.write_text('{"synthetic-owner/other": {"codex": "read-only"}}\n')
        path.chmod(0o622)
        refused = road.helper(['mode', '--mode', 'acceptEdits'])
        self.assertEqual(refused.returncode, 5, refused.stdout)
        self.assertIn('chmod 600', refused.stdout)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o622, 'never fixed silently')
        self.assertEqual(path.read_text(), '{"synthetic-owner/other": {"codex": "read-only"}}\n')
        self.assertNotIn('mode', road.saved())

    def test_neither_a_row_nor_an_approval_alone_launches_on_this_machine(self):
        cases = {'a row, no approval': None, 'a row, another approval': 'bypassPermissions'}
        for name, approval in cases.items():
            with self.subTest(name):
                road = self.road()
                road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
                path = road.host_state / 'approvals.json'
                if approval is None:
                    path.unlink(missing_ok=True)
                else:
                    path.write_text(json.dumps({road.repo: {'claude': approval}}))
                road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
                result = road.helper(['launch', '--spec', '900'])
                self.assertEqual(result.returncode, 5, result.stdout)
                self.assertIn('host-side approval', result.stdout)
                self.assertIn('mode --mode acceptEdits', result.stdout, 'says what to do')
                self.assertEqual(road.spawns(), [])
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
        road.origin_write({'docs/agents/fleet.md': fleet_md(builder=CLAUDE, small=CLAUDE)})
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('| Harness permission mode | `acceptEdits` |', result.stdout)
        self.assertIn('run mode, then setting, and merge it', result.stdout)
        self.assertEqual(road.spawns(), [])


class ReviewRound(unittest.TestCase):

    def road(self, name='always-wanted'):
        return Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))

    def test_r1_the_road_never_runs_a_sign_in_itself(self):
        text = (SKILL_DIR / 'SKILL.md').read_text()
        lines = [line for line in text.splitlines() if 'github_login.py sign-in' in line or 'auth login' in line]
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, r'\b(themselves|yourself)\b', line)
        self.assertIn('github_login.py status', text, "the agent's own step is the read-only check")
        road = self.road('fresh-project')
        road.change({'world': 'signed_out'})
        result = road.helper(['where', '--agents', 'cloud', '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertFalse([c for c in road.gh_calls() if c[:2] == ['auth', 'login']])

    def test_r2_this_machine_finds_the_driver_in_the_verified_build(self):
        road = self.road()
        del road.extra_env['OPENWIZ_ADAPTERS']
        build = road.dir / 'build'
        (build / 'runtime/adapters').mkdir(parents=True)
        shutil.copytree(road.dir / 'adapters/local', build / 'runtime/adapters/local')
        result = road.helper(['where', '--agents', 'local', '--build', str(build), '--yes'])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(road.saved()['host']['adapters'], str(build / 'runtime/adapters'))
        self.assertEqual(road.driver_calls(), [['version']])

    def test_r4_an_existing_branch_or_a_failed_write_never_opens_the_host_setting(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        world = json.loads(road.world_path.read_text())
        other = dict(world['files'])
        other['docs/agents/fleet.md'] += '\n| Harness permission mode | `default` |\n'
        other['docs/agents/host.md'] = '# Where agents run\n\nHost: boat\n'
        world.setdefault('branches', {})['openwiz/host-setting'] = other
        road.world_path.write_text(json.dumps(world))
        refused = road.helper(['setting', '--yes'])
        self.assertEqual(refused.returncode, 5, refused.stdout)
        after = json.loads(road.world_path.read_text())
        self.assertEqual(after.get('host_pulls', []), [])
        self.assertEqual(after['branches']['openwiz/host-setting'], other, 'the branch is left as it was')
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        world = json.loads(road.world_path.read_text())
        world['put_fails'] = True
        road.world_path.write_text(json.dumps(world))
        failed = road.helper(['setting', '--yes'])
        self.assertNotEqual(failed.returncode, 0, failed.stdout)
        self.assertNotEqual((road.saved().get('setting') or {}).get('state'), 'opened')

    def test_r4_an_edit_after_the_check_is_never_overwritten(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        world = json.loads(road.world_path.read_text())
        world.setdefault('branches', {})['openwiz/host-setting'] = dict(world['files'])
        theirs = world['files']['docs/agents/fleet.md'] + '\n| Harness permission mode | `default` |\n'
        world['edit_after_read'] = {'openwiz/host-setting': {'docs/agents/fleet.md': theirs}}
        road.world_path.write_text(json.dumps(world))
        refused = road.helper(['setting', '--yes'])
        self.assertEqual(refused.returncode, 5, refused.stdout)
        self.assertIn('changed while', refused.stdout)
        after = json.loads(road.world_path.read_text())
        self.assertEqual(after['branches']['openwiz/host-setting']['docs/agents/fleet.md'], theirs, 'their edit kept')
        self.assertEqual(after.get('host_pulls', []), [])
        self.assertNotEqual((road.saved().get('setting') or {}).get('state'), 'opened')

    def test_r4_a_branch_deleting_another_file_opens_nothing(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        world = json.loads(road.world_path.read_text())
        branch = dict(world['files'])
        del branch['docs/agents/triage-labels.md']
        world.setdefault('branches', {})['openwiz/host-setting'] = branch
        road.world_path.write_text(json.dumps(world))
        refused = road.helper(['setting', '--yes'])
        self.assertEqual(refused.returncode, 5, refused.stdout)
        self.assertIn('docs/agents/triage-labels.md', refused.stdout)
        self.assertEqual(json.loads(road.world_path.read_text()).get('host_pulls', []), [])
        self.assertNotEqual((road.saved().get('setting') or {}).get('state'), 'opened')

    def test_r4_a_resumed_pull_request_with_an_extra_change_is_not_ready(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'setting')
        self.assertEqual(road.helper(['setting', '--yes']).returncode, 0)
        world = json.loads(road.world_path.read_text())
        world['branches']['openwiz/host-setting']['docs/extra.md'] = 'another change\n'
        road.world_path.write_text(json.dumps(world))
        resumed = road.helper(['setting', '--yes'])
        self.assertEqual(resumed.returncode, 5, resumed.stdout)
        self.assertIn('docs/extra.md', resumed.stdout)
        self.assertNotIn('is open', resumed.stdout)

    def test_r5_line_endings_and_another_sessions_approval_survive(self):
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool') == ['mode'])
        path = road.host_state / 'approvals.json'
        path.write_bytes(b'{\r\n  "synthetic-owner/other": {"codex": "read-only"}\r\n}\r\n')
        path.chmod(0o600)
        self.assertEqual(road.helper(['mode', '--mode', 'acceptEdits']).returncode, 0)
        data = path.read_bytes()
        self.assertIn(b'"synthetic-owner/other": {"codex": "read-only"}\r\n', data)
        self.assertTrue(data.endswith(b'}\r\n'))
        road = self.road()
        road.replay_road(stop=lambda t: t.get('tool') == ['mode'])
        path = road.host_state / 'approvals.json'
        lock = open(road.host_state / 'approvals.json.lock', 'a+')
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        snapshot = {}
        proc = subprocess.Popen([sys.executable, '-I', str(SKILL_DIR / 'scripts/first_fleet.py'), 'mode', '--mode',
                                 'acceptEdits', '--state', str(road.state)], env=road.env(), cwd=road.dir,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        snapshot['synthetic-owner/other'] = {'codex': 'read-only'}
        path.write_text(json.dumps(snapshot))
        path.chmod(0o600)
        fcntl.flock(lock, fcntl.LOCK_UN)
        out, _ = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, out)
        self.assertEqual(road.approvals(), {'synthetic-owner/other': {'codex': 'read-only'},
                                            road.repo: {'claude': 'acceptEdits'}})

    def test_r3_without_node_the_video_is_skipped_in_one_line_and_the_fleet_still_starts(self):
        text = (SKILL_DIR / 'SKILL.md').read_text()
        plan = text.split('### 7. Plan\n', 1)[1].split('\n### ', 1)[0]
        self.assertRegex(plan, r'Without Node[^.]*skip[^.]*video')
        self.assertIn('the fleet still starts', plan)
        self.assertRegex(text, r'(?m)^- \*\*Read JSON and exit codes.*\bNode\b')

    def test_r7_the_fleet_starts_through_launch_fleets_start_path_not_a_one_off_thread(self):
        road = self.road('fresh-project')
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        preview = road.helper(['launch', '--spec', '900'])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        digest = re.findall(r'(?m)^Confirmation: ([0-9a-f]{64})$', preview.stdout)[0]
        fleet = teach_lines()['The fleet starting'][0].split(':', 1)[0]
        yes = road.helper(['launch', '--spec', '900', '--yes', '--confirm', digest])
        self.assertEqual(yes.returncode, 0, yes.stdout)
        self.assertEqual(road.spawns(), [], 'no one-off thread')
        self.assertNotIn(fleet, yes.stdout, 'not started until its activation record reads back')
        self.assertIn('Starting one', yes.stdout, "it hands the start to launch-fleet's own path")
        pending = road.helper(['launch', '--spec', '900'])
        self.assertEqual(pending.returncode, 6, pending.stdout)
        self.assertNotIn(fleet, pending.stdout)
        road.change({'world': 'fleet_record'})
        started = road.helper(['launch', '--spec', '900'])
        self.assertEqual(started.returncode, 0, started.stdout)
        self.assertIn(fleet, started.stdout)
        self.assertEqual(road.saved()['launch']['state'], 'started')
        self.assertEqual(road.spawns(), [])

    def test_r6_a_merge_closing_another_repositorys_issue_is_not_the_first_merge(self):
        road = self.road('fresh-project')
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
        saved = road.saved()
        saved['launch'] = {'spec': 900, 'state': 'started', 'tickets': [901, 902, 903]}
        road.state.write_text(json.dumps(saved))
        world = json.loads(road.world_path.read_text())
        world['onboard_pulls'] = [{'number': 911, 'url': 'https://github.com/%s/pull/911' % road.repo,
                                   'title': '#901: T1', 'state': 'MERGED', 'mergedAt': '2026-11-01T12:40:00Z',
                                   'closingIssuesReferences': [closing('synthetic-owner/elsewhere', 901)]}]
        road.world_path.write_text(json.dumps(world))
        result = road.helper(['first-merge', '--pr', '911'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertNotIn(teach_lines()['The closing offer'][0][:20], result.stdout)


class FirstMerge(unittest.TestCase):
    def test_the_closing_offer_follows_only_a_merge_read_back_for_this_spec(self):
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == 'fresh-project'))
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
        saved = road.saved()
        saved['launch'] = {'spec': 900, 'state': 'started', 'tickets': [901, 902, 903]}
        road.state.write_text(json.dumps(saved))
        offer = teach_lines()['The closing offer'][0][:20]
        pulls = [{'number': 911, 'url': 'https://github.com/%s/pull/911' % road.repo, 'title': '#901: T1',
                  'state': 'OPEN', 'mergedAt': None, 'closingIssuesReferences': [closing(road.repo, 901)]},
                 {'number': 912, 'url': 'https://github.com/%s/pull/912' % road.repo, 'title': '#77: other',
                  'state': 'MERGED', 'mergedAt': '2026-11-01T12:40:00Z', 'closingIssuesReferences': [closing(road.repo, 77)]}]
        road.world['onboard_pulls'] = pulls
        road.save_world()
        for number in (911, 912):
            result = road.helper(['first-merge', '--pr', str(number)])
            self.assertEqual(result.returncode, 5, result.stdout)
            self.assertNotIn(offer, result.stdout)
        pulls[0].update(state='MERGED', mergedAt='2026-11-01T12:41:00Z')
        road.save_world()
        result = road.helper(['first-merge', '--pr', '911'])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertTrue(says(result.stdout.splitlines()[-2], 'merged'), result.stdout)
        self.assertTrue(says(result.stdout.splitlines()[-1], 'offer'), result.stdout)


if __name__ == '__main__':
    unittest.main()
