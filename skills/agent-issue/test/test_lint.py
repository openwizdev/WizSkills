#!/usr/bin/env python3
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('agent_record_lint', SKILL / 'scripts' / 'lint.py')
lint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint)


def issue(**updates):
    body = {
        'schema': 'agent-issue/1',
        'id': '14',
        'kind': 'bug',
        'goal': 'The widget list stays empty after a successful save.',
        'summary': 'Show saved widgets.',
        'acceptance': [{'id': 'A1', 'check': 'python3 -m unittest tests/test_widgets.py'}],
        'owned_paths': ['src/widgets/', 'tests/test_widgets.py'],
        'out_of_scope': ['Changing the save API.'],
        'depends': [],
        'blocks': [],
        'risk': 'low: list rendering only',
        'gates': [],
        'effort': 'small',
        'ready': 'ready-for-agent',
        'context': ['https://example.com/widgets'],
    }
    body.update(updates)
    return body


def fence(info, obj):
    return '```%s\n%s\n```\n' % (info, json.dumps(obj, indent=2))


def run(argv, parse_json=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = lint.main(argv)
    raw = out.getvalue()
    want_json = ('--json' in argv) if parse_json is None else parse_json
    data = json.loads(raw) if want_json and code != 2 else None
    return code, raw, data


def lint_body(text, *extra):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'body.md'
        path.write_text(text, encoding='utf-8')
        return run(['--json', 'issue', '--body-file', str(path), *extra])


def rules(data):
    return sorted(item['rule'] for item in data['findings'])


class IssueLint(unittest.TestCase):
    def test_template_and_text_mode(self):
        code, raw, data = run(['--json', 'issue', '--body-file', str(SKILL / 'template.md')])
        self.assertEqual(code, 0, raw)
        self.assertTrue(data['ok'])
        code, raw, _ = run(['issue', '--body-file', str(SKILL / 'template.md')])
        self.assertEqual(code, 0)
        self.assertEqual(raw, 'agent-record: ok\n')

    def test_missing_goal_example_fails_on_goal_only(self):
        code, raw, data = run(['--json', 'issue', '--body-file', str(SKILL / 'examples' / 'missing-goal.md')])
        self.assertEqual(code, 1, raw)
        self.assertEqual(rules(data), ['goal'])
        self.assertEqual(data['findings'][0]['message'], 'missing')

    def test_usage_and_help(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = lint.main([])
        self.assertEqual(code, 2)
        self.assertIn('usage:', err.getvalue())
        code, raw, _ = run(['--help'])
        self.assertEqual(code, 0)
        self.assertIn('issue', raw)

    def test_fence_shape(self):
        code, _, data = lint_body('---\nid: "14"\n---\n')
        self.assertEqual(rules(data), ['fence'])
        code, _, data = lint_body(fence('agent-issue', issue()) + fence('agent-issue', issue()))
        self.assertIn('fence', rules(data))
        code, _, data = lint_body('```agent-issue\n{"schema": "agent-issue/1"}\n')
        self.assertEqual(data['findings'][0]['message'], 'fence is not closed')
        self.assertEqual(code, 1)

    def test_duplicate_and_unknown_keys(self):
        text = '```agent-issue\n{"schema": "agent-issue/1", "schema": "agent-issue/1"}\n```\n'
        _, _, data = lint_body(text)
        self.assertEqual(data['findings'][0]['rule'], 'json')
        self.assertIn('duplicate key', data['findings'][0]['message'])
        body = issue()
        body['owner'] = 'ada'
        _, _, data = lint_body(fence('agent-issue', body))
        self.assertIn('keys', rules(data))

    def test_goal_must_be_one_sentence(self):
        body = issue(goal='The list stays empty. The save still works.')
        _, _, data = lint_body(fence('agent-issue', body))
        self.assertEqual(rules(data), ['goal'])
        body = issue()
        body['acceptance'] = [{'id': 'A1', 'check': 'Run the tests.'}]
        _, _, data = lint_body(fence('agent-issue', body))
        self.assertEqual(rules(data), ['acceptance'])

    def test_ready_depends_and_effort(self):
        _, _, blocked = lint_body(fence('agent-issue', issue(ready='blocked', depends=['3'])))
        self.assertTrue(blocked['ok'], blocked)
        _, _, data = lint_body(fence('agent-issue', issue(ready='blocked', depends=[])))
        self.assertEqual(rules(data), ['ready'])
        _, _, data = lint_body(fence('agent-issue', issue(depends=['3'])))
        self.assertEqual(rules(data), ['ready'])
        _, _, waiting = lint_body(fence('agent-issue', issue(ready='needs-grill', depends=['3'])))
        self.assertTrue(waiting['ok'], waiting)
        _, _, data = lint_body(fence('agent-issue', issue(effort='large')))
        self.assertEqual(rules(data), ['effort'])

    def test_gates_paths_and_ids(self):
        _, _, data = lint_body(fence('agent-issue', issue(gates=['publish'])))
        self.assertEqual(rules(data), ['gates'])
        _, _, data = lint_body(fence('agent-issue', issue(owned_paths=['../secrets/'])))
        self.assertEqual(rules(data), ['owned_paths'])
        _, _, data = lint_body(fence('agent-issue', issue(id='my-issue')))
        self.assertEqual(rules(data), ['id'])
        _, _, data = lint_body(fence('agent-issue', issue(depends=['14'], blocks=['14'])))
        self.assertEqual(rules(data), ['blocks', 'depends', 'ready'])
        body = issue()
        body['acceptance'] = [
            {'id': 'A1', 'check': 'python3 -m unittest tests/test_widgets.py'},
            {'id': 'A2', 'check': 'python3 -m unittest tests/test_widgets.py'},
        ]
        _, _, data = lint_body(fence('agent-issue', body))
        self.assertEqual(rules(data), ['acceptance'])
        _, _, data = lint_body(fence('agent-issue', issue(context=['https://user:pass@example.com/widgets'])))
        self.assertEqual(rules(data), ['context'])

    def test_secret_is_not_echoed(self):
        token = 'ghp_' + ('a' * 20)
        body = issue(goal='The widget list leaks %s today.' % token)
        _, raw, data = lint_body(fence('agent-issue', body))
        self.assertFalse(data['ok'])
        self.assertNotIn(token, raw)
        self.assertNotIn('ghp_', raw)

    def test_prose_limit_and_crlf(self):
        _, _, data = lint_body('one\ntwo\nthree\nfour\n' + fence('agent-issue', issue()))
        self.assertIn('prose', rules(data))
        code, _, data = lint_body(fence('agent-issue', issue()).replace('\n', '\r\n'))
        self.assertEqual(code, 0, data)
        self.assertTrue(data['ok'])

    def test_spec_names_every_enum(self):
        text = (SKILL / 'spec.md').read_text(encoding='utf-8')
        for word in lint.KINDS + lint.READIES + lint.EFFORTS + lint.GATES:
            self.assertIn('`' + word + '`', text)

    def test_gates_rejects_unhashable_items(self):
        for bad in ([{'name': 'release'}], [['release']], ['release', 'release']):
            code, raw, data = lint_body(fence('agent-issue', issue(gates=bad)))
            self.assertEqual(code, 1, raw)
            self.assertEqual(rules(data), ['gates'])
        code, raw, data = lint_body(fence('agent-issue', issue(gates=['release'])))
        self.assertEqual(code, 0, raw)
        self.assertTrue(data['ok'])

    def test_paths_allow_spaces(self):
        body = issue(
            owned_paths=['docs/Getting Started.md', 'docs/User Guides/'],
            context=['docs/Getting Started.md'],
        )
        code, raw, data = lint_body(fence('agent-issue', body))
        self.assertEqual(code, 0, raw)
        self.assertTrue(data['ok'])
        for bad in ('docs/ /bad.md', 'docs/ bad.md', 'docs/bad /file.md', 'docs/Getting\tStarted.md'):
            code, raw, data = lint_body(fence('agent-issue', issue(owned_paths=[bad])))
            self.assertEqual(code, 1, raw)
            self.assertEqual(rules(data), ['owned_paths'])

    def test_record_inside_surrounding_fence_is_ignored(self):
        inner = fence('agent-issue', issue())
        for wrapped in (
            '````markdown\n' + inner + '````\n',
            '~~~markdown\n' + inner + '~~~\n',
            '  ````markdown\n' + inner + '  ````\n',
        ):
            code, raw, data = lint_body(wrapped)
            self.assertEqual(code, 1, raw)
            self.assertIn('fence', rules(data))
        inline_prose = '```agent-issue``` is the fence.\n' + inner
        code, raw, data = lint_body(inline_prose)
        self.assertEqual(code, 0, raw)
        self.assertTrue(data['ok'])

    def test_switches_only_in_option_positions(self):
        for flag in ('--help', '-h'):
            code, raw, data = run([
                '--json', 'title', '--title', '#14: wrong', '--issue-id', '14', '--expect', flag,
            ])
            self.assertEqual(code, 1, raw)
            self.assertEqual(rules(data), ['title'])
            code, raw, data = run([
                '--json', 'title', '--title', '#14: ' + flag, '--issue-id', '14', '--expect', flag,
            ])
            self.assertEqual(code, 0, raw)
            self.assertTrue(data['ok'])
        code, raw, data = run([
            '--json', 'title', '--title', '--help', '--issue-id', '14', '--expect', '--help',
        ])
        self.assertEqual(code, 1, raw)
        self.assertEqual(rules(data), ['title'])
        code, raw, _ = run([
            'title', '--title', '#14: --json', '--issue-id', '14', '--expect', '--json',
        ], parse_json=False)
        self.assertEqual(code, 0, raw)
        self.assertEqual(raw, 'agent-record: ok\n')
        code, raw, data = run([
            'title', '--title', '#14: --json', '--issue-id', '14', '--expect', '--json', '--json',
        ], parse_json=True)
        self.assertEqual(code, 0, raw)
        self.assertTrue(data['ok'])
        code, raw, _ = run(['issue', '--help'], parse_json=False)
        self.assertEqual(code, 0, raw)
        self.assertIn('usage:', raw)


if __name__ == '__main__':
    unittest.main()
