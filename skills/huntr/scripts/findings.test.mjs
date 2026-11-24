import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = join(dirname(fileURLToPath(import.meta.url)), 'findings.mjs');
const run = (...args) => spawnSync(process.execPath, [script, ...args], {encoding: 'utf8'});

test('refuses missing or unknown subcommand with usage and stubbed subcommands with exit 2', () => {
  for (const args of [[], ['bogus']]) {
    const r = run(...args);
    assert.ifError(r.error);
    assert.equal(r.status, 2);
    assert.equal(r.stdout, '');
    assert.match(r.stderr, /^huntr findings: usage: /);
  }
  for (const command of ['route', 'issue']) {
    const r = run(command);
    assert.ifError(r.error);
    assert.equal(r.status, 2);
    assert.equal(r.stdout, '');
    assert.equal(r.stderr, 'huntr findings: not built yet\n');
  }
});
