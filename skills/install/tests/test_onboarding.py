#!/usr/bin/env python3
"""The onboarding road (#1358): three choices, a short grill, a teacher, the first merge.

Replays three recorded synthetic onboardings (fixtures/onboarding.json), one
per first choice, against the packaged helper and recording fakes, and checks
the road's own steps one at a time: where agents run, the host setting, the
grill confirmed in chat, the launch from the plan's machine approval, and the
closing offer after a merge read back from GitHub. All values are synthetic.
"""
import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_first_fleet import (CLAUDE, FIXTURES, GRILL, WS17, WS17_WHY, Journey, SKILL_DIR,  # noqa: E402
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


def teach_lines():
    """teach.md's quoted lines under each heading."""
    found = {}
    for section in TEACH.split('\n## ')[1:]:
        found[section.split('\n')[0]] = [line[2:] for line in section.split('\n') if line.startswith('> ')]
    return found


def pattern(template):
    """A filled teach line: every word kept, each <...> filled (one of its options when it lists them)."""
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
    """One recorded onboarding road, replayed in its own private folder."""

    def __init__(self, case, journey):
        super().__init__(case)
        self.journey = journey
        self.repo = journey['repo']
        self.world['repo'] = self.repo
        self.world['files'] = {**self.world['files'], 'docs/agents/fleet.md': fleet_md(builder=CLAUDE, small=CLAUDE)}
        self.save_world()
        self.settings = {'harness': 'claude-code', 'model': 'syn-claude-model-01', 'effort': 'high'}
        repos = [demo_repository(self.repo)] if journey['existing'] else []
        self.repos.write_text(github(repos))
        adapters = self.dir / 'adapters/local'
        adapters.mkdir(parents=True)
        driver = adapters / 'driver'
        driver.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, FIXTURES / 'fake_driver.py'))
        driver.chmod(0o755)
        harness = self.dir / 'bin/claude'
        harness.write_text('#!/bin/sh\necho "$0 $*" >> "%s"\nexit 97\n' % (self.dir / 'harness.log'))
        harness.chmod(0o755)
        self.extra_env.update(OPENWIZ_ADAPTERS=str(self.dir / 'adapters'),
                              FAKE_DRIVER_LOG=str(self.dir / 'driver.log'), FAKE_GH_ARGV_LOG=str(self.dir / 'gh-argv.log'))

    def machine_approve(self, grill=GRILL, comment=90001):
        self.approve(comment=comment, grill=grill)

    def change(self, turn):
        self.world = json.loads(self.world_path.read_text())  # the fake gh writes it too
        what = turn['world']
        if what in ('signed_out', 'signed_in'):
            repos = json.loads(self.repos.read_text())
            repos['signed_out'] = what == 'signed_out'
            self.repos.write_text(json.dumps(repos))
        elif what == 'merge_setting':
            self.world['files']['docs/agents/host.md'] = self.world['branches']['openwiz/host-setting'][
                'docs/agents/host.md']
            self.world['host_pulls'][0]['state'] = 'MERGED'
            self.save_world()
        elif what == 'fleet_record':
            self.fleet_record()
        elif what == 'merged':
            pull = turn['pull']
            self.world.setdefault('onboard_pulls', []).append({
                'number': pull['number'], 'url': 'https://github.com/%s/pull/%d' % (self.repo, pull['number']),
                'title': pull['title'], 'state': 'MERGED', 'mergedAt': '2026-11-01T12:40:00Z',
                'closingIssuesReferences': [{'number': pull['closes']}]})
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
                self.write_setup(setup_state(turn['setup'], repository=self.repo,
                                             settings=('claude-code', 'syn-claude-model-01', 'high')))
            elif 'tool' in turn:
                results.append((turn, self.tool(turn)))
        return results

    def gh_calls(self):
        path = self.dir / 'gh-argv.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def driver_calls(self):
        path = self.dir / 'driver.log'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def saved(self):
        return json.loads(self.state.read_text()) if self.state.exists() else {}


def until(step):
    return lambda turn: turn['step'] == step


