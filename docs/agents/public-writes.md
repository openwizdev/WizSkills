# Public writes

The card for every public write: a commit, branch, pull request, issue, comment or file on `openwizdev/OpenWiz` or `openwizdev/WizSkills`. It sums up the [open development contract](../../contracts/open-development.v1.md); when they disagree, the contract wins. Read the whole contract only for release, publishing, importer, ticket-mover, privacy-check or workflow-runner work.

**Never public:** a thread id (`thr_…`) or other CloudRoom id (`proj_`, `prj_`, `mch_`, `usr_`, `acct_`, `auto_`, `cr_…`); a loop id, token or secret; a home folder (`/Users/<name>`, `/home/<name>`); a real email address; a machine or account name or any personal fact; anyone's exact words from a decision; live session content; any file under `private/` or `docs/grills/` (bar its README). Those stay in `jparker2006/ClosedWiz`.

**Synthetic forms are fine:** `thr_syn…`, `prj_syn…` (any prefix + `syn` or `web`), `/home/runner`, `/home/synthetic…`, `@example.com`, GitHub noreply addresses. Fixtures, examples and red logs use only these.

**A decision in public** is who, the date, the decision in your own plain words with no double quotes, then the pointer, exactly one comment URL: `https://github.com/jparker2006/ClosedWiz/issues/<N>#issuecomment-<C>`. Approval comments open `**Approved on its own by <decider>, <YYYY-MM-DD>:**` (or `**Spec confirmed by`, `**Plan graph approved by`) with `Private record: <pointer>` as the next line; a document source is `<decider>, <YYYY-MM-DD>: <decision> ([private record](<pointer>)).` Save the exact words in the private comment first.

**Fleet records** (`launch-fleet: …`) and every other public record name tickets, pull requests, commits and branches, never a thread.

**Checks do the rest:** commits must be authored by a GitHub noreply address (`$T author` sets it); the pre-push hook and CI's `privacy` check refuse the shapes above in the tree, commit messages and pull request title and body. Nothing checks an issue or pull request comment for you: before `gh ... comment --body-file <file>`, run `python3 -I skills/launch-fleet/scripts/context.py check <file>`. Images and quoted personal facts are the reviewer's to catch.
