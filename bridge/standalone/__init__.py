"""Daemonless (plugin) mode — per-invocation evaluation with SQLite state.

The daemon keeps limits and loop history in process memory. Plugin mode
runs a fresh process per hook event, so that state lives in SQLite under
~/.kaptn/ instead. Everything above the state layer (classifier, rules,
adapter, audit) is shared with the daemon.
"""
