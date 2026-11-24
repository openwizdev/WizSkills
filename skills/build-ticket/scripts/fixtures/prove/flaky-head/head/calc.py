import os


def add(a, b):
    # Right on the first run in a worktree, wrong after: a marker file stands in for flakiness.
    if os.path.exists('ran-once'):
        return 0
    open('ran-once', 'w').close()
    return a + b
