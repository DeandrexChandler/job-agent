---
description: Run the job-agent loop once (scan, gate, tailor, fill, track)
argument-hint: "[dry-run] [backlog]"
---

Run the `job-run` skill from this plugin. If the arguments include `dry-run`, treat `dry_run` as true for this run regardless of preferences. If they include `backlog`, first load the Simplify backlog (`job-scan` skill, "Backlog"), then run as usual.

Arguments: $ARGUMENTS
