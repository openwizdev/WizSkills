"""The paid role run (contract.md, section 6): the model acts through the fake shell.

Standard library only (no new dependency). The only network call is the model
API; the agent's commands run in `fakeworld.World`, in process.
"""
import json
import math
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # `driver.py mcp-relay` runs under python3 -I
import fakeworld  # noqa: E402
import records  # noqa: E402

API = 'https://api.anthropic.com/v1/messages'
OPENROUTER_API = 'https://openrouter.ai/api/v1/chat/completions'
SYSTEM = ('You are a coding agent working in a cloud sandbox. The repository checkout is '
          '/repo, the current directory. You have one tool, `shell`, which runs a command in '
          'the sandbox and returns its output and exit code. Do the task in the first '
          'message, following the instructions it points you to, then end your turn with a '
          'short reply saying what you did and why.')
TOOL = {'name': 'shell', 'description': 'Run one shell command in the sandbox; returns its output and exit code.',
        'input_schema': {'type': 'object', 'additionalProperties': False, 'required': ['command'],
                         'properties': {'command': {'type': 'string', 'description': 'The command to run.'}}}}
OUT_LIMIT = 30000


class TransportError(Exception):
    """A failed model request. `retryable`: refused before any work (429, 529), so retrying is safe;
    `uncertain`: the request may have been processed and charged."""

    def __init__(self, msg, retryable=False, uncertain=False):
        super().__init__(msg)
        self.retryable, self.uncertain = retryable, uncertain


def http_post(key, version):
    """One attempt per call; the driver decides about retries, each one reserved against the cap."""
    def post(url, body):
        if version == 'openrouter':
            if url != OPENROUTER_API:
                raise ValueError('OpenRouter transport refuses another endpoint')
            headers = {'Authorization': f'Bearer {key}', 'content-type': 'application/json'}
        else:
            headers = {'x-api-key': key, 'anthropic-version': version, 'content-type': 'application/json'}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST', headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise TransportError(f'HTTP {e.code}', retryable=version != 'openrouter' and e.code in (429, 529),
                                 uncertain=version == 'openrouter' or (e.code >= 500 and e.code != 529)) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            raise TransportError(f'network: {e}', uncertain=True) from None
    return post


def cost(usage, prices):
    return sum(usage.get(k, 0) * prices[k] for k in prices) / 1e6


def reserve(body, settings):
    """A conservative cost bound for one request: every request byte as an uncached input token
    at the dearest input price, plus a full `max_tokens` of output."""
    p = settings['prices_usd_per_mtok']
    size = len(json.dumps(body).encode())
    return ((size + 4096) * max(p['input_tokens'], p['cache_creation_input_tokens']) + body['max_tokens'] * p['output_tokens']) / 1e6


def openrouter_request(body, settings):
    """Convert the driver conversation to chat completions; no model command runs here."""
    messages = [{'role': 'system', 'content': body['system']}]
    for m in body['messages']:
        content = m['content']
        if isinstance(content, str):
            messages.append(dict(m))
            continue
        if m['role'] == 'assistant':
            msg = {'role': 'assistant', 'content': '\n'.join(b.get('text', '') for b in content if b['type'] == 'text') or None}
            calls = []
            for b in content:
                if b['type'] == 'tool_use':
                    calls.append({'id': b['id'], 'type': 'function', 'function': {
                        'name': b['name'], 'arguments': json.dumps(b['input'])}})
                elif b['type'] == 'reasoning_details':
                    msg['reasoning_details'] = b['details']
            if calls:
                msg['tool_calls'] = calls
            messages.append(msg)
        else:
            for b in content:
                messages.append({'role': 'tool', 'tool_call_id': b['tool_use_id'], 'content': b['content']})
    prices = settings['prices_usd_per_mtok']
    request = {'model': body['model'], 'messages': messages, 'max_tokens': body['max_tokens'],
               'reasoning': {'effort': settings['effort']},
               'provider': {'require_parameters': True,
                            'max_price': {'prompt': prices['input_tokens'], 'completion': prices['output_tokens']}}}
    if body.get('tools'):
        request['tools'] = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                             'parameters': t['input_schema']}} for t in body['tools']]
    return request


def openrouter_response(resp):
    """Validate usage before accepting a charged response; preserve raw provider counts."""
    raw = resp['usage']
    for key in ('prompt_tokens', 'completion_tokens'):
        if type(raw.get(key)) is not int or raw[key] < 0:
            raise ValueError('missing or invalid OpenRouter usage')
    cached = (raw.get('prompt_tokens_details') or {}).get('cached_tokens', 0)
    if type(cached) is not int or not 0 <= cached <= raw['prompt_tokens']:
        raise ValueError('invalid cached token count')
    charged = raw.get('cost')
    if charged is not None and (type(charged) not in (int, float) or not math.isfinite(charged) or charged < 0):
        raise ValueError('invalid OpenRouter cost')
    choice = resp['choices'][0]
    msg = choice['message']
    content = []
    if msg.get('reasoning_details'):
        content.append({'type': 'reasoning_details', 'details': msg['reasoning_details']})
    if msg.get('content'):
        if not isinstance(msg['content'], str):
            raise ValueError('invalid assistant content')
        content.append({'type': 'text', 'text': msg['content']})
    for t in msg.get('tool_calls') or []:
        if t.get('type') != 'function' or not isinstance(t.get('id'), str):
            raise ValueError('invalid tool call')
        args = records.strict_json(t['function']['arguments'])
        if not isinstance(args, dict):
            raise ValueError('tool arguments must be an object')
        content.append({'type': 'tool_use', 'id': t['id'], 'name': t['function']['name'], 'input': args})
    reason = {'stop': 'end_turn', 'tool_calls': 'tool_use', 'length': 'max_tokens',
              'content_filter': 'refusal'}.get(choice.get('finish_reason'), 'error')
    if reason == 'tool_use' and not any(b['type'] == 'tool_use' for b in content):
        raise ValueError('tool finish without calls')
    return {'content': content, 'stop_reason': reason, 'provider_usage': raw,
            'usage': {'input_tokens': raw['prompt_tokens'] - cached, 'output_tokens': raw['completion_tokens'],
                      'cache_read_input_tokens': cached, 'cache_creation_input_tokens': 0}}


