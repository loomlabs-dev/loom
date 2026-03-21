from __future__ import annotations

import json
import pathlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import (  # noqa: E402
    AgentPresenceRecord,
    AgentSnapshot,
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    EventRecord,
    InboxSnapshot,
    IntentRecord,
    StatusSnapshot,
)
from loom.mcp_readers import (  # noqa: E402
    read_activity_feed_resource_for,
    read_agent_resource_for,
    read_agents_resource,
    read_events_after_resource,
    read_status_resource,
)


def make_claim(*, claim_id: str, agent_id: str) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        agent_id=agent_id,
        description="Claimed work",
        scope=("src/api.py",),
        status="active",
        created_at="2026-03-18T12:00:00Z",
        git_branch="main",
    )


def make_intent(*, intent_id: str, agent_id: str, claim_id: str) -> IntentRecord:
    return IntentRecord(
        id=intent_id,
        agent_id=agent_id,
        description="Edit api",
        reason="Because",
        scope=("src/api.py",),
        status="active",
        created_at="2026-03-18T12:05:00Z",
        related_claim_id=claim_id,
        git_branch="main",
    )


def make_context(*, context_id: str, agent_id: str, claim_id: str, intent_id: str) -> ContextRecord:
    return ContextRecord(
        id=context_id,
        agent_id=agent_id,
        topic="handoff",
        body="body",
        scope=("src/api.py",),
        created_at="2026-03-18T12:10:00Z",
        related_claim_id=claim_id,
        related_intent_id=intent_id,
        git_branch="main",
    )


def make_conflict(*, conflict_id: str, claim_id: str, intent_id: str) -> ConflictRecord:
    return ConflictRecord(
        id=conflict_id,
        kind="semantic_overlap",
        severity="warning",
        summary="Overlap",
        object_type_a="claim",
        object_id_a=claim_id,
        object_type_b="intent",
        object_id_b=intent_id,
        scope=("src/api.py",),
        created_at="2026-03-18T12:15:00Z",
    )


def make_event(*, sequence: int, actor_id: str) -> EventRecord:
    return EventRecord(
        sequence=sequence,
        id=f"event_{sequence}",
        type="claim.created",
        timestamp="2026-03-18T12:20:00Z",
        actor_id=actor_id,
        payload={"claim_id": "claim_123"},
    )


class _FakeStore:
    def __init__(self) -> None:
        self.latest_sequence = 0
        self.agent_feed: tuple[tuple[EventRecord, ...], int] = ((), 0)

    def latest_event_sequence(self) -> int:
        return self.latest_sequence

    def agent_event_feed(
        self,
        *,
        agent_id: str,
        context_limit: int,
        limit: int,
        after_sequence: int,
        ascending: bool,
    ) -> tuple[tuple[EventRecord, ...], int]:
        return self.agent_feed


class _FakeClient:
    def __init__(self) -> None:
        self.project = pathlib.Path("/repo")
        self.store = _FakeStore()
        self._status = StatusSnapshot((), (), (), ())
        self._agents: tuple[object, ...] = ()
        self._events: tuple[EventRecord, ...] = ()
        self._daemon = {"running": False}
        self.status_agent_limit: int | None = None

    def daemon_status(self) -> dict[str, object]:
        return self._daemon

    def read_status(self) -> StatusSnapshot:
        return self._status

    def read_agents(self, *, limit: int) -> tuple[object, ...]:
        self.status_agent_limit = limit
        return self._agents

    def read_events(
        self,
        *,
        limit: int,
        event_type: str | None,
        after_sequence: int | None,
        ascending: bool,
    ) -> tuple[EventRecord, ...]:
        return self._events


