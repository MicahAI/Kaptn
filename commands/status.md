---
description: Show Kaptn rules, live per-session usage, and audit summary
---

Run this command with Bash and show the user its output, briefly
highlighting anything notable (sessions near their cap, paused windows):

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/kaptn-ctl" status
```

If `CLAUDE_PLUGIN_ROOT` is not set in the Bash environment, locate the
kaptn plugin directory under `~/.claude/plugins/` and run
`<plugin-dir>/scripts/kaptn-ctl status` instead.
