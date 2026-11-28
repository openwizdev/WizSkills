#!/usr/bin/env python3
import pathlib
import sys
import urllib.error
import urllib.request

SOURCE_COMMIT = '2b0b0d192d9013f223279d507bc7a809540f66da'
SOURCE_REPO = 'openwizdev/OpenWiz'
SOURCE_PATH = 'tools/comment-check/check.py'
LOCAL = pathlib.Path(__file__).resolve().parent / 'check.py'


def source_bytes():
    url = 'https://raw.githubusercontent.com/' + SOURCE_REPO + '/' + SOURCE_COMMIT + '/' + SOURCE_PATH
    request = urllib.request.Request(url, headers={'User-Agent': 'comment-check-drift'})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
            status = getattr(response, 'status', 200)
    except urllib.error.URLError as error:
        print('comment-check drift: could not read ' + SOURCE_REPO + '@' + SOURCE_COMMIT + ': ' + str(error), file=sys.stderr)
        return None
    if status != 200 or not payload:
        print('comment-check drift: ' + SOURCE_REPO + '@' + SOURCE_COMMIT + ' returned no bytes', file=sys.stderr)
        return None
    return payload


def main():
    source = source_bytes()
    if source is None:
        return 2
    local = LOCAL.read_bytes()
    if local != source:
        print('comment-check drift: ' + SOURCE_PATH + ' differs from ' + SOURCE_REPO + '@' + SOURCE_COMMIT, file=sys.stderr)
        print('source bytes ' + str(len(source)) + ', copy bytes ' + str(len(local)), file=sys.stderr)
        return 1
    print('comment-check drift: ' + SOURCE_PATH + ' matches ' + SOURCE_REPO + '@' + SOURCE_COMMIT)
    return 0


if __name__ == '__main__':
    sys.exit(main())