class _FakeServer:
    def __init__(self, client: _FakeClient) -> None:
        self.client = client
        self.identity = {"id": "agent-a", "source": "env", "stable_terminal_identity": True}
        self.agent_payload: dict[str, object] | None = None

    def _client_for_tools(self) -> _FakeClient:
        return self.client

    def _identity_payload(self, client: _FakeClient) -> dict[str, object]:
        return dict(self.identity)

    def _event_payloads(self, events: tuple[EventRecord, ...]) -> list[dict[str, object]]:
        return [self._event_payload(event) for event in events]

    def _event_payload(self, event: EventRecord) -> dict[str, object]:
        return {
            "sequence": event.sequence,
            "id": event.id,
            "type": event.type,
            "actor_id": event.actor_id,
        }

    def _event_uri(self, sequence: int) -> str:
        return f"loom://event/{sequence}"

    def _agent_runtime_payload(
        self,
        *,
        client: _FakeClient,
        agent_id: str,
        context_limit: int,
        event_limit: int,
    ) -> dict[str, object]:
        assert self.agent_payload is not None
        return self.agent_payload

    def _dead_session_agent_ids(self, agents: tuple[object, ...]) -> tuple[str, ...]:
        return ()


class McpReadersTest(unittest.TestCase):
    def test_read_status_resource_includes_repo_lanes_and_current_agent_links(self) -> None:
        client = _FakeClient()
        claim = make_claim(claim_id="claim_123", agent_id="agent-a")
        intent = make_intent(intent_id="intent_123", agent_id="agent-a", claim_id=claim.id)
        context = make_context(
            context_id="context_123",
            agent_id="agent-a",
            claim_id=claim.id,
            intent_id=intent.id,
        )
        conflict = make_conflict(
            conflict_id="conflict_123",
            claim_id=claim.id,
            intent_id=intent.id,
        )
        client._status = StatusSnapshot((claim,), (intent,), (context,), (conflict,))
        client._agents = (SimpleNamespace(agent_id="agent-a"),)
        server = _FakeServer(client)

        with (
            patch("loom.mcp_readers.guidance_stale_agent_ids", return_value={"agent-stale"}),
            patch(
                "loom.mcp_readers.guidance_repo_lanes_payload",
                return_value={
                    "counts": {"acknowledged_migration_lanes": 1},
                    "lanes": [],
                    "programs": [],
                },
            ),
            patch(
                "loom.mcp_readers._tool_status_action",
                return_value={"tool": "loom_claim", "arguments": {}},
            ),
            patch(
                "loom.mcp_readers._tool_status_next_steps",
                return_value=("step one", "step two"),
            ),
        ):
            payload = read_status_resource(server, status_agent_activity_limit=7)

        body = json.loads(payload["text"])
        self.assertEqual(client.status_agent_limit, 7)
        self.assertEqual(body["authority"]["status"], "absent")
        self.assertEqual(body["repo_lanes"]["counts"]["acknowledged_migration_lanes"], 1)
        self.assertEqual(body["next_action"]["tool"], "loom_claim")
        self.assertEqual(body["next_steps"], ["step one", "step two"])
        self.assertEqual(body["links"]["current_agent"], "loom://agent/agent-a")
        self.assertEqual(body["links"]["claims"], ["loom://claim/claim_123"])
        self.assertEqual(body["links"]["intents"], ["loom://intent/intent_123"])
        self.assertEqual(body["links"]["context"], ["loom://context/context_123"])
        self.assertEqual(body["links"]["active_conflicts"], ["loom://conflict/conflict_123"])

    def test_read_agent_resource_for_includes_runtime_action_and_related_links(self) -> None:
        client = _FakeClient()
        claim = make_claim(claim_id="claim_123", agent_id="agent-a")
        intent = make_intent(intent_id="intent_123", agent_id="agent-a", claim_id=claim.id)
        context = make_context(
            context_id="context_123",
            agent_id="agent-a",
            claim_id=claim.id,
            intent_id=intent.id,
        )
        conflict = make_conflict(
            conflict_id="conflict_123",
            claim_id=claim.id,
            intent_id=intent.id,
        )
        agent = AgentSnapshot(
            agent_id="agent-a",
            claim=claim,
            intent=intent,
            published_context=(context,),
            incoming_context=(context,),
            conflicts=(conflict,),
            events=(make_event(sequence=5, actor_id="agent-a"),),
        )
        server = _FakeServer(client)
        server.agent_payload = {
            "agent": agent,
            "active_work": {"started_at": "2026-03-18T12:30:00Z"},
            "recovery": {
                "started_at": "2026-03-18T12:30:00Z",
                "yield_alert": {"policy": "yield"},
                "lease_alert": None,
                "priority": None,
                "pending_context": (),
            },
            "worktree": {"has_drift": False, "changed_paths": ("src/api.py",)},
        }

        with (
            patch(
                "loom.mcp_readers._tool_agent_action",
                return_value={"tool": "loom_finish", "arguments": {}},
            ),
            patch(
                "loom.mcp_readers._tool_agent_next_steps",
                return_value=("step finish", "step inbox"),
            ),
        ):
            payload = read_agent_resource_for(
                server,
                uri="loom://agent/agent-a",
                agent_id="agent-a",
            )

        body = json.loads(payload["text"])
        self.assertEqual(body["next_action"]["tool"], "loom_finish")
        self.assertEqual(body["next_steps"], ["step finish", "step inbox"])
        self.assertEqual(body["links"]["claim"], "loom://claim/claim_123")
        self.assertEqual(body["links"]["intent"], "loom://intent/intent_123")
        self.assertEqual(body["links"]["published_context"], ["loom://context/context_123"])
        self.assertEqual(body["links"]["incoming_context"], ["loom://context/context_123"])
        self.assertEqual(body["links"]["conflicts"], ["loom://conflict/conflict_123"])

    def test_read_agents_resource_hides_idle_history_by_default(self) -> None:
        client = _FakeClient()
        active_claim = make_claim(claim_id="claim_1", agent_id="agent-a")
        client._agents = (
            AgentPresenceRecord(
                agent_id="agent-a",
                source="project",
                created_at="2026-03-18T12:00:00Z",
                last_seen_at="2026-03-18T12:30:00Z",
                claim=active_claim,
                intent=None,
            ),
            AgentPresenceRecord(
                agent_id="agent-idle",
                source="project",
                created_at="2026-03-18T11:00:00Z",
                last_seen_at="2026-03-18T11:30:00Z",
                claim=None,
                intent=None,
            ),
        )
        server = _FakeServer(client)

        payload = read_agents_resource(server)

        body = json.loads(payload["text"])
        self.assertEqual([entry["agent_id"] for entry in body["agents"]], ["agent-a"])
        self.assertFalse(body["showing_idle_history"])
        self.assertEqual(body["idle_history_hidden_count"], 1)
        self.assertEqual(body["links"]["agent_views"], ["loom://agent/agent-a"])
        self.assertEqual(
            body["next_steps"][0],
            "Call loom_agents with include_idle=true to inspect idle agent history.",
        )

    def test_read_events_after_resource_uses_latest_sequence_and_resume_cursor(self) -> None:
        client = _FakeClient()
        client.store.latest_sequence = 20
        client._events = (
            make_event(sequence=11, actor_id="agent-a"),
            make_event(sequence=15, actor_id="agent-b"),
        )
        server = _FakeServer(client)

        payload = read_events_after_resource(
            server,
            uri="loom://events/after/10",
            after_sequence=10,
        )

        body = json.loads(payload["text"])
        self.assertEqual(body["after_sequence"], 10)
        self.assertEqual(body["latest_sequence"], 20)
        self.assertEqual(body["resume_after_sequence"], 15)
        self.assertEqual(body["links"]["resume"], "loom://events/after/15")
        self.assertEqual(body["links"]["events"], ["loom://event/11", "loom://event/15"])

    def test_read_activity_feed_resource_for_clamps_latest_relevant_sequence_to_cursor(self) -> None:
        client = _FakeClient()
        client.store.agent_feed = ((), 9)
        server = _FakeServer(client)

        payload = read_activity_feed_resource_for(
            server,
            uri="loom://activity/agent-a/after/12",
            agent_id="agent-a",
            after_sequence=12,
        )

        body = json.loads(payload["text"])
        self.assertEqual(body["agent_id"], "agent-a")
        self.assertEqual(body["after_sequence"], 12)
        self.assertEqual(body["latest_relevant_sequence"], 12)
        self.assertEqual(body["resume_after_sequence"], 12)
        self.assertEqual(body["links"]["resume"], "loom://activity/agent-a/after/12")


if __name__ == "__main__":
    unittest.main()