JUDGE = ('You check one reply an agent gave at the end of a task. You see only the rule the reply must meet '
         'and the reply. Decide whether the reply meets the rule. Answer with only a JSON object: '
         '{"verdict": "pass" or "fail", "reason": "<one sentence>"}.')


def judge(rubric, final, settings, call):
    """An independent judgment of the final reply alone. Returns (judgment, stop or None).
    Only a completed reply that is one strict JSON object, exactly {verdict, reason}, counts."""
    body = {'model': settings['judge_model'], 'max_tokens': settings.get('judge_max_tokens', 1000), 'system': JUDGE,
            'messages': [{'role': 'user', 'content': f'Rule:\n{rubric}\n\nReply:\n<<<\n{final}\n>>>'}]}
    resp, stop, error = call(body)
    if resp is None:
        return {'verdict': None, 'reason': None, 'error': f'not judged: {error or stop}'}, ('cap' if stop == 'cap' else None)
    text = ''.join(b.get('text', '') for b in resp.get('content') or [] if b.get('type') == 'text').strip()
    invalid = {'verdict': 'invalid', 'reason': None, 'raw': text[:300], 'stop': resp.get('stop_reason')}
    if resp.get('stop_reason') != 'end_turn':
        return invalid, None
    try:
        j = records.strict_json(text)
    except ValueError:
        return invalid, None
    if (not isinstance(j, dict) or set(j) != {'verdict', 'reason'} or j['verdict'] not in ('pass', 'fail')
            or not isinstance(j['reason'], str) or not j['reason'].strip()):
        return invalid, None
    return {'verdict': j['verdict'], 'reason': j['reason'], 'model': settings['judge_model']}, None


def run_case(case, settings, snapshot, post, repeat, budget_usd=None, checkpoint=None):
    """One role run. Returns the transcript (contract.md, section 4), complete or not; never raises."""
    if settings.get('provider') == 'hermes':
        return hermes_run_case(case, settings, snapshot, repeat, budget_usd, checkpoint)
    world = fakeworld.World(case['world'], snapshot)
    messages = [{'role': 'user', 'content': case['brief']}]
    usage = {'input_tokens': 0, 'output_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}
    prices = settings['prices_usd_per_mtok']
    stop, final, error, judgment = None, '', None, None

    uncertain = [0.0]
    charged = [0.0]
    provider_usage = []
    is_openrouter = settings.get('provider') == 'openrouter'

    def spend(body, used=None):
        """With a body: may this request start inside the budget? With `used`: add its usage."""
        if used is not None:
            for k in usage:
                usage[k] += used.get(k) or 0
            return True
        return budget_usd is None or charged[0] + uncertain[0] + reserve(body, settings) <= budget_usd

    def call(body):
        """(response, None) or (None, stop, error). Every attempt is reserved first; an attempt whose usage
        is unknown keeps its reservation as spent and ends the run."""
        if is_openrouter:
            body = openrouter_request(body, settings)
        for attempt in range(4):
            if not spend(body):
                return None, 'cap', None
            if checkpoint:
                bound = round(charged[0] + uncertain[0] + reserve(body, settings), 9)
                checkpoint({'case': case['id'], 'repeat': repeat, 'stop': 'error', 'final': final,
                            'events': world.events, 'usage': dict(usage), 'provider_usage': list(provider_usage),
                            'cost_usd': bound, 'uncertain_usd': round(uncertain[0] + reserve(body, settings), 9),
                            'error': 'Interrupted request: reservation retained; never automatically retried',
                            'judgment': None, 'turns': sum(m['role'] == 'assistant' for m in messages)})
            try:
                resp = post(OPENROUTER_API if is_openrouter else API, body)
                if is_openrouter:
                    resp = openrouter_response(resp)
            except TransportError as e:
                if e.uncertain:
                    uncertain[0] += reserve(body, settings)
                    return None, 'error', f'{e} (usage unknown: its reservation is kept as spent)'
                if e.retryable and attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                return None, 'error', str(e)[:500]
            except Exception as e:  # noqa: BLE001 - an unknown failure may have been charged
                uncertain[0] += reserve(body, settings)
                return None, 'error', str(e)[:500]
            used = resp.get('usage') or {}
            if is_openrouter:
                provider_usage.append(resp['provider_usage'])
            billed = resp.get('provider_usage', {}).get('cost')
            charged[0] += cost(used, prices) if billed is None else billed
            spend(None, used)  # every successful response, the judge's too, counted once here
            return resp, None, None
        return None, 'error', 'retries exhausted'

    for _ in range(settings['max_turns']):
        body = {'model': settings['model'], 'max_tokens': settings['max_tokens'], 'system': SYSTEM,
                'tools': [TOOL], 'messages': messages, 'thinking': {'type': 'adaptive'},
                'output_config': {'effort': settings['effort']}, 'cache_control': {'type': 'ephemeral'}}
        resp, stop, error = call(body)
        if resp is None:
            break
        content = resp.get('content') or []
        messages.append({'role': 'assistant', 'content': content})
        final = '\n'.join(b.get('text', '') for b in content if b.get('type') == 'text').strip()
        reason = resp.get('stop_reason')
        if reason != 'tool_use':
            stop = {'end_turn': 'end_turn', 'stop_sequence': 'end_turn'}.get(reason, reason or 'error')
            break
        results = []
        try:
            for b in content:
                if b.get('type') != 'tool_use':
                    continue
                cmd = (b.get('input') or {}).get('command')
                if b.get('name') != 'shell' or not isinstance(cmd, str):
                    out = 'error: the only tool is shell, with one string `command`'
                else:
                    r = world.shell(cmd)
                    out = r.out if len(r.out) <= OUT_LIMIT else r.out[:OUT_LIMIT] + f'\n... (output cut at {OUT_LIMIT} characters)'
                    out = f'{out}\n[exit {r.code}]'
                results.append({'type': 'tool_result', 'tool_use_id': b['id'], 'content': out})
        except Exception as e:  # noqa: BLE001 - a fake-shell fault ends the run, recorded
            stop, error = 'error', f'fake shell failed: {type(e).__name__}: {str(e)[:300]}'
            break
        messages.append({'role': 'user', 'content': results})
    else:
        stop = 'turn_cap'
    if stop == 'end_turn' and case.get('expect', {}).get('final'):
        judgment, jstop = judge(case['expect']['final'], final, settings, call)
        stop = jstop or stop
    return {'provider_usage': provider_usage,
            'tokenizer': 'DeepSeek (OpenRouter provider usage; not Claude tokens)' if is_openrouter else 'Anthropic',
            'case': case['id'], 'repeat': repeat, 'stop': stop, 'final': final,
            'events': world.events, 'usage': usage, 'cost_usd': round(charged[0] + uncertain[0], 9),
            'uncertain_usd': round(uncertain[0], 9), 'error': error, 'judgment': judgment, 'turns': sum(1 for m in messages if m['role'] == 'assistant')}


# ---- Hermes route (#1362; A1 as revised 2026-11-13: Hermes Nous login) --------------------------
# Hermes is the harness; the case, fake shell, scorer and cap stay frozen. Hermes reaches the fake shell
# only through one MCP tool (`driver.py mcp-relay`), and the model only through `ModelProxy`, a loopback
# endpoint in this process that checks, bounds and accounts every outbound attempt. The only credential is
# the sandbox's Hermes Nous login, copied into each session; this process holds no API key.

HERMES_TOOL = 'mcp__eval__shell'
HERMES_TOOLSET = 'mcp-eval'
HERMES_TOKENIZER = 'DeepSeek V4.1 Flash via Nous (Hermes session usage; not Claude tokens)'
HERMES_KEYS = {'program': str, 'login_home': str, 'version': str, 'provider': str, 'model': str, 'upstream': str,
               'prices_usd_per_mtok': dict, 'max_input_tokens_per_call': int, 'max_api_calls': int,
               'judge_max_api_calls': int, 'judge_toolsets': str, 'timeout_s': int, 'config': dict, 'source': str,
               'portal_hosts': list}
PRICE_KEYS = {'input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens'}
USAGE_COLUMNS = ('input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens',
                 'api_call_count')
RELOGIN = 'sign in again with `hermes auth` (Nous Portal) on this machine'


def hermes_settings(settings):
    """The exact Hermes route block, or ValueError: a malformed route never starts a session."""
    h = settings.get('hermes')
    if not isinstance(h, dict) or set(h) != set(HERMES_KEYS) or any(type(h[k]) is not v for k, v in HERMES_KEYS.items()):
        raise ValueError('invalid hermes route settings')
    p = h['prices_usd_per_mtok']
    if set(p) != PRICE_KEYS or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in p.values()):
        raise ValueError('invalid hermes prices')
    if min(h['max_input_tokens_per_call'], h['max_api_calls'], h['judge_max_api_calls'], h['timeout_s']) < 1:
        raise ValueError('invalid hermes bounds')
    if not (h['upstream'].startswith('https://') or h['upstream'].startswith('http://127.0.0.1:')) or h['provider'] != 'nous':
        raise ValueError('the hermes route sends only to an https (or loopback) Nous upstream')
    if any(k in h['config'] for k in ('model', 'mcp_servers')):
        raise ValueError('hermes config may not set model or mcp_servers; the driver writes them')
    if not h['portal_hosts'] or not all(isinstance(x, str) and x and '/' not in x and ':' not in x for x in h['portal_hosts']):
        raise ValueError('invalid hermes portal hosts')
    return h


