# Forges

The record is the same on GitHub, GitLab, and Cursor Origin. The body is markdown. The fence is the record. Labels, boards, and approval buttons are not.

Field rules stay in [spec.md](spec.md). The pull request record stays in [agent-pr](../agent-pr/spec.md).

## GitHub

An issue or pull request description holds the fence. The title follows the title rule. A review is one pull request comment, not a line thread and not the Approve button. Read the head sha, the required checks on that sha, and whether the pull request can merge. The JSON `closes` field does not link the issue natively; put `Closes #N` on its own line outside the fence before merge (within the three-line prose limit), while `closes` in the record stays authoritative. Merge through the merge queue when the repository has one. After merge, verify issue `#N` is closed; if GitHub left it open, close it.

## GitLab

A merge request description holds the fence. The review is one note on that merge request. The pipeline that counts is the one for the head sha in the verdict. The JSON `closes` field does not link the issue natively; put `Closes #N` on its own line outside the fence before merge (within the three-line prose limit), while `closes` in the record stays authoritative. Merge when that pipeline succeeded and GitLab reports the merge request can merge. After merge, verify issue `#N` is closed; if GitLab left it open, close it.

## Cursor Origin

A pull request description holds the fence. The review is one comment. Read the head sha, the checks on it, and whether the pull request merges cleanly. Use the forge's normal merge. If the forge did not close the issue, close it after the merge.

## All three

Do not fork the schema per forge. `ready` in the body wins over any label. Do not put secrets in the description, the comment, or a commit. Before merge, the verdict sha is a prefix of the full head, not a different commit.
