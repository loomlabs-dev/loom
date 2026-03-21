from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.guidance import (  # noqa: E402
    active_work_nearby_yield_alert,
    agent_recommendation,
    claim_recommendation,
    repo_lanes_payload,
    start_recommendation,
    start_summary,
    status_recommendation,
)
from loom.local_store import (  # noqa: E402
    AgentPresenceRecord,
    ClaimRecord,
    ConflictRecord,
    IntentRecord,
    StatusSnapshot,
)


FUTURE_LEASE = "2099-01-01T00:00:00Z"
EXPIRED_LEASE = "2000-01-01T00:00:00Z"


def make_claim(
    *,
    claim_id: str,
    agent_id: str,
    scope: tuple[str, ...],
    created_at: str,
    lease_expires_at: str | None = None,
    lease_policy: str | None = None,
    status: str = "active",
    description: str = "Claimed work",
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        agent_id=agent_id,
        description=description,
        scope=scope,
        status=status,
        created_at=created_at,
        git_branch="main",
        lease_expires_at=lease_expires_at,
        lease_policy=lease_policy,
    )


def make_intent(
    *,
    intent_id: str,
    agent_id: str,
    scope: tuple[str, ...],
    created_at: str,
    related_claim_id: str | None = None,
    lease_expires_at: str | None = None,
    lease_policy: str | None = None,
    status: str = "active",
    description: str = "Declared intent",
    reason: str = "Need to edit this surface",
) -> IntentRecord:
    return IntentRecord(
        id=intent_id,
        agent_id=agent_id,
        description=description,
        reason=reason,
        scope=scope,
        status=status,
        created_at=created_at,
        related_claim_id=related_claim_id,
        git_branch="main",
        lease_expires_at=lease_expires_at,
        lease_policy=lease_policy,
    )


def make_conflict(
    *,
    conflict_id: str,
    left_type: str,
    left_id: str,
    right_type: str,
    right_id: str,
    scope: tuple[str, ...],
    resolved_at: str,
) -> ConflictRecord:
    return ConflictRecord(
        id=conflict_id,
        kind="scope_overlap",
        severity="warning",
        summary="Acknowledged overlap",
        object_type_a=left_type,
        object_id_a=left_id,
        object_type_b=right_type,
        object_id_b=right_id,
        scope=scope,
        created_at="2026-03-17T10:30:00Z",
        is_active=False,
        resolved_at=resolved_at,
        resolved_by="agent-review",
        resolution_note="Acknowledged migration lane.",
    )


def make_presence(
    *,
    agent_id: str,
    claim: ClaimRecord | None = None,
    intent: IntentRecord | None = None,
    last_seen_at: str = "2026-03-17T12:00:00Z",
) -> AgentPresenceRecord:
    return AgentPresenceRecord(
        agent_id=agent_id,
        source="test",
        created_at="2026-03-17T09:00:00Z",
        last_seen_at=last_seen_at,
        claim=claim,
        intent=intent,
    )


def make_snapshot(
    *,
    claims: tuple[ClaimRecord, ...] = (),
    intents: tuple[IntentRecord, ...] = (),
    conflicts: tuple[ConflictRecord, ...] = (),
) -> StatusSnapshot:
    return StatusSnapshot(
        claims=claims,
        intents=intents,
        context=(),
        conflicts=conflicts,
    )


