#!/usr/bin/env node
// huntr's controller lease on the switch issue (#1685): one controller at a time, by posting,
// reading back and expiring a comment, never by listing threads. Every lease time is GitHub's
// comment time (server time); only the precheck before a post reads the local clock.
//   lease.mjs id                              (local time + random suffix; generate once per run)
//   lease.mjs status
//   lease.mjs claim <run>
//   lease.mjs renew <run> <result-file>   (a checkpoint result, posted under the lease line)
//   lease.mjs release <run> <result-file>          (the final result, posted under the release line)
//   lease.mjs due <run> scheduled|hunter  (read-only: must this wake post a checkpoint?)
//   lease.mjs record <run> <index-file>            (a record without a lease of its own: an off switch,
//                                                   a lost lease; posted as it is, lease unchanged)
// Exit 0 prints {"holder": ...} as JSON; exit 2 is a refusal, a lost lease or an unconfirmed
// write, with its reason on stderr. Claims and refusals before a post write nothing.
import { randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';

const MINUTES = 45;
const RUN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$/;
const THREAD = /^thr_[A-Za-z0-9]{1,64}$/;
// Replay old thread-bearing comments too, so an upgrade cannot steal a live lease.
const LINE = /^huntr lease: (?:(claim|renew) (\S+)(?: thread (\S+))? for 45m|release (\S+))$/;
const LIMIT = 65536;

const fail = reason => { throw new Error(reason); };
const iso = ms => new Date(ms).toISOString().replace(/\.\d{3}Z$/, 'Z');
function gh(args, what) {
  try { return execFileSync('gh', args, {encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], maxBuffer: 64 * 1024 * 1024, timeout: 60000}); }
  catch { fail(what); }
}
function switchIssue() {
  // The project's huntr settings name the switch issue in their machine-readable policy.
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
// Replay every lease line in comment order. A claim takes a free or expired lease, or renews the
// holder's own; a renewal counts only from the live holder; a release frees the holder's lease.
// Everyone reading the same comments agrees on one holder.
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

function post(repo, issue, body, before) {
  if (body.length > LIMIT) fail(`comment over ${LIMIT} characters`);
  const dir = mkdtempSync(join(tmpdir(), 'huntr-lease-'));
  let url;
  try {
    writeFileSync(join(dir, 'body.md'), body);
    url = gh(['issue', 'comment', String(issue), '--body-file', join(dir, 'body.md')], 'lease write failed or is unconfirmed; run status before retrying');
  } finally { rmSync(dir, {recursive: true, force: true}); }
  // Read back: the posted comment must be there exactly, and is identified by its id.
  const after = comments(repo, issue);
  const id = Number(url.trim().match(/#issuecomment-(\d+)$/)?.[1]);
  const same = c => c.body.trimEnd() === body.trimEnd();
  const mine = after.find(c => c.id === id && same(c)) ?? (() => {
    const found = after.filter(c => c.id > before && same(c));
    return found.length === 1 ? found[0] : null;
  })();
  if (!mine) fail('lease write unconfirmed on read-back; run status before retrying');
  return {after, mine};
}
function main() {
  const [command, ...args] = process.argv.slice(2);
  const shapes = {id: 0, status: 0, claim: 1, renew: 2, release: 2, due: 2, record: 2};
  if (!Object.hasOwn(shapes, command) || args.length !== shapes[command]) fail('usage: lease.mjs id | status | claim <run> | renew <run> <result-file> | release <run> <result-file> | due <run> scheduled|hunter | record <run> <index-file>');
  // No GitHub or Cloudroom identity is needed, even when the switch is off.
  if (command === 'id') return `huntr-${new Date().toISOString().slice(0, 19).replace(/[-:]/g, '')}Z-${randomBytes(12).toString('hex')}`;
  const [run] = args;
  if (command !== 'status' && (!RUN.test(run) || run.startsWith('thr_'))) fail('unreadable run id');
  if (command === 'due' && !['scheduled', 'hunter'].includes(args[1])) fail('unreadable wake kind: scheduled or hunter');
  const result = command === 'renew' ? args[1] : command === 'release' || command === 'record' ? args[1] : null;
  let text = '';
  if (result !== null) {
    try { text = readFileSync(result, 'utf8'); } catch { fail('unreadable result file'); }
    if (!text.trim()) fail('empty result file');
  }
  // A plain record must never read as a switch, lease or kind-approval line.
  if (command === 'record' && /^huntr[ :]/.test(text.split(/\r?\n/, 1)[0])) fail('a record\'s first line may not start with huntr');
  const issue = switchIssue(), repo = repository();
  const before = comments(repo, issue);
  const now = current(holderOf(before), Date.now());
  if (command === 'status') return {holder: now};
  if (command === 'record') {
    const {after, mine} = post(repo, issue, text, before.at(-1)?.id ?? 0);
    return {holder: current(holderOf(after), Date.parse(mine.created_at)), comment: mine.id};
  }
  if (command === 'due') {
    if (!now) fail('no live lease');
    if (now.run !== run) fail(held(now));
    // Every scheduled wake posts a result; a hunter's wake posts only once one is 30 minutes overdue.
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
catch (e) { process.stderr.write(`huntr lease: ${e.message}\n`); process.exit(2); }
