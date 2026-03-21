from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import (  # noqa: E402
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
from loom.wire import (  # noqa: E402
    agent_presence_from_wire,
    agent_presence_to_wire,
    agent_snapshot_from_wire,
    agent_snapshot_to_wire,
    claim_from_wire,
    context_from_wire,
    event_from_wire,
    inbox_snapshot_from_wire,
    inbox_snapshot_to_wire,
    status_snapshot_from_wire,
    status_snapshot_to_wire,
)


class WireTest(unittest.TestCase):
    def test_agent_presence_round_trips_nested_records(self) -> None:
        presence = AgentPresenceRecord(
            agent_id="agent-a",
            source="project",
            created_at="2026-03-15T00:00:00Z",
            last_seen_at="2026-03-15T00:05:00Z",
            claim=ClaimRecord(
                id="claim_01",
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth",),
                status="active",
                created_at="2026-03-15T00:00:00Z",
                git_branch="feature/auth",
            ),
            intent=IntentRecord(
                id="intent_01",
                agent_id="agent-a",
                description="Touch middleware",
                reason="Need rate limit hook",
                scope=("src/auth/middleware",),
                status="active",
                created_at="2026-03-15T00:01:00Z",
                related_claim_id="claim_01",
                git_branch="feature/middleware",
            ),
        )

        self.assertEqual(
            agent_presence_from_wire(agent_presence_to_wire(presence)),
            presence,
        )

    def test_status_snapshot_round_trips_nested_records(self) -> None:
        claim = ClaimRecord(
            id="claim_01",
            agent_id="agent-a",
            description="Refactor auth flow",
            scope=("src/auth",),
            status="active",
            created_at="2026-03-15T00:00:00Z",
            git_branch="feature/auth",
        )
        intent = IntentRecord(
            id="intent_01",
            agent_id="agent-b",
            description="Touch middleware",
            reason="Need rate limit hook",
            scope=("src/auth/middleware",),
            status="active",
            created_at="2026-03-15T00:01:00Z",
            related_claim_id="claim_01",
            git_branch="feature/middleware",
        )
        acknowledgment = ContextAckRecord(
            id="ctxack_01",
            context_id="context_01",
            agent_id="agent-b",
            status="adapted",
            acknowledged_at="2026-03-15T00:02:00Z",
            note="Shifted work.",
        )
        context = ContextRecord(
            id="context_01",
            agent_id="agent-a",
            topic="auth-interface",
            body="Refresh token required.",
            scope=("src/auth",),
            created_at="2026-03-15T00:01:30Z",
            related_claim_id="claim_01",
            related_intent_id="intent_01",
            git_branch="feature/auth",
            acknowledgments=(acknowledgment,),
        )
        conflict = ConflictRecord(
            id="conflict_01",
            kind="semantic_overlap",
            severity="warning",
            summary="agent-b intent is semantically entangled with agent-a claim",
            object_type_a="claim",
            object_id_a="claim_01",
            object_type_b="intent",
            object_id_b="intent_01",
            scope=("src/auth", "src/auth/middleware"),
            created_at="2026-03-15T00:03:00Z",
            is_active=False,
            resolved_at="2026-03-15T00:04:00Z",
            resolved_by="agent-b",
            resolution_note="Coordinated.",
        )
        snapshot = StatusSnapshot(
            claims=(claim,),
            intents=(intent,),
            context=(context,),
            conflicts=(conflict,),
        )

        round_tripped = status_snapshot_from_wire(status_snapshot_to_wire(snapshot))

        self.assertEqual(round_tripped, snapshot)

    def test_agent_and_inbox_snapshots_round_trip_events(self) -> None:
        claim = ClaimRecord(
            id="claim_01",
            agent_id="agent-a",
            description="Refactor auth flow",
            scope=("src/auth",),
            status="active",
            created_at="2026-03-15T00:00:00Z",
            git_branch="feature/auth",
        )
        context = ContextRecord(
            id="context_01",
            agent_id="agent-b",
            topic="auth-interface",
            body="Refresh token required.",
            scope=("src/auth",),
            created_at="2026-03-15T00:01:00Z",
            related_claim_id=None,
            related_intent_id=None,
            acknowledgments=(),
        )
        conflict = ConflictRecord(
            id="conflict_01",
            kind="contextual_dependency",
            severity="warning",
            summary="agent-a claim may depend on agent-b context",
            object_type_a="claim",
            object_id_a="claim_01",
            object_type_b="context",
            object_id_b="context_01",
            scope=("src/auth",),
            created_at="2026-03-15T00:02:00Z",
        )
        event = EventRecord(
            sequence=4,
            id="event_01",
            type="context.published",
            timestamp="2026-03-15T00:01:00Z",
            actor_id="agent-b",
            payload={"context_id": "context_01"},
        )
        agent_snapshot = AgentSnapshot(
            agent_id="agent-a",
            claim=claim,
            intent=None,
            published_context=(),
            incoming_context=(context,),
            conflicts=(conflict,),
            events=(event,),
        )
        inbox_snapshot = InboxSnapshot(
            agent_id="agent-a",
            pending_context=(context,),
            conflicts=(conflict,),
            events=(event,),
        )

        self.assertEqual(
            agent_snapshot_from_wire(agent_snapshot_to_wire(agent_snapshot)),
            agent_snapshot,
        )
        self.assertEqual(
            inbox_snapshot_from_wire(inbox_snapshot_to_wire(inbox_snapshot)),
            inbox_snapshot,
        )

    def test_claim_from_wire_rejects_missing_required_fields_cleanly(self) -> None:
        with self.assertRaises(RuntimeError) as error:
            claim_from_wire(
                {
                    "agent_id": "agent-a",
                    "description": "Refactor auth flow",
                    "scope": ["src/auth"],
                    "status": "active",
                    "created_at": "2026-03-15T00:00:00Z",
                }
            )

        self.assertEqual(str(error.exception), "invalid_claim_payload")

    def test_event_from_wire_rejects_invalid_sequence_cleanly(self) -> None:
        with self.assertRaises(RuntimeError) as error:
            event_from_wire(
                {
                    "sequence": "not-an-int",
                    "id": "event_01",
                    "type": "claim.recorded",
                    "timestamp": "2026-03-15T00:00:00Z",
                    "actor_id": "agent-a",
                    "payload": {},
                }
            )

        self.assertEqual(str(error.exception), "invalid_event_payload")

    def test_context_from_wire_rejects_missing_required_fields_cleanly(self) -> None:
        with self.assertRaises(RuntimeError) as error:
            context_from_wire(
                {
                    "id": "context_01",
                    "agent_id": "agent-a",
                    "body": "Refresh token required.",
                    "scope": ["src/auth"],
                    "created_at": "2026-03-15T00:00:00Z",
                }
            )

        self.assertEqual(str(error.exception), "invalid_context_payload")

    def test_status_snapshot_from_wire_rejects_missing_required_lists_cleanly(self) -> None:
        with self.assertRaises(RuntimeError) as error:
            status_snapshot_from_wire(
                {
                    "intents": [],
                    "context": [],
                    "conflicts": [],
                }
            )

        self.assertEqual(str(error.exception), "invalid_status_snapshot_payload")

    def test_status_snapshot_from_wire_rejects_invalid_nested_claims_cleanly(self) -> None:
        with self.assertRaises(RuntimeError) as error:
            status_snapshot_from_wire(
                {
                    "claims": [
                        {
                            "agent_id": "agent-a",
                            "description": "Refactor auth flow",
                            "scope": ["src/auth"],
                            "status": "active",
                            "created_at": "2026-03-15T00:00:00Z",
                        }
                    ],
                    "intents": [],
                    "context": [],
                    "conflicts": [],
                }
            )

        self.assertEqual(str(error.exception), "invalid_status_snapshot_payload")


if __name__ == "__main__":
    unittest.main()
