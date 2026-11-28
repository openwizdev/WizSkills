#!/usr/bin/env python3
import json
import sys


def main(argv=None):
    for raw in sys.stdin.buffer:
        try:
            obj = json.loads(raw.decode("utf-8"))
        except Exception:
            reply = {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}
        else:
            req_id = obj.get("id") if isinstance(obj, dict) else None
            if req_id is None:
                continue
            reply = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "Method not found"}}
        sys.stdout.buffer.write((json.dumps(reply) + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
