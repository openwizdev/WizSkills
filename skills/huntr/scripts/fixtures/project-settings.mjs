import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';

export function projectSettings(start = process.cwd()) {
  for (let folder = start; ; folder = dirname(folder)) {
    const file = join(folder, 'docs/agents/huntr.md');
    if (existsSync(file)) return file;
    if (dirname(folder) === folder) return join(start, 'docs/agents/huntr.md');
  }
}