def hermes_attempt_bound(h, input_tokens, max_tokens):
    p = h['prices_usd_per_mtok']
    return (input_tokens * max(p['input_tokens'], p['cache_creation_input_tokens']) + max_tokens * p['output_tokens']) / 1e6


def hermes_reserve(h, max_tokens, calls):
    """A whole session's bound: every allowed attempt at the full input bound, uncached, plus full output."""
    return calls * hermes_attempt_bound(h, h['max_input_tokens_per_call'], max_tokens)


def usage_cost(u, h):
    """One attempt's cost from the provider's own usage, or None when it is missing or malformed. Reasoning
    is charged as output on top of completion tokens, and a reported cost wins when higher: overlaps can
    only overcharge."""
    if not isinstance(u, dict):
        return None
    prompt, completion = u.get('prompt_tokens'), u.get('completion_tokens')
    cached = (u.get('prompt_tokens_details') or {}).get('cached_tokens', 0) if isinstance(u.get('prompt_tokens_details') or {}, dict) else None
    reasoning = (u.get('completion_tokens_details') or {}).get('reasoning_tokens', 0) if isinstance(u.get('completion_tokens_details') or {}, dict) else None
    if any(type(x) is not int or x < 0 for x in (prompt, completion, cached, reasoning)) or cached > prompt:
        return None
    p = h['prices_usd_per_mtok']
    cost = ((prompt - cached) * p['input_tokens'] + cached * p['cache_read_input_tokens']
            + (completion + reasoning) * p['output_tokens']) / 1e6
    billed = u.get('cost')
    if billed is not None and (type(billed) not in (int, float) or not math.isfinite(billed) or billed < 0):
        return None
    return max(cost, billed or 0)


class suppress_oserror:
    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        return kind is not None and issubclass(kind, OSError)


