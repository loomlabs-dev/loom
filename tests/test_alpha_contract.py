from __future__ import annotations

import argparse
import pathlib
import sys
import tempfile
import tomllib
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom import __version__  # noqa: E402
from loom.cli import build_parser  # noqa: E402
from loom.mcp import MCP_PROTOCOL_VERSION, LoomMcpServer  # noqa: E402
from loom.protocol import describe_local_protocol  # noqa: E402


def _parser_commands(
    parser: argparse.ArgumentParser,
    prefix: tuple[str, ...] = (),
) -> set[str]:
    commands: set[str] = set()
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for name, subparser in action.choices.items():
            command = prefix + (name,)
            commands.add(" ".join(command))
            commands.update(_parser_commands(subparser, command))
    return commands


class AlphaContractTest(unittest.TestCase):
    def test_package_name_and_version_match_alpha_contract(self) -> None:
        pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
        contract = (PROJECT_ROOT / "docs/alpha/ALPHA_0_1_CONTRACT.md").read_text()
        changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text()

        self.assertEqual(pyproject["project"]["name"], "loom-coord")
        self.assertEqual(pyproject["project"]["version"], __version__)
        self.assertEqual(__version__, "0.1.0a0")

        self.assertIn("Python distribution: `loom-coord`", contract)
        self.assertIn("current alpha version: `0.1.0a0`", contract)
        self.assertIn("## 0.1.0a0 - 2026-03-15", changelog)

    def test_cli_commands_cover_the_supported_alpha_surface(self) -> None:
        commands = _parser_commands(build_parser())
        self.assertTrue(
            {
                "start",
                "init",
                "whoami",
                "claim",
                "unclaim",
                "intent",
                "renew",
                "finish",
                "clean",
                "status",
                "report",
                "resume",
                "agents",
                "agent",
                "inbox",
                "conflicts",
                "resolve",
                "log",
                "timeline",
                "protocol",
                "mcp",
                "context write",
                "context read",
                "context ack",
            }.issubset(commands)
        )

    def test_mcp_alpha_surface_is_discoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            initialize = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            self.assertIsNotNone(initialize)

            tools_list = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                }
            )
            self.assertIsNotNone(tools_list)
            assert tools_list is not None
            tools = {
                tool["name"] for tool in tools_list["result"]["tools"]
            }
            self.assertTrue(
                {
                    "loom_init",
                    "loom_bind",
                    "loom_whoami",
                    "loom_start",
                    "loom_protocol",
                    "loom_claim",
                    "loom_unclaim",
                    "loom_finish",
                    "loom_clean",
                    "loom_renew",
                    "loom_intent",
                    "loom_context_write",
                    "loom_context_read",
                    "loom_context_ack",
                    "loom_status",
                    "loom_agents",
                    "loom_agent",
                    "loom_inbox",
                    "loom_conflicts",
                    "loom_resolve",
                    "loom_log",
                    "loom_timeline",
                }.issubset(tools)
            )

            prompts_list = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "prompts/list",
                }
            )
            self.assertIsNotNone(prompts_list)
            assert prompts_list is not None
            prompts = {
                prompt["name"] for prompt in prompts_list["result"]["prompts"]
            }
            self.assertEqual(
                prompts,
                {
                    "coordinate_before_edit",
                    "triage_inbox",
                    "resolve_conflict",
                    "adapt_or_wait",
                    "finish_and_release",
                    "handoff_work",
                },
            )

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {"name": "loom_init", "arguments": {}},
                }
            )
            self.assertIsNotNone(init_result)

            resources_list = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "resources/list",
                }
            )
            self.assertIsNotNone(resources_list)
            assert resources_list is not None
            resources = {
                resource["uri"] for resource in resources_list["result"]["resources"]
            }
            self.assertTrue(
                {
                    "loom://start",
                    "loom://protocol",
                    "loom://identity",
                    "loom://mcp",
                    "loom://status",
                    "loom://log",
                    "loom://context",
                    "loom://agents",
                    "loom://conflicts",
                    "loom://conflicts/history",
                    "loom://agent",
                    "loom://inbox",
                    "loom://activity",
                }.issubset(resources)
            )

            templates_list = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "resources/templates/list",
                }
            )
            self.assertIsNotNone(templates_list)
            assert templates_list is not None
            templates = {
                template["uriTemplate"]
                for template in templates_list["result"]["resourceTemplates"]
            }
            self.assertTrue(
                {
                    "loom://claim/{claim_id}",
                    "loom://claim/{claim_id}/timeline",
                    "loom://intent/{intent_id}",
                    "loom://intent/{intent_id}/timeline",
                    "loom://context/{context_id}",
                    "loom://context/{context_id}/timeline",
                    "loom://conflict/{conflict_id}",
                    "loom://conflict/{conflict_id}/timeline",
                    "loom://agent/{agent_id}",
                    "loom://inbox/{agent_id}",
                    "loom://activity/{agent_id}",
                    "loom://activity/{agent_id}/after/{sequence}",
                    "loom://timeline/{object_id}",
                    "loom://event/{sequence}",
                    "loom://events/after/{sequence}",
                }.issubset(templates)
            )

    def test_local_protocol_alpha_contract_stays_visible(self) -> None:
        protocol = describe_local_protocol()

        self.assertEqual(protocol["name"], "loom.local")
        self.assertEqual(protocol["version"], 1)
        self.assertEqual(protocol["transport"], "unix-domain-socket")
        self.assertEqual(protocol["framing"], "newline-delimited")
        self.assertIn("operation_schemas", protocol)
        self.assertTrue(
            {
                "ping",
                "protocol.describe",
                "claim.create",
                "claim.release",
                "claim.renew",
                "intent.declare",
                "intent.release",
                "intent.renew",
                "context.publish",
                "context.read",
                "context.get",
                "context.ack",
                "status.read",
                "agents.read",
                "agent.read",
                "inbox.read",
                "conflicts.read",
                "conflict.resolve",
                "events.read",
                "events.follow",
            }.issubset(set(protocol["operations"]))
        )


if __name__ == "__main__":
    unittest.main()
