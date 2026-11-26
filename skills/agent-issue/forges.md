# Forges

The record is the same on GitHub, GitLab, and Cursor Origin. The body is markdown. The fence is the record. Labels, boards, and approval buttons are not.

Field rules stay in [spec.md](spec.md). The pull request record stays in [agent-pr](../agent-pr/spec.md).

## GitHub

An issue or pull request description holds the fence. The title follows the title rule. A review is one pull request comment, not a line thread and not the Approve button. Read the head sha, the required checks on that sha, and whether the pull request can merge. `Closes #N` may sit outside the fence. `closes` in the record is authoritative. Merge through the merge queue when the repository has one.

## GitLab

A merge request description holds the fence. The review is one note on that merge request. The pipeline that counts is the one for the head sha in the verdict. Merge when that pipeline succeeded and GitLab reports the merge request can merge.

## Cursor Origin

A pull request description holds the fence. The review is one comment. Read the head sha, the checks on it, and whether the pull request merges cleanly. Use the forge's normal merge. If the forge did not close the issue, close it after the merge.

## All three

Do not fork the schema per forge. `ready` in the body wins over any label. Do not put secrets in the description, the comment, or a commit. Before merge, the verdict sha is a prefix of the full head, not a different commit.
