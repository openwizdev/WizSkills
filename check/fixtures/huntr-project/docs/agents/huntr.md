# Synthetic huntr consumer (test-only)

This invented project is only an input to the carried huntr suites. The issue
number, policy and paths below are synthetic fixtures, not project authority.
No real consumer settings or private procedure are copied into this package.

```json
{
  "version": 2,
  "label": "huntr",
  "switch_issue": 394,
  "max_changed_lines": 200,
  "open_cap": 50,
  "max_tier": 3,
  "tiers": {
    "0": [],
    "1": [
      "tests",
      "docs"
    ],
    "2": [
      "code",
      "tests",
      "docs"
    ],
    "3": [
      "code",
      "tests",
      "docs"
    ]
  },
  "groups": {
    "code": {
      "prefixes": [
        "crates/core/src/",
        "crates/server/src/",
        "apps/web/src/"
      ],
      "suffixes": [
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".mjs"
      ],
      "root_suffixes": []
    },
    "tests": {
      "prefixes": [
        "tests/",
        "apps/web/test/"
      ],
      "suffixes": [],
      "root_suffixes": []
    },
    "docs": {
      "prefixes": [
        "docs/"
      ],
      "suffixes": [],
      "root_suffixes": [
        ".md"
      ]
    }
  },
  "never_prefixes": [
    "crates/adapters/cloudroom/src/allowlist.rs",
    "crates/core/src/limits.rs",
    "release/openwiz/",
    "contracts/",
    ".github/",
    "ci/runner/",
    ".githooks/",
    "skills/",
    "docs/agents/",
    "docs/adr/",
    "docs/grills/",
    ".claude-plugin/"
  ],
  "never_names": [
    "AGENTS.md",
    "CLAUDE.md",
    "Cargo.toml",
    "Cargo.lock",
    "package.json",
    "package-lock.json",
    "rust-toolchain.toml"
  ],
  "never_name_prefixes": [
    ".env",
    "requirements"
  ],
  "never_components": [
    ".git",
    ".cargo"
  ],
  "never_suffixes": [
    ".schema.json"
  ]
}
```

## Slice manifests (#696)

For this synthetic handoff, each numbered part is bounded to 65,536 bytes.
Use `pack run-record.json` to prepare parts and `unpack readback.json` to
verify every part against the saved digest. An index has links to every part;
verify the index and read-back before archival. These names are fixture data.
