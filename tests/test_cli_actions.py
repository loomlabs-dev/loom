from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.action_errors import ContextNotFoundError, NoActiveClaimError, WhoamiSelectionError  # noqa: E402
from loom.cli_actions import (  # noqa: E402
    agent_next_steps,
    error_next_steps,
    onboarding_commands,
    report_next_steps,
    resume_next_steps,
    start_next_action,
    start_next_steps,
    status_next_action,
    status_next_steps,
    timeline_next_steps,
    whoami_next_steps,
)
from loom.local_store import ClaimRecord, StatusSnapshot  # noqa: E402


EXPIRED_LEASE = "2000-01-01T00:00:00Z"


def make_claim(*, claim_id: str, agent_id: str, lease_expires_at: str | None = None) -> ClaimRecord:
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


class CliActionsTest(unittest.TestCase):
    def test_onboarding_commands_for_project_identity_starts_without_binding(self) -> None:
        steps = onboarding_commands(
            default_agent="agent-project",
            identity={
                "source": "project",
                "stable_terminal_identity": True,
                "project_default_agent": "agent-project",
            },
        )

        self.assertEqual(
            steps,
            (
                "loom start",
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                "loom status",
            ),
        )

    def test_whoami_next_steps_for_uninitialized_unstable_identity_prefers_env_binding(self) -> None:
        steps = whoami_next_steps(
            project=None,
            identity={
                "source": "tty",
                "stable_terminal_identity": False,
            },
        )

        self.assertEqual(
            steps,
            (
                "loom init --no-daemon",
                "export LOOM_AGENT=<agent-name>",
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
            ),
        )

    def test_whoami_next_steps_for_bindable_tty_prefers_single_start_bind_command(self) -> None:
        steps = whoami_next_steps(
            project=SimpleNamespace(),
            identity={
                "source": "tty",
                "stable_terminal_identity": True,
            },
        )

        self.assertEqual(
            steps,
            (
                "loom start --bind <agent-name>",
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                "loom status",
            ),
        )

    def test_start_next_steps_for_raw_tty_identity_prioritizes_binding_path(self) -> None:
        steps = start_next_steps(
            project=SimpleNamespace(),
            identity={
                "id": "dev@host:pid-123",
                "source": "tty",
                "stable_terminal_identity": False,
            },
            snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
        )

        self.assertEqual(
            steps,
            (
                "export LOOM_AGENT=<agent-name>",
                "loom start",
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
            ),
        )

    def test_start_next_steps_for_bindable_tty_uses_single_start_bind_command(self) -> None:
        steps = start_next_steps(
            project=SimpleNamespace(),
            identity={
                "id": "dev@host:ttys001",
                "source": "tty",
                "stable_terminal_identity": True,
            },
            snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
        )

        self.assertEqual(
            steps,
            (
                "loom start --bind <agent-name>",
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                "loom status",
            ),
        )

    def test_status_next_steps_prioritizes_renew_for_expired_current_agent_lease(self) -> None:
        snapshot = StatusSnapshot(
            claims=(make_claim(claim_id="claim-expired", agent_id="agent-a", lease_expires_at=EXPIRED_LEASE),),
            intents=(),
            context=(),
            conflicts=(),
        )

        steps = status_next_steps(
            snapshot=snapshot,
            identity={"id": "agent-a", "source": "env", "stable_terminal_identity": True},
            is_past_timestamp=lambda value: value == EXPIRED_LEASE,
        )

        self.assertEqual(steps, ("loom renew", "loom agent", "loom status"))

    def test_agent_next_steps_prioritizes_priority_command_before_inbox(self) -> None:
        steps = agent_next_steps(
            has_claim=True,
            has_intent=True,
            has_published_context=False,
            pending_context=1,
            conflict_count=0,
            has_priority_attention=True,
            priority_command="loom resolve conflict_01 --note handled",
        )

        self.assertEqual(
            steps,
            (
                "loom resolve conflict_01 --note handled",
                "loom inbox",
                "loom status",
            ),
        )

    def test_start_next_action_passes_identity_recommendation_for_unstable_tty(self) -> None:
        def fake_start_recommendation(**kwargs):
            identity_recommendation = kwargs["identity_recommendation"]
            self.assertIsNotNone(identity_recommendation)
            self.assertEqual(identity_recommendation["command"], "export LOOM_AGENT=<agent-name>")
            return identity_recommendation

        with patch("loom.cli_actions.guidance_start_recommendation", side_effect=fake_start_recommendation):
            action = start_next_action(
                project=SimpleNamespace(),
                identity={
                    "id": "dev@host:pid-123",
                    "source": "tty",
                    "stable_terminal_identity": False,
                },
                snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
            )

        self.assertEqual(action["command"], "export LOOM_AGENT=<agent-name>")
        self.assertEqual(action["confidence"], "high")

    def test_start_next_action_prefers_clean_when_dead_sessions_exist(self) -> None:
        action = start_next_action(
            project=SimpleNamespace(),
            identity={"id": "agent-a", "source": "project", "stable_terminal_identity": True},
            dead_session_count=2,
            snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
        )

        assert action is not None
        self.assertEqual(action["command"], "loom clean")
        self.assertEqual(action["kind"], "cleanup")

    def test_start_next_steps_prefers_clean_when_dead_sessions_exist(self) -> None:
        self.assertEqual(
            start_next_steps(
                project=SimpleNamespace(),
                identity={"id": "agent-a", "source": "project", "stable_terminal_identity": True},
                dead_session_count=1,
                snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
            ),
            ("loom clean", "loom status", "loom agents --all"),
        )

    def test_status_next_action_uses_bind_recommendation_when_terminal_can_bind(self) -> None:
        def fake_status_recommendation(**kwargs):
            identity_recommendation = kwargs["identity_recommendation"]
            self.assertIsNotNone(identity_recommendation)
            self.assertEqual(identity_recommendation["command"], "loom start --bind <agent-name>")
            return identity_recommendation

        with (
            patch("loom.cli_actions.guidance_identity_has_stable_coordination", return_value=False),
            patch("loom.cli_actions.guidance_identity_needs_env_binding", return_value=False),
            patch("loom.cli_actions.guidance_status_recommendation", side_effect=fake_status_recommendation),
        ):
            action = status_next_action(
                store=SimpleNamespace(),
                snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
                identity={"id": "agent-a", "source": "tty", "stable_terminal_identity": True},
            )

        self.assertEqual(action["command"], "loom start --bind <agent-name>")
        self.assertEqual(action["summary"], "Bind this terminal and continue with Loom's first coordinated step.")

    def test_status_next_action_prefers_clean_when_dead_sessions_exist(self) -> None:
        action = status_next_action(
            store=SimpleNamespace(),
            snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
            identity={"id": "agent-a", "source": "project", "stable_terminal_identity": True},
            dead_session_count=1,
        )

        assert action is not None
        self.assertEqual(action["command"], "loom clean")
        self.assertEqual(action["kind"], "cleanup")

    def test_status_next_steps_prefers_clean_when_dead_sessions_exist(self) -> None:
        self.assertEqual(
            status_next_steps(
                snapshot=StatusSnapshot(claims=(), intents=(), context=(), conflicts=()),
                identity={"id": "agent-a", "source": "project", "stable_terminal_identity": True},
                dead_session_count=1,
            ),
            ("loom clean", "loom status", "loom agents --all"),
        )

    def test_resume_report_and_timeline_helpers_prioritize_expected_paths(self) -> None:
        handoff = SimpleNamespace(scope=("src/api",))

        self.assertEqual(
            resume_next_steps(
                pending_context=0,
                conflict_count=0,
                has_claim=False,
                has_intent=False,
                recent_handoff=handoff,
            ),
            (
                'loom claim "Describe the work you\'re starting" --scope src/api',
                "loom status",
                "loom agent",
            ),
        )
        self.assertEqual(
            report_next_steps(conflict_count=2, stale_active_count=1),
            ("loom agents", "loom status", "loom report --json"),
        )
        self.assertEqual(
            timeline_next_steps(object_type="claim", related_conflict_count=0),
            ("loom status", "loom log --limit 10"),
        )
        self.assertEqual(
            timeline_next_steps(object_type="conflict", related_conflict_count=0),
            ("loom conflicts", "loom inbox"),
        )

    def test_error_next_steps_prefers_typed_errors_then_string_fallback(self) -> None:
        self.assertEqual(
            error_next_steps(NoActiveClaimError("missing claim")),
            (
                "loom status",
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
            ),
        )
        self.assertEqual(
            error_next_steps(ContextNotFoundError("missing context")),
            ("loom context read --limit 10", "loom inbox"),
        )
        self.assertEqual(error_next_steps(WhoamiSelectionError()), ("loom whoami",))
        self.assertEqual(
            error_next_steps("Context not found: context_123"),
            ("loom context read --limit 10", "loom inbox"),
        )


if __name__ == "__main__":
    unittest.main()
