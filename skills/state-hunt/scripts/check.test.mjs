import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const checker = fileURLToPath(new URL('./check.mjs', import.meta.url));
const fixtures = new URL('../../../contracts/fixtures/state-model/', import.meta.url);
const expected = JSON.parse(readFileSync(new URL('expected.json', fixtures)));
const root = fileURLToPath(new URL('../../../', import.meta.url));

function run(file, { script = checker, cwd = root, flags = [] } = {}) {
  const child = spawnSync(process.execPath, [...flags, script, ...[file].filter(Boolean)], {
    cwd, encoding: 'utf8', timeout: 5000, env: { NODE_PATH: '' },
  });
  assert.ifError(child.error);
  assert.equal(child.stderr, '');
  return { exit: child.status, report: JSON.parse(child.stdout) };
}

for (const [name, result] of Object.entries(expected)) {
  test(`matches the contract report for ${name}`, () => {
    assert.deepEqual(run(fileURLToPath(new URL(`${name}.json`, fixtures))), result);
  });
}

const source = 'src/synthetic.mjs';
const model = {
  schema: 'openwiz.state-model.v1',
  machine: 'synthetic',
  sources: { commit: '0'.repeat(40), files: [source] },
  variables: { retries: { type: 'int', min: 0, max: 2 } },
  init: { retries: 0 },
  actions: [],
  invariants: {},
  bound: 8,
};
const ref = (variable) => ({ var: variable });
const pred = (op, ...args) => ({ op, args });
const assign = (variable, value) => ({ op: 'assign', var: variable, value });
const action = (name, guard, ...effect) => ({
  name, guard, effect, cites: [{ file: source, start: 1, end: 1 }],
});

function withModel(t, value) {
  const dir = mkdtempSync(join(tmpdir(), 'state-hunt-'));
  t.after(() => rmSync(dir, { recursive: true }));
  const file = join(dir, 'model.json');
  writeFileSync(file, typeof value === 'string' || Buffer.isBuffer(value) ? value : JSON.stringify(value));
  return { file, dir };
}

test('two writers reach the same broken state by paths of different lengths', (t) => {
  const { file } = withModel(t, {
    ...model,
    variables: { a: { type: 'int', min: 0, max: 1 }, b: { type: 'int', min: 0, max: 1 } },
    init: { a: 0, b: 0 },
    actions: [
      action('start-a', pred('eq', ref('a'), 0), assign('a', 1)),
      action('start-b', pred('eq', ref('b'), 0), assign('b', 1)),
      action('race', true, assign('a', 1), assign('b', 1)),
    ],
    invariants: { exclusive: pred('or', pred('eq', ref('a'), 0), pred('eq', ref('b'), 0)) },
  });
  assert.deepEqual(run(file), {
    exit: 1,
    report: {
      status: 'counterexample', statesExplored: 4, kind: 'invariant', name: 'exclusive',
      trace: [{ action: 'race', state: { a: 1, b: 1 } }],
    },
  });
});

test('a retry counter that never resets eventually gets stuck', (t) => {
  const { file } = withModel(t, {
    ...model,
    actions: [
      action('first-retry', pred('eq', ref('retries'), 0), assign('retries', 1)),
      action('last-retry', pred('eq', ref('retries'), 1), assign('retries', 2)),
    ],
  });
  assert.deepEqual(run(file), {
    exit: 1,
    report: {
      status: 'counterexample', statesExplored: 3, kind: 'stuck',
      trace: [{ action: 'first-retry', state: { retries: 1 } }, { action: 'last-retry', state: { retries: 2 } }],
    },
  });
});

test('sets coalesce by membership, use Unicode code-point order and respect domains', (t) => {
  const { file } = withModel(t, {
    ...model,
    variables: {
      tags: { type: 'set', items: ['𐀀', '\uE000', 'overflow'], maxSize: 2 },
      peer: { type: 'set', items: ['𐀀', '\uE000', 'overflow'], maxSize: 1 },
    },
    init: { tags: ['𐀀', '\uE000'], peer: [] },
    actions: [
      action('reorder', true, assign('tags', ['\uE000', '𐀀'])),
      action('copy-too-many', true, assign('peer', ref('tags'))),
      action('add-too-many', true, { op: 'add', var: 'tags', item: 'overflow' }),
      action('remove-one', pred('in', '𐀀', ref('tags')), { op: 'remove', var: 'tags', item: '𐀀' }),
      action('add-one', pred('not', pred('in', '𐀀', ref('tags'))), { op: 'add', var: 'tags', item: 'overflow' }),
    ],
    invariants: { consistent: pred('not', pred('in', 'overflow', ref('tags'))) },
  });
  assert.deepEqual(run(file), {
    exit: 1,
    report: {
      status: 'counterexample', statesExplored: 4, kind: 'invariant', name: 'consistent',
      trace: [
        { action: 'remove-one', state: { tags: ['\uE000'], peer: [] } },
        { action: 'add-one', state: { tags: ['overflow', '\uE000'], peer: [] } },
      ],
    },
  });
});

