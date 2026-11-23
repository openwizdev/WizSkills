---
"launch-fleet": patch
---

`fleet.sh` prints `decision #<P> for #<N> at <commit>` when a record author's `**Orchestrator decision:**` is the newest record on a pull request whose findings are parked for Jake, so the fleet acts on it at once instead of at its next heartbeat; the fleet's own record after it quiets the line.
