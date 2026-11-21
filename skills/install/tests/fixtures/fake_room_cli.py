#!/usr/bin/env python3
import json
import os
import signal
import sys


def main(argv):
    with open(os.environ['FAKE_ROOM_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(argv) + '\n')
    path = os.environ['FAKE_ROOM_SCRIPT']
    with open(path, encoding='utf-8') as handle:
        script = json.load(handle)
    queue = script.get('spawn') if argv[:2] == ['thread', 'spawn'] else None
    if not queue:
        sys.stderr.write('fake room-cli: unexpected call\n')
        return 99
    answer = queue.pop(0)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(script, handle)
    if answer.get('kill_caller'):
        os.kill(os.getppid(), signal.SIGKILL)
    sys.stdout.write(answer.get('stdout', ''))
    return answer['exit']


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
