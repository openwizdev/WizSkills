"""Required-text token accounting (contract.md, section 7)."""
import hashlib
import json
import posixpath
import re
from pathlib import Path

PROBE = 'x'


def load_map(path):
    m = json.loads(Path(path).read_text())
    if m.get('schema') != 'openwiz.skills-eval.required-text.v2':
        raise ValueError('required-text: wrong schema')
    return m['skills']


def mentions(skill, text, exists, lst=lambda p: []):
    """Every existing file or folder a SKILL.md names, found independently of the map: backticked
    paths, Markdown links (from the root or the skill's folder), folders by the snapshot's listing,
    and the project's instructions, glossary and ADRs named in words. A folder ends in `/`."""
    found = set()
    folder = f'skills/{skill}'
    for tok in re.findall(r'`([^`\n]+)`', text) + re.findall(r'\]\(([^)#\s]+)', text):
        tok = tok.strip().strip('"\'')
        for cand in (tok, posixpath.normpath(posixpath.join(folder, tok)) + ('/' if tok.endswith('/') else '')):
            if cand.startswith('./'):
                cand = cand[2:]
            if not cand or cand.startswith(('/', 'http', '..')) or cand in ('.', './'):
                continue
            if not cand.endswith('/') and exists(cand):
                found.add(cand)
            elif re.fullmatch(r'[\w.-]+(/[\w.-]+)*/?', tok) and '/' in tok.strip('/') + ('/' if tok.endswith('/') else '') \
                    and tok.strip('./') and lst(cand.rstrip('/') + '/'):
                found.add(cand.rstrip('/') + '/')
    low = text.lower()
    if re.search(r"agents\.md|claude\.md|project's instructions|project instructions", low):
        found.add('AGENTS.md')
    if 'glossary' in low:
        found.add('GLOSSARY.md')
    if re.search(r'\badrs?\b', low):
        found.add('docs/adr/')
    return found


def linked_files(path, text, exists):
    """Files one file links to: its Markdown links, resolved from its own folder, and its
    backticked repository paths. Only existing files; no folders, no web links."""
    out = set()
    here = posixpath.dirname(path)
    for target in re.findall(r'\]\(([^)\s]+)\)', text):
        target = target.split('#', 1)[0]
        if not target or target.startswith(('http:', 'https:', 'mailto:')):
            continue
        cand = posixpath.normpath(posixpath.join(here, target))
        if not cand.startswith('..') and exists(cand):
            out.add(cand)
    for tok in re.findall(r'`([^`\n]+)`', text):
        tok = tok.strip()
        if not tok.startswith(('/', '..')) and exists(tok):
            out.add(tok)
    return out


def expand_links(entries, read, lst):
    """Every file linked from the files of each `linked` entry, in a stable order."""
    out = []
    for p in sorted(entries):
        for f in expand([p], lst):
            for x in sorted(linked_files(f, read(f) or '', lambda q: read(q) is not None)):
                if x not in out:
                    out.append(x)
    return out


def expand(paths, lst):
    """Files, in order, with each folder entry (ending `/`) replaced by every file under it."""
    out = []
    for p in paths:
        for f in (sorted(lst(p)) if p.endswith('/') else [p]):
            if f not in out:
                out.append(f)
    return out


def map_problems(skills_map, shipped, read, lst):
    """Every shipped skill mapped once, its SKILL.md first, every entry readable, every mention classified."""
    errs = []
    if sorted(skills_map) != sorted(shipped):
        errs.append(f'mapped {sorted(skills_map)} != shipped {sorted(shipped)}')
    for s, v in skills_map.items():
        if set(v) - {'linked'} != {'required', 'conditional', 'not_loaded'}:
            errs.append(f'{s}: keys')
            continue
        if not v['required'] or v['required'][0] != f'skills/{s}/SKILL.md':
            errs.append(f'{s}: SKILL.md must be the first required file')
        lists = [v['required'], list(v['conditional']), list(v['not_loaded'])]
        flat = [p for x in lists for p in x]
        if len(set(flat)) != len(flat):
            errs.append(f'{s}: a path listed twice')
        for p in flat + list(v.get('linked', {})):
            if (not lst(p)) if p.endswith('/') else read(p) is None:
                errs.append(f'{s}: {p} is not in the snapshot')
        for kind in ('conditional', 'not_loaded', 'linked'):
            for p, why in v.get(kind, {}).items():
                if not isinstance(why, str) or not why.strip():
                    errs.append(f'{s}: {kind} {p} needs its reason')
        text = read(f'skills/{s}/SKILL.md') or ''
        covered = [f for f in flat if f.endswith('/')]
        for p in sorted(mentions(s, text, lambda q: read(q) is not None, lst) - set(flat)):
            if any(p.startswith(f) for f in covered):
                continue
            errs.append(f'{s}: SKILL.md names {p}, which the map does not classify')
    return errs