class ModelProxy:
    """Hermes's NOUS_INFERENCE_BASE_URL for one session. Before an attempt leaves, it must name the route's
    model, fit the attempt count and input bound, and carry max_tokens at or under the cap (clamped);
    streams always ask for usage. Hermes's own bearer is passed to the fixed upstream unchanged. Each
    attempt reserves its bound until its usage arrives; `close()` freezes the accounting, so an attempt
    still open then (an interrupted stream, a killed session) stays uncertain.

    It is also the session's only HTTP(S) proxy (HTTPS_PROXY and friends, with NO_PROXY naming just this
    endpoint), so routing does not depend on Hermes keeping NOUS_INFERENCE_BASE_URL: after a credential
    refresh or client rebuild, a request to any other endpoint arrives here as CONNECT or an absolute URL
    and is refused before it leaves. Only CONNECT to the login's Nous Portal (token refresh, port 443) is
    tunnelled."""

    def __init__(self, h, max_tokens, calls_cap):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        self.h, self.max_tokens, self.calls_cap = h, max_tokens, calls_cap
        self.lock, self.closed, self.attempts, self.refused, self.final = threading.Lock(), False, [], [], None
        self.escapes = []
        proxy = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *a):
                pass

            def do_GET(self):
                proxy._offroute(self) or proxy._get(self)

            def do_POST(self):
                proxy._offroute(self) or proxy._post(self)

            def do_CONNECT(self):
                proxy._connect(self)

            def __getattr__(self, name):  # any other method, any target: refused
                if name.startswith('do_'):
                    return lambda: proxy._offroute(self, always=True)
                raise AttributeError(name)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.server.handle_error = lambda *a: None  # a client gone mid-reply is accounted, not printed
        self.endpoint = f'127.0.0.1:{self.server.server_address[1]}'
        self.url = f'http://{self.endpoint}/v1'
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @staticmethod
    def _reply(handler, code, obj):
        data = json.dumps(obj).encode()
        handler.send_response(code)
        handler.send_header('Content-Type', 'application/json')
        handler.send_header('Content-Length', str(len(data)))
        handler.send_header('Connection', 'close')
        handler.end_headers()
        handler.wfile.write(data)

    def _headers(self, handler, accept):
        out = {'Content-Type': 'application/json', 'Accept': accept}
        for k, v in handler.headers.items():
            if k.lower() in ('authorization', 'user-agent') or k.lower().startswith('x-'):
                out[k] = v
        return out

    def proxy_env(self):
        """Every proxy variable Hermes and its clients read, all naming this endpoint."""
        url = f'http://{self.endpoint}'
        env = {k: url for k in ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'https_proxy', 'http_proxy', 'all_proxy')}
        env.update(NO_PROXY=self.endpoint, no_proxy=self.endpoint)
        return env

    def _offroute(self, handler, always=False):
        """A proxied request for another endpoint (an absolute URL) is refused; True when refused."""
        if not always and handler.path.startswith('/'):
            return False
        with self.lock:
            self.escapes.append(f'{handler.command} {handler.path[:200]}')
        self._reply(handler, 403, {'error': {'message': 'skills-eval proxy: only the eval endpoint is reachable'}})
        return True

    def _connect(self, handler):
        host, _, port = handler.path.rpartition(':')
        with self.lock:
            allowed = not self.closed and port == '443' and host in self.h['portal_hosts']
            if not allowed:
                self.escapes.append(f'CONNECT {handler.path[:200]}')
        if not allowed:
            return self._reply(handler, 403, {'error': {'message': 'skills-eval proxy: only the Nous Portal is reachable'}})
        try:
            upstream = socket.create_connection((host, 443), timeout=30)
        except OSError:
            return self._reply(handler, 502, {'error': {'message': 'skills-eval proxy: portal unreachable'}})
        handler.send_response(200, 'Connection established')
        handler.end_headers()
        handler.wfile.flush()
        client = handler.connection

        def pump(a, b):
            try:
                while True:
                    data = a.recv(65536)
                    if not data:
                        break
                    b.sendall(data)
            except OSError:
                pass
            finally:
                with suppress_oserror():
                    b.shutdown(socket.SHUT_WR)
        other = threading.Thread(target=pump, args=(upstream, client), daemon=True)
        other.start()
        pump(client, upstream)
        other.join(timeout=60)
        upstream.close()
        handler.close_connection = True

    def _get(self, handler):
        if handler.path.rstrip('/') != '/v1/models':  # model listing is free; nothing else is forwarded
            return self._reply(handler, 404, {'error': {'message': 'skills-eval proxy: not found'}})
        try:
            req = urllib.request.Request(self.h['upstream'].rstrip('/') + '/models', headers=self._headers(handler, 'application/json'))
            with urllib.request.urlopen(req, timeout=60) as r:
                return self._reply(handler, r.status, json.loads(r.read()))
        except Exception:  # noqa: BLE001 - a listing failure costs nothing
            return self._reply(handler, 502, {'error': {'message': 'skills-eval proxy: upstream listing failed'}})

    def _refuse(self, handler, problem):
        self.refused.append(problem)
        self._reply(handler, 400, {'error': {'message': f'skills-eval proxy refused: {problem}', 'type': 'invalid_request_error'}})

    def _post(self, handler):
        if handler.path.rstrip('/') != '/v1/chat/completions':
            return self._reply(handler, 404, {'error': {'message': 'skills-eval proxy: not found'}})
        try:
            body = records.strict_json(handler.rfile.read(int(handler.headers.get('Content-Length') or 0)).decode())
        except (ValueError, UnicodeDecodeError):
            body = None
        with self.lock:
            if self.closed:
                problem = 'the session has ended'
            elif not isinstance(body, dict) or body.get('model') != self.h['model']:
                problem = f"only {self.h['model']} is allowed"
            elif len(self.attempts) >= self.calls_cap:
                problem = f'the attempt bound of {self.calls_cap} is reached'
            else:
                problem = None
                limits = [k for k in ('max_tokens', 'max_completion_tokens') if k in body]
                for k in limits:
                    v = body[k]
                    body[k] = v if type(v) is int and 0 < v <= self.max_tokens else self.max_tokens
                if not limits:
                    body['max_tokens'] = self.max_tokens
                if body.get('stream'):
                    so = body.get('stream_options') if isinstance(body.get('stream_options'), dict) else {}
                    body['stream_options'] = dict(so, include_usage=True)
                data = json.dumps(body).encode()
                tokens = len(data) + 4096  # every request byte as a token, plus template slack
                if tokens > self.h['max_input_tokens_per_call']:
                    problem = f"the request is over the input bound of {self.h['max_input_tokens_per_call']} tokens"
                else:
                    attempt = {'bound': hermes_attempt_bound(self.h, tokens, self.max_tokens), 'cost': None,
                               'usage': None, 'status': None}
                    self.attempts.append(attempt)
        if problem:
            return self._refuse(handler, problem)
        accept = 'text/event-stream' if body.get('stream') else 'application/json'
        req = urllib.request.Request(self.h['upstream'].rstrip('/') + '/chat/completions', data=data, method='POST',
                                     headers=self._headers(handler, accept))
        try:
            resp = urllib.request.urlopen(req, timeout=self.h['timeout_s'])
        except urllib.error.HTTPError as e:  # its usage is unknown: the attempt stays reserved
            attempt['status'] = e.code
            try:
                payload = json.loads(e.read() or b'{}')
            except ValueError:
                payload = {'error': {'message': f'upstream HTTP {e.code}'}}
            return self._reply(handler, e.code, payload)
        except Exception:  # noqa: BLE001 - may have been processed: stays reserved
            return self._reply(handler, 502, {'error': {'message': 'skills-eval proxy: upstream failed'}})
        usage, alive = None, True
        with resp:
            attempt['status'] = resp.status
            streaming = 'text/event-stream' in (resp.headers.get('Content-Type') or '')
            try:
                handler.send_response(resp.status)
                handler.send_header('Content-Type', resp.headers.get('Content-Type') or accept)
                handler.send_header('Connection', 'close')
                if not streaming:
                    raw = resp.read()
                    handler.send_header('Content-Length', str(len(raw)))
                handler.end_headers()
            except OSError:
                alive = False
            if streaming:
                for line in resp:  # keep reading after Hermes goes away: the usage still arrives here
                    if alive:
                        try:
                            handler.wfile.write(line)
                            handler.wfile.flush()
                        except OSError:
                            alive = False
                    s = line.strip()
                    if s.startswith(b'data:') and s[5:].strip() not in (b'', b'[DONE]'):
                        try:
                            chunk = json.loads(s[5:])
                        except ValueError:
                            continue
                        if isinstance(chunk, dict) and isinstance(chunk.get('usage'), dict):
                            usage = chunk['usage']
            else:
                if alive:
                    try:
                        handler.wfile.write(raw)
                    except OSError:
                        pass
                try:
                    usage = json.loads(raw).get('usage')
                except (ValueError, AttributeError):
                    usage = None
        with self.lock:
            attempt['usage'], attempt['cost'] = usage, usage_cost(usage, self.h)

    def close(self):
        """Stop taking attempts and freeze the accounting."""
        with self.lock:
            self.closed = True
            done = [a for a in self.attempts if a['cost'] is not None]
            self.final = {'forwarded': len(self.attempts), 'accounted': len(done), 'refused': list(self.refused),
                          'cost': sum(a['cost'] for a in done),
                          'uncertain': sum(a['bound'] for a in self.attempts if a['cost'] is None),
                          'usage': [a['usage'] for a in done], 'escapes': list(self.escapes)}
        self.server.shutdown()
        self.server.server_close()
        return self.final