class Conversation(unittest.TestCase):
    """The packaged skill and the recorded roads, read as conversations."""

    def test_the_skill_says_each_moment_in_order_and_asks_no_plan_approval(self):
        # catches: the skill dropping a moment's line, the three choices or the grill's yes, or keeping a plan approval
        text = (SKILL_DIR / 'SKILL.md').read_text()
        headings = ['Up front', 'Install done', 'Where agents run', 'The grill', 'The spec and its video',
                    'The fleet starting', 'A pull request opened', 'Reviewed', 'Merged', 'The closing offer']
        at = [text.find('**%s**' % h) for h in headings]
        self.assertNotIn(-1, at, dict(zip(headings, at)))
        self.assertEqual(at, sorted(at))
        for words in ('ideas.md', 'teach.md', 'grill --confirmed', 'first-merge'):
            self.assertIn(words, text)
        self.assertNotRegex(text, r'(?i)exact-plan approval|approve the plan|demo repository \(recommended\)')

    def test_each_road_follows_the_skills_steps_in_order(self):
        # catches: a road whose recorded steps skip, repeat or reorder the packaged skill's steps
        steps = skill_steps()
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                seen = [turn['step'] for turn in journey['turns']]
                self.assertEqual(sorted(set(seen), key=steps.index), steps)
                self.assertEqual(seen, sorted(seen, key=steps.index))

    def test_every_moment_says_its_teach_line_in_order(self):
        # catches: a road that skips a moment's line, rewords it, leaves a <placeholder> unfilled or says it out of order
        lines = teach_lines()
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                said = [t for t in journey['turns'] if 'say' in t]
                spoken = [t['say'] for t in said if t['say'] != 'missing']
                self.assertEqual(spoken, ORDER)
                for turn in said:
                    self.assertTrue(says(turn['agent'], turn['say'], lines), (turn['say'], turn['agent']))
                    self.assertNotRegex(turn['agent'], r'<[^>]+>')
                self.assertEqual([t['agent'] for t in said[:3]], lines['Up front'])
        self.assertTrue(any(t.get('say') == 'missing' for j in ROAD['journeys'] for t in j['turns']))

    def test_after_the_grills_yes_nothing_is_asked_until_the_closing_offer(self):
        # catches: a plan or spec approval, or a "start them?" launch question, coming back after the grill's yes
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                turns = journey['turns']
                yes = next(i for i, t in enumerate(turns) if t.get('say') == 'grill-summary') + 1
                self.assertEqual(turns[yes].get('user'), 'Yes.')
                offer = next(i for i, t in enumerate(turns) if t.get('say') == 'offer')
                asked = [t['agent'] for t in turns[yes + 1:offer] if '?' in t.get('agent', '')]
                self.assertEqual(asked, [])
                self.assertFalse([t for t in turns if re.search(r'(?i)\bapprove\b', t.get('agent', ''))])
                launch = [t['tool'] for t in turns if t.get('tool', [''])[0] == 'launch']
                self.assertEqual(launch, [['launch', '--spec', '900']])

    def test_every_gate_is_asked_before_its_effect(self):
        # catches: a repository created, a file written or setup run without its own yes first
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
                    if args[:1] == ['continue']:
                        self.assertIn('setup', granted)
                    if 'gate' in turn:
                        self.assertTrue(turn['agent'].endswith('?'))
                        self.assertEqual(turns[i + 1].get('permits'), [turn['gate']])

    def test_ideas_come_from_the_chosen_group_and_the_user_picks(self):
        # catches: ideas invented on the spot, or offered from another choice's group
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                offer = next(t for t in journey['turns'] if 'ideas' in t)
                self.assertTrue(set(offer['ideas']) <= set(idea_group(journey['choice'])))
                self.assertTrue(2 <= len(offer['ideas']) <= 3)


