from __future__ import annotations

import pathlib
import sys
from types import SimpleNamespace
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import ClaimRecord  # noqa: E402
from loom.mcp_steps import tool_agent_next_steps, tool_start_next_steps, tool_status_next_steps, tool_whoami_next_steps  # noqa: E402


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


class McpStepsTest(unittest.TestCase):
    def test_tool_whoami_next_steps_for_tty_identity_points_at_init_then_start(self) -> None:
        steps = tool_whoami_next_steps(
            project=SimpleNamespace(),
            identity={"source": "tty"},
        )

        self.assertEqual(
            steps,
            (
                'Call loom_bind with agent_id="<agent-name>" to pin this MCP session to a stable agent identity.',
                "Call loom_start to ask Loom what to do next in this repository.",
                'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
            ),
        )

    def test_tool_start_next_steps_for_empty_repo_and_raw_identity_uses_start_order(self) -> None:
        steps = tool_start_next_steps(
            project=SimpleNamespace(),
            identity={"source": "tty", "stable_terminal_identity": False},
            snapshot=SimpleNamespace(claims=(), intents=(), context=(), conflicts=()),
        )

        self.assertEqual(
            steps,
            (
                'Call loom_bind with agent_id="<agent-name>" to pin this MCP session to a stable agent identity.',
                "Call loom_start to ask Loom what to do next in this repository.",
                'Call loom_claim with description="Describe the work you\'re starting" and scope=["path/to/area"].',
            ),
        )

    def test_tool_status_next_steps_prioritizes_renew_for_expired_current_agent_lease(self) -> None:
        steps = tool_status_next_steps(
            snapshot=SimpleNamespace(
                claims=(make_claim(claim_id="claim-expired", agent_id="agent-a", lease_expires_at=EXPIRED_LEASE),),
                intents=(),
                context=(),
                conflicts=(),
            ),
            identity={"id": "agent-a", "source": "env", "stable_terminal_identity": True},
            is_past_timestamp=lambda value: value == EXPIRED_LEASE,
        )

        self.assertEqual(
            steps,
            (
                "Call loom_renew to extend the current coordination lease.",
                "Call loom_agent for a focused agent view.",
                "Call loom_status to confirm the current coordination state.",
            ),
        )

    def test_tool_agent_next_steps_prioritizes_yield_alert_before_other_followups(self) -> None:
        steps = tool_agent_next_steps(
            agent=SimpleNamespace(
                claim=make_claim(claim_id="claim-a", agent_id="agent-a"),
                intent=None,
                published_context=(),
                conflicts=(),
            ),
            active_work={
                "started_at": "2026-03-18T10:00:00Z",
                "yield_alert": {"policy": "yield"},
                "lease_alert": None,
                "priority": None,
                "pending_context": (),
            },
            worktree_signal={"has_drift": False, "changed_paths": ("src/api.py",)},
        )

        self.assertEqual(
            steps,
            (
                "Call loom_finish to publish an optional handoff and release current work.",
                "Call loom_inbox for this agent to inspect the coordination pressure.",
                "Call loom_status to compare this agent with the rest of the repo.",
            ),
        )


if __name__ == "__main__":
    unittest.main()