def hermes_session(home):
    """Read the one session in an isolated HERMES_HOME, read-only: (usage, messages). ValueError if absent or odd."""
    db = Path(home) / 'state.db'
    if not db.is_file():
        raise ValueError('no Hermes session store')
    con = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    try:
        rows = con.execute('SELECT id, ' + ', '.join(USAGE_COLUMNS) + ' FROM sessions').fetchall()
        if len(rows) != 1:
            raise ValueError(f'expected exactly one Hermes session, found {len(rows)}')
        sid, *counts = rows[0]
        if any(type(c) is not int or c < 0 for c in counts):
            raise ValueError('missing or invalid Hermes session usage')
        msgs = con.execute('SELECT role, content, tool_calls FROM messages WHERE session_id = ? ORDER BY id', (sid,)).fetchall()
    except sqlite3.Error as e:
        raise ValueError(f'unreadable Hermes session store: {e}') from None
    finally:
        con.close()
    return dict(zip(USAGE_COLUMNS, counts), session=sid), msgs


def hermes_calls(tool_calls):
    """Tool names in one stored assistant message; ValueError on anything but a list of function calls."""
    if tool_calls in (None, '', '[]'):
        return []
    calls = records.strict_json(tool_calls)
    if not isinstance(calls, list):
        raise ValueError('invalid stored tool calls')
    names = []
    for c in calls:
        f = c.get('function') if isinstance(c, dict) else None
        if not isinstance(f, dict) or not isinstance(f.get('name'), str):
            raise ValueError('invalid stored tool call')
        names.append(f['name'])
    return names


class ShellRelay:
    """A Unix socket in the run's private folder; each line {"command": str} runs in the case's World."""

    def __init__(self, world, folder):
        self.world, self.calls, self.fault, self.connected = world, 0, None, False
        self.path = str(Path(folder) / 'shell.sock')
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        os.chmod(self.path, 0o600)
        self.server.listen(4)
        self.lock = threading.Lock()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.connected = True
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn, conn.makefile('rwb') as f:
            for line in f:
                try:
                    cmd = records.strict_json(line.decode())
                    cmd = cmd.get('command') if isinstance(cmd, dict) and set(cmd) == {'command'} else None
                    if not isinstance(cmd, str):
                        reply = {'text': 'error: the only tool is shell, with one string `command`'}
                    else:
                        with self.lock:
                            self.calls += 1
                            r = self.world.shell(cmd)
                        out = r.out if len(r.out) <= OUT_LIMIT else r.out[:OUT_LIMIT] + f'\n... (output cut at {OUT_LIMIT} characters)'
                        reply = {'text': f'{out}\n[exit {r.code}]'}
                except Exception as e:  # noqa: BLE001 - a fake-shell fault ends the run, recorded
                    self.fault = f'fake shell failed: {type(e).__name__}: {str(e)[:300]}'
                    reply = {'text': 'error: the sandbox failed'}
                f.write((json.dumps(reply) + '\n').encode())
                f.flush()

    def close(self):
        self.server.close()


