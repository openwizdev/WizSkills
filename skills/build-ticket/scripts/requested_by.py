import json
import sys


def render(data):
    return {
        "pr_body": data["pr_body"],
        "changelog_line": data["changelog_line"],
        "listing_links": data["listing_links"],
    }


if __name__ == "__main__":
    print(json.dumps(render(json.load(sys.stdin))))
