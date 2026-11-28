import { readFileSync } from 'node:fs';

class InvalidModel extends Error {}
function requireModel(condition, reason = 'invalid-model') {
  if (!condition) throw new InvalidModel(reason);
}

const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = (value) => typeof value === 'string' && value.length > 0;
const name = (value) => text(value) && /^[A-Za-z_][A-Za-z0-9_-]*(?![\s\S])/.test(value);
const integer = Number.isSafeInteger;
const positive = (value) => integer(value) && value > 0;
const unique = (values) => new Set(values).size === values.length;
const list = (value, item) => Array.isArray(value) && value.every(item);
const strings = (value) => list(value, text) && unique(value);

function fields(value, required, optional = []) {
  requireModel(object(value) && required.every((key) => Object.hasOwn(value, key))
    && Object.keys(value).every((key) => required.includes(key) || optional.includes(key)));
}

function parseModel(bytes) {
  const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  const model = JSON.parse(source);
  const keys = [];
  for (const [token, member] of source.matchAll(/"(?:[^"\\]|\\[\s\S])*"(?:(\s*:))?|[{}]/g)) {
    if (token === '{') keys.push(new Set());
    else if (token === '}') keys.pop();
    else if (member) {
      const key = JSON.parse(token.slice(0, -1));
      requireModel(!keys.at(-1).has(key));
      keys.at(-1).add(key);
    }
  }
  return model;
}

function filePath(value) {
  return text(value) && value.split('/').every((part) =>
    /^[A-Za-z0-9_.-]+(?![\s\S])/.test(part) && part !== '.' && part !== '..');
}

function domain(value) {
  requireModel(object(value));
  switch (value.type) {
    case 'enum':
      fields(value, ['type', 'values']);
      requireModel(strings(value.values) && value.values.length > 0);
      return { kind: 'enum', fits: (item) => value.values.includes(item) };
    case 'int':
      requireModel(Object.hasOwn(value, 'min') && Object.hasOwn(value, 'max'), 'unbounded-domain');
      fields(value, ['type', 'min', 'max']);
      requireModel(integer(value.min) && integer(value.max) && value.min <= value.max);
      return { kind: 'int', fits: (item) => integer(item) && item >= value.min && item <= value.max };
    case 'set':
      requireModel(Object.hasOwn(value, 'maxSize'), 'unbounded-domain');
      fields(value, ['type', 'items', 'maxSize']);
      requireModel(strings(value.items) && integer(value.maxSize)
        && value.maxSize >= 0 && value.maxSize <= value.items.length);
      return {
        kind: 'set', items: value.items,
        fits: (items) => strings(items) && items.length <= value.maxSize
          && items.every((item) => value.items.includes(item)),
      };
    default:
      throw new InvalidModel('invalid-model');
  }
}

function variable(domains, key) {
  requireModel(name(key));
  requireModel(domains.has(key), 'unknown-variable');
  return domains.get(key);
}

function term(domains, value) {
  if (object(value)) {
    fields(value, ['var']);
    return { kind: variable(domains, value.var).kind, read: (state) => state[value.var] };
  }
  const kind = text(value) ? 'enum' : integer(value) ? 'int' : strings(value) ? 'set' : null;
  requireModel(kind !== null);
  return { kind, read: () => value };
}

function equal(left, right) {
  return Array.isArray(left) ? left.length === right.length && left.every((item) => right.includes(item))
    : left === right;
}

const comparisons = new Map([
  ['eq', equal], ['ne', (a, b) => !equal(a, b)],
  ['lt', (a, b) => a < b], ['le', (a, b) => a <= b],
  ['gt', (a, b) => a > b], ['ge', (a, b) => a >= b],
  ['in', (item, items) => items.includes(item)],
]);

function predicate(domains, value) {
  if (typeof value === 'boolean') return () => value;
  fields(value, ['op', 'args']);
  const { op, args } = value;
  if (op === 'and' || op === 'or' || op === 'not') {
    requireModel(Array.isArray(args) && (op === 'not' ? args.length === 1 : args.length >= 2));
    const checks = args.map((arg) => predicate(domains, arg));
    if (op === 'not') return (state) => !checks[0](state);
    if (op === 'and') return (state) => checks.every((check) => check(state));
    return (state) => checks.some((check) => check(state));
  }
  requireModel(comparisons.has(op), typeof op === 'string' ? 'unknown-expression' : 'invalid-model');
  requireModel(Array.isArray(args) && args.length === 2);
  const [a, b] = args.map((arg) => term(domains, arg));
  if (op === 'in') requireModel(a.kind === 'enum' && b.kind === 'set');
  else if (op === 'eq' || op === 'ne') requireModel(a.kind === b.kind);
  else requireModel(a.kind === 'int' && b.kind === 'int');
  const compare = comparisons.get(op);
  return (state) => compare(a.read(state), b.read(state));
}

function update(domains, value) {
  fields(value, ['op', 'var'], ['value', 'item']);
  const { op, var: key, item } = value;
  const target = variable(domains, key);
  if (op === 'assign') {
    fields(value, ['op', 'var', 'value']);
    const { kind, read } = term(domains, value.value);
    requireModel(kind === target.kind && (object(value.value) || target.fits(value.value)));
    return { key, read };
  }
  requireModel(op === 'add' || op === 'remove', typeof op === 'string' ? 'unknown-expression' : 'invalid-model');
  fields(value, ['op', 'var', 'item']);
  requireModel(target.kind === 'set' && target.items.includes(item));
  const read = (state) => op === 'add' ? [...new Set([...state[key], item])] : state[key].filter((tag) => tag !== item);
  return { key, read };
}

