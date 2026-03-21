from __future__ import annotations

from contextlib import redirect_stdout
import io
import pathlib
import sys
import unittest
from types import SimpleNamespace


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli_output import (  # noqa: E402
    activity_suffix,
    print_active_work_recovery,
    print_inbox_snapshot,
    print_worktree_signal,
    worktree_adoption_command,
)
from loom.local_store import ConflictRecord, ContextRecord, EventRecord, InboxSnapshot  # noqa: E402


def make_context(context_id: str = "context_123") -> ContextRecord:
    return ContextRecord(
        id=context_id,
        agent_id="agent-a",
        topic="handoff",
        body="Context body",
        scope=("src/api.py",),
        created_at="2026-03-18T12:00:00Z",
        related_claim_id="claim_123",
        related_intent_id="intent_123",
    )


def make_conflict(conflict_id: str = "conflict_123") -> ConflictRecord:
    return ConflictRecord(
        id=conflict_id,
        kind="scope_overlap",
        severity="warning",
        summary="Overlap on api",
        object_type_a="claim",
        object_id_a="claim_123",
        object_type_b="intent",
        object_id_b="intent_123",
        scope=("src/api.py",),
        created_at="2026-03-18T12:05:00Z",
    )


def make_event(event_id: str = "event_123") -> EventRecord:
    return EventRecord(
        sequence=1,
        id=event_id,
        type="context.published",
        timestamp="2026-03-18T12:10:00Z",
        actor_id="agent-a",
        payload={"context_id": "context_123"},
    )


class CliOutputTest(unittest.TestCase):
    def test_worktree_adoption_command_prefers_intent_when_active_scope_exists(self) -> None:
        signal = {
            "has_active_scope": True,
            "suggested_scope": ("src/api.py", "src/models.py"),
        }

        intent_command = lambda scope: f"intent:{','.join(scope)}"
        claim_command = lambda scope: f"claim:{','.join(scope)}"

        self.assertEqual(
            worktree_adoption_command(
                signal,
                intent_command=intent_command,
                claim_command=claim_command,
            ),
            "intent:src/api.py,src/models.py",
        )
        self.assertEqual(
            worktree_adoption_command(
                {"has_active_scope": False, "suggested_scope": ("src/api.py",)},
                intent_command=intent_command,
                claim_command=claim_command,
            ),
            "claim:src/api.py",
        )

    def test_print_worktree_signal_shows_scope_adoption_guidance(self) -> None:
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            print_worktree_signal(
                {
                    "changed_paths": ("src/api.py", "src/models.py"),
                    "drift_paths": ("src/models.py",),
                    "active_scope": ("src/api.py",),
                    "suggested_scope": ("src/api.py", "src/models.py"),
                    "has_active_scope": True,
                },
                heading="Worktree drift",
                current_scope_label="current scope",
                intent_command=lambda scope: f"loom intent --scope {' --scope '.join(scope)}",
                claim_command=lambda scope: f"loom claim --scope {' --scope '.join(scope)}",
            )

        output = buffer.getvalue()
        self.assertIn("Worktree drift:", output)
        self.assertIn("- changed paths: 2", output)
        self.assertIn("current scope: src/api.py", output)
        self.assertIn("outside scope: src/models.py", output)
        self.assertIn("suggested widened scope: src/api.py, src/models.py", output)
        self.assertIn("next: loom intent --scope src/api.py --scope src/models.py", output)

    def test_print_active_work_recovery_surfaces_lease_yield_and_scope_adoption(self) -> None:
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            print_active_work_recovery(
                active_work={
                    "started_at": "2026-03-18T12:00:00Z",
                    "pending_context": (),
                    "conflicts": (),
                    "events": (),
                    "react_now_context": (),
                    "review_soon_context": (),
                    "expired_leases": (
                        {
                            "kind": "claim",
                            "description": "Claimed work",
                            "id": "claim_123",
                            "lease_expires_at": "2026-03-18T11:00:00Z",
                        },
                    ),
                    "lease_alert": {"next_step": "loom renew --lease-minutes 30"},
                    "yield_alert": {
                        "summary": "Yield to overlapping migration work.",
                        "next_step": "loom finish",
                        "nearby": (
                            {
                                "kind": "intent",
                                "id": "intent_123",
                                "agent_id": "agent-b",
                                "description": "Update API",
                                "overlap_scope": ("src/api.py",),
                            },
                        ),
                    },
                    "priority": None,
                },
                agent_id="agent-a",
                active_work_completion_ready=lambda **kwargs: False,
                renew_command=lambda: "loom renew",
                intent_command=lambda scope: f"loom intent --scope {' --scope '.join(scope)}",
                claim_command=lambda scope: f"loom claim --scope {' --scope '.join(scope)}",
                worktree_signal={
                    "has_drift": True,
                    "has_active_scope": False,
                    "suggested_scope": ("src/api.py",),
                },
            )

        output = buffer.getvalue()
        self.assertIn("Lease attention:", output)
        self.assertIn("next: loom renew --lease-minutes 30", output)
        self.assertIn("Yield attention:", output)
        self.assertIn("Yield to overlapping migration work.", output)
        self.assertIn("nearby intent intent_123 from agent-b: Update API", output)
        self.assertIn("next: loom finish", output)
        self.assertIn("Scope adoption:", output)
        self.assertIn("- loom claim --scope src/api.py", output)
        self.assertIn("Relevant changes since active work started (0):", output)

    def test_print_inbox_snapshot_clear_path_uses_next_steps(self) -> None:
        snapshot = InboxSnapshot(
            agent_id="agent-a",
            pending_context=(),
            conflicts=(),
            events=(),
        )
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            print_inbox_snapshot(
                snapshot,
                daemon_status=SimpleNamespace(describe=lambda: "running on daemon.sock"),
                identity={"id": "agent-a", "source": "env"},
                heading="Inbox for agent-a",
                next_steps=("loom start", "loom status"),
                identity_summary_printer=lambda **kwargs: print("Identity summary"),
            )

        output = buffer.getvalue()
        self.assertIn("Inbox for agent-a", output)
        self.assertIn("Daemon: running on daemon.sock", output)
        self.assertIn("Identity summary", output)
        self.assertIn("Attention: clear", output)
        self.assertIn("Inbox is clear.", output)
        self.assertIn("- loom start", output)
        self.assertIn("- loom status", output)

    def test_print_inbox_snapshot_lists_ack_and_resolve_commands(self) -> None:
        snapshot = InboxSnapshot(
            agent_id="agent-a",
            pending_context=(make_context(),),
            conflicts=(make_conflict(),),
            events=(make_event(),),
        )
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            print_inbox_snapshot(snapshot)

        output = buffer.getvalue()
        self.assertIn("Pending context (1):", output)
        self.assertIn("loom context ack context_123 --agent agent-a --status read", output)
        self.assertIn('--status adapted --note "<what changed>"', output)
        self.assertIn("Active conflicts (1):", output)
        self.assertIn('loom resolve conflict_123 --agent agent-a --note "<resolution>"', output)
        self.assertIn("Recent triggers (1):", output)

    def test_activity_suffix_marks_only_stale_agents(self) -> None:
        self.assertEqual(activity_suffix("agent-a", stale_agent_ids={"agent-a"}), " (stale)")
        self.assertEqual(activity_suffix("agent-b", stale_agent_ids={"agent-a"}), "")


if __name__ == "__main__":
    unittest.main()
