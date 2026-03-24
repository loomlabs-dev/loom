from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.client import CoordinationClient  # noqa: E402
from loom.cli import main  # noqa: E402
from loom.daemon import DaemonStatus  # noqa: E402
from loom.local_store import EventRecord  # noqa: E402
from loom.mcp import (  # noqa: E402
    BACKGROUND_WATCH_DAEMON_RETRY_SECONDS,
    BACKGROUND_WATCH_STREAM_RETRY_SECONDS,
    MCP_PROTOCOL_VERSION,
    LoomMcpServer,
)
from loom.project import initialize_project  # noqa: E402


@contextlib.contextmanager
def working_directory(path: pathlib.Path) -> pathlib.Path:
    previous = pathlib.Path.cwd()
    os.chdir(path)
    try:
        yield path
    finally:
        os.chdir(previous)


def _init_git_repo(repo_root: pathlib.Path) -> None:
    subprocess.run(
        ("git", "-C", str(repo_root), "init", "-q"),
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(repo_root: pathlib.Path, message: str) -> None:
    subprocess.run(
        ("git", "-C", str(repo_root), "config", "user.email", "loom-tests@example.com"),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repo_root), "config", "user.name", "Loom Tests"),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repo_root), "add", "."),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repo_root), "commit", "-q", "-m", message),
        check=True,
        capture_output=True,
        text=True,
    )


