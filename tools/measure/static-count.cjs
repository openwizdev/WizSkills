'use strict';

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const TOKENIZER = { package: 'js-tiktoken', version: '1.0.21', encoding: 'o200k_base' };
const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true });

function loadTokenizer(directory) {
  if (!directory) return null;
  const root = path.resolve(directory);
  try {
    const metadata = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
    if (metadata.name !== TOKENIZER.package || metadata.version !== TOKENIZER.version) return null;
    return require(root).getEncoding(TOKENIZER.encoding);
  } catch {
    return null;
  }
}

function git(...args) {
  return execFileSync('git', args, { stdio: ['ignore', 'pipe', 'pipe'] });
}

function filesAt(commit) {
  const files = new Map();
  try {
    for (const row of git('ls-tree', '-rz', '--full-tree', commit).toString('utf8').split('\0')) {
      const match = /^100(?:644|755) blob ([a-f0-9]+)\t(.+)$/.exec(row);
      if (match) files.set(match[2], match[1]);
    }
  } catch {
  }
  return files;
}

function countBlob(tokenizer, oid) {
  if (!tokenizer || !oid) return null;
  try {
    const text = decoder.decode(git('cat-file', 'blob', oid));
    return tokenizer.encode(text, [], []).length;
  } catch {
    return null;
  }
}

function createReport(manifest, directory) {
  if (!/^[a-f0-9]{40}$/.test(manifest.commit) ||
      !manifest.workflows || Array.isArray(manifest.workflows) ||
      typeof manifest.workflows !== 'object') {
    throw new Error('invalid manifest');
  }
  const files = filesAt(manifest.commit);
  const tokenizer = loadTokenizer(directory);
  const counts = new Map();
  const workflows = Object.entries(manifest.workflows).map(([id, paths]) => {
    if (!Array.isArray(paths) || !paths.length || paths.some(file =>
      typeof file !== 'string' || !file || /[\u0000-\u001f]/.test(file) ||
      file.split('/').some(part => !part || part === '.' || part === '..'))) {
      throw new Error('invalid workflow fragments');
    }
    const fragments = Object.fromEntries([...new Set(paths)].map(file => {
      if (!counts.has(file)) counts.set(file, countBlob(tokenizer, files.get(file)));
      return [file, counts.get(file)];
    }));
    const values = Object.values(fragments);
    return [id, {
      fragments,
      loaded_path_tokens: values.includes(null) ? null : values.reduce((sum, count) => sum + count, 0),
    }];
  });
  return { commit: manifest.commit, tokenizer: TOKENIZER, workflows: Object.fromEntries(workflows) };
}

try {
  if (process.argv.length < 3 || process.argv.length > 4) throw new Error('bad arguments');
  const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  console.log(JSON.stringify(createReport(manifest, process.argv[3]), null, 2));
} catch {
  console.error('usage: node static-count.cjs <manifest.json> [js-tiktoken package directory]');
  process.exitCode = 2;
}
