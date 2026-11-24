#!/usr/bin/env node
import { randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const MINUTES = 45;
const RUN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/;
const THREAD = /^thr_[A-Za-z0-9]{1,64}$/;
const LINE = /^huntr lease: (?:(claim|renew) (\S+)(?: thread (\S+))? for 45m|release (\S+))$/;
const LIMIT = 65536;

const fail = reason => { throw new Error(reason); };
const pending = reason => { throw Object.assign(new Error(reason), {exit: 3}); };
const ATTEMPTS = 4;
const iso = ms => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
function gh(args, what) {
  try { return execFileSync('gh', args, {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024, timeout: 60000}); }
  catch { fail(what); }
}
function switchIssue() {
  let policy;
  try {
    const text = readFileSync('docs/agents/huntr.md', 'utf8');
    policy = JSON.parse(text.split('\n```json\n')[1].split('\n```')[0]);
  } catch { fail('unreadable huntr settings: run from the consuming repository root'); }
  if (!Number.isSafeInteger(policy.switch_issue) || policy.switch_issue <= 0) fail('unreadable switch issue');
  return policy.switch_issue;
}
function repository() {
  const repo = process.env.GH_REPO || JSON.parse(gh(['repo', 'view', '--json', 'nameWithOwner'], 'GitHub repository read failed')).nameWithOwner;
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo ?? '')) fail('unreadable repository');
  return repo;
}
function comments(repo, issue) {
  let pages;
  try { pages = JSON.parse(gh(['api', '--paginate', '--slurp', `repos/${repo}/issues/${issue}/comments?per_page=100`], 'switch issue read failed')); }
  catch (e) { if (e instanceof SyntaxError) fail('unreadable switch issue comments'); throw e; }
  if (!Array.isArray(pages) || !pages.every(Array.isArray)) fail('unreadable switch issue comments');
  const all = pages.flat(), ids = new Set();
  for (const c of all) {
    if (!Number.isSafeInteger(c?.id) || c.id <= 0 || ids.has(c.id) || typeof c.body !== 'string'
      || typeof c.created_at !== 'string' || Number.isNaN(Date.parse(c.created_at))) fail('unreadable or duplicate switch issue comments');
    ids.add(c.id);
  }
  return all.sort((a, b) => a.id - b.id);
}
function holderOf(list) {
  let holder = null;
  for (const c of list) {
    const m = c.body.split(/\r?\n/, 1)[0].match(LINE);
    if (!m) continue;
    const t = Date.parse(c.created_at);
    const live = holder && Date.parse(holder.expires) > t;
    const [, kind, run, thread, released] = m;
    if (kind && (!RUN.test(run) || (thread !== undefined && !THREAD.test(thread)))) continue;
    const take = since => ({run, since, expires: iso(t + MINUTES * 60000), comment: c.id});
    if (kind === 'claim' && (!live || holder.run === run)) holder = take(live ? holder.since : c.created_at);
    else if (kind === 'renew' && live && holder.run === run) holder = take(holder.since);
    else if (released && live && holder.run === released) holder = null;
  }
  return holder;
}
const current = (holder, now) => holder && Date.parse(holder.expires) > now ? holder : null;
const held = h => `held by ${h.run} until ${h.expires}`;

