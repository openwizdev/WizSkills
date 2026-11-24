# Triage labels

The skills talk about five triage roles. This file maps each role to the label this project's tracker uses for it.

## Labels

| Role | Label here | Meaning |
| --- | --- | --- |
| `needs-triage` | `<label>` | Maintainer needs to evaluate this issue |
| `needs-info` | `<label>` | Waiting on reporter for more information |
| `ready-for-agent` | `<label>` | Fully specified, ready for an agent to take unattended |
| `ready-for-human` | `<label>` | Requires human implementation |
| `wontfix` | `<label>` | Will not be actioned |

When a skill names a role (for example, "label it ready for an agent"), use that role's label from this table. Each label exists in the tracker exactly once.

## Optional Pro triage

| Label | Colour | Description |
| --- | --- | --- |
| `pro` | `#8250DF` | Opened by a Pro member |

Automatic labelling is off by default. To turn it on, create `pro` in the issue tracker and add a line reading Pro repository: followed by owner/name of the private Pro repository. The label is public, so turn it on only where the project tells its Pro members about it.
