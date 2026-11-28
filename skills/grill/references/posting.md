# Post one grill question

The host posts. Nothing in this skill calls Slack. The channel and the mentions live in [channel.json](../../role-call/channel.json). Read them from there.

1. Write the one saved question to a private file. It has one `➡️` line.
2. Run `python3 -I "<installed-role-call>/scripts/channel.py" question --id <ID> --body-file <file>`.
   Fleet mode adds `--answers counterpart`.
3. Post the printed `text` as one message in `channel`. One message is one question. Do not combine questions, and do not add a mention the text does not already contain.
4. When `answers_from` is `thread`, the answer is a reply to that message. Save that reply as the exact reply. When `answers_from` is `counterpart`, the orchestrator or spec decides, and a thread reply settles nothing.
5. The alignment summary is its own message. Run the same script with `summary --body-file <file>`. Its thread reply is the acceptance. Fleet mode posts no summary, because it does not confirm.