function unconfirmed(kind, why) {
  const next = kind === 'index' ? 'read back the switch issue before retrying' : 'run status before retrying';
  fail(`unconfirmed write: ${kind} ${why}; ${next}`);
}
function postOnly(issue, body, kind = 'lease') {
  if (body.length > LIMIT) fail(`comment over ${LIMIT} characters`);
  const dir = mkdtempSync(join(tmpdir(), 'huntr-lease-'));
  try {
    writeFileSync(join(dir, 'body.md'), body);
    const next = kind === 'index' ? 'read back the switch issue before retrying' : 'run status before retrying';
    const url = gh(['issue', 'comment', String(issue), '--body-file', join(dir, 'body.md')],
      `unconfirmed write: ${kind} write failed or response was lost; ${next}`);
    return Number(url.trim().match(/#issuecomment-(\d+)$/)?.[1]);
  } finally { rmSync(dir, {recursive: true, force: true}); }
}
function post(repo, issue, body, before, kind = 'lease') {
  const id = postOnly(issue, body, kind);
  let after;
  try { after = comments(repo, issue); } catch { unconfirmed(kind, 'read-back failed after write'); }
  const same = c => c.body.trimEnd() === body.trimEnd();
  const mine = after.find(c => c.id === id && same(c)) ?? (() => {
    const found = after.filter(c => c.id > before && same(c));
    return found.length === 1 ? found[0] : null;
  })();
  if (!mine) unconfirmed(kind, 'write unconfirmed on read-back');
  return {after, mine};
}
function switchState(list) {
  const firsts = list.map(c => ({comment: c.id, line: c.body.split(/\r?\n/, 1)[0]}));
  const line = firsts.filter(f => f.line.startsWith('huntr:')).at(-1)?.line ?? null;
  return {switch: line?.match(/^huntr: (on|off)(?:\s+[—–-]\s.*)?$/)?.[1] === 'on' ? 'on' : 'off', line,
    kinds: firsts.filter(f => f.line.startsWith('huntr kind approved:'))};
}
function pace(timezone, streak, lastEmpty) {
  const ask = what => fail(`unknown ${what}: ask on the tracking issue`);
  let day;
  try { day = new Intl.DateTimeFormat('en-CA', {timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit'}); }
  catch { ask('timezone'); }
  if (!timezone) ask('timezone');
  if (!/^(0|[1-9][0-9]*)$/.test(streak)) ask('empty-hunt streak');
  if (Number(streak) < 2) return {hunt: true};
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?$/.test(lastEmpty))
    fail('last empty hunt time needs Z or an offset (such as 2026-11-19T23:55:00Z): ask on the tracking issue');
  const last = Date.parse(lastEmpty);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d{1,9})?)?(Z|[+-]\d{2}:\d{2})$/.test(lastEmpty) || Number.isNaN(last)) ask('last empty hunt time');
  const lastDay = day.format(last);
  if (day.format(Date.now()) > lastDay) return {hunt: true};
  const [y, m, d] = lastDay.split('-').map(Number);
  return {hunt: false, until: new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10)};
}
function finish(repo, issue, run, text) {
  const wait = process.env.HUNTR_LEASE_RETRY_MS ?? '15000';
  if (!/^(0|[1-9][0-9]{0,5})$/.test(wait)) fail('unreadable HUNTR_LEASE_RETRY_MS');
  const released = `huntr lease: release ${run}\n\n${text}`;
  const same = (c, body) => c.body.trimEnd() === body.trimEnd();
  let list = null;
  for (let i = 0; i < ATTEMPTS && !list; i++) {
    if (i) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, Number(wait) * 2 ** (i - 1));
    try { list = comments(repo, issue); } catch { }
  }
  const stuck = 'finalization pending: nothing was confirmed posted; keep the index and rerun finish on the next wake';
  if (!list) {
    let id;
    try { id = postOnly(issue, released); } catch { pending(stuck); }
    return {finished: 'release', verified: false, comment: id};
  }
  const done = list.find(c => same(c, released) || same(c, text));
  if (done) return {finished: 'already', verified: true, comment: done.id, holder: current(holderOf(list), Date.now())};
  const now = current(holderOf(list), Date.now());
  const holding = now?.run === run;
  let after, mine;
  try { ({after, mine} = post(repo, issue, holding ? released : text, list.at(-1)?.id ?? 0)); } catch { pending(stuck); }
  const holder = current(holderOf(after), Date.parse(mine.created_at));
  if (holding && holder?.run === run) fail(`release not effective: ${held(holder)}`);
  return {finished: holding ? 'release' : 'record', verified: true, comment: mine.id, holder};
}
function publish(repo, issue, run, recordFile, indexFile) {
  const manifest = fileURLToPath(new URL('./manifest.mjs', import.meta.url));
  const node = (args, what) => {
    try { return JSON.parse(execFileSync(process.execPath, [manifest, ...args], {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024})); }
    catch { fail(what); }
  };
  let record;
  try { record = JSON.parse(readFileSync(recordFile, 'utf8')); } catch { fail('unreadable record file'); }
  if (record?.run !== run) fail(`the record is not run ${run}'s`);
  const packed = node(['pack', recordFile], 'the record cannot be packed');
  let list = comments(repo, issue);
  const ids = [];
  for (const [i, body] of packed.comments.entries()) {
    const found = list.find(c => c.body.trimEnd() === body.trimEnd());
    if (found) { ids.push(found.id); continue; }
    try { ({after: list} = post(repo, issue, body, list.at(-1)?.id ?? 0)); }
    catch { fail(`part ${i + 1}/${packed.comments.length} unconfirmed; rerun publish to reconcile`); }
    ids.push(list.find(c => c.body.trimEnd() === body.trimEnd()).id);
  }
  const back = comments(repo, issue);
  const bodies = ids.map(id => back.find(c => c.id === id)?.body ?? fail('a posted part is missing on read-back'));
  const dir = mkdtempSync(join(tmpdir(), 'huntr-publish-'));
  try {
    writeFileSync(join(dir, 'readback.json'), JSON.stringify(bodies));
    const verified = node(['unpack', join(dir, 'readback.json'), packed.sha256], 'the read-back parts do not verify');
    if (JSON.stringify(verified) !== JSON.stringify(record)) fail('the read-back record differs');
  } finally { rmSync(dir, {recursive: true, force: true}); }
  const total = ids.length;
  writeFileSync(indexFile, [`Hunt record index for ${run}: ${total} parts, sha256 ${packed.sha256}`, '',
    ...ids.map((id, i) => `- part ${i + 1}/${total}: https://github.com/${repo}/issues/${issue}#issuecomment-${id}`), ''].join('\n'));
  return {sha256: packed.sha256, parts: total, index: indexFile};
}
function main() {
  const [command, ...args] = process.argv.slice(2);
  const shapes = {id: 0, status: 0, claim: 1, renew: 2, release: 2, due: 2, record: 2, finish: 2, switch: 0, pace: 3, publish: 3};
  if (!Object.hasOwn(shapes, command) || args.length !== shapes[command]) fail('usage: lease.mjs id | status | claim <run> | renew <run> <result-file> | release <run> <result-file> | due <run> scheduled|hunter | record <run> <index-file> | finish <run> <index-file> | switch | pace <timezone> <streak> <last-empty-at> | publish <run> <record.json> <index-file>');
  if (command === 'id') return `huntr-${new Date().toISOString().slice(0, 19).replace(/[-:]/g, '')}Z-${randomBytes(12).toString('hex')}`;
  if (command === 'pace') return pace(...args);
  if (command === 'switch') return switchState(comments(repository(), switchIssue()));
  const [run] = args;
  if (command !== 'status' && (!RUN.test(run) || run.startsWith('thr_'))) fail('unreadable run id');
  if (command === 'due' && !['scheduled', 'hunter'].includes(args[1])) fail('unreadable wake kind: scheduled or hunter');
  const result = ['renew', 'release', 'record', 'finish'].includes(command) ? args[1] : null;
  let text = '';
  if (result !== null) {
    try { text = readFileSync(result, 'utf8'); } catch { fail('unreadable result file'); }
    if (!text.trim()) fail('empty result file');
  }
  if ((command === 'record' || command === 'finish') && /^huntr[ :]/.test(text.split(/\r?\n/, 1)[0])) fail('a record\'s first line may not start with huntr');
  let issue, repo, before;
  try {
    issue = switchIssue(); repo = repository();
    if (command === 'publish') return publish(repo, issue, run, args[1], args[2]);
    if (command === 'finish') return finish(repo, issue, run, text);
    before = comments(repo, issue);
  } catch (e) {
    if (command === 'due') Object.assign(e, {exit: 3, message: `${e.message}: the lease is unknown, so file nothing this wake`});
    throw e;
  }
  const now = current(holderOf(before), Date.now());
  if (command === 'status') return {holder: now};
  if (command === 'record') {
    if (now && now.run === run) fail(`${run} holds the live lease: post its final index with release`);
    const existing = before.find(c => c.body.trimEnd() === text.trimEnd());
    if (existing) return {holder: now, comment: existing.id, already: true};
    const {after, mine} = post(repo, issue, text, before.at(-1)?.id ?? 0, 'index');
    return {holder: current(holderOf(after), Date.parse(mine.created_at)), comment: mine.id};
  }
  if (command === 'due') {
    if (!now) fail('no live lease');
    if (now.run !== run) fail(held(now));
    const last = Date.parse(now.expires) - MINUTES * 60000;
    return {holder: now, checkpoint: args[1] === 'scheduled' || Date.now() - last >= 30 * 60000};
  }
  if (command === 'claim' && now && now.run !== run) fail(held(now));
  if (command !== 'claim') {
    if (!now) fail('no live lease to ' + command);
    if (now.run !== run) fail(held(now));
  }
  const line = command === 'release' ? `huntr lease: release ${run}` : `huntr lease: ${command} ${run} for ${MINUTES}m`;
  const {after, mine} = post(repo, issue, result === null ? line : `${line}\n\n${text}`, before.at(-1)?.id ?? 0);
  const holder = holderOf(after.filter(c => c.id <= mine.id));
  if (command === 'release') {
    if (holder) fail(`release not effective: ${held(holder)}`);
    return {holder: current(holderOf(after), Date.parse(mine.created_at))};
  }
  if (!holder || holder.run !== run || holder.comment !== mine.id) fail(holder ? `lost to ${holder.run}` : 'lease not taken');
  return {holder};
}
try { const result = main(); process.stdout.write((typeof result === 'string' ? result : JSON.stringify(result)) + '\n'); }
catch (e) { process.stderr.write(`huntr lease: ${e.message}\n`); process.exit(e.exit ?? 2); }
