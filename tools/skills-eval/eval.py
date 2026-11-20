#!/usr/bin/env python3
"""Skills eval command line (contract.md). Standard library only.

  eval.py check                          cases, coverage, provenance, required text, controls (offline)
  eval.py coverage                       the skill-to-case map (offline)
  eval.py run --out DIR [--rev REV]      paid role runs; resumable; needs OPENROUTER_API_KEY
  eval.py score DIR                      score a results set; exit 0 only if every case passed every repeat
  eval.py compare A B                    compare two scored sets with equal settings and cases hashes
  eval.py tokens --out FILE [--rev REV] [--offline]
  eval.py token-diff BEFORE AFTER
"""
import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cases as C  # noqa: E402
import driver  # noqa: E402
import score as S  # noqa: E402
import tokens as T  # noqa: E402

REPO = HERE.parent.parent
CODE = ['contract.md', 'fakeworld.py', 'score.py', 'records.py', 'cases.py', 'driver.py', 'tokens.py', 'eval.py']


def git(*args):
    return subprocess.run(['git', '-C', str(REPO), *args], check=True, capture_output=True).stdout


def snapshot(rev):
    """Read-only (read, list) over one commit; harness side, never the agent's."""
    names = git('ls-tree', '-r', '--name-only', rev).decode().splitlines()
    cache = {}
    nameset = set(names)

    def read(p):
        if p not in nameset:
            return None
        if p not in cache:
            try:
                cache[p] = git('cat-file', 'blob', f'{rev}:{p}').decode()
            except (UnicodeDecodeError, subprocess.CalledProcessError):
                cache[p] = None
        return cache[p]

    def lst(prefix):
        return [n for n in names if n.startswith(prefix)]
    return read, lst


def revision(rev):
    commit = git('rev-parse', rev).decode().strip()
    tree = git('rev-parse', f'{commit}^{{tree}}').decode().strip()
    return {'commit': commit, 'tree': tree}


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def code_hash():
    h = hashlib.sha256()
    for n in CODE:
        h.update(n.encode() + b'\0' + (HERE / n).read_bytes())
    return h.hexdigest()


def shipped(read):
    plugin = json.loads(read('.claude-plugin/plugin.json'))
    return [p.rsplit('/', 1)[-1] for p in plugin['skills']]


def coverage(all_cases, skills):
    out = {s: {k: [] for k in sorted(C.CATEGORIES)} for s in skills}
    for c in all_cases:
        for s in c['skills']:
            if s in out:
                out[s][c['category']].append(c['id'])
    return out


def check(read, lst, folder=HERE / 'cases'):
    errs = []
    skills = shipped(read)
    schema = json.loads(read('contracts/decisions.v1.schema.json'))
    all_cases = []
    for p in sorted(Path(folder).glob('*.json')):
        try:
            c = json.loads(p.read_text())
        except ValueError as e:
            errs.append(f'{p.name}: {e}')
            continue
        all_cases.append(c)
        errs += C.problems(c, skills, p.name)
    ids = [c.get('id') for c in all_cases]
    if len(ids) != len(set(ids)):
        errs.append('duplicate case ids')
    for c in all_cases:
        if C.problems(c, skills):
            continue
        for kind in ('pass', 'fail'):
            for j, ctl in enumerate(c['controls'][kind]):
                ok, reasons, details = S.score(c, C.control_transcript(c, ctl), schema)
                if kind == 'pass' and not ok:
                    errs.append(f"{c['id']}: pass control {j} fails: {reasons} {details}")
                if kind == 'fail' and (ok or ctl['reason'] not in reasons):
                    errs.append(f"{c['id']}: fail control {j} gives {reasons}, wants {ctl['reason']}")
    cov = coverage(all_cases, skills)
    prov = json.loads((HERE / 'provenance.json').read_text())
    na = prov.get('not_applicable', {})
    for s, cats in cov.items():
        if not cats['workflow']:
            errs.append(f'{s}: no workflow case')
        for k in ('approval', 'privacy', 'failure'):
            reason = (na.get(s) or {}).get(k)
            if not cats[k] and not (isinstance(reason, str) and reason.strip()):
                errs.append(f'{s}: no {k} case and no not-applicable reason')
            if cats[k] and reason:
                errs.append(f'{s}: {k} is covered and also listed not applicable')
    if sorted(prov['cases']) != sorted(ids):
        errs.append(f"provenance cases {sorted(set(prov['cases']) ^ set(ids))} do not match the case files")
    for cid, src in prov['cases'].items():
        if cid.startswith('i') and cid[1:2].isdigit():
            if not src.get('links') or not all(l.startswith('https://github.com/') for l in src['links']):
                errs.append(f'{cid}: an incident needs its GitHub links')
        elif not src.get('rule'):
            errs.append(f'{cid}: a rule case needs its skill file and line')
    incidents = [c for c in all_cases if c['category'] == 'incident']
    if len(incidents) < 5:
        errs.append(f'{len(incidents)} incident cases; the five seeds are required')
    errs += T.map_problems(T.load_map(HERE / 'required-text.json'), skills, read, lst)
    return errs, all_cases, cov


