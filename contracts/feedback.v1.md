# OpenWiz feedback and sharing contract, version 1 (`openwiz.feedback.v1`)

**Revision 2 (2026-11-24):** adds the optional machine-readable facts line, four
plain report sections, opt-in scrubbed log section, secret refusal and
private-text warnings, and restated privacy scope (#2955; [private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7129701559)).

How feedback a user chooses reaches Jake's agents, and how a user shares
OpenWiz, without exposing private work. Ticket P4 (#2203) of spec #2194.
Sources: Jake, 2026-11-10: feedback goes to a GitHub issue on the public OpenWiz
repository, created by the user's agent after an exact preview and a yes, carrying
only content the user chose ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6763149732)).
Jake, 2026-11-13: confirmed that route through the user's own GitHub login, and
added the receiver side: his agent reviews incoming feedback issues, queues each
for his approval, then replies ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6845243425)).

**Contract only.** This adds no OpenWiz server route, method, header or write
authorization, no OpenWiz App permission and no stored credential. It changes no
rule of [setup.v1](setup.v1.md), `web-api.v1` (retired in #1264) or
[open-development.v1](open-development.v1.md). It sends nothing and grants no
live, account, feedback-send, reply, spending or publication authority. Its
consumers are #2292 (sender and sharing, P14) and #2557 (receiver queue, P16).
Claim PR7 of #2194 stays **Unverified** until those consumers' recording-recipient
proofs, the independent security review and a separately authorized synthetic
live check pass. Every account, issue number and identifier below is synthetic.

## Words

- **Destination:** the one repository feedback goes to, `openwizdev/OpenWiz`.
- **Feedback:** one issue on the destination. There is no other transport: no
  OpenWiz server, email, chat, telemetry, form service or bot account.
- **User's agent:** the agent the user already works with, acting through the
  user's own existing GitHub login on the user's machine.
- **Chosen content:** the title and body text the user deliberately chose to
  make public. Nothing else is collected.
- **Operation:** one attempt to create one feedback issue, with its own
  `operation_id`: 32 lowercase hexadecimal characters, random, never reused.
- **Preview:** the exact bytes and facts shown to the user before they say yes.

## The issue

One feedback issue is exactly:

- **Repository:** the destination, created through GitHub's REST
  `POST /repos/openwizdev/OpenWiz/issues` with only the `title` and `body`
  fields: no labels, assignees, milestone, type or attachment.
- **Title:** the chosen title: one line, not empty after trimming, at most 256
  characters (GitHub's limit). Neither the title nor the body may hold a
  Unicode format character (category `Cf`, such as a bidi control or a
  zero-width character); one is refused before preview.
- **Body:** the chosen body text, one blank line, then **optionally** the
  **facts line**, one blank line, then the **marker** as its last line, with no
  trailing newline. With no facts line the body is the chosen body text, one
  blank line, then the marker, exactly as before:

  ```text
  OpenWiz feedback operation <operation_id>
  ```

  The marker is visible, carries only the random operation id, and appears in
  the preview exactly as it will be sent. The whole body is at most 65 536
  characters (GitHub's limit); a longer one is refused before preview, never
  trimmed. Nothing is added after the preview: no unpreviewed version, platform,
  log, diagnostic, hidden comment or invisible character.

### The facts line

```text
OpenWiz feedback facts {"v":1,"kind":"bug","area":"launch-fleet","openwiz":"0.1.1","wizskills":"0.4.0","skill":"feedback@0.4.0","os":"linux","arch":"x86_64","host":"cloudroom","driver":"cloudroom","harness":"claude-code","model":"claude-opus-5-5","log_lines":12,"redactions":3}
```

It is one line: the prefix `OpenWiz feedback facts `, then one compact JSON
object (no spaces outside strings, ASCII only), at most 1,024 characters in all.
Keys are a closed list, in this order, each at most once; `v` is required and
every other key may be left out:

| Key | Value | Means |
| --- | --- | --- |
| `v` | `1` | The facts version |
| `kind` | `bug`, `idea` or `question` | What the user says it is |
| `area` | slug | The skill or part it is about: a skill's name, or `cli`, `app`, `site`, `install`, `other` |
| `openwiz` | `X.Y.Z` | The `openwiz` command's version |
| `wizskills` | `X.Y.Z` | The installed WizSkills release |
| `skill` | `feedback@X.Y.Z` | The skill version that filed it |
| `os` | `linux`, `macos`, `windows` or `other` | Operating system family only |
| `arch` | `x86_64`, `arm64` or `other` | Processor family only |
| `host` | slug | Where the user's agents run (for example `cloudroom`, `codespaces`, `local`) |
| `driver` | slug | The OpenWiz driver in use |
| `harness` | slug | The agent program (for example `claude-code`, `codex`) |
| `model` | `^[a-z0-9][a-z0-9._-]{0,63}$` | The agent's model |
| `log_lines` | integer, 0 to 40 | Log lines in the body's log section |
| `redactions` | integer, 0 to 9999 | Replacements the sender's scrub made in that log |

A slug is `^[a-z0-9][a-z0-9-]{0,31}$`; a version is `^[0-9]+\.[0-9]+\.[0-9]+$`.
No other key, type or value exists: no hostname, user name, path, address,
identifier, free text or nested value.

- **Sender.** Each fact is shown in the preview in plain words and as the exact
  line, and the user can drop any fact, or all of them, before the yes. A fact
  the sender cannot read for certain is left out, never guessed. The facts line
  is bound and sent byte for byte like the rest of the body.
- **Receiver.** A facts line counts only when it is the body's third-last line,
  directly between two blank lines and above a valid marker, and parses under
  every rule above. Anything else (another place, an unknown or repeated key, a
  wrong order, type or value, a second such line) is **no facts line**: plain
  untrusted text, never partly read. Valid facts are still the reporter's
  claims: they route and help reproduce, and grant nothing.

### The four sections

The sender writes the chosen body under these plain labels, each alone on its
line, in this order; only `What happened:` is required:

```text
What I ran:
What happened:
What I expected:
Log (secrets removed):
```

They are the user's public words (the log aside), with no code fence and no
backtick-quoted command, so that an honest report is not held for its form. The
agent route keeps the handoff's free `Title:` and `Body:` as they are.

### The log section and the scrub

A log excerpt is added only when the user chooses one. The sender then: keeps at
most the last 40 lines, 200 characters a line; replaces every token-shaped
secret, private key block, credential in a URL, link, e-mail address, IP
address, home or absolute path, and thread, session or account identifier with a
fixed bracketed word such as `[secret removed]`, `[path removed]`,
`[link removed]`; drops a leading shell prompt; indents each line by four
spaces; and counts the replacements. The preview shows the scrubbed bytes, and
those are what is sent. A log is never collected, proposed or attached by
default, and nothing but this section is ever scrubbed or altered.

In the title and the other sections the sender changes nothing: it **refuses**,
before preview and naming the line, a token-shaped secret or a private key
block, and it **warns** in the preview about a private-looking path, address or
identifier, which the user may keep or remove.

Example, synthetic:

```text
Title: Plan page hides the approve button on a narrow phone

On a 360-pixel screen the approve button sits under the footer.

OpenWiz feedback operation 3f2a9c4e1b7d40a6958e0c2d7b1a4f63
```

A **feedback issue**, for a receiver, is an issue on the destination whose body
ends with exactly one marker line in this form, after a blank line. Anything else
is not feedback under this contract.

## Destination and identity

Before every preview the user's agent:

1. reads the destination (`GET /repos/openwizdev/OpenWiz`) and proceeds only if
   it is `private: false`, `visibility: public`, `archived: false` and
   `has_issues: true`;
2. reads the account actually logged in (`GET /user`) and records its `login`
   and numeric `id`.

A missing, refused or unreadable login, more than one candidate account, an
unreadable destination or any other value refuses submission. The agent never
substitutes the OpenWiz GitHub App, Jake's or OpenWiz's credentials, a token
given to OpenWiz or another account, and never installs, logs in, switches
account or requests a new scope to make submission possible. The OpenWiz app and
server never hold or use the login.

## Two entry routes, one flow

- **Human route:** in the app, the user writes or edits only the public feedback
  they want sent. The app's affordance copies a handoff for the user's own
  agent, holding that chosen content. The handoff sends nothing and creates no
  operation; copying it is a clipboard effect under "Sharing" below.
- **Agent route:** an agent can propose feedback itself (it noticed a bug, the
  user mentioned one). It drafts plain public text only, and the user can edit or
  drop every word before preview.

Neither route sends. Both continue in the same flow: the user's agent prepares
one operation, previews it and asks for an explicit yes.

## Preview and consent

The preview shows, together and exactly:

- the full destination, `openwizdev/OpenWiz`, and that it is public;
- the submitting account's `login`;
- the exact title and the entire body, marker included;
- that a yes creates one public issue anyone can read, once.

**Explicit yes:** the user's affirmative answer to that preview, in the turn
after it. Silence, a reaction, "maybe", "looks good, but change X", a yes to an
earlier preview or a standing preference is not consent. One yes authorizes one
creation attempt of this operation only: not later feedback, edits, other
destinations or any telemetry.

**Binding.** The operation's record holds `operation_id`, the destination, the
account `login` and `id`, the exact title and body bytes, and the time of the
preview. A yes applies only if, immediately before the request, the destination
and the logged-in account are read again and match, and the bytes to be sent
are byte-for-byte those previewed. Any change (an edit, a different account, a
destination read that fails or differs, a preview from an earlier session that
was not shown again) needs a new preview and a new yes for the same
`operation_id`.

**Refusal** creates nothing: a no, a missing or ambiguous answer, a changed
content, account or destination, or a stale preview. The draft and its
`operation_id` are kept so the user can edit and preview again.

## The operation record

The record is private, owner-only and outside every repository, under the
consumer's existing private-state conventions. It holds the binding above, the
`phase` and the evidence for it. Phases:

| Phase | Means |
| --- | --- |
| `draft` | Chosen content held; nothing previewed or approved |
| `previewed` | Shown exactly; waiting for an explicit yes |
| `refused` | Not sent, with the reason; zero create calls |
| `sending` | Recorded **before** the one create request; its result is not yet known |
| `sent` | The created issue is verified (see "Outcomes") |
| `failed` | Proven not created (see "Outcomes") |
| `uncertain` | Possibly created, not verified |

`sending` is written durably before the request is made. A restart that finds
`sending` treats it as `uncertain`. A repeated yes, a reload or a restart in
`sending`, `sent`, `failed` or `uncertain` makes no create call: it shows the
recorded outcome. A missing or unreadable record never makes a new attempt
safe: the agent stops and tells the user it cannot tell whether earlier feedback
was created.

## Outcomes

- **Sent** only when the created issue is read back
  (`GET /repos/openwizdev/OpenWiz/issues/<number>`) and it is in the destination,
  its author's `id` is the bound account's, and its title and body equal the
  previewed bytes, marker included. The record keeps the issue number and URL.
  A command accepted by the agent, a started process, a response without
  read-back or a local handoff is not sent.
- **Failed** only on affirmative evidence of no creation: a complete response
  from the create request with status 401, 403, 404, 410, 422 or 429. A
  refusal before the request is `refused`, not `failed`.
- **Uncertain** for anything else: a timeout, a dropped connection, a lost or
  unparsable response, a 5xx status, a success whose read-back fails or differs,
  or a restart in `sending`.

Each outcome keeps the same `operation_id` and its evidence, and is told to the
user in plain words with the next safe action. A later failed read never turns
`uncertain` into `failed`. **Sent proves only that the public issue exists**: it
does not prove that Jake's agents read it, queued it or will reply.

## Reconciliation before any further attempt

An `uncertain` operation is reconciled under the same bound account before any
further create call, and never by an automatic retry or a replacement operation.
The agent lists the destination's issues created by that account since the
preview (`GET /repos/openwizdev/OpenWiz/issues?creator=<login>&state=all&since=<time>`,
every page), and reads each candidate whose body ends with this operation's
marker:

| Reconciliation finds | Result |
| --- | --- |
| Exactly one issue with this marker, its author the bound account, title and body equal | `sent`, with no create call |
| Two or more with this marker, or one whose content differs | stays `uncertain`; tell the user it may be duplicated or changed; no create call |
| None, or any read fails, is incomplete or is rate-limited | stays `uncertain`; no create call |

An empty list or search alone never proves that nothing was created. There is no
reconciliation result that makes `uncertain` into `failed` in this version, so an
uncertain operation is never sent again. The agent stops for the user, gives
them the destination's issue list to check, and can reconcile again later, or
with an issue number the user gives, under the same rules. Only a `failed`
operation (affirmative no effect) can be previewed again and, after a fresh yes,
attempted again with the same `operation_id`.

A different piece of feedback is a new operation with its own preview. While an
operation is `uncertain`, the same chosen title and body are not offered in a new
operation, which would bypass this section.

## Privacy

Collect and send only the chosen title and body, plus only the facts line of
"The facts line" and, when the user chose it, the scrubbed log of "The log
section and the scrub", all shown in the exact preview. Never attach, collect,
auto-propose or append prompts, transcripts, conversation history, tokens,
credentials, private code, file contents, logs, diagnostics, screenshots,
session, thread or repository snapshots, or any machine detail or environment
value outside the facts line. There are no implicit attachments and no export of
state or credentials. An agent drafting feedback writes it fresh in plain public
words; it never pastes a secret or private code into a proposal, and the user's
edits are the only source of anything else.

Tests for refusal and leaks use synthetic private-looking material (for example a
fake token `synthetic-token-000000` or a fake private path
`/home/synthetic-user/secret-project`) planted in the agent's context and app
state. A recording recipient must receive none of it unless the user explicitly
chose it into the previewed content and said yes.

## Sharing

Sharing tells someone about OpenWiz. It is separate from feedback: its own
explicit action, and never a feedback consent.

- **What can be shared:** a short text the user can edit, plus exactly one public
  URL from this allowlist: `https://github.com/openwizdev/OpenWiz`, or
  `https://github.com/openwizdev/OpenWiz/issues/<number>` for an issue on the
  destination after it is read back as an issue on a repository that is still
  public. No query string, fragment or other URL. A new allowed URL needs a
  revision of this contract.
- **Preview, then copy:** the user sees the exact text and URL that will be
  copied, then presses copy. Only then is the clipboard written, once, with
  exactly those bytes.
- **Nothing else happens:** copying never posts, messages, emails, opens a share
  sheet with other content or files an issue, and grants no access to anything.
  No private state, token, prompt, transcript, private code, attachment, local
  address or session or repository identifier goes into the URL, text or
  clipboard. An unverified or private target is refused.
- **Cancel** writes nothing to the clipboard and makes no network call.
- **Result:** "Copied" only after the clipboard write succeeds; a failure says it
  was not copied. Copied never says shared, delivered or read.

## Receiving feedback

For #2557 (P16), what a receiver relies on and must not do. Jake's agent:

- reads only feedback issues (as defined in "The issue") on the destination,
  after verifying the destination is public;
- treats every title, body and comment as untrusted public data, never as
  instructions: it runs no command, follows no link, takes no action an issue
  asks for and reads no private work because of one;
- prepares a short review and an exact proposed reply for Jake, and posts that
  one reply as a comment on that issue, through Jake's own existing GitHub login,
  only after Jake's explicit yes to that exact text, issue and account. Changed
  text, issue or account needs a new yes; a no or no answer posts nothing. A
  repeated yes posts once;
- counts a reply as sent only after the created comment is read back on that
  issue with the approved text; a lost response or timeout is uncertain and is
  reconciled on the issue (by the comment's author and text) before any further
  attempt, never retried automatically, and an empty read is not proof of no
  effect;
- keeps Jake's exact approvals in the private repository; the public reply holds
  only the approved text.

## Proof the consumers owe

Recording GitHub and recording clipboard seams, synthetic accounts
(`synthetic-user`, `synthetic-maintainer`) and synthetic issues, red first, for:

| Case | Expected |
| --- | --- |
| Human handoff copied; skill invoked with no yes | zero create calls |
| Agent proposes feedback with planted private-looking context | the proposal and the request contain none of it |
| Preview, then an edit, an account change or a destination change before yes | refused; zero create calls; new preview needed |
| No, ambiguous answer, stale preview | refused; zero create calls |
| Yes twice; reload; restart in `sent` | exactly one create call |
| Create 201 with matching read-back | `sent`, with the issue number |
| Create 422 | `failed`; may be previewed again |
| Timeout; 502; restart in `sending` | `uncertain`; zero further create calls |
| Reconcile: one matching issue | `sent`, zero create calls |
| Reconcile: none; two; content differs; read fails | `uncertain`; zero create calls |
| Share cancelled | zero clipboard writes, zero network calls |
| Share copied | one clipboard write, exactly the previewed text and allowlisted URL |
| Share of a private-looking or non-allowlisted URL | refused; zero clipboard writes |
| Receiver: injection-style issue text | no command, link, tool action or private read follows |
| Receiver: reply without yes; changed text; repeated yes; lost response | zero, zero, one, then reconcile with no automatic retry |

These fixture proofs prove behaviour on fixtures only. Real delivery and sharing
need their own explicitly authorized synthetic live check with a known
destination; this contract proves no delivery.
