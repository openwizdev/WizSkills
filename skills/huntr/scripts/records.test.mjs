import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { projectSettings } from './fixtures/project-settings.mjs';
import { spawnSync } from 'node:child_process';

const here = dirname(fileURLToPath(import.meta.url));
const settings = projectSettings();
function run(command, value, digest) {
  const dir = mkdtempSync(join(tmpdir(), 'huntr-record-'));
  try {
    const input = join(dir, 'record.json');
    writeFileSync(input, JSON.stringify(value));
    const r = spawnSync(process.execPath, [join(here, 'manifest.mjs'), command, input,
      ...(digest === undefined ? [] : [digest])], {encoding: 'utf8'});
    assert.ifError(r.error);
    return r;
  } finally { rmSync(dir, {recursive: true, force: true}); }
}
function ok(command, value, digest) {
  const r = run(command, value, digest);
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
}
const small = {run: 'synthetic-r1', slices: [], gaps: []};
const large = {...small, note: 'quoted "text"\nλ😺'.repeat(10000)};

test('R1 one small record uses one bounded part and a large record round-trips all numbered parts', () => {
  assert.equal(ok('pack', small).comments.length, 1);
  const packed = ok('pack', large);
  assert.equal(packed.comments.length, 6);
  assert.match(packed.sha256, /^[a-f0-9]{64}$/);
  for (const [i, body] of packed.comments.entries()) {
    assert.ok(Buffer.byteLength(body) <= 65536);
    assert.ok(body.startsWith(`Hunt record part ${i + 1}/6\n`));
  }
  assert.deepEqual(ok('unpack', packed.comments.toReversed(), packed.sha256), large);
});
function changePart(body, edit) {
  return body.replace(/\n(\{.*\})\n```$/, (_match, raw) => '\n' + JSON.stringify(edit(JSON.parse(raw))) + '\n```');
}
for (const problem of ['missing', 'duplicate', 'truncated', 'changed', 'wrong-root', 'bad-number', 'extra-key']) {
  test(`R1 read-back refuses ${problem} parts`, () => {
    const packed = ok('pack', large), parts = [...packed.comments];
    let expected = packed.sha256;
    if (problem === 'missing') parts.pop();
    if (problem === 'duplicate') parts[1] = parts[0];
    if (problem === 'truncated') parts[0] = parts[0].slice(0, -1);
    if (problem === 'changed') parts[0] = changePart(parts[0], p => {
      const data = Buffer.from(p.data, 'base64');
      data.write('synthetic-r2', data.indexOf('synthetic-r1'));
      return {...p, data: data.toString('base64')};
    });
    if (problem === 'wrong-root') expected = '0'.repeat(64);
    if (problem === 'bad-number') parts[0] = changePart(parts[0], p => ({...p, part: 2}));
    if (problem === 'extra-key') parts[0] = changePart(parts[0], p => ({...p, extra: true}));
    const r = run('unpack', parts, expected);
    assert.equal(r.status, 2, problem); assert.equal(r.stdout, '', problem);
  });
}
test('R1 the operative handoff requires bounded indexed parts and read-back before archival', () => {
  const section = readFileSync(settings, 'utf8').split('## Slice manifests (#696)\n')[1]?.split('\n## ')[0] ?? '';
  assert.match(section, /65,536/);
  assert.match(section, /pack .*run-record\.json/);
  assert.match(section, /unpack .*readback\.json/);
  assert.match(section, /index.*links/i);
  const finish = readFileSync(join(here, '../SKILL.md'), 'utf8').split('## 5. Record the result and finish this hunt\n')[1];
  assert.match(finish, /read back.*every.*part/i);
});

function finishRecord(finish) {
  assert.doesNotMatch(finish, /#\d+\b/, 'step 5 uses the configured switch issue, never a hardcoded issue number');
  const sentences = finish.split(/(?<=\.)\s+/);
  const summary = sentences.find(s => s.startsWith('Include **found, approved, proposed, skipped**'));
  assert.match(summary ?? '', /each with counts and tracker links/, 'record includes counts and links');
  const readBack = sentences.findIndex(s => /read back\*\* every configured switch issue part and index/i.test(s));
  assert.match(sentences[readBack] ?? '', /use `unpack` with the planned digest to verify all numbered parts/,
    'read-back verifies all numbered parts with the planned digest');
  assert.match(sentences[readBack] ?? '', /run identity,\s*coverage,\s*manifests,\s*skips,\s*ownership,\s*pacing and next action/i,
    'read-back checks the recovered record contents');
  const delivery = sentences.findIndex(s => s.startsWith('Once that record is verified, delivery is complete: **the configured switch issue is the only report channel** to the orchestrator'));
  assert.ok(delivery >= 0, 'configured switch issue alone completes delivery after verification');
  assert.match(finish, /Do not send direct thread messages or attempt a second delivery/,
    'direct messages and second delivery are forbidden');
  assert.doesNotMatch(finish, /send the orchestrator a short note|room-cli thread tell/i,
    'no direct orchestrator delivery');
  const archive = sentences.findIndex(s => s.includes('room-cli thread archive --self'));
  assert.ok(readBack >= 0 && archive >= 0, 'read-back and archive sentences present');
  assert.ok(readBack < delivery && delivery < archive, 'verification precedes delivery completion and archival');
}
const step5 = () => readFileSync(join(here, '../SKILL.md'), 'utf8')
  .split('## 5. Record the result and finish this hunt\n')[1].split('\n**Night setting:**')[0];
test('#959 step 5 sends its report only through the verified configured switch issue record before archival', () => {
  finishRecord(step5());
});
const summaryLine = 'Include **found, approved, proposed, skipped**, each with counts and tracker links.';
const readBackLine = 'Then **read back** every configured switch issue part and index, use `unpack` with the planned digest to verify all numbered parts, and check that the recovered record holds run identity, coverage, manifests, skips, ownership, pacing and next action.';
const deliveryLine = 'Once that record is verified, delivery is complete: **the configured switch issue is the only report channel** to the orchestrator, including partial results, final results, tier-0 audits, proposals and blockers.';
const noDirectLine = 'Do not send direct thread messages or attempt a second delivery.';
const archiveLine = 'Run `room-cli thread archive --self` as the final action.';
const validPolicy = `${summaryLine} ${readBackLine} ${deliveryLine} ${noDirectLine} ${archiveLine}`;
for (const [name, text, reason] of [
  ['hardcoded issue number instead of configured switch issue', validPolicy.replace('every configured switch issue part', 'every #394 part'),
    'step 5 uses the configured switch issue, never a hardcoded issue number'],
  ['direct note instead of configured-channel-only delivery', `${summaryLine} ${readBackLine} Send the orchestrator a short note naming the verified switch issue record. ${noDirectLine} ${archiveLine}`,
    'configured switch issue alone completes delivery after verification'],
  ['direct thread command added', `${validPolicy} Run \`room-cli thread tell synthetic-orchestrator report\`.`,
    'no direct orchestrator delivery'],
  ['direct note added', `${validPolicy} Send the orchestrator a short note naming the verified switch issue record.`,
    'no direct orchestrator delivery'],
  ['archival before verification', `${summaryLine} ${archiveLine} ${readBackLine} ${deliveryLine} ${noDirectLine}`,
    'verification precedes delivery completion and archival'],
  ['delivery before read-back', `${summaryLine} ${deliveryLine} ${readBackLine} ${noDirectLine} ${archiveLine}`,
    'verification precedes delivery completion and archival'],
  ['read-back without digest verification', validPolicy.replace(', use `unpack` with the planned digest to verify all numbered parts', ''),
    'read-back verifies all numbered parts with the planned digest'],
  ['read-back without semantic content check', validPolicy.replace(', and check that the recovered record holds run identity, coverage, manifests, skips, ownership, pacing and next action', ''),
    'read-back checks the recovered record contents'],
  ['record without counts', validPolicy.replace('counts and ', ''),
    'record includes counts and links'],
]) {
  test(`#959 the record check refuses ${name}`, () => {
    assert.throws(() => finishRecord(text), error => error.code === 'ERR_ASSERTION' && error.message.startsWith(reason));
  });
}
test('#959 the record check accepts configured-channel-only delivery after verification and before archival', () => {
  finishRecord(validPolicy);
});
test('#177 publish and finish use the configured switch issue rather than #394', () => {
  const dir = mkdtempSync(join(tmpdir(), 'huntr-channel-'));
  try {
    mkdirSync(join(dir, 'bin'));
    mkdirSync(join(dir, 'docs/agents'), {recursive: true});
    const customSettings = readFileSync(settings, 'utf8').replace('"switch_issue": 394', '"switch_issue": 777');
    writeFileSync(join(dir, 'docs/agents/huntr.md'), customSettings);
    const stateFile = join(dir, 'state.json');
    const logFile = join(dir, 'log');
    writeFileSync(stateFile, JSON.stringify({comments: [{id: 200, created_at: '2030-01-02T00:00:00Z', body: 'huntr: on'}]}));
    writeFileSync(join(dir, 'bin/gh'), `#!/usr/bin/env node
import { readFileSync, writeFileSync, appendFileSync } from 'node:fs';
const stateFile = process.env.HUNTR_FAKE_STATE;
const w = JSON.parse(readFileSync(stateFile, 'utf8'));
const a = process.argv.slice(2);
appendFileSync(process.env.HUNTR_FAKE_LOG, JSON.stringify(a) + '\\n');
const repo = process.env.GH_REPO;
if (a.join(' ') === \`api --paginate --slurp repos/\${repo}/issues/777/comments?per_page=100\`) {
  process.stdout.write(JSON.stringify([w.comments]));
} else if (a[0] === 'issue' && a[1] === 'comment' && a[2] === '777' && a[3] === '--body-file' && a.length === 5) {
  const id = Math.max(199, ...w.comments.map(c => c.id)) + 1;
  w.comments.push({id, created_at: '2030-01-02T00:05:00Z', body: readFileSync(a[4], 'utf8')});
  writeFileSync(stateFile, JSON.stringify(w));
  process.stdout.write(\`https://github.com/\${repo}/issues/777#issuecomment-\${id}\\n\`);
} else {
  process.stderr.write('unexpected gh call: ' + JSON.stringify(a) + '\\n');
  process.exit(1);
}
`, {mode: 0o755});
    const env = {...process.env, GH_REPO: 'synthetic/project', PATH: join(dir, 'bin') + ':' + process.env.PATH,
      HUNTR_FAKE_STATE: stateFile, HUNTR_FAKE_LOG: logFile, HUNTR_LEASE_RETRY_MS: '0'};
    const record = {
      run: 'synthetic-chan-777', coverage: ['core/correctness'], manifests: {'core/correctness': 'sha-syn'},
      skips: [], owners: {controller: 'synthetic-chan-777'}, pacing: {streak: 0, last_empty_at: 'none'},
      next: 'continue on next scheduled wake',
    };
    const recordFile = join(dir, 'record.json');
    const indexFile = join(dir, 'index.md');
    writeFileSync(recordFile, JSON.stringify(record));
    const pub = spawnSync(process.execPath, [join(here, 'lease.mjs'), 'publish', record.run, recordFile, indexFile], {cwd: dir, env, encoding: 'utf8'});
    assert.equal(pub.status, 0, pub.stderr);
    const pubOut = JSON.parse(pub.stdout);
    const indexText = readFileSync(indexFile, 'utf8');
    assert.match(indexText, /https:\/\/github\.com\/synthetic\/project\/issues\/777#issuecomment-201/);
    assert.doesNotMatch(indexText, /issues\/394/);
    const fin = spawnSync(process.execPath, [join(here, 'lease.mjs'), 'finish', record.run, indexFile], {cwd: dir, env, encoding: 'utf8'});
    assert.equal(fin.status, 0, fin.stderr);
    const state = JSON.parse(readFileSync(stateFile, 'utf8'));
    assert.deepEqual(ok('unpack', [state.comments[1].body], pubOut.sha256), record);
    const calls = readFileSync(logFile, 'utf8').trim().split('\n').map(JSON.parse);
    assert.ok(calls.every(c => !c.join(' ').includes('394')), 'no call targets hardcoded #394');
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