def cmd_check(a):
    read, lst = snapshot(a.rev)
    errs, all_cases, _ = check(read, lst)
    for e in errs:
        print('FAIL', e)
    print(f"{'PASS' if not errs else 'FAIL'}: {len(all_cases)} cases, {len(errs)} problems")
    return 0 if not errs else 1


def cmd_coverage(a):
    read, lst = snapshot(a.rev)
    _, _, cov = check(read, lst)
    print(json.dumps(cov, indent=1))
    return 0


def _key(a, settings=None):
    if settings is None:
        settings = json.loads((HERE / 'settings.json').read_text())
    if settings.get('provider') == 'hermes':  # no API key: the machine's Hermes Nous login, checked offline
        problem = driver.hermes_login_problem(settings)
        if problem:
            sys.exit(f'Hermes runs are recorded as not run: {problem}')
        return None
    key = os.environ.get('OPENROUTER_API_KEY')
    if not key and a.env_file and Path(a.env_file).exists():
        for line in Path(a.env_file).read_text().splitlines():
            if line.startswith('OPENROUTER_API_KEY='):
                key = line.split('=', 1)[1].strip().strip('"\'')
    if not key:
        sys.exit('no OPENROUTER_API_KEY: paid runs are recorded as not run (contract.md, section 6)')
    return key


def cmd_run(a):
    settings = json.loads((HERE / 'settings.json').read_text())
    _key(a, settings)  # fail before creating results when the key is absent
    snap = snapshot(a.rev)
    errs, all_cases, _ = check(*snap)
    if errs:
        sys.exit(f'refusing to run: eval.py check has {len(errs)} problems')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    lock = os.open(out, os.O_RDONLY)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('results folder is already running; refusing concurrent spend')
        return run_locked(a, settings, snap, all_cases, out)
    finally:
        os.close(lock)


