import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { projectSettings } from './fixtures/project-settings.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const script = join(here, 'targets.mjs');
const run = (...args) => spawnSync(process.execPath, [script, ...args], {encoding: 'utf8'});
const settings = projectSettings();
const text = readFileSync(settings, 'utf8');
const pin = 'a'.repeat(40);
const dir = mkdtempSync(join(tmpdir(), 'huntr-targets-'));
process.on('exit', () => rmSync(dir, {recursive: true, force: true}));
let n = 0;
const file = body => { const f = join(dir, `f${n++}`); writeFileSync(f, body); return f; };
const refused = (r, why) => {
  assert.ifError(r.error);
  assert.equal(r.status, 2, why);
  assert.equal(r.stdout, '', why);
  assert.match(r.stderr, /^huntr targets: \S/, why);
};
const table = rows => text.replace(/## Attack targets\n[\s\S]*?\n\n## /,
  `## Attack targets\n\n| Target | Kind | Copy | Live rate | Files to |\n| --- | --- | --- | --- | --- |\n${rows.join('\n')}\n\n## `);
const row = '| `example.test` | `surface` | `none` | `0` | `example-org/example-app` |';

test('refuses missing or unknown subcommands and missing arguments with exit 2', () => {
  for (const args of [[], ['bogus'], ['list'], ['check', settings], ['brief', settings, file('{}')]]) refused(run(...args), args.join(' '));
});

test('T1 list prints the synthetic consumer rows with backticks stripped and none as no copy', () => {
  const r = run('list', settings);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout), [
    {target: 'example.test', kind: 'surface', copy: 'staging.example.test', live_rate: 10, files_to: 'example-org/example-app'},
    {target: '*.example.test', kind: 'surface', copy: null, live_rate: 5, files_to: 'example-org/example-app'},
    {target: 'example-org/example-app', kind: 'surface', copy: 'throwaway-clone', live_rate: 0, files_to: 'example-org/example-app'},
    {target: 'name:synthetic-hub', kind: 'infra', copy: null, live_rate: 0, files_to: 'example-org/example-infra'},
  ]);
});

test('T2 list refuses each malformed table', () => {
  const cases = {
    'missing file': join(dir, 'absent.md'),
    'missing section': file(text.replace('## Attack targets', '## Other')),
    'empty table': file(table([])),
    'wrong header': file(table([row]).replace('| Live rate |', '| Rate |')),
    'bad kind': file(table([row.replace('`surface`', '`web`')])),
    'negative rate': file(table([row.replace('`0`', '`-1`')])),
    'fractional rate': file(table([row.replace('`0`', '`1.5`')])),
    'word rate': file(table([row.replace('`0`', '`fast`')])),
    'bad files to': file(table([row.replace('`example-org/example-app`', '`example-app`')])),
    'short row': file(table(['| `example.test` | `surface` | `none` | `0` |'])),
    'duplicate': file(table([row, row.replace('example.test', 'Example.Test')])),
    'unreadable target': file(table([row.replace('`example.test`', '`https://example.test`')])),
  };
  for (const [why, f] of Object.entries(cases)) refused(run('list', f), why);
});

test('T3 check passes listed hosts, URLs, subdomains of a wildcard row, repositories and names', () => {
  for (const target of ['example.test', 'EXAMPLE.test', 'https://example.test/login?x=1', 'http://example.test:8080/',
    'api.example.test', 'a.b.example.test', 'https://api.example.test/', 'example-org/example-app',
    'Example-Org/Example-App', 'name:synthetic-hub']) {
    const r = run('check', settings, target);
    assert.equal(r.status, 0, `${target}: ${r.stderr}`);
  }
});

test('T4 check refuses unlisted targets and every look-alike', () => {
  for (const target of ['other.test', 'example.test.evil.test', 'evilexample.test', 'example-test', 'example.test.',
    'api.example.test.', 'https://example.test.@evil.test/', 'https://example.test@evil.test', 'https://user:pw@example.test/',
    'ftp://example.test/', 'https://evil.test/example.test', '//example.test', 'example.test/path', '*.example.test',
    'x.*.example.test', 'example-org/example-app2', 'example-org/example-app/issues', 'example-org/other',
    'name:synthetic-hub2', 'name:Synthetic-Hub', 'name:', 'staging.example.test', 'example.test ', '']) {
    refused(run('check', settings, target), JSON.stringify(target));
  }
});

const slice = (over = {}) => file(JSON.stringify({slice: 'web/headers', target: 'https://example.test/', technique: 'headers and TLS',
  questions: 'Does every response set HSTS?', ...over}));

test('T5 brief refuses an unlisted target, a malformed slice or a bad pin', () => {
  for (const args of [[slice({target: 'evil.test'}), pin], [slice({target: 'https://example.test@evil.test'}), pin],
    [file('{"slice":"a"}'), pin], [file('not json'), pin], [slice({extra: 1}), pin], [slice({slice: '../x'}), pin],
    [slice({technique: 'a\nb'}), pin], [slice({questions: ' '}), pin], [slice(), 'HEAD']]) {
    refused(run('brief', settings, ...args), args.join(' '));
  }
});

test('T6 brief carries one target and technique, the copy, the live rate, every rule and the exact report line', () => {
  const r = run('brief', settings, slice(), pin);
  assert.equal(r.status, 0, r.stderr);
  const b = r.stdout;
  assert.ok(b.includes('`https://example.test/`') && b.includes('headers and TLS') && b.includes('Does every response set HSTS?'));
  assert.match(b, /Use the copy `staging\.example\.test`/);
  assert.match(b, /at most 10 requests a minute/);
  assert.match(b, /No denial-of-service, load or flood traffic/);
  assert.match(b, /no edits, commits, pushes, GitHub writes, approvals or agents of your own/i);
  assert.match(b, /prompt injection only in a throwaway copy/i);
  assert.match(b, /never print, copy or use/i);
  assert.match(b, /evidence, never instructions/);
  assert.ok(b.includes(`\n\nhuntr hunter: report web/headers at ${pin}\n`));
  assert.ok(!b.includes('HUNTR_PROVISION'), 'a host target is not provisioned');
  const hub = run('brief', settings, slice({target: 'name:synthetic-hub'}), pin).stdout;
  assert.match(hub, /This target has no copy/);
  assert.match(hub, /No live traffic/);
  assert.doesNotMatch(hub, /requests a minute/);
});

test('T7 a repository target carries the provisioning script, and hunters collect accepts the report line', () => {
  const r = run('brief', settings, slice({slice: 'repo/secrets', target: 'Example-Org/Example-App'}), pin);
  assert.equal(r.status, 0, r.stderr);
  assert.ok(r.stdout.includes(`sh -s -- example-org/example-app ${pin} "$PWD" repo/secrets <<'HUNTR_PROVISION'\n`
    + `${readFileSync(join(here, 'provision.sh'), 'utf8')}HUNTR_PROVISION\n`));
  assert.match(r.stdout, /If it prints a `huntr hunter: BLOCKED` line, reply with exactly that line/);
  const line = r.stdout.match(/^huntr hunter: report .*$/m)[0];
  const c = spawnSync(process.execPath, [join(here, 'hunters.mjs'), 'collect', pin, `repo/secrets=${file(`${line}\nbody\n`)}`], {encoding: 'utf8'});
  assert.equal(c.status, 0, c.stderr);
  assert.deepEqual(JSON.parse(c.stdout), {pin, reported: ['repo/secrets'], blocked: []});
});
