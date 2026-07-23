"""Tests for the Claude Code tool classifier."""

from bridge.claude.tool_classifier import classify, classify_command
from bridge.models import ApprovalCategory


class TestNonBashTools:
    def test_read_tool(self):
        category, action, details = classify("Read", {"file_path": "/tmp/x.py"})
        assert category == ApprovalCategory.FILE_READ
        assert action == "Read /tmp/x.py"
        assert details["path"] == "/tmp/x.py"
        assert details["tool_name"] == "Read"

    def test_write_tools(self):
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            category, _, _ = classify(tool, {"file_path": "a.py"})
            assert category == ApprovalCategory.FILE_WRITE

    def test_search_tools(self):
        assert classify("Glob", {"pattern": "**/*.py"})[0] == ApprovalCategory.SEARCH
        assert classify("Grep", {"pattern": "TODO"})[0] == ApprovalCategory.SEARCH
        assert classify("WebSearch", {"query": "kaptn"})[0] == ApprovalCategory.SEARCH
        assert classify("WebFetch", {"url": "https://x.com"})[0] == ApprovalCategory.SEARCH

    def test_mcp_tool(self):
        category, action, _ = classify("mcp__konvyr__konvyr_status", {})
        assert category == ApprovalCategory.TOOL_CALL
        assert action == "mcp__konvyr__konvyr_status"

    def test_agent_tools(self):
        assert classify("Task", {"description": "explore"})[0] == ApprovalCategory.TOOL_CALL
        assert classify("TodoWrite", {})[0] == ApprovalCategory.TOOL_CALL

    def test_unknown_tool(self):
        assert classify("SomeNewTool", {})[0] == ApprovalCategory.UNKNOWN

    def test_none_tool_input(self):
        category, action, details = classify("Read", None)
        assert category == ApprovalCategory.FILE_READ
        assert action == "Read"
        assert "path" not in details

    def test_context_set_for_loop_detection(self):
        _, action, details = classify("Grep", {"pattern": "foo"})
        assert details["context"] == action


class TestBashClassification:
    def test_safe_commands(self):
        for cmd in ("ls -la", "cat foo.txt", "pwd", "echo hi", "grep -r x ."):
            assert classify_command(cmd) == ApprovalCategory.COMMAND_SAFE, cmd

    def test_unsafe_commands(self):
        for cmd in ("npm install", "pip install requests", "python script.py", "curl https://x"):
            assert classify_command(cmd) == ApprovalCategory.COMMAND_UNSAFE, cmd

    def test_delete_commands(self):
        for cmd in ("rm -rf build", "rmdir old", "unlink f", "shred secret.txt"):
            assert classify_command(cmd) == ApprovalCategory.FILE_DELETE, cmd

    def test_delete_wins_in_compound(self):
        assert classify_command("ls && rm -rf build") == ApprovalCategory.FILE_DELETE
        assert classify_command("cat x | rm y") == ApprovalCategory.FILE_DELETE

    def test_compound_all_safe(self):
        assert classify_command("ls && pwd; echo done") == ApprovalCategory.COMMAND_SAFE

    def test_compound_mixed_is_unsafe(self):
        assert classify_command("ls && npm install") == ApprovalCategory.COMMAND_UNSAFE

    def test_empty_command_unsafe(self):
        assert classify_command("") == ApprovalCategory.COMMAND_UNSAFE
        assert classify_command("   ") == ApprovalCategory.COMMAND_UNSAFE

    def test_bash_tool_end_to_end(self):
        category, action, details = classify("Bash", {"command": "ls -la"})
        assert category == ApprovalCategory.COMMAND_SAFE
        assert action == "ls -la"
        assert details["command"] == "ls -la"

    def test_long_command_truncated_action(self):
        long_cmd = "echo " + "x" * 500
        _, action, details = classify("Bash", {"command": long_cmd})
        assert len(action) == 200
        assert details["command"] == long_cmd


class TestGitClassification:
    def test_safe_git_subcommands(self):
        for cmd in ("git status", "git log --oneline", "git diff HEAD", "git -C repos/x status"):
            assert classify_command(cmd) == ApprovalCategory.COMMAND_SAFE, cmd

    def test_unsafe_git_subcommands(self):
        for cmd in ("git push origin main", "git commit -m x", "git checkout -- f", "git reset --hard"):
            assert classify_command(cmd) == ApprovalCategory.COMMAND_UNSAFE, cmd

    def test_git_delete_subcommands(self):
        assert classify_command("git clean -fd") == ApprovalCategory.FILE_DELETE
        assert classify_command("git rm file.py") == ApprovalCategory.FILE_DELETE

    def test_git_no_subcommand(self):
        assert classify_command("git") == ApprovalCategory.COMMAND_UNSAFE


class TestSegmentEdgeCases:
    def test_sudo_is_never_safe(self):
        assert classify_command("sudo ls") == ApprovalCategory.COMMAND_UNSAFE
        assert classify_command("sudo rm -rf /x") == ApprovalCategory.FILE_DELETE
        assert classify_command("sudo") == ApprovalCategory.COMMAND_UNSAFE
        assert classify_command("sudo git status") == ApprovalCategory.COMMAND_UNSAFE
        assert classify_command("sudo find /") == ApprovalCategory.COMMAND_UNSAFE

    def test_env_prefix_stripped(self):
        assert classify_command("FOO=bar ls") == ApprovalCategory.COMMAND_SAFE
        assert classify_command("FOO=bar npm install") == ApprovalCategory.COMMAND_UNSAFE

    def test_bare_env_assignment_safe(self):
        assert classify_command("FOO=bar") == ApprovalCategory.COMMAND_SAFE

    def test_absolute_path_command(self):
        assert classify_command("/bin/rm -rf x") == ApprovalCategory.FILE_DELETE
        assert classify_command("/bin/ls") == ApprovalCategory.COMMAND_SAFE

    def test_unbalanced_quotes_fall_back(self):
        # shlex.split raises on unbalanced quotes — falls back to str.split
        assert classify_command("echo 'unbalanced") == ApprovalCategory.COMMAND_SAFE

    def test_kaptn_read_only_subcommands_safe(self):
        for cmd in ("kaptn status", "kaptn help", "kaptn log -n 50",
                    "kaptn status -c /x/kaptn.config.json", "kaptn claude status", "kaptn"):
            assert classify_command(cmd) == ApprovalCategory.COMMAND_SAFE, cmd

    def test_kaptn_state_changing_subcommands_unsafe(self):
        for cmd in ("kaptn reset", "kaptn stop", "kaptn start",
                    "kaptn claude install", "kaptn claude serve", "sudo kaptn status"):
            assert classify_command(cmd) == ApprovalCategory.COMMAND_UNSAFE, cmd

    def test_find_variants(self):
        assert classify_command("find . -name '*.py'") == ApprovalCategory.COMMAND_SAFE
        assert classify_command("find . -delete") == ApprovalCategory.FILE_DELETE
        assert classify_command("find . -exec rm {} ;") == ApprovalCategory.FILE_DELETE
        assert classify_command("find . -exec chmod 644 {} ;") == ApprovalCategory.COMMAND_UNSAFE
        assert classify_command("find . -execdir rm {} ;") == ApprovalCategory.FILE_DELETE
