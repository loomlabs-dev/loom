from __future__ import annotations

import pathlib
import sys
import unittest
from types import SimpleNamespace


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import (  # noqa: E402
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    IntentRecord,
    StatusSnapshot,
)
from loom.mcp_links import (  # noqa: E402
    tool_context_write_links,
    tool_inbox_links,
    tool_resolve_links,
    tool_status_links,
    tool_timeline_links,
)


def make_claim() -> ClaimRecord:
    return ClaimRecord(
        id="claim_123",
        agent_id="agent-a",
        description="Claimed work",
        scope=("src/api.py",),
        status="active",
        created_at="2026-03-18T12:00:00Z",
    )


def make_intent() -> IntentRecord:
    return IntentRecord(
        id="intent_123",
        agent_id="agent-a",
        description="Update API",
        reason="migration",
        scope=("src/api.py",),
        status="active",
        created_at="2026-03-18T12:05:00Z",
        related_claim_id="claim_123",
    )


def make_context() -> ContextRecord:
    return ContextRecord(
        id="context_123",
        agent_id="agent-a",
        topic="handoff",
        body="context body",
        scope=("src/api.py",),
        created_at="2026-03-18T12:10:00Z",
        related_claim_id="claim_123",
        related_intent_id="intent_123",
    )


def make_conflict() -> ConflictRecord:
    return ConflictRecord(
        id="conflict_123",
        kind="semantic_overlap",
        severity="warning",
        summary="Overlap",
        object_type_a="claim",
        object_id_a="claim_123",
        object_type_b="intent",
        object_id_b="intent_123",
        scope=("src/api.py",),
        created_at="2026-03-18T12:15:00Z",
    )


class McpLinksTest(unittest.TestCase):
    def test_tool_context_write_links_include_related_objects_and_conflicts(self) -> None:
        links = tool_context_write_links(
            agent_id="agent-a",
            context=make_context(),
            conflicts=(make_conflict(),),
        )

        self.assertEqual(links["agent"], "loom://agent/agent-a")
        self.assertEqual(links["context_item"], "loom://context/context_123")
        self.assertEqual(links["context_timeline"], "loom://context/context_123/timeline")
        self.assertEqual(links["related_claim"], "loom://claim/claim_123")
        self.assertEqual(links["related_intent"], "loom://intent/intent_123")
        self.assertEqual(links["conflicts_for_context"], ["loom://conflict/conflict_123"])

    def test_tool_status_links_include_all_active_object_kinds(self) -> None:
        snapshot = StatusSnapshot(
            claims=(make_claim(),),
            intents=(make_intent(),),
            context=(make_context(),),
            conflicts=(make_conflict(),),
        )

        links = tool_status_links(agent_id="agent-a", snapshot=snapshot)

        self.assertEqual(links["claims"], ["loom://claim/claim_123"])
        self.assertEqual(links["intents"], ["loom://intent/intent_123"])
        self.assertEqual(links["context_items"], ["loom://context/context_123"])
        self.assertEqual(links["active_conflicts"], ["loom://conflict/conflict_123"])

    def test_tool_resolve_links_use_object_lookup_callback(self) -> None:
        conflict = make_conflict()

        links = tool_resolve_links(
            agent_id="agent-a",
            conflict=conflict,
            object_resource_uri_for_object_id=lambda object_id: f"loom://object/{object_id}",
        )

        self.assertEqual(links["conflict"], "loom://conflict/conflict_123")
        self.assertEqual(links["object_a"], "loom://object/claim_123")
        self.assertEqual(links["object_b"], "loom://object/intent_123")

    def test_tool_timeline_links_fall_back_to_generic_timeline_uri(self) -> None:
        links = tool_timeline_links(
            agent_id="agent-a",
            object_id="intent_123",
            linked_context=(make_context(),),
            related_conflicts=(make_conflict(),),
            object_resource_uri_for_object_id=lambda object_id: f"loom://object/{object_id}",
            timeline_alias_uri_for_object_id=lambda object_id: None,
        )

        self.assertEqual(links["object"], "loom://object/intent_123")
        self.assertEqual(links["timeline"], "loom://timeline/intent_123")
        self.assertEqual(links["linked_context"], ["loom://context/context_123"])
        self.assertEqual(links["related_conflicts"], ["loom://conflict/conflict_123"])

    def test_tool_inbox_links_include_pending_context_conflicts_and_feed(self) -> None:
        inbox = SimpleNamespace(
            agent_id="agent-a",
            pending_context=(make_context(),),
            conflicts=(make_conflict(),),
        )

        links = tool_inbox_links(inbox=inbox)

        self.assertEqual(links["pending_context"], ["loom://context/context_123"])
        self.assertEqual(links["conflicts"], ["loom://conflict/conflict_123"])
        self.assertEqual(links["activity_feed"], "loom://activity/agent-a/after/0")


if __name__ == "__main__":
    unittest.main()
