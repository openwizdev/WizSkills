#!/usr/bin/env node
const [command] = process.argv.slice(2);
if (command === 'route' || command === 'issue') {
  process.stderr.write('huntr findings: not built yet\n');
  process.exit(2);
}
process.stderr.write('huntr findings: usage: findings.mjs route|issue ...\n');
process.exit(2);
