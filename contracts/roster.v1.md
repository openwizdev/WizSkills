# Roster contract, version 1 (`openwiz.roster.v1`)

Spec #1365 (the kernel, 0.1.1 work), ticket KN20 (#1853), from the roster
decision B4. This contract fixes who may take which role in a project's
fleet, and how every one of them writes on GitHub: the one `## Roster` table
in `docs/agents/fleet.md`, how a fleet picks an entry for a role, the one
write rule every entry follows, what happens with no roster, and that
entries share nothing beyond the records on GitHub.
[`fixtures/roster/`](fixtures/roster/) holds one case per rule; every reader
runs them and must agree on each reading, pick and refusal.

Readers: KN21 (#1854, launch-fleet's pick), KN22 (#1855, setup's starting
Roster and its check) and KN23 (#1856, OpenWiz's own Roster). WizSkills
carries a byte-identical copy of this file (KN21).

It builds on two contracts and changes neither:

- [`models.v1`](models.v1.md) gives the harness, model and effort for each
  start (its **choice**), with its follow, fixer and cross-family rules.
- [`token-service.v1`](token-service.v1.md) gives every agent its GitHub
  token, from the owner's own machine, with its fallback.

Like a user and permission model, the Roster says who may take which
role, and every entry is read, started and written the same
way. No entry, kind of entry or bot has a rule of its own beyond the one
harness match below.

**This contract grants nothing.** It authorizes no installation, token,
start, live read or write. A fixture that passes here proves the contract is
consistent, never that any of it is live. Every example is synthetic.

## Words

| Word | Means |
| --- | --- |
| Entry | One row of the Roster: something a fleet may give a role to |
| Kind | `harness` (an agent program the person has signed into, such as Claude Code or Codex), `host` (a place that runs agents, such as their own computer or a cloud sandbox) or `bot` (an always-on bot on its own platform) |
| Driver | The [driver v1](../kernel/driver.v1.md) that starts the entry's agents: OpenWiz's `adapters/<driver>/driver` |
| Role | One of four: `orchestrator`, `builder`, `reviewer`, `helper` |
| Person | The GitHub login of the person who owns the project's GitHub App and runs its token service on their own machine |
| Label | `<name> via <person>`: how the entry's records name it |

## The Roster table

One `## Roster` section in `docs/agents/fleet.md`, its heading exactly the
line `## Roster`. Any other Markdown heading whose text is `Roster` in any
case is refused, never read as no Roster, so a Roster that renders is never
skipped: a `#` heading of any level or with closing hashes (such as
`## Roster ##`, `# Roster`, `### roster` or an indented `## Roster`), and an
underlined one (a `Roster` line followed by a line of only `=` or only
`-`). Prose may come before its table; the section's first table
is the Roster table, and must be:

```md
## Roster

| Name | Kind | Driver | Roles | Writes as |
| --- | --- | --- | --- | --- |
| Demo Bot | bot | demo-bot | orchestrator | syn-owner's App |
| Claude Code | harness | cloudroom | builder, reviewer | syn-owner's App |
| Codex | harness | cloudroom | reviewer | syn-owner's App |
| Own computer | host | local | builder, helper | syn-owner's App |
```

- **Header:** exactly these five column names, in this order, then a
  `| --- |` row. Cells are read trimmed of spaces. The section ends at the
  next `#` or `##` heading.
- **Rows:** one or more, one per entry, in the order the fleet prefers them.
- **Name:** 1 to 40 characters: ASCII letters, digits, `.`, `_`, `-` and
  single spaces, starting and ending with a letter or digit. No two entries
  share a name, compared without regard to case.
- **Kind:** exactly `harness`, `host` or `bot`.
- **Driver:** a driver's name as [records v1, section 6](../kernel/records.v1.md#6-the-host-setting)
  names a host: lowercase letters, digits and single hyphens, at most 40
  characters, such as `local`, `cloudroom` or `boat`.
- **Roles:** one or more of the four roles, separated by commas (spaces
  around them are ignored), each at most once, in any order. Writers write
  them in the order `orchestrator, builder, reviewer, helper`, joined by `, `.
- **Writes as:** exactly `<person>'s App`, where `<person>` is a GitHub login
  (1 to 39 ASCII letters, digits and single hyphens, starting and ending with
  a letter or digit). Every row names the same person.
- **Label:** `<name> via <person>` is at most 60 characters, so it fits the
  status note's `harness` field ([agent status v1](https://github.com/openwizdev/WizSkills/blob/main/contracts/agent-status.v1.md)).
- **Nothing else:** no cell holds an App id, key, token, machine, account or
  path. The person's login is the only identity the Roster names.

**Refused, never guessed.** A reader refuses the whole Roster when it breaks
any rule above, and then starts nothing that needs it: it never falls back to
today's starts past a broken Roster. It checks the section, then the header,
then each row in order, each row's cells left to right, and reports the first
broken rule with exactly its line. `<n>` is the row's number among the
entries, from 1; `<name>` and `<cell>` are the trimmed cells as written.

| Code | Refusal |
| --- | --- |
| `heading-form` | `Roster refused: the Roster heading must be exactly ## Roster: <line>` |
| `headings` | `Roster refused: more than one ## Roster heading` |
| `no-table` | `Roster refused: the Roster section has no table` |
| `header` | `Roster refused: the header is not Name, Kind, Driver, Roles, Writes as` |
| `empty` | `Roster refused: the table has no entries` |
| `cells` | `Roster refused: row <n> has <k> cells, not 5` |
| `name` | `Roster refused: row <n>: bad name: <cell>` |
| `duplicate-name` | `Roster refused: row <n>: <name> is already an entry` |
| `kind` | `Roster refused: row <n> (<name>): unknown kind: <cell>` |
| `driver` | `Roster refused: row <n> (<name>): bad driver: <cell>` |
| `no-role` | `Roster refused: row <n> (<name>): no roles` |
| `role` | `Roster refused: row <n> (<name>): unknown role: <role>` |
| `repeated-role` | `Roster refused: row <n> (<name>): role listed twice: <role>` |
| `writes-as` | `Roster refused: row <n> (<name>): writes as <cell>, not <person>'s App` |
| `person` | `Roster refused: row <n> (<name>): writes as <cell>, not <first>'s App like row 1` |
| `label` | `Roster refused: row <n> (<name>): <label> is longer than 60 characters` |

In `role` and `repeated-role`, `<role>` is the offending role as written; in
`person`, `<first>` is row 1's person; in `writes-as`, `<person>'s App` is
written as it stands; in `heading-form`, `<line>` is the first such heading
line (an underlined heading's `Roster` line), trimmed of trailing spaces.

**The starting Roster** (KN22) is one row: the person's own harness, every
role, on the driver setup chose, such as
`| Claude Code | harness | local | orchestrator, builder, reviewer, helper | syn-owner's App |`.
Fixture: `starting/`.

## Who may take which role

An entry takes only the roles in its Roles cell, whatever its kind. Each
start needs one role and one choice, both from what the fleet already reads:

| Start | Role | Choice ([`models.v1`](models.v1.md)) |
| --- | --- | --- |
| A spec's fleet thread | `orchestrator` | The Orchestrator |
| A ticket's builder | `builder` | The Builder, or the Small builder for a ticket with an exact `polish`, `huntr` or `proposal` label |
| A fix round | `builder` | The fixer rule's choice |
| A review | `reviewer` | The cross-family rule's choice |
| A helper an orchestrator starts | `helper` | The Builder |

When models.v1 says the start **waits** (the fixer or cross-family rule), it
waits as models.v1 says: the Roster adds nothing and picks nothing.

## Picking an entry

For a start with role R and choice C:

1. **What a driver can take:** a start goes only through driver v1, whose
   `start` takes a harness word matching `^[a-z0-9][a-z0-9._-]{0,59}$` and a
   model id matching `^[A-Za-z0-9][A-Za-z0-9 ._:@+-]{0,59}$`
   ([its schema](../kernel/driver-kit/schema.json)). models.v1 allows more,
   such as the namespaced `vendor/demo`. When C's harness word (step 6) or
   model id doesn't match, no entry is picked: the start waits, the same for
   every entry and driver, and the fleet says, exactly:

   ```text
   roster: driver v1 can't start codex vendor/demo; choose another model in the Models table
   ```

   `roster: driver v1 can't start <harness word> <model id>; choose another model in the Models table`.
   A later driver version that takes such ids lifts this wait by its own
   contract change. With no Roster, nothing here applies.
2. **Candidates** are the entries whose Roles hold R, in table order.
3. **A harness entry runs only its own harness:** it is a candidate only
   when its Name is C's harness as models.v1 names it (`Claude Code` for
   `claude-code`, `Codex` for `codex`, any other provider as its id). A host
   or bot entry is given C as it is; what a bot's own platform runs for it is
   its driver's business (driver v1, D4).