def mcp_relay(sock_path, inp=sys.stdin, out=sys.stdout):
    """`driver.py mcp-relay SOCK`: a minimal MCP stdio server with one tool, `shell`, forwarded to the driver."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(sock_path)
    link = conn.makefile('rwb')

    def send(msg):
        out.write(json.dumps(msg) + '\n')
        out.flush()
    for line in inp:
        if not line.strip():
            continue
        try:
            msg = records.strict_json(line)
        except ValueError:
            send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'parse error'}})
            continue
        if not isinstance(msg, dict) or 'id' not in msg:
            continue  # notifications need no answer
        method, mid, params = msg.get('method'), msg['id'], msg.get('params') or {}
        if method == 'initialize':
            result = {'protocolVersion': params.get('protocolVersion', '2025-06-18'), 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'skills-eval', 'version': '1'}}
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': [{'name': TOOL['name'], 'description': TOOL['description'], 'inputSchema': TOOL['input_schema']}]}
        elif method == 'tools/call':
            args = params.get('arguments')
            if params.get('name') != TOOL['name'] or not isinstance(args, dict) or set(args) != {'command'}:
                result = {'content': [{'type': 'text', 'text': 'error: the only tool is shell, with one string `command`'}],
                          'isError': True}
            else:
                link.write((json.dumps({'command': args['command']}) + '\n').encode())
                link.flush()
                reply = records.strict_json(link.readline().decode())
                result = {'content': [{'type': 'text', 'text': reply['text']}], 'isError': False}
        else:
            send({'jsonrpc': '2.0', 'id': mid, 'error': {'code': -32601, 'message': 'method not found'}})
            continue
        send({'jsonrpc': '2.0', 'id': mid, 'result': result})


PREFLIGHT_TAIL = "runpy.run_module('json.tool', run_name='__main__', alter_sys=True)"
PREFLIGHT_CHECK = """
import json as _j, os as _o
import hermes_cli
from hermes_cli import managed_scope as _ms
from hermes_cli.auth import get_provider_auth_state as _gs
from hermes_cli.auth_nous import get_nous_session_validity as _gv
_root = sys.path[0]
_st = _gs('nous') or {}
print(_j.dumps({'version': getattr(hermes_cli, '__version__', None), 'install_env': _o.path.exists(_o.path.join(_root, '.env')),
                'managed': str(_ms.get_managed_dir()), 'validity': _gv(), 'refresh': bool(_st.get('refresh_token'))}))
"""


def hermes_home(h, folder):
    """A fresh private session home: (env, problem). Only the Nous login is copied in; nothing else of the
    machine's Hermes state, environment or managed scope is visible."""
    folder = Path(folder)
    home, hh, cwd, managed = (folder / n for n in ('home', 'hermes', 'cwd', 'managed'))
    for d in (home, hh, cwd, managed):
        d.mkdir(mode=0o700)
    login = Path(h['login_home']).expanduser()
    try:
        store = records.strict_json((login / 'auth.json').read_text())
    except (OSError, ValueError, UnicodeDecodeError):
        return None, f'Nous login missing: no readable Hermes login store; {RELOGIN}'
    nous = (store.get('providers') or {}).get('nous') if isinstance(store, dict) and isinstance(store.get('providers') or {}, dict) else None
    if not isinstance(nous, dict):
        return None, f'Nous login missing; {RELOGIN}'
    # Only the subscription login: no credential pool (it can hold manually added API keys) and no field
    # named as an API key. Hermes seeds its pool from this singleton.
    login_state = {k: v for k, v in nous.items() if 'api_key' not in k.lower()}
    portal = urllib.parse.urlparse(str(login_state.get('portal_base_url') or 'https://portal.nousresearch.com'))
    if portal.scheme != 'https' or portal.hostname not in h['portal_hosts']:
        return None, f'refusing: the Nous login names an unexpected portal {portal.hostname!r}'
    copy = {'version': store.get('version', 1), 'providers': {'nous': login_state}, 'active_provider': 'nous'}
    fd = os.open(hh / 'auth.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(json.dumps(copy))
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': str(home), 'HERMES_HOME': str(hh), 'LANG': 'C.UTF-8',
           'HERMES_MANAGED_DIR': str(managed),  # an empty private managed scope: no machine env or config overlay
           'HERMES_SHARED_AUTH_DIR': str(login / 'shared')}  # Hermes's rotation-safe Nous token store, so refreshes stay in the login
    return env, None


