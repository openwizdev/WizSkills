#!/usr/bin/env python3
"""The pull request record, review comment, branch, and title."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ISSUE = Path(__file__).resolve().parents[2] / 'agent-issue'
SPEC = importlib.util.spec_from_file_location('agent_record_lint', ISSUE / 'scripts' / 'lint.py')
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


def pull(**updates):
    body = {
        'schema': 'agent-pr/1',
        'closes': '14',
        'intent': 'Reload the widget list after a successful save.',
        'changes': [{'acceptance': 'A1', 'change': 'The list reloads after a successful save.'}],
        'proof': [{
            'acceptance': 'A1',
            'command': 'python3 -m unittest tests/test_widgets.py',
            'result': 'pass',
            'red_first': True,
        }],
        'risk': 'low: list rendering only',
        'rollback': 'Revert the merge commit.',
        'owned_paths': ['src/widgets/list.py', 'tests/test_widgets.py'],
        'gates': [],
    }
    body.update(updates)
    return body


def fence(info, obj):
    return '```%s\n%s\n```\n' % (info, json.dumps(obj, indent=2))


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = lint.main(argv)
    raw = out.getvalue()
    data = json.loads(raw) if code != 2 else None
    return code, raw, data


def lint_pr(text, issue_text=None, mode=None):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        body = root / 'body.md'
        body.write_text(text, encoding='utf-8')
        argv = ['--json', 'pr', '--body-file', str(body)]
        if issue_text is not None:
            issue_path = root / 'issue.md'
            issue_path.write_text(issue_text, encoding='utf-8')
            argv.extend(['--issue-file', str(issue_path)])
        if mode:
            argv.extend(['--mode', mode])
        return run(argv)


def lint_review(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'review.md'
        path.write_text(text, encoding='utf-8')
        return run(['--json', 'review', '--body-file', str(path)])


def rules(data):
    return sorted(item['rule'] for item in data['findings'])


class PullRequestLint(unittest.TestCase):
    def test_templates_cross_check(self):
        code, raw, data = run([
            '--json', 'pr',
            '--body-file', str(HERE.parent / 'template.md'),
            '--issue-file', str(ISSUE / 'template.md'),
        ])
        self.assertEqual(code, 0, raw)
        self.assertTrue(data['ok'])

    def test_review_examples(self):
        for name in ('review-approve.md', 'review-changes.md'):
            code, raw, data = run(['--json', 'review', '--body-file', str(HERE.parent / 'examples' / name)])
            self.assertEqual(code, 0, raw)
            self.assertTrue(data['ok'])

    def test_branch_and_title(self):
        code, raw, data = run(['--json', 'branch', '--name', 'ada/widgets-14-build', '--repo', 'widgets', '--issue-id', '14'])
        self.assertEqual(code, 0, raw)
        code, raw, data = run(['--json', 'branch', '--name', 'ada/my-repo-14-fix', '--repo', 'my-repo', '--issue-id', '14'])
        self.assertEqual(code, 0, raw)
        _, _, data = run(['--json', 'branch', '--name', 'ada/widgets-14-Build'])
        self.assertEqual(rules(data), ['branch'])
        code, raw, data = run(['--json', 'title', '--title', '#14: Show saved widgets.', '--issue-id', '14',
                               '--expect', 'Show saved widgets.'])
        self.assertEqual(code, 0, raw)
        _, _, data = run(['--json', 'title', '--title', '14: Show saved widgets.', '--issue-id', '14'])
        self.assertEqual(rules(data), ['title'])
        _, _, data = run(['--json', 'title', '--title', '#14: Other widgets.', '--issue-id', '14',
                          '--expect', 'Show saved widgets.'])
        self.assertEqual(rules(data), ['title'])
        code, _, data = run(['--json', 'title', '--title', 'widget_list: Show saved widgets.',
                             '--issue-id', 'widget_list', '--expect', 'Show saved widgets.'])
        self.assertEqual(code, 0, data)

    def test_review_protocol(self):
        approve = (HERE.parent / 'examples' / 'review-approve.md').read_text(encoding='utf-8')
        _, _, data = lint_review(approve.replace('nit', 'blocking'))
        self.assertIn('verdict', rules(data))
        changes = (HERE.parent / 'examples' / 'review-changes.md').read_text(encoding='utf-8')
        _, _, data = lint_review(changes.replace('blocking', 'nit'))
        self.assertIn('verdict', rules(data))
        _, _, data = lint_review(approve.replace('VERDICT: APPROVE at abc1234', 'VERDICT: APPROVE at abc1235'))
        self.assertIn('verdict', rules(data))
        empty = 'Review #15 at abc1234\n\nVERDICT: APPROVE at abc1234\n'
        code, _, data = lint_review(empty)
        self.assertEqual(code, 0, data)

    def test_cross_check(self):
        good_issue = fence('agent-issue', issue())
        _, _, data = lint_pr(fence('agent-pr', pull(owned_paths=['src/other/list.py'])), good_issue)
        self.assertEqual(rules(data), ['owned_paths'])
        exact = fence('agent-issue', issue(owned_paths=['src/widgets', 'tests/test_widgets.py']))
        _, _, data = lint_pr(fence('agent-pr', pull()), exact)
        self.assertEqual(rules(data), ['owned_paths'])
        _, _, data = lint_pr(fence('agent-pr', pull()), fence('agent-issue', issue(gates=['migration'])))
        self.assertEqual(rules(data), ['gates'])
        proof = pull()['proof']
        proof[0]['red_first'] = False
        _, _, data = lint_pr(fence('agent-pr', pull(proof=proof)), good_issue)
        self.assertEqual(rules(data), ['proof'])
        proof[0]['red_first'] = True
        proof[0]['command'] = 'python3 -m unittest tests/test_other.py'
        _, _, data = lint_pr(fence('agent-pr', pull(proof=proof)), good_issue)
        self.assertEqual(rules(data), ['proof'])
        held = fence('agent-issue', issue(ready='blocked', depends=['3']))
        _, _, data = lint_pr(fence('agent-pr', pull()), held)
        self.assertEqual(rules(data), ['ready'])

    def test_draft_and_ready_results(self):
        proof = pull()['proof']
        proof[0]['result'] = 'fail'
        code, _, data = lint_pr(fence('agent-pr', pull(proof=proof)), mode='draft')
        self.assertEqual(code, 0, data)
        _, _, data = lint_pr(fence('agent-pr', pull(proof=proof)))
        self.assertEqual(rules(data), ['proof'])

    def test_spec_states_the_protocol(self):
        text = (HERE.parent / 'spec.md').read_text(encoding='utf-8')
        self.assertIn('<agent>/<repo>-<N>-<lane>', text)
        self.assertIn('APPROVE', text)
        self.assertIn('CHANGES', text)
        self.assertIn('blocking', text)
        self.assertIn('nit', text)


if __name__ == '__main__':
    unittest.main()
