"""Record validators (contract.md, section 5). Each returns a list of problems."""
import json
import re

FENCE = re.compile(r'^```json\n(.*?)\n^```$', re.S | re.M)
HEX40 = re.compile(r'[0-9a-f]{40}')


def _strict_pairs(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate key')
    return dict(pairs)


def _no_float(s):
    raise ValueError(f'non-integer number {s}')


def strict_json(text):
    return json.loads(text, object_pairs_hook=_strict_pairs, parse_float=_no_float,
                      parse_constant=_no_float)


def schema_errors(value, schema, root, path='$'):
    """A JSON Schema subset: the keywords contracts/decisions.v1.schema.json uses."""
    if '$ref' in schema:
        ref = schema['$ref']
        if not ref.startswith('#/$defs/'):
            return [f'{path}: unsupported $ref {ref}']
        return schema_errors(value, root['$defs'][ref[8:]], root, path)
    errs = []
    if 'oneOf' in schema:
        ok = [s for s in schema['oneOf'] if not schema_errors(value, s, root, path)]
        if len(ok) != 1:
            errs.append(f'{path}: matches {len(ok)} of oneOf')
    t = schema.get('type')
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_is(value, x) for x in types):
            return errs + [f'{path}: not {t}']
    if 'const' in schema and value != schema['const']:
        errs.append(f'{path}: not {schema["const"]!r}')
    if 'enum' in schema and value not in schema['enum']:
        errs.append(f'{path}: not in enum')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 1 << 30):
            errs.append(f'{path}: length')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            errs.append(f'{path}: pattern')
    if _is(value, 'integer') and 'minimum' in schema and value < schema['minimum']:
        errs.append(f'{path}: below minimum')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', 1 << 30):
            errs.append(f'{path}: item count')
        if schema.get('uniqueItems') and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            errs.append(f'{path}: duplicate items')
        if 'items' in schema:
            for i, v in enumerate(value):
                errs += schema_errors(v, schema['items'], root, f'{path}[{i}]')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for k in schema.get('required', []):
            if k not in value:
                errs.append(f'{path}: missing {k}')
        for k, v in value.items():
            if k in props:
                errs += schema_errors(v, props[k], root, f'{path}.{k}')
            elif schema.get('additionalProperties') is False:
                errs.append(f'{path}: extra key {k}')
    return errs


def _is(v, t):
    return {'object': isinstance(v, dict), 'array': isinstance(v, list),
            'string': isinstance(v, str), 'boolean': isinstance(v, bool),
            'null': v is None,
            'integer': isinstance(v, int) and not isinstance(v, bool),
            'number': isinstance(v, (int, float)) and not isinstance(v, bool)}.get(t, False)


def check_decisions(body, schema):
    blocks = FENCE.findall(body or '')
    if len(blocks) != 1:
        return [f'expected one json block, found {len(blocks)}']
    try:
        obj = strict_json(blocks[0])
    except ValueError as e:
        return [f'invalid JSON: {e}']
    if not isinstance(obj, dict) or obj.get('schema') != 'openwiz.decisions.v1':
        return ['not an openwiz.decisions.v1 object']
    if obj.get('kind') == 'response':
        return ['a response envelope, not a request']
    return schema_errors(obj, schema, schema)


def check(kind, body, ctx):
    """ctx: {'head': <sha>, 'number': <ticket>, 'schema': <decisions schema>}."""
    body = body or ''
    first = body.split('\n', 1)[0].strip()
    if kind == 'decisions.v1':
        return check_decisions(body, ctx['schema'])
    if kind == 'verdict':
        m = re.fullmatch(r'VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{40})', first)
        if not m:
            return ['first line is not `VERDICT: APPROVE|CHANGES at <40 hex>`']
        if ctx.get('head') and m.group(2) != ctx['head']:
            return [f'names {m.group(2)}, not the head {ctx["head"]}']
        return []
    if kind == 'launch-fleet':
        return [] if first.startswith('launch-fleet: ') else ['first line does not start `launch-fleet: `']
    if kind == 'handback':
        n = ctx.get('number')
        errs = []
        if not re.search(rf'(?m)^Closes #{n}\b', body):
            errs.append(f'no `Closes #{n}`')
        if ctx.get('head') and ctx['head'] not in body:
            errs.append('does not name the head')
        return errs
    if kind == 'text':
        return [] if body.strip() else ['empty body']
    return [f'unknown record kind {kind}']
