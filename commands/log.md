---
description: Show recent Kaptn approval decisions (audit trail)
---

Run this command with Bash and show the user the output. If the user
passed an argument, use it as the record count: $ARGUMENTS

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/kaptn-ctl" log -n 20
```

If `CLAUDE_PLUGIN_ROOT` is not set in the Bash environment, locate the
kaptn plugin directory under `~/.claude/plugins/` and run
`<plugin-dir>/scripts/kaptn-ctl log` instead.
