import json
import os
from pathlib import Path
import sys

path = Path(os.environ['GOLDEN_WORLD'])
world = json.loads(path.read_text())
args = sys.argv[1:]
if args[:1] != ['api']:
    sys.exit(3)
url = args[-1]
repo = 'repos/' + world['repo']
issue = f'{repo}/issues/{world["pr"]}'
if url == repo:
    answer = {'full_name': world['repo'], 'private': True, 'visibility': 'private'}
elif url == f'{repo}/pulls/{world["pr"]}':
    answer = {'number': world['pr'], 'state': 'open', 'head': {'sha': world['head'], 'repo': {'full_name': world['repo']}}}
elif url == f'{repo}/contents/{world["file"]}?ref={world["head"]}':
    answer = {'encoding': 'base64', 'content': world['source'], 'path': world['file']}
elif url == issue + '/comments':
    if args[1:3] == ['-X', 'POST']:
        answer = {'id': 81 + len(world['comments']), 'issue_url': 'https://api.github.com/' + issue,
                  **json.load(sys.stdin)}
        world['comments'].append(answer)
        path.write_text(json.dumps(world))
    else:
        answer = [world['comments']]
elif url.startswith(f'{repo}/issues/comments/'):
    comment = world['comments'][int(url.rsplit('/', 1)[1]) - 81]
    if args[1:3] == ['-X', 'PATCH']:
        comment.update(json.load(sys.stdin))
        path.write_text(json.dumps(world))
    answer = comment
else:
    sys.exit(4)
print(json.dumps(answer))