class McpTest(unittest.TestCase):
    def test_initialized_notification_sets_state_under_lock(self) -> None:
        class _RecordingLock:
            def __init__(self) -> None:
                self.enter_count = 0

            def __enter__(self):
                self.enter_count += 1
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        server = LoomMcpServer(cwd=PROJECT_ROOT)
        recording_lock = _RecordingLock()
        server._state_lock = recording_lock  # type: ignore[assignment]

        with patch.object(server, "_maybe_start_background_watch") as start_watch_mock:
            response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            )

        self.assertIsNone(response)
        self.assertTrue(server._initialized)
        self.assertEqual(recording_lock.enter_count, 1)
        start_watch_mock.assert_called_once_with()

    def test_tool_init_assigns_client_under_state_lock_after_store_initialize(self) -> None:
        class _RecordingLock:
            def __init__(self) -> None:
                self.enter_count = 0
                self.entered_after_store_init = False
                self.store_initialized = False

            def __enter__(self):
                self.enter_count += 1
                self.entered_after_store_init = self.store_initialized
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)
            recording_lock = _RecordingLock()
            server._state_lock = recording_lock  # type: ignore[assignment]

            fake_client = Mock()

            def initialize_store() -> None:
                recording_lock.store_initialized = True

            fake_client.store.initialize.side_effect = initialize_store

            with patch("loom.mcp.initialize_project") as init_project_mock, patch(
                "loom.mcp.CoordinationClient",
                return_value=fake_client,
            ) as client_cls:
                project, _ = initialize_project(repo_root)
                init_project_mock.return_value = (project, False)
                result = server._tool_init({})

        self.assertIs(server._client, fake_client)
        self.assertEqual(recording_lock.enter_count, 1)
        self.assertTrue(recording_lock.entered_after_store_init)
        client_cls.assert_called_once()
        fake_client.store.initialize.assert_called_once_with()
        self.assertEqual(result["structured"]["created"], False)

    def test_server_initialize_and_list_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            initialize_project(repo_root)
            server = LoomMcpServer(cwd=repo_root)

            initialize = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "0"},
                    },
                }
            )
            self.assertIsNotNone(initialize)
            assert initialize is not None
            self.assertEqual(initialize["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
            self.assertIn("prompts", initialize["result"]["capabilities"])
            self.assertIn("resources", initialize["result"]["capabilities"])
            self.assertTrue(initialize["result"]["capabilities"]["resources"]["subscribe"])
            self.assertTrue(initialize["result"]["capabilities"]["resources"]["listChanged"])

            initialized = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            )
            self.assertIsNone(initialized)

            listed = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                }
            )
            self.assertIsNotNone(listed)
            assert listed is not None
            tools = {tool["name"]: tool for tool in listed["result"]["tools"]}
            self.assertIn("loom_init", tools)
            self.assertIn("loom_bind", tools)
            self.assertIn("loom_whoami", tools)
            self.assertIn("loom_start", tools)
            self.assertIn("loom_protocol", tools)
            self.assertIn("loom_claim", tools)
            self.assertIn("loom_renew", tools)
            self.assertIn("loom_context_write", tools)
            self.assertIn("loom_context_ack", tools)
            self.assertIn("loom_log", tools)
            self.assertIn("loom_agents", tools)
            self.assertIn("loom_agent", tools)
            self.assertIn("loom_timeline", tools)
            self.assertIn("loom_inbox", tools)
            self.assertEqual(tools["loom_status"]["title"], "Read Status")
            self.assertTrue(tools["loom_status"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["loom_start"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["loom_agents"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["loom_whoami"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["loom_protocol"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["loom_agent"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["loom_log"]["annotations"]["readOnlyHint"])
            self.assertTrue(tools["loom_timeline"]["annotations"]["readOnlyHint"])
            self.assertFalse(tools["loom_claim"]["annotations"]["readOnlyHint"])
            self.assertFalse(tools["loom_bind"]["annotations"]["readOnlyHint"])
            self.assertFalse(tools["loom_renew"]["annotations"]["readOnlyHint"])
            self.assertFalse(tools["loom_claim"]["annotations"]["destructiveHint"])
            self.assertFalse(tools["loom_context_ack"]["annotations"]["readOnlyHint"])
            self.assertIn("outputSchema", tools["loom_claim"])
            self.assertEqual(tools["loom_claim"]["outputSchema"]["required"], ["ok"])
            self.assertIn("next_steps", tools["loom_claim"]["outputSchema"]["properties"])
            self.assertIn("links", tools["loom_status"]["outputSchema"]["properties"])
            self.assertIn("authority", tools["loom_status"]["outputSchema"]["properties"])
            self.assertIn("repo_lanes", tools["loom_status"]["outputSchema"]["properties"])
            self.assertIn(
                "lanes",
                tools["loom_status"]["outputSchema"]["properties"]["repo_lanes"]["properties"],
            )
            self.assertIn(
                "programs",
                tools["loom_status"]["outputSchema"]["properties"]["repo_lanes"]["properties"],
            )
            self.assertIn("attention", tools["loom_start"]["outputSchema"]["properties"])
            self.assertIn("authority", tools["loom_start"]["outputSchema"]["properties"])
            self.assertIn("repo_lanes", tools["loom_start"]["outputSchema"]["properties"])
            self.assertIn(
                "lanes",
                tools["loom_start"]["outputSchema"]["properties"]["repo_lanes"]["properties"],
            )
            self.assertIn(
                "programs",
                tools["loom_start"]["outputSchema"]["properties"]["repo_lanes"]["properties"],
            )
            self.assertIn(
                "worktree_drift",
                tools["loom_start"]["outputSchema"]["properties"]["attention"]["properties"],
            )
            self.assertIn(
                "acknowledged_migration_lanes",
                tools["loom_start"]["outputSchema"]["properties"]["attention"]["properties"],
            )
            self.assertIn("next_action", tools["loom_start"]["outputSchema"]["properties"])
            self.assertIn(
                "urgency",
                tools["loom_start"]["outputSchema"]["properties"]["next_action"]["properties"],
            )
            self.assertIn("active_work", tools["loom_start"]["outputSchema"]["properties"])
            self.assertIn("worktree", tools["loom_start"]["outputSchema"]["properties"])
            self.assertIn("handoff", tools["loom_start"]["outputSchema"]["properties"])
            self.assertIn("active_work", tools["loom_agent"]["outputSchema"]["properties"])
            self.assertIn("worktree", tools["loom_agent"]["outputSchema"]["properties"])

            prompts = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "prompts/list",
                }
            )
            self.assertIsNotNone(prompts)
            assert prompts is not None
            prompt_map = {prompt["name"]: prompt for prompt in prompts["result"]["prompts"]}
            self.assertIn("coordinate_before_edit", prompt_map)
            self.assertIn("triage_inbox", prompt_map)
            self.assertIn("resolve_conflict", prompt_map)
            self.assertIn("adapt_or_wait", prompt_map)
            self.assertIn("finish_and_release", prompt_map)
            self.assertIn("handoff_work", prompt_map)
            self.assertTrue(
                any(argument["required"] for argument in prompt_map["coordinate_before_edit"]["arguments"])
            )
            self.assertTrue(
                any(argument["required"] for argument in prompt_map["handoff_work"]["arguments"])
            )
            self.assertTrue(
                any(argument["required"] for argument in prompt_map["adapt_or_wait"]["arguments"])
            )

            resources = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "resources/list",
                }
            )
            self.assertIsNotNone(resources)
            assert resources is not None
            resource_map = {resource["uri"]: resource for resource in resources["result"]["resources"]}
            self.assertIn("loom://start", resource_map)
            self.assertIn("loom://mcp", resource_map)
            self.assertIn("loom://protocol", resource_map)
            self.assertIn("loom://identity", resource_map)
            self.assertIn("loom://activity", resource_map)
            self.assertIn("loom://log", resource_map)
            self.assertIn("loom://context", resource_map)
            self.assertIn("loom://conflicts", resource_map)
            self.assertIn("loom://conflicts/history", resource_map)
            self.assertIn("loom://agent", resource_map)
            self.assertIn("loom://inbox", resource_map)

            templates = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "resources/templates/list",
                }
            )
            self.assertIsNotNone(templates)
            assert templates is not None
            template_map = {
                template["uriTemplate"]: template
                for template in templates["result"]["resourceTemplates"]
            }
            self.assertIn("loom://claim/{claim_id}", template_map)
            self.assertIn("loom://claim/{claim_id}/timeline", template_map)
            self.assertIn("loom://intent/{intent_id}", template_map)
            self.assertIn("loom://intent/{intent_id}/timeline", template_map)
            self.assertIn("loom://agent/{agent_id}", template_map)
            self.assertIn("loom://inbox/{agent_id}", template_map)
            self.assertIn("loom://activity/{agent_id}", template_map)
            self.assertIn("loom://activity/{agent_id}/after/{sequence}", template_map)
            self.assertIn("loom://conflict/{conflict_id}", template_map)
            self.assertIn("loom://context/{context_id}", template_map)
            self.assertIn("loom://conflict/{conflict_id}/timeline", template_map)
            self.assertIn("loom://context/{context_id}/timeline", template_map)
            self.assertIn("loom://timeline/{object_id}", template_map)
            self.assertIn("loom://event/{sequence}", template_map)
            self.assertIn("loom://events/after/{sequence}", template_map)

    def test_protocol_tool_returns_local_protocol_descriptor(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "protocol",
                "method": "tools/call",
                "params": {"name": "loom_protocol", "arguments": {}},
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertFalse(response["result"]["isError"])
        structured = response["result"]["structuredContent"]
        self.assertTrue(structured["ok"])
        self.assertEqual(structured["protocol"]["name"], "loom.local")
        self.assertIn("agents.read", structured["protocol"]["operations"])
        self.assertIn("operation_schemas", structured["protocol"])

    def test_start_tool_guides_repo_state_across_bootstrap_and_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            before_init = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-before-init",
                    "method": "tools/call",
                    "params": {"name": "loom_start", "arguments": {}},
                }
            )
            self.assertIsNotNone(before_init)
            assert before_init is not None
            self.assertFalse(before_init["result"]["isError"])
            self.assertIn("Next: loom_init.", before_init["result"]["content"][0]["text"])
            self.assertIn(
                "Why: Loom is not initialized yet.",
                before_init["result"]["content"][0]["text"],
            )
            before_structured = before_init["result"]["structuredContent"]
            self.assertTrue(before_structured["ok"])
            self.assertEqual(before_structured["mode"], "uninitialized")
            self.assertFalse(before_structured["mcp"]["initialized"])
            self.assertEqual(before_structured["links"]["protocol"], "loom://protocol")
            self.assertEqual(before_structured["next_action"]["tool"], "loom_init")
            self.assertEqual(before_structured["next_action"]["confidence"], "high")
            self.assertIn("not initialized", before_structured["next_action"]["reason"])
            self.assertEqual(
                before_structured["next_steps"],
                [
                    "Call loom_init to initialize Loom in this repository.",
                    'Call loom_init with default_agent="<agent-name>" to pin a stable agent identity.',
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
                ],
            )
            self.assertEqual(before_structured["dead_session_agents"], [])
            self.assertEqual(
                before_structured["quick_loop"],
                [
                    "start: call loom_start, execute next_action, then loop back if needed",
                    "claim: say what you're working on before edits",
                    "intent: say what you're about to touch only when the scope gets specific",
                    "inbox: react to context or conflicts before continuing",
                    "finish: release work cleanly when you're done for now",
                ],
            )
            self.assertEqual(before_structured["command_guide"][0]["tool"], "loom_start")
            self.assertEqual(before_structured["command_guide"][1]["tool"], "loom_init")
            self.assertEqual(before_structured["command_guide"][-1]["tool"], "loom_finish")

            before_init_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-resource-before-init",
                    "method": "resources/read",
                    "params": {"uri": "loom://start"},
                }
            )
            self.assertIsNotNone(before_init_resource)
            assert before_init_resource is not None
            before_resource_payload = json.loads(
                before_init_resource["result"]["contents"][0]["text"]
            )
            self.assertEqual(before_resource_payload["mode"], "uninitialized")
            self.assertEqual(before_resource_payload["links"]["protocol"], "loom://protocol")
            self.assertEqual(before_resource_payload["command_guide"][0]["tool"], "loom_start")
            self.assertEqual(before_resource_payload["command_guide"][1]["tool"], "loom_init")

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            ready_start = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-ready",
                    "method": "tools/call",
                    "params": {"name": "loom_start", "arguments": {}},
                }
            )
            self.assertIsNotNone(ready_start)
            assert ready_start is not None
            self.assertIn("Next: loom_claim", ready_start["result"]["content"][0]["text"])
            self.assertIn('"scope": ["path/to/area"]', ready_start["result"]["content"][0]["text"])
            self.assertIn(
                "Why: The repository is initialized and currently has no active coordination state.",
                ready_start["result"]["content"][0]["text"],
            )
            ready_structured = ready_start["result"]["structuredContent"]
            self.assertEqual(ready_structured["mode"], "ready")
            self.assertEqual(ready_structured["attention"]["claims"], 0)
            self.assertEqual(ready_structured["links"]["status"], "loom://status")
            self.assertEqual(ready_structured["links"]["agent"], "loom://agent/agent-a")
            self.assertEqual(ready_structured["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                ready_structured["next_action"]["arguments"]["scope"],
                ["path/to/area"],
            )
            self.assertEqual(ready_structured["next_action"]["confidence"], "medium")
            self.assertEqual(
                ready_structured["next_steps"],
                [
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
                    "Call loom_status to compare the repo state.",
                    "Call loom_agent for a focused agent view.",
                ],
            )
            self.assertEqual(ready_structured["dead_session_agents"], [])
            self.assertEqual(ready_structured["command_guide"][0]["tool"], "loom_start")

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-a",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None

            intent_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "intent-b",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_intent",
                        "arguments": {
                            "agent_id": "agent-b",
                            "description": "Touch auth middleware",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(intent_result)
            assert intent_result is not None

            attention_start = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-attention",
                    "method": "tools/call",
                    "params": {"name": "loom_start", "arguments": {}},
                }
            )
            self.assertIsNotNone(attention_start)
            assert attention_start is not None
            attention_structured = attention_start["result"]["structuredContent"]
            self.assertEqual(attention_structured["mode"], "attention")
            self.assertEqual(attention_structured["attention"]["conflicts"], 1)
            self.assertEqual(attention_structured["attention"]["agent_conflicts"], 1)
            self.assertIsNotNone(attention_structured["active_work"])
            self.assertEqual(attention_structured["active_work"]["priority"]["kind"], "conflict")
            self.assertEqual(
                [entry["id"] for entry in attention_structured["active_work"]["react_now_context"]],
                [],
            )
            self.assertEqual(
                [entry["id"] for entry in attention_structured["active_work"]["review_soon_context"]],
                [],
            )
            self.assertEqual(attention_structured["next_action"]["tool"], "loom_resolve")
            self.assertEqual(
                attention_structured["next_action"]["arguments"]["conflict_id"],
                attention_structured["active_work"]["priority"]["id"],
            )
            self.assertEqual(attention_structured["next_action"]["confidence"], "high")
            self.assertIn("active conflict", attention_structured["next_action"]["reason"])
            self.assertEqual(attention_structured["active_work"]["priority"]["confidence"], "high")
            self.assertIn("active conflict", attention_structured["active_work"]["priority"]["reason"])
            self.assertEqual(attention_structured["links"]["conflicts"], "loom://conflicts")
            self.assertEqual(attention_structured["links"]["inbox"], "loom://inbox/agent-a")
            self.assertEqual(
                attention_structured["next_steps"][0],
                f'Call loom_resolve with conflict_id="{attention_structured["active_work"]["priority"]["id"]}" and note="<resolution>".',
            )

            attention_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-resource-attention",
                    "method": "resources/read",
                    "params": {"uri": "loom://start"},
                }
            )
            self.assertIsNotNone(attention_resource)
            assert attention_resource is not None
            attention_resource_payload = json.loads(
                attention_resource["result"]["contents"][0]["text"]
            )
            self.assertEqual(attention_resource_payload["mode"], "attention")
            self.assertEqual(attention_resource_payload["attention"]["conflicts"], 1)
            self.assertEqual(attention_resource_payload["links"]["inbox"], "loom://inbox/agent-a")

    def test_start_tool_surfaces_invalid_authority_and_claim_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-invalid-authority",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: missing\n"
                "      path: DOES_NOT_EXIST.md\n"
                "      role: root_truth\n",
                encoding="utf-8",
            )

            start_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-invalid-authority",
                    "method": "tools/call",
                    "params": {"name": "loom_start", "arguments": {}},
                }
            )
            self.assertIsNotNone(start_result)
            assert start_result is not None
            structured = start_result["result"]["structuredContent"]
            self.assertEqual(structured["mode"], "attention")
            self.assertEqual(structured["authority"]["status"], "invalid")
            self.assertEqual(structured["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                structured["next_action"]["arguments"],
                {
                    "description": "Fix declared authority configuration",
                    "scope": ["loom.yaml"],
                },
            )
            self.assertEqual(
                structured["next_steps"][0],
                'Call loom_claim with description="Fix declared authority configuration" and scope=["loom.yaml"].',
            )
            self.assertIn("missing file 'DOES_NOT_EXIST.md'", structured["next_action"]["reason"])

    def test_start_resource_surfaces_invalid_authority_and_claim_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "resource-init-invalid-authority",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: missing\n"
                "      path: DOES_NOT_EXIST.md\n"
                "      role: root_truth\n",
                encoding="utf-8",
            )

            start_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-resource-invalid-authority",
                    "method": "resources/read",
                    "params": {"uri": "loom://start"},
                }
            )
            self.assertIsNotNone(start_resource)
            assert start_resource is not None
            payload = json.loads(start_resource["result"]["contents"][0]["text"])
            self.assertEqual(payload["mode"], "attention")
            self.assertEqual(payload["authority"]["status"], "invalid")
            self.assertEqual(payload["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                payload["next_action"]["arguments"],
                {
                    "description": "Fix declared authority configuration",
                    "scope": ["loom.yaml"],
                },
            )
            self.assertEqual(
                payload["next_steps"][0],
                'Call loom_claim with description="Fix declared authority configuration" and scope=["loom.yaml"].',
            )

    def test_start_resource_promotes_declaration_change_to_authority_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "resource-init-authority-change",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      scope_hints:\n"
                "        - src\n",
                encoding="utf-8",
            )

            start_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-resource-authority-change",
                    "method": "resources/read",
                    "params": {"uri": "loom://start"},
                }
            )
            self.assertIsNotNone(start_resource)
            assert start_resource is not None
            payload = json.loads(start_resource["result"]["contents"][0]["text"])
            self.assertEqual(payload["mode"], "attention")
            self.assertTrue(payload["authority"]["declaration_changed"])
            self.assertEqual(payload["authority"]["changed_scope_hints"], ["src"])
            self.assertEqual(payload["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                payload["next_action"]["arguments"],
                {
                    "description": "Review repo surfaces affected by authority change",
                    "scope": ["src"],
                },
            )
            self.assertEqual(
                payload["next_steps"][0],
                'Call loom_claim with description="Review repo surfaces affected by authority change" and scope=["src"].',
            )

    def test_status_tool_and_resource_promote_declaration_change_to_authority_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (repo_root / "docs").mkdir()
            (repo_root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-authority-change",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      scope_hints:\n"
                "        - src\n"
                "        - docs/guide.md\n",
                encoding="utf-8",
            )

            status_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "status-authority-change",
                    "method": "tools/call",
                    "params": {"name": "loom_status", "arguments": {}},
                }
            )
            self.assertIsNotNone(status_result)
            assert status_result is not None
            structured = status_result["result"]["structuredContent"]
            self.assertTrue(structured["authority"]["declaration_changed"])
            self.assertEqual(
                structured["authority"]["changed_scope_hints"],
                ["src", "docs/guide.md"],
            )
            self.assertEqual(structured["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                structured["next_action"]["arguments"],
                {
                    "description": "Review repo surfaces affected by authority change",
                    "scope": ["src", "docs/guide.md"],
                },
            )

            status_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "status-resource-authority-change",
                    "method": "resources/read",
                    "params": {"uri": "loom://status"},
                }
            )
            self.assertIsNotNone(status_resource)
            assert status_resource is not None
            payload = json.loads(status_resource["result"]["contents"][0]["text"])
            self.assertTrue(payload["authority"]["declaration_changed"])
            self.assertEqual(payload["authority"]["changed_scope_hints"], ["src", "docs/guide.md"])
            self.assertEqual(payload["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                payload["next_action"]["arguments"]["scope"],
                ["src", "docs/guide.md"],
            )

    def test_start_resource_promotes_changed_authority_surface_to_authority_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "resource-init-surface-authority-change",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      scope_hints:\n"
                "        - src\n",
                encoding="utf-8",
            )
            _commit_all(repo_root, "declare authority")
            (repo_root / "PRODUCT.md").write_text("product changed\n", encoding="utf-8")

            start_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-resource-surface-authority-change",
                    "method": "resources/read",
                    "params": {"uri": "loom://start"},
                }
            )
            self.assertIsNotNone(start_resource)
            assert start_resource is not None
            payload = json.loads(start_resource["result"]["contents"][0]["text"])
            self.assertFalse(payload["authority"]["declaration_changed"])
            self.assertEqual(payload["mode"], "attention")
            self.assertEqual(payload["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                payload["next_action"]["arguments"],
                {
                    "description": "Review repo surfaces affected by authority change",
                    "scope": ["src"],
                },
            )

    def test_status_resource_surfaces_affected_active_work_for_changed_authority_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-surface-authority-change",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      scope_hints:\n"
                "        - src\n",
                encoding="utf-8",
            )
            _commit_all(repo_root, "declare authority")

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-authority-affected-work",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Touch app code",
                            "scope": ["src"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)

            (repo_root / "PRODUCT.md").write_text("product changed\n", encoding="utf-8")

            status_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "status-resource-surface-authority-change",
                    "method": "resources/read",
                    "params": {"uri": "loom://status"},
                }
            )
            self.assertIsNotNone(status_resource)
            assert status_resource is not None
            payload = json.loads(status_resource["result"]["contents"][0]["text"])
            self.assertFalse(payload["authority"]["declaration_changed"])
            self.assertEqual(
                tuple(item["path"] for item in payload["authority"]["changed_surfaces"]),
                ("PRODUCT.md",),
            )
            self.assertEqual(payload["authority"]["changed_scope_hints"], ["src"])
            self.assertEqual(len(payload["authority"]["affected_active_work"]), 1)
            self.assertEqual(payload["authority"]["affected_active_work"][0]["kind"], "claim")
            self.assertEqual(payload["authority"]["affected_active_work"][0]["agent_id"], "agent-a")

    def test_start_status_agents_and_clean_tools_surface_dead_pid_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-clean",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-dead-pid",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "agent_id": "dev@host:pid-101",
                            "description": "Legacy pid claim",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)

            with patch(
                "loom.mcp.terminal_identity_process_is_alive",
                side_effect=lambda agent_id: False if agent_id == "dev@host:pid-101" else None,
            ):
                start_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "start-dead-pid",
                        "method": "tools/call",
                        "params": {"name": "loom_start", "arguments": {}},
                    }
                )
                self.assertIsNotNone(start_result)
                assert start_result is not None
                start_structured = start_result["result"]["structuredContent"]
                self.assertEqual(start_structured["dead_session_agents"], ["dev@host:pid-101"])
                self.assertEqual(start_structured["next_action"]["tool"], "loom_clean")
                self.assertEqual(
                    start_structured["next_steps"][0],
                    "Call loom_clean to close dead pid-based session work and prune idle history.",
                )
                self.assertEqual(start_structured["command_guide"][-1]["tool"], "loom_clean")

                status_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "status-dead-pid",
                        "method": "tools/call",
                        "params": {"name": "loom_status", "arguments": {}},
                    }
                )
                self.assertIsNotNone(status_result)
                assert status_result is not None
                status_structured = status_result["result"]["structuredContent"]
                self.assertEqual(status_structured["dead_session_agents"], ["dev@host:pid-101"])
                self.assertEqual(status_structured["next_action"]["tool"], "loom_clean")

                agents_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "agents-dead-pid",
                        "method": "tools/call",
                        "params": {"name": "loom_agents", "arguments": {}},
                    }
                )
                self.assertIsNotNone(agents_result)
                assert agents_result is not None
                agents_structured = agents_result["result"]["structuredContent"]
                self.assertEqual(agents_structured["dead_session_agents"], ["dev@host:pid-101"])
                self.assertEqual(
                    agents_structured["next_steps"][0],
                    "Call loom_clean to close dead pid-based session work and prune idle history.",
                )

                clean_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "clean-dead-pid",
                        "method": "tools/call",
                        "params": {"name": "loom_clean", "arguments": {}},
                    }
                )

            self.assertIsNotNone(clean_result)
            assert clean_result is not None
            clean_structured = clean_result["result"]["structuredContent"]
            self.assertEqual(clean_structured["closed_dead_sessions"], ["dev@host:pid-101"])
            self.assertEqual(len(clean_structured["released_claim_ids"]), 1)
            self.assertEqual(clean_structured["next_action"]["tool"], "loom_start")
            self.assertEqual(
                clean_structured["next_steps"],
                [
                    "Call loom_start to ask Loom what to do next in this repository.",
                    "Call loom_status to compare the updated repo state.",
                    "Call loom_agents to inspect the remaining agents.",
                ],
            )
            self.assertIn("dev@host:pid-101", clean_structured["pruned_idle_agents"])

    def test_finish_tool_releases_work_and_records_optional_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-finish",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-before-finish",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)

            finish_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "finish-tool",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_finish",
                        "arguments": {"summary": "Finished auth refactor."},
                    },
                }
            )
            self.assertIsNotNone(finish_result)
            assert finish_result is not None
            finish_structured = finish_result["result"]["structuredContent"]
            self.assertEqual(finish_structured["claim"]["description"], "Refactor auth flow")
            self.assertIsNone(finish_structured["intent"])
            self.assertEqual(finish_structured["context"]["topic"], "session-handoff")
            self.assertEqual(finish_structured["context"]["scope"], ["src/auth"])
            self.assertEqual(finish_structured["pruned_idle_agents"], ["agent-a"])
            self.assertEqual(
                finish_structured["next_steps"][0],
                "Call loom_start to ask Loom what to do next in this repository.",
            )

            status_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "status-after-finish",
                    "method": "tools/call",
                    "params": {"name": "loom_status", "arguments": {}},
                }
            )
            self.assertIsNotNone(status_result)
            assert status_result is not None
            status_structured = status_result["result"]["structuredContent"]
            self.assertEqual(len(status_structured["status"]["claims"]), 0)

    def test_finish_tool_can_keep_idle_agent_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-finish-keep-idle",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-before-finish-keep-idle",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)

            finish_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "finish-tool-keep-idle",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_finish",
                        "arguments": {"keep_idle": True},
                    },
                }
            )
            self.assertIsNotNone(finish_result)
            assert finish_result is not None
            finish_structured = finish_result["result"]["structuredContent"]
            self.assertEqual(finish_structured["pruned_idle_agents"], [])

            agents_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "agents-after-finish-keep-idle",
                    "method": "tools/call",
                    "params": {"name": "loom_agents", "arguments": {"include_idle": True}},
                }
            )
            self.assertIsNotNone(agents_result)
            assert agents_result is not None
            agent_ids = [
                agent["agent_id"]
                for agent in agents_result["result"]["structuredContent"]["agents"]
            ]
            self.assertIn("agent-a", agent_ids)

    def test_start_tool_needs_identity_uses_shared_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-no-default",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            start_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "start-needs-identity",
                    "method": "tools/call",
                    "params": {"name": "loom_start", "arguments": {}},
                }
            )
            self.assertIsNotNone(start_result)
            assert start_result is not None
            structured = start_result["result"]["structuredContent"]
            self.assertEqual(structured["mode"], "needs_identity")
            self.assertEqual(
                structured["summary"],
                f"{structured['identity']['id']} is a raw terminal identity. Resolve a stable agent before coordinated work.",
            )
            self.assertEqual(
                structured["next_steps"],
                [
                    'Call loom_bind with agent_id="<agent-name>" to pin this MCP session to a stable agent identity.',
                    "Call loom_start to ask Loom what to do next in this repository.",
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
                ],
            )

    def test_start_tool_surfaces_worktree_drift_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-drift",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            with patch(
                "loom.guidance.current_worktree_paths",
                return_value=("src/mobile/app.dart", "src/mobile/session.dart"),
            ):
                drift_start = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "start-drift",
                        "method": "tools/call",
                        "params": {"name": "loom_start", "arguments": {}},
                    }
                )

            self.assertIsNotNone(drift_start)
            assert drift_start is not None
            structured = drift_start["result"]["structuredContent"]
            self.assertEqual(structured["mode"], "attention")
            self.assertEqual(structured["attention"]["worktree_drift"], 2)
            self.assertIsNone(structured["active_work"])
            self.assertEqual(structured["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                structured["next_action"]["arguments"]["scope"],
                ["src/mobile"],
            )
            self.assertEqual(structured["next_action"]["confidence"], "high")
            self.assertIn("changed files", structured["next_action"]["reason"])
            self.assertEqual(structured["worktree"]["suggested_scope"], ["src/mobile"])
            self.assertEqual(
                structured["next_steps"],
                [
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["src/mobile"].',
                    "Call loom_status to compare the repo state.",
                    "Call loom_agent for a focused agent view.",
                ],
            )

    def test_start_tool_surfaces_recent_handoff_when_no_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-handoff",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            handoff_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "handoff-context",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_write",
                        "arguments": {
                            "topic": "session-handoff",
                            "body": "Resume auth cleanup from the prior session.",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(handoff_result)
            assert handoff_result is not None

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                handoff_start = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "start-handoff",
                        "method": "tools/call",
                        "params": {"name": "loom_start", "arguments": {}},
                    }
                )

            self.assertIsNotNone(handoff_start)
            assert handoff_start is not None
            structured = handoff_start["result"]["structuredContent"]
            self.assertEqual(structured["mode"], "active")
            self.assertIn("recent handoff", structured["summary"])
            self.assertIsNone(structured["active_work"])
            self.assertIsNotNone(structured["handoff"])
            self.assertEqual(structured["handoff"]["topic"], "session-handoff")
            self.assertEqual(structured["handoff"]["scope"], ["src/auth"])
            self.assertEqual(structured["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                structured["next_action"]["arguments"]["scope"],
                ["src/auth"],
            )
            self.assertEqual(structured["next_action"]["confidence"], "high")
            self.assertIn("recent self-handoff", structured["next_action"]["reason"])
            self.assertEqual(
                structured["next_steps"],
                [
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["src/auth"].',
                    "Call loom_status to compare the repo state.",
                    "Call loom_agent for a focused agent view.",
                ],
            )

    def test_start_tool_surfaces_settled_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-settled",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-settled",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                settled_start = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "start-settled",
                        "method": "tools/call",
                        "params": {"name": "loom_start", "arguments": {}},
                    }
                )

            self.assertIsNotNone(settled_start)
            assert settled_start is not None
            structured = settled_start["result"]["structuredContent"]
            self.assertEqual(structured["mode"], "active")
            self.assertIn("looks settled", structured["summary"])
            self.assertTrue(structured["active_work"]["completion_ready"])
            self.assertEqual(structured["active_work"]["react_now_context"], [])
            self.assertEqual(structured["active_work"]["review_soon_context"], [])
            self.assertEqual(structured["next_action"]["tool"], "loom_finish")
            self.assertEqual(structured["next_action"]["arguments"], {})
            self.assertEqual(structured["next_action"]["confidence"], "high")
            self.assertEqual(
                structured["next_steps"],
                [
                    "Call loom_finish to publish an optional handoff and release current work.",
                    "Call loom_status to compare the repo state.",
                    "Call loom_agent for a focused agent view.",
                ],
            )

    def test_start_tool_prefers_finish_for_yield_policy_under_context_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-yield",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-yield",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Background dependency hygiene",
                            "scope": ["src/deps"],
                            "lease_minutes": 30,
                            "lease_policy": "yield",
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None

            context_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "context-yield",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_write",
                        "arguments": {
                            "agent_id": "agent-b",
                            "topic": "deps-are-moving",
                            "body": "Feature work is changing dependency behavior right now.",
                            "scope": ["src/deps"],
                        },
                    },
                }
            )
            self.assertIsNotNone(context_result)
            assert context_result is not None

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                pressured_start = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "start-yield-pressure",
                        "method": "tools/call",
                        "params": {"name": "loom_start", "arguments": {}},
                    }
                )

            self.assertIsNotNone(pressured_start)
            assert pressured_start is not None
            structured = pressured_start["result"]["structuredContent"]
            self.assertEqual(structured["mode"], "attention")
            self.assertIsNone(structured["active_work"]["lease_alert"])
            self.assertEqual(structured["active_work"]["yield_alert"]["policy"], "yield")
            self.assertEqual(structured["next_action"]["tool"], "loom_finish")
            self.assertEqual(
                structured["next_steps"][0],
                "Call loom_finish to publish an optional handoff and release current work.",
            )

    def test_agent_tool_prefers_finish_for_yield_policy_under_nearby_intent_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Background auth cleanup",
                            "scope": ["src/auth/session"],
                            "lease_minutes": 30,
                            "lease_policy": "yield",
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None

            intent_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "intent-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_intent",
                        "arguments": {
                            "description": "Touch auth session internals",
                            "scope": ["src/auth/session"],
                            "lease_minutes": 30,
                            "lease_policy": "yield",
                        },
                    },
                }
            )
            self.assertIsNotNone(intent_result)
            assert intent_result is not None

            nearby_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "intent-nearby-pressure",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_intent",
                        "arguments": {
                            "agent_id": "agent-b",
                            "description": "Refactor auth session implementation",
                            "scope": ["src/auth/session"],
                        },
                    },
                }
            )
            self.assertIsNotNone(nearby_result)
            assert nearby_result is not None

            conflicts_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "conflicts-nearby-pressure",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_conflicts",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(conflicts_result)
            assert conflicts_result is not None
            conflict_ids = [
                item["id"] for item in conflicts_result["result"]["structuredContent"]["conflicts"]
            ]
            self.assertTrue(conflict_ids)
            for index, conflict_id in enumerate(conflict_ids):
                resolve_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": f"resolve-nearby-pressure-{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_resolve",
                            "arguments": {
                                "conflict_id": conflict_id,
                                "note": "Nearby work is intentional.",
                            },
                        },
                    }
                )
                self.assertIsNotNone(resolve_result)
                assert resolve_result is not None

            with patch("loom.guidance.current_worktree_paths", return_value=("src/auth/session",)):
                agent_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "agent-yield-nearby-pressure",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_agent",
                            "arguments": {"agent_id": "agent-a"},
                        },
                    }
                )

            self.assertIsNotNone(agent_result)
            assert agent_result is not None
            structured = agent_result["result"]["structuredContent"]
            self.assertEqual(structured["active_work"]["yield_alert"]["policy"], "yield")
            self.assertTrue(structured["active_work"]["yield_alert"]["acknowledged"])
            self.assertEqual(structured["active_work"]["yield_alert"]["confidence"], "medium")
            self.assertEqual(structured["next_action"]["tool"], "loom_finish")
            self.assertIn("acknowledged nearby active work", structured["next_action"]["reason"])
            self.assertEqual(
                structured["next_steps"][0],
                "Call loom_finish to publish an optional handoff and release current work.",
            )

    def test_status_tool_ignores_stale_nearby_claim_for_yield_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-stale-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-stale-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Background auth cleanup",
                            "scope": ["src/auth/session"],
                            "lease_minutes": 30,
                            "lease_policy": "yield",
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None

            intent_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "intent-stale-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_intent",
                        "arguments": {
                            "description": "Touch auth session internals",
                            "scope": ["src/auth/session"],
                            "lease_minutes": 30,
                            "lease_policy": "yield",
                        },
                    },
                }
            )
            self.assertIsNotNone(intent_result)
            assert intent_result is not None

            nearby_claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-stale-nearby-pressure",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "agent_id": "agent-b",
                            "description": "Direct auth session work",
                            "scope": ["src/auth/session"],
                        },
                    },
                }
            )
            self.assertIsNotNone(nearby_claim_result)
            assert nearby_claim_result is not None

            conflicts_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "conflicts-stale-nearby-pressure",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_conflicts",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(conflicts_result)
            assert conflicts_result is not None
            conflict_ids = [
                item["id"] for item in conflicts_result["result"]["structuredContent"]["conflicts"]
            ]
            self.assertTrue(conflict_ids)
            for index, conflict_id in enumerate(conflict_ids):
                resolve_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": f"resolve-stale-nearby-pressure-{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_resolve",
                            "arguments": {
                                "conflict_id": conflict_id,
                                "note": "Stale nearby claim acknowledged.",
                            },
                        },
                    }
                )
                self.assertIsNotNone(resolve_result)
                assert resolve_result is not None

            with patch("loom.guidance.is_stale_utc_timestamp", return_value=True):
                status_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "status-stale-yield-nearby-pressure",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_status",
                            "arguments": {},
                        },
                    }
                )

            self.assertIsNotNone(status_result)
            assert status_result is not None
            structured = status_result["result"]["structuredContent"]
            self.assertEqual(structured["next_action"]["tool"], "loom_agent")

    def test_agent_tool_prefers_finish_for_semantic_nearby_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.py").write_text(
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
                encoding="utf-8",
            )
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-semantic-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-semantic-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Background API cleanup",
                            "scope": ["src/api/handlers.py"],
                            "lease_minutes": 30,
                            "lease_policy": "yield",
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None

            intent_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "intent-semantic-yield-nearby",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_intent",
                        "arguments": {
                            "description": "Touch API handler response shape",
                            "scope": ["src/api/handlers.py"],
                            "lease_minutes": 30,
                            "lease_policy": "yield",
                        },
                    },
                }
            )
            self.assertIsNotNone(intent_result)
            assert intent_result is not None

            nearby_claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-semantic-nearby-pressure",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "agent_id": "agent-b",
                            "description": "Refactor auth session model",
                            "scope": ["src/auth/session.py"],
                        },
                    },
                }
            )
            self.assertIsNotNone(nearby_claim_result)
            assert nearby_claim_result is not None

            conflicts_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "conflicts-semantic-nearby-pressure",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_conflicts",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(conflicts_result)
            assert conflicts_result is not None
            conflict_ids = [
                item["id"] for item in conflicts_result["result"]["structuredContent"]["conflicts"]
            ]
            self.assertTrue(conflict_ids)
            for index, conflict_id in enumerate(conflict_ids):
                resolve_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": f"resolve-semantic-nearby-pressure-{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_resolve",
                            "arguments": {
                                "conflict_id": conflict_id,
                                "note": "Semantic nearby work acknowledged.",
                            },
                        },
                    }
                )
                self.assertIsNotNone(resolve_result)
                assert resolve_result is not None

            with patch("loom.guidance.current_worktree_paths", return_value=("src/api/handlers.py",)):
                agent_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "agent-semantic-yield-nearby-pressure",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_agent",
                            "arguments": {"agent_id": "agent-a"},
                        },
                    }
                )

            self.assertIsNotNone(agent_result)
            assert agent_result is not None
            structured = agent_result["result"]["structuredContent"]
            self.assertEqual(structured["active_work"]["yield_alert"]["policy"], "yield")
            self.assertTrue(structured["active_work"]["yield_alert"]["acknowledged"])
            self.assertEqual(structured["active_work"]["yield_alert"]["confidence"], "medium")
            self.assertEqual(structured["next_action"]["tool"], "loom_finish")

    def test_status_tool_prefers_semantic_nearby_pressure_over_scope_proximity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.py").write_text(
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
                encoding="utf-8",
            )
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-semantic-priority",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            for tool_id, name, arguments in (
                (
                    "claim-semantic-priority",
                    "loom_claim",
                    {
                        "description": "Background API cleanup",
                        "scope": ["src/api/handlers.py"],
                        "lease_minutes": 30,
                        "lease_policy": "yield",
                    },
                ),
                (
                    "intent-semantic-priority",
                    "loom_intent",
                    {
                        "description": "Touch API handler response shape",
                        "scope": ["src/api/handlers.py"],
                        "lease_minutes": 30,
                        "lease_policy": "yield",
                    },
                ),
                (
                    "claim-semantic-nearby",
                    "loom_claim",
                    {
                        "agent_id": "agent-b",
                        "description": "Refactor auth session model",
                        "scope": ["src/auth/session.py"],
                    },
                ),
                (
                    "intent-scope-nearby",
                    "loom_intent",
                    {
                        "agent_id": "agent-c",
                        "description": "Touch broader API surface",
                        "scope": ["src/api"],
                    },
                ),
            ):
                result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": tool_id,
                        "method": "tools/call",
                        "params": {
                            "name": name,
                            "arguments": arguments,
                        },
                    }
                )
                self.assertIsNotNone(result)
                assert result is not None

            conflicts_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "conflicts-semantic-priority",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_conflicts",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(conflicts_result)
            assert conflicts_result is not None
            conflict_ids = [
                item["id"] for item in conflicts_result["result"]["structuredContent"]["conflicts"]
            ]
            self.assertTrue(conflict_ids)
            for index, conflict_id in enumerate(conflict_ids):
                resolve_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": f"resolve-semantic-priority-{index}",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_resolve",
                            "arguments": {
                                "conflict_id": conflict_id,
                                "note": "Nearby work acknowledged.",
                            },
                        },
                    }
                )
                self.assertIsNotNone(resolve_result)
                assert resolve_result is not None

            status_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "status-semantic-priority",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_status",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(status_result)
            assert status_result is not None
            structured = status_result["result"]["structuredContent"]
            self.assertEqual(structured["repo_lanes"]["acknowledged_migration_lanes"], 2)
            self.assertEqual(structured["repo_lanes"]["fresh_acknowledged_migration_lanes"], 2)
            self.assertEqual(structured["repo_lanes"]["ongoing_acknowledged_migration_lanes"], 0)
            self.assertEqual(structured["repo_lanes"]["acknowledged_migration_programs"], 2)
            self.assertEqual(structured["repo_lanes"]["fresh_acknowledged_migration_programs"], 2)
            self.assertEqual(structured["repo_lanes"]["ongoing_acknowledged_migration_programs"], 0)
            self.assertEqual(len(structured["repo_lanes"]["lanes"]), 2)
            self.assertEqual(len(structured["repo_lanes"]["programs"]), 2)
            lanes_by_relationship = {
                item["relationship"]: item
                for item in structured["repo_lanes"]["lanes"]
            }
            programs_by_hint = {
                item["scope_hint"]: item
                for item in structured["repo_lanes"]["programs"]
            }
            self.assertIn("dependency", lanes_by_relationship)
            self.assertIn("scope", lanes_by_relationship)
            self.assertEqual(
                sorted(lanes_by_relationship["dependency"]["scope"]),
                ["src/api/handlers.py", "src/auth/session.py"],
            )
            self.assertTrue(lanes_by_relationship["scope"]["scope"])
            self.assertIn(None, programs_by_hint)
            self.assertIn("src/api", programs_by_hint)
            self.assertEqual(programs_by_hint[None]["lane_count"], 1)
            self.assertEqual(structured["next_action"]["tool"], "loom_finish")
            self.assertEqual(structured["next_action"]["urgency"], "fresh")
            self.assertIn("fresh acknowledged nearby active work", structured["next_action"]["reason"])
            self.assertIn("semantically entangled", structured["next_action"]["reason"])

    def test_agent_tool_claim_without_intent_uses_shared_calm_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-agent-calm",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-agent-calm",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None

            agent_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "agent-calm",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_agent",
                        "arguments": {"agent_id": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(agent_result)
            assert agent_result is not None
            structured = agent_result["result"]["structuredContent"]
            self.assertEqual(
                structured["next_steps"],
                [
                    "Call loom_finish to publish an optional handoff and release current work.",
                    "Call loom_status to compare this agent with the rest of the repo.",
                ],
            )
            self.assertEqual(structured["next_action"]["tool"], "loom_finish")
            self.assertTrue(structured["active_work"]["completion_ready"])

    def test_mcp_surfaces_preserve_unicode_in_structured_json_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init-unicode",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None

            context_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "unicode-context-write",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_write",
                        "arguments": {
                            "topic": "über-topic",
                            "body": "Body <unsafe> café 設計",
                            "scope": ["src/über/設計 notes"],
                        },
                    },
                }
            )
            self.assertIsNotNone(context_result)
            assert context_result is not None
            self.assertFalse(context_result["result"]["isError"])
            content_text = context_result["result"]["content"][1]["text"]
            self.assertIn("über-topic", content_text)
            self.assertIn("café 設計", content_text)
            self.assertNotIn("\\u00fc", content_text)

            context_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "unicode-context-resource",
                    "method": "resources/read",
                    "params": {"uri": "loom://context"},
                }
            )
            self.assertIsNotNone(context_resource)
            assert context_resource is not None
            resource_text = context_resource["result"]["contents"][0]["text"]
            self.assertIn("über-topic", resource_text)
            self.assertIn("café 設計", resource_text)
            self.assertNotIn("\\u8a2d", resource_text)

    def test_client_cache_initializes_once_across_threads(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        project = object()
        created_clients: list[object] = []
        returned_clients: list[object] = []
        ready = threading.Event()

        def fake_client(candidate_project: object) -> object:
            self.assertIs(candidate_project, project)
            threading.Event().wait(0.02)
            client = object()
            created_clients.append(client)
            return client

        def worker(method_name: str) -> None:
            ready.wait(0.05)
            returned_clients.append(getattr(server, method_name)())

        with patch.object(server, "_maybe_load_project", return_value=project):
            with patch("loom.mcp.CoordinationClient", side_effect=fake_client):
                threads = [
                    threading.Thread(target=worker, args=("_client_for_tools",)),
                    threading.Thread(
                        target=worker,
                        args=("_maybe_client_for_project_resources",),
                    ),
                    threading.Thread(target=worker, args=("_client_for_tools",)),
                ]
                for thread in threads:
                    thread.start()
                ready.set()
                for thread in threads:
                    thread.join()

        self.assertEqual(len(created_clients), 1)
        self.assertEqual(len(returned_clients), 3)
        self.assertTrue(all(client is returned_clients[0] for client in returned_clients))

    def test_prompt_get_returns_coordination_workflow_text(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "prompt",
                "method": "prompts/get",
                "params": {
                    "name": "coordinate_before_edit",
                    "arguments": {
                        "task": "Refactor auth flow",
                        "scope": "src/auth",
                        "agent_id": "agent-a",
                    },
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        messages = response["result"]["messages"]
        self.assertEqual(len(messages), 1)
        prompt_text = messages[0]["content"]["text"]
        self.assertIn("Refactor auth flow", prompt_text)
        self.assertIn("src/auth", prompt_text)
        self.assertIn("agent-a", prompt_text)
        self.assertIn("loom://start", prompt_text)
        self.assertIn("loom_start", prompt_text)
        self.assertIn("loom_claim", prompt_text)
        self.assertIn("loom_protocol", prompt_text)

    def test_prompt_get_surfaces_invalid_authority_from_live_start_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "prompt-init-invalid-authority",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: missing\n"
                "      path: DOES_NOT_EXIST.md\n"
                "      role: root_truth\n",
                encoding="utf-8",
            )

            response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "prompt-invalid-authority",
                    "method": "prompts/get",
                    "params": {
                        "name": "coordinate_before_edit",
                        "arguments": {"task": "Refactor auth flow"},
                    },
                }
            )

            self.assertIsNotNone(response)
            assert response is not None
            prompt_text = response["result"]["messages"][0]["content"]["text"]
            self.assertIn("Declared authority: `loom.yaml` is currently invalid.", prompt_text)
            self.assertIn("missing file 'DOES_NOT_EXIST.md'", prompt_text)
            self.assertIn(
                "Treat fixing declared repository truth as the first coordination move",
                prompt_text,
            )

    def test_prompt_get_surfaces_changed_authority_from_live_start_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            server = LoomMcpServer(cwd=repo_root)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "prompt-init-authority-change",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)

            (repo_root / "loom.yaml").write_text(
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n",
                encoding="utf-8",
            )

            response = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "prompt-authority-change",
                    "method": "prompts/get",
                    "params": {
                        "name": "coordinate_before_edit",
                        "arguments": {"task": "Refactor auth flow"},
                    },
                }
            )

            self.assertIsNotNone(response)
            assert response is not None
            prompt_text = response["result"]["messages"][0]["content"]["text"]
            self.assertIn("Declared authority surfaces: PRODUCT.md", prompt_text)
            self.assertIn(
                "Declared authority changed recently; treat these surfaces as the first repo truth to coordinate: PRODUCT.md",
                prompt_text,
            )

    def test_prompt_get_returns_finish_and_release_guidance(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "prompt-finish",
                "method": "prompts/get",
                "params": {
                    "name": "finish_and_release",
                    "arguments": {
                        "agent_id": "agent-a",
                        "summary": "Completed auth refactor.",
                    },
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        prompt_text = response["result"]["messages"][0]["content"]["text"]
        self.assertIn("Completed auth refactor.", prompt_text)
        self.assertIn("loom://start", prompt_text)
        self.assertIn("loom_start", prompt_text)
        self.assertIn("loom://agent", prompt_text)
        self.assertIn("loom://inbox", prompt_text)
        self.assertIn("loom_unclaim", prompt_text)
        self.assertIn("loom_resolve", prompt_text)

    def test_prompt_get_returns_adapt_or_wait_guidance(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "prompt-adapt",
                "method": "prompts/get",
                "params": {
                    "name": "adapt_or_wait",
                    "arguments": {
                        "conflict_id": "conflict_01",
                        "agent_id": "agent-a",
                    },
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        prompt_text = response["result"]["messages"][0]["content"]["text"]
        self.assertIn("conflict_01", prompt_text)
        self.assertIn("agent-a", prompt_text)
        self.assertIn("loom://start", prompt_text)
        self.assertIn("loom_start", prompt_text)
        self.assertIn("loom://conflicts", prompt_text)
        self.assertIn("loom_timeline", prompt_text)
        self.assertIn("loom_resolve", prompt_text)

    def test_prompt_get_returns_handoff_guidance(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "prompt-handoff",
                "method": "prompts/get",
                "params": {
                    "name": "handoff_work",
                    "arguments": {
                        "task": "Finish auth middleware integration",
                        "scope": "src/auth",
                        "recipient_agent": "agent-b",
                    },
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        prompt_text = response["result"]["messages"][0]["content"]["text"]
        self.assertIn("Finish auth middleware integration", prompt_text)
        self.assertIn("src/auth", prompt_text)
        self.assertIn("agent-b", prompt_text)
        self.assertIn("loom://start", prompt_text)
        self.assertIn("loom_start", prompt_text)
        self.assertIn("loom_context_write", prompt_text)
        self.assertIn("loom_unclaim", prompt_text)
        self.assertIn("loom_timeline", prompt_text)

    def test_prompt_get_returns_triage_inbox_guidance(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "prompt-triage",
                "method": "prompts/get",
                "params": {
                    "name": "triage_inbox",
                    "arguments": {"agent_id": "agent-a"},
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        messages = response["result"]["messages"]
        self.assertEqual(len(messages), 1)
        prompt_text = messages[0]["content"]["text"]
        self.assertIn("agent-a", prompt_text)
        self.assertIn("loom://start", prompt_text)
        self.assertIn("loom_start", prompt_text)
        self.assertIn("loom://inbox", prompt_text)
        self.assertIn("loom_inbox", prompt_text)
        self.assertIn("loom_context_ack", prompt_text)
        self.assertIn("loom_resolve", prompt_text)

    def test_prompt_get_returns_resolve_conflict_guidance(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "prompt-resolve",
                "method": "prompts/get",
                "params": {
                    "name": "resolve_conflict",
                    "arguments": {"conflict_id": "conflict_01"},
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        messages = response["result"]["messages"]
        self.assertEqual(len(messages), 1)
        prompt_text = messages[0]["content"]["text"]
        self.assertIn("conflict_01", prompt_text)
        self.assertIn("loom://start", prompt_text)
        self.assertIn("loom_start", prompt_text)
        self.assertIn("loom_timeline", prompt_text)
        self.assertIn("loom_status", prompt_text)
        self.assertIn("loom_resolve", prompt_text)
        self.assertIn("loom_context_write", prompt_text)

    def test_prompt_get_rejects_invalid_arguments_as_invalid_params(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "prompt-invalid",
                "method": "prompts/get",
                "params": {
                    "name": "coordinate_before_edit",
                    "arguments": {
                        "task": "Refactor auth flow",
                        "unexpected": True,
                    },
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertEqual(response["error"]["code"], -32602)
        self.assertIn("Unexpected arguments", response["error"]["message"])

    def test_resource_read_returns_protocol_descriptor(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "resource-protocol",
                "method": "resources/read",
                "params": {"uri": "loom://protocol"},
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        contents = response["result"]["contents"]
        self.assertEqual(len(contents), 1)
        payload = json.loads(contents[0]["text"])
        self.assertEqual(payload["protocol"]["name"], "loom.local")
        self.assertIn("operation_schemas", payload["protocol"])

    def test_resource_read_returns_mcp_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            initialize = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            self.assertIsNotNone(initialize)

            initialized = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/initialized",
                }
            )
            self.assertIsNone(initialized)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None
            self.assertFalse(init_result["result"]["isError"])

            subscribe_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "subscribe-events",
                    "method": "resources/subscribe",
                    "params": {"uri": "loom://events/after/0"},
                }
            )
            self.assertIsNotNone(subscribe_result)
            assert subscribe_result is not None
            self.assertEqual(subscribe_result["result"], {})

            with server._state_lock:
                server._watch_state = "watching"
                server._watch_last_sequence = 7
                server._watch_last_error = None
                server._watch_thread = threading.current_thread()

            with patch.object(
                CoordinationClient,
                "daemon_status",
                return_value=DaemonStatus(running=False, detail="daemon not running"),
            ):
                response = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "resource-mcp",
                        "method": "resources/read",
                        "params": {"uri": "loom://mcp"},
                    }
                )

            self.assertIsNotNone(response)
            assert response is not None
            contents = response["result"]["contents"]
            self.assertEqual(len(contents), 1)
            payload = json.loads(contents[0]["text"])
            self.assertEqual(payload["mcp"]["protocol_version"], MCP_PROTOCOL_VERSION)
            self.assertTrue(payload["mcp"]["initialized"])
            self.assertEqual(payload["mcp"]["subscription_count"], 1)
            self.assertEqual(payload["mcp"]["subscriptions"], ["loom://events/after/0"])
            self.assertTrue(payload["mcp"]["watcher"]["active"])
            self.assertEqual(payload["mcp"]["watcher"]["state"], "watching")
            self.assertEqual(payload["mcp"]["watcher"]["last_sequence"], 7)
            self.assertEqual(payload["daemon"]["detail"], "daemon not running")
            self.assertEqual(payload["identity"]["id"], "agent-a")
            self.assertEqual(payload["links"]["protocol"], "loom://protocol")
            self.assertEqual(payload["links"]["start"], "loom://start")
            self.assertEqual(payload["links"]["status"], "loom://status")
            self.assertEqual(payload["links"]["context"], "loom://context")
            self.assertEqual(payload["links"]["current_agent"], "loom://agent/agent-a")

    def test_resource_subscriptions_emit_updates_and_respect_unsubscribe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )

            with patch.object(server, "_emit_notification") as emit_notification:
                init_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "tool-init",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_init",
                            "arguments": {"default_agent": "agent-a"},
                        },
                    }
                )

            self.assertIsNotNone(init_result)
            assert init_result is not None
            self.assertFalse(init_result["result"]["isError"])
            self.assertIn(
                "notifications/resources/list_changed",
                [call.args[0] for call in emit_notification.call_args_list],
            )

            for index, uri in enumerate(
                (
                    "loom://activity",
                    "loom://log",
                    "loom://context",
                    "loom://events/after/0",
                    "loom://conflicts",
                    "loom://conflicts/history",
                    "loom://inbox",
                    "loom://agent",
                    "loom://activity/agent-a/after/0",
                    "loom://activity/agent-b/after/0",
                ),
                start=1,
            ):
                subscribe_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": f"subscribe-{index}",
                        "method": "resources/subscribe",
                        "params": {"uri": uri},
                    }
                )
                self.assertIsNotNone(subscribe_result)
                assert subscribe_result is not None
                self.assertEqual(subscribe_result["result"], {})

            unsubscribe_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "unsubscribe-agent",
                    "method": "resources/unsubscribe",
                    "params": {"uri": "loom://agent"},
                }
            )
            self.assertIsNotNone(unsubscribe_result)
            assert unsubscribe_result is not None
            self.assertEqual(unsubscribe_result["result"], {})

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-a",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None
            self.assertFalse(claim_result["result"]["isError"])
            claim_id = claim_result["result"]["structuredContent"]["claim"]["id"]

            subscribe_timeline = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "subscribe-timeline",
                    "method": "resources/subscribe",
                    "params": {"uri": f"loom://timeline/{claim_id}"},
                }
            )
            self.assertIsNotNone(subscribe_timeline)
            assert subscribe_timeline is not None
            self.assertEqual(subscribe_timeline["result"], {})

            subscribe_claim = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "subscribe-claim",
                    "method": "resources/subscribe",
                    "params": {"uri": f"loom://claim/{claim_id}"},
                }
            )
            self.assertIsNotNone(subscribe_claim)
            assert subscribe_claim is not None
            self.assertEqual(subscribe_claim["result"], {})

            context_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "context-a",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_write",
                        "arguments": {
                            "topic": "auth-interface",
                            "body": "Refresh token required.",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(context_result)
            assert context_result is not None
            self.assertFalse(context_result["result"]["isError"])
            context_id = context_result["result"]["structuredContent"]["context"]["id"]

            subscribe_context = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "subscribe-context",
                    "method": "resources/subscribe",
                    "params": {"uri": f"loom://context/{context_id}"},
                }
            )
            self.assertIsNotNone(subscribe_context)
            assert subscribe_context is not None
            self.assertEqual(subscribe_context["result"], {})

            subscribe_context_timeline = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "subscribe-context-timeline",
                    "method": "resources/subscribe",
                    "params": {"uri": f"loom://context/{context_id}/timeline"},
                }
            )
            self.assertIsNotNone(subscribe_context_timeline)
            assert subscribe_context_timeline is not None
            self.assertEqual(subscribe_context_timeline["result"], {})

            for index, uri in enumerate(
                (
                    "loom://agent/agent-b",
                    "loom://inbox/agent-b",
                    "loom://activity/agent-b",
                    "loom://agent/agent-a",
                    "loom://inbox/agent-a",
                    "loom://activity/agent-a",
                ),
                start=1,
            ):
                subscribe_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": f"subscribe-agent-b-{index}",
                        "method": "resources/subscribe",
                        "params": {"uri": uri},
                    }
                )
                self.assertIsNotNone(subscribe_result)
                assert subscribe_result is not None
                self.assertEqual(subscribe_result["result"], {})

            with patch.object(server, "_emit_notification") as emit_notification:
                intent_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "intent-b",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_intent",
                            "arguments": {
                                "agent_id": "agent-b",
                                "description": "Touch auth middleware",
                                "scope": ["src/auth"],
                            },
                        },
                    }
                )
                self.assertIsNotNone(intent_result)
                assert intent_result is not None
                self.assertFalse(intent_result["result"]["isError"])
                conflict_id = intent_result["result"]["structuredContent"]["conflicts"][0]["id"]

                subscribe_conflict = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "subscribe-conflict",
                        "method": "resources/subscribe",
                        "params": {"uri": f"loom://conflict/{conflict_id}"},
                    }
                )
                self.assertIsNotNone(subscribe_conflict)
                assert subscribe_conflict is not None
                self.assertEqual(subscribe_conflict["result"], {})

                subscribe_conflict_timeline = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "subscribe-conflict-timeline",
                        "method": "resources/subscribe",
                        "params": {"uri": f"loom://conflict/{conflict_id}/timeline"},
                    }
                )
                self.assertIsNotNone(subscribe_conflict_timeline)
                assert subscribe_conflict_timeline is not None
                self.assertEqual(subscribe_conflict_timeline["result"], {})

                ack_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "context-ack",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_context_ack",
                            "arguments": {
                                "context_id": context_id,
                                "agent_id": "agent-b",
                                "status": "adapted",
                                "note": "Adjusted middleware plan.",
                            },
                        },
                    }
                )
                self.assertIsNotNone(ack_result)
                assert ack_result is not None
                self.assertFalse(ack_result["result"]["isError"])

                resolve_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "resolve",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_resolve",
                            "arguments": {
                                "conflict_id": conflict_id,
                                "resolution_note": "Coordinated around overlap.",
                            },
                        },
                    }
                )
                self.assertIsNotNone(resolve_result)
                assert resolve_result is not None
                self.assertFalse(resolve_result["result"]["isError"])

            updated_uris = {
                call.args[1]["uri"]
                for call in emit_notification.call_args_list
                if call.args[0] == "notifications/resources/updated"
            }
            self.assertIn("loom://activity", updated_uris)
            self.assertIn("loom://log", updated_uris)
            self.assertIn("loom://context", updated_uris)
            self.assertIn("loom://events/after/0", updated_uris)
            self.assertIn("loom://conflicts", updated_uris)
            self.assertIn("loom://conflicts/history", updated_uris)
            self.assertIn(f"loom://claim/{claim_id}", updated_uris)
            self.assertIn(f"loom://context/{context_id}/timeline", updated_uris)
            self.assertIn(f"loom://conflict/{conflict_id}", updated_uris)
            self.assertIn(f"loom://conflict/{conflict_id}/timeline", updated_uris)
            self.assertIn("loom://inbox", updated_uris)
            self.assertIn("loom://agent/agent-a", updated_uris)
            self.assertIn("loom://inbox/agent-a", updated_uris)
            self.assertIn("loom://activity/agent-a", updated_uris)
            self.assertIn("loom://activity/agent-a/after/0", updated_uris)
            self.assertIn("loom://agent/agent-b", updated_uris)
            self.assertIn("loom://inbox/agent-b", updated_uris)
            self.assertIn("loom://activity/agent-b", updated_uris)
            self.assertIn("loom://activity/agent-b/after/0", updated_uris)
            self.assertIn(f"loom://timeline/{claim_id}", updated_uris)
            self.assertNotIn("loom://agent", updated_uris)
            self.assertNotIn(
                "notifications/resources/list_changed",
                [call.args[0] for call in emit_notification.call_args_list],
            )

    def test_subscribe_claim_resource_does_not_force_resource_read(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            initialize = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            self.assertIsNotNone(initialize)

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None
            self.assertFalse(init_result["result"]["isError"])

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-a",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None
            self.assertFalse(claim_result["result"]["isError"])
            claim_id = claim_result["result"]["structuredContent"]["claim"]["id"]

            with patch.object(
                server,
                "_read_claim_resource",
                side_effect=AssertionError("subscribe should not read claim resource"),
            ):
                subscribe_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "subscribe-claim",
                        "method": "resources/subscribe",
                        "params": {"uri": f"loom://claim/{claim_id}"},
                    }
                )

            self.assertIsNotNone(subscribe_result)
            assert subscribe_result is not None
            self.assertEqual(subscribe_result["result"], {})

    def test_unsubscribe_last_resource_stops_background_watch(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
            }
        )
        server._resource_subscriptions = {"loom://events/after/0"}

        with patch.object(server, "_stop_background_watch") as stop_watch:
            result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "unsubscribe-last",
                    "method": "resources/unsubscribe",
                    "params": {"uri": "loom://events/after/0"},
                }
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["result"], {})
        stop_watch.assert_called_once()
        self.assertEqual(server._resource_subscriptions, set())

    def test_unsubscribe_with_remaining_resources_keeps_background_watch_running(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
            }
        )
        server._resource_subscriptions = {"loom://events/after/0", "loom://mcp"}

        with patch.object(server, "_stop_background_watch") as stop_watch:
            result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "unsubscribe-one",
                    "method": "resources/unsubscribe",
                    "params": {"uri": "loom://events/after/0"},
                }
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["result"], {})
        stop_watch.assert_not_called()
        self.assertEqual(server._resource_subscriptions, {"loom://mcp"})

    def _make_repo_with_branch(
        self,
        repo_root: pathlib.Path,
        *,
        branch: str = "feature/mcp-bridge",
    ) -> None:
        (repo_root / ".git").mkdir()
        (repo_root / ".git" / "HEAD").write_text(
            f"ref: refs/heads/{branch}\n",
            encoding="utf-8",
        )

    def _initialize_mcp_server(self, repo_root: pathlib.Path) -> LoomMcpServer:
        server = LoomMcpServer(cwd=repo_root)
        self.addCleanup(server.close)
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
            }
        )
        self.assertIsNotNone(response)
        return server

    def _call_tool(
        self,
        server: LoomMcpServer,
        *,
        request_id: str,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {
                    "name": name,
                    "arguments": {} if arguments is None else arguments,
                },
            }
        )
        self.assertIsNotNone(response)
        assert response is not None
        return response

    def _read_resource_payload(
        self,
        server: LoomMcpServer,
        *,
        request_id: str,
        uri: str,
    ) -> dict[str, object]:
        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "resources/read",
                "params": {"uri": uri},
            }
        )
        self.assertIsNotNone(response)
        assert response is not None
        return json.loads(response["result"]["contents"][0]["text"])

    def _bootstrap_claimed_server(
        self,
        repo_root: pathlib.Path,
    ) -> tuple[LoomMcpServer, dict[str, object], dict[str, object], dict[str, object]]:
        self._make_repo_with_branch(repo_root)
        server = self._initialize_mcp_server(repo_root)
        init_result = self._call_tool(
            server,
            request_id="tool-init",
            name="loom_init",
            arguments={"default_agent": "agent-a"},
        )
        self.assertFalse(init_result["result"]["isError"])
        claim_result = self._call_tool(
            server,
            request_id="tool-claim",
            name="loom_claim",
            arguments={
                "agent_id": "agent-a",
                "description": "Refactor auth flow",
                "scope": ["src/auth"],
                "lease_minutes": 30,
                "lease_policy": "renew",
            },
        )
        self.assertFalse(claim_result["result"]["isError"])
        renew_result = self._call_tool(
            server,
            request_id="tool-renew",
            name="loom_renew",
            arguments={
                "agent_id": "agent-a",
                "lease_minutes": 90,
            },
        )
        self.assertFalse(renew_result["result"]["isError"])
        return (
            server,
            init_result["result"]["structuredContent"],
            claim_result["result"]["structuredContent"],
            renew_result["result"]["structuredContent"],
        )

    def _bootstrap_conflict_server(
        self,
        repo_root: pathlib.Path,
    ) -> tuple[LoomMcpServer, dict[str, object], dict[str, object], str]:
        self._make_repo_with_branch(repo_root)
        server = self._initialize_mcp_server(repo_root)
        init_result = self._call_tool(
            server,
            request_id="conflict-tool-init",
            name="loom_init",
            arguments={"default_agent": "agent-a"},
        )
        self.assertFalse(init_result["result"]["isError"])
        claim_result = self._call_tool(
            server,
            request_id="conflict-claim-a",
            name="loom_claim",
            arguments={
                "description": "Refactor auth flow",
                "scope": ["src/auth"],
            },
        )
        self.assertFalse(claim_result["result"]["isError"])
        intent_result = self._call_tool(
            server,
            request_id="conflict-intent-b",
            name="loom_intent",
            arguments={
                "agent_id": "agent-b",
                "description": "Touch auth middleware",
                "scope": ["src/auth"],
            },
        )
        self.assertFalse(intent_result["result"]["isError"])
        conflicts = intent_result["result"]["structuredContent"]["conflicts"]
        self.assertEqual(len(conflicts), 1)
        conflict_id = conflicts[0]["id"]
        return (
            server,
            claim_result["result"]["structuredContent"],
            intent_result["result"]["structuredContent"],
            conflict_id,
        )

    def test_mcp_bootstrap_claim_and_status_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            self._make_repo_with_branch(repo_root)
            server = self._initialize_mcp_server(repo_root)

            status_before_init = self._call_tool(
                server,
                request_id="status-before",
                name="loom_status",
            )
            self.assertTrue(status_before_init["result"]["isError"])
            self.assertFalse(status_before_init["result"]["structuredContent"]["ok"])
            self.assertEqual(
                status_before_init["result"]["structuredContent"]["next_tool"],
                "loom_init",
            )
            self.assertIn(
                "Call loom_init to initialize Loom in this repository.",
                status_before_init["result"]["structuredContent"]["next_steps"],
            )

            init_structured = self._call_tool(
                server,
                request_id="tool-init",
                name="loom_init",
                arguments={"default_agent": "agent-a"},
            )["result"]["structuredContent"]
            self.assertTrue(init_structured["ok"])
            self.assertTrue(init_structured["created"])
            self.assertIn(
                "Call loom_start to ask Loom what to do next in this repository.",
                init_structured["next_steps"],
            )
            self.assertIn(
                'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
                init_structured["next_steps"],
            )

            claim_result = self._call_tool(
                server,
                request_id="tool-claim",
                name="loom_claim",
                arguments={
                    "agent_id": "agent-a",
                    "description": "Refactor auth flow",
                    "scope": ["src/auth"],
                    "lease_minutes": 30,
                    "lease_policy": "renew",
                },
            )
            self.assertFalse(claim_result["result"]["isError"])
            claim_structured = claim_result["result"]["structuredContent"]
            self.assertTrue(claim_structured["ok"])
            self.assertEqual(
                claim_structured["claim"]["git_branch"],
                "feature/mcp-bridge",
            )
            self.assertIsNotNone(claim_structured["claim"]["lease_expires_at"])
            self.assertEqual(claim_structured["claim"]["lease_policy"], "renew")
            self.assertEqual(claim_structured["project"]["default_agent"], "agent-a")
            self.assertEqual(claim_structured["identity"]["id"], "agent-a")
            self.assertEqual(
                claim_structured["links"]["claim"],
                f"loom://claim/{claim_structured['claim']['id']}",
            )
            self.assertEqual(
                claim_structured["links"]["claim_timeline"],
                f"loom://claim/{claim_structured['claim']['id']}/timeline",
            )
            self.assertIn(
                "Call loom_status to confirm the updated coordination state.",
                claim_structured["next_steps"],
            )
            self.assertEqual(
                json.loads(claim_result["result"]["content"][1]["text"]),
                claim_structured,
            )

            renew_structured = self._call_tool(
                server,
                request_id="tool-renew",
                name="loom_renew",
                arguments={"agent_id": "agent-a", "lease_minutes": 90},
            )["result"]["structuredContent"]
            self.assertEqual(renew_structured["lease_minutes"], 90)
            self.assertIsNotNone(renew_structured["claim"])
            self.assertIsNone(renew_structured["intent"])
            self.assertEqual(
                renew_structured["next_steps"][0],
                "Call loom_agent for a focused agent view.",
            )

            status_structured = self._call_tool(
                server,
                request_id="tool-status",
                name="loom_status",
            )["result"]["structuredContent"]
            self.assertEqual(
                status_structured["status"]["claims"][0]["lease_expires_at"],
                renew_structured["claim"]["lease_expires_at"],
            )
            self.assertEqual(status_structured["project"]["default_agent"], "agent-a")
            self.assertEqual(status_structured["identity"]["id"], "agent-a")
            self.assertFalse(status_structured["mcp"]["initialized"])
            self.assertEqual(status_structured["mcp"]["subscription_count"], 0)
            self.assertEqual(status_structured["mcp"]["watcher"]["state"], "idle")
            self.assertEqual(status_structured["links"]["start"], "loom://start")
            self.assertEqual(status_structured["next_action"]["tool"], "loom_agent")
            self.assertEqual(
                status_structured["next_action"]["arguments"],
                {"agent_id": "agent-a"},
            )
            self.assertEqual(status_structured["next_action"]["confidence"], "medium")
            self.assertEqual(status_structured["links"]["agent"], "loom://agent/agent-a")
            self.assertEqual(
                status_structured["links"]["claims"],
                [f"loom://claim/{status_structured['status']['claims'][0]['id']}"],
            )
            self.assertIn(
                "Call loom_agent for a focused agent view.",
                status_structured["next_steps"],
            )

            agents_structured = self._call_tool(
                server,
                request_id="tool-agents",
                name="loom_agents",
                arguments={"limit": 5},
            )["result"]["structuredContent"]
            self.assertTrue(agents_structured["identity"]["project_initialized"])
            self.assertEqual(agents_structured["project"]["default_agent"], "agent-a")
            self.assertEqual(agents_structured["agents"][0]["agent_id"], "agent-a")
            self.assertEqual(
                agents_structured["agents"][0]["claim"]["git_branch"],
                "feature/mcp-bridge",
            )
            self.assertFalse(agents_structured["mcp"]["initialized"])
            self.assertEqual(agents_structured["mcp"]["subscription_count"], 0)
            self.assertEqual(agents_structured["mcp"]["watcher"]["state"], "idle")
            self.assertEqual(agents_structured["links"]["start"], "loom://start")
            self.assertEqual(agents_structured["links"]["items"], ["loom://agent/agent-a"])
            self.assertFalse(agents_structured["showing_idle_history"])
            self.assertEqual(agents_structured["idle_history_hidden_count"], 0)
            self.assertIn(
                "Call loom_agent for one agent's focused view.",
                agents_structured["next_steps"],
            )

    def test_agents_tool_hides_idle_history_by_default_and_can_include_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            self._call_tool(
                server,
                request_id="tool-init-agents-hide-idle",
                name="loom_init",
                arguments={"default_agent": "agent-a"},
            )
            self._call_tool(
                server,
                request_id="tool-claim-agent-a",
                name="loom_claim",
                arguments={
                    "description": "Active auth work",
                    "scope": ["src/auth"],
                },
            )
            self._call_tool(
                server,
                request_id="tool-claim-agent-b",
                name="loom_claim",
                arguments={
                    "agent_id": "agent-b",
                    "description": "Idle cleanup work",
                    "scope": ["src/ops"],
                },
            )
            self._call_tool(
                server,
                request_id="tool-finish-agent-b",
                name="loom_finish",
                arguments={
                    "agent_id": "agent-b",
                    "keep_idle": True,
                    "summary": "Finished ops cleanup.",
                },
            )

            hidden_payload = self._call_tool(
                server,
                request_id="tool-agents-hide-idle",
                name="loom_agents",
                arguments={},
            )["result"]["structuredContent"]
            self.assertEqual([entry["agent_id"] for entry in hidden_payload["agents"]], ["agent-a"])
            self.assertFalse(hidden_payload["showing_idle_history"])
            self.assertEqual(hidden_payload["idle_history_hidden_count"], 1)
            self.assertEqual(
                hidden_payload["next_steps"][0],
                "Call loom_agents with include_idle=true to inspect idle agent history.",
            )

            full_payload = self._call_tool(
                server,
                request_id="tool-agents-include-idle",
                name="loom_agents",
                arguments={"include_idle": True},
            )["result"]["structuredContent"]
            self.assertTrue(full_payload["showing_idle_history"])
            self.assertEqual(full_payload["idle_history_hidden_count"], 0)
            self.assertEqual(
                sorted(entry["agent_id"] for entry in full_payload["agents"]),
                ["agent-a", "agent-b"],
            )

    def test_mcp_activity_resources_follow_claim_lifecycle_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            server, _init_structured, claim_structured, renew_structured = (
                self._bootstrap_claimed_server(repo_root)
            )
            claim = claim_structured["claim"]

            log_payload = self._read_resource_payload(
                server,
                request_id="resource-log-smoke",
                uri="loom://log",
            )
            self.assertEqual(log_payload["events"][0]["type"], "claim.renewed")
            self.assertEqual(log_payload["links"]["status"], "loom://status")
            self.assertIn(
                f"loom://claim/{claim['id']}",
                log_payload["events"][0]["links"]["objects"],
            )
            self.assertIn(log_payload["events"][0]["resource_uri"], log_payload["links"]["events"])

            events_after_payload = self._read_resource_payload(
                server,
                request_id="resource-events-after-smoke",
                uri="loom://events/after/0",
            )
            self.assertEqual(events_after_payload["after_sequence"], 0)
            self.assertEqual(events_after_payload["events"][0]["type"], "claim.recorded")
            self.assertEqual(
                events_after_payload["links"]["resume"],
                f"loom://events/after/{events_after_payload['resume_after_sequence']}",
            )

            activity_payload = self._read_resource_payload(
                server,
                request_id="resource-activity-smoke",
                uri="loom://activity",
            )
            self.assertEqual(activity_payload["agent"]["claim_id"], claim["id"])
            self.assertEqual(activity_payload["links"]["claim"], f"loom://claim/{claim['id']}")
            self.assertEqual(activity_payload["links"]["feed"], "loom://activity/agent-a/after/2")
            self.assertEqual(activity_payload["events"][0]["type"], "claim.recorded")

            event_payload = self._read_resource_payload(
                server,
                request_id="resource-event-smoke",
                uri=log_payload["events"][0]["resource_uri"],
            )
            self.assertEqual(event_payload["event"]["type"], "claim.renewed")
            self.assertEqual(event_payload["event"]["actor_id"], "agent-a")
            self.assertEqual(event_payload["links"]["log"], "loom://log")

            activity_feed_payload = self._read_resource_payload(
                server,
                request_id="resource-activity-feed-smoke",
                uri="loom://activity/agent-a/after/0",
            )
            self.assertEqual(activity_feed_payload["agent_id"], "agent-a")
            self.assertEqual(activity_feed_payload["events"][0]["type"], "claim.recorded")
            self.assertEqual(
                activity_feed_payload["links"]["resume"],
                "loom://activity/agent-a/after/2",
            )

            claim_payload = self._read_resource_payload(
                server,
                request_id="resource-claim-smoke",
                uri=f"loom://claim/{claim['id']}",
            )
            self.assertEqual(claim_payload["claim"]["id"], claim["id"])
            self.assertEqual(
                claim_payload["claim"]["lease_expires_at"],
                renew_structured["claim"]["lease_expires_at"],
            )
            self.assertEqual(
                claim_payload["timeline_uri"],
                f"loom://claim/{claim['id']}/timeline",
            )
            self.assertEqual(claim_payload["links"]["activity"], "loom://activity/agent-a")
            self.assertEqual(claim_payload["related_conflicts"], [])

            agent_payload = self._read_resource_payload(
                server,
                request_id="resource-agent-template-smoke",
                uri="loom://agent/agent-a",
            )
            self.assertEqual(agent_payload["agent"]["agent_id"], "agent-a")
            self.assertEqual(agent_payload["agent"]["claim"]["id"], claim["id"])
            self.assertEqual(agent_payload["links"]["claim"], f"loom://claim/{claim['id']}")
            self.assertTrue(agent_payload["active_work"]["completion_ready"])

            inbox_payload = self._read_resource_payload(
                server,
                request_id="resource-inbox-template-smoke",
                uri="loom://inbox/agent-a",
            )
            self.assertEqual(inbox_payload["inbox"]["agent_id"], "agent-a")
            self.assertEqual(inbox_payload["links"]["activity"], "loom://activity/agent-a")

            activity_template_payload = self._read_resource_payload(
                server,
                request_id="resource-activity-template-smoke",
                uri="loom://activity/agent-a",
            )
            self.assertEqual(activity_template_payload["agent"]["id"], "agent-a")
            self.assertEqual(activity_template_payload["agent"]["claim_id"], claim["id"])
            self.assertEqual(
                activity_template_payload["links"]["claim"],
                f"loom://claim/{claim['id']}",
            )

    def test_mcp_expired_lease_status_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            server, _init_structured, _claim_structured, _renew_structured = (
                self._bootstrap_claimed_server(repo_root)
            )

            with patch("loom.guidance.is_past_utc_timestamp", return_value=True), patch(
                "loom.mcp.is_past_utc_timestamp",
                return_value=True,
            ), patch(
                "loom.mcp_support.is_past_utc_timestamp",
                return_value=True,
            ):
                expired_status_structured = self._call_tool(
                    server,
                    request_id="tool-status-expired-smoke",
                    name="loom_status",
                )["result"]["structuredContent"]

            self.assertEqual(expired_status_structured["next_action"]["tool"], "loom_renew")
            self.assertEqual(
                expired_status_structured["next_steps"][0],
                "Call loom_renew to extend the current coordination lease.",
            )

    def test_mcp_context_intent_and_repo_resources_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            server, _init_structured, claim_structured, _renew_structured = (
                self._bootstrap_claimed_server(repo_root)
            )
            claim = claim_structured["claim"]

            context_structured = self._call_tool(
                server,
                request_id="resource-context-source-smoke",
                name="loom_context_write",
                arguments={
                    "topic": "auth-interface",
                    "body": "Refresh token required.",
                    "scope": ["src/auth"],
                },
            )["result"]["structuredContent"]
            context_id = context_structured["context"]["id"]

            context_payload = self._read_resource_payload(
                server,
                request_id="resource-context-template-smoke",
                uri=f"loom://context/{context_id}",
            )
            self.assertEqual(context_payload["context"]["id"], context_id)
            self.assertEqual(context_payload["context"]["topic"], "auth-interface")
            self.assertEqual(
                context_payload["timeline_uri"],
                f"loom://context/{context_id}/timeline",
            )
            self.assertEqual(context_payload["links"]["start"], "loom://start")
            self.assertEqual(context_payload["links"]["agent"], "loom://agent/agent-a")
            self.assertEqual(
                context_payload["links"]["related_claim"],
                f"loom://claim/{claim['id']}",
            )

            context_timeline_alias_payload = self._read_resource_payload(
                server,
                request_id="resource-context-timeline-alias-smoke",
                uri=f"loom://context/{context_id}/timeline",
            )
            self.assertEqual(context_timeline_alias_payload["links"]["start"], "loom://start")
            self.assertEqual(context_timeline_alias_payload["object_type"], "context")
            self.assertEqual(context_timeline_alias_payload["object_id"], context_id)

            status_payload = self._read_resource_payload(
                server,
                request_id="resource-status-smoke",
                uri="loom://status",
            )
            self.assertEqual(status_payload["status"]["claims"][0]["git_branch"], "feature/mcp-bridge")
            self.assertEqual(status_payload["next_action"]["tool"], "loom_inbox")
            self.assertEqual(
                status_payload["next_action"]["arguments"],
                {"agent_id": "agent-a"},
            )
            self.assertIn(
                "Call loom_inbox for the affected agent.",
                status_payload["next_steps"],
            )
            self.assertEqual(status_payload["links"]["current_agent"], "loom://agent/agent-a")
            self.assertEqual(status_payload["links"]["context_feed"], "loom://context")
            self.assertIn(f"loom://claim/{claim['id']}", status_payload["links"]["claims"])

            agents_payload = self._read_resource_payload(
                server,
                request_id="resource-agents-smoke",
                uri="loom://agents",
            )
            self.assertEqual(agents_payload["agents"][0]["agent_id"], "agent-a")
            self.assertEqual(
                agents_payload["next_steps"],
                [
                    "Call loom_agent for one agent's focused view.",
                    "Call loom_inbox for pending coordination work.",
                    "Call loom_status to compare the full repo state.",
                ],
            )
            self.assertEqual(agents_payload["links"]["current_agent"], "loom://agent/agent-a")

            context_feed_payload = self._read_resource_payload(
                server,
                request_id="resource-context-feed-smoke",
                uri="loom://context",
            )
            self.assertEqual(context_feed_payload["context"][0]["id"], context_id)
            self.assertEqual(context_feed_payload["links"]["status"], "loom://status")
            self.assertEqual(
                context_feed_payload["links"]["items"],
                [f"loom://context/{context_id}"],
            )
            self.assertIn("loom://agent/agent-a", context_feed_payload["links"]["authors"])
            self.assertEqual(
                context_feed_payload["links"]["related_claims"],
                [f"loom://claim/{claim['id']}"],
            )

            agent_payload = self._read_resource_payload(
                server,
                request_id="resource-agent-smoke",
                uri="loom://agent",
            )
            self.assertTrue(agent_payload["identity"]["project_initialized"])
            self.assertEqual(agent_payload["identity"]["id"], "agent-a")
            self.assertEqual(agent_payload["next_action"]["tool"], "loom_finish")
            self.assertEqual(
                agent_payload["next_steps"],
                [
                    "Call loom_finish to publish an optional handoff and release current work.",
                    "Call loom_status to compare this agent with the rest of the repo.",
                ],
            )
            self.assertEqual(agent_payload["links"]["activity"], "loom://activity/agent-a")

            inbox_payload = self._read_resource_payload(
                server,
                request_id="resource-inbox-smoke",
                uri="loom://inbox",
            )
            self.assertEqual(inbox_payload["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                inbox_payload["next_steps"],
                [
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
                    "Call loom_status to confirm the current coordination state.",
                ],
            )
            self.assertEqual(inbox_payload["links"]["agent"], "loom://agent/agent-a")
            self.assertEqual(inbox_payload["links"]["context_feed"], "loom://context")

            conflicts_payload = self._read_resource_payload(
                server,
                request_id="resource-conflicts-smoke",
                uri="loom://conflicts",
            )
            self.assertEqual(conflicts_payload["next_action"]["tool"], "loom_claim")
            self.assertEqual(
                conflicts_payload["next_steps"],
                [
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
                    "Call loom_status to confirm the current coordination state.",
                ],
            )
            self.assertEqual(conflicts_payload["links"]["history"], "loom://conflicts/history")

            intent_structured = self._call_tool(
                server,
                request_id="resource-intent-source-smoke",
                name="loom_intent",
                arguments={
                    "description": "Touch auth middleware",
                    "scope": ["src/auth/middleware"],
                },
            )["result"]["structuredContent"]
            intent_id = intent_structured["intent"]["id"]

            intent_payload = self._read_resource_payload(
                server,
                request_id="resource-intent-template-smoke",
                uri=f"loom://intent/{intent_id}",
            )
            self.assertEqual(intent_payload["intent"]["id"], intent_id)
            self.assertEqual(
                intent_payload["timeline_uri"],
                f"loom://intent/{intent_id}/timeline",
            )
            self.assertEqual(intent_payload["links"]["start"], "loom://start")
            self.assertEqual(intent_payload["links"]["agent"], "loom://agent/agent-a")
            self.assertEqual(
                intent_payload["links"]["related_claim"],
                f"loom://claim/{claim['id']}",
            )

            conflicts_history_payload = self._read_resource_payload(
                server,
                request_id="resource-conflicts-history-smoke",
                uri="loom://conflicts/history",
            )
            self.assertIn("identity", conflicts_history_payload)
            self.assertIn("conflicts", conflicts_history_payload)
            self.assertEqual(conflicts_history_payload["links"]["active"], "loom://conflicts")
            self.assertEqual(conflicts_history_payload["links"]["items"], [])

            timeline_payload = self._read_resource_payload(
                server,
                request_id="resource-timeline-smoke",
                uri=f"loom://timeline/{claim['id']}",
            )
            self.assertEqual(timeline_payload["links"]["start"], "loom://start")
            self.assertEqual(timeline_payload["object_type"], "claim")
            self.assertEqual(timeline_payload["target"]["id"], claim["id"])
            self.assertEqual(
                timeline_payload["events"][0]["resource_uri"],
                f"loom://event/{timeline_payload['events'][0]['sequence']}",
            )

    def test_mcp_conflict_resolution_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            server, claim_structured, intent_structured, conflict_id = (
                self._bootstrap_conflict_server(repo_root)
            )
            self.assertEqual(claim_structured["claim"]["agent_id"], "agent-a")
            self.assertEqual(intent_structured["conflicts"][0]["kind"], "scope_overlap")
            self.assertEqual(
                intent_structured["links"]["intent"],
                f"loom://intent/{intent_structured['intent']['id']}",
            )
            self.assertEqual(
                intent_structured["links"]["conflicts_for_intent"],
                [f"loom://conflict/{conflict_id}"],
            )
            self.assertIn(
                "Call loom_conflicts to inspect the overlap.",
                intent_structured["next_steps"],
            )

            conflicts_structured = self._call_tool(
                server,
                request_id="smoke-conflicts",
                name="loom_conflicts",
            )["result"]["structuredContent"]
            self.assertEqual(len(conflicts_structured["conflicts"]), 1)
            self.assertEqual(conflicts_structured["conflicts"][0]["id"], conflict_id)
            self.assertEqual(conflicts_structured["project"]["default_agent"], "agent-a")
            self.assertEqual(conflicts_structured["identity"]["id"], "agent-a")
            self.assertFalse(conflicts_structured["mcp"]["initialized"])
            self.assertEqual(conflicts_structured["mcp"]["watcher"]["state"], "idle")
            self.assertEqual(conflicts_structured["links"]["start"], "loom://start")
            self.assertEqual(
                conflicts_structured["links"]["items"],
                [f"loom://conflict/{conflict_id}"],
            )
            self.assertEqual(conflicts_structured["next_action"]["tool"], "loom_resolve")
            self.assertEqual(
                conflicts_structured["next_action"]["arguments"],
                {"conflict_id": conflict_id},
            )
            self.assertEqual(conflicts_structured["next_action"]["confidence"], "high")
            self.assertIn(
                "Call loom_inbox for the affected agent.",
                conflicts_structured["next_steps"],
            )

            agent_structured = self._call_tool(
                server,
                request_id="smoke-agent",
                name="loom_agent",
                arguments={"agent_id": "agent-a", "context_limit": 5, "event_limit": 10},
            )["result"]["structuredContent"]
            self.assertEqual(agent_structured["agent"]["conflicts"][0]["id"], conflict_id)
            self.assertEqual(agent_structured["project"]["default_agent"], "agent-a")
            self.assertEqual(agent_structured["identity"]["id"], "agent-a")
            self.assertFalse(agent_structured["mcp"]["initialized"])
            self.assertEqual(agent_structured["mcp"]["watcher"]["state"], "idle")
            self.assertEqual(agent_structured["links"]["agent"], "loom://agent/agent-a")
            self.assertEqual(agent_structured["next_action"]["tool"], "loom_resolve")
            self.assertEqual(
                agent_structured["next_action"]["arguments"],
                {"conflict_id": conflict_id},
            )
            self.assertEqual(agent_structured["next_action"]["confidence"], "high")
            self.assertEqual(
                agent_structured["next_action"]["reason"],
                "Loom found an active conflict touching the current work.",
            )
            self.assertEqual(
                agent_structured["links"]["claim"],
                f"loom://claim/{claim_structured['claim']['id']}",
            )
            self.assertEqual(
                agent_structured["links"]["conflicts"],
                [f"loom://conflict/{conflict_id}"],
            )
            self.assertEqual(
                agent_structured["active_work"]["conflicts"][0]["id"],
                conflict_id,
            )
            self.assertFalse(agent_structured["worktree"]["has_drift"])
            self.assertEqual(
                agent_structured["next_steps"][0],
                f'Call loom_resolve with conflict_id="{conflict_id}" and note="<resolution>".',
            )

            inbox_structured = self._call_tool(
                server,
                request_id="smoke-inbox",
                name="loom_inbox",
                arguments={"agent_id": "agent-a", "context_limit": 5, "event_limit": 10},
            )["result"]["structuredContent"]
            self.assertEqual(inbox_structured["inbox"]["conflicts"][0]["id"], conflict_id)
            self.assertEqual(inbox_structured["project"]["default_agent"], "agent-a")
            self.assertEqual(inbox_structured["identity"]["id"], "agent-a")
            self.assertFalse(inbox_structured["mcp"]["initialized"])
            self.assertEqual(inbox_structured["mcp"]["watcher"]["state"], "idle")
            self.assertEqual(inbox_structured["links"]["agent"], "loom://agent/agent-a")
            self.assertEqual(
                inbox_structured["links"]["conflicts"],
                [f"loom://conflict/{conflict_id}"],
            )
            self.assertEqual(inbox_structured["next_action"]["tool"], "loom_conflicts")
            self.assertEqual(inbox_structured["next_action"]["arguments"], {})
            self.assertEqual(inbox_structured["next_action"]["confidence"], "high")
            self.assertEqual(inbox_structured["next_steps"], [])

            conflicts_payload = self._read_resource_payload(
                server,
                request_id="smoke-conflicts-resource",
                uri="loom://conflicts",
            )
            self.assertEqual(conflicts_payload["links"]["start"], "loom://start")
            self.assertEqual(conflicts_payload["identity"]["id"], "agent-a")
            self.assertEqual(conflicts_payload["conflicts"][0]["id"], conflict_id)
            self.assertEqual(conflicts_payload["next_action"]["tool"], "loom_resolve")
            self.assertEqual(
                conflicts_payload["next_action"]["arguments"],
                {"conflict_id": conflict_id},
            )
            self.assertEqual(
                conflicts_payload["next_steps"],
                [
                    "Call loom_inbox for the affected agent.",
                    "Call loom_status to compare the full repo state.",
                ],
            )

            conflict_payload = self._read_resource_payload(
                server,
                request_id="smoke-conflict-template",
                uri=f"loom://conflict/{conflict_id}",
            )
            self.assertEqual(conflict_payload["conflict"]["id"], conflict_id)
            self.assertTrue(conflict_payload["conflict"]["is_active"])
            self.assertEqual(
                conflict_payload["timeline_uri"],
                f"loom://conflict/{conflict_id}/timeline",
            )
            self.assertEqual(conflict_payload["links"]["start"], "loom://start")
            self.assertEqual(
                conflict_payload["links"]["object_a"],
                f"loom://claim/{conflict_payload['conflict']['object_id_a']}",
            )
            self.assertEqual(
                conflict_payload["links"]["object_b"],
                f"loom://intent/{intent_structured['intent']['id']}",
            )

            conflict_timeline_alias_payload = self._read_resource_payload(
                server,
                request_id="smoke-conflict-timeline-alias",
                uri=f"loom://conflict/{conflict_id}/timeline",
            )
            self.assertEqual(conflict_timeline_alias_payload["links"]["start"], "loom://start")
            self.assertEqual(conflict_timeline_alias_payload["object_type"], "conflict")
            self.assertEqual(conflict_timeline_alias_payload["object_id"], conflict_id)

            agent_payload = self._read_resource_payload(
                server,
                request_id="smoke-agent-resource",
                uri="loom://agent",
            )
            self.assertEqual(agent_payload["identity"]["id"], "agent-a")
            self.assertEqual(agent_payload["agent"]["conflicts"][0]["id"], conflict_id)
            self.assertEqual(agent_payload["next_action"]["tool"], "loom_resolve")
            self.assertEqual(
                agent_payload["next_steps"][0],
                f'Call loom_resolve with conflict_id="{conflict_id}" and note="<resolution>".',
            )

            inbox_payload = self._read_resource_payload(
                server,
                request_id="smoke-inbox-resource",
                uri="loom://inbox",
            )
            self.assertEqual(inbox_payload["identity"]["id"], "agent-a")
            self.assertEqual(inbox_payload["inbox"]["conflicts"][0]["id"], conflict_id)
            self.assertEqual(inbox_payload["next_action"]["tool"], "loom_conflicts")
            self.assertEqual(inbox_payload["next_steps"], [])

            prompt_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "smoke-prompt-conflict",
                    "method": "prompts/get",
                    "params": {
                        "name": "adapt_or_wait",
                        "arguments": {
                            "conflict_id": conflict_id,
                            "agent_id": "agent-a",
                        },
                    },
                }
            )
            self.assertIsNotNone(prompt_result)
            assert prompt_result is not None
            prompt_text = prompt_result["result"]["messages"][0]["content"]["text"]
            self.assertIn(conflict_id, prompt_text)
            self.assertIn("loom://conflicts", prompt_text)

            resolve_structured = self._call_tool(
                server,
                request_id="smoke-resolve-conflict",
                name="loom_resolve",
                arguments={
                    "conflict_id": conflict_id,
                    "resolution_note": "Waiting on agent-b after coordination.",
                },
            )["result"]["structuredContent"]
            self.assertFalse(resolve_structured["conflict"]["is_active"])
            self.assertEqual(resolve_structured["conflict"]["resolved_by"], "agent-a")
            self.assertEqual(
                resolve_structured["links"]["conflict"],
                f"loom://conflict/{conflict_id}",
            )

            active_conflicts_after = self._call_tool(
                server,
                request_id="smoke-conflicts-after",
                name="loom_conflicts",
            )["result"]["structuredContent"]
            self.assertEqual(active_conflicts_after["conflicts"], [])

            all_conflicts_after = self._call_tool(
                server,
                request_id="smoke-conflicts-all-after",
                name="loom_conflicts",
                arguments={"include_resolved": True},
            )["result"]["structuredContent"]
            self.assertEqual(len(all_conflicts_after["conflicts"]), 1)
            self.assertFalse(all_conflicts_after["conflicts"][0]["is_active"])

            conflicts_history_payload = self._read_resource_payload(
                server,
                request_id="smoke-conflicts-history-after",
                uri="loom://conflicts/history",
            )
            self.assertEqual(len(conflicts_history_payload["conflicts"]), 1)
            self.assertFalse(conflicts_history_payload["conflicts"][0]["is_active"])

            conflicts_after_payload = self._read_resource_payload(
                server,
                request_id="smoke-conflicts-resource-after",
                uri="loom://conflicts",
            )
            self.assertEqual(conflicts_after_payload["conflicts"], [])

            agent_after_payload = self._read_resource_payload(
                server,
                request_id="smoke-agent-after",
                uri="loom://agent",
            )
            self.assertEqual(agent_after_payload["agent"]["conflicts"], [])

            inbox_after_payload = self._read_resource_payload(
                server,
                request_id="smoke-inbox-after",
                uri="loom://inbox",
            )
            self.assertEqual(inbox_after_payload["inbox"]["conflicts"], [])

    def test_mcp_init_can_set_default_agent_and_claim_without_agent_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )

            init_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )
            self.assertIsNotNone(init_result)
            assert init_result is not None
            self.assertFalse(init_result["result"]["isError"])
            self.assertEqual(
                init_result["result"]["structuredContent"]["project"]["default_agent"],
                "agent-a",
            )

            whoami_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "whoami",
                    "method": "tools/call",
                    "params": {"name": "loom_whoami", "arguments": {}},
                }
            )
            self.assertIsNotNone(whoami_result)
            assert whoami_result is not None
            self.assertFalse(whoami_result["result"]["isError"])
            agent = whoami_result["result"]["structuredContent"]["agent"]
            self.assertEqual(agent["id"], "agent-a")
            self.assertEqual(agent["source"], "project")
            self.assertEqual(agent["project_default_agent"], "agent-a")

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-claim",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None
            self.assertFalse(claim_result["result"]["isError"])
            self.assertEqual(
                claim_result["result"]["structuredContent"]["claim"]["agent_id"],
                "agent-a",
            )

    def test_mcp_whoami_prefers_env_over_project_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )

            with patch.dict(os.environ, {"LOOM_AGENT": "agent-env"}, clear=False):
                whoami_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "whoami",
                        "method": "tools/call",
                        "params": {"name": "loom_whoami", "arguments": {}},
                    }
                )

            self.assertIsNotNone(whoami_result)
            assert whoami_result is not None
            self.assertFalse(whoami_result["result"]["isError"])
            agent = whoami_result["result"]["structuredContent"]["agent"]
            self.assertEqual(agent["id"], "agent-env")
            self.assertEqual(agent["source"], "env")
            self.assertEqual(agent["project_default_agent"], "agent-a")

    def test_mcp_bind_sets_terminal_alias_and_adopts_existing_terminal_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {},
                    },
                }
            )

            raw_terminal_identity = "dev@host:ttys007"
            with patch("loom.identity.current_terminal_identity", return_value=raw_terminal_identity), patch(
                "loom.mcp.current_terminal_identity",
                return_value=raw_terminal_identity,
            ):
                start_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "start-bind",
                        "method": "tools/call",
                        "params": {"name": "loom_start", "arguments": {}},
                    }
                )
                self.assertIsNotNone(start_result)
                assert start_result is not None
                start_structured = start_result["result"]["structuredContent"]
                self.assertEqual(start_structured["next_action"]["tool"], "loom_bind")
                self.assertEqual(start_structured["command_guide"][1]["tool"], "loom_bind")

                claim_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "tool-claim-raw",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_claim",
                            "arguments": {
                                "description": "Refactor auth flow",
                                "scope": ["src/auth"],
                            },
                        },
                    }
                )
                self.assertIsNotNone(claim_result)
                assert claim_result is not None
                claim_id = claim_result["result"]["structuredContent"]["claim"]["id"]
                self.assertEqual(
                    claim_result["result"]["structuredContent"]["claim"]["agent_id"],
                    raw_terminal_identity,
                )

                bind_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "tool-bind",
                        "method": "tools/call",
                        "params": {
                            "name": "loom_bind",
                            "arguments": {"agent_id": "agent-a"},
                        },
                    }
                )
                self.assertIsNotNone(bind_result)
                assert bind_result is not None
                self.assertFalse(bind_result["result"]["isError"])
                bind_structured = bind_result["result"]["structuredContent"]
                self.assertEqual(bind_structured["agent"]["id"], "agent-a")
                self.assertEqual(bind_structured["agent"]["source"], "terminal")
                self.assertEqual(bind_structured["agent"]["terminal_binding"], "agent-a")
                self.assertEqual(
                    bind_structured["binding_adoption"]["terminal_identity"],
                    raw_terminal_identity,
                )
                self.assertTrue(bind_structured["binding_adoption"]["source_had_work"])
                self.assertFalse(bind_structured["binding_adoption"]["target_had_work"])
                self.assertEqual(
                    bind_structured["binding_adoption"]["adopted_claim_id"],
                    claim_id,
                )

                whoami_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "whoami-after-bind",
                        "method": "tools/call",
                        "params": {"name": "loom_whoami", "arguments": {}},
                    }
                )
                self.assertIsNotNone(whoami_result)
                assert whoami_result is not None
                self.assertEqual(
                    whoami_result["result"]["structuredContent"]["agent"]["id"],
                    "agent-a",
                )
                self.assertEqual(
                    whoami_result["result"]["structuredContent"]["agent"]["terminal_binding"],
                    "agent-a",
                )

                agent_result = server.handle_message(
                    {
                        "jsonrpc": "2.0",
                        "id": "agent-after-bind",
                        "method": "tools/call",
                        "params": {"name": "loom_agent", "arguments": {}},
                    }
                )
                self.assertIsNotNone(agent_result)
                assert agent_result is not None
                self.assertEqual(
                    agent_result["result"]["structuredContent"]["agent"]["claim"]["id"],
                    claim_id,
                )
                self.assertEqual(
                    agent_result["result"]["structuredContent"]["agent"]["claim"]["agent_id"],
                    "agent-a",
                )

    def test_tools_call_rejects_unexpected_arguments_as_tool_error(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        response = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {
                    "name": "loom_status",
                    "arguments": {"extra": True},
                },
            }
        )

        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response["result"]["isError"])
        self.assertFalse(response["result"]["structuredContent"]["ok"])
        self.assertIn("Unexpected arguments", response["result"]["structuredContent"]["error"])
        self.assertEqual(response["result"]["structuredContent"]["error_code"], "invalid_arguments")

    def test_agent_and_context_ack_tools_close_the_context_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {"name": "loom_init", "arguments": {}},
                }
            )
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim-a",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "agent_id": "agent-b",
                            "description": "Own auth scope",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            context_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "context-write",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_write",
                        "arguments": {
                            "agent_id": "agent-a",
                            "topic": "auth-interface",
                            "body": "Refresh token required.",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(context_result)
            assert context_result is not None
            context_structured = context_result["result"]["structuredContent"]
            context_id = context_structured["context"]["id"]
            self.assertEqual(
                context_structured["links"]["context_item"],
                f"loom://context/{context_id}",
            )
            self.assertEqual(
                context_structured["links"]["context_timeline"],
                f"loom://context/{context_id}/timeline",
            )

            agent_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "agent-view",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_agent",
                        "arguments": {
                            "agent_id": "agent-b",
                            "context_limit": 5,
                            "event_limit": 10,
                        },
                    },
                }
            )
            self.assertIsNotNone(agent_result)
            assert agent_result is not None
            self.assertFalse(agent_result["result"]["isError"])
            agent_structured = agent_result["result"]["structuredContent"]
            agent = agent_structured["agent"]
            self.assertEqual(agent["claim"]["agent_id"], "agent-b")
            self.assertEqual(agent["incoming_context"][0]["id"], context_id)
            self.assertEqual(
                agent_structured["active_work"]["pending_context"][0]["id"],
                context_id,
            )
            conflict_id = agent_structured["active_work"]["conflicts"][0]["id"]
            self.assertFalse(agent_structured["worktree"]["has_drift"])
            self.assertEqual(agent_structured["next_action"]["tool"], "loom_resolve")
            self.assertEqual(
                agent_structured["next_action"]["arguments"],
                {"conflict_id": conflict_id},
            )
            self.assertEqual(agent_structured["next_action"]["confidence"], "high")
            self.assertEqual(
                agent_structured["next_action"]["reason"],
                "Loom found an active conflict touching the current work.",
            )
            self.assertEqual(
                agent_structured["next_steps"][0],
                f'Call loom_resolve with conflict_id="{conflict_id}" and note="<resolution>".',
            )

            ack_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "context-ack",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_ack",
                        "arguments": {
                            "context_id": context_id,
                            "agent_id": "agent-b",
                            "status": "adapted",
                            "note": "Shifted auth work to match.",
                        },
                    },
                }
            )
            self.assertIsNotNone(ack_result)
            assert ack_result is not None
            self.assertFalse(ack_result["result"]["isError"])
            ack_structured = ack_result["result"]["structuredContent"]
            ack = ack_structured["acknowledgment"]
            self.assertEqual(ack["status"], "adapted")
            self.assertEqual(ack["agent_id"], "agent-b")
            self.assertEqual(
                ack_structured["links"]["context_item"],
                f"loom://context/{context_id}",
            )
            self.assertIn(
                "Call loom_status to compare the updated repo state.",
                ack_structured["next_steps"],
            )

            context_read = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "context-read",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_read",
                        "arguments": {"topic": "auth-interface", "limit": 5},
                    },
                }
            )
            self.assertIsNotNone(context_read)
            assert context_read is not None
            context_read_structured = context_read["result"]["structuredContent"]
            context_entries = context_read_structured["context"]
            self.assertEqual(
                context_entries[0]["acknowledgments"][0]["status"],                "adapted",
            )
            self.assertEqual(
                context_read_structured["links"]["items"],
                [f"loom://context/{context_id}"],
            )
            self.assertIn(
                "Call loom_context_ack for notes that changed your plan.",
                context_read_structured["next_steps"],
            )

            context_resource = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "context-resource",
                    "method": "resources/read",
                    "params": {"uri": "loom://context"},
                }
            )
            self.assertIsNotNone(context_resource)
            assert context_resource is not None
            context_payload = json.loads(context_resource["result"]["contents"][0]["text"])
            self.assertEqual(context_payload["links"]["start"], "loom://start")

    def test_log_and_timeline_tools_surface_recent_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {"name": "loom_init", "arguments": {}},
                }
            )
            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "agent_id": "agent-a",
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None
            claim_id = claim_result["result"]["structuredContent"]["claim"]["id"]

            context_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "context",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_context_write",
                        "arguments": {
                            "agent_id": "agent-a",
                            "topic": "auth-interface",
                            "body": "Refresh token required.",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(context_result)
            assert context_result is not None
            context_structured = context_result["result"]["structuredContent"]
            context_id = context_structured["context"]["id"]
            self.assertEqual(
                context_structured["links"]["context_item"],
                f"loom://context/{context_id}",
            )

            log_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "log",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_log",
                        "arguments": {"limit": 10},
                    },
                }
            )
            self.assertIsNotNone(log_result)
            assert log_result is not None
            self.assertFalse(log_result["result"]["isError"])
            log_structured = log_result["result"]["structuredContent"]
            self.assertTrue(log_structured["identity"]["project_initialized"])
            self.assertIsNone(log_structured["project"]["default_agent"])
            self.assertFalse(log_structured["mcp"]["initialized"])
            self.assertEqual(log_structured["mcp"]["watcher"]["state"], "idle")
            self.assertEqual(log_structured["links"]["start"], "loom://start")
            self.assertEqual(log_structured["links"]["events_feed"], "loom://events/after/0")
            event_types = [
                event["type"]
                for event in log_structured["events"]
            ]
            self.assertIn("claim.recorded", event_types)
            self.assertIn("context.published", event_types)
            self.assertTrue(
                all(link.startswith("loom://event/") for link in log_structured["links"]["events"])
            )

            timeline_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "timeline",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_timeline",
                        "arguments": {"object_id": claim_id, "limit": 10},
                    },
                }
            )
            self.assertIsNotNone(timeline_result)
            assert timeline_result is not None
            self.assertFalse(timeline_result["result"]["isError"])
            timeline = timeline_result["result"]["structuredContent"]
            self.assertEqual(timeline["object_type"], "claim")
            self.assertEqual(timeline["target"]["id"], claim_id)
            self.assertEqual(timeline["linked_context"][0]["id"], context_id)
            self.assertEqual(timeline["links"]["start"], "loom://start")
            self.assertEqual(timeline["links"]["object"], f"loom://claim/{claim_id}")
            self.assertEqual(timeline["links"]["timeline"], f"loom://claim/{claim_id}/timeline")
            self.assertIn(
                "context.published",
                [event["type"] for event in timeline["events"]],
            )

    def test_run_processes_stdio_messages(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        input_stream = io.StringIO(
            "\n".join(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                        }
                    ),
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized",
                        }
                    ),
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/list",
                        }
                    ),
                    "",
                ]
            )
        )
        output_stream = io.StringIO()

        self.assertEqual(server.run(in_stream=input_stream, out_stream=output_stream), 0)

        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["result"]["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(responses[1]["id"], 2)
        self.assertIn("tools", responses[1]["result"])

    def test_run_emits_resource_notifications_for_subscribed_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)
            input_stream = io.StringIO(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 1,
                                "method": "initialize",
                                "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                            }
                        ),
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 2,
                                "method": "resources/subscribe",
                                "params": {"uri": "loom://identity"},
                            }
                        ),
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": 3,
                                "method": "tools/call",
                                "params": {
                                    "name": "loom_init",
                                    "arguments": {"default_agent": "agent-a"},
                                },
                            }
                        ),
                        "",
                    ]
                )
            )
            output_stream = io.StringIO()

            self.assertEqual(server.run(in_stream=input_stream, out_stream=output_stream), 0)

            messages = [json.loads(line) for line in output_stream.getvalue().splitlines()]
            methods = [message.get("method", "response") for message in messages]
            self.assertIn("notifications/resources/list_changed", methods)
            self.assertIn("notifications/resources/updated", methods)
            updated_uris = [
                message["params"]["uri"]
                for message in messages
                if message.get("method") == "notifications/resources/updated"
            ]
            self.assertIn("loom://identity", updated_uris)

    def test_run_exits_cleanly_when_response_stream_breaks(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        input_stream = io.StringIO(
            "\n".join(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                        }
                    ),
                    "",
                ]
            )
        )

        class _BrokenOutput:
            def write(self, _value: str) -> int:
                raise BrokenPipeError("broken pipe")

            def flush(self) -> None:
                raise AssertionError("flush should not run after write failure")

        self.assertEqual(server.run(in_stream=input_stream, out_stream=_BrokenOutput()), 0)
        self.assertIsNone(server._writer)

    def test_run_emits_background_resource_notifications_from_daemon_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)
            streamed_event = EventRecord(
                sequence=2,
                id="event_bg_01",
                type="claim.recorded",
                timestamp="2026-03-14T12:00:00Z",
                actor_id="agent-a",
                payload={"claim_id": "claim_bg_01"},
            )
            watcher_notified = threading.Event()

            class BlockingInput:
                def __init__(self, lines: list[str], ready: threading.Event) -> None:
                    self._lines = iter(lines)
                    self._ready = ready

                def readline(self) -> str:
                    try:
                        return next(self._lines)
                    except StopIteration:
                        self._ready.wait(0.5)
                        return ""

            input_stream = BlockingInput(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized",
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {
                                "name": "loom_init",
                                "arguments": {"default_agent": "agent-a"},
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "resources/subscribe",
                            "params": {"uri": "loom://events/after/0"},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 4,
                            "method": "resources/subscribe",
                            "params": {"uri": "loom://activity/agent-a/after/0"},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 5,
                            "method": "resources/subscribe",
                            "params": {"uri": "loom://mcp"},
                        }
                    )
                    + "\n",
                ],
                watcher_notified,
            )
            output_stream = io.StringIO()
            original_notify = server._notify_followed_event_updates

            def wrapped_notify(event: object) -> None:
                original_notify(event)
                watcher_notified.set()

            with patch.object(
                CoordinationClient,
                "daemon_status",
                return_value=DaemonStatus(running=True, detail="running on daemon.sock"),
            ), patch.object(
                CoordinationClient,
                "follow_events",
                return_value=iter((streamed_event,)),
            ) as follow_events_mock, patch.object(
                server,
                "_notify_followed_event_updates",
                side_effect=wrapped_notify,
            ):
                self.assertEqual(server.run(in_stream=input_stream, out_stream=output_stream), 0)

            self.assertGreaterEqual(follow_events_mock.call_count, 1)
            self.assertEqual(follow_events_mock.call_args_list[0].kwargs["after_sequence"], 0)
            messages = [json.loads(line) for line in output_stream.getvalue().splitlines()]
            updated_uris = [
                message["params"]["uri"]
                for message in messages
                if message.get("method") == "notifications/resources/updated"
            ]
            self.assertIn("loom://events/after/0", updated_uris)
            self.assertIn("loom://activity/agent-a/after/0", updated_uris)

    def test_run_background_watch_recovers_when_daemon_appears(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)
            streamed_event = EventRecord(
                sequence=3,
                id="event_bg_retry_01",
                type="intent.declared",
                timestamp="2026-03-14T12:01:00Z",
                actor_id="agent-b",
                payload={"intent_id": "intent_bg_retry_01", "claim_id": "claim_bg_retry_01"},
            )
            watcher_notified = threading.Event()

            class BlockingInput:
                def __init__(self, lines: list[str], ready: threading.Event) -> None:
                    self._lines = iter(lines)
                    self._ready = ready

                def readline(self) -> str:
                    try:
                        return next(self._lines)
                    except StopIteration:
                        self._ready.wait(0.5)
                        return ""

            input_stream = BlockingInput(
                [
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized",
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 2,
                            "method": "tools/call",
                            "params": {
                                "name": "loom_init",
                                "arguments": {"default_agent": "agent-a"},
                            },
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 3,
                            "method": "resources/subscribe",
                            "params": {"uri": "loom://events/after/0"},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 4,
                            "method": "resources/subscribe",
                            "params": {"uri": "loom://activity/agent-b/after/0"},
                        }
                    )
                    + "\n",
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 5,
                            "method": "resources/subscribe",
                            "params": {"uri": "loom://mcp"},
                        }
                    )
                    + "\n",
                ],
                watcher_notified,
            )
            output_stream = io.StringIO()
            original_notify = server._notify_followed_event_updates

            def wrapped_notify(event: object) -> None:
                original_notify(event)
                watcher_notified.set()

            daemon_statuses = iter(
                (
                    DaemonStatus(running=False, detail="not running"),
                    DaemonStatus(running=True, detail="running on daemon.sock"),
                    DaemonStatus(running=True, detail="running on daemon.sock"),
                )
            )

            def daemon_status_side_effect(*, refresh: bool = False) -> DaemonStatus:
                try:
                    return next(daemon_statuses)
                except StopIteration:
                    return DaemonStatus(running=True, detail="running on daemon.sock")

            with patch.object(
                CoordinationClient,
                "daemon_status",
                side_effect=daemon_status_side_effect,
            ), patch.object(
                CoordinationClient,
                "follow_events",
                return_value=iter((streamed_event,)),
            ) as follow_events_mock, patch.object(
                server,
                "_notify_followed_event_updates",
                side_effect=wrapped_notify,
            ):
                self.assertEqual(server.run(in_stream=input_stream, out_stream=output_stream), 0)

            self.assertGreaterEqual(follow_events_mock.call_count, 1)
            self.assertEqual(follow_events_mock.call_args_list[0].kwargs["after_sequence"], 0)
            messages = [json.loads(line) for line in output_stream.getvalue().splitlines()]
            updated_uris = [
                message["params"]["uri"]
                for message in messages
                if message.get("method") == "notifications/resources/updated"
            ]
            self.assertIn("loom://events/after/0", updated_uris)
            self.assertIn("loom://activity/agent-b/after/0", updated_uris)
            self.assertGreaterEqual(updated_uris.count("loom://mcp"), 2)

    def test_stop_background_watch_keeps_live_thread_registered_until_exit(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        stop_event = threading.Event()

        class _FakeThread:
            name = "loom-mcp-watch"

            def __init__(self) -> None:
                self.join_calls: list[float] = []

            def is_alive(self) -> bool:
                return True

            def join(self, timeout: float | None = None) -> None:
                self.join_calls.append(0.0 if timeout is None else float(timeout))

        watch_thread = _FakeThread()
        server._watch_stop = stop_event
        server._watch_thread = watch_thread
        server._watch_state = "watching"

        server._stop_background_watch()

        self.assertTrue(stop_event.is_set())
        self.assertEqual(watch_thread.join_calls, [0.2])
        self.assertIs(server._watch_thread, watch_thread)
        self.assertEqual(server._watch_state, "stopping")

    def test_stop_background_watch_clears_thread_once_join_finishes(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        stop_event = threading.Event()

        class _FakeThread:
            name = "loom-mcp-watch"

            def __init__(self) -> None:
                self.alive = True
                self.join_calls: list[float] = []

            def is_alive(self) -> bool:
                return self.alive

            def join(self, timeout: float | None = None) -> None:
                self.join_calls.append(0.0 if timeout is None else float(timeout))
                self.alive = False

        watch_thread = _FakeThread()
        server._watch_stop = stop_event
        server._watch_thread = watch_thread
        server._watch_state = "watching"

        server._stop_background_watch()

        self.assertTrue(stop_event.is_set())
        self.assertEqual(watch_thread.join_calls, [0.2])
        self.assertIsNone(server._watch_thread)
        self.assertEqual(server._watch_state, "idle")

    def test_background_watch_retries_stream_from_last_seen_sequence(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server._writer = io.StringIO()
        server._resource_subscriptions = {"loom://events/after/0"}
        server._watch_thread = threading.current_thread()
        first_event = EventRecord(
            sequence=5,
            id="event_watch_retry_01",
            type="claim.recorded",
            timestamp="2026-03-17T12:00:00Z",
            actor_id="agent-a",
            payload={"claim_id": "claim_watch_retry_01"},
        )
        second_event = EventRecord(
            sequence=6,
            id="event_watch_retry_02",
            type="intent.declared",
            timestamp="2026-03-17T12:01:00Z",
            actor_id="agent-a",
            payload={"intent_id": "intent_watch_retry_01"},
        )
        follow_calls: list[int] = []
        delivered_sequences: list[int] = []

        class _FakeStopEvent:
            def __init__(self) -> None:
                self._set = False
                self.wait_calls: list[float] = []

            def is_set(self) -> bool:
                return self._set

            def set(self) -> None:
                self._set = True

            def wait(self, timeout: float | None = None) -> bool:
                self.wait_calls.append(0.0 if timeout is None else float(timeout))
                return self._set

        class _FakeClient:
            def daemon_status(self, *, refresh: bool = False) -> DaemonStatus:
                return DaemonStatus(running=True, detail="running on daemon.sock")

            def follow_events(self, *, after_sequence: int = 0):
                follow_calls.append(int(after_sequence))
                if len(follow_calls) == 1:
                    return self._broken_stream()
                return iter((second_event,))

            @staticmethod
            def _broken_stream():
                yield first_event
                raise RuntimeError("socket_unavailable")

        stop_event = _FakeStopEvent()

        def _record_event(event: EventRecord) -> None:
            delivered_sequences.append(event.sequence)
            if event.sequence == second_event.sequence:
                stop_event.set()

        with patch.object(
            server,
            "_maybe_client_for_project_resources",
            return_value=_FakeClient(),
        ), patch.object(
            server,
            "_notify_followed_event_updates",
            side_effect=_record_event,
        ):
            server._background_watch_loop(stop_event, after_sequence=0)

        self.assertEqual(follow_calls, [0, first_event.sequence])
        self.assertEqual(delivered_sequences, [first_event.sequence, second_event.sequence])
        self.assertEqual(stop_event.wait_calls, [BACKGROUND_WATCH_STREAM_RETRY_SECONDS])
        self.assertEqual(server._watch_last_sequence, second_event.sequence)
        self.assertEqual(server._watch_state, "idle")
        self.assertIsNone(server._watch_thread)

    def test_background_watch_backs_off_while_daemon_is_unavailable(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server._initialized = True
        server._writer = io.StringIO()
        server._resource_subscriptions = {"loom://events/after/0"}

        class _FakeStopEvent:
            def __init__(self) -> None:
                self._set = False
                self.wait_calls: list[float] = []

            def is_set(self) -> bool:
                return self._set

            def set(self) -> None:
                self._set = True

            def wait(self, timeout: float | None = None) -> bool:
                self.wait_calls.append(0.0 if timeout is None else float(timeout))
                if len(self.wait_calls) >= 4:
                    self._set = True
                return self._set

        class _FakeClient:
            def daemon_status(self, *, refresh: bool = False) -> DaemonStatus:
                return DaemonStatus(running=False, detail="daemon unavailable")

            def follow_events(self, *, after_sequence: int = 0):
                raise AssertionError("follow_events should not run while daemon is down")

        stop_event = _FakeStopEvent()

        with patch.object(
            server,
            "_maybe_client_for_project_resources",
            return_value=_FakeClient(),
        ), patch.object(server, "_maybe_start_background_watch") as maybe_start:
            server._background_watch_loop(stop_event, after_sequence=0)

        self.assertEqual(
            stop_event.wait_calls,
            [
                BACKGROUND_WATCH_DAEMON_RETRY_SECONDS,
                BACKGROUND_WATCH_DAEMON_RETRY_SECONDS * 2.0,
                BACKGROUND_WATCH_DAEMON_RETRY_SECONDS * 4.0,
                BACKGROUND_WATCH_DAEMON_RETRY_SECONDS * 8.0,
            ],
        )
        maybe_start.assert_called_once_with()
        self.assertEqual(server._watch_state, "idle")
        self.assertIsNone(server._watch_thread)

    def test_background_watch_resets_stream_backoff_after_delivering_event(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server._initialized = True
        server._writer = io.StringIO()
        server._resource_subscriptions = {"loom://events/after/0"}
        delivered_sequences: list[int] = []

        event = EventRecord(
            sequence=5,
            id="event_watch_backoff_reset_01",
            type="claim.recorded",
            timestamp="2026-03-17T12:00:00Z",
            actor_id="agent-a",
            payload={"claim_id": "claim_watch_backoff_reset_01"},
        )

        class _FakeStopEvent:
            def __init__(self) -> None:
                self._set = False
                self.wait_calls: list[float] = []

            def is_set(self) -> bool:
                return self._set

            def set(self) -> None:
                self._set = True

            def wait(self, timeout: float | None = None) -> bool:
                self.wait_calls.append(0.0 if timeout is None else float(timeout))
                if len(self.wait_calls) >= 3:
                    self._set = True
                return self._set

        class _FakeClient:
            def __init__(self) -> None:
                self.calls = 0

            def daemon_status(self, *, refresh: bool = False) -> DaemonStatus:
                return DaemonStatus(running=True, detail="running on daemon.sock")

            def follow_events(self, *, after_sequence: int = 0):
                self.calls += 1
                if self.calls == 1:
                    return self._broken_stream()
                if self.calls == 2:
                    return self._event_then_broken_stream()
                return self._broken_stream()

            @staticmethod
            def _broken_stream():
                raise RuntimeError("socket_unavailable")
                yield

            @staticmethod
            def _event_then_broken_stream():
                yield event
                raise RuntimeError("socket_unavailable")

        stop_event = _FakeStopEvent()
        client = _FakeClient()

        def _record_event(delivered_event: EventRecord) -> None:
            delivered_sequences.append(delivered_event.sequence)

        with patch.object(
            server,
            "_maybe_client_for_project_resources",
            return_value=client,
        ), patch.object(
            server,
            "_notify_followed_event_updates",
            side_effect=_record_event,
        ), patch.object(server, "_maybe_start_background_watch") as maybe_start:
            server._background_watch_loop(stop_event, after_sequence=0)

        self.assertEqual(delivered_sequences, [event.sequence])
        self.assertEqual(
            stop_event.wait_calls,
            [
                BACKGROUND_WATCH_STREAM_RETRY_SECONDS,
                BACKGROUND_WATCH_STREAM_RETRY_SECONDS,
                BACKGROUND_WATCH_STREAM_RETRY_SECONDS * 2.0,
            ],
        )
        maybe_start.assert_called_once_with()
        self.assertEqual(server._watch_last_sequence, event.sequence)
        self.assertEqual(server._watch_state, "idle")
        self.assertIsNone(server._watch_thread)

    def test_background_watch_restarts_after_stop_when_subscriptions_return(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server._initialized = True
        server._writer = io.StringIO()
        server._resource_subscriptions = {"loom://events/after/0"}
        server._watch_thread = threading.current_thread()
        stop_event = threading.Event()
        stop_event.set()

        class _FakeClient:
            def daemon_status(self, *, refresh: bool = False) -> DaemonStatus:
                return DaemonStatus(running=True, detail="running on daemon.sock")

            def follow_events(self, *, after_sequence: int = 0):
                return iter(())

        with patch.object(
            server,
            "_maybe_client_for_project_resources",
            return_value=_FakeClient(),
        ), patch.object(server, "_maybe_start_background_watch") as maybe_start:
            server._background_watch_loop(stop_event, after_sequence=0)

        maybe_start.assert_called_once()
        self.assertIsNone(server._watch_thread)
        self.assertEqual(server._watch_state, "idle")

    def test_background_watch_does_not_restart_without_subscriptions(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server._initialized = True
        server._writer = io.StringIO()
        server._resource_subscriptions = set()
        server._watch_thread = threading.current_thread()
        stop_event = threading.Event()
        stop_event.set()

        class _FakeClient:
            def daemon_status(self, *, refresh: bool = False) -> DaemonStatus:
                return DaemonStatus(running=True, detail="running on daemon.sock")

            def follow_events(self, *, after_sequence: int = 0):
                return iter(())

        with patch.object(
            server,
            "_maybe_client_for_project_resources",
            return_value=_FakeClient(),
        ), patch.object(server, "_maybe_start_background_watch") as maybe_start:
            server._background_watch_loop(stop_event, after_sequence=0)

        maybe_start.assert_not_called()
        self.assertIsNone(server._watch_thread)
        self.assertEqual(server._watch_state, "idle")

    def test_background_watch_does_not_restart_without_writer(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)
        server._initialized = True
        server._writer = None
        server._resource_subscriptions = {"loom://events/after/0"}
        server._watch_thread = threading.current_thread()
        stop_event = threading.Event()
        stop_event.set()

        class _FakeClient:
            def daemon_status(self, *, refresh: bool = False) -> DaemonStatus:
                return DaemonStatus(running=True, detail="running on daemon.sock")

            def follow_events(self, *, after_sequence: int = 0):
                return iter(())

        with patch.object(
            server,
            "_maybe_client_for_project_resources",
            return_value=_FakeClient(),
        ), patch.object(server, "_maybe_start_background_watch") as maybe_start:
            server._background_watch_loop(stop_event, after_sequence=0)

        maybe_start.assert_not_called()
        self.assertIsNone(server._watch_thread)
        self.assertEqual(server._watch_state, "idle")

    def test_emit_notification_clears_writer_when_stream_write_fails(self) -> None:
        server = LoomMcpServer(cwd=PROJECT_ROOT)

        class _BrokenWriter:
            def write(self, _value: str) -> int:
                raise BrokenPipeError("broken pipe")

            def flush(self) -> None:
                raise AssertionError("flush should not run after write failure")

        server._writer = _BrokenWriter()

        server._emit_notification("notifications/resources/updated", {"uri": "loom://mcp"})

        self.assertIsNone(server._writer)

    def test_mcp_unclaim_releases_active_claim_and_returns_structured_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_init",
                        "arguments": {"default_agent": "agent-a"},
                    },
                }
            )

            claim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "claim",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_claim",
                        "arguments": {
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                        },
                    },
                }
            )
            self.assertIsNotNone(claim_result)
            assert claim_result is not None
            claim_id = claim_result["result"]["structuredContent"]["claim"]["id"]

            unclaim_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "unclaim",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_unclaim",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(unclaim_result)
            assert unclaim_result is not None
            self.assertFalse(unclaim_result["result"]["isError"])
            unclaim_structured = unclaim_result["result"]["structuredContent"]
            self.assertTrue(unclaim_structured["ok"])
            self.assertEqual(unclaim_structured["claim"]["id"], claim_id)
            self.assertTrue(len(unclaim_structured["next_steps"]) > 0)

            unclaim_again = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "unclaim-again",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_unclaim",
                        "arguments": {},
                    },
                }
            )
            self.assertIsNotNone(unclaim_again)
            assert unclaim_again is not None
            self.assertTrue(unclaim_again["result"]["isError"])
            self.assertEqual(
                unclaim_again["result"]["structuredContent"]["error_code"],
                "no_active_claim",
            )
            self.assertEqual(
                unclaim_again["result"]["structuredContent"]["next_steps"],
                [
                    "Call loom_status to confirm the current coordination state.",
                    'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
                ],
            )

    def test_mcp_intent_rejects_empty_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            server = LoomMcpServer(cwd=repo_root)

            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "init",
                    "method": "initialize",
                    "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
                }
            )
            server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "tool-init",
                    "method": "tools/call",
                    "params": {"name": "loom_init", "arguments": {}},
                }
            )

            intent_result = server.handle_message(
                {
                    "jsonrpc": "2.0",
                    "id": "intent-empty",
                    "method": "tools/call",
                    "params": {
                        "name": "loom_intent",
                        "arguments": {
                            "description": "Test",
                            "scope": [],
                        },
                    },
                }
            )
            self.assertIsNotNone(intent_result)
            assert intent_result is not None
            self.assertTrue(intent_result["result"]["isError"])
            self.assertIn(
                "Intent scope must not be empty",
                intent_result["result"]["structuredContent"]["error"],
            )

    def test_cli_mcp_command_routes_to_server(self) -> None:
        with patch("loom.cli.run_mcp_server", return_value=0) as run_mcp_server_mock:
            self.assertEqual(main(["mcp"]), 0)

        run_mcp_server_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
