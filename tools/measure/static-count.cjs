'use strict';
const fs = require('node:fs');
const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
console.log(JSON.stringify({
  commit: manifest.commit,
  workflows: Object.fromEntries(Object.entries(manifest.workflows).map(([id, paths]) => [
    id, { fragments: Object.fromEntries(paths.map(path => [path, 0])), loaded_path_tokens: 0 },
  ])),
}));
