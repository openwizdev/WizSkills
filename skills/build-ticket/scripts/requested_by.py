import argparse
import json
import re
import sys


LOGIN = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
FIELDS = {"labels", "request", "pr_body", "changelog_line", "listing_links"}
HELP = """Follow the verified triage record to the original GitHub request.
Confirm the source repository is public and in the subscriber requests contract
scope. Verify the original issue's request marker and visibility, and take its
authenticated author from GitHub.
Contract: https://github.com/openwizdev/OpenWiz/blob/main/contracts/subscriber-requests.v1.md

Pass one JSON object on stdin:
  labels           Ticket label names from GitHub.
  request          Object with intake "public", author and visibility
                   from the verified source. Omit visibility only if the
                   original request omits it. Use null for a private,
                   missing or unverified source.
  pr_body          Public pull request draft body.
  changelog_line   Public changelog draft summary line.
  listing_links    Public listing's links array, or null without a listing.

stdout returns pr_body, changelog_line and listing_links. Use those values
before committing the changelog and opening or updating the PR or listing.
Exit 2 means the input was invalid.
"""


def unique_object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError
    return obj


def credit_login(labels, request):
    if "subscriber-request" not in labels or not isinstance(request, dict):
        return None
    if set(request) not in ({"intake", "author"}, {"intake", "author", "visibility"}):
        return None
    if request["intake"] != "public" or request.get("visibility", "public") != "public":
        return None
    login = request["author"]
    if isinstance(login, str) and len(login) <= 39 and LOGIN.fullmatch(login):
        return login
    return None


def valid_links(links):
    return links is None or isinstance(links, list) and all(
        isinstance(link, dict) and set(link) == {"label", "url"}
        and all(isinstance(value, str) for value in link.values())
        for link in links
    )


def render(data):
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError
    labels = data["labels"]
    body, changelog, links = data["pr_body"], data["changelog_line"], data["listing_links"]
    if (not isinstance(labels, list) or not all(isinstance(label, str) for label in labels)
            or not isinstance(body, str) or not isinstance(changelog, str) or not valid_links(links)):
        raise ValueError

    login = credit_login(labels, data["request"])
    if login:
        credit = f"Requested by @{login}"
        if body.rstrip().split("\n")[-1] != credit:
            body = f"{body.rstrip()}\n\n{credit}\n" if body.strip() else f"{credit}\n"
        if changelog.rstrip() != credit and not changelog.rstrip().endswith(f" {credit}"):
            changelog = f"{changelog.rstrip()} {credit}\n" if changelog.strip() else f"{credit}\n"
        link = {"label": credit, "url": f"https://github.com/{login}"}
        if links is not None and link not in links:
            links = [*links, link]
    return {"pr_body": body, "changelog_line": changelog, "listing_links": links}


def main():
    parser = argparse.ArgumentParser(
        description=HELP, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.parse_args()
    try:
        result = render(json.load(sys.stdin, object_pairs_hook=unique_object))
    except (ValueError, RecursionError):
        print("Invalid attribution input.", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
