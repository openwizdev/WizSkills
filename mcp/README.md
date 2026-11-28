# WizSkills MCP server

A Python standard-library MCP server (`mcp/server.py`, no extra dependencies) that serves WizSkills over stdio under [`openwiz.skills-mcp.v1`](../contracts/skills-mcp.v1.md) (MCP protocol version `2025-11-25`).

## What it serves

- **Prompts (`prompts/list`, `prompts/get`):** one prompt per skill under `skills/<skill>/SKILL.md`, with front matter `name` and `description`, and the body after the closing `---` delimiter as the prompt text.
- **Resources (`resources/list`, `resources/read`):** every regular UTF-8 text file under each visible skill folder (including `SKILL.md`), with URI `wizskills://<skill>/<path>` (`mimeType: "text/plain"`). Binary files (NUL bytes or invalid UTF-8) and symlinks are excluded at load time and re-checked on every read.
- **No tools:** `tools/list` and any other unsupported method return JSON-RPC `-32601` (`Method not found`). The server is read-only over the selected skills directory.

## Options

```sh
python3 -I mcp/server.py [--from <folder>]
```

- `--from <folder>`: local WizSkills checkout to serve (defaults to the checkout containing `mcp/server.py`).
- **Role scopes (`--role <role>`, `--roles <file>`):** planned in [openwizdev/OpenWiz#3776](https://github.com/openwizdev/OpenWiz/issues/3776) (MP3) to serve only one role's skills from `openwiz.skills-roles.v1`.
- **Pinned GitHub source (`--from github:<owner>/<repo>@<commit> --tree <tree>`):** planned in [openwizdev/OpenWiz#3777](https://github.com/openwizdev/OpenWiz/issues/3777) (MP4) to load and verify a pinned commit through `gh`.

## Add to an MCP client

Point your client at `python3 -I <path-to-wizskills>/mcp/server.py` (optionally adding `--from <checkout>`).

### Claude Code

```sh
claude mcp add wizskills -- python3 -I /path/to/WizSkills/mcp/server.py
```

### Codex

Add a stdio server block in `~/.codex/config.toml`:

```toml
[mcp_servers.wizskills]
command = "python3"
args = ["-I", "/path/to/WizSkills/mcp/server.py"]
```

### T3

Add an MCP stdio server named `wizskills` with command `python3` and arguments `["-I", "/path/to/WizSkills/mcp/server.py"]` in T3's MCP server settings.

### Any MCP client

Configure a stdio MCP server with:

- **Command:** `python3`
- **Arguments:** `["-I", "/path/to/WizSkills/mcp/server.py"]`
- **Transport:** line-delimited JSON-RPC 2.0 over stdio (`2025-11-25`)

## Extension seams

Protocol handling (`handle_line`, `handle_request`, `serve`) reads only an `Inventory` and needs no edits when adding role scopes or remote sources:

- **Skill filter (`apply_filter(inventory, skill_filter)`):** pass a callable `skill_filter(skill_names: list[str]) -> Iterable[str]` to `load_inventory(checkout_root, skill_filter=...)` (or `main(argv, skill_filter=...)`). `apply_filter` restricts both prompts and resources to the returned names in ascending order and raises `StartupError("unknown-skill")` if any name is absent from the inventory. Role scopes (#3776) plug in here.
- **Source resolver (`resolve_source(from_arg)`):** validates `--from` and returns the resolved local checkout root, raising `StartupError` (`invalid-source` or `source-unavailable`) on refusal. Pinned GitHub loading (#3777) plugs in here.

## Tests

```sh
python3 -I mcp/test_server.py
```
