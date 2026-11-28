#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent.parent
NON_INSTALLED_DIRS = frozenset({'test', 'tests', 'fixtures', 'evidence'})
SYNTHETIC_OLD_SPEC = json.dumps({
    'body': '# Synthetic Spec\n\nNo checkpoints section.\n',
    'createdAt': '2026-01-01T00:00:00Z',
})


def is_installed_python_script(rel):
    parts = rel.split('/')
    if not rel.endswith('.py') or len(parts) < 3 or parts[0] != 'skills':
        return False
    if any(part in NON_INSTALLED_DIRS for part in parts[2:-1]):
        return False
    name = parts[-1]
    return not (name.startswith('test_') or name.startswith('test-'))


def installed_python_scripts(root):
    return sorted(
        path.relative_to(root).as_posix()
        for path in (root / 'skills').rglob('*.py')
        if path.is_file() and not path.is_symlink()
        and is_installed_python_script(path.relative_to(root).as_posix())
    )


def stage_packaged_tree(source, dest, *, omit_contracts=()):
    omitted = set(omit_contracts)
    shutil.copytree(source / 'skills', dest / 'skills')
    shutil.copytree(source / 'contracts', dest / 'contracts')
    for rel in omitted:
        target = dest / rel
        if target.exists():
            target.unlink()
    plugin_dir = dest / '.claude-plugin'
    plugin_dir.mkdir()
    shutil.copy2(source / '.claude-plugin' / 'plugin.json', plugin_dir / 'plugin.json')


def probe_import(pkg_root, rel_path):
    target = pkg_root / rel_path
    code = (
        'import importlib.util, json, pathlib, sys\n'
        'sys.dont_write_bytecode = True\n'
        f'target = pathlib.Path({str(target)!r})\n'
        'sys.path.insert(0, str(target.parent))\n'
        "spec = importlib.util.spec_from_file_location('wiz_packaged_probe', target)\n"
        'mod = importlib.util.module_from_spec(spec)\n'
        'spec.loader.exec_module(mod)\n'
        'contract = getattr(mod, "CONTRACT", None)\n'
        'if isinstance(contract, pathlib.Path):\n'
        '    print(json.dumps({"contract": str(contract)}))\n'
    )
    return subprocess.run(
        [sys.executable, '-I', '-c', code],
        cwd=str(pkg_root),
        capture_output=True,
        text=True,
        timeout=30,
    )


class PackagedScriptsTest(unittest.TestCase):
    def test_every_installed_python_script_imports_against_the_packaged_tree(self):
        scripts = installed_python_scripts(ROOT)
        self.assertIn('skills/launch-fleet/scripts/post.py', scripts)
        self.assertIn('skills/launch-fleet/scripts/effects.py', scripts)
        self.assertIn('skills/launch-fleet/scripts/merge.py', scripts)
        self.assertIn('skills/write-driver/scripts/write_driver.py', scripts)

        with tempfile.TemporaryDirectory(prefix='wizskills-packaged-') as tmp:
            pkg = Path(tmp) / 'packaged'
            stage_packaged_tree(ROOT, pkg)
            failures = []
            contract_paths = {}
            for rel in scripts:
                result = probe_import(pkg, rel)
                if result.returncode != 0:
                    failures.append(f'{rel}: exit {result.returncode}\n{result.stderr.strip()}')
                    continue
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line.startswith('{'):
                        data = json.loads(line)
                        if 'contract' in data:
                            contract_paths[rel] = Path(data['contract'])
            self.assertEqual(failures, [], '\n\n'.join(failures))
            self.assertIn('skills/launch-fleet/scripts/merge.py', contract_paths)
            self.assertIn('skills/write-driver/scripts/write_driver.py', contract_paths)
            for rel, contract_path in sorted(contract_paths.items()):
                with self.subTest(script=rel, contract=str(contract_path)):
                    self.assertTrue(
                        contract_path.is_file(),
                        f'{rel} CONTRACT missing in packaged tree: {contract_path}',
                    )
                    self.assertTrue(
                        contract_path.resolve().is_relative_to(pkg.resolve()),
                        f'{rel} CONTRACT escapes packaged tree: {contract_path}',
                    )

    def test_installed_check_approval_reads_packaged_checkpoints_contract(self):
        with tempfile.TemporaryDirectory(prefix='wizskills-packaged-') as tmp:
            pkg = Path(tmp) / 'packaged'
            stage_packaged_tree(ROOT, pkg)
            checker = pkg / 'skills/to-tickets/scripts/check-approval.sh'
            result = subprocess.run(
                ['sh', str(checker), '--checkpoints', '7'],
                cwd=str(pkg),
                input=SYNTHETIC_OLD_SPEC,
                capture_output=True,
                text=True,
                timeout=30,
                env={'PATH': os.environ.get('PATH', ''), 'HOME': tmp},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('#7 checkpoint answers are valid', result.stdout)

    def test_missing_ops_dispatch_schema_fails_post_import(self):
        with tempfile.TemporaryDirectory(prefix='wizskills-packaged-') as tmp:
            pkg = Path(tmp) / 'packaged'
            stage_packaged_tree(ROOT, pkg, omit_contracts=('contracts/ops-dispatch.v1.schema.json',))
            result = probe_import(pkg, 'skills/launch-fleet/scripts/post.py')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FileNotFoundError', result.stderr)
            self.assertIn('contracts/ops-dispatch.v1.schema.json', result.stderr)

    def test_missing_checkpoints_contract_fails_check_approval(self):
        with tempfile.TemporaryDirectory(prefix='wizskills-packaged-') as tmp:
            pkg = Path(tmp) / 'packaged'
            stage_packaged_tree(ROOT, pkg, omit_contracts=('contracts/checkpoints.v1.md',))
            checker = pkg / 'skills/to-tickets/scripts/check-approval.sh'
            result = subprocess.run(
                ['sh', str(checker), '--checkpoints', '7'],
                cwd=str(pkg),
                input=SYNTHETIC_OLD_SPEC,
                capture_output=True,
                text=True,
                timeout=30,
                env={'PATH': os.environ.get('PATH', ''), 'HOME': tmp},
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('contracts/checkpoints.v1.md', result.stderr)


if __name__ == '__main__':
    unittest.main()