def write_json(path, value):
    """Durable replacement: the reservation must reach disk before a paid attempt."""
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as f:
        f.write(json.dumps(value, indent=1) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def run_locked(a, settings, snap, all_cases, out):
    manifest = {'schema': 'openwiz.skills-eval.results.v1', 'settings': settings, 'settings_hash': sha(settings),
                'cases_hash': C.cases_hash(), 'revision': revision(a.rev), 'code_hash': code_hash(),
                'cases': [c['id'] for c in all_cases], 'repeats': settings['repeats']}
    mf = out / 'manifest.json'
    if mf.exists():
        old = json.loads(mf.read_text())
        errs = manifest_problems(old)
        for k in ('settings_hash', 'cases_hash', 'revision', 'code_hash', 'cases', 'repeats'):
            if old.get(k) != manifest[k]:
                errs.append(f'{k} differs')
        if errs:
            sys.exit(f"refusing to resume {mf}: {'; '.join(errs)}; start a new results set")
    else:
        write_json(mf, manifest)
    only = set(a.case or [])
    for rep in range(1, settings['repeats'] + 1):
        for c in all_cases:
            if only and c['id'] not in only:
                continue
            f = out / f"{c['id']}.r{rep}.json"
            if f.exists():
                continue
            spent = sum(json.loads(p.read_text()).get('cost_usd', 0) for p in out.glob('*.r*.json'))
            post = driver.http_post(_key(a, settings), settings.get('provider', settings['api_version']))
            t = driver.run_case(c, settings, snap, post, rep, budget_usd=settings['spend_cap_usd'] - spent,
                                checkpoint=lambda interim: write_json(f, interim))
            write_json(f, t)
            print(f"{c['id']} r{rep}: stop={t['stop']} turns={t['turns']} ${t['cost_usd']:.3f}", flush=True)
            if t['stop'] == 'cap':
                print(f"spend cap ${settings['spend_cap_usd']} reached (${spent + t['cost_usd']:.2f}); this run is kept as incomplete; stopping")
                return 3
    return 0


def manifest_problems(man):
    """A results set's manifest must describe exactly the current suite, settings and code."""
    errs = []
    if not isinstance(man, dict):
        return ['the manifest is not an object']
    settings, ids = man.get('settings'), sorted(c['id'] for c in C.load_all())
    if not isinstance(settings, dict) or sha(settings) != man.get('settings_hash'):
        errs.append('the settings do not match their recorded hash')
    rep = man.get('repeats')
    if type(rep) is not int or rep < 1 or not isinstance(settings, dict) or rep != settings.get('repeats'):
        errs.append('repeats must be a positive integer equal to the settings\' repeats')
    if not isinstance(man.get('cases'), list) or sorted(man['cases']) != ids:
        errs.append('the case list is not exactly the current cases, each once')
    if man.get('cases_hash') != C.cases_hash() or man.get('code_hash') != code_hash():
        errs.append('the cases or the eval code changed since this set ran: score it at its own commit, or take a fresh baseline')
    if not isinstance(man.get('revision'), dict) or not man['revision'].get('commit'):
        errs.append('no revision')
    return errs


def score_set(folder):
    """Score a results set with the cases, code, settings and schema it ran with, or refuse."""
    folder = Path(folder)
    man = json.loads((folder / 'manifest.json').read_text())
    errs = manifest_problems(man)
    if errs:
        raise ValueError('; '.join(errs))
    schema_text = snapshot(man['revision']['commit'])[0]('contracts/decisions.v1.schema.json')
    schema = json.loads(schema_text)
    by_id = {c['id']: c for c in C.load_all()}
    rows, ok_all = [], True
    for cid in man['cases']:
        for rep in range(1, man['repeats'] + 1):
            f = folder / f'{cid}.r{rep}.json'
            if cid not in by_id:
                rows.append({'case': cid, 'repeat': rep, 'pass': False, 'reasons': ['incomplete'], 'details': ['case file missing']})
                ok_all = False
                continue
            try:
                t = json.loads(f.read_text())
            except (OSError, ValueError):
                rows.append({'case': cid, 'repeat': rep, 'pass': False, 'reasons': ['incomplete'], 'details': ['not run or unreadable']})
                ok_all = False
                continue
            if not isinstance(t, dict) or t.get('case') != cid or type(t.get('repeat')) is not int or t['repeat'] != rep:
                rows.append({'case': cid, 'repeat': rep, 'pass': False, 'reasons': ['incomplete'],
                             'details': ['the transcript names another case or repeat']})
                ok_all = False
                continue
            ok, reasons, details = S.score(by_id[cid], t, schema)
            ok_all &= ok
            rows.append({'case': cid, 'repeat': rep, 'pass': ok, 'reasons': reasons, 'details': details,
                         'cost_usd': t.get('cost_usd'), 'stop': t.get('stop')})
    return {'schema': 'openwiz.skills-eval.score.v1', 'settings_hash': man['settings_hash'],
            'cases_hash': man['cases_hash'], 'revision': man['revision'], 'code_hash': man['code_hash'],
            'schema_hash': hashlib.sha256(schema_text.encode()).hexdigest(),
            'suite_pass': ok_all, 'runs': len(rows), 'passed': sum(r['pass'] for r in rows),
            'cost_usd': round(sum(r.get('cost_usd') or 0 for r in rows), 9), 'rows': rows}


def cmd_score(a):
    try:
        s = score_set(a.dir)
    except ValueError as err:
        print(f'refused: {err}')
        return 2
    Path(a.dir, 'score.json').write_text(json.dumps(s, indent=1) + '\n')
    print(f"suite {'PASS' if s['suite_pass'] else 'FAIL'}: {s['passed']}/{s['runs']} runs passed, ${s['cost_usd']}")
    return 0 if s['suite_pass'] else 1


def compare(a, b):
    for k in ('settings_hash', 'cases_hash', 'code_hash', 'schema_hash'):
        if a.get(k) is None or a.get(k) != b.get(k):
            raise ValueError(f'{k} differs: not comparable; take a fresh baseline')
    pa = {(r['case'], r['repeat']): r['pass'] for r in a['rows']}
    pb = {(r['case'], r['repeat']): r['pass'] for r in b['rows']}
    return {'before': f"{a['passed']}/{a['runs']}", 'after': f"{b['passed']}/{b['runs']}",
            'fixed': sorted({k[0] for k in pb if pb[k] and not pa.get(k)}),
            'broken': sorted({k[0] for k in pb if not pb[k] and pa.get(k)})}


def cmd_compare(a):
    try:
        r = compare(*(json.loads(Path(x, 'score.json').read_text()) for x in (a.a, a.b)))
    except ValueError as e:
        print(f'refused: {e}')
        return 2
    print(json.dumps(r, indent=1))
    return 0


def cmd_tokens(a):
    settings = json.loads((HERE / 'settings.json').read_text())
    if not a.offline:
        if not a.results:
            sys.exit('DeepSeek tokens need --results DIR: provider usage, not a Claude tokenizer or text estimate')
        r = T.usage_report(a.results)
        Path(a.out).write_text(json.dumps(r, indent=1) + '\n')
        print(f"DeepSeek provider tokens (not Claude tokens): {r['total']}")
        return 0
    read, lst = snapshot(a.rev)
    m = T.load_map(HERE / 'required-text.json')
    errs = T.map_problems(m, shipped(read), read, lst)
    if errs:
        sys.exit('\n'.join(errs))
    count, tok = None, 'none (offline: bytes only, never reported as tokens)'
    r = T.report(m, read, count, tok, revision(a.rev), lst)
    import datetime
    r['measured_at'] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    Path(a.out).write_text(json.dumps(r, indent=1) + '\n')
    print(f"total required: {r['total_required_tokens']} tokens, {r['total_required_bytes']} bytes ({tok})")
    return 0


def cmd_token_diff(a):
    try:
        r = T.diff(*(json.loads(Path(x).read_text()) for x in (a.before, a.after)))
    except ValueError as e:
        print(f'refused: {e}')
        return 2
    print(json.dumps(r, indent=1))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('check', 'coverage', 'run', 'score', 'tokens'):
        q = sub.add_parser(name)
        q.add_argument('--rev', default='HEAD', help='the snapshot commit (default HEAD)')
        q.add_argument('--env-file', default=None, help='a dotenv file holding OPENROUTER_API_KEY')
        if name == 'run':
            q.add_argument('--out', required=True)
            q.add_argument('--case', action='append', help='only this case (repeatable)')
        if name == 'score':
            q.add_argument('dir')
        if name == 'tokens':
            q.add_argument('--out', required=True)
            q.add_argument('--offline', action='store_true')
            q.add_argument('--results', help='results folder whose provider usage is reported; makes no API call')
    q = sub.add_parser('compare')
    q.add_argument('a')
    q.add_argument('b')
    q = sub.add_parser('token-diff')
    q.add_argument('before')
    q.add_argument('after')
    a = p.parse_args(argv)
    return {'check': cmd_check, 'coverage': cmd_coverage, 'run': cmd_run, 'score': cmd_score,
            'compare': cmd_compare, 'tokens': cmd_tokens, 'token-diff': cmd_token_diff}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