def hermes_preflight(h, env):
    """Through Hermes's own published launch command, with no model call: the pinned version, no
    installation-root .env, the private empty managed scope and a usable Nous login. Returns a problem or None."""
    program = str(Path(h['program']).expanduser())
    try:
        p = subprocess.run([program, '--print-runtime-command', '--module', 'json.tool'], env=env, capture_output=True,
                           text=True, timeout=300, stdin=subprocess.DEVNULL, cwd=env['HOME'])
        cmd = records.strict_json(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        cmd = None
    if (not isinstance(cmd, list) or len(cmd) != 4 or not all(isinstance(c, str) for c in cmd)
            or cmd[1:3] != ['-I', '-c'] or not cmd[3].endswith(PREFLIGHT_TAIL)):
        return 'unsupported Hermes runtime: its launch command could not be read'
    try:
        p = subprocess.run([cmd[0], '-I', '-c', cmd[3][:-len(PREFLIGHT_TAIL)] + PREFLIGHT_CHECK], env=env, capture_output=True,
                           text=True, timeout=300, stdin=subprocess.DEVNULL, cwd=env['HOME'])
        facts = records.strict_json(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 and p.stdout.strip() else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        facts = None
    if not isinstance(facts, dict):
        return 'unsupported Hermes runtime: its offline status could not be read'
    if facts.get('version') != h['version']:
        return f"unsupported Hermes runtime {facts.get('version')!r}; this route is checked against {h['version']}"
    if facts.get('install_env') is not False:
        return 'refusing: the Hermes installation has its own .env, which would add credentials or config to the session'
    managed = Path(env['HERMES_MANAGED_DIR'])
    if facts.get('managed') != str(managed) or any(managed.iterdir()):
        return 'refusing: Hermes did not use the empty private managed scope'
    if facts.get('validity') == 'valid' or (facts.get('validity') == 'unknown' and facts.get('refresh') is True):
        return None
    return f"Nous login missing or revoked (status: {facts.get('validity')}); {RELOGIN}"


def hermes_login_problem(settings):
    """Offline: can a Hermes session start under this machine's Nous login? A problem string or None."""
    try:
        h = hermes_settings(settings)
    except ValueError as e:
        return str(e)
    with tempfile.TemporaryDirectory(prefix='skills-eval-hermes-') as folder:
        env, problem = hermes_home(h, folder)
        return problem or hermes_preflight(h, env)


def hermes_run(prompt, persona, h, settings, folder, relay, max_tokens, calls_cap):
    """One isolated Hermes session. Returns {'not_run': problem} before any model attempt, or
    {'usage', 'msgs', 'error', 'proxy'} with the proxy's frozen attempt accounting."""
    env, problem = hermes_home(h, folder)
    problem = problem or hermes_preflight(h, env)
    if problem:
        return {'not_run': problem}
    hh, cwd = Path(env['HERMES_HOME']), Path(folder) / 'cwd'
    config = json.loads(json.dumps(h['config']))
    config['model'] = {'provider': h['provider'], 'default': h['model'], 'max_tokens': max_tokens,
                       'context_length': h['max_input_tokens_per_call']}
    config.setdefault('agent', {})['reasoning_effort'] = settings['effort']
    if relay:
        config['mcp_servers'] = {'eval': {'command': sys.executable, 'args': ['-I', str(Path(__file__).resolve()), 'mcp-relay', relay.path],
                                          'env': {}, 'tools': {'include': [TOOL['name']], 'resources': False, 'prompts': False}}}
    (hh / 'config.yaml').write_text(json.dumps(config, indent=1) + '\n')  # JSON is YAML
    (hh / 'SOUL.md').write_text(persona + '\n')
    proxy = ModelProxy(h, max_tokens, calls_cap)
    env['NOUS_INFERENCE_BASE_URL'] = proxy.url
    env.update(proxy.proxy_env())
    turns = settings['max_turns'] if relay else 1
    argv = [str(Path(h['program']).expanduser()), 'chat', '-Q', '--oneshot', '-q', prompt, '--provider', h['provider'],
            '-m', h['model'], '--toolsets', HERMES_TOOLSET if relay else h['judge_toolsets'],
            '--max-turns', str(turns), '--source', 'tool']
    error = None
    try:
        p = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=h['timeout_s'])
        if p.returncode != 0:
            error = f'hermes exited {p.returncode}'
    except subprocess.TimeoutExpired:
        error = 'hermes timed out'
    except OSError as e:
        error = f'hermes did not start: {e}'
    acct = proxy.close()
    try:
        usage, msgs = hermes_session(hh)
    except ValueError as e:
        usage, msgs, error = None, None, f'{error + "; " if error else ""}{e}'
    return {'usage': usage, 'msgs': msgs, 'error': error, 'proxy': acct}


def hermes_check(usage, msgs, calls_cap, allowed):
    """Stored tool names must all be `allowed`, and the session within its call bound. Returns (final, turns, problem)."""
    final, turns, problem = '', 0, None
    try:
        for role, content, tool_calls in msgs:
            if role != 'assistant':
                continue
            turns += 1
            names = hermes_calls(tool_calls)
            if any(n not in allowed for n in names):
                problem = f'Hermes used a tool outside the fake shell: {sorted(set(names) - set(allowed))}'
            final = (content or '').strip() if not names else ''
    except ValueError as e:
        problem = str(e)
    if usage['api_call_count'] > calls_cap:
        problem = f"Hermes made {usage['api_call_count']} model calls, over the bound of {calls_cap}"
    return final, turns, problem


def hermes_run_case(case, settings, snapshot, repeat, budget_usd=None, checkpoint=None):
    """The Hermes form of `run_case`: one actor session, then one judge session; never raises."""
    world = fakeworld.World(case['world'], snapshot)
    usage = {'input_tokens': 0, 'output_tokens': 0, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}
    sessions, spent, uncertain = [], [0.0], [0.0]
    stop, final, error, judgment, turns = None, '', None, None, 0

    def transcript():
        return {'provider_usage': sessions, 'tokenizer': HERMES_TOKENIZER, 'case': case['id'], 'repeat': repeat,
                'stop': stop, 'final': final, 'events': world.events, 'usage': usage,
                'cost_usd': round(spent[0] + uncertain[0], 9), 'uncertain_usd': round(uncertain[0], 9),
                'error': error, 'judgment': judgment, 'turns': turns}
    try:
        h = hermes_settings(settings)
    except ValueError as e:
        stop, error = 'error', str(e)
        return transcript()

    def session(prompt, persona, relay_world, max_tokens, calls_cap, allowed):
        """((final, turns), None) or (None, (stop, error)). The whole bound is reserved before Hermes starts;
        afterwards the proxy's attempt accounting replaces it. When the session store cannot confirm that
        every model call passed the proxy, the rest of the bound stays reserved as uncertain."""
        bound = hermes_reserve(h, max_tokens, calls_cap)
        if budget_usd is not None and spent[0] + uncertain[0] + bound > budget_usd:
            return None, ('cap', None)
        if checkpoint:
            snap = transcript()
            snap.update(stop='error', cost_usd=round(spent[0] + uncertain[0] + bound, 9),
                        uncertain_usd=round(uncertain[0] + bound, 9),
                        error='Interrupted Hermes session: reservation retained; never automatically retried')
            checkpoint(snap)
        with tempfile.TemporaryDirectory(prefix='skills-eval-hermes-') as folder:
            relay = ShellRelay(relay_world, folder) if relay_world else None
            try:
                r = hermes_run(prompt, persona, h, settings, folder, relay, max_tokens, calls_cap)
            finally:
                if relay:
                    relay.close()
        if 'not_run' in r:
            return None, ('error', r['not_run'])  # nothing left this process: no proxy existed yet
        acct, u = r['proxy'], r['usage']
        spent[0] += acct['cost']
        uncertain[0] += acct['uncertain']
        unseen = max(0.0, bound - acct['cost'] - acct['uncertain'])
        sessions.append({'session': u, 'proxy': {k: acct[k] for k in ('forwarded', 'accounted', 'refused', 'escapes', 'cost', 'uncertain', 'usage')}})
        problem = None
        escaped = [e for e in acct['escapes'] if urllib.parse.urlparse(h['upstream']).hostname in e]
        if acct['uncertain'] > 0:  # contract section 6: unknown usage ends the run; nothing more is admitted
            problem = (f"{acct['forwarded'] - acct['accounted']} model attempt(s) without complete usage; "
                       'their reservations are kept and the run ends')
        if escaped:
            problem = f'Hermes tried to reach the model outside the proxy ({escaped[0]}); refused before it left'
        if u is None:
            uncertain[0] += unseen
            problem = 'the Hermes session store is unreadable, so calls outside the proxy cannot be ruled out (the rest of the bound is kept)'
        elif u['api_call_count'] > acct['forwarded'] + len(acct['refused']) + len(acct['escapes']):
            uncertain[0] += unseen
            problem = (f"Hermes recorded {u['api_call_count']} model calls but the proxy saw only "
                       f"{acct['forwarded'] + len(acct['refused']) + len(acct['escapes'])} "
                       '(the rest of the bound is kept)')
        if u is not None:
            usage['input_tokens'] += u['input_tokens']
            usage['output_tokens'] += u['output_tokens'] + u['reasoning_tokens']
            usage['cache_read_input_tokens'] += u['cache_read_tokens']
            usage['cache_creation_input_tokens'] += u['cache_write_tokens']
        text = n = None
        if not problem:
            text, n, problem = hermes_check(u, r['msgs'], calls_cap, allowed)
        if not problem and relay and not relay.connected:
            problem = 'Hermes never connected the fake shell (is its MCP support installed?)'
        if not problem and relay:
            stored = sum(len(hermes_calls(m[2])) for m in r['msgs'] if m[0] == 'assistant')
            if stored != relay.calls:
                problem = f'{stored} stored tool calls but {relay.calls} reached the fake shell'
        failure = '; '.join(x for x in (r['error'], relay.fault if relay else None, problem) if x)
        return ((text, n), None) if not failure else (None, ('error', failure))

    got, failed = session(case['brief'], SYSTEM, world, settings['max_tokens'], h['max_api_calls'], {HERMES_TOOL})
    if failed:
        stop, error = failed
        return transcript()
    final, turns = got
    stop = 'end_turn' if final else 'turn_cap'
    rubric = case.get('expect', {}).get('final')
    if stop == 'end_turn' and rubric:
        got, failed = session(f'Rule:\n{rubric}\n\nReply:\n<<<\n{final}\n>>>', JUDGE, None,
                              settings.get('judge_max_tokens', 1000), h['judge_max_api_calls'], set())
        if failed:
            judgment = {'verdict': None, 'reason': None, 'error': f'not judged: {failed[1] or failed[0]}'}
            stop = 'cap' if failed[0] == 'cap' else stop
        else:
            try:
                j = records.strict_json(got[0])
            except ValueError:
                j = None
            if (not isinstance(j, dict) or set(j) != {'verdict', 'reason'} or j['verdict'] not in ('pass', 'fail')
                    or not isinstance(j['reason'], str) or not j['reason'].strip()):
                judgment = {'verdict': 'invalid', 'reason': None, 'raw': got[0][:300], 'stop': 'end_turn'}
            else:
                judgment = {'verdict': j['verdict'], 'reason': j['reason'], 'model': f"{h['provider']}:{h['model']}"}
    return transcript()


def hermes_usage_report(folder):
    """Recorded Hermes session usage per run, actor and judge included. No request, no estimate."""
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest['settings'].get('provider') != 'hermes':
        raise ValueError('Hermes usage report requires a Hermes results set')
    rows = []
    for p in sorted(folder.glob('*.r*.json')):
        t = json.loads(p.read_text())
        u = t['usage']
        rows.append({'case': t['case'], 'repeat': t['repeat'], 'input_tokens': u['input_tokens'] + u['cache_read_input_tokens'],
                     'cached_input_tokens': u['cache_read_input_tokens'], 'output_tokens': u['output_tokens'],
                     'sessions': t['provider_usage'], 'cost_usd': t['cost_usd']})
    return {'schema': 'openwiz.skills-eval.provider-tokens.v1', 'tokenizer': HERMES_TOKENIZER,
            'model': f"{manifest['settings']['hermes']['provider']}:{manifest['settings']['hermes']['model']}",
            'revision': manifest['revision'], 'settings_hash': manifest.get('settings_hash'),
            'cases_hash': manifest.get('cases_hash'),
            'total': {k: sum(r[k] for r in rows) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')},
            'cost_usd': round(sum(r['cost_usd'] for r in rows), 9), 'runs': rows,
            'note': 'Hermes session store counts. Input here adds cache reads to the session input count; whether Hermes '
                    'already includes them is unverified. Actor and judge sessions included. Not per-skill required-text tokens.'}


if __name__ == '__main__':
    if sys.argv[1:2] == ['mcp-relay'] and len(sys.argv) == 3:
        mcp_relay(sys.argv[2])
    elif sys.argv[1:3] == ['usage', '--results'] and len(sys.argv) == 4:
        print(json.dumps(hermes_usage_report(sys.argv[3]), indent=1))
    else:
        sys.exit('usage: driver.py mcp-relay SOCK | driver.py usage --results DIR')
