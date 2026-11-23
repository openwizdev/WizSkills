import hashlib
import json
import os
import subprocess


def env(root, fleets):
    base = os.path.join(str(root), 'git-origin', hashlib.sha256(json.dumps(fleets, sort_keys=True).encode()).hexdigest())
    origins = os.path.join(base, 'origins')
    ident = dict(os.environ, GIT_AUTHOR_NAME='Synthetic', GIT_AUTHOR_EMAIL='synthetic@example.invalid',
                 GIT_COMMITTER_NAME='Synthetic', GIT_COMMITTER_EMAIL='synthetic@example.invalid',
                 GIT_INDEX_FILE=os.path.join(base, 'index'))
    for repo, text in fleets.items():
        bare = os.path.join(origins, repo + '.git')
        if os.path.isdir(bare):
            continue
        path, text = ('README.md', 'synthetic\n') if text is None else ('docs/agents/fleet.md', text)

        def git(*args, stdin=None):
            return subprocess.run(['git', '--git-dir', bare, *args], env=ident, input=stdin, check=True,
                                  capture_output=True, text=True, timeout=60).stdout.strip()

        subprocess.run(['git', 'init', '--quiet', '--bare', bare], env=ident, check=True, capture_output=True,
                       timeout=60)
        blob = git('hash-object', '-w', '--stdin', stdin=text)
        if os.path.exists(ident['GIT_INDEX_FILE']):
            os.unlink(ident['GIT_INDEX_FILE'])
        git('update-index', '--add', '--cacheinfo', f'100644,{blob},{path}')
        commit = git('commit-tree', git('write-tree'), '-m', 'synthetic')
        git('update-ref', 'HEAD', commit)
    return {'GITREAD_LOCAL_ONLY': '1', 'XDG_CACHE_HOME': os.path.join(base, 'cache'), 'GIT_CONFIG_COUNT': '1',
            'GIT_CONFIG_KEY_0': f'url.file://{origins}/.insteadOf', 'GIT_CONFIG_VALUE_0': 'https://github.com/'}
