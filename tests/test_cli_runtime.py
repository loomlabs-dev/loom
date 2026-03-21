from __future__ import annotations

import pathlib
import sys
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli_runtime import (  # noqa: E402
    active_work_with_repo_yield_alert,
    agent_activity_payload,
    identity_payload,
    partition_agents_by_activity,
    stale_agent_ids,
    validated_lease_minutes,
    validated_lease_policy,
)
from loom.local_store import AgentPresenceRecord, ClaimRecord  # noqa: E402
from loom.project import LoomProject  # noqa: E402


FUTURE_LEASE = "2099-01-01T00:00:00Z"
EXPIRED_LEASE = "2000-01-01T00:00:00Z"


def make_project() -> LoomProject:
    repo_root = PROJECT_ROOT
    loom_dir = repo_root / ".loom"
    return LoomProject(
        repo_root=repo_root,
        loom_dir=loom_dir,
        config_path=loom_dir / "config.json",
        db_path=loom_dir / "coordination.db",
        socket_path=loom_dir / "daemon.sock",
        runtime_path=loom_dir / "daemon.json",
        log_path=loom_dir / "daemon.log",
        schema_version=2,
        default_agent="agent-project",
        terminal_aliases={"dev@host:tmux-7": "agent-terminal"},
    )


def make_claim(
    *,
    claim_id: str,
    agent_id: str,
    lease_expires_at: str | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        id=claim_id,
        agent_id=agent_id,
        description="Claimed work",
        scope=("src/api",),
        status="active",
        created_at="2026-03-18T10:00:00Z",
        git_branch="main",
        lease_expires_at=lease_expires_at,
        lease_policy="yield" if lease_expires_at else None,
    )


def make_presence(
    *,
    agent_id: str,
    claim: ClaimRecord | None = None,
    last_seen_at: str = "2026-03-18T12:00:00Z",
) -> AgentPresenceRecord:
    return AgentPresenceRecord(
        agent_id=agent_id,
        source="test",
        created_at="2026-03-18T09:00:00Z",
        last_seen_at=last_seen_at,
        claim=claim,
        intent=None,
    )


