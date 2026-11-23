"""A synthetic stand-in for the fake host in OpenWiz's kernel/driver-kit/kit.py, for write-driver's own tests only.

FakeHost takes the real one's arguments that write-driver's expired-login probe passes (status, body, test_key) and
keeps the same records: requests, each as its request line, its headers and its body, and fetches, one flag per
test-key request. It gives its test key at /.openwiz/hostkey-test-key and answers everything else with status.
The real fake host is OpenWiz's; its own tests and write-driver's WRITE_DRIVER_OPENWIZ test run it.
"""
import http.server
import json
import threading

KEY_PATH = '/.openwiz/hostkey-test-key'


class FakeHost:
    def __init__(self, status=200, headers=(), body=b'{}', answers=(), test_key=None, trust=None, phase=None):
        self.requests, self.fetches = [], []
        self.lock = threading.Lock()
        host = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def answer(self):
                sent = self.rfile.read(int(self.headers.get('Content-Length') or 0))
                if self.path == KEY_PATH:
                    given = test_key is not None and self.command == 'GET'
                    with host.lock:
                        host.fetches.append(given)
                    code, data = (200, json.dumps({'key': test_key}).encode()) if given else (404, b'{}')
                else:
                    with host.lock:
                        host.requests.append((self.requestline, list(self.headers.items()), sent))
                    code, data = status, body
                self.send_response(code)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = answer

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
