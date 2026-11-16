"""A fake `gh` for check-helpers.sh's test: the reads the check makes, over a
synthetic repository, shaped as GitHub and gh 2.100 answer them. Any other
call (a write, a flag it doesn't know, another path) exits 3, so a check
that writes, or reads something else, fails its case.

  gh repo view --json nameWithOwner --jq .nameWithOwner
  gh api repos/<repo>/issues/<n>                        an issue (or a pull request, as an issue)
  gh api repos/<repo>/pulls/<n>                         a pull request
  gh api --paginate repos/<repo>/git/matching-refs/heads/<prefix>
  gh api --paginate repos/<repo>/issues/<n>/comments?per_page=<k>
  gh api --paginate repos/<repo>/pulls/<n>/reviews?per_page=<k>
  gh api --paginate repos/<repo>/pulls/<n>/comments?per_page=<k>

Lists come in pages of FAKE_GH_PAGE items (default: per_page), one JSON array
after another, as gh prints them; without --paginate, only the first page.
Each call is logged to FAKE_GH_LOG as one line ("issue 12", "refs room/12-",
"comments 12", ...). The repository is the JSON file FAKE_GH_WORLD:

  {"repo": "owner/name",
   "issues": {"<n>": {"pull": bool, "comments": [{"id", "body", "updated_at"}]}},
   "pulls": {"<n>": {"state", "merged", "head", "reviews": [{"id", "body", "state", "submitted_at"}],
                     "review_comments": [{"id", "body", "updated_at"}]}},
   "refs": {"<branch>": "<commit>"}}

FAKE_GH_FAULT="<log line>=<kind>" breaks that one call:
  fail       exit 1, nothing on stdout
  cut        the first page, then exit 1 (a read that fails part way)
  empty      nothing at all, exit 0
  truncated  the first page cut in half, exit 0
  object     {"message": "Not Found"}, exit 0
  null       null, exit 0
  repeat     every page, then the first page again, exit 0
  noid       the first item without its id (or ref, or number)
  nullbody   the first item's body null (a ref: its sha not a commit)
  outside    one more ref, outside the prefix (refs only)
  twice      the first ref twice (refs only)
  two        the one object twice (an issue or a pull request)
"""

import json
import os
import re
import sys
from urllib.parse import parse_qs, urlsplit


def die(code, msg):
    sys.stderr.write(msg + "\n")
    sys.exit(code)


def log(line):
    with open(os.environ["FAKE_GH_LOG"], "a", encoding="utf-8") as f:
        f.write(line + "\n")


FLEET = ("# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n"
         "| Record authors | `openwiz[bot]`, `robin` |\n\n## Standing merge rules\n")