4. **The first candidate is picked:** table order is the preference, as a
   shell takes the first match on its `PATH`. A picked entry whose start
   fails is retried and reported as any failed driver start is (KN11); the
   next candidate is never tried in its place.
5. **No candidate:** the start waits, never swapped for an entry that may not
   take R, and the fleet says, exactly:

   ```text
   roster: no entry may take the reviewer role with Codex
   ```

   `roster: no entry may take the <R> role with <C's harness name>`.
6. **The start** calls the picked entry's driver,
   `adapters/<driver>/driver start`, with the ticket's repository and
   number, the role's skill, the harness `claude` for `claude-code` and any
   other provider as its id (as launch-fleet's host start passes it today),
   and C's model id. When C sets an effort, the start also sends it as
   driver v1's `effort`, and only to a driver whose `version` `can` lists
   `effort` (driver v1, E4). Through any other driver, or when the driver
   refuses that effort, nothing starts: the start is never retried without
   the effort. When C sets none, the start sends no `effort` and runs at the
   host's default effort (driver v1, E2).

## How every entry writes

One rule, the same for every entry, of every kind:

1. **As the person's App.** An entry's agent writes on GitHub as the
   person's own GitHub App, with installation tokens from the person's own
   token service on their own machine, asked for through the agent helper
   as every agent launch-fleet starts asks (token-service.v1; GA4, #1846).
   The request's `requester` is `<role>-<ticket>` and its `repositories` the
   ticket's repository. Nothing in the request, the token or its handover
   depends on the entry's name or kind.
2. **Every user the same.** A project that isn't OpenWiz's has its own App,
   installed on its own repositories, with its key only on its person's
   machine and its own token service (token-service.v1, "Where the key
   lives"). Nothing of OpenWiz's (no App, key, token or service) takes part.
3. **The same fallback.** With no usable token, the agent works as the
   person's own GitHub login with token-service.v1's one standard-error
   note; with no service configured, as today. An entry never writes with an
   account, token or App of its own.
4. **Records show the label.** The agent's status note's `harness` field is
   its label, `<name> via <person>` (such as `Demo Bot via syn-owner`). Its
   `model` field names the effort the agent runs at: it is
   `<C's model name> <effort> effort` (such as `Opus 5.5 high effort` for
   a Builder row set to High), with C's effort as the start sends it, or
   `<C's model name> default effort` only when C sets none. The model name
   is as the Models table's Model cell writes it. The field holds at most
   60 characters (agent status v1): when the note would be longer, the
   model name is shown as its first characters, trailing spaces dropped,
   then `...`, as many as leave the note 60 characters (its first 42 for
   `default effort`, its first 43 for `medium effort`).
5. **The person's own login** keeps approvals, repository settings and
   changes to `.github/workflows/` (github-identity.v1's roles).

## No roster

A `fleet.md` without a `## Roster` heading has no roster: every start is
exactly as today (the host setting of records v1 section 6, or `room-cli`,
and the model settings), with no label and no roster check. Fixture:
`no-roster/`.

With a Roster, each start uses its picked entry's driver, and the host
setting is not read for starts. A run is still woken and stopped through the
driver that started it (records v1, H2).

## No shared scratch space

Entries share work only through the records on GitHub: tickets, their
comments and status notes, branches and pull requests (records v1). There is
no shared board, file, channel or message route between entries. A hand-off
between entries is a record any of them can read, so any entry can be
replaced.

## Fixtures and the test

[`fixtures/roster/`](fixtures/roster/), all synthetic. Each case folder has a
`fleet.md` (a Models table and, but for `no-roster/`, a Roster) and a
`case.json`: the `repository`, the `person`, the `roster` as read (each
entry's `name`, `kind`, `driver`, `roles`, `writes_as` and `label`; null with
no roster), and its `picks`. Each pick gives the `ticket`, the `role`, its
`start` (what started it, from the table in "Who may take which role":
`{"kind": "spec"}`, `{"kind": "build", "labels": [...]}` with the ticket's
labels, `{"kind": "fix", "builder_family": ...}` or
`{"kind": "review", "builder_family": ...}` with the original builder's
family, `claude`, `gpt` or null when unknown, or `{"kind": "helper"}`), the
`choice` (C as models.v1 resolves it for that start from that `fleet.md`, with its
`harness`, `provider`, `model`, `effort` and `model_name`, or null when it
waits), and either the `pick` (the entry's `name`, `kind`, `driver`, its
driver `start` harness and model, its status `note`'s `harness` and `model`,
`writes_as` and its `token`: the `service` that mints it, named by its
person, and the request's `requester` and `repositories`), or `waits`:
`models`, `driver` or `roster`, with the `look` line of the last two. `no-roster/case.json` is `{"roster": null, "starts": "today"}`.

| Case | Shows |
| --- | --- |
| `mixed/` | A harness, a host and a bot entry; table order; a harness entry skipped for another harness's choice |
| `role-not-allowed/` | An entry never picked for a role it may not take; a role nobody may take waits; a models wait |
| `other-user/` | A user project that isn't ours: its own person, App, repositories and token service, with a bot |
| `namespaced/` | A namespaced model id driver v1 can't take waits; a Builder set to High whose note says `high effort` |
| `long-model/` | At medium effort, model names of 46 characters (shown whole: a 60-character note) and 47 (cut to `...`) |
| `starting/` | KN22's starting Roster |
| `no-roster/` | No Roster: starts as today |

`invalid/` holds one Markdown file per refusal code (and
`heading-form-underlined.md` beside `heading-form.md`), and
`refusals.json` each file's exact refusal line.

[`fixtures/roster/roster_contract.rs`](fixtures/roster/roster_contract.rs)
is the contract's reference reader, registered in `tests/cli-agent/main.rs`:
`cargo test -p openwiz-tests --test cli-agent roster_contract`. It is
offline and checks every reading, pick and refusal, that every choice is
what models.v1 resolves for its start from its case's Models table (a wait
included), and that every entry writes the same way.

## Gaps

- The fixtures prove the contract's cases agree with its rules, read by the
  reference reader; they prove no reader. KN21's and KN22's tests must run
  them.
- Whether a bot's own platform reaches the person's token service, and which
  GitHub login it holds when it can't, is that bot's driver's and its run's
  proof (KN7 to KN9); this contract can only require the rule.
