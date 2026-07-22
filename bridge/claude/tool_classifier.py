"""Classify Claude Code tool calls into Kaptn approval categories.

Unlike the Windsurf driver, which infers categories from scraped DOM text,
Claude Code hooks deliver the exact tool name and input — classification
here is deterministic.
"""

import logging
import re
import shlex

from bridge.models import ApprovalCategory

logger = logging.getLogger(__name__)

READ_TOOLS = {"Read", "NotebookRead"}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
SEARCH_TOOLS = {"Glob", "Grep", "WebSearch", "WebFetch"}
AGENT_TOOLS = {
    "Task", "Agent", "Skill", "TodoWrite", "TaskCreate", "TaskUpdate",
    "ExitPlanMode", "AskUserQuestion",
}

SAFE_COMMANDS = {
    "ls", "cat", "head", "tail", "wc", "pwd", "echo", "printf", "which",
    "whoami", "date", "env", "printenv", "uname", "stat", "file", "du",
    "df", "ps", "grep", "rg", "egrep", "fgrep", "tree", "basename",
    "dirname", "readlink", "shasum", "md5", "sort", "uniq", "cut",
    "diff", "true",
}

SAFE_GIT_SUBCOMMANDS = {
    "status", "log", "diff", "show", "branch", "remote", "rev-parse",
    "describe", "blame", "shortlog", "ls-files", "ls-remote", "grep",
}

GIT_DELETE_SUBCOMMANDS = {"clean", "rm"}

DELETE_COMMANDS = {"rm", "rmdir", "unlink", "shred"}

# git global flags that consume the following token (e.g. `git -C path status`)
_GIT_FLAGS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree"}

_SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
_ENV_ASSIGNMENT = re.compile(r"^\w+=")

# tool_input keys that identify a file path (used for rule path_patterns)
_PATH_KEYS = ("file_path", "path", "notebook_path")
# additional keys that describe what the tool is acting on
_CONTEXT_KEYS = _PATH_KEYS + ("pattern", "query", "url", "description")


def classify(tool_name: str, tool_input: dict | None) -> tuple[ApprovalCategory, str, dict]:
    """Classify a Claude Code tool call.

    Args:
        tool_name: The tool being invoked (e.g. 'Bash', 'Write', 'mcp__x__y').
        tool_input: The tool's input parameters from the hook event.

    Returns:
        Tuple of (category, action_text, details) where action_text is a
        short human-readable description and details feeds rule conditions
        (path/command matching) and loop detection (context key).
    """
    tool_input = tool_input or {}

    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        category = classify_command(command)
        action = command.strip()[:200] or tool_name
        return category, action, {
            "tool_name": tool_name,
            "command": command,
            "context": action,
        }

    category = _classify_non_bash(tool_name)

    target = ""
    for key in _CONTEXT_KEYS:
        if tool_input.get(key):
            target = str(tool_input[key])
            break

    action = f"{tool_name} {target}".strip()[:200]
    details = {"tool_name": tool_name, "context": action}
    for key in _PATH_KEYS:
        if tool_input.get(key):
            details["path"] = str(tool_input[key])
            break

    return category, action, details


def _classify_non_bash(tool_name: str) -> ApprovalCategory:
    """Map a non-Bash tool name to its approval category."""
    if tool_name in READ_TOOLS:
        return ApprovalCategory.FILE_READ
    if tool_name in WRITE_TOOLS:
        return ApprovalCategory.FILE_WRITE
    if tool_name in SEARCH_TOOLS:
        return ApprovalCategory.SEARCH
    if tool_name.startswith("mcp__") or tool_name in AGENT_TOOLS:
        return ApprovalCategory.TOOL_CALL
    logger.debug("Unrecognized Claude tool '%s' — classifying as unknown", tool_name)
    return ApprovalCategory.UNKNOWN


def classify_command(command: str) -> ApprovalCategory:
    """Classify a shell command string.

    Compound commands (&&, ||, ;, |) are split into segments; the overall
    category is the most dangerous segment: any delete wins, then unsafe,
    and only an all-safe command is safe.

    Args:
        command: The full shell command from the Bash tool input.

    Returns:
        FILE_DELETE, COMMAND_SAFE, or COMMAND_UNSAFE.
    """
    segments = [s.strip() for s in _SEGMENT_SPLIT.split(command) if s.strip()]
    if not segments:
        return ApprovalCategory.COMMAND_UNSAFE

    results = [_classify_segment(s) for s in segments]
    if ApprovalCategory.FILE_DELETE in results:
        return ApprovalCategory.FILE_DELETE
    if all(r == ApprovalCategory.COMMAND_SAFE for r in results):
        return ApprovalCategory.COMMAND_SAFE
    return ApprovalCategory.COMMAND_UNSAFE


def _classify_segment(segment: str) -> ApprovalCategory:
    """Classify a single pipeline segment of a shell command."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()

    while tokens and _ENV_ASSIGNMENT.match(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return ApprovalCategory.COMMAND_SAFE  # bare env assignment

    sudo = False
    if tokens[0] == "sudo":
        sudo = True
        tokens = tokens[1:]
        if not tokens:
            return ApprovalCategory.COMMAND_UNSAFE

    cmd = tokens[0].rsplit("/", 1)[-1]

    if cmd in DELETE_COMMANDS:
        return ApprovalCategory.FILE_DELETE
    if cmd == "git":
        return _classify_git(tokens[1:], sudo)
    if cmd == "find":
        return _classify_find(tokens[1:], sudo)
    if sudo:
        return ApprovalCategory.COMMAND_UNSAFE
    if cmd in SAFE_COMMANDS:
        return ApprovalCategory.COMMAND_SAFE
    return ApprovalCategory.COMMAND_UNSAFE


def _classify_git(args: list[str], sudo: bool) -> ApprovalCategory:
    """Classify a git invocation by its subcommand."""
    subcommand = ""
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token in _GIT_FLAGS_WITH_ARG:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        subcommand = token
        break

    if subcommand in GIT_DELETE_SUBCOMMANDS:
        return ApprovalCategory.FILE_DELETE
    if sudo:
        return ApprovalCategory.COMMAND_UNSAFE
    if subcommand in SAFE_GIT_SUBCOMMANDS:
        return ApprovalCategory.COMMAND_SAFE
    return ApprovalCategory.COMMAND_UNSAFE


def _classify_find(args: list[str], sudo: bool) -> ApprovalCategory:
    """Classify a find invocation — read-only unless it deletes or execs."""
    if "-delete" in args:
        return ApprovalCategory.FILE_DELETE
    if "-exec" in args or "-execdir" in args:
        for flag in ("-exec", "-execdir"):
            if flag in args:
                idx = args.index(flag)
                if idx + 1 < len(args) and args[idx + 1].rsplit("/", 1)[-1] in DELETE_COMMANDS:
                    return ApprovalCategory.FILE_DELETE
        return ApprovalCategory.COMMAND_UNSAFE
    if sudo:
        return ApprovalCategory.COMMAND_UNSAFE
    return ApprovalCategory.COMMAND_SAFE