def main(argv):
    world_path = os.environ.get("FAKE_GH_WORLD")
    if not world_path or "FAKE_GH_LOG" not in os.environ:
        die(3, "fake gh: FAKE_GH_WORLD and FAKE_GH_LOG must be set")
    with open(world_path, encoding="utf-8") as f:
        world = json.load(f)
    repo = world["repo"]
    fault_at, _, fault = os.environ.get("FAKE_GH_FAULT", "").partition("=")

    if argv == ["repo", "view", repo, "--json", "isPrivate", "--jq", ".isPrivate"]:
        print("true" if world.get("private", True) else "false")
        return
    if argv == ["repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]:
        log("repo view")
        if fault_at == "repo view":
            die(1, "fake gh: no git remotes found")
        print(repo)
        return
    # #717: the one raw read of the Record authors setting, from the world's
    # "fleet" text (FLEET below unless the world names its own).
    if argv == ["api", "-H", "Accept: application/vnd.github.raw+json",
                f"repos/{repo}/contents/docs/agents/fleet.md"]:
        log("fleet")
        if fault_at == "fleet":
            die(1, "gh: Not Found (HTTP 404)")
        sys.stdout.write(world.get("fleet", FLEET))
        return
    if not argv or argv[0] != "api":
        die(3, f"fake gh: unexpected call: gh {' '.join(argv)}")
    paginate = False
    rest = argv[1:]
    if rest[:1] == ["--paginate"]:
        paginate, rest = True, rest[1:]
    if len(rest) != 1 or rest[0].startswith("-"):
        die(3, f"fake gh: unexpected call: gh {' '.join(argv)}")
    url = urlsplit(rest[0])
    query = parse_qs(url.query)
    path = url.path
    base = f"repos/{repo}/"
    if not path.startswith(base):
        die(3, f"fake gh: not this repository: {path}")
    path = path[len(base):]

    m = re.fullmatch(r"(issues|pulls)/([0-9]+)", path)
    if m and not paginate and not query:
        kind, n = m.group(1), m.group(2)
        line = f"{'issue' if kind == 'issues' else 'pull'} {n}"
        log(line)
        if kind == "issues":
            issue = world["issues"].get(n)
            if issue is None:
                die(1, "gh: Not Found (HTTP 404)")
            item = {"number": int(n), "title": f"Synthetic #{n}", "state": "open", "user": {"login": "robin"}}
            if issue.get("pull"):
                item["pull_request"] = {"url": f"https://api.github.invalid/{n}", "merged_at": None}
        else:
            pull = world["pulls"].get(n)
            if pull is None:
                die(1, "gh: Not Found (HTTP 404)")
            item = {"number": int(n), "title": f"Synthetic #{n}", "state": pull["state"], "merged": pull["merged"],
                    "head": {"ref": pull["head"], "sha": world["refs"].get(pull["head"], "0" * 40),
                             "label": f"example:{pull['head']}"}, "user": {"login": "robin"}}
        answer(line, fault_at, fault, [[item]], single=True)
        return

    m = re.fullmatch(r"git/matching-refs/heads/(.+)", path)
    if m and not query:
        prefix = m.group(1)
        line = f"refs {prefix}"
        log(line)
        items = [{"ref": f"refs/heads/{name}", "node_id": "REF_synthetic",
                  "url": f"https://api.github.invalid/refs/heads/{name}",
                  "object": {"sha": sha, "type": "commit", "url": "https://api.github.invalid/commit"}}
                 for name, sha in sorted(world["refs"].items()) if name.startswith(prefix)]
        if line == fault_at and fault == "outside":
            items.append({"ref": "refs/heads/main", "object": {"sha": "0" * 40, "type": "commit"}})
        if line == fault_at and fault == "twice" and items:
            items.insert(1, items[0])
        # GitHub answers matching-refs in one page, whatever per_page says.
        answer(line, fault_at, fault, [items], key="ref")
        return

    m = re.fullmatch(r"(issues|pulls)/([0-9]+)/(comments|reviews)", path)
    if m and set(query) == {"per_page"}:
        kind, n, what = m.groups()
        per_page = int(query["per_page"][0])
        if kind == "issues" and what == "comments":
            line, source = f"comments {n}", world["issues"].get(n, {}).get("comments")
        elif kind == "pulls" and what == "reviews":
            line, source = f"reviews {n}", world["pulls"].get(n, {}).get("reviews")
        elif kind == "pulls":
            line, source = f"review comments {n}", world["pulls"].get(n, {}).get("review_comments")
        else:
            die(3, f"fake gh: unexpected read: {path}")
        log(line)
        if source is None:
            die(1, "gh: Not Found (HTTP 404)")
        items = []
        for c in sorted(source, key=lambda c: c["id"]):
            # A comment names its own "user" (null: a deleted account); else robin's.
            item = {"id": c["id"], "node_id": f"N_{c['id']}", "user": c.get("user", {"login": "robin"}),
                    "body": c["body"],
                    "author_association": "OWNER"}
            if what == "reviews":
                item.update({"state": c["state"], "submitted_at": c["submitted_at"], "commit_id": "a" * 40})
            else:
                item.update({"created_at": "2026-11-01T09:00:00Z", "updated_at": c["updated_at"]})
            items.append(item)
        size = int(os.environ.get("FAKE_GH_PAGE") or per_page)
        pages = [items[i:i + size] for i in range(0, len(items), size)] or [[]]
        if not paginate:
            pages = pages[:1]
        answer(line, fault_at, fault, pages, key="id")
        return

    die(3, f"fake gh: unexpected call: gh {' '.join(argv)}")


def answer(line, fault_at, fault, pages, key=None, single=False):
    """Print the pages as gh does (a single object for a plain read), or break
    them as FAKE_GH_FAULT says when it names this call."""
    if line == fault_at:
        if fault == "fail":
            die(1, "gh: HTTP 502: Bad Gateway")
        if fault == "empty":
            return
        if fault == "object":
            print(json.dumps({"message": "Not Found"}))
            return
        if fault == "null":
            print("null")
            return
        if fault in ("noid", "nullbody") and pages and pages[0]:
            first = pages[0][0]
            if fault == "noid":
                for k in (key, "number"):
                    first.pop(k, None)
            elif "object" in first:
                first["object"]["sha"] = "not-a-commit"
            else:
                first["body"] = None
        if fault == "truncated":
            text = json.dumps(pages[0][0] if single else pages[0])
            sys.stdout.write(text[: len(text) // 2])
            return
        if fault == "cut":
            sys.stdout.write(json.dumps(pages[0]))
            sys.stdout.flush()
            die(1, "gh: HTTP 502: Bad Gateway")
        if fault == "repeat":
            pages = pages + pages[:1]
    if single:
        print(json.dumps(pages[0][0]))
        if line == fault_at and fault == "two":
            print(json.dumps(pages[0][0]))
        return
    for page in pages:
        sys.stdout.write(json.dumps(page))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main(sys.argv[1:])
