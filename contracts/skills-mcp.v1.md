# Skills over MCP, version 1 (`openwiz.skills-mcp.v1`)

Ticket [MP1](https://github.com/openwizdev/OpenWiz/issues/3774) defines the interface for the local server, role filter and pinned loader. The [fixtures](fixtures/skills-mcp/) are synthetic inputs and expected outputs for those consumers to run.

## Stdio

Use the [MCP 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25) message shapes over stdio. Use UTF-8, one JSON-RPC 2.0 object per line, with embedded newlines escaped inside strings. Reserve stdout for replies and stderr for fixed diagnostics. End the session at EOF.

| Request | Parameters | Result |
| --- | --- | --- |
| `initialize` | MCP `protocolVersion`, `capabilities` and `clientInfo` | `protocolVersion: "2025-11-25"`, `capabilities: {"prompts": {}, "resources": {}}`, `serverInfo: {"name": "wizskills", "version": "1"}` |
| `prompts/list` | None required | `prompts`, one `{name, description}` per visible skill |
| `prompts/get` | `name` and optional empty `arguments` | `description` and one entry in `messages` with `role: "user"` and `content: {type: "text", text: <body>}` |
| `resources/list` | None required | `resources`, one `{uri, name, mimeType}` per visible text file |
| `resources/read` | `uri` | `contents`, one `{uri, mimeType, text}` for the visible file |

`initialize` returns the supported version even when the client proposes another. A client that cannot use it stops. The client then sends `notifications/initialized`. Notifications get no reply. List calls return the entire visible inventory in ascending name or URI order, with no `nextCursor`. Clients omit the cursor. The server advertises neither tools nor list-change notifications.

This profile supports the five requests in the table. A request for any other method, including `tools/list` or `ping`, returns method not found. Clients that require the optional MCP ping mechanism need a server that implements it.

A reply echoes the request's string or integer `id`. Error objects use the code and message below, with no request contents in the message. A refused line leaves the server ready to read the next one.

| Code | Message | When |
| --- | --- | --- |
| `-32700` | Parse error | Unreadable UTF-8 or JSON syntax. Omit `id`. |
| `-32600` | Invalid Request | The decoded line is not a JSON-RPC 2.0 request or notification object, including a batch. Omit `id` when the ID cannot be read. |
| `-32601` | Method not found | An unsupported request method. |
| `-32602` | Invalid params | Missing or invalid method parameters, or an unknown or out-of-scope prompt name. |
| `-32002` | Resource not found | The URI does not name an exact entry in the visible resource inventory. |

## Prompts and resources

Load skills from `skills/<skill>/SKILL.md` under the selected checkout. Use the front matter's `name` and `description` as prompt metadata. The name identifies the skill and matches its folder. A skill name consists of lowercase ASCII letters and digits joined in groups by single hyphens. The prompt text is the file content after the closing front matter delimiter and its line break, with the remaining whitespace preserved.

Serve regular UTF-8 text files within each visible skill folder, including `SKILL.md`, as `text/plain`. Exclude binary files, including files with NUL bytes or invalid UTF-8, and exclude symlink entries and symlinked directory components. Form each URI as `wizskills://<skill>/<path>`. Use the skill-relative path, percent-encode each UTF-8 segment as needed with uppercase hex escapes, and keep separator slashes. The resource's `name` is the unencoded relative path, and `text` is its decoded file content. A read matches the literal URI against the visible inventory before opening a file and still enforces confinement when it reads it.

## Sources

`--from <folder>` selects a local WizSkills checkout, defaulting to the server's checkout. For a remote checkout use `--from github:<owner>/<repo>@<commit>` with `--tree <tree>`. Copy the full commit and tree IDs from the `commit` and `tree` fields of `wizskills.lock`. Both are 40 lowercase hexadecimal characters. Resolve the pinned commit itself and check its complete tree against the supplied tree ID before serving anything, including on a cache hit.

Use the owner's signed-in `gh` as a subprocess for a pinned fetch. The server never asks for, reads or prints a token. Cache only within the server's own cache folder. A cached pinned commit is re-verified without a fetch. A new download that fails verification is discarded within that cache, with no fallback to an unverified source.

| Refusal | When |
| --- | --- |
| `invalid-source` | Malformed repository source, or a local source paired with `--tree`. |
| `unpinned-commit` | A GitHub ref that is not a full pinned commit ID, including a branch, tag or short SHA. |
| `missing-tree` | The GitHub pin has no `--tree`. |
| `invalid-tree` | The tree ID is not 40 lowercase hex characters. |
| `tree-mismatch` | The observed tree differs from the requested tree. |
| `source-unavailable` | The selected checkout or pinned commit cannot be read. |

Check the remote syntax and both pins before a fetch. A refusal at startup exits nonzero with a line containing its reason on stderr and leaves stdout empty.

## Role scopes

A roles file is a UTF-8 JSON object with `contract: "openwiz.skills-roles.v1"` and a `roles` map. The [roles schema](skills-mcp.v1.schema.json) fixes the shape. The four allowed Roster roles are `orchestrator`, `builder`, `reviewer` and `helper`. Each role maps to distinct skill names. Omit a role to leave it unavailable. Use an empty array to make a role available with no skills. [Roster roles](roster.v1.md#words)

With no `--role`, serve the complete skill inventory. With `--role <role>`, load and validate the chosen roles file and check every named skill against the selected source. Refuse an unreadable or schema-invalid file, including duplicate JSON object keys, with `invalid-roles`. Refuse a missing inventory name with `unknown-skill` and a requested role absent from the map with `unknown-role`. Use the same filtered inventory for list and read methods, including direct prompt and resource lookup.

## Privacy and proof

Read served files only within the selected skills tree. Read role configuration only from the designated roles file. The remote loader inspects the pinned source and tree metadata for verification. Serve skill files only, and write only the server-owned cache. Never probe secrets, credential stores, sign-in files or unrelated user files. Selected sources are intended for sharing with the harness. Keep secrets out of them.

- [`protocol.json`](fixtures/skills-mcp/protocol.json) gives the checkout's text files, binary byte arrays, and symlinks relative to each link's parent. Start each case with a fresh server and apply `start` first unless `fresh` is true. Each step writes `send` as JSON or `line` as literal input plus a newline. Compare the decoded object with `reply`. A null `reply` means silence.
- [`roles.json`](fixtures/skills-mcp/roles.json) gives the inventory, roles file documents and expected schema and runtime results. For `hidden`, check both lists and direct access to that skill's prompt and resources. A well-formed file naming an absent skill passes the schema and fails the inventory check.
- [`sources.json`](fixtures/skills-mcp/sources.json) supplies synthetic arguments, observed trees, cache conditions and expected fetch counts or refusals. Pack `archiveFiles` as regular 0644 UTF-8 files for the synthetic fetch. `discard` means remove the rejected new download. Use a fake fetcher, never live GitHub.
