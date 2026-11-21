#!/usr/bin/env python3
import json
import os
import sys


def form(argv):
    if len(argv) == 3 and argv[0] == 'fleet' and argv[1].isdigit() and argv[2] == '--json':
        return 'fleet'
    return None


def main():
    argv = sys.argv[1:]
    name = form(argv)
    entry = {'argv': argv, 'form': name}
    with open(os.environ['FAKE_OPENWIZ_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(entry, sort_keys=True) + '\n')
    script_path = os.environ['FAKE_OPENWIZ_SCRIPT']
    with open(script_path, encoding='utf-8') as handle:
        script = json.load(handle)
    queue = script.get(name) if name else None
    if not queue:
        sys.stderr.write('fake openwiz: unexpected call\n')
        return 99
    answer = queue.pop(0)
    with open(script_path, 'w', encoding='utf-8') as handle:
        json.dump(script, handle)
    out = answer.get('stdout', '')
    if not isinstance(out, str):
        out = json.dumps(out) + '\n'
    sys.stdout.write(out)
    return answer['exit']


if __name__ == '__main__':
    sys.exit(main())
