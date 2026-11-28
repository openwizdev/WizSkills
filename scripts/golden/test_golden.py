import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
GENERATE = HERE / 'generate.py'
FIXTURES = ROOT / 'fixtures/records/v1'
FORMS = (
    'Status note', 'Decision request', 'Decision answer', 'Plan links', 'Labels',
    'Fleet OpenWiz rows', 'Fleet record authors', 'Fleet models', 'Models-offered snapshot',
    'Grill file', 'Spec and ticket templates', 'Narrated-spec video comment',
)
NOT_WIZSKILLS = {'Decision answer', 'Models-offered snapshot', 'Fleet OpenWiz rows'}


def generate(*args):
    return subprocess.run([sys.executable, '-I', str(GENERATE), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=300)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((FIXTURES / 'index.json').read_text())

    def copy(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        target = Path(tmp.name) / 'v1'
        shutil.copytree(FIXTURES, target)
        return target

    def test_every_records_v1_form_is_indexed_once(self):
        self.assertEqual(self.index['records_contract'], 1)
        self.assertEqual([form['form'] for form in self.index['forms']], list(FORMS))

    def test_every_form_with_a_wizskills_writer_has_a_fixture_from_it(self):
        listed = set()
        for form in self.index['forms']:
            if form['form'] in NOT_WIZSKILLS:
                self.assertEqual(form['fixtures'], [], form['form'])
                self.assertTrue(form['why_none'], form['form'])
                continue
            self.assertTrue(form['fixtures'], form['form'])
            for fixture in form['fixtures']:
                self.assertIn(fixture['made_by'], ('script', 'template', 'checked'))
                self.assertTrue(fixture['writer'].startswith('skills/'), fixture)
                self.assertTrue((ROOT / fixture['writer']).is_file(), fixture)
                self.assertTrue((FIXTURES / fixture['path']).is_file(), fixture)
                listed.add(fixture['path'])
        files = {p.relative_to(FIXTURES).as_posix() for p in FIXTURES.rglob('*') if p.is_file()}
        self.assertEqual(files - {'index.json'}, listed)

    def test_status_notes_and_decision_requests_read_back(self):
        status = load('status', ROOT / 'skills/launch-fleet/scripts/status.py')
        notes = [f for f in self.index['forms'][0]['fixtures']]
        self.assertEqual({n['state'] for n in notes}, {'working', 'asking', 'done', 'stopped'})
        for note in notes:
            self.assertIsNotNone(status.parse((FIXTURES / note['path']).read_text()), note)
        grill = load('records', ROOT / 'skills/grill/scripts/records.py')
        kinds = set()
        for request in self.index['forms'][1]['fixtures']:
            _, record = grill.parse_comment((FIXTURES / request['path']).read_text())
            self.assertEqual(record['schema'], 'openwiz.decisions.v1')
            self.assertEqual((record['kind'], record['status']), (request['kind'], request['state']))
            kinds.add(record['kind'])
        self.assertEqual(kinds, {'grill_round', 'grill_confirmation', 'spec_confirmation', 'plan_approval'})

    def test_committed_fixtures_are_fresh(self):
        result = generate('check')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_hand_edited_fixture_fails_the_freshness_check(self):
        target = self.copy()
        note = next(target.glob('status-note/*.md'))
        note.write_text(note.read_text().replace('state: ', 'state:  ', 1))
        result = generate('check', '--dir', str(target))
        self.assertEqual(result.returncode, 1)
        self.assertIn(note.relative_to(target).as_posix(), result.stdout)
        self.assertIn('scripts/golden/generate.py', result.stdout)

    def test_added_or_removed_fixture_fails_the_freshness_check(self):
        target = self.copy()
        (target / 'status-note/extra.md').write_text('hand made\n')
        result = generate('check', '--dir', str(target))
        self.assertEqual(result.returncode, 1)
        self.assertIn('status-note/extra.md', result.stdout)
        target = self.copy()
        (target / 'index.json').unlink()
        result = generate('check', '--dir', str(target))
        self.assertEqual(result.returncode, 1)
        self.assertIn('index.json', result.stdout)

    def test_release_archive_is_named_with_the_records_contract_version(self):
        with tempfile.TemporaryDirectory() as out:
            first = generate('archive', out)
            self.assertEqual(first.returncode, 0, first.stderr)
            archive = Path(out) / 'wizskills-records-v1.tar.gz'
            self.assertEqual(first.stdout.strip(), str(archive))
            again = Path(out) / 'again'
            again.mkdir()
            self.assertEqual(generate('archive', str(again)).returncode, 0)
            self.assertEqual(archive.read_bytes(), (again / archive.name).read_bytes())
            with tarfile.open(archive) as tar:
                names = sorted(m.name for m in tar.getmembers() if m.isfile())
                self.assertEqual(tar.extractfile('records/v1/index.json').read(),
                                 (FIXTURES / 'index.json').read_bytes())
        files = sorted('records/v1/' + p.relative_to(FIXTURES).as_posix()
                       for p in FIXTURES.rglob('*') if p.is_file())
        self.assertEqual(names, files)


if __name__ == '__main__':
    unittest.main()
