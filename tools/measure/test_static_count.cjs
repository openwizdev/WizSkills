'use strict';

const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const cli = path.join(__dirname, 'static-count.cjs');
const tokenizer = process.env.WIZSKILLS_TEST_TOKENIZER;

function count(t, tokenizerDir) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'wizskills-static-'));
  t.after(() => fs.rmSync(cwd, { recursive: true }));
  const git = (...args) => execFileSync('git', args, { cwd, encoding: 'utf8' }).trim();
  git('init', '-q');
  fs.writeFileSync(path.join(cwd, 'entry.md'), 'hello world');
  fs.writeFileSync(path.join(cwd, 'reference.md'), 'hello world');
  fs.symlinkSync('reference.md', path.join(cwd, 'link.md'));
  git('add', '.');
  git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Fixture');
  const manifest = {
    commit: git('rev-parse', 'HEAD'),
    workflows: {
      'fixture.complete': ['entry.md', 'reference.md'],
      'fixture.missing': ['entry.md', 'missing.md'],
      'fixture.link': ['entry.md', 'link.md'],
    },
  };
  fs.writeFileSync(path.join(cwd, 'manifest.json'), JSON.stringify(manifest));
  // The checked-out bytes disagree with the immutable Git blob.
  fs.writeFileSync(path.join(cwd, 'entry.md'), 'changed in the working directory');
  const args = [cli, 'manifest.json'];
  if (tokenizerDir) args.push(tokenizerDir);
  return JSON.parse(execFileSync(process.execPath, args, { cwd, encoding: 'utf8' }));
}

test('counts each pinned fragment separately and refuses partial workflow totals', { skip: !tokenizer }, t => {
  const report = count(t, tokenizer);
  assert.deepEqual(report.workflows, {
    'fixture.complete': { fragments: { 'entry.md': 2, 'reference.md': 2 }, loaded_path_tokens: 4 },
    'fixture.missing': { fragments: { 'entry.md': 2, 'missing.md': null }, loaded_path_tokens: null },
    'fixture.link': { fragments: { 'entry.md': 2, 'link.md': null }, loaded_path_tokens: null },
  });
  assert.deepEqual(report.tokenizer, { package: 'js-tiktoken', version: '1.0.21', encoding: 'o200k_base' });
});

test('unavailable tokenizer leaves a readable workflow unknown', t => {
  const report = count(t);
  assert.deepEqual(report.workflows['fixture.complete'], {
    fragments: { 'entry.md': null, 'reference.md': null }, loaded_path_tokens: null,
  });
});
