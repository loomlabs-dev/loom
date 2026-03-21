from __future__ import annotations

from dataclasses import FrozenInstanceError
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import loom.local_store as local_store  # noqa: E402
from loom.local_store.records import (  # noqa: E402
    AgentPresenceRecord,
    AgentSnapshot,
    ClaimRecord,
    ConflictRecord,
    ContextAckRecord,
    ContextRecord,
    EventRecord,
    InboxSnapshot,
    IntentRecord,
    StatusSnapshot,
)


class RecordsTest(unittest.TestCase):
    def test_local_store_re_exports_public_record_types(self) -> None:
        self.assertIs(local_store.ClaimRecord, ClaimRecord)
        self.assertIs(local_store.IntentRecord, IntentRecord)
        self.assertIs(local_store.ContextRecord, ContextRecord)
        self.assertIs(local_store.ContextAckRecord, ContextAckRecord)
        self.assertIs(local_store.ConflictRecord, ConflictRecord)
        self.assertIs(local_store.EventRecord, EventRecord)
        self.assertIs(local_store.StatusSnapshot, StatusSnapshot)
        self.assertIs(local_store.AgentSnapshot, AgentSnapshot)
        self.assertIs(local_store.InboxSnapshot, InboxSnapshot)
        self.assertIs(local_store.AgentPresenceRecord, AgentPresenceRecord)

    def test_claim_record_is_frozen(self) -> None:
        claim = ClaimRecord(
            id="claim_123",
            agent_id="agent-a",
            description="Claimed work",
            scope=("src/api",),
            status="active",
            created_at="2026-03-18T12:00:00Z",
            git_branch="main",
            lease_expires_at=None,
            lease_policy=None,
        )

        with self.assertRaises(FrozenInstanceError):
            claim.status = "released"  # type: ignore[misc]

    def test_conflict_and_context_defaults_stay_stable(self) -> None:
        conflict = ConflictRecord(
            id="conflict_123",
            kind="scope_overlap",
            severity="warning",
            summary="Overlap",
            object_type_a="claim",
            object_id_a="claim_1",
            object_type_b="intent",
            object_id_b="intent_1",
            scope=("src/api",),
            created_at="2026-03-18T12:00:00Z",
        )
        context = ContextRecord(
            id="context_123",
            agent_id="agent-a",
            topic="session-handoff",
            body="Continue here.",
            scope=("src/api",),
            created_at="2026-03-18T12:05:00Z",
            related_claim_id=None,
            related_intent_id=None,
            git_branch="main",
        )

        self.assertTrue(conflict.is_active)
        self.assertIsNone(conflict.resolved_at)
        self.assertEqual(context.acknowledgments, ())

    def test_snapshot_records_preserve_nested_tuple_contracts(self) -> None:
        claim = ClaimRecord(
            id="claim_123",
            agent_id="agent-a",
            description="Claimed work",
            scope=("src/api",),
            status="active",
            created_at="2026-03-18T12:00:00Z",
            git_branch="main",
            lease_expires_at=None,
            lease_policy=None,
        )
        intent = IntentRecord(
            id="intent_123",
            agent_id="agent-a",
            description="Declared intent",
            reason="Need to change API",
            scope=("src/api",),
            status="active",
            created_at="2026-03-18T12:05:00Z",
            related_claim_id=claim.id,
            git_branch="main",
            lease_expires_at=None,
            lease_policy=None,
        )
        context = ContextRecord(
            id="context_123",
            agent_id="agent-a",
            topic="implementation-note",
            body="Carry this forward.",
            scope=("src/api",),
            created_at="2026-03-18T12:10:00Z",
            related_claim_id=claim.id,
            related_intent_id=intent.id,
            git_branch="main",
            acknowledgments=(
                ContextAckRecord(
                    id="ack_123",
                    context_id="context_123",
                    agent_id="agent-b",
                    status="acknowledged",
                    acknowledged_at="2026-03-18T12:15:00Z",
                    note="Read and understood.",
                ),
            ),
        )
        conflict = ConflictRecord(
            id="conflict_123",
            kind="semantic_overlap",
            severity="warning",
            summary="Potential overlap",
            object_type_a="claim",
            object_id_a=claim.id,
            object_type_b="intent",
            object_id_b=intent.id,
            scope=("src/api",),
            created_at="2026-03-18T12:20:00Z",
        )
        event = EventRecord(
            sequence=7,
            id="event_123",
            type="claim.recorded",
            timestamp="2026-03-18T12:00:01Z",
            actor_id="agent-a",
            payload={"claim_id": claim.id},
        )

        status = StatusSnapshot(
            claims=(claim,),
            intents=(intent,),
            context=(context,),
            conflicts=(conflict,),
        )
        agent = AgentSnapshot(
            agent_id="agent-a",
            claim=claim,
            intent=intent,
            published_context=(context,),
            incoming_context=(),
            conflicts=(conflict,),
            events=(event,),
        )
        inbox = InboxSnapshot(
            agent_id="agent-b",
            pending_context=(context,),
            conflicts=(conflict,),
            events=(event,),
        )
        presence = AgentPresenceRecord(
            agent_id="agent-a",
            source="cli",
            created_at="2026-03-18T11:55:00Z",
            last_seen_at="2026-03-18T12:30:00Z",
            claim=claim,
            intent=intent,
        )

        self.assertEqual(status.claims[0].id, "claim_123")
        self.assertEqual(status.context[0].acknowledgments[0].note, "Read and understood.")
        self.assertEqual(agent.events[0].sequence, 7)
        self.assertEqual(inbox.pending_context[0].topic, "implementation-note")
        self.assertEqual(presence.claim, claim)


if __name__ == "__main__":
    unittest.main()
