#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
PROBE = (
    'import importlib.util, pathlib, sys\n'
    'base = pathlib.Path(sys.argv[1])\n'
    'targets = [base / arg for arg in sys.argv[2:]]\n'
    'failures = []\n'
    'for index, path in enumerate(targets):\n'
    '    parent = str(path.parent)\n'
    '    added = parent not in sys.path\n'
    '    if added:\n'
    '        sys.path.insert(0, parent)\n'
    '    try:\n'
    '        spec = importlib.util.spec_from_file_location(f"packaged_script_{index}", path)\n'
    '        module = importlib.util.module_from_spec(spec)\n'
    '        spec.loader.exec_module(module)\n'
    '    except BaseException as exc:\n'
    '        failures.append(f"{path.relative_to(base)}: {type(exc).__name__}: {exc}")\n'
    '    finally:\n'
    '        if added and parent in sys.path:\n'
    '            sys.path.remove(parent)\n'
    'if failures:\n'
    '    sys.stderr.write("\\n".join(failures) + "\\n")\n'
    '    sys.exit(1)\n'
)


def installed_scripts(base):
    return sorted(
        path.relative_to(base).as_posix()
        for path in base.glob('skills/*/scripts/**/*.py')
        if 'fixtures' not in path.parts
        and 'evidence' not in path.parts
        and not path.name.startswith(('test_', 'test-'))
    )


def stage_packaged_tree(dest, include_contracts=True):
    shutil.copytree(ROOT / 'skills', dest / 'skills')
    if include_contracts:
        shutil.copytree(ROOT / 'contracts', dest / 'contracts')
    (dest / '.claude-plugin').mkdir()
    shutil.copy2(ROOT / '.claude-plugin/plugin.json', dest / '.claude-plugin/plugin.json')


class PackagedScriptImports(unittest.TestCase):
    def test_every_installed_script_imports_against_the_packaged_tree(self):
        with tempfile.TemporaryDirectory(prefix='wizskills-packaged-imports-') as tmp:
            tree = Path(tmp)
            stage_packaged_tree(tree, include_contracts=True)
            scripts = installed_scripts(tree)
            self.assertIn('skills/launch-fleet/scripts/post.py', scripts)
            result = subprocess.run([sys.executable, '-I', '-c', PROBE, str(tree), *scripts],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_ops_dispatch_schema_fails_importing_post(self):
        with tempfile.TemporaryDirectory(prefix='wizskills-packaged-missing-') as tmp:
            tree = Path(tmp)
            stage_packaged_tree(tree, include_contracts=True)
            (tree / 'contracts/ops-dispatch.v1.schema.json').unlink()
            result = subprocess.run([sys.executable, '-I', '-c', PROBE, str(tree),
                                     'skills/launch-fleet/scripts/post.py'],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FileNotFoundError', result.stderr)
            self.assertIn('contracts/ops-dispatch.v1.schema.json', result.stderr)


if __name__ == '__main__':
    unittest.main()