test('effects read the original state and invariants are checked on final states at the bound', (t) => {
  const { file } = withModel(t, {
    ...model,
    variables: { a: { type: 'int', min: 0, max: 1 }, b: { type: 'int', min: 0, max: 1 } },
    init: { a: 0, b: 1 },
    actions: [action('swap', true, assign('a', ref('b')), assign('b', ref('a')))],
    invariants: { z: pred('gt', ref('b'), ref('a')), A: pred('lt', ref('a'), ref('b')) },
    final: pred('ge', ref('a'), ref('b')),
    bound: 2,
  });
  assert.deepEqual(run(file), {
    exit: 1,
    report: {
      status: 'counterexample', statesExplored: 2, kind: 'invariant', name: 'A',
      trace: [{ action: 'swap', state: { a: 1, b: 0 } }],
    },
  });
});

const invalid = (reason) => ({ exit: 2, report: { status: 'invalid', statesExplored: 0, reason } });
const rejected = {
  'extra root property': { ...model, extra: false },
  'reversed bounds': { ...model, variables: { retries: { type: 'int', min: 3, max: 2 } } },
  'init outside domain': { ...model, init: { retries: 3 } },
  'unknown init key': { ...model, init: { other: 0 } },
  'unsafe integer': { ...model, bound: Number.MAX_SAFE_INTEGER + 1 },
  'duplicate key with an escaped spelling': JSON.stringify(model).replace('"init":', '"\\u0069nit":{},"init":'),
  'invalid UTF-8 in a string': Buffer.concat([Buffer.from('{"machine":"'), Buffer.from([0xff]), Buffer.from('"}')]),
  'wrong operand kind in dead code': { ...model, actions: [action('dead', pred('and', false, pred('lt', '0', 1)))] },
  'literal assignment outside domain': { ...model, actions: [action('dead', false, assign('retries', 3))] },
  'duplicate effect targets': { ...model, actions: [action('dead', false, assign('retries', 1), assign('retries', 2))] },
  'duplicate action names': { ...model, actions: [action('dup', false), action('dup', false)] },
  'undeclared cite file': { ...model, sources: { ...model.sources, files: ['src/other.mjs'] }, actions: [action('dead', false)] },
  'reversed cite range': { ...model, actions: [{ ...action('dead', false), cites: [{ file: source, start: 2, end: 1 }] }] },
  'unsafe source path': { ...model, sources: { ...model.sources, files: ['../synthetic.mjs'] } },
  'progress and invariant name overlap': { ...model, invariants: { done: true }, progress: { done: true } },
};

for (const [name, input] of Object.entries(rejected)) {
  test(`refuses ${name} before exploring`, (t) => {
    assert.deepEqual(run(withModel(t, input).file), invalid('invalid-model'));
  });
}

test('reports fixed errors for missing arguments and unreadable files', (t) => {
  const { dir } = withModel(t, model);
  assert.deepEqual(run(), invalid('invalid-model'));
  assert.deepEqual(run(join(dir, 'absent.json')), invalid('unreadable'));
});

test('runs in an empty dependency tree with filesystem-only imports and no fetch', (t) => {
  const { file, dir } = withModel(t, { ...model, final: true });
  const script = join(dir, 'check.mjs');
  copyFileSync(checker, script);
  const moduleUrl = (code) => `data:text/javascript,${encodeURIComponent(code)}`;
  const loader = moduleUrl(`
    export function resolve(specifier, context, nextResolve) {
      if (context.parentURL && specifier !== 'node:fs') throw new Error('Unexpected checker import');
      return nextResolve(specifier, context);
    }
  `);
  const preload = moduleUrl(`
    import { register } from 'node:module';
    register(${JSON.stringify(loader)});
    globalThis.fetch = () => { throw new Error('Checker called fetch'); };
    process.getBuiltinModule = () => { throw new Error('Checker loaded a builtin dynamically'); };
  `);
  assert.deepEqual(run(file, { script, cwd: dir, flags: ['--import', preload] }), {
    exit: 0, report: { status: 'ok', statesExplored: 1 },
  });
});