@unittest.skipUnless(WS17, WS17_WHY)
class Replay(unittest.TestCase):
    """Each choice, replayed to its first merge against the fakes."""

    def test_each_choice_reaches_its_first_merge_and_the_closing_offer(self):
        # catches: a road that cannot start its fleet from the machine approval, asks for a launch yes, runs agents
        # somewhere other than the user's answer, or offers to close before a merge reads back
        for journey in ROAD['journeys']:
            with self.subTest(journey['name']):
                road = Road(self, journey)
                for turn, result in road.replay_road():
                    self.assertEqual(result.returncode, turn['exit'], (turn['tool'], result.stdout, result.stderr))
                spawns = road.spawns()
                self.assertEqual(len(spawns), 1)
                machine = spawns[0][spawns[0].index('--machine') + 1]
                self.assertEqual(machine, journey['host'])
                outputs = {tuple(args): result.stdout for args, result in road.calls}
                launch = outputs[('launch', '--spec', '900')]
                fleet = next(t['agent'] for t in journey['turns'] if t.get('say') == 'fleet-start')
                self.assertIn(fleet, launch.splitlines())
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
        # catches: a signed-out user recorded as ready, or the helper running a sign-in itself
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
        # catches: "this machine" recorded where no local driver or no harness could run a builder
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
        # catches: a host recorded before the user answered, or a choice that hides what it spends
        road = self.road()
        preview = road.helper(['where', '--agents', 'cloud'])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        self.assertIn('Cloud Credits', preview.stdout)
        self.assertNotIn('host', road.saved())
        local = road.helper(['where', '--agents', 'local', '--yes'])
        self.assertEqual(local.returncode, 0, local.stdout)
        self.assertEqual(road.saved()['host'], {'agents': 'local', 'harnesses': ['claude-code']})
        self.assertEqual(road.driver_calls(), [['version']])


class Setting(unittest.TestCase):
    def connected(self, name='small-change'):
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == name))
        road.replay_road(stop=until('setting'))
        return road

    def test_this_machine_opens_one_host_setting_pull_request_only_on_yes(self):
        # catches: the setting written without its yes, written twice, or naming anything beyond the host
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
        # catches: cloud agents silently sent to a host the project names, or a user's setting replaced
        road = self.connected('fresh-project')
        result = road.helper(['setting'])
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('branches', json.loads(road.world_path.read_text()))
        road = self.connected('fresh-project')
        road.world['files']['docs/agents/host.md'] = '# Host\n\nHost: local\n'
        road.save_world()
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
        # catches: a fleet started from another grill's plan, or from an approval nobody's checks made
        road = self.planned(grill=OTHER_GRILL)
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('grill', result.stdout)
        road.approve(comment=90003, human=True)  # a human plan graph approval, newest
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertEqual(road.spawns(), [])

    def test_no_launch_without_the_grills_yes_or_the_hosts_answer(self):
        # catches: a fleet started before the user confirmed the grill in chat or said where agents run
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
        # catches: builders started on this machine while launch-fleet would still read no host, or another one
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == 'always-wanted'))
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch', skip=lambda t: t.get('world') == 'merge_setting')
        road.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': ''}]}))
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('host setting', result.stdout)
        road.world['files']['docs/agents/host.md'] = 'Host: local\nHost: boat\n'
        road.save_world()
        result = road.helper(['launch', '--spec', '900'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertEqual(road.spawns(), [])


class FirstMerge(unittest.TestCase):
    def test_the_closing_offer_follows_only_a_merge_read_back_for_this_spec(self):
        # catches: the closing offer made on a count, an open pull request, or a merge from another spec
        road = Road(self, next(j for j in ROAD['journeys'] if j['name'] == 'fresh-project'))
        road.replay_road(stop=lambda t: t.get('tool', [''])[0] == 'launch')
        saved = road.saved()
        saved['launch'] = {'spec': 900, 'state': 'started', 'tickets': [901, 902, 903]}
        road.state.write_text(json.dumps(saved))
        offer = teach_lines()['The closing offer'][0][:20]
        pulls = [{'number': 911, 'url': 'https://github.com/%s/pull/911' % road.repo, 'title': '#901: T1',
                  'state': 'OPEN', 'mergedAt': None, 'closingIssuesReferences': [{'number': 901}]},
                 {'number': 912, 'url': 'https://github.com/%s/pull/912' % road.repo, 'title': '#77: other',
                  'state': 'MERGED', 'mergedAt': '2026-11-01T12:40:00Z', 'closingIssuesReferences': [{'number': 77}]}]
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
