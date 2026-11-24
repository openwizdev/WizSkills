import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const script = join(dirname(fileURLToPath(import.meta.url)), 'findings.mjs');
const run = (...args) => spawnSync(process.execPath, [script, ...args], {encoding: 'utf8'});

const ACCEPTANCE_CRITERION =
  '- [ ] A check or test that fails before the fix and passes after it is in the fix\'s pull request.';

function baseFinding(overrides = {}) {
  return {
    target: 'example.test',
    technique: 'headers and TLS',
    severity: 'medium',
    live_users: false,
    secrets: false,
    person_data: false,
    money: false,
    machine_level: false,
    summary: 'Missing Content-Security-Policy-Report-Only header on public site.',
    proof_command: 'curl -sI https://example.test/users/profile',
    steps: 'PRIVATE-EXPLOIT-STEP-SENTINEL: 1. send crafted request to 192.0.2.10 with thr_synstep1',
    ...overrides,
  };
}

function withTempDir(fn) {
  const dir = mkdtempSync(join(tmpdir(), 'huntr-findings-'));
  try {
    return fn(dir);
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
}

test('refuses missing, unknown, or wrong-arity subcommands with usage and exit 2', () => {
  for (const args of [[], ['bogus'], ['route'], ['route', 'a.json', 'b.json'], ['issue'], ['issue', 'a.json', 'b.json']]) {
    const r = run(...args);
    assert.ifError(r.error);
    assert.equal(r.status, 2);
    assert.equal(r.stdout, '');
    assert.match(r.stderr, /^huntr findings: usage: /);
  }
});

test('refuses unreadable files, malformed JSON, duplicate keys, missing/extra fields, and wrong types', () => {
  withTempDir(dir => {
    const missing = join(dir, 'missing.json');
    for (const cmd of ['route', 'issue']) {
      const r = run(cmd, missing);
      assert.ifError(r.error);
      assert.equal(r.status, 2);
      assert.equal(r.stdout, '');
      assert.match(r.stderr, /^huntr findings: unreadable /);
    }

    const badRaw = [
      ['invalid json', '{not-json'],
      ['array top-level', '[]'],
      ['null top-level', 'null'],
      ['primitive top-level', '"hello"'],
      [
        'duplicate boolean key',
        '{"target":"example.test","technique":"headers","severity":"low","live_users":true,"live_users":false,"secrets":false,"person_data":false,"money":false,"machine_level":false,"summary":"ok","proof_command":"curl -sI https://example.test","steps":"s"}',
      ],
    ];

    for (const [label, raw] of badRaw) {
      const file = join(dir, `raw-${label.replace(/\W+/g, '_')}.json`);
      writeFileSync(file, raw, 'utf8');
      for (const cmd of ['route', 'issue']) {
        const r = run(cmd, file);
        assert.ifError(r.error);
        assert.equal(r.status, 2, `${cmd} should refuse ${label}`);
        assert.equal(r.stdout, '', `${cmd} stdout must be empty on ${label}`);
        assert.match(r.stderr, /^huntr findings: (unreadable|invalid) /);
      }
    }

    const requiredKeys = Object.keys(baseFinding());
    const badObjects = [];
    for (const key of requiredKeys) {
      const copy = baseFinding();
      delete copy[key];
      badObjects.push([`missing ${key}`, copy]);
    }
    badObjects.push(['extra key', {...baseFinding(), extra: true}]);

    for (const flag of ['live_users', 'secrets', 'person_data', 'money', 'machine_level']) {
      for (const badVal of ['false', 0, 1, null, []]) {
        badObjects.push([`${flag}=${JSON.stringify(badVal)}`, baseFinding({[flag]: badVal})]);
      }
    }
    for (const badSev of ['CRITICAL', 'info', '', null, 1, {critical: null}]) {
      badObjects.push([`severity=${JSON.stringify(badSev)}`, baseFinding({severity: badSev})]);
    }
    for (const field of ['target', 'technique', 'summary', 'proof_command']) {
      for (const badVal of ['', '   ', 123, null, []]) {
        badObjects.push([`${field}=${JSON.stringify(badVal)}`, baseFinding({[field]: badVal})]);
      }
    }
    badObjects.push(['target newline', baseFinding({target: 'example.test\nevil'})]);
    badObjects.push(['technique newline', baseFinding({technique: 'headers\nevil'})]);
    for (const badSteps of [null, 123, [], {}]) {
      badObjects.push([`steps=${JSON.stringify(badSteps)}`, baseFinding({steps: badSteps})]);
    }

    for (let i = 0; i < badObjects.length; i++) {
      const [label, obj] = badObjects[i];
      const file = join(dir, `bad-${i}.json`);
      writeFileSync(file, JSON.stringify(obj), 'utf8');
      for (const cmd of ['route', 'issue']) {
        const r = run(cmd, file);
        assert.ifError(r.error);
        assert.equal(r.status, 2, `${cmd} should refuse ${label}`);
        assert.equal(r.stdout, '', `${cmd} stdout must be empty on ${label}`);
        assert.match(r.stderr, /^huntr findings: invalid /);
      }
    }
  });
});

test('P3: route covers all 128 combinations of five flags and four severities (RT4, RT5)', () => {
  const severities = ['low', 'medium', 'high', 'critical'];
  const bools = [false, true];
  let count = 0;

  withTempDir(dir => {
    const file = join(dir, 'finding.json');
    for (const live_users of bools) {
      for (const secrets of bools) {
        for (const person_data of bools) {
          for (const money of bools) {
            for (const machine_level of bools) {
              for (const severity of severities) {
                count += 1;
                writeFileSync(
                  file,
                  JSON.stringify(baseFinding({live_users, secrets, person_data, money, machine_level, severity})),
                  'utf8',
                );
                const r = run('route', file);
                assert.ifError(r.error);
                assert.equal(r.status, 0, `expected exit 0 for case ${count}: ${r.stderr}`);
                assert.equal(r.stderr, '');
                const out = JSON.parse(r.stdout);
                assert.deepEqual(Object.keys(out).sort(), ['channel', 'fix']);

                const isPrivate = live_users || secrets || person_data || money;
                const expectedChannel = !isPrivate ? 'public' : machine_level ? 'private' : 'advisory';
                const expectedFix = severity === 'critical' ? 'builder-now' : 'triage';

                assert.equal(
                  out.channel,
                  expectedChannel,
                  `channel mismatch for flags=${JSON.stringify({live_users, secrets, person_data, money, machine_level})}`,
                );
                assert.equal(out.fix, expectedFix, `fix mismatch for severity=${severity}`);
              }
            }
          }
        }
      }
    }
  });

  assert.equal(count, 128);
});

test('P4: issue prints neutral public body with required fields and acceptance criterion, never steps', () => {
  withTempDir(dir => {
    const file = join(dir, 'public.json');
    const finding = baseFinding({
      machine_level: true,
      summary: 'Missing Strict-Transport-Security on disk-usage page v1.2.3.',
      proof_command: 'curl -sI https://example.test/api/v1/organizations/members/settings',
      steps: 'SECRET-STEPS-MUST-NEVER-PRINT thr_syn999 /home/synthetic/x 192.0.2.55 someone@example.org',
    });
    writeFileSync(file, JSON.stringify(finding), 'utf8');

    const r = run('issue', file);
    assert.ifError(r.error);
    assert.equal(r.status, 0, `expected exit 0: ${r.stderr}`);
    assert.equal(r.stderr, '');

    const lines = r.stdout.split('\n');
    assert.match(lines[0], /^# .+/, 'first line must be a markdown title');
    assert.ok(r.stdout.includes(finding.summary), 'body must include summary');
    assert.ok(r.stdout.includes(finding.target), 'body must include target');
    assert.ok(r.stdout.includes(finding.technique), 'body must include technique');
    assert.ok(r.stdout.includes(finding.severity), 'body must include severity');
    assert.ok(r.stdout.includes(finding.proof_command), 'body must include safe proof command');
    assert.ok(lines.includes(ACCEPTANCE_CRITERION), 'body must include exact regression-check acceptance criterion');
    assert.ok(!r.stdout.includes('SECRET-STEPS-MUST-NEVER-PRINT'), 'body must never print steps');
    assert.ok(!r.stdout.includes('thr_syn999'), 'body must never leak steps content');
  });
});

test('P4: issue refuses non-public findings (advisory and private) with exit 2', () => {
  withTempDir(dir => {
    const file = join(dir, 'private.json');
    for (const flag of ['live_users', 'secrets', 'person_data', 'money']) {
      for (const machine_level of [false, true]) {
        writeFileSync(file, JSON.stringify(baseFinding({[flag]: true, machine_level})), 'utf8');
        const r = run('issue', file);
        assert.ifError(r.error);
        assert.equal(r.status, 2, `issue must refuse ${flag}=true machine_level=${machine_level}`);
        assert.equal(r.stdout, '');
        assert.match(r.stderr, /^huntr findings: not public /);
      }
    }
  });
});

test('P4: issue refuses every leak pattern in any printed field without echoing the leaked value', () => {
  const leaks = [
    ['thread id', 'see thr_synabc123 for details', 'thr_synabc123'],
    ['linux home path', 'check /home/synthetic/app/config', '/home/synthetic/app/config'],
    ['macos home path', 'check /Users/synthetic/app/config', '/Users/synthetic/app/config'],
    ['tilde home path', 'check ~/secrets/config', '~/secrets/config'],
    ['ipv4 address', 'host 192.0.2.42 responded', '192.0.2.42'],
    ['email address', 'contact someone@example.org for access', 'someone@example.org'],
    ['ghp token', 'token ' + 'ghp_' + 'a1b2c3d4e5f6g7h8i9j0', 'ghp_' + 'a1b2c3d4e5f6g7h8i9j0'],
    ['github_pat token', 'token ' + 'github_pat_' + '11synthetic99', 'github_pat_' + '11synthetic99'],
    ['sk token', 'key ' + 'sk-' + 'synthetic123456', 'sk-' + 'synthetic123456'],
    ['xox token', 'slack ' + 'xox' + 'b-123456-synthetic', 'xox' + 'b-123456-synthetic'],
    ['hex 32+ run', 'digest ' + '0123456789abcdef'.repeat(2), '0123456789abcdef'.repeat(2)],
    ['base64 32+ run', 'blob YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo=', 'YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo='],
    ['base64url 32+ run', 'blob aB1_cD2-eF3_gH4-iJ5_kL6-mN7_oP89', 'aB1_cD2-eF3_gH4-iJ5_kL6-mN7_oP89'],
  ];

  withTempDir(dir => {
    const file = join(dir, 'leak.json');
    for (const [label, value, secret] of leaks) {
      writeFileSync(file, JSON.stringify(baseFinding({summary: value})), 'utf8');
      const r = run('issue', file);
      assert.ifError(r.error);
      assert.equal(r.status, 2, `issue must refuse ${label} in summary`);
      assert.equal(r.stdout, '');
      assert.match(r.stderr, /^huntr findings: leak in summary: /);
      assert.ok(!r.stderr.includes(secret), `stderr must not echo leaked ${label}`);
    }

    for (const field of ['target', 'technique', 'proof_command']) {
      const secret = 'thr_synfield1';
      writeFileSync(file, JSON.stringify(baseFinding({[field]: `bad ${secret}`})), 'utf8');
      const r = run('issue', file);
      assert.ifError(r.error);
      assert.equal(r.status, 2, `issue must refuse leak in ${field}`);
      assert.equal(r.stdout, '');
      assert.match(r.stderr, new RegExp(`^huntr findings: leak in ${field}: `));
      assert.ok(!r.stderr.includes(secret), `stderr must not echo leaked value from ${field}`);
    }
  });
});