function compile(model) {
  fields(model, ['schema', 'machine', 'sources', 'variables', 'init', 'actions', 'invariants', 'bound'],
    ['progress', 'final']);
  requireModel(model.schema === 'openwiz.state-model.v1' && text(model.machine) && positive(model.bound));
  const { sources, init, bound } = model;
  fields(sources, ['commit', 'files']);
  requireModel(text(sources.commit) && /^[0-9a-f]{40}(?![\s\S])/.test(sources.commit)
    && list(sources.files, filePath) && sources.files.length > 0 && unique(sources.files));
  requireModel(object(model.variables) && Object.keys(model.variables).every(name) && object(init));
  const domains = new Map(Object.entries(model.variables).map(([key, value]) => [key, domain(value)]));
  for (const [key, value] of Object.entries(init)) requireModel(variable(domains, key).fits(value));
  requireModel(Object.keys(init).length === domains.size && Array.isArray(model.actions));

  const actions = model.actions.map((action) => {
    fields(action, ['name', 'guard', 'effect'], ['cites']);
    requireModel(Object.hasOwn(action, 'cites') && !(Array.isArray(action.cites) && action.cites.length === 0),
      'missing-cite');
    requireModel(name(action.name) && Array.isArray(action.effect) && Array.isArray(action.cites));
    for (const cite of action.cites) {
      fields(cite, ['file', 'start', 'end']);
      requireModel(sources.files.includes(cite.file) && positive(cite.start) && positive(cite.end) && cite.start <= cite.end);
    }
    const guard = predicate(domains, action.guard);
    const updates = action.effect.map((value) => update(domains, value));
    requireModel(unique(updates.map(({ key }) => key)));
    return { name: action.name, guard, updates };
  });
  requireModel(unique(actions.map((action) => action.name)));

  function checks(map) {
    requireModel(object(map) && Object.keys(map).every(name));
    return Object.keys(map).sort().map((key) => [key, predicate(domains, map[key])]);
  }
  const invariants = checks(model.invariants);
  const progress = checks(Object.hasOwn(model, 'progress') ? model.progress : {});
  requireModel(progress.every(([key]) => !Object.hasOwn(model.invariants, key)));
  const final = predicate(domains, Object.hasOwn(model, 'final') ? model.final : false);
  return { init, bound, domains, actions, invariants, progress, final };
}

function unicodeOrder(left, right) {
  const a = Array.from(left, (char) => char.codePointAt(0));
  const b = Array.from(right, (char) => char.codePointAt(0));
  const mismatch = a.findIndex((point, index) => index < b.length && point !== b[index]);
  return mismatch === -1 ? a.length - b.length : a[mismatch] - b[mismatch];
}

function counterexample(node, statesExplored, kind, name) {
  const trace = [];
  for (let step = node; step.parent; step = step.parent) trace.push({ action: step.action, state: step.state });
  return { status: 'counterexample', statesExplored, kind, name, trace: trace.reverse() };
}

function progressFailure(nodes, obligations) {
  let first;
  for (const [name, check] of obligations) {
    const reachable = new Set(nodes.filter(({ state }) => check(state)));
    for (const node of reachable) {
      for (const previous of node.incoming) reachable.add(previous);
    }
    const failed = nodes.findIndex((node) => !node.final && !reachable.has(node));
    if (failed !== -1 && (!first || failed < first.index)) first = { name, index: failed };
  }
  return first && counterexample(nodes[first.index], nodes.length, 'invariant', first.name);
}

function search({ init, bound, domains, actions, invariants, progress, final }) {
  const keys = [...domains.keys()].sort();
  const nodes = [];
  const visited = new Map();
  function enqueue(state, parent, action) {
    for (const key of keys) {
      if (Array.isArray(state[key])) state[key] = [...state[key]].sort(unicodeOrder);
    }
    const id = JSON.stringify(keys.map((key) => state[key]));
    let node = visited.get(id);
    if (!node && nodes.length <= bound) {
      node = { state, parent, action, incoming: [] };
      visited.set(id, node);
      nodes.push(node);
    }
    if (node && parent && progress.length) node.incoming.push(parent);
  }
  enqueue(init);
  let statesExplored = 0;
  while (statesExplored < nodes.length && statesExplored < bound) {
    const node = nodes[statesExplored++];
    const { state } = node;
    const broken = invariants.find(([, check]) => !check(state));
    if (broken) return counterexample(node, statesExplored, 'invariant', broken[0]);
    node.final = final(state);
    let enabled = false;
    for (const action of actions) {
      if (!action.guard(state)) continue;
      const values = action.updates.map(({ key, read }) => [key, read(state)]);
      if (!values.every(([key, value]) => domains.get(key).fits(value))) continue;
      enabled = true;
      enqueue({ ...state, ...Object.fromEntries(values) }, node, action.name);
    }
    if (!enabled && !node.final) return counterexample(node, statesExplored, 'stuck');
  }
  if (statesExplored < nodes.length) return { status: 'bound-reached', statesExplored };
  return progressFailure(nodes, progress) ?? { status: 'ok', statesExplored };
}

function run(args) {
  const invalid = (reason) => ({ status: 'invalid', statesExplored: 0, reason });
  if (args.length !== 1) return invalid('invalid-model');
  let bytes;
  try {
    bytes = readFileSync(args[0]);
  } catch {
    return invalid('unreadable');
  }
  let model;
  try {
    model = compile(parseModel(bytes));
  } catch (error) {
    return invalid(error instanceof InvalidModel ? error.message : 'invalid-model');
  }
  return search(model);
}

const report = run(process.argv.slice(2));
console.log(JSON.stringify(report));
process.exitCode = { ok: 0, counterexample: 1, invalid: 2, 'bound-reached': 3 }[report.status];
