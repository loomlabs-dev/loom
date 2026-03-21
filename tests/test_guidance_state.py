from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.guidance_state import (  # noqa: E402
    active_scope_for_worktree,
    active_work_nearby_yield_alert,
    active_work_started_at,
    agent_presence_has_expired_lease,
    compact_scope_suggestion,
    latest_recent_handoff,
    repo_lanes_payload,
    stale_agent_ids,
    worktree_scope_candidate,
)
from loom.local_store import (  # noqa: E402
    AgentPresenceRecord,
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    IntentRecord,
    StatusSnapshot,
)


def make_claim(
    *,
    claim_id: str,
    agent_id: str = "agent-a",
    scope: tuple[str, ...] = ("src/api",),
    created_at: str = "2026-03-18T10:00:00Z",
    lease_expires_at: str | None = None,
    status: str = "active",
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        agent_id=agent_id,
        description="Claimed work",
        scope=scope,
        status=status,
        created_at=created_at,
        git_branch="main",
        lease_expires_at=lease_expires_at,
        lease_policy="yield" if lease_expires_at is not None else None,
    )


def make_intent(
    *,
    intent_id: str,
    agent_id: str = "agent-a",
    scope: tuple[str, ...] = ("src/api",),
    created_at: str = "2026-03-18T10:05:00Z",
    lease_expires_at: str | None = None,
    status: str = "active",
) -> IntentRecord:
    return IntentRecord(
        id=intent_id,
        agent_id=agent_id,
        description="Declared intent",
        reason="Need to edit this surface",
        scope=scope,
        status=status,
        created_at=created_at,
        related_claim_id=None,
        git_branch="main",
        lease_expires_at=lease_expires_at,
        lease_policy="yield" if lease_expires_at is not None else None,
    )


def make_presence(
    *,
    agent_id: str,
    claim: ClaimRecord | None = None,
    intent: IntentRecord | None = None,
    last_seen_at: str = "2026-03-18T12:00:00Z",
) -> AgentPresenceRecord:
    return AgentPresenceRecord(
        agent_id=agent_id,
        source="test",
        created_at="2026-03-18T09:00:00Z",
        last_seen_at=last_seen_at,
        claim=claim,
        intent=intent,
    )


def make_context(
    *,
    context_id: str,
    agent_id: str = "agent-a",
    topic: str = "session-handoff",
    created_at: str = "2026-03-18T11:00:00Z",
) -> ContextRecord:
    return ContextRecord(
        id=context_id,
        agent_id=agent_id,
        topic=topic,
        body="Carry this work forward.",
        scope=("src/api",),
        created_at=created_at,
        related_claim_id=None,
        related_intent_id=None,
        git_branch="main",
        acknowledgments=(),
    )


def make_conflict(
    *,
    conflict_id: str,
    left_type: str,
    left_id: str,
    right_type: str,
    right_id: str,
    scope: tuple[str, ...],
    resolved_at: str = "2026-03-18T11:30:00Z",
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
        created_at="2026-03-18T11:00:00Z",
        is_active=False,
        resolved_at=resolved_at,
        resolved_by="agent-review",
        resolution_note="Acknowledged migration lane.",
    )


class FakeContextStore:
    def __init__(self, handoffs: tuple[ContextRecord, ...]) -> None:
        self.handoffs = handoffs
        self.calls: list[tuple[str, str, int]] = []

    def read_context(
        self,
        *,
        topic: str,
        agent_id: str,
        limit: int,
    ) -> tuple[ContextRecord, ...]:
        self.calls.append((topic, agent_id, limit))
        return self.handoffs


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


