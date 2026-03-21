from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import ClaimRecord, ConflictRecord  # noqa: E402
from loom.mcp_support import (  # noqa: E402
    json_text,
    prompt_message,
    tool_action_from_recommendation,
    tool_agent_action,
    tool_conflicts_action,
    tool_content,
    tool_status_action,
)


def make_conflict(conflict_id: str) -> ConflictRecord:
    return ConflictRecord(
        id=conflict_id,
        kind="scope_overlap",
        severity="warning",
        summary="overlap",
        object_type_a="claim",
        object_id_a="claim_a",
        object_type_b="claim",
        object_id_b="claim_b",
        scope=("src/api.py",),
        created_at="2026-03-18T12:00:00Z",
    )


class McpSupportTest(unittest.TestCase):
    def test_tool_content_collapses_duplicate_structured_json(self) -> None:
        structured = {"message": "cafe"}
        summary = json.dumps(structured, sort_keys=True, ensure_ascii=False)

        content = tool_content(summary, structured)

        self.assertEqual(content, [{"type": "text", "text": summary}])

    def test_tool_content_and_json_text_preserve_unicode_and_json_ready_values(self) -> None:
        structured = {"path": Path("src/uber"), "message": "café"}

        content = tool_content("summary", structured)
        rendered = json_text(structured)

        self.assertEqual(content[0], {"type": "text", "text": "summary"})
        self.assertEqual(json.loads(content[1]["text"]), {"message": "café", "path": "src/uber"})
        self.assertEqual(json.loads(rendered), {"message": "café", "path": "src/uber"})
        self.assertIn("café", rendered)

    def test_prompt_message_wraps_text_as_user_message(self) -> None:
        self.assertEqual(
            prompt_message("Use Loom first."),
            {
                "role": "user",
                "content": {"type": "text", "text": "Use Loom first."},
            },
        )

    def test_tool_action_from_recommendation_preserves_urgency(self) -> None:
        action = tool_action_from_recommendation(
            {
                "tool_name": "loom_claim",
                "tool_arguments": {"description": "Start work"},
                "summary": "Start work.",
                "reason": "Nothing is claimed yet.",
                "confidence": "high",
                "urgency": "fresh",
            }
        )

        self.assertEqual(
            action,
            {
                "tool": "loom_claim",
                "arguments": {"description": "Start work"},
                "summary": "Start work.",
                "reason": "Nothing is claimed yet.",
                "confidence": "high",
                "urgency": "fresh",
            },
        )

    def test_tool_agent_action_uses_default_runtime_payloads_when_missing(self) -> None:
        def fake_recommendation(**kwargs):
            self.assertEqual(kwargs["agent_id"], "agent-a")
            self.assertEqual(kwargs["active_work"], {"priority": None, "started_at": None})
            self.assertEqual(kwargs["worktree_signal"], {"has_drift": False, "suggested_scope": ()})
            return {
                "tool_name": "loom_claim",
                "tool_arguments": {"description": "Start work"},
                "summary": "Start work.",
                "reason": "No active work is recorded.",
                "confidence": "medium",
            }

        with patch("loom.mcp_support.guidance_agent_recommendation", side_effect=fake_recommendation):
            action = tool_agent_action(
                agent=SimpleNamespace(
                    agent_id="agent-a",
                    claim=None,
                    intent=None,
                    published_context=(),
                ),
                active_work=None,
                worktree_signal=None,
            )

        self.assertEqual(action["tool"], "loom_claim")
        self.assertEqual(action["arguments"], {"description": "Start work"})

    def test_tool_status_action_propagates_identity_recommendation_for_unstable_identity(self) -> None:
        client = SimpleNamespace(store=object())

        def fake_status_recommendation(**kwargs):
            self.assertEqual(kwargs["agent_id"], "agent-a")
            self.assertEqual(kwargs["stale_agent_ids"], {"agent-stale"})
            self.assertEqual(kwargs["repo_lanes"], {"counts": {"acknowledged_migration_lanes": 1}})
            self.assertEqual(kwargs["empty_recommendation"]["tool_name"], "loom_claim")
            self.assertEqual(kwargs["identity_recommendation"]["tool_name"], "loom_bind")
            return kwargs["identity_recommendation"]

        with (
            patch("loom.mcp_support.guidance_identity_has_stable_coordination", return_value=False),
            patch("loom.mcp_support.guidance_status_recommendation", side_effect=fake_status_recommendation),
        ):
            action = tool_status_action(
                client=client,
                snapshot=SimpleNamespace(claims=(), intents=(), context=(), conflicts=()),
                identity={"id": "agent-a", "source": "tty", "stable_terminal_identity": False},
                stale_agent_ids={"agent-stale"},
                repo_lanes={"counts": {"acknowledged_migration_lanes": 1}},
            )

        self.assertEqual(action["tool"], "loom_bind")
        self.assertEqual(action["arguments"], {"agent_id": "<agent-name>"})

    def test_tool_conflicts_action_filters_non_conflict_values(self) -> None:
        conflict = make_conflict("conflict_123")

        def fake_recommendation(conflicts):
            self.assertEqual(conflicts, (conflict,))
            return {
                "tool_name": "loom_resolve",
                "tool_arguments": {"conflict_id": conflict.id},
                "summary": "Resolve the open conflict.",
                "reason": "One active conflict remains.",
                "confidence": "high",
            }

        with patch("loom.mcp_support.guidance_conflicts_recommendation", side_effect=fake_recommendation):
            action = tool_conflicts_action(conflicts=(conflict, "not-a-conflict"))

        self.assertEqual(action["tool"], "loom_resolve")
        self.assertEqual(action["arguments"], {"conflict_id": "conflict_123"})


if __name__ == "__main__":
    unittest.main()
