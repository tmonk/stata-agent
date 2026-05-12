"""Unit tests for the linter module."""

from __future__ import annotations

from stata_agent.linter import lint_text, lint_file


class TestLintText:
    def test_no_issues(self):
        issues = lint_text("display 1+1\nreg price mpg\n")
        assert len(issues) >= 1
        assert any(i.severity == "info" and "No issues" in i.message for i in issues)

    def test_unclosed_brace(self):
        issues = lint_text("if x > 0 {\ndisplay 1+1\n")
        errors = [i for i in issues if i.severity == "error" and "Unclosed brace" in i.message]
        assert len(errors) >= 1

    def test_too_many_closing_braces(self):
        issues = lint_text("}\n")
        errors = [i for i in issues if i.severity == "error" and "Too many closing braces" in i.message]
        assert len(errors) >= 1

    def test_mata_block_not_closed(self):
        issues = lint_text("mata:\nx = 1+1\n")
        errors = [i for i in issues if i.severity == "error" and "Mata block not closed" in i.message]
        assert len(errors) >= 1

    def test_mata_block_closed(self):
        issues = lint_text("mata:\nx = 1+1\nend\n")
        assert not any("Mata block not closed" in i.message for i in issues)

    def test_shell_command_warning(self):
        issues = lint_text("!rm -rf /tmp/data\n")
        warnings = [i for i in issues if i.severity == "warning" and "Shell command" in i.message]
        assert len(warnings) >= 1

    def test_set_memory_deprecated(self):
        issues = lint_text("set memory 100m\n")
        infos = [i for i in issues if i.severity == "info" and "set memory" in i.message]
        assert len(infos) >= 1

    def test_empty_file(self):
        issues = lint_text("")
        assert any(i.severity == "info" for i in issues)


class TestLintFile:
    def test_file_not_found(self, tmp_path):
        issues = lint_file(tmp_path / "nonexistent.do")
        errors = [i for i in issues if i.severity == "error" and "not found" in i.message]
        assert len(errors) >= 1

    def test_file_with_content(self, tmp_path):
        f = tmp_path / "test.do"
        f.write_text("display 1+1\n")
        issues = lint_file(f)
        assert len(issues) >= 1
