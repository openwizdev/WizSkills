#!/usr/bin/env python3
"""Resume a frozen results set with four independent in-process driver runs.

This scheduler never changes prompts, settings, scoring or run_case. Every
request still passes the driver's durable checkpoint before transport. The
checkpoint serializes the *whole set's* cost plus in-flight reservations.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import driver
spec = importlib.util.spec_from_file_location('eval_cli', HERE / 'eval.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)


class Cap(Exception):
    def __init__(self, interim):
        self.transcript = dict(interim, stop='cap', error='Global results-set cap; no request sent',
                               cost_usd=round(interim['cost_usd'] - interim['uncertain_usd'], 9), uncertain_usd=0)


class Budget:
    def __init__(self, out, cap):
        self.out, self.cap, self.lock = out, cap, threading.Lock()

    def checkpoint(self, path, interim):
        with self.lock:
            other = sum(json.loads(p.read_text())['cost_usd'] for p in self.out.glob('*.r*.json') if p != path)
            if other + interim['cost_usd'] > self.cap:
                raise Cap(interim)
            E.write_json(path, interim)

    def finish(self, path, transcript):
        with self.lock:
            E.write_json(path, transcript)


def resume(out, env_file):
    out = Path(out)
    lock = os.open(out, os.O_RDONLY)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        man = json.loads((out / 'manifest.json').read_text())
        errors = E.manifest_problems(man)
        if E.sha(json.loads((HERE / 'settings.json').read_text())) != man['settings_hash']:
            errors.append('settings changed')
        if errors:
            raise ValueError('; '.join(errors))
        settings = man['settings']
        snap = E.snapshot(man['revision']['commit'])
        errors, cases, _ = E.check(*snap)
        if errors:
            raise ValueError('; '.join(errors))
        key = E._key(argparse.Namespace(env_file=env_file), settings)
        budget = Budget(out, settings['spend_cap_usd'])
        execution = {'schema': 'openwiz.skills-eval.execution.v1', 'workers': 4,
                     'scheduler_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     'core_code_hash': E.code_hash(), 'snapshot': man['revision'],
                     'method': 'Resume existing records unchanged; run independent cases with the same frozen driver. '
                               'One serialized durable global reservation before each request, including judges.'}
        ef = out / 'execution.json'
        if ef.exists() and json.loads(ef.read_text()) != execution:
            raise ValueError('scheduler changed: refusing resume')
        E.write_json(ef, execution)
        jobs = [(c, rep) for rep in range(1, man['repeats'] + 1) for c in cases
                if not (out / f"{c['id']}.r{rep}.json").exists()]

        def one(job):
            c, rep = job
            path = out / f"{c['id']}.r{rep}.json"
            post = driver.http_post(key, settings['provider'])
            try:
                t = driver.run_case(c, settings, snap, post, rep,
                                    checkpoint=lambda interim: budget.checkpoint(path, interim))
            except Cap as e:
                t = e.transcript
            budget.finish(path, t)
            print(f"{c['id']} r{rep}: stop={t['stop']} turns={t['turns']} ${t['cost_usd']:.6f}", flush=True)
            return t['stop'] == 'cap'
        with ThreadPoolExecutor(max_workers=4) as pool:
            capped = any(list(pool.map(one, jobs)))
        return 3 if capped else 0
    finally:
        os.close(lock)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    p.add_argument('--env-file', required=True)
    a = p.parse_args()
    sys.exit(resume(a.out, a.env_file))