class GuidanceStateTest(unittest.TestCase):
    def test_active_scope_for_worktree_merges_and_normalizes_claim_and_intent_scope(
        self,
    ) -> None:
        claim = make_claim(
            claim_id="claim-a",
            scope=("src/api/", "src/api/**"),
        )
        intent = make_intent(
            intent_id="intent-a",
            scope=("src\\ui\\components", "src/api"),
        )

        self.assertEqual(
            active_scope_for_worktree(claim=claim, intent=intent),
            ("src/api", "src/ui/components"),
        )

    def test_worktree_scope_candidate_uses_parent_for_nested_file_scope(self) -> None:
        self.assertEqual(
            worktree_scope_candidate("src/api/session.py"),
            "src/api",
        )
        self.assertEqual(
            worktree_scope_candidate("README.md"),
            "README.md",
        )

    def test_compact_scope_suggestion_prefers_broadest_non_overlapping_scopes(self) -> None:
        self.assertEqual(
            compact_scope_suggestion(
                (
                    "src/api/auth",
                    "src/api",
                    "tests/unit",
                    "tests",
                    "docs/alpha",
                )
            ),
            ("tests", "docs/alpha", "src/api"),
        )

    def test_latest_recent_handoff_skips_stale_entries(self) -> None:
        stale = make_context(
            context_id="context-stale",
            created_at="old-handoff",
        )
        fresh = make_context(
            context_id="context-fresh",
            created_at="fresh-handoff",
        )
        store = FakeContextStore((stale, fresh))

        result = latest_recent_handoff(
            store=store,
            agent_id="agent-a",
            is_stale_timestamp=lambda value, *, stale_after_hours: value.startswith("old"),
        )

        self.assertEqual(result, fresh)
        self.assertEqual(store.calls, [("session-handoff", "agent-a", 5)])

    def test_latest_recent_handoff_returns_none_when_all_entries_are_stale(self) -> None:
        store = FakeContextStore(
            (
                make_context(context_id="context-old-1", created_at="old-1"),
                make_context(context_id="context-old-2", created_at="old-2"),
            )
        )

        result = latest_recent_handoff(
            store=store,
            agent_id="agent-a",
            is_stale_timestamp=lambda value, *, stale_after_hours: value.startswith("old"),
        )

        self.assertIsNone(result)

    def test_active_work_started_at_prefers_latest_timestamp(self) -> None:
        claim = make_claim(
            claim_id="claim-a",
            created_at="2026-03-18T09:00:00Z",
        )
        intent = make_intent(
            intent_id="intent-a",
            created_at="2026-03-18T10:30:00Z",
        )

        self.assertEqual(
            active_work_started_at(claim=claim, intent=intent),
            "2026-03-18T10:30:00Z",
        )

    def test_agent_presence_has_expired_lease_only_counts_active_records(self) -> None:
        expired_claim = make_claim(
            claim_id="claim-expired",
            lease_expires_at="expired",
        )
        released_intent = make_intent(
            intent_id="intent-released",
            lease_expires_at="expired",
            status="released",
        )

        self.assertTrue(
            agent_presence_has_expired_lease(
                make_presence(agent_id="agent-a", claim=expired_claim),
                is_past_timestamp=lambda value: value == "expired",
            )
        )
        self.assertFalse(
            agent_presence_has_expired_lease(
                make_presence(agent_id="agent-b", intent=released_intent),
                is_past_timestamp=lambda value: value == "expired",
            )
        )

    def test_stale_agent_ids_marks_stale_or_expired_active_agents_only(self) -> None:
        agents = (
            make_presence(
                agent_id="agent-stale",
                claim=make_claim(claim_id="claim-stale"),
                last_seen_at="stale",
            ),
            make_presence(
                agent_id="agent-expired",
                intent=make_intent(
                    intent_id="intent-expired",
                    lease_expires_at="expired",
                ),
                last_seen_at="fresh",
            ),
            make_presence(
                agent_id="agent-idle",
                claim=None,
                intent=None,
                last_seen_at="stale",
            ),
            make_presence(
                agent_id="agent-active",
                claim=make_claim(
                    claim_id="claim-active",
                    lease_expires_at="future",
                ),
                last_seen_at="fresh",
            ),
        )

        result = stale_agent_ids(
            agents,
            is_stale_timestamp=lambda value: value == "stale",
            is_past_timestamp=lambda value: value == "expired",
        )

        self.assertEqual(result, {"agent-stale", "agent-expired"})

    def test_active_work_nearby_yield_alert_marks_acknowledged_ongoing_scope_pressure_low(
        self,
    ) -> None:
        claim = make_claim(
            claim_id="claim-a",
            scope=("src/api",),
            lease_expires_at="future",
        )
        nearby_claim = make_claim(
            claim_id="claim-b",
            agent_id="agent-b",
            scope=("src/api",),
            created_at="2026-03-18T01:00:00Z",
        )
        store = FakeGuidanceStore(
            resolved_conflicts={
                tuple(
                    sorted(
                        (
                            ("claim", "claim-a"),
                            ("claim", "claim-b"),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-a",
                    left_type="claim",
                    left_id="claim-a",
                    right_type="claim",
                    right_id="claim-b",
                    scope=("src/api",),
                )
            }
        )
        snapshot = StatusSnapshot(
            claims=(nearby_claim,),
            intents=(),
            context=(),
            conflicts=(),
        )

        alert = active_work_nearby_yield_alert(
            agent_id="agent-a",
            claim=claim,
            intent=None,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=set(),
            is_stale_timestamp=lambda value, *, stale_after_hours: value.endswith("01:00:00Z"),
            is_past_timestamp=lambda value: value == "expired",
        )

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertTrue(alert["acknowledged"])
        self.assertEqual(alert["urgency"], "ongoing")
        self.assertEqual(alert["confidence"], "low")
        self.assertEqual(alert["nearby"][0]["id"], "claim-b")
        self.assertIn("acknowledged nearby active work that is still live", alert["reason"])

    def test_active_work_nearby_yield_alert_prefers_fresh_dependency_over_acknowledged_scope(
        self,
    ) -> None:
        claim = make_claim(
            claim_id="claim-a",
            scope=("src/api",),
            created_at="2026-03-18T10:00:00Z",
            lease_expires_at="future",
        )
        acknowledged_scope_claim = make_claim(
            claim_id="claim-b",
            agent_id="agent-b",
            scope=("src/api",),
            created_at="2026-03-18T01:00:00Z",
        )
        fresh_dependency_intent = make_intent(
            intent_id="intent-c",
            agent_id="agent-c",
            scope=("src/worker",),
            created_at="2026-03-18T10:10:00Z",
        )
        store = FakeGuidanceStore(
            dependency_scopes={
                (("src/api",), ("src/worker",)): ("src/shared/types",),
            },
            resolved_conflicts={
                tuple(
                    sorted(
                        (
                            ("claim", "claim-a"),
                            ("claim", "claim-b"),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-b",
                    left_type="claim",
                    left_id="claim-a",
                    right_type="claim",
                    right_id="claim-b",
                    scope=("src/api",),
                )
            },
        )
        snapshot = StatusSnapshot(
            claims=(acknowledged_scope_claim,),
            intents=(fresh_dependency_intent,),
            context=(),
            conflicts=(),
        )

        alert = active_work_nearby_yield_alert(
            agent_id="agent-a",
            claim=claim,
            intent=None,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=set(),
            is_stale_timestamp=lambda value, *, stale_after_hours: value.endswith("01:00:00Z"),
            is_past_timestamp=lambda value: False,
        )

        self.assertIsNotNone(alert)
        assert alert is not None
        self.assertEqual(alert["confidence"], "high")
        self.assertEqual(alert["nearby"][0]["kind"], "intent")
        self.assertEqual(alert["nearby"][0]["agent_id"], "agent-c")
        self.assertEqual(alert["nearby"][0]["relationship"], "dependency")
        self.assertFalse(alert["nearby"][0]["acknowledged"])
        self.assertIn("semantically entangled", alert["reason"])

    def test_repo_lanes_payload_keeps_distinct_programs_without_shared_scope_hint(
        self,
    ) -> None:
        claim_a = make_claim(
            claim_id="claim-a",
            scope=("README.md",),
            lease_expires_at="future",
        )
        claim_c = make_claim(
            claim_id="claim-c",
            agent_id="agent-c",
            scope=("Makefile",),
            lease_expires_at="future",
        )
        nearby_readme_claim = make_claim(
            claim_id="claim-b",
            agent_id="agent-b",
            scope=("README.md",),
            created_at="2026-03-18T01:00:00Z",
        )
        nearby_make_claim = make_claim(
            claim_id="claim-d",
            agent_id="agent-d",
            scope=("Makefile",),
            created_at="2026-03-18T01:05:00Z",
        )
        store = FakeGuidanceStore(
            resolved_conflicts={
                tuple(
                    sorted(
                        (
                            ("claim", "claim-a"),
                            ("claim", "claim-b"),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-readme",
                    left_type="claim",
                    left_id="claim-a",
                    right_type="claim",
                    right_id="claim-b",
                    scope=("README.md",),
                ),
                tuple(
                    sorted(
                        (
                            ("claim", "claim-c"),
                            ("claim", "claim-d"),
                        )
                    )
                ): make_conflict(
                    conflict_id="conflict-make",
                    left_type="claim",
                    left_id="claim-c",
                    right_type="claim",
                    right_id="claim-d",
                    scope=("Makefile",),
                ),
            }
        )
        agents = (
            make_presence(agent_id="agent-a", claim=claim_a),
            make_presence(agent_id="agent-c", claim=claim_c),
        )
        snapshot = StatusSnapshot(
            claims=(nearby_readme_claim, nearby_make_claim),
            intents=(),
            context=(),
            conflicts=(),
        )

        payload = repo_lanes_payload(
            agents=agents,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=set(),
            is_stale_timestamp=lambda value, *, stale_after_hours: value.startswith("2026-03-18T01:"),
            is_past_timestamp=lambda value: False,
        )

        self.assertEqual(payload["acknowledged_migration_lanes"], 2)
        self.assertEqual(payload["acknowledged_migration_programs"], 2)
        self.assertTrue(all(program["scope_hint"] is None for program in payload["programs"]))
        self.assertEqual(
            {program["lane_scopes"][0] for program in payload["programs"]},
            {("Makefile",), ("README.md",)},
        )


if __name__ == "__main__":
    unittest.main()
