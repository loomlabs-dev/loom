from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.daemon import DaemonStatus  # noqa: E402
from loom.local_store import (  # noqa: E402
    AgentPresenceRecord,
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    EventRecord,
    IntentRecord,
    StatusSnapshot,
)
from loom.reporting import (  # noqa: E402
    build_coordination_report,
    render_coordination_report_html,
    summarize_scope_hotspots,
)


class ReportingTest(unittest.TestCase):
    def test_summarize_scope_hotspots_uses_repo_bucket_for_unscoped_activity(self) -> None:
        snapshot = StatusSnapshot(
            claims=(
                ClaimRecord(
                    id="claim_repo",
                    agent_id="agent-a",
                    description="Sweep the repo",
                    scope=(),
                    status="active",
                    created_at="2026-03-16T00:00:00Z",
                ),
            ),
            intents=(),
            context=(
                ContextRecord(
                    id="context_repo",
                    agent_id="agent-b",
                    topic="repo-note",
                    body="Whole-repo context",
                    scope=(),
                    created_at="2026-03-16T00:01:00Z",
                    related_claim_id=None,
                    related_intent_id=None,
                ),
            ),
            conflicts=(),
        )

        hotspots = summarize_scope_hotspots(snapshot)

        self.assertEqual(len(hotspots), 1)
        self.assertEqual(hotspots[0].scope, "(repo)")
        self.assertEqual(hotspots[0].status, "active")
        self.assertEqual(hotspots[0].claim_count, 1)
        self.assertEqual(hotspots[0].context_count, 1)
        self.assertEqual(hotspots[0].agents, ("agent-a", "agent-b"))

    def test_summarize_scope_hotspots_prioritizes_conflict_heat(self) -> None:
        snapshot = StatusSnapshot(
            claims=(
                ClaimRecord(
                    id="claim_1",
                    agent_id="agent-a",
                    description="Refactor auth",
                    scope=("src/auth",),
                    status="active",
                    created_at="2026-03-16T00:00:00Z",
                ),
            ),
            intents=(
                IntentRecord(
                    id="intent_1",
                    agent_id="agent-b",
                    description="Touch middleware",
                    reason="Need auth hooks",
                    scope=("src/auth/middleware",),
                    status="active",
                    created_at="2026-03-16T00:01:00Z",
                    related_claim_id=None,
                ),
            ),
            context=(
                ContextRecord(
                    id="context_1",
                    agent_id="agent-a",
                    topic="auth-interface-change",
                    body="UserSession now requires refresh_token.",
                    scope=("src/auth", "src/api"),
                    created_at="2026-03-16T00:02:00Z",
                    related_claim_id="claim_1",
                    related_intent_id=None,
                ),
            ),
            conflicts=(
                ConflictRecord(
                    id="conflict_1",
                    kind="scope_overlap",
                    severity="warning",
                    summary="agent-b overlaps agent-a on auth",
                    object_type_a="claim",
                    object_id_a="claim_1",
                    object_type_b="intent",
                    object_id_b="intent_1",
                    scope=("src/auth",),
                    created_at="2026-03-16T00:03:00Z",
                ),
            ),
        )

        hotspots = summarize_scope_hotspots(snapshot)

        self.assertGreaterEqual(len(hotspots), 2)
        self.assertEqual(hotspots[0].scope, "src/auth")
        self.assertEqual(hotspots[0].status, "conflict")
        self.assertEqual(hotspots[0].conflict_count, 1)
        self.assertIn("agent-a", hotspots[0].agents)
        self.assertIn("agent-b", hotspots[0].agents)

    def test_summarize_scope_hotspots_attributes_context_linked_conflict_agents(self) -> None:
        snapshot = StatusSnapshot(
            claims=(),
            intents=(),
            context=(
                ContextRecord(
                    id="context_left",
                    agent_id="agent-left",
                    topic="left",
                    body="left body",
                    scope=("src/shared",),
                    created_at="2026-03-16T00:02:00Z",
                    related_claim_id=None,
                    related_intent_id=None,
                ),
                ContextRecord(
                    id="context_right",
                    agent_id="agent-right",
                    topic="right",
                    body="right body",
                    scope=("src/shared",),
                    created_at="2026-03-16T00:03:00Z",
                    related_claim_id=None,
                    related_intent_id=None,
                ),
            ),
            conflicts=(
                ConflictRecord(
                    id="conflict_context",
                    kind="contextual_dependency",
                    severity="warning",
                    summary="context overlap",
                    object_type_a="context",
                    object_id_a="context_left",
                    object_type_b="context",
                    object_id_b="context_right",
                    scope=("src/shared",),
                    created_at="2026-03-16T00:04:00Z",
                ),
            ),
        )

        hotspots = summarize_scope_hotspots(snapshot)

        self.assertEqual(hotspots[0].scope, "src/shared")
        self.assertEqual(hotspots[0].status, "conflict")
        self.assertEqual(hotspots[0].agents, ("agent-left", "agent-right"))

    def test_render_coordination_report_html_includes_scope_heat_and_agents(self) -> None:
        snapshot = StatusSnapshot(
            claims=(
                ClaimRecord(
                    id="claim_1",
                    agent_id="agent-a",
                    description="Refactor auth",
                    scope=("src/auth",),
                    status="active",
                    created_at="2026-03-16T00:00:00Z",
                ),
            ),
            intents=(),
            context=(),
            conflicts=(),
        )
        agents = (
            AgentPresenceRecord(
                agent_id="agent-a",
                source="terminal",
                created_at="2026-03-16T00:00:00Z",
                last_seen_at="2099-03-16T00:05:00Z",
                claim=snapshot.claims[0],
                intent=None,
            ),
        )
        events = (
            EventRecord(
                sequence=1,
                id="event_1",
                type="claim.recorded",
                timestamp="2026-03-16T00:00:01Z",
                actor_id="agent-a",
                payload={"claim_id": "claim_1"},
            ),
        )

        report = build_coordination_report(
            project_root=PROJECT_ROOT,
            daemon_status=DaemonStatus(running=False, detail="not running (direct SQLite mode)"),
            status_snapshot=snapshot,
            agents=agents,
            recent_events=events,
        )
        html = render_coordination_report_html(report)

        self.assertIn("Loom Coordination Report", html)
        self.assertIn("Scope Heat", html)
        self.assertIn("Live Active Agents", html)
        self.assertIn("src/auth", html)
        self.assertIn("agent-a", html)
        self.assertIn("claim.recorded", html)
        self.assertIn("DM+Sans", html)
        self.assertIn("Syne", html)
        self.assertIn("overflow-wrap: anywhere", html)

    def test_build_coordination_report_separates_live_and_stale_active_agents(self) -> None:
        snapshot = StatusSnapshot(
            claims=(
                ClaimRecord(
                    id="claim_live",
                    agent_id="agent-live",
                    description="Refactor auth",
                    scope=("src/auth",),
                    status="active",
                    created_at="2026-03-16T00:00:00Z",
                    lease_expires_at="2099-03-16T01:00:00Z",
                ),
                ClaimRecord(
                    id="claim_stale",
                    agent_id="agent-stale",
                    description="Old cleanup pass",
                    scope=("src/legacy",),
                    status="active",
                    created_at="2026-03-16T00:10:00Z",
                    lease_expires_at="2026-03-16T00:30:00Z",
                ),
            ),
            intents=(),
            context=(),
            conflicts=(),
        )
        agents = (
            AgentPresenceRecord(
                agent_id="agent-live",
                source="terminal",
                created_at="2099-03-16T00:00:00Z",
                last_seen_at="2099-03-16T00:05:00Z",
                claim=snapshot.claims[0],
                intent=None,
            ),
            AgentPresenceRecord(
                agent_id="agent-stale",
                source="terminal",
                created_at="2099-03-16T00:10:00Z",
                last_seen_at="2099-03-16T00:15:00Z",
                claim=snapshot.claims[1],
                intent=None,
            ),
        )

        with patch("loom.reporting.is_stale_utc_timestamp", return_value=False):
            report = build_coordination_report(
                project_root=PROJECT_ROOT,
                daemon_status=DaemonStatus(running=False, detail="not running (direct SQLite mode)"),
                status_snapshot=snapshot,
                agents=agents,
                recent_events=(),
            )

        self.assertEqual(report["summary"]["active_agents"], 2)
        self.assertEqual(report["summary"]["live_active_agents"], 1)
        self.assertEqual(report["summary"]["stale_active_agents"], 1)
        self.assertEqual(len(report["live_active_agents"]), 1)
        self.assertEqual(len(report["stale_active_agents"]), 1)
        html = render_coordination_report_html(report)
        self.assertIn("Claim lease:", html)
        self.assertIn("(expired)", html)

    def test_build_coordination_report_counts_idle_agents_and_preserves_daemon_metadata(self) -> None:
        snapshot = StatusSnapshot(
            claims=(),
            intents=(),
            context=(),
            conflicts=(),
        )
        agents = (
            AgentPresenceRecord(
                agent_id="agent-idle",
                source="terminal",
                created_at="2026-03-16T00:00:00Z",
                last_seen_at="2026-03-16T00:05:00Z",
                claim=None,
                intent=None,
            ),
        )

        report = build_coordination_report(
            project_root=PROJECT_ROOT,
            daemon_status=DaemonStatus(
                running=True,
                detail="running on daemon.sock",
                pid=4321,
                started_at="2026-03-16T00:00:00Z",
            ),
            status_snapshot=snapshot,
            agents=agents,
            recent_events=(),
        )

        self.assertEqual(report["summary"]["known_agents"], 1)
        self.assertEqual(report["summary"]["active_agents"], 0)
        self.assertEqual(report["summary"]["idle_agents"], 1)
        self.assertEqual(len(report["idle_agents"]), 1)
        self.assertEqual(report["daemon"]["running"], True)
        self.assertEqual(report["daemon"]["pid"], 4321)
        self.assertEqual(report["daemon"]["started_at"], "2026-03-16T00:00:00Z")
        self.assertEqual(report["project_root"], str(PROJECT_ROOT))

    def test_render_coordination_report_preserves_unicode_and_escapes_html(self) -> None:
        snapshot = StatusSnapshot(
            claims=(),
            intents=(),
            context=(
                ContextRecord(
                    id="context_unicode",
                    agent_id="agent-über",
                    topic="über-topic",
                    body="Body <unsafe> café 設計",
                    scope=("src/über/設計 notes",),
                    created_at="2026-03-16T00:02:00Z",
                    related_claim_id=None,
                    related_intent_id=None,
                ),
            ),
            conflicts=(),
        )

        report = build_coordination_report(
            project_root=PROJECT_ROOT,
            daemon_status=DaemonStatus(running=False, detail="not running (direct SQLite mode)"),
            status_snapshot=snapshot,
            agents=(),
            recent_events=(),
        )
        html = render_coordination_report_html(report)

        self.assertIn("über-topic", html)
        self.assertIn("café 設計", html)
        self.assertIn("&lt;unsafe&gt;", html)
        self.assertNotIn("\\u8a2d", html)


if __name__ == "__main__":
    unittest.main()
