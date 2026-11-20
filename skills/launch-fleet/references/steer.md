# Steering from the spec's video

Read this for a `hold`, `re-cut` or `steer` line (#1340).

to-spec posts the spec's video as a comment that is exactly its link line (`[Watch the narrated spec](<https URL>)`), a blank line and `Comment here to steer: stop, reset, or anything else.`; nothing else counts as a video. Steering is on only when the latest video was posted by an App login (`...[bot]`), that is when agents post as the App. While agents post from the same login as the owner (until the OpenWiz App identity, OpenWiz #1402, is in use), no comment can prove it is the owner's, so no comment on the video steers: the check prints one `look #S: comments on the video steer nothing while agents post from the same login as the owner, ...` until its `launch-fleet: look:` record, and the owner steers through the orchestrator meanwhile. With steering on, each later plain comment from the owner (a record author that is not an App login) steers, by its first word: `stop` holds the fleet, `reset` holds it and asks for a re-cut and a new video, and anything else is a steer to read. A bold record line (`**...`), a quote, a `VERDICT` or an `Orchestrator` line is no steer. A held spec starts, takes over and releases nothing until a newer video; its running builders keep going until the orchestrator decides. A steer grants nothing: every action gate (publish, spend, secrets, deleting user data, cut-overs) keeps its own approval.

| Line | Do |
| --- | --- |
| `hold #S: ...` | Record `launch-fleet: held by stop <comment id>` on the spec and tell the orchestrator, who decides what its running builders do |
| `re-cut #S: ...` | Record `launch-fleet: re-cut asked <comment id>` and have the orchestrator re-cut the plan and make a new video (to-spec, step 5) |
| `steer #S: ...` | Read the comment, act on it within the fleet's roles (anything else goes to the orchestrator), and record `launch-fleet: steer read <comment id>` |
