#!/usr/bin/env node
const [command] = process.argv.slice(2);
if (command === 'list' || command === 'check' || command === 'brief') {
  process.stderr.write('huntr targets: not built yet\n');
  process.exit(2);
}
process.stderr.write('huntr targets: usage: targets.mjs list|check|brief ...\n');
process.exit(2);
