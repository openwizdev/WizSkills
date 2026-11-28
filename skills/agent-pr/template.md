```agent-pr
{
  "schema": "agent-pr/1",
  "closes": "14",
  "intent": "Reload the widget list after a successful save.",
  "changes": [
    {
      "acceptance": "A1",
      "change": "The list reloads after a successful save."
    }
  ],
  "proof": [
    {
      "acceptance": "A1",
      "command": "python3 -m unittest tests/test_widgets.py",
      "result": "pass",
      "red_first": true
    }
  ],
  "risk": "low: list rendering only",
  "rollback": "Revert the merge commit.",
  "owned_paths": [
    "src/widgets/list.py",
    "tests/test_widgets.py"
  ],
  "gates": []
}
```
