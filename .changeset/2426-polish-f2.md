---
"launch-fleet": patch
"to-tickets": patch
---

launch-fleet's fixture runner runs a focused `again` case after the cases it follows, without reading a missing parent output first, and fleet.sh and to-tickets' check-approval.sh drop redundant comments inside their jq filters.
