from __future__ import annotations

import argparse
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli_parser import build_parser  # noqa: E402
from loom.guidance import DEFAULT_RENEW_LEASE_MINUTES  # noqa: E402
from loom.util import DEFAULT_LEASE_POLICY  # noqa: E402


def _handler(_: argparse.Namespace) -> int:
    return 0


def _handlers() -> dict[str, object]:
    return {
        "init": _handler,
        "start": _handler,
        "whoami": _handler,
        "claim": _handler,
        "unclaim": _handler,
        "intent": _handler,
        "finish": _handler,
        "clean": _handler,
        "renew": _handler,
        "status": _handler,
        "report": _handler,
        "resume": _handler,
        "agents": _handler,
        "agent": _handler,
        "inbox": _handler,
        "conflicts": _handler,
        "resolve": _handler,
        "log": _handler,
        "timeline": _handler,
        "context_write": _handler,
        "context_ack": _handler,
        "context_read": _handler,
        "protocol": _handler,
        "mcp": _handler,
        "daemon_start": _handler,
        "daemon_stop": _handler,
        "daemon_status": _handler,
        "daemon_run": _handler,
        "daemon_ping": _handler,
    }


class CliParserTest(unittest.TestCase):
    def test_parser_help_keeps_quick_start_epilog(self) -> None:
        parser = build_parser(handlers=_handlers())

        help_text = parser.format_help()

        self.assertIn("Start here:", help_text)
        self.assertIn("loom init --no-daemon", help_text)
        self.assertIn("Core loop:", help_text)
        self.assertIn("claim    say what you're working on", help_text)

    def test_claim_parser_supports_scope_and_lease_flags(self) -> None:
        parser = build_parser(handlers=_handlers())

        args = parser.parse_args(
            [
                "claim",
                "Refactor auth",
                "--scope",
                "src/auth",
                "--scope",
                "src/api",
                "--lease-minutes",
                "45",
                "--lease-policy",
                "yield",
                "--agent",
                "agent-a",
            ]
        )

        self.assertEqual(args.command, "claim")
        self.assertEqual(args.description, "Refactor auth")
        self.assertEqual(args.scope, ["src/auth", "src/api"])
        self.assertEqual(args.lease_minutes, 45)
        self.assertEqual(args.lease_policy, "yield")
        self.assertEqual(args.agent, "agent-a")
        self.assertIs(args.handler, _handler)

    def test_intent_parser_accepts_reason_and_optional_lease_policy(self) -> None:
        parser = build_parser(handlers=_handlers())

        args = parser.parse_args(
            [
                "intent",
                "Update API contract",
                "--reason",
                "Migration in progress",
                "--scope",
                "src/api",
                "--lease-policy",
                DEFAULT_LEASE_POLICY,
            ]
        )

        self.assertEqual(args.command, "intent")
        self.assertEqual(args.reason, "Migration in progress")
        self.assertEqual(args.scope, ["src/api"])
        self.assertEqual(args.lease_policy, DEFAULT_LEASE_POLICY)

    def test_renew_parser_uses_default_lease_window(self) -> None:
        parser = build_parser(handlers=_handlers())

        args = parser.parse_args(["renew"])

        self.assertEqual(args.command, "renew")
        self.assertEqual(args.lease_minutes, DEFAULT_RENEW_LEASE_MINUTES)
        self.assertIs(args.handler, _handler)

    def test_context_and_daemon_subcommands_are_required(self) -> None:
        parser = build_parser(handlers=_handlers())

        with self.assertRaises(SystemExit):
            parser.parse_args(["context"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["daemon"])

    def test_context_read_and_report_parse_public_alpha_flags(self) -> None:
        parser = build_parser(handlers=_handlers())

        context_args = parser.parse_args(
            [
                "context",
                "read",
                "--topic",
                "migration",
                "--scope",
                "src/api",
                "--follow",
                "--limit",
                "7",
            ]
        )
        report_args = parser.parse_args(
            [
                "report",
                "--output",
                "reports/latest.html",
                "--agent-limit",
                "9",
                "--event-limit",
                "11",
            ]
        )

        self.assertEqual(context_args.command, "context")
        self.assertEqual(context_args.context_command, "read")
        self.assertEqual(context_args.topic, "migration")
        self.assertEqual(context_args.scope, ["src/api"])
        self.assertTrue(context_args.follow)
        self.assertEqual(context_args.limit, 7)

        self.assertEqual(report_args.command, "report")
        self.assertEqual(report_args.output, pathlib.Path("reports/latest.html"))
        self.assertEqual(report_args.agent_limit, 9)
        self.assertEqual(report_args.event_limit, 11)

    def test_agents_and_clean_parse_cleanup_flags(self) -> None:
        parser = build_parser(handlers=_handlers())

        start_args = parser.parse_args(["start", "--bind", "agent-a"])
        agents_args = parser.parse_args(["agents", "--all", "--limit", "7"])
        finish_args = parser.parse_args(["finish", "--keep-idle"])
        clean_args = parser.parse_args(["clean", "--keep-idle"])

        self.assertEqual(start_args.command, "start")
        self.assertEqual(start_args.bind, "agent-a")
        self.assertEqual(agents_args.command, "agents")
        self.assertTrue(agents_args.all)
        self.assertEqual(agents_args.limit, 7)
        self.assertEqual(finish_args.command, "finish")
        self.assertTrue(finish_args.keep_idle)
        self.assertEqual(clean_args.command, "clean")
        self.assertTrue(clean_args.keep_idle)


if __name__ == "__main__":
    unittest.main()