class FakeGuidanceStore:
    def __init__(
        self,
        *,
        dependency_scopes: dict[
            tuple[tuple[str, ...], tuple[str, ...]],
            tuple[str, ...],
        ] | None = None,
        resolved_conflicts: dict[
            tuple[tuple[str, str], tuple[str, str]],
            ConflictRecord,
        ] | None = None,
    ) -> None:
        self._dependency_scopes = dependency_scopes or {}
        self._resolved_conflicts = resolved_conflicts or {}

    def dependency_scope_between_scopes(
        self,
        left_scope: tuple[str, ...],
        right_scope: tuple[str, ...],
    ) -> tuple[str, ...]:
        left_key = tuple(left_scope)
        right_key = tuple(right_scope)
        return self._dependency_scopes.get(
            (left_key, right_key),
            self._dependency_scopes.get((right_key, left_key), ()),
        )

    def latest_resolved_conflict_between_references(
        self,
        *,
        left_refs: tuple[tuple[str, str], ...],
        right_refs: tuple[tuple[str, str], ...],
    ) -> ConflictRecord | None:
        for left_ref in left_refs:
            for right_ref in right_refs:
                key = tuple(sorted((tuple(left_ref), tuple(right_ref))))
                conflict = self._resolved_conflicts.get(key)
                if conflict is not None:
                    return conflict
        return None


