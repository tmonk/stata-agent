"""Unit tests for the CLI parser and command handlers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from stata_agent.cli import build_parser, main


class TestParser:
    def test_parser_builds(self):
        parser = build_parser()
        assert parser is not None

    def test_parse_daemon_start(self):
        parser = build_parser()
        args = parser.parse_args(["daemon", "start"])
        assert args.command == "daemon"
        assert args.daemon_cmd == "start"
        assert args.session == "default"

    def test_parse_daemon_start_mock(self):
        parser = build_parser()
        args = parser.parse_args(["daemon", "start", "--mock"])
        assert args.command == "daemon"
        assert args.daemon_cmd == "start"
        assert args.mock is True

    def test_parse_daemon_stop(self):
        parser = build_parser()
        args = parser.parse_args(["daemon", "stop", "--session", "test"])
        assert args.command == "daemon"
        assert args.daemon_cmd == "stop"
        assert args.session == "test"

    def test_parse_run(self):
        parser = build_parser()
        args = parser.parse_args(["run", "display 1+1"])
        assert args.command == "run"
        assert args.code == "display 1+1"
        assert args.echo is True
        assert args.background is False

    def test_parse_run_file(self):
        parser = build_parser()
        args = parser.parse_args(["run", "--file", "/tmp/test.do"])
        assert args.command == "run"
        assert args.file == "/tmp/test.do"

    def test_parse_break(self):
        parser = build_parser()
        args = parser.parse_args(["break", "--session", "test"])
        assert args.command == "break"
        assert args.session == "test"

    def test_parse_inspect_describe(self):
        parser = build_parser()
        args = parser.parse_args(["inspect", "describe", "price", "mpg"])
        assert args.command == "inspect"
        assert args.inspect_cmd == "describe"
        assert args.varlist == ["price", "mpg"]

    def test_parse_inspect_summary(self):
        parser = build_parser()
        args = parser.parse_args(["inspect", "summary"])
        assert args.command == "inspect"
        assert args.inspect_cmd == "summary"

    def test_parse_graph_list(self):
        parser = build_parser()
        args = parser.parse_args(["graph", "list"])
        assert args.command == "graph"
        assert args.graph_cmd == "list"

    def test_parse_graph_export(self):
        parser = build_parser()
        args = parser.parse_args(["graph", "export", "--name", "fig1", "--format", "svg"])
        assert args.command == "graph"
        assert args.graph_cmd == "export"
        assert args.name == "fig1"
        assert args.format == "svg"

    def test_parse_results(self):
        parser = build_parser()
        args = parser.parse_args(["results", "--return", "e"])
        assert args.command == "results"
        assert args.return_class == "e"

    def test_parse_help(self):
        parser = build_parser()
        args = parser.parse_args(["help", "regress", "--format", "syntax"])
        assert args.command == "help"
        assert args.topic == "regress"
        assert args.format == "syntax"

    def test_parse_log_tail(self):
        parser = build_parser()
        args = parser.parse_args(["log", "tail", "--lines", "100"])
        assert args.command == "log"
        assert args.log_cmd == "tail"
        assert args.lines == 100

    def test_parse_log_search(self):
        parser = build_parser()
        args = parser.parse_args(["log", "search", "error"])
        assert args.command == "log"
        assert args.log_cmd == "search"
        assert args.pattern == "error"

    def test_parse_log_errors(self):
        parser = build_parser()
        args = parser.parse_args(["log", "errors"])
        assert args.command == "log"
        assert args.log_cmd == "errors"

    def test_parse_log_path(self):
        parser = build_parser()
        args = parser.parse_args(["log", "path"])
        assert args.command == "log"
        assert args.log_cmd == "path"

    def test_parse_lint(self):
        parser = build_parser()
        args = parser.parse_args(["lint", "/tmp/test.do"])
        assert args.command == "lint"
        assert args.path == "/tmp/test.do"

    def test_parse_doctor(self):
        parser = build_parser()
        args = parser.parse_args(["doctor"])
        assert args.command == "doctor"

    def test_parse_discover(self):
        parser = build_parser()
        args = parser.parse_args(["discover"])
        assert args.command == "discover"

    def test_parse_task_status(self):
        parser = build_parser()
        args = parser.parse_args(["task", "status", "--task-id", "abc123"])
        assert args.command == "task"
        assert args.task_cmd == "status"
        assert args.task_id == "abc123"

    def test_parse_task_cancel(self):
        parser = build_parser()
        args = parser.parse_args(["task", "cancel", "--task-id", "abc123"])
        assert args.command == "task"
        assert args.task_cmd == "cancel"
        assert args.task_id == "abc123"

    def test_parse_task_list(self):
        parser = build_parser()
        args = parser.parse_args(["task", "list"])
        assert args.command == "task"
        assert args.task_cmd == "list"

    def test_no_args_shows_help(self):
        result = main([])
        assert result == 1


class TestMainReturns:
    def test_unknown_command_returns_exit_code(self):
        result = main(["unknown_command"])
        assert result == 2

    @patch("stata_agent.cli._start_daemon")
    def test_daemon_start(self, mock_start):
        mock_start.return_value = 0
        result = main(["daemon", "start"])
        assert result == 0

    @patch("stata_agent.cli.RpcClient")
    def test_daemon_stop(self, mock_client):
        instance = mock_client.return_value
        instance.is_alive.return_value = False
        result = main(["daemon", "stop"])
        assert result == 0
