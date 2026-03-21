from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import CoordinationStore  # noqa: E402


def init_repo_root(temp_dir: str) -> pathlib.Path:
    repo_root = pathlib.Path(temp_dir)
    git_dir = repo_root / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return repo_root


def write_file(repo_root: pathlib.Path, relative_path: str, contents: str) -> None:
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")


class StoreTest(unittest.TestCase):
    def test_nested_reuse_connection_rolls_back_all_changes_after_outer_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
                reuse_connections=True,
            )
            store.initialize()

            with self.assertRaisesRegex(RuntimeError, "boom"):
                with store._connect():
                    store.record_claim(
                        agent_id="agent-a",
                        description="Nested transaction claim",
                        scope=("src/auth",),
                        source="test",
                    )
                    raise RuntimeError("boom")

            snapshot = store.status()
            self.assertEqual(snapshot.claims, ())
            self.assertEqual(snapshot.intents, ())
            self.assertEqual(snapshot.context, ())
            self.assertEqual(snapshot.conflicts, ())
            self.assertEqual(store.list_events(limit=None), ())

    def test_renew_claim_preserves_policy_and_records_event_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T10:00:00Z"):
                claim, _ = store.record_claim(
                    agent_id="agent-a",
                    description="Background maintenance lane",
                    scope=("src/maintenance",),
                    source="test",
                    lease_minutes=30,
                    lease_policy="yield",
                )

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T10:05:00Z"):
                renewed = store.renew_claim(
                    agent_id="agent-a",
                    lease_minutes=45,
                    source="test",
                )

            assert renewed is not None
            self.assertEqual(renewed.id, claim.id)
            self.assertEqual(renewed.lease_policy, "yield")
            self.assertEqual(renewed.lease_expires_at, "2026-03-18T10:50:00Z")

            renewed_events = store.list_events(
                limit=None,
                event_type="claim.renewed",
                ascending=True,
            )
            self.assertEqual(len(renewed_events), 1)
            self.assertEqual(
                renewed_events[0].payload,
                {
                    "claim_id": claim.id,
                    "lease_expires_at": "2026-03-18T10:50:00Z",
                },
            )

    def test_renew_intent_preserves_policy_and_records_event_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T11:00:00Z"):
                claim, _ = store.record_claim(
                    agent_id="agent-a",
                    description="Auth migration lane",
                    scope=("src/auth",),
                    source="test",
                )
                intent, _ = store.record_intent(
                    agent_id="agent-a",
                    description="Broaden auth edits",
                    reason="Continue the migration work",
                    scope=("src/auth",),
                    source="test",
                    lease_minutes=30,
                    lease_policy="finish",
                )

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T11:05:00Z"):
                renewed = store.renew_intent(
                    agent_id="agent-a",
                    lease_minutes=45,
                    source="test",
                )

            assert renewed is not None
            self.assertEqual(renewed.id, intent.id)
            self.assertEqual(renewed.related_claim_id, claim.id)
            self.assertEqual(renewed.lease_policy, "finish")
            self.assertEqual(renewed.lease_expires_at, "2026-03-18T11:50:00Z")

            renewed_events = store.list_events(
                limit=None,
                event_type="intent.renewed",
                ascending=True,
            )
            self.assertEqual(len(renewed_events), 1)
            self.assertEqual(
                renewed_events[0].payload,
                {
                    "intent_id": intent.id,
                    "lease_expires_at": "2026-03-18T11:50:00Z",
                },
            )

    def test_adopt_agent_work_moves_active_claim_and_intent_to_bound_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T11:00:00Z"):
                claim, _ = store.record_claim(
                    agent_id="dev@host:pid-101",
                    description="Auth migration lane",
                    scope=("src/auth",),
                    source="tty",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T11:01:00Z"):
                intent, _ = store.record_intent(
                    agent_id="dev@host:pid-101",
                    description="Update auth handlers",
                    reason="Need a concrete edit plan",
                    scope=("src/auth/handlers.py",),
                    source="tty",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T11:02:00Z"):
                store.record_claim(
                    agent_id="agent-b",
                    description="Nearby auth work",
                    scope=("src/auth",),
                    source="test",
                )

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T11:03:00Z"):
                adoption = store.adopt_agent_work(
                    from_agent_id="dev@host:pid-101",
                    to_agent_id="agent-a",
                    source="terminal",
                )

            self.assertTrue(adoption["source_had_work"])
            self.assertFalse(adoption["target_had_work"])
            adopted_claim = adoption["adopted_claim"]
            adopted_intent = adoption["adopted_intent"]
            assert adopted_claim is not None
            assert adopted_intent is not None
            self.assertEqual(adopted_claim.id, claim.id)
            self.assertEqual(adopted_claim.agent_id, "agent-a")
            self.assertEqual(adopted_intent.id, intent.id)
            self.assertEqual(adopted_intent.agent_id, "agent-a")
            self.assertEqual(adopted_intent.related_claim_id, claim.id)

            self.assertIsNone(store.agent_snapshot(agent_id="dev@host:pid-101").claim)
            self.assertIsNone(store.agent_snapshot(agent_id="dev@host:pid-101").intent)
            self.assertEqual(store.agent_snapshot(agent_id="agent-a").claim.id, claim.id)
            self.assertEqual(store.agent_snapshot(agent_id="agent-a").intent.id, intent.id)

            active_conflicts = store.list_conflicts()
            self.assertEqual(len(active_conflicts), 2)
            self.assertTrue(all("agent-a" in conflict.summary for conflict in active_conflicts))
            self.assertTrue(
                all("dev@host:pid-101" not in conflict.summary for conflict in active_conflicts)
            )

            adopted_events = store.list_events(limit=None, ascending=True)
            self.assertEqual(
                tuple(event.type for event in adopted_events if event.type.endswith(".adopted")),
                ("claim.adopted", "intent.adopted"),
            )
            self.assertIn(
                {
                    "claim_id": claim.id,
                    "agent_id": "agent-a",
                },
                tuple(
                    event.payload
                    for event in adopted_events
                    if event.type == "claim.adopted"
                ),
            )
            self.assertIn(
                {
                    "intent_id": intent.id,
                    "agent_id": "agent-a",
                    "related_claim_id": claim.id,
                },
                tuple(
                    event.payload
                    for event in adopted_events
                    if event.type == "intent.adopted"
                ),
            )

    def test_release_claim_deactivates_related_conflicts_and_agent_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            claim_a, _ = store.record_claim(
                agent_id="agent-a",
                description="Auth migration lane",
                scope=("src/auth",),
                source="test",
            )
            claim_b, conflicts = store.record_claim(
                agent_id="agent-b",
                description="Nearby auth work",
                scope=("src/auth",),
                source="test",
            )

            self.assertEqual(len(conflicts), 1)
            self.assertEqual(len(store.agent_snapshot(agent_id="agent-b").conflicts), 1)

            released = store.release_claim(agent_id="agent-a")

            assert released is not None
            self.assertEqual(released.id, claim_a.id)
            self.assertEqual(released.status, "released")
            self.assertEqual(store.list_conflicts(), ())
            self.assertEqual(store.agent_snapshot(agent_id="agent-b").conflicts, ())

            archived_conflicts = store.list_conflicts_for_object(
                object_type="claim",
                object_id=claim_b.id,
                include_resolved=True,
            )
            self.assertEqual(len(archived_conflicts), 1)
            self.assertFalse(archived_conflicts[0].is_active)
            self.assertIsNone(archived_conflicts[0].resolved_at)
            self.assertIsNone(archived_conflicts[0].resolved_by)

            released_events = store.list_events(
                limit=None,
                event_type="claim.released",
                ascending=True,
            )
            self.assertEqual(len(released_events), 1)
            self.assertEqual(
                released_events[0].payload,
                {"claim_id": claim_a.id},
            )

    def test_release_intent_deactivates_related_conflicts_and_agent_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            store.record_claim(
                agent_id="agent-a",
                description="Auth migration lane",
                scope=("src/auth",),
                source="test",
            )
            intent_b, conflicts = store.record_intent(
                agent_id="agent-b",
                description="Broaden auth edits",
                reason="Need follow-up migration work",
                scope=("src/auth",),
                source="test",
            )

            self.assertEqual(len(conflicts), 1)
            self.assertEqual(len(store.agent_snapshot(agent_id="agent-a").conflicts), 1)

            released = store.release_intent(agent_id="agent-b")

            assert released is not None
            self.assertEqual(released.id, intent_b.id)
            self.assertEqual(released.status, "released")
            self.assertEqual(store.list_conflicts(), ())
            self.assertEqual(store.agent_snapshot(agent_id="agent-a").conflicts, ())

            archived_conflicts = store.list_conflicts_for_object(
                object_type="intent",
                object_id=intent_b.id,
                include_resolved=True,
            )
            self.assertEqual(len(archived_conflicts), 1)
            self.assertFalse(archived_conflicts[0].is_active)
            self.assertIsNone(archived_conflicts[0].resolved_at)
            self.assertIsNone(archived_conflicts[0].resolved_by)

            released_events = store.list_events(
                limit=None,
                event_type="intent.released",
                ascending=True,
            )
            self.assertEqual(len(released_events), 1)
            self.assertEqual(
                released_events[0].payload,
                {"intent_id": intent_b.id},
            )

    def test_prune_idle_agents_removes_only_agents_without_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            store.record_context(
                agent_id="idle-agent",
                topic="note",
                body="Historical note only.",
                scope=("docs",),
                source="test",
            )
            store.record_claim(
                agent_id="active-agent",
                description="Auth migration lane",
                scope=("src/auth",),
                source="test",
            )

            pruned = store.prune_idle_agents()

            self.assertEqual(pruned, ("idle-agent",))
            remaining_agents = tuple(
                presence.agent_id for presence in store.list_agents(limit=None)
            )
            self.assertEqual(remaining_agents, ("active-agent",))

    def test_resolve_conflict_is_idempotent_for_already_resolved_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            store.record_claim(
                agent_id="agent-a",
                description="Auth migration lane",
                scope=("src/auth",),
                source="test",
            )
            _claim_b, conflicts = store.record_claim(
                agent_id="agent-b",
                description="Nearby auth work",
                scope=("src/auth",),
                source="test",
            )

            first_resolution = store.resolve_conflict(
                conflict_id=conflicts[0].id,
                agent_id="reviewer",
                resolution_note="Handled already.",
            )
            second_resolution = store.resolve_conflict(
                conflict_id=conflicts[0].id,
                agent_id="someone-else",
                resolution_note="Should be ignored.",
            )

            assert first_resolution is not None
            assert second_resolution is not None
            self.assertEqual(second_resolution.id, first_resolution.id)
            self.assertEqual(second_resolution.resolved_by, "reviewer")
            self.assertEqual(second_resolution.resolution_note, "Handled already.")
            self.assertEqual(
                len(
                    tuple(
                        event
                        for event in store.list_events(limit=None, ascending=True)
                        if (
                            event.type == "conflict.resolved"
                            and event.payload.get("conflict_id") == conflicts[0].id
                        )
                    )
                ),
                1,
            )

    def test_dependency_scope_between_scopes_returns_semantic_link_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            write_file(
                repo_root,
                "src/auth/session.py",
                "class UserSession:\n    pass\n",
            )
            write_file(
                repo_root,
                "src/api/handlers.py",
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
            )
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            scope = store.dependency_scope_between_scopes(
                ("src/api/handlers.py",),
                ("src/auth/session.py",),
            )

            self.assertEqual(
                scope,
                ("src/api/handlers.py", "src/auth/session.py"),
            )

    def test_record_context_creates_semantic_context_dependency_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            write_file(
                repo_root,
                "src/auth/session.py",
                "class UserSession:\n    pass\n",
            )
            write_file(
                repo_root,
                "src/api/handlers.py",
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
            )
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()
            store.record_claim(
                agent_id="agent-b",
                description="Touch API handler",
                scope=("src/api/handlers.py",),
                source="test",
            )

            _context, conflicts = store.record_context(
                agent_id="agent-a",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth/session.py",),
                source="test",
            )

            self.assertEqual(len(conflicts), 1)
            conflict = conflicts[0]
            self.assertEqual(conflict.kind, "contextual_dependency")
            self.assertEqual(
                conflict.scope,
                ("src/api/handlers.py", "src/auth/session.py"),
            )
            self.assertIn("may depend on", conflict.summary)
            self.assertIn("src/api/handlers.py -> src/auth/session.py", conflict.summary)

    def test_acknowledge_context_upgrades_without_downgrading_and_preserves_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            claim, _ = store.record_claim(
                agent_id="agent-a",
                description="Auth migration lane",
                scope=("src/auth",),
                source="test",
            )
            intent, _ = store.record_intent(
                agent_id="agent-a",
                description="Broaden auth edits",
                reason="Continue the migration work",
                scope=("src/auth",),
                source="test",
            )
            context, _ = store.record_context(
                agent_id="agent-a",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth",),
                source="test",
            )

            first_ack = store.acknowledge_context(
                context_id=context.id,
                agent_id="agent-b",
                status="adapted",
                note="Shifted work away from auth middleware.",
            )
            second_ack = store.acknowledge_context(
                context_id=context.id,
                agent_id="agent-b",
                status="read",
            )

            assert first_ack is not None
            assert second_ack is not None
            self.assertEqual(first_ack.id, second_ack.id)
            self.assertEqual(second_ack.status, "adapted")
            self.assertEqual(
                second_ack.note,
                "Shifted work away from auth middleware.",
            )

            hydrated = store.get_context(context.id)
            assert hydrated is not None
            self.assertEqual(len(hydrated.acknowledgments), 1)
            self.assertEqual(hydrated.acknowledgments[0].agent_id, "agent-b")
            self.assertEqual(hydrated.acknowledgments[0].status, "adapted")
            self.assertEqual(
                hydrated.acknowledgments[0].note,
                "Shifted work away from auth middleware.",
            )

            claim_context = store.list_context_for_claim(claim.id)
            intent_context = store.list_context_for_intent(intent.id)
            self.assertEqual(len(claim_context), 1)
            self.assertEqual(len(intent_context), 1)
            self.assertEqual(claim_context[0].acknowledgments[0].status, "adapted")
            self.assertEqual(intent_context[0].acknowledgments[0].status, "adapted")

            ack_events = store.list_events(
                limit=None,
                event_type="context.acknowledged",
                ascending=True,
            )
            self.assertEqual(len(ack_events), 2)
            self.assertEqual(
                [event.payload for event in ack_events],
                [
                    {"context_id": context.id, "status": "adapted"},
                    {"context_id": context.id, "status": "adapted"},
                ],
            )

    def test_status_hydrates_acknowledgments_for_recent_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            store.record_claim(
                agent_id="agent-a",
                description="Auth migration lane",
                scope=("src/auth",),
                source="test",
            )
            store.record_intent(
                agent_id="agent-a",
                description="Broaden auth edits",
                reason="Continue the migration work",
                scope=("src/auth",),
                source="test",
            )
            context, _ = store.record_context(
                agent_id="agent-a",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth",),
                source="test",
            )
            store.acknowledge_context(
                context_id=context.id,
                agent_id="agent-b",
                status="adapted",
                note="Shifted work away from auth middleware.",
            )

            snapshot = store.status()

            self.assertEqual(len(snapshot.claims), 1)
            self.assertEqual(len(snapshot.intents), 1)
            self.assertEqual(len(snapshot.context), 1)
            self.assertEqual(snapshot.context[0].id, context.id)
            self.assertEqual(len(snapshot.context[0].acknowledgments), 1)
            self.assertEqual(snapshot.context[0].acknowledgments[0].agent_id, "agent-b")
            self.assertEqual(snapshot.context[0].acknowledgments[0].status, "adapted")
            self.assertEqual(
                snapshot.context[0].acknowledgments[0].note,
                "Shifted work away from auth middleware.",
            )

    def test_inbox_snapshot_excludes_acknowledged_context_but_keeps_conflict_attention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T13:00:00Z"):
                store.record_claim(
                    agent_id="agent-b",
                    description="Auth migration lane",
                    scope=("src/auth",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T13:01:00Z"):
                context, conflicts = store.record_context(
                    agent_id="agent-a",
                    topic="auth-interface-change",
                    body="UserSession now requires refresh_token.",
                    scope=("src/auth",),
                    source="test",
                )

            self.assertEqual(len(conflicts), 1)
            before_ack = store.inbox_snapshot(agent_id="agent-b")
            self.assertEqual([entry.id for entry in before_ack.pending_context], [context.id])
            self.assertEqual(len(before_ack.conflicts), 1)
            self.assertEqual(
                [event.type for event in before_ack.events],
                ["context.published", "conflict.detected"],
            )

            store.acknowledge_context(
                context_id=context.id,
                agent_id="agent-b",
                status="read",
            )

            after_ack = store.inbox_snapshot(agent_id="agent-b")
            self.assertEqual(after_ack.pending_context, ())
            self.assertEqual(len(after_ack.conflicts), 1)
            self.assertEqual(
                [event.type for event in after_ack.events],
                ["conflict.detected"],
            )

    def test_agent_snapshot_includes_semantic_incoming_context_and_related_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            write_file(
                repo_root,
                "src/auth/session.py",
                "class UserSession:\n    pass\n",
            )
            write_file(
                repo_root,
                "src/api/handlers.py",
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
            )
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T14:00:00Z"):
                claim_b, _ = store.record_claim(
                    agent_id="agent-b",
                    description="Touch API handler",
                    scope=("src/api/handlers.py",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T14:01:00Z"):
                context, conflicts = store.record_context(
                    agent_id="agent-a",
                    topic="auth-interface-change",
                    body="UserSession now requires refresh_token.",
                    scope=("src/auth/session.py",),
                    source="test",
                )

            self.assertEqual(len(conflicts), 1)

            snapshot = store.agent_snapshot(agent_id="agent-b")

            assert snapshot.claim is not None
            self.assertEqual(snapshot.claim.id, claim_b.id)
            self.assertIsNone(snapshot.intent)
            self.assertEqual([entry.id for entry in snapshot.incoming_context], [context.id])
            self.assertEqual(snapshot.incoming_context[0].acknowledgments, ())
            self.assertEqual(len(snapshot.conflicts), 1)
            self.assertEqual(snapshot.conflicts[0].kind, "contextual_dependency")
            self.assertEqual(
                [event.type for event in snapshot.events],
                ["claim.recorded", "context.published", "conflict.detected"],
            )

    def test_latest_resolved_conflict_between_references_returns_newest_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-17T10:00:00Z"):
                claim_a, _ = store.record_claim(
                    agent_id="agent-a",
                    description="Auth migration lane",
                    scope=("src/auth",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-17T10:01:00Z"):
                claim_b, first_conflicts = store.record_claim(
                    agent_id="agent-b",
                    description="Nearby auth work",
                    scope=("src/auth",),
                    source="test",
                )
            self.assertEqual(len(first_conflicts), 1)
            with patch("loom.local_store.store.utc_now", return_value="2026-03-17T10:02:00Z"):
                first_resolved = store.resolve_conflict(
                    conflict_id=first_conflicts[0].id,
                    agent_id="reviewer",
                    resolution_note="Acknowledged first overlap.",
                )
            self.assertIsNotNone(first_resolved)

            with patch("loom.local_store.store.utc_now", return_value="2026-03-17T10:03:00Z"):
                intent_b, second_conflicts = store.record_intent(
                    agent_id="agent-b",
                    description="Broaden auth edits",
                    reason="Need follow-up migration work",
                    scope=("src/auth",),
                    source="test",
                )
            self.assertEqual(len(second_conflicts), 1)
            with patch("loom.local_store.store.utc_now", return_value="2026-03-17T10:04:00Z"):
                second_resolved = store.resolve_conflict(
                    conflict_id=second_conflicts[0].id,
                    agent_id="reviewer",
                    resolution_note="Acknowledged newer overlap.",
                )
            self.assertIsNotNone(second_resolved)

            latest = store.latest_resolved_conflict_between_references(
                left_refs=(("claim", claim_a.id),),
                right_refs=(("claim", claim_b.id), ("intent", intent_b.id)),
            )
            reversed_latest = store.latest_resolved_conflict_between_references(
                left_refs=(("claim", claim_b.id), ("intent", intent_b.id)),
                right_refs=(("claim", claim_a.id),),
            )

            self.assertIsNotNone(latest)
            self.assertIsNotNone(reversed_latest)
            assert latest is not None
            assert reversed_latest is not None
            self.assertEqual(latest.id, second_conflicts[0].id)
            self.assertEqual(reversed_latest.id, second_conflicts[0].id)
            self.assertEqual(latest.resolution_note, "Acknowledged newer overlap.")

    def test_agent_event_feed_uses_latest_relevant_sequence_not_global_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T12:00:00Z"):
                store.record_claim(
                    agent_id="agent-a",
                    description="Auth migration lane",
                    scope=("src/auth",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T12:01:00Z"):
                store.record_intent(
                    agent_id="agent-a",
                    description="Broaden auth edits",
                    reason="Continue the migration work",
                    scope=("src/auth",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T12:02:00Z"):
                store.record_context(
                    agent_id="agent-a",
                    topic="auth-migration-note",
                    body="Need to update the handler contract.",
                    scope=("src/auth",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T12:03:00Z"):
                store.record_claim(
                    agent_id="agent-b",
                    description="Unrelated billing work",
                    scope=("src/billing",),
                    source="test",
                )

            first_page, latest_sequence = store.agent_event_feed(
                agent_id="agent-a",
                limit=1,
                ascending=True,
            )

            self.assertEqual([event.type for event in first_page], ["claim.recorded"])
            self.assertEqual(latest_sequence, 3)

            follow_up, follow_up_latest = store.agent_event_feed(
                agent_id="agent-a",
                after_sequence=first_page[0].sequence,
                limit=10,
                ascending=True,
            )

            self.assertEqual(
                [event.type for event in follow_up],
                ["intent.declared", "context.published"],
            )
            self.assertEqual(follow_up_latest, 3)

    def test_list_agents_orders_by_last_seen_and_attaches_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T15:00:00Z"):
                claim_a, _ = store.record_claim(
                    agent_id="agent-a",
                    description="Auth migration lane",
                    scope=("src/auth",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T15:01:00Z"):
                claim_b, _ = store.record_claim(
                    agent_id="agent-b",
                    description="Billing lane",
                    scope=("src/billing",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T15:02:00Z"):
                intent_b, _ = store.record_intent(
                    agent_id="agent-b",
                    description="Broaden billing edits",
                    reason="Need follow-up API work",
                    scope=("src/billing",),
                    source="test",
                )
            with patch("loom.local_store.store.utc_now", return_value="2026-03-18T15:03:00Z"):
                store.renew_claim(
                    agent_id="agent-a",
                    lease_minutes=30,
                    source="test",
                )

            agents = store.list_agents(limit=None)

            self.assertEqual([agent.agent_id for agent in agents], ["agent-a", "agent-b"])
            self.assertEqual(agents[0].last_seen_at, "2026-03-18T15:03:00Z")
            self.assertEqual(agents[0].claim.id if agents[0].claim else None, claim_a.id)
            self.assertIsNone(agents[0].intent)
            self.assertEqual(agents[1].last_seen_at, "2026-03-18T15:02:00Z")
            self.assertEqual(agents[1].claim.id if agents[1].claim else None, claim_b.id)
            self.assertEqual(agents[1].intent.id if agents[1].intent else None, intent_b.id)

            limited_agents = store.list_agents(limit=1)
            self.assertEqual([agent.agent_id for agent in limited_agents], ["agent-a"])

    def test_list_conflicts_for_object_excludes_resolved_conflicts_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            claim_a, _ = store.record_claim(
                agent_id="agent-a",
                description="Auth migration lane",
                scope=("src/auth",),
                source="test",
            )
            _claim_b, conflicts = store.record_claim(
                agent_id="agent-b",
                description="Nearby auth work",
                scope=("src/auth",),
                source="test",
            )

            self.assertEqual(
                len(
                    store.list_conflicts_for_object(
                        object_type="claim",
                        object_id=claim_a.id,
                        include_resolved=False,
                    )
                ),
                1,
            )

            store.resolve_conflict(
                conflict_id=conflicts[0].id,
                agent_id="reviewer",
                resolution_note="Resolved for lane planning.",
            )

            self.assertEqual(
                store.list_conflicts_for_object(
                    object_type="claim",
                    object_id=claim_a.id,
                    include_resolved=False,
                ),
                (),
            )
            resolved = store.list_conflicts_for_object(
                object_type="claim",
                object_id=claim_a.id,
                include_resolved=True,
            )
            self.assertEqual(len(resolved), 1)
            self.assertFalse(resolved[0].is_active)
            self.assertEqual(resolved[0].resolution_note, "Resolved for lane planning.")


if __name__ == "__main__":
    unittest.main()
