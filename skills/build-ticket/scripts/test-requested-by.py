import json
from pathlib import Path
import subprocess
import sys
import unittest


SCRIPT = Path(__file__).with_name("requested_by.py")
LINK = {"label": "Sample docs", "url": "https://example.org/docs"}
CREDIT = "Requested by @synthetic-reader"


def draft(**changes):
    return {
        "labels": ["subscriber-request"],
        "request": {"intake": "public", "author": "synthetic-reader"},
        "pr_body": "## Summary\n\nShow sample settings.\n",
        "changelog_line": "Show sample settings.\n",
        "listing_links": [LINK],
        **changes,
    }


def run(data):
    return subprocess.run(
        [sys.executable, "-I", SCRIPT], input=data, text=True, capture_output=True
    )


class RequestedByTest(unittest.TestCase):
    def render(self, **changes):
        result = run(json.dumps(draft(**changes)))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_public_credit_ends_each_destination_and_keeps_existing_links(self):
        self.assertEqual(self.render(), {
            "pr_body": "## Summary\n\nShow sample settings.\n\n" + CREDIT + "\n",
            "changelog_line": "Show sample settings. " + CREDIT + "\n",
            "listing_links": [
                LINK, {"label": CREDIT, "url": "https://github.com/synthetic-reader"}
            ],
        })

    def test_private_missing_invalid_or_unlabelled_source_keeps_drafts(self):
        cases = [
            {"request": {"intake": "owner-private", "author": "synthetic-private",
                         "visibility": "private"}},
            {"request": {"intake": "owner-private", "author": "synthetic-private",
                         "visibility": "public"}},
            {"request": {"intake": "public", "author": "synthetic-private",
                         "visibility": "private"}},
            {"request": None},
            {"request": {"author": "synthetic-reader"}},
            {"request": {"intake": "public", "author": "synthetic-reader",
                         "visibility": None}},
            {"request": {"intake": "public", "author": "sample\n@synthetic-other"}},
            {"request": {"intake": "public", "author": "a" * 40}},
            {"request": {"intake": "public", "author": "synthetic--reader"}},
            {"request": {"intake": "public", "author": "synthetic-reader", "extra": True}},
            {"labels": ["subscriber-requested"]},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                self.assertEqual(self.render(**changes), {
                    "pr_body": "## Summary\n\nShow sample settings.\n",
                    "changelog_line": "Show sample settings.\n",
                    "listing_links": [LINK],
                })

    def test_repeat_credit_is_idempotent_and_listing_is_optional(self):
        first = self.render(listing_links=None)
        self.assertTrue(first["changelog_line"].endswith(CREDIT + "\n"))
        self.assertIsNone(first["listing_links"])
        market = self.render()
        self.assertEqual(self.render(**market), market)
        self.assertEqual(self.render(**first), first)

    def test_refuses_malformed_json_and_duplicate_fields_with_fixed_diagnostic(self):
        for data in ['{"synthetic-private":', '{"request":null,"request":{}}',
                     json.dumps(draft(labels="subscriber-request")),
                     json.dumps(draft(listing_links=["synthetic-private"]))]:
            with self.subTest(data=data):
                result = run(data)
                self.assertEqual(result.stdout, "")
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stderr, "Invalid attribution input.\n")


if __name__ == "__main__":
    unittest.main()