class GuidanceTest(unittest.TestCase):
    def test_agent_recommendation_prefers_finish_when_expired_lease_work_is_settled(self) -> None:
        claim = make_claim(
            claim_id="claim-expired",
            agent_id="agent-a",
            scope=("src/api",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=EXPIRED_LEASE,
            lease_policy="renew",
        )

        recommendation = agent_recommendation(
            agent_id="agent-a",
            claim=claim,
            intent=None,
            has_published_context=False,
            active_work={
                "started_at": "2026-03-17T10:00:00Z",
                "needs_attention": True,
                "lease_alert": {
                    "policy": "renew",
                    "next_step": "loom renew",
                    "tool_name": "loom_renew",
                    "tool_arguments": {"agent_id": "agent-a"},
                    "summary": "Renew the expired claim lease before continuing current work.",
                    "reason": "Loom found active work whose coordination lease has expired.",
                    "confidence": "high",
                },
                "yield_alert": None,
                "priority": None,
            },
            worktree_signal={
                "has_drift": False,
                "changed_paths": (),
            },
        )

        self.assertEqual(recommendation["tool_name"], "loom_finish")
        self.assertEqual(recommendation["command"], "loom finish")

    def test_agent_recommendation_prefers_yield_alert_over_priority(self) -> None:
        recommendation = agent_recommendation(
            agent_id="agent-a",
            claim=make_claim(
                claim_id="claim-yield",
                agent_id="agent-a",
                scope=("src/api",),
                created_at="2026-03-17T10:00:00Z",
                lease_expires_at=FUTURE_LEASE,
                lease_policy="yield",
            ),
            intent=None,
            has_published_context=False,
            active_work={
                "started_at": "2026-03-17T10:00:00Z",
                "needs_attention": True,
                "lease_alert": None,
                "yield_alert": {
                    "policy": "yield",
                    "next_step": "loom finish",
                    "tool_name": "loom_finish",
                    "tool_arguments": {"agent_id": "agent-a"},
                    "summary": "Yield the current leased work before continuing.",
                    "reason": "Loom found higher-priority coordination pressure.",
                    "confidence": "high",
                    "urgency": "fresh",
                },
                "priority": {
                    "kind": "conflict",
                    "id": "conflict-01",
                    "next_step": "loom resolve conflict-01",
                    "tool_name": "loom_resolve",
                    "tool_arguments": {"conflict_id": "conflict-01"},
                    "summary": "Resolve the conflict.",
                    "reason": "Conflict needs attention.",
                    "confidence": "high",
                },
            },
            worktree_signal={"has_drift": False, "changed_paths": ()},
        )

        self.assertEqual(recommendation["kind"], "yield")
        self.assertEqual(recommendation["tool_name"], "loom_finish")

    def test_active_work_nearby_yield_alert_prefers_acknowledged_dependency_pressure(self) -> None:
        claim = make_claim(
            claim_id="claim-a",
            agent_id="agent-a",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
            description="Background API cleanup",
        )
        intent = make_intent(
            intent_id="intent-a",
            agent_id="agent-a",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:05:00Z",
            related_claim_id=claim.id,
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
            description="Touch API handler response shape",
        )
        nearby_claim = make_claim(
            claim_id="claim-b",
            agent_id="agent-b",
            scope=("src/auth/session.py",),
            created_at="2026-03-17T10:45:00Z",
            description="Refactor auth session model",
        )
        nearby_intent = make_intent(
            intent_id="intent-c",
            agent_id="agent-c",
            scope=("src/api",),
            created_at="2026-03-17T10:50:00Z",
            description="Touch broader API surface",
        )
        snapshot = make_snapshot(
            claims=(claim, nearby_claim),
            intents=(intent, nearby_intent),
        )
        store = FakeGuidanceStore(
            dependency_scopes={
                (
                    ("src/api/handlers.py",),
                    ("src/auth/session.py",),
                ): ("src/api/handlers.py", "src/auth/session.py"),
            },
            resolved_conflicts={
                tuple(
                    sorted(
                        (
                            ("claim", claim.id),
                            ("claim", nearby_claim.id),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-semantic",
                    left_type="claim",
                    left_id=claim.id,
                    right_type="claim",
                    right_id=nearby_claim.id,
                    scope=("src/api/handlers.py", "src/auth/session.py"),
                    resolved_at="2026-03-17T11:00:00Z",
                ),
                tuple(
                    sorted(
                        (
                            ("intent", intent.id),
                            ("intent", nearby_intent.id),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-scope",
                    left_type="intent",
                    left_id=intent.id,
                    right_type="intent",
                    right_id=nearby_intent.id,
                    scope=("src/api",),
                    resolved_at="2026-03-17T11:02:00Z",
                ),
            },
        )

        alert = active_work_nearby_yield_alert(
            agent_id="agent-a",
            claim=claim,
            intent=intent,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=set(),
        )

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertEqual(alert["policy"], "yield")
        self.assertTrue(alert["acknowledged"])
        self.assertEqual(alert["urgency"], "fresh")
        self.assertEqual(alert["confidence"], "medium")
        self.assertEqual(alert["nearby"][0]["relationship"], "dependency")
        self.assertTrue(alert["nearby"][0]["acknowledged"])
        self.assertEqual(alert["nearby"][0]["risk"], "high")
        self.assertIn("fresh acknowledged nearby active work", str(alert["reason"]))
        self.assertIn("semantically entangled", str(alert["reason"]))

    def test_active_work_nearby_yield_alert_ignores_stale_and_expired_nearby_records(self) -> None:
        claim = make_claim(
            claim_id="claim-a",
            agent_id="agent-a",
            scope=("src/auth/session",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        intent = make_intent(
            intent_id="intent-a",
            agent_id="agent-a",
            scope=("src/auth/session",),
            created_at="2026-03-17T10:05:00Z",
            related_claim_id=claim.id,
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        stale_claim = make_claim(
            claim_id="claim-stale",
            agent_id="agent-stale",
            scope=("src/auth/session",),
            created_at="2026-03-17T10:10:00Z",
        )
        expired_intent = make_intent(
            intent_id="intent-expired",
            agent_id="agent-expired",
            scope=("src/auth/session",),
            created_at="2026-03-17T10:12:00Z",
            lease_expires_at=EXPIRED_LEASE,
            lease_policy="yield",
        )
        snapshot = make_snapshot(
            claims=(claim, stale_claim),
            intents=(intent, expired_intent),
        )

        alert = active_work_nearby_yield_alert(
            agent_id="agent-a",
            claim=claim,
            intent=intent,
            snapshot=snapshot,
            store=FakeGuidanceStore(),
            stale_agent_ids={"agent-stale"},
        )

        self.assertIsNone(alert)

    def test_active_work_nearby_yield_alert_uses_high_confidence_for_unacknowledged_fresh_dependency_pressure(self) -> None:
        claim = make_claim(
            claim_id="claim-a",
            agent_id="agent-a",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        nearby_claim = make_claim(
            claim_id="claim-b",
            agent_id="agent-b",
            scope=("src/auth/session.py",),
            created_at="2026-03-17T10:45:00Z",
            description="Refactor auth session model",
        )
        snapshot = make_snapshot(claims=(claim, nearby_claim))
        store = FakeGuidanceStore(
            dependency_scopes={
                (
                    ("src/api/handlers.py",),
                    ("src/auth/session.py",),
                ): ("src/api/handlers.py", "src/auth/session.py"),
            },
        )

        alert = active_work_nearby_yield_alert(
            agent_id="agent-a",
            claim=claim,
            intent=None,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=set(),
        )

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertFalse(alert["acknowledged"])
        self.assertEqual(alert["urgency"], "fresh")
        self.assertEqual(alert["confidence"], "high")
        self.assertEqual(alert["nearby"][0]["relationship"], "dependency")
        self.assertIn("fresh nearby active work", str(alert["reason"]))

    def test_active_work_nearby_yield_alert_ignores_broad_parent_scope_only_pressure(self) -> None:
        claim = make_claim(
            claim_id="claim-a",
            agent_id="agent-a",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        nearby_claim = make_claim(
            claim_id="claim-b",
            agent_id="agent-b",
            scope=("src/api",),
            created_at="2026-03-17T10:30:00Z",
            description="Touch broad api surface",
        )
        snapshot = make_snapshot(claims=(claim, nearby_claim))

        alert = active_work_nearby_yield_alert(
            agent_id="agent-a",
            claim=claim,
            intent=None,
            snapshot=snapshot,
            store=FakeGuidanceStore(),
            stale_agent_ids=set(),
        )

        self.assertIsNone(alert)

    def test_repo_lanes_payload_groups_shared_feature_family_into_program(self) -> None:
        claim_a = make_claim(
            claim_id="claim-a",
            agent_id="agent-a",
            scope=("src/auth/session",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        intent_a = make_intent(
            intent_id="intent-a",
            agent_id="agent-a",
            scope=("src/auth/session",),
            created_at="2026-03-17T10:05:00Z",
            related_claim_id=claim_a.id,
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        intent_b = make_intent(
            intent_id="intent-b",
            agent_id="agent-b",
            scope=("src/auth/session",),
            created_at="2026-03-17T10:10:00Z",
        )
        claim_c = make_claim(
            claim_id="claim-c",
            agent_id="agent-c",
            scope=("src/auth/validation",),
            created_at="2026-03-17T10:15:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        intent_c = make_intent(
            intent_id="intent-c",
            agent_id="agent-c",
            scope=("src/auth/validation",),
            created_at="2026-03-17T10:20:00Z",
            related_claim_id=claim_c.id,
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        intent_d = make_intent(
            intent_id="intent-d",
            agent_id="agent-d",
            scope=("src/auth/validation",),
            created_at="2026-03-17T10:25:00Z",
        )
        agents = (
            make_presence(agent_id="agent-a", claim=claim_a, intent=intent_a),
            make_presence(agent_id="agent-b", intent=intent_b),
            make_presence(agent_id="agent-c", claim=claim_c, intent=intent_c),
            make_presence(agent_id="agent-d", intent=intent_d),
        )
        snapshot = make_snapshot(
            claims=(claim_a, claim_c),
            intents=(intent_a, intent_b, intent_c, intent_d),
        )
        store = FakeGuidanceStore(
            resolved_conflicts={
                tuple(
                    sorted(
                        (
                            ("claim", claim_a.id),
                            ("intent", intent_b.id),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-auth-session",
                    left_type="claim",
                    left_id=claim_a.id,
                    right_type="intent",
                    right_id=intent_b.id,
                    scope=("src/auth/session",),
                    resolved_at="2026-03-17T10:30:00Z",
                ),
                tuple(
                    sorted(
                        (
                            ("claim", claim_c.id),
                            ("intent", intent_d.id),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-auth-validation",
                    left_type="claim",
                    left_id=claim_c.id,
                    right_type="intent",
                    right_id=intent_d.id,
                    scope=("src/auth/validation",),
                    resolved_at="2026-03-17T10:31:00Z",
                ),
            }
        )

        payload = repo_lanes_payload(
            agents=agents,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=set(),
        )

        self.assertEqual(payload["acknowledged_migration_lanes"], 2)
        self.assertEqual(payload["fresh_acknowledged_migration_lanes"], 2)
        self.assertEqual(payload["ongoing_acknowledged_migration_lanes"], 0)
        self.assertEqual(payload["acknowledged_migration_programs"], 1)
        self.assertEqual(payload["fresh_acknowledged_migration_programs"], 1)
        self.assertEqual(len(payload["lanes"]), 2)
        self.assertEqual(len(payload["programs"]), 1)
        self.assertEqual(payload["programs"][0]["scope_hint"], "src/auth")
        self.assertEqual(payload["programs"][0]["lane_count"], 2)
        self.assertEqual(payload["programs"][0]["participant_count"], 4)

    def test_repo_lanes_payload_sorts_fresh_dependency_lane_before_ongoing_scope_lane(self) -> None:
        claim_a = make_claim(
            claim_id="claim-a",
            agent_id="agent-a",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        intent_a = make_intent(
            intent_id="intent-a",
            agent_id="agent-a",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:05:00Z",
            related_claim_id=claim_a.id,
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        nearby_claim = make_claim(
            claim_id="claim-b",
            agent_id="agent-b",
            scope=("src/auth/session.py",),
            created_at="2026-03-17T10:45:00Z",
        )
        nearby_intent = make_intent(
            intent_id="intent-c",
            agent_id="agent-c",
            scope=("src/api",),
            created_at="2026-03-17T08:00:00Z",
        )
        agents = (
            make_presence(agent_id="agent-a", claim=claim_a, intent=intent_a),
            make_presence(agent_id="agent-b", claim=nearby_claim),
            make_presence(agent_id="agent-c", intent=nearby_intent),
        )
        snapshot = make_snapshot(
            claims=(claim_a, nearby_claim),
            intents=(intent_a, nearby_intent),
        )
        store = FakeGuidanceStore(
            dependency_scopes={
                (
                    ("src/api/handlers.py",),
                    ("src/auth/session.py",),
                ): ("src/api/handlers.py", "src/auth/session.py"),
            },
            resolved_conflicts={
                tuple(sorted((("claim", claim_a.id), ("claim", nearby_claim.id)))): make_conflict(
                    conflict_id="conflict-dependency",
                    left_type="claim",
                    left_id=claim_a.id,
                    right_type="claim",
                    right_id=nearby_claim.id,
                    scope=("src/api/handlers.py", "src/auth/session.py"),
                    resolved_at="2026-03-17T11:00:00Z",
                ),
                tuple(sorted((("intent", intent_a.id), ("intent", nearby_intent.id)))): make_conflict(
                    conflict_id="conflict-scope",
                    left_type="intent",
                    left_id=intent_a.id,
                    right_type="intent",
                    right_id=nearby_intent.id,
                    scope=("src/api",),
                    resolved_at="2026-03-17T09:00:00Z",
                ),
            },
        )

        payload = repo_lanes_payload(
            agents=agents,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=set(),
        )

        self.assertEqual(len(payload["lanes"]), 2)
        self.assertEqual(payload["lanes"][0]["relationship"], "dependency")
        self.assertEqual(payload["lanes"][0]["urgency"], "fresh")
        self.assertEqual(payload["lanes"][1]["relationship"], "scope")
        self.assertEqual(payload["lanes"][1]["urgency"], "ongoing")

    def test_repo_lanes_payload_stays_empty_without_acknowledged_nearby_work(self) -> None:
        claim_a = make_claim(
            claim_id="claim-a",
            agent_id="agent-a",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=FUTURE_LEASE,
            lease_policy="yield",
        )
        nearby_intent = make_intent(
            intent_id="intent-b",
            agent_id="agent-b",
            scope=("src/api/handlers.py",),
            created_at="2026-03-17T10:45:00Z",
        )
        agents = (
            make_presence(agent_id="agent-a", claim=claim_a),
            make_presence(agent_id="agent-b", intent=nearby_intent),
        )
        snapshot = make_snapshot(
            claims=(claim_a,),
            intents=(nearby_intent,),
        )

        payload = repo_lanes_payload(
            agents=agents,
            snapshot=snapshot,
            store=FakeGuidanceStore(),
            stale_agent_ids=set(),
        )

        self.assertEqual(payload["acknowledged_migration_lanes"], 0)
        self.assertEqual(payload["acknowledged_migration_programs"], 0)
        self.assertEqual(payload["lanes"], ())
        self.assertEqual(payload["programs"], ())

    def test_start_summary_reports_acknowledged_migration_lane_before_empty_repo_ready(self) -> None:
        mode, summary = start_summary(
            project_initialized=True,
            identity={"id": "agent-a", "source": "env"},
            snapshot=make_snapshot(),
            repo_lanes={"acknowledged_migration_lanes": 1},
        )

        self.assertEqual(mode, "active")
        self.assertEqual(
            summary,
            "The repository already has acknowledged migration work in flight.",
        )

    def test_start_recommendation_prefers_acknowledged_migration_lane_over_empty_repo_start(self) -> None:
        recommendation = start_recommendation(
            project_initialized=True,
            identity_recommendation=None,
            agent_id="agent-a",
            snapshot=make_snapshot(),
            repo_lanes={"acknowledged_migration_lanes": 1},
        )

        self.assertIsNotNone(recommendation)
        assert recommendation is not None
        self.assertEqual(recommendation["tool_name"], "loom_status")
        self.assertEqual(recommendation["command"], "loom status")
        self.assertIn("long-running coordinated change", str(recommendation["reason"]))

    def test_start_recommendation_prefers_inbox_attention_over_repo_lane_focus(self) -> None:
        recommendation = start_recommendation(
            project_initialized=True,
            identity_recommendation=None,
            agent_id="agent-a",
            snapshot=make_snapshot(),
            inbox_snapshot=SimpleNamespace(
                pending_context=(object(),),
                conflicts=(),
            ),
            repo_lanes={"acknowledged_migration_lanes": 2},
        )

        self.assertIsNotNone(recommendation)
        assert recommendation is not None
        self.assertEqual(recommendation["tool_name"], "loom_inbox")
        self.assertEqual(recommendation["command"], "loom inbox")

    def test_status_recommendation_prefers_worktree_adoption_before_repo_lane_focus(self) -> None:
        recommendation = status_recommendation(
            agent_id="agent-a",
            store=None,
            snapshot=make_snapshot(),
            worktree_signal={
                "has_drift": True,
                "suggested_scope": ("src/api",),
            },
            repo_lanes={"acknowledged_migration_lanes": 2},
            empty_recommendation=claim_recommendation(
                summary="Start work",
                reason="No coordination exists yet.",
                confidence="medium",
                agent_id="agent-a",
            ),
        )

        self.assertEqual(recommendation["tool_name"], "loom_claim")
        self.assertIn("--scope src/api", str(recommendation["command"]))
        self.assertNotEqual(recommendation["tool_name"], "loom_agent")

    def test_status_recommendation_prefers_expired_lease_alert_over_repo_lane_focus(self) -> None:
        current_claim = make_claim(
            claim_id="claim-expired",
            agent_id="agent-a",
            scope=("src/api",),
            created_at="2026-03-17T10:00:00Z",
            lease_expires_at=EXPIRED_LEASE,
            lease_policy="yield",
        )

        recommendation = status_recommendation(
            agent_id="agent-a",
            store=None,
            snapshot=make_snapshot(claims=(current_claim,)),
            repo_lanes={"acknowledged_migration_lanes": 2},
            empty_recommendation=claim_recommendation(
                summary="Start work",
                reason="No coordination exists yet.",
                confidence="medium",
                agent_id="agent-a",
            ),
        )

        self.assertEqual(recommendation["kind"], "lease")
        self.assertEqual(recommendation["tool_name"], "loom_finish")


if __name__ == "__main__":
    unittest.main()