def report(skills_map, read, count, tokenizer, revision, lst=lambda p: []):
    """count(text) -> tokens, or None offline. Each required file counts once per skill load."""
    files, cache = {}, {}
    overhead = count(PROBE) - 1 if count else None
    sets = {}
    for s, v in skills_map.items():
        req = expand(v['required'], lst)
        cond = [p for p in expand(list(v['conditional']), lst) + expand_links(v.get('linked', {}), read, lst) if p not in req]
        cond = list(dict.fromkeys(cond))
        sets[s] = (req, cond)
        for p in req + cond:
            if p in files:
                continue
            text = read(p)
            sha = hashlib.sha256(text.encode()).hexdigest()
            if count and sha not in cache:
                cache[sha] = count(text) - overhead
            files[p] = {'sha256': sha, 'bytes': len(text.encode()), 'tokens': cache.get(sha)}
    per = {}
    for s, (req, cond) in sorted(sets.items()):
        per[s] = {'required_tokens': sum(files[p]['tokens'] or 0 for p in req) if count else None,
                  'conditional_tokens': sum(files[p]['tokens'] or 0 for p in cond) if count else None,
                  'required_bytes': sum(files[p]['bytes'] for p in req),
                  'conditional_bytes': sum(files[p]['bytes'] for p in cond),
                  'files': req, 'conditional': cond}
    total = sum(x['required_tokens'] for x in per.values()) if count else None
    return {'schema': 'openwiz.skills-eval.tokens.v1', 'tokenizer': tokenizer, 'revision': revision,
            'overhead_subtracted': overhead, 'files': dict(sorted(files.items())), 'skills': per,
            'total_required_tokens': total,
            'total_conditional_tokens': sum(x['conditional_tokens'] for x in per.values()) if count else None,
            'total_required_bytes': sum(x['required_bytes'] for x in per.values())}


def diff(before, after):
    if before.get('schema') != 'openwiz.skills-eval.tokens.v1' or after.get('schema') != 'openwiz.skills-eval.tokens.v1':
        raise ValueError('provider usage is not a required-text token report; no text savings claimed')
    if before['tokenizer'] != after['tokenizer']:
        raise ValueError(f"tokenizers differ: {before['tokenizer']} vs {after['tokenizer']}")
    if before['total_required_tokens'] is None or after['total_required_tokens'] is None:
        raise ValueError('a report has no token counts (offline); bytes are never tokens')
    rows = []
    for s in sorted(set(before['skills']) | set(after['skills'])):
        b = (before['skills'].get(s) or {}).get('required_tokens')
        a = (after['skills'].get(s) or {}).get('required_tokens')
        if a is None or b is None:
            rows.append({'skill': s, 'before': b, 'after': a, 'saved': None, 'percent': None})
            continue
        rows.append({'skill': s, 'before': b, 'after': a, 'saved': b - a,
                     'percent': round(100 * (b - a) / b, 2) if b else None})
    b, a = before['total_required_tokens'], after['total_required_tokens']
    return {'tokenizer': before['tokenizer'], 'before_revision': before['revision'],
            'after_revision': after['revision'], 'skills': rows,
            'total': {'before': b, 'after': a, 'saved': b - a, 'percent': round(100 * (b - a) / b, 2) if b else None}}


def usage_report(folder):
    """Provider counts per run, actor and judge included. No API or token estimate."""
    folder = Path(folder)
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest['settings'].get('provider') != 'openrouter':
        raise ValueError('provider usage report requires an OpenRouter results set')
    rows = []
    for p in sorted(folder.glob('*.r*.json')):
        t = json.loads(p.read_text())
        usage = t['usage']
        rows.append({'case': t['case'], 'repeat': t['repeat'],
                     'input_tokens': usage.get('input_tokens', 0) + usage.get('cache_read_input_tokens', 0),
                     'cached_input_tokens': usage.get('cache_read_input_tokens', 0),
                     'output_tokens': usage.get('output_tokens', 0),
                     'requests': t['provider_usage'], 'cost_usd': t['cost_usd']})
    return {'schema': 'openwiz.skills-eval.provider-tokens.v1',
            'tokenizer': 'DeepSeek (OpenRouter provider usage; not Claude tokens)',
            'model': manifest['settings']['model'], 'revision': manifest['revision'],
            'settings_hash': manifest.get('settings_hash'), 'cases_hash': manifest.get('cases_hash'),
            'total': {k: sum(r[k] for r in rows) for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')},
            'cost_usd': round(sum(r['cost_usd'] for r in rows), 9), 'runs': rows,
            'note': 'Cached input is a subset of input. Actor and judge requests included. '
                    'Usage counts are not per-skill required-text token counts and prove no text savings.'}
