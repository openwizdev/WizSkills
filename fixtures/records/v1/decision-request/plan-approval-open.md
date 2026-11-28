```json
{
  "id": "golden-plan",
  "risk": "ordinary",
  "spec": 40,
  "summary": [
    "List the notes in date order.",
    "Export the notes as plain text."
  ],
  "headline": "The notebook lists your notes in date order.",
  "tickets": [
    {
      "number": 41,
      "title": "0.9.9 GN1: notes list in date order",
      "blockers": []
    },
    {
      "number": 42,
      "title": "0.9.9 GN2: plain text export",
      "blockers": [
        41
      ]
    }
  ],
  "schema": "openwiz.decisions.v1",
  "kind": "plan_approval",
  "graph": [
    {
      "blocker": 41,
      "ticket": 42
    }
  ],
  "status": "open",
  "fingerprint": "cb9a4edec370cb0fbc1517e91f90db71a9d570adf23e7971d0f929cd1b3af37b"
}
```
