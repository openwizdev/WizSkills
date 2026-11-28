```agent-issue
{
  "schema": "agent-issue/1",
  "id": "14",
  "kind": "bug",
  "goal": "The widget list stays empty after a successful save.",
  "summary": "Show saved widgets.",
  "acceptance": [
    {
      "id": "A1",
      "check": "python3 -m unittest tests/test_widgets.py"
    }
  ],
  "owned_paths": [
    "src/widgets/",
    "tests/test_widgets.py"
  ],
  "out_of_scope": [
    "Changing the save API."
  ],
  "depends": [],
  "blocks": [],
  "risk": "low: list rendering only",
  "gates": [],
  "effort": "small",
  "ready": "ready-for-agent",
  "context": [
    "https://example.com/widgets"
  ]
}
```
