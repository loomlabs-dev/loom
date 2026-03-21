from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.guidance_actions import (  # noqa: E402
    claim_recommendation,
    conflicts_recommendation,
    focus_agent_recommendation,
    handoff_recommendation,
    inbox_recommendation,
    inspect_conflicts_recommendation,
    inspect_inbox_recommendation,
    intent_recommendation,
    lease_alert_recommendation,
    priority_recommendation,
    recommendation,
    worktree_adoption_recommendation,
    yield_alert_recommendation,
)
from loom.local_store import ConflictRecord, ContextRecord  # noqa: E402


def make_conflict(conflict_id: str = "conflict_123") -> ConflictRecord:
    return ConflictRecord(
        id=conflict_id,
        kind="scope_overlap",
        severity="warning",
        summary="Overlap on api",
        object_type_a="claim",
        object_id_a="claim_123",
        object_type_b="intent",
        object_id_b="intent_123",
        scope=("src/api.py",),
        created_at="2026-03-18T12:00:00Z",
    )


def make_context(context_id: str = "context_123") -> ContextRecord:
    return ContextRecord(
        id=context_id,
        agent_id="agent-a",
        topic="handoff",
        body="Context body",
        scope=("src/api.py",),
        created_at="2026-03-18T12:05:00Z",
        related_claim_id="claim_123",
        related_intent_id="intent_123",
    )


