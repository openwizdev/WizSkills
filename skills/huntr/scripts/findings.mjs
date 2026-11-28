#!/usr/bin/env node
import { readFileSync } from 'node:fs';

const REQUIRED_KEYS = [
  'live_users', 'machine_level', 'money', 'person_data', 'proof_command',
  'secrets', 'severity', 'steps', 'summary', 'target', 'technique',
].join(',');
const BOOLEAN_FIELDS = ['live_users', 'secrets', 'person_data', 'money', 'machine_level'];
const TEXT_FIELDS = ['target', 'technique', 'summary', 'proof_command'];
const SINGLE_LINE_FIELDS = ['target', 'technique'];
const PRINTED_FIELDS = ['target', 'technique', 'severity', 'summary', 'proof_command'];
const SEVERITIES = new Set(['low', 'medium', 'high', 'critical']);

const THREAD_ID = /thr_/;
const HOME_PATH = /\/home\/|\/Users\/|~\//;
const IPV4 = /(?<![0-9]\.)(?<![0-9])(?:(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?!\.?[0-9])/;
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;
const TOKEN_PREFIX = /ghp_|github_pat_|(?<![A-Za-z0-9])sk-[A-Za-z0-9]|(?<![A-Za-z0-9])xox/i;
const HEX_RUN = /(?<![A-Za-z0-9])[0-9a-fA-F]{32,}(?![A-Za-z0-9])/;
const BASE64_CORE = /(?:[A-Za-z0-9+]{32,}={0,2}|[A-Za-z0-9+]{31}=|[A-Za-z0-9+]{30}==)/;
const BASE64_EXTENDED = /[A-Za-z0-9+/_-]+={0,2}/g;

const fail = reason => { throw new Error(reason); };

function assertUniqueJsonKeys(text) {
  let i = 0;
  const n = text.length;
  const skipWs = () => { while (i < n && ' \t\r\n'.includes(text[i])) i += 1; };
  const readString = () => {
    const start = i++;
    while (i < n) {
      if (text[i] === '\\') { i += 2; continue; }
      if (text[i] === '"') return JSON.parse(text.slice(start, ++i));
      i += 1;
    }
    fail('invalid finding JSON');
  };
  const walk = () => {
    skipWs();
    if (i >= n) return;
    const ch = text[i];
    if (ch === '"') { readString(); return; }
    if (ch === '{') {
      i += 1;
      const seen = new Set();
      skipWs();
      if (text[i] === '}') { i += 1; return; }
      while (i < n) {
        skipWs();
        const key = readString();
        if (seen.has(key)) fail('invalid finding JSON: duplicate key');
        seen.add(key);
        skipWs();
        i += 1;
        walk();
        skipWs();
        if (text[i] === ',') { i += 1; continue; }
        if (text[i] === '}') { i += 1; return; }
        fail('invalid finding JSON');
      }
      return;
    }
    if (ch === '[') {
      i += 1;
      skipWs();
      if (text[i] === ']') { i += 1; return; }
      while (i < n) {
        walk();
        skipWs();
        if (text[i] === ',') { i += 1; continue; }
        if (text[i] === ']') { i += 1; return; }
        fail('invalid finding JSON');
      }
      return;
    }
    while (i < n && !',]} \t\r\n'.includes(text[i])) i += 1;
  };
  walk();
}

function readFinding(file) {
  let raw;
  try { raw = readFileSync(file, 'utf8'); } catch { fail('unreadable finding file'); }
  let parsed;
  try { parsed = JSON.parse(raw); } catch { fail('invalid finding JSON'); }
  assertUniqueJsonKeys(raw);

  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) fail('invalid finding: expected JSON object');
  if (Object.keys(parsed).sort().join(',') !== REQUIRED_KEYS) fail('invalid finding: exact required fields only');
  for (const field of BOOLEAN_FIELDS) {
    if (typeof parsed[field] !== 'boolean') fail(`invalid finding: ${field} must be boolean`);
  }
  if (typeof parsed.severity !== 'string' || !SEVERITIES.has(parsed.severity)) {
    fail('invalid finding: severity must be low, medium, high, or critical');
  }
  for (const field of TEXT_FIELDS) {
    if (typeof parsed[field] !== 'string' || !parsed[field].trim()) {
      fail(`invalid finding: ${field} must be a non-empty string`);
    }
  }
  for (const field of SINGLE_LINE_FIELDS) {
    if (/[\r\n]/.test(parsed[field])) fail(`invalid finding: ${field} must be single-line`);
  }
  if (typeof parsed.steps !== 'string') fail('invalid finding: steps must be a string');
  return parsed;
}

// SECURITY: routing rule per spec #3073 Implementation Decisions (grill RT4 and RT5).
function routeFinding(finding) {
  const isPrivate = finding.live_users || finding.secrets || finding.person_data || finding.money;
  const channel = !isPrivate ? 'public' : finding.machine_level ? 'private' : 'advisory';
  const fix = finding.severity === 'critical' ? 'builder-now' : 'triage';
  return {channel, fix};
}

function findLeak(value) {
  if (THREAD_ID.test(value)) return 'thread id';
  if (HOME_PATH.test(value)) return 'home path';
  if (IPV4.test(value)) return 'IPv4 address';
  if (EMAIL.test(value)) return 'email address';
  if (TOKEN_PREFIX.test(value) || HEX_RUN.test(value) || BASE64_CORE.test(value)) return 'token-shaped text';
  for (const [token] of value.matchAll(BASE64_EXTENDED)) {
    if (token.length < 32 || token.startsWith('/')) continue;
    if (/[+=]/.test(token) || (/[A-Z]/.test(token) && /[a-z]/.test(token) && /[0-9]/.test(token))) {
      return 'token-shaped text';
    }
  }
  return null;
}

function renderIssue(finding) {
  const route = routeFinding(finding);
  if (route.channel !== 'public') fail(`not public (channel: ${route.channel})`);
  for (const field of PRINTED_FIELDS) {
    const leak = findLeak(finding[field]);
    if (leak) fail(`leak in ${field}: ${leak}`);
  }
  const backtickRuns = finding.proof_command.match(/`+/g) ?? [];
  const fence = '`'.repeat(Math.max(3, ...backtickRuns.map(run => run.length + 1)));

  return [
    `# ${finding.target}: ${finding.technique} (${finding.severity})`,
    '',
    finding.summary,
    '',
    `- **Target:** \`${finding.target}\``,
    `- **Technique:** \`${finding.technique}\``,
    `- **Severity:** \`${finding.severity}\``,
    '',
    '## Safe proof command',
    '',
    `${fence}sh`,
    finding.proof_command,
    fence,
    '',
    '## Acceptance criteria',
    '',
    "- [ ] A check or test that fails before the fix and passes after it is in the fix's pull request.",
    '',
  ].join('\n');
}

try {
  const [command, ...args] = process.argv.slice(2);
  if (command === 'route') {
    if (args.length !== 1) fail('usage: findings.mjs route <finding.json>');
    process.stdout.write(JSON.stringify(routeFinding(readFinding(args[0]))) + '\n');
  } else if (command === 'issue') {
    if (args.length !== 1) fail('usage: findings.mjs issue <finding.json>');
    process.stdout.write(renderIssue(readFinding(args[0])));
  } else {
    fail('usage: findings.mjs route|issue <finding.json>');
  }
} catch (e) {
  process.stderr.write(`huntr findings: ${e.message}\n`);
  process.exit(2);
}
