import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wizskills_run', HERE / 'run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)


def listed(name):
    return [command[-1] for command in run.SUITES.get(name, [])]


class CheckSuites(unittest.TestCase):
    def test_every_check_test_runs_in_the_check_suite(self):
        tests = sorted(p.relative_to(HERE.parent).as_posix() for p in HERE.glob('test*.py'))
        self.assertIn('check/test_notice.py', tests)
        self.assertEqual(sorted(listed('check')), tests)

    def test_an_unlisted_check_test_fails_the_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'check').mkdir()
            (root / 'check' / 'test_synthetic.py').write_text('', encoding='utf-8')
            (root / 'skills').mkdir()
            out = io.StringIO()
            saved = run.SUITES
            run.SUITES = {}
            try:
                with contextlib.redirect_stdout(out):
                    ok = run.suites(root)
            finally:
                run.SUITES = saved
        self.assertFalse(ok)
        self.assertIn('suite inventory: check/test_synthetic.py: unlisted', out.getvalue())


if __name__ == '__main__':
    unittest.main()
