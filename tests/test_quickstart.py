from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli import main  # noqa: E402


@contextlib.contextmanager
def working_directory(path: pathlib.Path) -> pathlib.Path:
    previous = pathlib.Path.cwd()
    os.chdir(path)
    try:
        yield path
    finally:
        os.chdir(previous)


def run_cli(
    repo_root: pathlib.Path,
    argv: list[str],
    *,
    terminal_identity: str | None = None,
) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with working_directory(repo_root), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        if terminal_identity is None:
            exit_code = main(argv)
        else:
            with patch("loom.cli.current_terminal_identity", return_value=terminal_identity), patch(
                "loom.cli_runtime.current_terminal_identity",
                return_value=terminal_identity,
            ), patch(
                "loom.identity.current_terminal_identity",
                return_value=terminal_identity,
            ):
                exit_code = main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


class QuickstartTest(unittest.TestCase):
    def test_alpha_quickstart_conflict_loop_matches_documented_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            terminal_a = "tester@host:tty-a"
            terminal_b = "tester@host:tty-b"
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "middleware.py").write_text(
                "def auth_middleware():\n    return None\n"
            )
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n"
            )
            (repo_root / "src" / "api" / "rate_limit.py").write_text(
                "def rate_limit_hook():\n    return None\n"
            )

            exit_code, init_output, init_error = run_cli(
                repo_root,
                ["init", "--no-daemon"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=init_error)
            self.assertIn("Initialized Loom", init_output)

            exit_code, bind_a_output, bind_a_error = run_cli(
                repo_root,
                ["whoami", "--bind", "agent-a"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=bind_a_error)
            self.assertIn("Terminal binding set: agent-a", bind_a_output)
            self.assertIn("Agent: agent-a (source: terminal)", bind_a_output)

            exit_code, claim_a_output, claim_a_error = run_cli(
                repo_root,
                ["claim", "Refactor auth flow", "--scope", "src/auth"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=claim_a_error)
            self.assertIn("Agent: agent-a", claim_a_output)
            self.assertIn("Scope: src/auth", claim_a_output)

            exit_code, bind_b_output, bind_b_error = run_cli(
                repo_root,
                ["whoami", "--bind", "agent-b"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=bind_b_error)
            self.assertIn("Terminal binding set: agent-b", bind_b_output)
            self.assertIn("Agent: agent-b (source: terminal)", bind_b_output)

            exit_code, claim_b_output, claim_b_error = run_cli(
                repo_root,
                ["claim", "Add rate limiting hook", "--scope", "src/api"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=claim_b_error)
            self.assertIn("Agent: agent-b", claim_b_output)
            self.assertIn("Scope: src/api", claim_b_output)

            exit_code, intent_output, intent_error = run_cli(
                repo_root,
                [
                    "intent",
                    "Touch auth middleware",
                    "--reason",
                    "Need auth middleware integration",
                ],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=intent_error)
            self.assertIn("Scope source: inferred", intent_output)
            self.assertIn("matched auth, middleware", intent_output)
            self.assertIn("Conflicts detected:", intent_output)
            self.assertIn("loom conflicts", intent_output)

            exit_code, start_b_output, start_b_error = run_cli(
                repo_root,
                ["start"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=start_b_error)
            self.assertIn("Mode: attention", start_b_output)
            self.assertIn("Identity: agent-b (source: terminal)", start_b_output)
            self.assertIn("React now:", start_b_output)
            self.assertIn("loom resolve conflict_", start_b_output)

            exit_code, conflicts_output, conflicts_error = run_cli(
                repo_root,
                ["conflicts", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=conflicts_error)
            conflicts_payload = json.loads(conflicts_output)
            self.assertTrue(conflicts_payload["ok"])
            self.assertEqual(len(conflicts_payload["conflicts"]), 1)
            self.assertEqual(conflicts_payload["next_action"]["kind"], "conflict")
            self.assertEqual(conflicts_payload["next_action"]["confidence"], "high")
            conflict_id = conflicts_payload["conflicts"][0]["id"]

            exit_code, inbox_output, inbox_error = run_cli(
                repo_root,
                ["inbox", "--json"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=inbox_error)
            inbox_payload = json.loads(inbox_output)
            self.assertTrue(inbox_payload["ok"])
            self.assertEqual(inbox_payload["identity"]["id"], "agent-b")
            self.assertEqual(inbox_payload["attention"]["active_conflicts"], 1)
            self.assertEqual(inbox_payload["next_action"]["id"], conflict_id)
            self.assertEqual(inbox_payload["next_action"]["kind"], "conflict")

            exit_code, status_output, status_error = run_cli(
                repo_root,
                ["status", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=status_error)
            status_payload = json.loads(status_output)
            self.assertTrue(status_payload["ok"])
            self.assertEqual(len(status_payload["status"]["claims"]), 2)
            self.assertEqual(len(status_payload["status"]["intents"]), 1)
            self.assertEqual(len(status_payload["status"]["conflicts"]), 1)
            self.assertEqual(status_payload["next_action"]["command"], "loom conflicts")

            exit_code, resolve_output, resolve_error = run_cli(
                repo_root,
                [
                    "resolve",
                    conflict_id,
                    "--note",
                    "Shifted middleware work to avoid auth overlap.",
                ],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=resolve_error)
            self.assertIn(f"Conflict resolved: {conflict_id}", resolve_output)
            self.assertIn("Resolved by: agent-b", resolve_output)
            self.assertIn("Shifted middleware work to avoid auth overlap.", resolve_output)

            exit_code, status_after_output, status_after_error = run_cli(
                repo_root,
                ["status", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=status_after_error)
            status_after_payload = json.loads(status_after_output)
            self.assertTrue(status_after_payload["ok"])
            self.assertEqual(len(status_after_payload["status"]["claims"]), 2)
            self.assertEqual(len(status_after_payload["status"]["intents"]), 1)
            self.assertEqual(status_after_payload["status"]["conflicts"], [])

    def test_alpha_quickstart_context_dependency_loop_matches_existing_system_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            terminal_a = "tester@host:tty-a"
            terminal_b = "tester@host:tty-b"
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n"
            )
            (repo_root / "src" / "api" / "handlers.py").write_text(
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n"
            )

            exit_code, init_output, init_error = run_cli(
                repo_root,
                ["init", "--no-daemon"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=init_error)
            self.assertIn("Initialized Loom", init_output)

            exit_code, bind_b_output, bind_b_error = run_cli(
                repo_root,
                ["whoami", "--bind", "agent-b"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=bind_b_error)
            self.assertIn("Terminal binding set: agent-b", bind_b_output)

            exit_code, claim_b_output, claim_b_error = run_cli(
                repo_root,
                ["claim", "Update API handler return shape", "--scope", "src/api/handlers.py"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=claim_b_error)
            self.assertIn("Agent: agent-b", claim_b_output)
            self.assertIn("Scope: src/api/handlers.py", claim_b_output)

            exit_code, bind_a_output, bind_a_error = run_cli(
                repo_root,
                ["whoami", "--bind", "agent-a"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=bind_a_error)
            self.assertIn("Terminal binding set: agent-a", bind_a_output)

            exit_code, write_output, write_error = run_cli(
                repo_root,
                [
                    "context",
                    "write",
                    "auth-interface-change",
                    "UserSession now requires refresh_token.",
                    "--scope",
                    "src/auth/session.py",
                ],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=write_error)
            self.assertIn("Context recorded:", write_output)
            self.assertIn("Context dependencies surfaced:", write_output)
            self.assertIn(
                "agent-b claim may depend on agent-a context auth-interface-change via "
                "src/api/handlers.py -> src/auth/session.py",
                write_output,
            )

            exit_code, context_output, context_error = run_cli(
                repo_root,
                ["context", "read", "--json", "--limit", "5"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=context_error)
            context_payload = json.loads(context_output)
            self.assertTrue(context_payload["ok"])
            self.assertEqual(len(context_payload["context"]), 1)
            context_id = context_payload["context"][0]["id"]

            exit_code, conflicts_output, conflicts_error = run_cli(
                repo_root,
                ["conflicts", "--json"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=conflicts_error)
            conflicts_payload = json.loads(conflicts_output)
            self.assertTrue(conflicts_payload["ok"])
            self.assertEqual(len(conflicts_payload["conflicts"]), 1)
            self.assertEqual(conflicts_payload["conflicts"][0]["kind"], "contextual_dependency")
            conflict_id = conflicts_payload["conflicts"][0]["id"]

            exit_code, inbox_output, inbox_error = run_cli(
                repo_root,
                ["inbox", "--json"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=inbox_error)
            inbox_payload = json.loads(inbox_output)
            self.assertTrue(inbox_payload["ok"])
            self.assertEqual(inbox_payload["identity"]["id"], "agent-b")
            self.assertEqual(len(inbox_payload["inbox"]["pending_context"]), 1)
            self.assertEqual(inbox_payload["inbox"]["pending_context"][0]["id"], context_id)
            self.assertEqual(inbox_payload["attention"]["active_conflicts"], 1)
            self.assertEqual(inbox_payload["next_action"]["kind"], "conflict")

            exit_code, ack_output, ack_error = run_cli(
                repo_root,
                [
                    "context",
                    "ack",
                    context_id,
                    "--status",
                    "adapted",
                    "--note",
                    "Shifted handler work away from session internals.",
                ],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=ack_error)
            self.assertIn(f"Context acknowledged: {context_id}", ack_output)
            self.assertIn("Status: adapted", ack_output)
            self.assertIn("Shifted handler work away from session internals.", ack_output)

            exit_code, inbox_after_ack_output, inbox_after_ack_error = run_cli(
                repo_root,
                ["inbox", "--json"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=inbox_after_ack_error)
            inbox_after_ack_payload = json.loads(inbox_after_ack_output)
            self.assertEqual(inbox_after_ack_payload["inbox"]["pending_context"], [])
            self.assertEqual(inbox_after_ack_payload["attention"]["active_conflicts"], 1)
            self.assertEqual(inbox_after_ack_payload["next_action"]["kind"], "conflict")
            self.assertTrue(
                inbox_after_ack_payload["next_action"]["command"].startswith("loom resolve conflict_")
            )

            exit_code, resolve_output, resolve_error = run_cli(
                repo_root,
                [
                    "resolve",
                    conflict_id,
                    "--note",
                    "Acknowledged session change and adjusted the handler plan.",
                ],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=resolve_error)
            self.assertIn(f"Conflict resolved: {conflict_id}", resolve_output)
            self.assertIn("Resolved by: agent-b", resolve_output)

            exit_code, inbox_after_resolve_output, inbox_after_resolve_error = run_cli(
                repo_root,
                ["inbox", "--json"],
                terminal_identity=terminal_b,
            )
            self.assertEqual(exit_code, 0, msg=inbox_after_resolve_error)
            inbox_after_resolve_payload = json.loads(inbox_after_resolve_output)
            self.assertEqual(inbox_after_resolve_payload["inbox"]["pending_context"], [])
            self.assertEqual(inbox_after_resolve_payload["attention"]["active_conflicts"], 0)

            exit_code, status_output, status_error = run_cli(
                repo_root,
                ["status", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=status_error)
            status_payload = json.loads(status_output)
            self.assertTrue(status_payload["ok"])
            self.assertEqual(status_payload["status"]["conflicts"], [])
            self.assertEqual(len(status_payload["status"]["context"]), 1)
            self.assertEqual(
                status_payload["status"]["context"][0]["acknowledgments"][0]["status"],
                "adapted",
            )

    def test_alpha_quickstart_handoff_resume_loop_matches_documented_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            terminal_a = "tester@host:tty-a"
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "auth" / "middleware.py").write_text(
                "def auth_middleware():\n    return None\n"
            )

            exit_code, init_output, init_error = run_cli(
                repo_root,
                ["init", "--no-daemon"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=init_error)
            self.assertIn("Initialized Loom", init_output)

            exit_code, bind_output, bind_error = run_cli(
                repo_root,
                ["whoami", "--bind", "agent-a"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=bind_error)
            self.assertIn("Terminal binding set: agent-a", bind_output)

            exit_code, claim_output, claim_error = run_cli(
                repo_root,
                ["claim", "Refactor auth flow", "--scope", "src/auth"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=claim_error)
            self.assertIn("Scope: src/auth", claim_output)

            exit_code, intent_output, intent_error = run_cli(
                repo_root,
                [
                    "intent",
                    "Touch auth middleware",
                    "--reason",
                    "Need auth middleware cleanup",
                    "--scope",
                    "src/auth/middleware.py",
                ],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=intent_error)
            self.assertIn("Intent recorded:", intent_output)

            exit_code, finish_output, finish_error = run_cli(
                repo_root,
                [
                    "finish",
                    "--note",
                    "Paused after auth pass. Resume with auth cleanup.",
                ],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=finish_error)
            self.assertIn("Session finished for agent-a", finish_output)
            self.assertIn("Context recorded: context_", finish_output)
            self.assertIn("Intent released: intent_", finish_output)
            self.assertIn("Claim released: claim_", finish_output)

            exit_code, status_output, status_error = run_cli(
                repo_root,
                ["status", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=status_error)
            status_payload = json.loads(status_output)
            self.assertTrue(status_payload["ok"])
            self.assertEqual(status_payload["status"]["claims"], [])
            self.assertEqual(status_payload["status"]["intents"], [])
            self.assertEqual(len(status_payload["status"]["context"]), 1)
            self.assertEqual(status_payload["status"]["context"][0]["topic"], "session-handoff")
            self.assertEqual(
                status_payload["status"]["context"][0]["scope"],
                ["src/auth/middleware.py"],
            )

            exit_code, start_output, start_error = run_cli(
                repo_root,
                ["start", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=start_error)
            start_payload = json.loads(start_output)
            self.assertTrue(start_payload["ok"])
            self.assertEqual(start_payload["mode"], "active")
            self.assertIsNotNone(start_payload["handoff"])
            self.assertEqual(start_payload["handoff"]["topic"], "session-handoff")
            self.assertEqual(start_payload["handoff"]["scope"], ["src/auth/middleware.py"])
            self.assertEqual(
                start_payload["next_action"]["command"],
                'loom claim "Describe the work you\'re starting" --scope src/auth/middleware.py',
            )

            exit_code, resume_output, resume_error = run_cli(
                repo_root,
                ["resume", "--json", "--no-checkpoint"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=resume_error)
            resume_payload = json.loads(resume_output)
            self.assertTrue(resume_payload["ok"])
            self.assertEqual(resume_payload["identity"]["id"], "agent-a")
            self.assertFalse(resume_payload["checkpoint_updated"])
            self.assertEqual(resume_payload["after_sequence"], 0)
            self.assertIsNotNone(resume_payload["handoff"])
            self.assertEqual(resume_payload["handoff"]["topic"], "session-handoff")
            self.assertEqual(resume_payload["handoff"]["scope"], ["src/auth/middleware.py"])
            self.assertEqual(
                resume_payload["next_action"]["command"],
                'loom claim "Describe the work you\'re starting" --scope src/auth/middleware.py',
            )
            self.assertTrue(
                any(event["type"] == "context.published" for event in resume_payload["events"])
            )

    def test_alpha_quickstart_expired_lease_then_renew_loop_matches_stewardship_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            terminal_a = "tester@host:tty-a"
            (repo_root / ".git").mkdir()

            exit_code, init_output, init_error = run_cli(
                repo_root,
                ["init", "--no-daemon"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=init_error)
            self.assertIn("Initialized Loom", init_output)

            exit_code, bind_output, bind_error = run_cli(
                repo_root,
                ["whoami", "--bind", "agent-a"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=bind_error)
            self.assertIn("Terminal binding set: agent-a", bind_output)

            with patch("loom.local_store.store.utc_now", return_value="2026-03-17T10:00:00Z"):
                exit_code, claim_output, claim_error = run_cli(
                    repo_root,
                    [
                        "claim",
                        "Background dependency hygiene",
                        "--scope",
                        "src/deps",
                        "--lease-minutes",
                        "30",
                    ],
                    terminal_identity=terminal_a,
                )
                self.assertEqual(exit_code, 0, msg=claim_error)
                self.assertIn("Background dependency hygiene", claim_output)

                exit_code, intent_output, intent_error = run_cli(
                    repo_root,
                    [
                        "intent",
                        "Touch dependency metadata",
                        "--reason",
                        "Need lockfile cleanup",
                        "--scope",
                        "src/deps/lockfiles",
                        "--lease-minutes",
                        "30",
                    ],
                    terminal_identity=terminal_a,
                )
                self.assertEqual(exit_code, 0, msg=intent_error)
                self.assertIn("Touch dependency metadata", intent_output)

            exit_code, status_output, status_error = run_cli(
                repo_root,
                ["status", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=status_error)
            status_payload = json.loads(status_output)
            self.assertTrue(status_payload["ok"])
            self.assertEqual(status_payload["next_action"]["kind"], "lease")
            self.assertEqual(status_payload["next_action"]["command"], "loom renew")

            exit_code, start_output, start_error = run_cli(
                repo_root,
                ["start", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=start_error)
            start_payload = json.loads(start_output)
            self.assertTrue(start_payload["ok"])
            self.assertIsNotNone(start_payload["active_work"]["lease_alert"])
            self.assertEqual(start_payload["active_work"]["lease_alert"]["policy"], "renew")
            self.assertEqual(
                {entry["kind"] for entry in start_payload["active_work"]["expired_leases"]},
                {"claim", "intent"},
            )

            exit_code, renew_output, renew_error = run_cli(
                repo_root,
                ["renew", "--lease-minutes", "90", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=renew_error)
            renew_payload = json.loads(renew_output)
            self.assertTrue(renew_payload["ok"])
            self.assertEqual(renew_payload["lease_minutes"], 90)
            self.assertIsNotNone(renew_payload["claim"])
            self.assertIsNotNone(renew_payload["intent"])
            self.assertIsNotNone(renew_payload["claim"]["lease_expires_at"])
            self.assertIsNotNone(renew_payload["intent"]["lease_expires_at"])
            self.assertEqual(renew_payload["next_steps"][0], "loom agent")

            exit_code, start_after_output, start_after_error = run_cli(
                repo_root,
                ["start", "--json"],
                terminal_identity=terminal_a,
            )
            self.assertEqual(exit_code, 0, msg=start_after_error)
            start_after_payload = json.loads(start_after_output)
            self.assertTrue(start_after_payload["ok"])
            self.assertIsNone(start_after_payload["active_work"]["lease_alert"])
            self.assertEqual(start_after_payload["active_work"]["expired_leases"], [])
            self.assertNotEqual(start_after_payload["next_action"]["command"], "loom renew")


if __name__ == "__main__":
    unittest.main()
