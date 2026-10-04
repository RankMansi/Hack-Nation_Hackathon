---
name: GitHub upload access
description: Safe repository uploads when connector access works but Git CLI authentication fails
---

A working GitHub connector does not necessarily repair the Git CLI's saved
authentication. Use the authenticated connector's Git Data API when CLI access
remains unavailable; do not extract or store credentials.

**Why:** GitHub connector requests succeeded while Git CLI access still rejected
its saved authentication. The remote also contained work absent from this checkout.

**How to apply:** Compare remote and local history before uploading. When histories
diverge, preserve the default branch and upload the requested workspace snapshot
on a separate branch rather than force-pushing. Verify blob/tree hashes and the
resulting branch reference; explain when the remote commit is a combined snapshot
rather than the exact local commit.