class GuidanceActionsTest(unittest.TestCase):
    def test_recommendation_includes_optional_fields_only_when_present(self) -> None:
        payload = recommendation(
            command="loom claim",
            tool_name="loom_claim",
            tool_arguments={"description": "Start"},
            summary="Start work.",
            reason="Nothing is active yet.",
            confidence="high",
            urgency="fresh",
            kind="context",
            action_id="context_123",
        )

        self.assertEqual(
            payload,
            {
                "command": "loom claim",
                "tool_name": "loom_claim",
                "tool_arguments": {"description": "Start"},
                "summary": "Start work.",
                "reason": "Nothing is active yet.",
                "confidence": "high",
                "urgency": "fresh",
                "kind": "context",
                "id": "context_123",
            },
        )

    def test_claim_and_intent_recommendations_preserve_scope_and_agent(self) -> None:
        claim = claim_recommendation(
            summary="Start work.",
            reason="Repo is idle.",
            confidence="medium",
            scope=("src/api.py", "src/models.py"),
            agent_id="agent-a",
        )
        intent = intent_recommendation(
            summary="Declare edit.",
            reason="Scope is widening.",
            confidence="high",
            scope=(),
            agent_id="agent-b",
        )

        self.assertEqual(
            claim["command"],
            'loom claim "Describe the work you\'re starting" --scope src/api.py --scope src/models.py',
        )
        self.assertEqual(
            claim["tool_arguments"],
            {
                "description": "Describe the work you're starting",
                "scope": ["src/api.py", "src/models.py"],
                "agent_id": "agent-a",
            },
        )
        self.assertEqual(
            intent["tool_arguments"],
            {
                "description": "Describe the edit you're about to make",
                "scope": ["path/to/area"],
                "agent_id": "agent-b",
            },
        )

    def test_priority_and_alert_recommendations_validate_shape_and_apply_defaults(self) -> None:
        self.assertIsNone(priority_recommendation(None))
        self.assertIsNone(priority_recommendation({"next_step": "loom claim"}))

        priority = priority_recommendation(
            {
                "next_step": "loom resolve conflict_123 --note \"<resolution>\"",
                "tool_name": "loom_resolve",
                "tool_arguments": {"conflict_id": "conflict_123"},
                "kind": "conflict",
                "id": "conflict_123",
            }
        )
        lease = lease_alert_recommendation(
            {
                "next_step": "loom renew",
                "tool_name": "loom_renew",
                "tool_arguments": {"agent_id": "agent-a"},
            }
        )
        yielded = yield_alert_recommendation(
            {
                "next_step": "loom finish",
                "tool_name": "loom_finish",
                "tool_arguments": {"agent_id": "agent-a"},
                "urgency": "fresh",
            }
        )

        self.assertEqual(priority["kind"], "conflict")
        self.assertEqual(priority["id"], "conflict_123")
        self.assertEqual(priority["summary"], "React to Loom's top priority.")
        self.assertEqual(lease["kind"], "lease")
        self.assertIn("coordination lease has expired", lease["reason"])
        self.assertEqual(yielded["kind"], "yield")
        self.assertEqual(yielded["urgency"], "fresh")

    def test_worktree_and_handoff_recommendations_choose_correct_underlying_action(self) -> None:
        adoption_without_scope = worktree_adoption_recommendation(
            has_active_scope=False,
            suggested_scope=("src/api.py",),
            agent_id="agent-a",
        )
        adoption_with_scope = worktree_adoption_recommendation(
            has_active_scope=True,
            suggested_scope=("src/api.py",),
            agent_id="agent-a",
        )
        handoff = handoff_recommendation(
            handoff=make_context(),
            agent_id="agent-a",
        )

        self.assertEqual(adoption_without_scope["tool_name"], "loom_claim")
        self.assertEqual(adoption_with_scope["tool_name"], "loom_intent")
        self.assertEqual(handoff["tool_name"], "loom_claim")
        self.assertEqual(handoff["tool_arguments"]["scope"], ["src/api.py"])

    def test_inbox_recommendation_orders_conflicts_then_context_then_claim(self) -> None:
        conflict = inbox_recommendation(
            agent_id="agent-a",
            pending_context=(make_context(),),
            conflicts=(make_conflict(),),
        )
        conflict_inspect = inbox_recommendation(
            agent_id="agent-a",
            pending_context=(),
            conflicts=(make_conflict(),),
            prefer_conflict_inspection=True,
        )
        context = inbox_recommendation(
            agent_id="agent-a",
            pending_context=(make_context(),),
            conflicts=(),
        )
        empty = inbox_recommendation(
            agent_id="agent-a",
            pending_context=(),
            conflicts=(),
        )

        self.assertEqual(conflict["tool_name"], "loom_resolve")
        self.assertEqual(conflict["kind"], "conflict")
        self.assertEqual(conflict_inspect["tool_name"], "loom_conflicts")
        self.assertEqual(context["tool_name"], "loom_context_ack")
        self.assertEqual(context["kind"], "context")
        self.assertEqual(empty["tool_name"], "loom_claim")
        self.assertEqual(empty["tool_arguments"]["agent_id"], "agent-a")

    def test_conflict_and_focus_inspection_recommendations_shape_expected_commands(self) -> None:
        conflict = conflicts_recommendation((make_conflict(),))
        no_conflict = conflicts_recommendation(())
        inbox_focus = inspect_inbox_recommendation(
            agent_id="agent-a",
            summary="Inspect inbox.",
            reason="Pending work exists.",
            confidence="high",
        )
        conflict_focus = inspect_conflicts_recommendation(
            summary="Inspect conflicts.",
            reason="Repo overlaps exist.",
            confidence="medium",
        )
        agent_focus = focus_agent_recommendation(
            agent_id="agent-a",
            summary="Focus agent.",
            reason="Active work needs review.",
            confidence="high",
        )

        self.assertEqual(conflict["tool_name"], "loom_resolve")
        self.assertEqual(conflict["id"], "conflict_123")
        self.assertEqual(no_conflict["tool_name"], "loom_claim")
        self.assertEqual(inbox_focus["tool_name"], "loom_inbox")
        self.assertEqual(inbox_focus["tool_arguments"], {"agent_id": "agent-a"})
        self.assertEqual(conflict_focus["tool_name"], "loom_conflicts")
        self.assertEqual(agent_focus["tool_name"], "loom_agent")
        self.assertEqual(agent_focus["tool_arguments"], {"agent_id": "agent-a"})


if __name__ == "__main__":
    unittest.main()