class CliRuntimeTest(unittest.TestCase):
    def test_identity_payload_reports_binding_and_warning_for_unstable_terminal(self) -> None:
        project = make_project()
        with patch("loom.cli_runtime.current_terminal_identity", return_value="dev@host:pid-123"), patch(
            "loom.cli_runtime.terminal_identity_is_stable",
            return_value=False,
        ):
            payload = identity_payload(
                project=project,
                agent_id="agent-env",
                source="env",
            )

        self.assertEqual(payload["id"], "agent-env")
        self.assertEqual(payload["source"], "env")
        self.assertEqual(payload["terminal_identity"], "dev@host:pid-123")
        self.assertFalse(payload["stable_terminal_identity"])
        self.assertIsNone(payload["terminal_binding"])
        self.assertEqual(payload["project_default_agent"], "agent-project")
        self.assertTrue(payload["project_initialized"])
        self.assertIn("no stable terminal identity", str(payload["identity_warning"]))

    def test_identity_payload_reports_terminal_binding_when_present(self) -> None:
        project = make_project()
        with patch("loom.cli_runtime.current_terminal_identity", return_value="dev@host:tmux-7"), patch(
            "loom.cli_runtime.terminal_identity_is_stable",
            return_value=True,
        ):
            payload = identity_payload(
                project=project,
                agent_id="agent-terminal",
                source="terminal",
            )

        self.assertEqual(payload["terminal_binding"], "agent-terminal")
        self.assertIsNone(payload["identity_warning"])

    def test_validated_lease_helpers_enforce_positive_and_policy_requirements(self) -> None:
        self.assertIsNone(validated_lease_minutes(None))
        self.assertEqual(validated_lease_minutes(30), 30)
        self.assertEqual(validated_lease_policy(None, lease_minutes=30), "renew")
        self.assertEqual(validated_lease_policy("yield", lease_minutes=30), "yield")

        with self.assertRaisesRegex(ValueError, "Lease minutes must be positive"):
            validated_lease_minutes(0)
        with self.assertRaisesRegex(ValueError, "Lease policy requires --lease-minutes"):
            validated_lease_policy("yield", lease_minutes=None)

    def test_partition_agents_by_activity_separates_live_stale_and_idle_agents(self) -> None:
        live_active, stale_active, idle = partition_agents_by_activity(
            (
                make_presence(
                    agent_id="agent-live",
                    claim=make_claim(
                        claim_id="claim-live",
                        agent_id="agent-live",
                        lease_expires_at=FUTURE_LEASE,
                    ),
                ),
                make_presence(
                    agent_id="agent-stale-seen",
                    claim=make_claim(
                        claim_id="claim-stale-seen",
                        agent_id="agent-stale-seen",
                        lease_expires_at=FUTURE_LEASE,
                    ),
                    last_seen_at="2000-01-01T00:00:00Z",
                ),
                make_presence(
                    agent_id="agent-stale-lease",
                    claim=make_claim(
                        claim_id="claim-stale-lease",
                        agent_id="agent-stale-lease",
                        lease_expires_at=EXPIRED_LEASE,
                    ),
                ),
                make_presence(agent_id="agent-idle"),
            ),
            is_stale_timestamp=lambda value, stale_after_hours: value.startswith("2000-"),
            is_past_timestamp=lambda value: value.startswith("2000-"),
        )

        self.assertEqual(tuple(p.agent_id for p in live_active), ("agent-live",))
        self.assertEqual(
            tuple(p.agent_id for p in stale_active),
            ("agent-stale-seen", "agent-stale-lease"),
        )
        self.assertEqual(tuple(p.agent_id for p in idle), ("agent-idle",))

    def test_agent_activity_payload_and_stale_agent_ids_match_partitioned_agents(self) -> None:
        agents = (
            make_presence(
                agent_id="agent-live",
                claim=make_claim(
                    claim_id="claim-live",
                    agent_id="agent-live",
                    lease_expires_at=FUTURE_LEASE,
                ),
            ),
            make_presence(
                agent_id="agent-stale",
                claim=make_claim(
                    claim_id="claim-stale",
                    agent_id="agent-stale",
                    lease_expires_at=EXPIRED_LEASE,
                ),
            ),
            make_presence(agent_id="agent-idle"),
        )

        activity = agent_activity_payload(
            agents,
            is_stale_timestamp=lambda value, stale_after_hours: False,
            is_past_timestamp=lambda value: value == EXPIRED_LEASE,
        )
        stale_ids = stale_agent_ids(
            agents,
            is_stale_timestamp=lambda value, stale_after_hours: False,
            is_past_timestamp=lambda value: value == EXPIRED_LEASE,
        )

        self.assertEqual(
            activity,
            {
                "known_agents": 3,
                "live_active_agents": 1,
                "stale_active_agents": 1,
                "idle_agents": 1,
                "stale_after_hours": activity["stale_after_hours"],
            },
        )
        self.assertEqual(stale_ids, {"agent-stale"})

    def test_active_work_with_repo_yield_alert_only_adds_new_yield_when_needed(self) -> None:
        store = Mock()
        active_work = {
            "started_at": "2026-03-18T10:00:00Z",
            "yield_alert": None,
            "needs_attention": False,
        }
        claim = make_claim(
            claim_id="claim-live",
            agent_id="agent-a",
            lease_expires_at=FUTURE_LEASE,
        )
        nearby_yield = {
            "policy": "yield",
            "summary": "Yield now.",
            "reason": "Nearby pressure.",
        }

        with patch("loom.cli_runtime.guidance_active_work_nearby_yield_alert", return_value=nearby_yield):
            updated = active_work_with_repo_yield_alert(
                store=store,
                active_work=active_work,
                agent_id="agent-a",
                claim=claim,
                intent=None,
                snapshot=object(),
                stale_agent_ids={"agent-stale"},
            )

        self.assertIsNot(updated, active_work)
        self.assertTrue(updated["needs_attention"])
        self.assertEqual(updated["yield_alert"], nearby_yield)

        with patch("loom.cli_runtime.guidance_active_work_nearby_yield_alert") as yield_mock:
            unchanged = active_work_with_repo_yield_alert(
                store=store,
                active_work={
                    "started_at": "2026-03-18T10:00:00Z",
                    "yield_alert": {"policy": "yield"},
                    "needs_attention": True,
                },
                agent_id="agent-a",
                claim=claim,
                intent=None,
                snapshot=object(),
            )

        self.assertEqual(unchanged["yield_alert"], {"policy": "yield"})
        yield_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
