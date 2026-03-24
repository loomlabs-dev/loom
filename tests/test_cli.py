from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import signal
import sqlite3
import threading
import tempfile
import sys
import time
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom import __version__  # noqa: E402
from loom.cli import main  # noqa: E402
import loom.daemon.runtime as daemon_runtime  # noqa: E402
import loom.local_store.store as store_module  # noqa: E402
from loom.daemon import DaemonControlResult, DaemonStatus  # noqa: E402
from loom.dependency_graph import DependencyGraph  # noqa: E402
from loom.identity import terminal_identity_is_stable  # noqa: E402
from loom.local_store import (  # noqa: E402
    AgentPresenceRecord,
    AgentSnapshot,
    ClaimRecord,
    ConflictRecord,
    ContextAckRecord,
    ContextRecord,
    CoordinationStore,
    EventRecord,
    InboxSnapshot,
    IntentRecord,
    StatusSnapshot,
)
from loom.project import initialize_project, load_project  # noqa: E402


@contextlib.contextmanager
def working_directory(path: pathlib.Path) -> pathlib.Path:
    previous = pathlib.Path.cwd()
    os.chdir(path)
    try:
        yield path
    finally:
        os.chdir(previous)


def init_command(*extra: str) -> list[str]:
    return ["init", "--no-daemon", *extra]


class CliTest(unittest.TestCase):
    def test_init_creates_local_project_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                exit_code = main(init_command())

            output = stdout.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn("Initialized Loom", output)
            self.assertIn("loom start", output)
            if terminal_identity_is_stable():
                self.assertIn("loom start --bind <agent-name>", output)
            else:
                self.assertIn("export LOOM_AGENT=<agent-name>", output)
            self.assertIn(
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                output,
            )
            self.assertTrue((repo_root / ".loom" / "config.json").exists())
            self.assertTrue((repo_root / ".loom" / "coordination.db").exists())

    def test_init_attempts_daemon_start_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()

            with patch(
                "loom.cli.start_daemon",
                return_value=DaemonControlResult(
                    detail="Daemon started.",
                    pid=4242,
                    log_path=repo_root / ".loom" / "daemon.log",
                ),
            ) as start_daemon_mock:
                with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                    exit_code = main(["init"])

            output = stdout.getvalue()

            self.assertEqual(exit_code, 0)
            start_daemon_mock.assert_called_once()
            self.assertIn("Daemon: Daemon started.", output)
            self.assertIn("PID: 4242", output)

    def test_init_falls_back_to_direct_mode_when_daemon_start_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()

            with patch(
                "loom.cli.start_daemon",
                side_effect=RuntimeError(
                    f"Failed to start daemon. Check {repo_root / '.loom' / 'daemon.log'}."
                ),
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                    exit_code = main(["init"])

            output = stdout.getvalue()

            self.assertEqual(exit_code, 0)
            self.assertIn("Daemon: direct SQLite mode", output)
            self.assertIn("Failed to start daemon.", output)

    def test_init_can_set_repo_default_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            claim_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            project = load_project(repo_root)
            self.assertEqual(project.default_agent, "agent-a")
            self.assertIn("Default agent: agent-a", init_stdout.getvalue())

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            self.assertIn("Agent: agent-a", claim_stdout.getvalue())

    def test_whoami_reports_project_default_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            whoami_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(whoami_stdout):
                self.assertEqual(main(["whoami"]), 0)

            output = whoami_stdout.getvalue()
            self.assertIn("Agent: agent-a", output)
            self.assertIn("(source: project)", output)
            self.assertIn("Project default: agent-a", output)
            self.assertIn("Next:", output)
            self.assertIn("loom start", output)
            self.assertIn(
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                output,
            )

    def test_whoami_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            whoami_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(whoami_stdout):
                self.assertEqual(main(["whoami", "--json"]), 0)

            payload = json.loads(whoami_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["agent"]["id"], "agent-a")
            self.assertEqual(payload["agent"]["source"], "project")
            self.assertIn("terminal_identity", payload["agent"])
            self.assertEqual(payload["agent"]["project_default_agent"], "agent-a")
            self.assertTrue(payload["agent"]["project_initialized"])
            self.assertEqual(payload["next_steps"][0], "loom start")
            self.assertIn(
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                payload["next_steps"],
            )

    def test_whoami_warns_when_terminal_identity_is_pid_based(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()

            with working_directory(repo_root), patch(
                "loom.cli.current_terminal_identity",
                return_value="tester@host:pid-12345",
            ), patch(
                "loom.cli_runtime.current_terminal_identity",
                return_value="tester@host:pid-12345",
            ), patch(
                "loom.identity.current_terminal_identity",
                return_value="tester@host:pid-12345",
            ):
                self.assertEqual(main(["init", "--no-daemon"]), 0)
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["whoami"]), 0)

            output = stdout.getvalue()
            self.assertIn("Identity note:", output)
            self.assertIn("no stable terminal identity", output)
            self.assertIn("export LOOM_AGENT=<agent-name>", output)
            self.assertNotIn("loom whoami --bind <agent-name>", output)

    def test_start_prefers_env_guidance_when_terminal_identity_is_pid_based(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()

            with working_directory(repo_root), patch(
                "loom.cli.current_terminal_identity",
                return_value="tester@host:pid-12345",
            ), patch(
                "loom.cli_runtime.current_terminal_identity",
                return_value="tester@host:pid-12345",
            ), patch(
                "loom.identity.current_terminal_identity",
                return_value="tester@host:pid-12345",
            ):
                self.assertEqual(main(["init", "--no-daemon"]), 0)
                with contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["start"]), 0)

            output = stdout.getvalue()
            self.assertIn("Identity note:", output)
            self.assertIn("export LOOM_AGENT=<agent-name>", output)
            self.assertNotIn("loom whoami --bind <agent-name>", output)

    def test_whoami_env_overrides_project_default_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            whoami_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            with patch.dict(os.environ, {"LOOM_AGENT": "agent-env"}, clear=False):
                with working_directory(repo_root), contextlib.redirect_stdout(whoami_stdout):
                    self.assertEqual(main(["whoami"]), 0)

            output = whoami_stdout.getvalue()
            self.assertIn("Agent: agent-env", output)
            self.assertIn("(source: env)", output)
            self.assertIn("Project default: agent-a", output)

    def test_start_before_init_guides_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start"]), 0)

            output = stdout.getvalue()
            self.assertIn("Loom start", output)
            self.assertIn("Project: not initialized", output)
            self.assertIn("Mode: uninitialized", output)
            self.assertIn("Do this first:", output)
            self.assertIn("next: loom init --no-daemon", output)
            self.assertIn("Coordination rule:", output)
            self.assertIn("Use Loom only for coordination in this repository.", output)
            self.assertIn("Do not inspect `.loom/`, `.loom-reports/`", output)
            self.assertIn("Quick loop:", output)
            self.assertIn("claim: say what you're working on before edits", output)
            self.assertIn(
                "intent: say what you're about to touch only when the scope gets specific",
                output,
            )
            self.assertIn("loom init --no-daemon", output)
            if terminal_identity_is_stable():
                self.assertIn("loom start --bind <agent-name>", output)
            else:
                self.assertIn("export LOOM_AGENT=<agent-name>", output)

    def test_start_before_init_json_uses_shared_bootstrap_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "uninitialized")
            expected_bind = (
                "loom start --bind <agent-name>"
                if terminal_identity_is_stable()
                else "export LOOM_AGENT=<agent-name>"
            )
            self.assertEqual(
                payload["next_steps"],
                [
                    "loom init --no-daemon",
                    expected_bind,
                    'loom claim "Describe the work you\'re starting" --scope path/to/area',
                ],
            )
            self.assertEqual(
                payload["quick_loop"],
                [
                    "start: run loom start, follow the next action, then loop back if needed",
                    "claim: say what you're working on before edits",
                    "intent: say what you're about to touch only when the scope gets specific",
                    "inbox: react to context or conflicts before continuing",
                    "finish: release work cleanly when you're done for now",
                ],
            )
            self.assertEqual(
                payload["command_guide"],
                [
                    {
                        "command": "loom start",
                        "summary": "Read the board, then follow Loom's best next move.",
                    },
                    {
                        "command": "loom init --no-daemon",
                        "summary": "Initialize Loom in this repository before coordination begins.",
                    },
                    {
                        "command": expected_bind,
                        "summary": "Pin a stable agent identity before coordinated work.",
                    },
                    {
                        "command": "loom claim",
                        "summary": "Reserve the work before edits.",
                    },
                    {
                        "command": "loom intent",
                        "summary": "Narrow to the exact scope once the edit is specific.",
                    },
                    {
                        "command": "loom inbox",
                        "summary": "React to context or conflicts before continuing.",
                    },
                    {
                        "command": "loom finish",
                        "summary": "Release work cleanly when you are done for now.",
                    },
                ],
            )
            self.assertEqual(payload["next_action"]["command"], "loom init --no-daemon")

    def test_start_after_init_without_stable_identity_nudges_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "needs_identity")
            self.assertEqual(payload["identity"]["source"], "tty")
            self.assertEqual(
                payload["summary"],
                f"{payload['identity']['id']} is a raw terminal identity. Resolve a stable agent before coordinated work.",
            )
            if terminal_identity_is_stable():
                self.assertEqual(
                    payload["next_steps"],
                    [
                        "loom start --bind <agent-name>",
                        'loom claim "Describe the work you\'re starting" --scope path/to/area',
                        "loom status",
                    ],
                )
                self.assertEqual(
                    payload["next_action"]["command"],
                    "loom start --bind <agent-name>",
                )
            else:
                self.assertEqual(
                    payload["next_steps"],
                    [
                        "export LOOM_AGENT=<agent-name>",
                        "loom start",
                        'loom claim "Describe the work you\'re starting" --scope path/to/area',
                    ],
                )
                self.assertEqual(
                    payload["next_action"]["command"],
                    "export LOOM_AGENT=<agent-name>",
                )
            self.assertEqual(payload["next_action"]["confidence"], "high")

    def test_start_after_init_without_stable_identity_prints_next_action_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                self.assertEqual(main(["start"]), 0)

            output = start_stdout.getvalue()
            self.assertIn("Do this first:", output)
            self.assertIn("Coordination rule:", output)
            if terminal_identity_is_stable():
                self.assertIn("next: loom start --bind <agent-name>", output)
            else:
                self.assertIn("next: export LOOM_AGENT=<agent-name>", output)

    def test_start_bind_sets_terminal_alias_and_runs_start_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                self.assertEqual(main(["start", "--bind", "agent-seat"]), 0)

            project = load_project(repo_root)
            self.assertTrue(project.terminal_aliases)

            output = start_stdout.getvalue()
            self.assertIn("Terminal binding set: agent-seat", output)
            self.assertIn("Identity: agent-seat (source: terminal)", output)
            self.assertIn("Do this first:", output)
            self.assertIn("next: loom claim", output)

    def test_start_bind_warns_when_terminal_identity_is_pid_based(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            start_stdout = io.StringIO()
            raw_terminal_identity = "tester@host:pid-12345"

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with patch("loom.identity.current_terminal_identity", return_value=raw_terminal_identity), patch(
                "loom.cli.current_terminal_identity",
                return_value=raw_terminal_identity,
            ), patch(
                "loom.cli_runtime.current_terminal_identity",
                return_value=raw_terminal_identity,
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--bind", "agent-seat"]), 0)

            output = start_stdout.getvalue()
            self.assertIn("Terminal binding set: agent-seat", output)
            self.assertIn("export LOOM_AGENT=agent-seat", output)
            self.assertIn("Identity note:", output)
            self.assertIn("repeatable agent identity", output)
            self.assertIn("Mode: needs_identity", output)
            self.assertIn("Do this first: Pin a stable Loom agent identity for this shell.", output)
            self.assertIn("next: export LOOM_AGENT=agent-seat", output)

    def test_start_bind_json_promotes_env_followup_when_terminal_identity_is_pid_based(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            raw_terminal_identity = "tester@host:pid-12345"
            init_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with patch("loom.identity.current_terminal_identity", return_value=raw_terminal_identity), patch(
                "loom.cli.current_terminal_identity",
                return_value=raw_terminal_identity,
            ), patch(
                "loom.cli_runtime.current_terminal_identity",
                return_value=raw_terminal_identity,
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--bind", "agent-seat", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "needs_identity")
            self.assertIn("still needs LOOM_AGENT", payload["summary"])
            self.assertEqual(payload["next_action"]["command"], "export LOOM_AGENT=agent-seat")
            self.assertEqual(
                payload["next_steps"],
                [
                    "export LOOM_AGENT=agent-seat",
                    "loom start",
                    'loom claim "Describe the work you\'re starting" --scope path/to/area',
                ],
            )
            self.assertIn(
                {
                    "command": "export LOOM_AGENT=agent-seat",
                    "summary": "Pin a stable agent identity before coordinated work.",
                },
                payload["command_guide"],
            )

    def test_start_with_conflicts_points_to_inbox_and_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "attention")
            self.assertEqual(payload["attention"]["conflicts"], 1)
            self.assertEqual(payload["attention"]["agent_conflicts"], 1)
            self.assertIsNotNone(payload["active_work"]["started_at"])
            self.assertTrue(payload["summary"].startswith("agent-a should react to conflict "))
            self.assertTrue(payload["next_steps"][0].startswith("loom resolve conflict_"))
            self.assertEqual(payload["next_steps"][1], "loom inbox")
            self.assertEqual(payload["next_steps"][2], "loom status")
            self.assertTrue(payload["next_action"]["command"].startswith("loom resolve conflict_"))
            self.assertEqual(payload["next_action"]["kind"], "conflict")
            self.assertEqual(payload["next_action"]["confidence"], "high")

    def test_start_with_active_work_prints_recovery_narrative(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                self.assertEqual(main(["start"]), 0)

            output = start_stdout.getvalue()
            self.assertIn("Do this first: conflict", output)
            self.assertIn("React now:", output)
            self.assertIn("Working tree:", output)
            self.assertIn("Next:", output)
            self.assertIn("loom resolve conflict_", output)

    def test_start_with_settled_active_work_suggests_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "active")
            self.assertIn("looks settled", payload["summary"])
            self.assertEqual(
                payload["next_steps"],
                [
                    "loom finish",
                    "loom status",
                    "loom agent",
                ],
            )
            self.assertEqual(payload["next_action"]["command"], "loom finish")
            self.assertEqual(payload["next_action"]["confidence"], "high")

    def test_start_with_expired_lease_suggests_renew_before_continuing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--scope",
                            "src/auth",
                            "--lease-minutes",
                            "30",
                        ]
                    ),
                    0,
                )

            with patch("loom.guidance.is_past_utc_timestamp", return_value=True), patch(
                "loom.guidance.current_worktree_paths",
                return_value=("src/auth/session.py",),
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertIsNotNone(payload["active_work"]["lease_alert"])
            self.assertEqual(payload["active_work"]["expired_leases"][0]["kind"], "claim")
            self.assertEqual(payload["active_work"]["expired_leases"][0]["lease_policy"], "renew")
            self.assertEqual(payload["next_action"]["command"], "loom renew")
            self.assertEqual(payload["next_action"]["kind"], "lease")
            self.assertEqual(payload["next_steps"][0], "loom renew")

    def test_start_with_expired_yield_policy_suggests_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background dependency hygiene",
                            "--scope",
                            "src/deps",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )

            with patch("loom.guidance.is_past_utc_timestamp", return_value=True), patch(
                "loom.guidance.current_worktree_paths",
                return_value=("src/deps/lockfile.py",),
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["active_work"]["lease_alert"]["policy"], "yield")
            self.assertEqual(payload["active_work"]["expired_leases"][0]["lease_policy"], "yield")
            self.assertEqual(payload["next_action"]["command"], "loom finish")
            self.assertEqual(payload["next_steps"][0], "loom finish")

    def test_start_with_yield_policy_and_pending_context_prefers_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background dependency hygiene",
                            "--scope",
                            "src/deps",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "deps-are-moving",
                            "Feature work is changing dependency behavior right now.",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/deps",
                        ]
                    ),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertIsNone(payload["active_work"]["lease_alert"])
            self.assertEqual(payload["active_work"]["yield_alert"]["policy"], "yield")
            self.assertEqual(payload["next_action"]["command"], "loom finish")
            self.assertEqual(payload["next_action"]["kind"], "yield")
            self.assertEqual(payload["next_steps"][0], "loom finish")

    def test_agent_view_with_yield_policy_and_nearby_intent_prefers_finish(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            agent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth cleanup",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth session internals",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Refactor auth session implementation",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                status_payload = json.loads(status_stdout.getvalue())
                conflict_ids = [item["id"] for item in status_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Nearby work is intentional."]),
                        0,
                    )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/auth/session",)):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a", "--json"]), 0)

            payload = json.loads(agent_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["active_work"]["yield_alert"]["policy"], "yield")
            self.assertTrue(payload["active_work"]["yield_alert"]["acknowledged"])
            self.assertEqual(payload["active_work"]["yield_alert"]["confidence"], "medium")
            self.assertEqual(payload["active_work"]["yield_alert"]["nearby"][0]["risk"], "high")
            self.assertTrue(payload["active_work"]["yield_alert"]["nearby"][0]["acknowledged"])
            self.assertIn(
                "acknowledged nearby active work",
                payload["active_work"]["yield_alert"]["reason"],
            )
            self.assertEqual(payload["next_action"]["command"], "loom finish")

    def test_agent_view_with_yield_policy_ignores_broad_nearby_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            agent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth cleanup",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth session internals",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Broad auth work",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                status_payload = json.loads(status_stdout.getvalue())
                conflict_ids = [item["id"] for item in status_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Broad claim noted."]),
                        0,
                    )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/auth/session",)):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a", "--json"]), 0)

            payload = json.loads(agent_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertIsNone(payload["active_work"]["yield_alert"])
            self.assertEqual(payload["next_action"]["command"], "loom status")

    def test_agent_view_with_yield_policy_ignores_stale_nearby_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            agent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth cleanup",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth session internals",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Direct auth session work",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                status_payload = json.loads(status_stdout.getvalue())
                conflict_ids = [item["id"] for item in status_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Stale nearby claim acknowledged."]),
                        0,
                    )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/auth/session",)):
                with patch("loom.cli.is_stale_utc_timestamp", return_value=True):
                    with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                        self.assertEqual(main(["agent", "--agent", "agent-a", "--json"]), 0)

            payload = json.loads(agent_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertIsNone(payload["active_work"]["yield_alert"])
            self.assertEqual(payload["next_action"]["command"], "loom status")

    def test_agent_view_with_yield_policy_prefers_finish_for_semantic_nearby_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.py").write_text(
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
                encoding="utf-8",
            )
            agent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background API cleanup",
                            "--scope",
                            "src/api/handlers.py",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch API handler response shape",
                            "--scope",
                            "src/api/handlers.py",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth session model",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session.py",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch broader API surface",
                            "--agent",
                            "agent-c",
                            "--scope",
                            "src/api",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                status_payload = json.loads(status_stdout.getvalue())
                conflict_ids = [item["id"] for item in status_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Semantic nearby work acknowledged."]),
                        0,
                    )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/api/handlers.py",)):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a", "--json"]), 0)

            payload = json.loads(agent_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["active_work"]["yield_alert"]["policy"], "yield")
            self.assertTrue(payload["active_work"]["yield_alert"]["acknowledged"])
            self.assertEqual(payload["active_work"]["yield_alert"]["confidence"], "medium")
            self.assertEqual(payload["active_work"]["yield_alert"]["urgency"], "fresh")
            self.assertEqual(payload["active_work"]["yield_alert"]["nearby"][0]["relationship"], "dependency")
            self.assertTrue(payload["active_work"]["yield_alert"]["nearby"][0]["acknowledged"])
            self.assertEqual(payload["active_work"]["yield_alert"]["nearby"][0]["urgency"], "fresh")
            self.assertEqual(payload["active_work"]["yield_alert"]["nearby"][0]["risk"], "high")
            self.assertGreaterEqual(len(payload["active_work"]["yield_alert"]["nearby"]), 2)
            self.assertEqual(payload["active_work"]["yield_alert"]["nearby"][1]["relationship"], "scope")
            self.assertIn(
                "fresh acknowledged nearby active work",
                payload["active_work"]["yield_alert"]["reason"],
            )
            self.assertIn("semantically entangled", payload["active_work"]["yield_alert"]["reason"])
            self.assertEqual(payload["next_action"]["command"], "loom finish")

    def test_agent_view_with_yield_policy_marks_older_nearby_claim_as_ongoing_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            agent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth cleanup",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth session internals",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Direct auth session work",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                status_payload = json.loads(status_stdout.getvalue())
                conflict_ids = [item["id"] for item in status_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Older nearby claim acknowledged."]),
                        0,
                    )

            connection = sqlite3.connect(repo_root / ".loom" / "coordination.db")
            try:
                connection.execute(
                    """
                    UPDATE claims
                    SET created_at = '2026-03-01T00:00:00Z'
                    WHERE agent_id = 'agent-b'
                    """
                )
                connection.commit()
            finally:
                connection.close()

            with patch("loom.guidance.current_worktree_paths", return_value=("src/auth/session",)):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a", "--json"]), 0)

            payload = json.loads(agent_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["active_work"]["yield_alert"]["policy"], "yield")
            self.assertTrue(payload["active_work"]["yield_alert"]["acknowledged"])
            self.assertEqual(payload["active_work"]["yield_alert"]["urgency"], "ongoing")
            self.assertEqual(payload["active_work"]["yield_alert"]["confidence"], "low")
            self.assertTrue(payload["active_work"]["yield_alert"]["nearby"][0]["acknowledged"])
            self.assertEqual(payload["active_work"]["yield_alert"]["nearby"][0]["urgency"], "ongoing")
            self.assertIn(
                "acknowledged nearby active work that is still live",
                payload["active_work"]["yield_alert"]["reason"],
            )
            self.assertEqual(payload["next_action"]["command"], "loom finish")

    def test_status_with_yield_policy_marks_older_nearby_claim_as_ongoing_pressure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth cleanup",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth session internals",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Direct auth session work",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session",
                        ]
                    ),
                    0,
                )
                with contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                status_payload = json.loads(status_stdout.getvalue())
                conflict_ids = [item["id"] for item in status_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Older nearby claim acknowledged."]),
                        0,
                    )

            connection = sqlite3.connect(repo_root / ".loom" / "coordination.db")
            try:
                connection.execute(
                    """
                    UPDATE claims
                    SET created_at = '2026-03-01T00:00:00Z'
                    WHERE agent_id = 'agent-b'
                    """
                )
                connection.commit()
            finally:
                connection.close()

            status_stdout = io.StringIO()
            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status", "--json"]), 0)

            payload = json.loads(status_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["repo_lanes"]["acknowledged_migration_lanes"], 1)
            self.assertEqual(payload["repo_lanes"]["fresh_acknowledged_migration_lanes"], 0)
            self.assertEqual(payload["repo_lanes"]["ongoing_acknowledged_migration_lanes"], 1)
            self.assertEqual(payload["repo_lanes"]["acknowledged_migration_programs"], 1)
            self.assertEqual(payload["repo_lanes"]["fresh_acknowledged_migration_programs"], 0)
            self.assertEqual(payload["repo_lanes"]["ongoing_acknowledged_migration_programs"], 1)
            self.assertEqual(len(payload["repo_lanes"]["lanes"]), 1)
            self.assertEqual(payload["repo_lanes"]["lanes"][0]["scope"], ["src/auth/session"])
            self.assertEqual(payload["repo_lanes"]["lanes"][0]["relationship"], "scope")
            self.assertEqual(payload["repo_lanes"]["lanes"][0]["participant_count"], 2)
            self.assertEqual(len(payload["repo_lanes"]["programs"]), 1)
            self.assertEqual(payload["repo_lanes"]["programs"][0]["scope_hint"], "src/auth")
            self.assertEqual(payload["repo_lanes"]["programs"][0]["lane_count"], 1)
            self.assertEqual(payload["next_action"]["command"], "loom finish")
            self.assertEqual(payload["next_action"]["kind"], "yield")
            self.assertEqual(payload["next_action"]["urgency"], "ongoing")
            self.assertEqual(payload["next_action"]["confidence"], "low")
            self.assertIn(
                "acknowledged nearby active work that is still live",
                payload["next_action"]["reason"],
            )

    def test_start_surfaces_acknowledged_migration_lane_as_repo_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-z"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth cleanup",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth session internals",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Refactor auth session implementation",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session",
                        ]
                    ),
                    0,
                )
                status_stdout = io.StringIO()
                with contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                status_payload = json.loads(status_stdout.getvalue())
                conflict_ids = [item["id"] for item in status_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Nearby work is intentional."]),
                        0,
                    )

            with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "active")
            self.assertEqual(payload["attention"]["acknowledged_migration_lanes"], 1)
            self.assertEqual(payload["repo_lanes"]["acknowledged_migration_lanes"], 1)
            self.assertEqual(payload["repo_lanes"]["fresh_acknowledged_migration_lanes"], 1)
            self.assertEqual(payload["repo_lanes"]["ongoing_acknowledged_migration_lanes"], 0)
            self.assertEqual(payload["repo_lanes"]["acknowledged_migration_programs"], 1)
            self.assertEqual(len(payload["repo_lanes"]["lanes"]), 1)
            self.assertEqual(payload["repo_lanes"]["lanes"][0]["scope"], ["src/auth/session"])
            self.assertEqual(payload["repo_lanes"]["lanes"][0]["participant_count"], 2)
            self.assertEqual(payload["repo_lanes"]["programs"][0]["scope_hint"], "src/auth")
            self.assertEqual(
                payload["summary"],
                "The repository already has acknowledged migration work in flight.",
            )
            self.assertEqual(payload["next_action"]["command"], "loom status")
            self.assertIn(
                "acknowledged long-running coordinated change already in flight",
                payload["next_action"]["reason"],
            )

    def test_status_groups_acknowledged_migration_lanes_by_shared_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-z"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth cleanup",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth session internals",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth validation cleanup",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Refactor auth validation flow",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/session",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Refactor auth session implementation",
                            "--agent",
                            "agent-c",
                            "--scope",
                            "src/auth/session",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background billing cleanup",
                            "--agent",
                            "agent-d",
                            "--scope",
                            "src/billing/payments",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background auth validation cleanup",
                            "--agent",
                            "agent-f",
                            "--scope",
                            "src/auth/validation",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth validation internals",
                            "--agent",
                            "agent-f",
                            "--scope",
                            "src/auth/validation",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Refactor auth validation rules",
                            "--agent",
                            "agent-g",
                            "--scope",
                            "src/auth/validation",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch billing payment internals",
                            "--agent",
                            "agent-d",
                            "--scope",
                            "src/billing/payments",
                            "--lease-minutes",
                            "30",
                            "--lease-policy",
                            "yield",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Refactor billing payment flow",
                            "--agent",
                            "agent-e",
                            "--scope",
                            "src/billing/payments",
                        ]
                    ),
                    0,
                )
                conflict_stdout = io.StringIO()
                with contextlib.redirect_stdout(conflict_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)
                conflict_payload = json.loads(conflict_stdout.getvalue())
                conflict_ids = [item["id"] for item in conflict_payload["status"]["conflicts"]]
                self.assertTrue(conflict_ids)
                for conflict_id in conflict_ids:
                    self.assertEqual(
                        main(["resolve", conflict_id, "--note", "Migration lane acknowledged."]),
                        0,
                    )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status", "--json"]), 0)

            payload = json.loads(status_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["repo_lanes"]["acknowledged_migration_lanes"], 3)
            self.assertEqual(payload["repo_lanes"]["fresh_acknowledged_migration_lanes"], 3)
            self.assertEqual(payload["repo_lanes"]["ongoing_acknowledged_migration_lanes"], 0)
            self.assertEqual(payload["repo_lanes"]["acknowledged_migration_programs"], 2)
            self.assertEqual(payload["repo_lanes"]["fresh_acknowledged_migration_programs"], 2)
            self.assertEqual(payload["repo_lanes"]["ongoing_acknowledged_migration_programs"], 0)
            self.assertEqual(len(payload["repo_lanes"]["lanes"]), 3)
            self.assertEqual(len(payload["repo_lanes"]["programs"]), 2)
            lanes_by_scope = {
                tuple(item["scope"]): item
                for item in payload["repo_lanes"]["lanes"]
            }
            self.assertEqual(
                lanes_by_scope[("src/auth/session",)]["participant_count"],
                3,
            )
            self.assertEqual(
                sorted(lanes_by_scope[("src/auth/session",)]["agents"]),
                ["agent-a", "agent-b", "agent-c"],
            )
            self.assertEqual(
                lanes_by_scope[("src/billing/payments",)]["participant_count"],
                2,
            )
            self.assertEqual(
                sorted(lanes_by_scope[("src/billing/payments",)]["agents"]),
                ["agent-d", "agent-e"],
            )
            self.assertEqual(
                lanes_by_scope[("src/auth/validation",)]["participant_count"],
                2,
            )
            programs_by_hint = {
                item["scope_hint"]: item
                for item in payload["repo_lanes"]["programs"]
            }
            self.assertEqual(programs_by_hint["src/auth"]["lane_count"], 2)
            self.assertEqual(programs_by_hint["src/auth"]["participant_count"], 5)
            self.assertEqual(programs_by_hint["src/billing"]["lane_count"], 1)

    def test_start_surfaces_worktree_drift_for_current_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/billing/invoice.py",)):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "attention")
            self.assertIsNotNone(payload["active_work"]["started_at"])
            self.assertEqual(payload["attention"]["worktree_drift"], 1)
            self.assertEqual(payload["worktree"]["drift_paths"], ["src/billing/invoice.py"])
            self.assertEqual(payload["worktree"]["suggested_scope"], ["src/auth", "src/billing"])
            self.assertEqual(
                payload["next_steps"],
                [
                    'loom intent "Describe the edit you\'re about to make" --scope src/auth --scope src/billing',
                    "loom agent",
                    "loom status",
                ],
            )

    def test_start_surfaces_worktree_scope_suggestion_without_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            with patch(
                "loom.guidance.current_worktree_paths",
                return_value=("src/mobile/app.dart", "src/mobile/session.dart"),
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "attention")
            self.assertEqual(payload["attention"]["worktree_drift"], 2)
            self.assertEqual(payload["worktree"]["suggested_scope"], ["src/mobile"])
            self.assertEqual(
                payload["next_steps"],
                [
                    'loom claim "Describe the work you\'re starting" --scope src/mobile',
                    "loom status",
                    "loom agent",
                ],
            )

    def test_whoami_bind_sets_terminal_alias_and_claim_uses_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            whoami_stdout = io.StringIO()
            claim_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(whoami_stdout):
                self.assertEqual(main(["whoami", "--bind", "agent-seat"]), 0)

            project = load_project(repo_root)
            self.assertTrue(project.terminal_aliases)
            self.assertIn("Terminal binding set: agent-seat", whoami_stdout.getvalue())
            self.assertIn(
                "Coordination rule: Loom is already active here. Do not inspect `.loom/`, `.loom-reports/`, or Loom internals; run `loom start` and follow the returned next action.",
                whoami_stdout.getvalue(),
            )
            self.assertIn("(source: terminal)", whoami_stdout.getvalue())
            self.assertIn("Next:", whoami_stdout.getvalue())
            self.assertIn("loom status", whoami_stdout.getvalue())

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            self.assertIn("Agent: agent-seat", claim_stdout.getvalue())

    def test_whoami_bind_adopts_existing_terminal_work_into_bound_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            raw_terminal_identity = "tester@host:pid-12345"
            bind_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon"]), 0)

            with patch("loom.identity.current_terminal_identity", return_value=raw_terminal_identity):
                with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(
                        main(
                            [
                                "claim",
                                "Refactor auth flow",
                                "--scope",
                                "src/auth",
                            ]
                        ),
                        0,
                    )

            with patch("loom.identity.current_terminal_identity", return_value=raw_terminal_identity), patch(
                "loom.cli.current_terminal_identity",
                return_value=raw_terminal_identity,
            ), patch(
                "loom.cli_runtime.current_terminal_identity",
                return_value=raw_terminal_identity,
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(bind_stdout):
                    self.assertEqual(main(["whoami", "--bind", "agent-seat"]), 0)

            output = bind_stdout.getvalue()
            self.assertIn("Terminal binding set: agent-seat", output)
            self.assertIn(
                "Coordination rule: Loom is already active here. Do not inspect `.loom/`, `.loom-reports/`, or Loom internals; run `loom start` and follow the returned next action.",
                output,
            )
            self.assertIn(f"Adopted active work from: {raw_terminal_identity}", output)
            self.assertIn("repeatable agent identity", output)
            self.assertIn("- export LOOM_AGENT=agent-seat", output)
            self.assertIn("- loom start", output)

            project = load_project(repo_root)
            store = CoordinationStore(project.db_path, repo_root=project.repo_root)
            store.initialize()
            self.assertIsNone(store.agent_snapshot(agent_id=raw_terminal_identity).claim)
            adopted_claim = store.agent_snapshot(agent_id="agent-seat").claim
            assert adopted_claim is not None
            self.assertEqual(adopted_claim.agent_id, "agent-seat")
            self.assertEqual(adopted_claim.description, "Refactor auth flow")
            store.close()

    def test_whoami_unbind_clears_terminal_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            bind_stdout = io.StringIO()
            unbind_stdout = io.StringIO()
            whoami_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-default"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(bind_stdout):
                self.assertEqual(main(["whoami", "--bind", "agent-seat"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(unbind_stdout):
                self.assertEqual(main(["whoami", "--unbind"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(whoami_stdout):
                self.assertEqual(main(["whoami"]), 0)

            project = load_project(repo_root)
            self.assertEqual(project.terminal_aliases, {})
            self.assertIn("Terminal binding cleared:", unbind_stdout.getvalue())
            output = whoami_stdout.getvalue()
            self.assertIn("Agent: agent-default", output)
            self.assertIn("(source: project)", output)
            self.assertIn("Project default: agent-default", output)

    def test_whoami_set_updates_project_default_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            whoami_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(whoami_stdout):
                self.assertEqual(main(["whoami", "--set", "agent-b"]), 0)

            project = load_project(repo_root)
            self.assertEqual(project.default_agent, "agent-b")
            output = whoami_stdout.getvalue()
            self.assertIn("Default agent set: agent-b", output)
            self.assertIn("Agent: agent-b", output)
            self.assertIn("(source: project)", output)

    def test_claim_intent_and_status_surface_active_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            intent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                            "--reason",
                            "Need rate limiting hook",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            self.assertIn("Conflicts detected: none", claim_stdout.getvalue())
            self.assertIn("Next:", claim_stdout.getvalue())
            self.assertIn("loom status", claim_stdout.getvalue())
            self.assertIn("Conflicts detected:", intent_stdout.getvalue())
            self.assertIn("agent-b intent overlaps agent-a claim", intent_stdout.getvalue())
            self.assertIn("loom conflicts", intent_stdout.getvalue())
            self.assertIn("loom inbox", intent_stdout.getvalue())

            status_output = status_stdout.getvalue()
            self.assertIn("Active claims (1):", status_output)
            self.assertIn("Refactor auth flow", status_output)
            self.assertIn("Active intents (1):", status_output)
            self.assertIn("Touch auth middleware", status_output)
            self.assertIn("Recent context (0):", status_output)
            self.assertIn("Active conflicts (1):", status_output)
            self.assertIn("scope_overlap", status_output)

    def test_claim_and_intent_surface_explicit_leases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            claim_stdout = io.StringIO()
            intent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background dependency hygiene",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/deps",
                            "--lease-minutes",
                            "30",
                            "--json",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch dependency metadata",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/deps/lockfiles",
                            "--lease-minutes",
                            "45",
                            "--json",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            claim_payload = json.loads(claim_stdout.getvalue())
            intent_payload = json.loads(intent_stdout.getvalue())
            self.assertIsNotNone(claim_payload["claim"]["lease_expires_at"])
            self.assertIsNotNone(intent_payload["intent"]["lease_expires_at"])
            self.assertEqual(claim_payload["claim"]["lease_policy"], "renew")
            self.assertEqual(intent_payload["intent"]["lease_policy"], "renew")

            status_output = status_stdout.getvalue()
            self.assertIn("lease until:", status_output)
            self.assertIn("Background dependency hygiene", status_output)
            self.assertIn("Touch dependency metadata", status_output)

    def test_renew_refreshes_active_work_leases(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            renew_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(main(["whoami", "--bind", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background dependency hygiene",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/deps",
                            "--lease-minutes",
                            "30",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch dependency metadata",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/deps/lockfiles",
                            "--lease-minutes",
                            "30",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(renew_stdout):
                self.assertEqual(
                    main(["renew", "--agent", "agent-a", "--lease-minutes", "90", "--json"]),
                    0,
                )

            payload = json.loads(renew_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["lease_minutes"], 90)
            self.assertIsNotNone(payload["claim"])
            self.assertIsNotNone(payload["intent"])
            self.assertIsNotNone(payload["claim"]["lease_expires_at"])
            self.assertIsNotNone(payload["intent"]["lease_expires_at"])
            self.assertEqual(payload["next_steps"][0], "loom agent")

    def test_intent_surfaces_semantic_conflict_through_python_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.py").write_text(
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
                encoding="utf-8",
            )

            init_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            intent_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor session model",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session.py",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Update API handler return shape",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/api/handlers.py",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            self.assertIn("Conflicts detected: none", claim_stdout.getvalue())
            self.assertIn("semantically entangled", intent_stdout.getvalue())
            conflicts_output = conflicts_stdout.getvalue()
            self.assertIn("semantic_overlap", conflicts_output)
            self.assertIn("src/api/handlers.py -> src/auth/session.py", conflicts_output)
            self.assertIn("scope: src/api/handlers.py, src/auth/session.py", conflicts_output)

    def test_intent_surfaces_semantic_conflict_through_typescript_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.ts").write_text(
                "export function createSession(): string {\n"
                "    return 'session';\n"
                "}\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.ts").write_text(
                'import { createSession } from "../auth/session.js";\n\n'
                "export function handleRequest(): string {\n"
                "    return createSession();\n"
                "}\n",
                encoding="utf-8",
            )

            init_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            intent_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor session model",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session.ts",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Update API handler return shape",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/api/handlers.ts",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            self.assertIn("Conflicts detected: none", claim_stdout.getvalue())
            self.assertIn("semantically entangled", intent_stdout.getvalue())
            conflicts_output = conflicts_stdout.getvalue()
            self.assertIn("semantic_overlap", conflicts_output)
            self.assertIn("src/api/handlers.ts -> src/auth/session.ts", conflicts_output)
            self.assertIn("scope: src/api/handlers.ts, src/auth/session.ts", conflicts_output)

    def test_unrelated_python_scopes_do_not_trigger_semantic_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "billing").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "billing" / "invoice.py").write_text(
                "class Invoice:\n    pass\n",
                encoding="utf-8",
            )

            init_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            intent_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor session model",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session.py",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Update invoice formatting",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/billing/invoice.py",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            self.assertIn("Conflicts detected: none", claim_stdout.getvalue())
            self.assertIn("Conflicts detected: none", intent_stdout.getvalue())
            self.assertIn("Open conflicts (0):", conflicts_stdout.getvalue())
            self.assertIn("Next:", conflicts_stdout.getvalue())
            self.assertIn(
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                conflicts_stdout.getvalue(),
            )

    def test_claim_without_init_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["claim", "Refactor auth flow"])

            self.assertEqual(exit_code, 1)
            self.assertIn("Run `loom init` first", stderr.getvalue())
            self.assertIn("Next:", stderr.getvalue())
            self.assertIn("loom init --no-daemon", stderr.getvalue())

    def test_json_errors_are_written_to_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main(["claim", "Refactor auth flow", "--json"])

            self.assertEqual(exit_code, 1)
            self.assertEqual(stdout.getvalue(), "")
            payload = json.loads(stderr.getvalue())
            self.assertFalse(payload["ok"])
            self.assertIn("Run `loom init` first", payload["error"])
            self.assertEqual(payload["error_code"], "project_not_initialized")
            self.assertEqual(payload["next_steps"], ["loom init --no-daemon"])

    def test_claim_without_scope_infers_repo_area_from_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text("class UserSession: pass\n")
            (repo_root / "src" / "api" / "handlers.py").write_text("def handle(): pass\n")
            setup_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(main(["claim", "Refactor auth flow"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            claim_output = claim_stdout.getvalue()
            self.assertIn("Claim recorded:", claim_output)
            self.assertIn("Scope: src/auth", claim_output)
            self.assertIn("Scope source: inferred", claim_output)
            self.assertIn("matched auth", claim_output)
            self.assertIn("Active claims (1):", status_stdout.getvalue())
            self.assertIn("scope: src/auth", status_stdout.getvalue())

    def test_claim_json_includes_scope_resolution_when_inferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "docs" / "alpha").mkdir(parents=True)
            (repo_root / "docs" / "alpha" / "notes.md").write_text("# notes\n")
            setup_stdout = io.StringIO()
            claim_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(main(["claim", "Alpha docs truthfulness", "--json"]), 0)

            payload = json.loads(claim_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["scope_resolution"]["mode"], "inferred")
            self.assertTrue(payload["scope_resolution"]["used"])
            self.assertIn("docs/alpha", payload["scope_resolution"]["scopes"])
            self.assertIn("alpha", payload["scope_resolution"]["matched_tokens"])

    def test_claim_without_scope_can_stay_unscoped_when_no_confident_match_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text("class UserSession: pass\n")
            setup_stdout = io.StringIO()
            claim_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(main(["claim", "Investigate throughput ceilings"]), 0)

            output = claim_stdout.getvalue()
            self.assertIn("Scope: (none)", output)
            self.assertIn("Scope source: No confident repo path match", output)

    def test_claim_without_scope_stays_unscoped_when_matches_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "mobile").mkdir(parents=True)
            (repo_root / "docs" / "mobile").mkdir(parents=True)
            (repo_root / "src" / "mobile" / "app.dart").write_text("void main() {}\n")
            (repo_root / "docs" / "mobile" / "guide.md").write_text("# guide\n")
            setup_stdout = io.StringIO()
            claim_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(main(["claim", "Touch mobile"]), 0)

            output = claim_stdout.getvalue()
            self.assertIn("Scope: (none)", output)
            self.assertIn("Multiple plausible repo path matches were found", output)
            self.assertIn("docs/mobile", output)
            self.assertIn("src/mobile", output)

    def test_intent_without_scope_infers_repo_area_from_description(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "middleware.py").write_text("def gate(): pass\n")
            (repo_root / "src" / "api" / "handlers.py").write_text("def handle(): pass\n")
            setup_stdout = io.StringIO()
            intent_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(main(["intent", "Touch auth middleware", "--agent", "agent-a"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            output = intent_stdout.getvalue()
            self.assertIn("Intent recorded:", output)
            self.assertIn("Scope:", output)
            self.assertIn("src/auth/middleware", output)
            self.assertIn("Scope source: inferred", output)
            self.assertIn("matched auth, middleware", output)
            self.assertIn("Active intents (1):", status_stdout.getvalue())

    def test_intent_json_includes_scope_resolution_when_inferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "docs" / "public" / "brand").mkdir(parents=True)
            (repo_root / "docs" / "public" / "brand" / "README.md").write_text("# brand\n")
            setup_stdout = io.StringIO()
            intent_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(main(["intent", "Tighten brand docs", "--json"]), 0)

            payload = json.loads(intent_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["scope_resolution"]["mode"], "inferred")
            self.assertTrue(payload["scope_resolution"]["used"])
            self.assertIn("docs/public/brand", payload["scope_resolution"]["scopes"])
            self.assertIn("brand", payload["scope_resolution"]["matched_tokens"])

    def test_intent_without_scope_returns_helpful_error_when_inference_is_weak(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text("class UserSession: pass\n")
            setup_stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["intent", "Investigate throughput ceilings"])

            self.assertEqual(exit_code, 1)
            error_output = stderr.getvalue()
            self.assertIn("Intent scope could not be inferred confidently.", error_output)
            self.assertIn("Provide --scope", error_output)

    def test_intent_without_scope_returns_helpful_error_when_matches_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "mobile").mkdir(parents=True)
            (repo_root / "docs" / "mobile").mkdir(parents=True)
            (repo_root / "src" / "mobile" / "app.dart").write_text("void main() {}\n")
            (repo_root / "docs" / "mobile" / "guide.md").write_text("# guide\n")
            setup_stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["intent", "Touch mobile"])

            self.assertEqual(exit_code, 1)
            error_output = stderr.getvalue()
            self.assertIn("Intent scope could not be inferred confidently.", error_output)
            self.assertIn("Multiple plausible repo path matches were found", error_output)
            self.assertIn("docs/mobile", error_output)
            self.assertIn("src/mobile", error_output)

    def test_package_exposes_version(self) -> None:
        self.assertEqual(__version__, "0.1.0a0")

    def test_store_caches_dependency_graph_between_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()
            graph = DependencyGraph(files=(), imports_by_file={})

            with patch(
                "loom.local_store.store.DependencyGraph.build",
                return_value=graph,
            ) as build_graph_mock:
                store.record_claim(
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=("src/auth",),
                    source="test",
                )
                store.record_intent(
                    agent_id="agent-b",
                    description="Touch billing flow",
                    reason="Need pricing hook",
                    scope=("src/billing",),
                    source="test",
                )

            self.assertEqual(build_graph_mock.call_count, 1)

    def test_store_skips_dependency_fingerprint_recheck_within_interval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
                dependency_graph_recheck_seconds=60.0,
            )
            store.initialize()
            graph = DependencyGraph(files=(), imports_by_file={})

            with patch(
                "loom.local_store.store.source_fingerprint",
                return_value=(),
            ) as fingerprint_mock, patch(
                "loom.local_store.store.DependencyGraph.build",
                return_value=graph,
            ) as build_graph_mock:
                store.record_claim(
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=("src/auth",),
                    source="test",
                )
                store.record_intent(
                    agent_id="agent-b",
                    description="Touch billing flow",
                    reason="Need pricing hook",
                    scope=("src/billing",),
                    source="test",
                )

            self.assertEqual(fingerprint_mock.call_count, 1)
            self.assertEqual(build_graph_mock.call_count, 1)

    def test_store_invalidates_dependency_graph_cache_when_python_files_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()
            graph = DependencyGraph(files=(), imports_by_file={})

            with patch(
                "loom.local_store.store.DependencyGraph.build",
                return_value=graph,
            ) as build_graph_mock:
                store.record_claim(
                    agent_id="agent-a",
                    description="Refactor session model",
                    scope=("src/auth/session.py",),
                    source="test",
                )
                (repo_root / "src" / "api").mkdir(parents=True)
                (repo_root / "src" / "api" / "handlers.py").write_text(
                    "def handle_request() -> None:\n    return None\n",
                    encoding="utf-8",
                )
                store.record_intent(
                    agent_id="agent-b",
                    description="Update API handler",
                    reason="Need response wrapper",
                    scope=("src/api/handlers.py",),
                    source="test",
                )

            self.assertEqual(build_graph_mock.call_count, 2)

    def test_store_invalidates_dependency_graph_cache_when_script_files_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.ts").write_text(
                "export function createSession(): string {\n"
                "    return 'session';\n"
                "}\n",
                encoding="utf-8",
            )
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()
            graph = DependencyGraph(files=(), imports_by_file={})

            with patch(
                "loom.local_store.store.DependencyGraph.build",
                return_value=graph,
            ) as build_graph_mock:
                store.record_claim(
                    agent_id="agent-a",
                    description="Refactor session model",
                    scope=("src/auth/session.ts",),
                    source="test",
                )
                (repo_root / "src" / "api").mkdir(parents=True)
                (repo_root / "src" / "api" / "handlers.ts").write_text(
                    'import { createSession } from "../auth/session";\n',
                    encoding="utf-8",
                )
                store.record_intent(
                    agent_id="agent-b",
                    description="Update API handler",
                    reason="Need response wrapper",
                    scope=("src/api/handlers.ts",),
                    source="test",
                )

            self.assertEqual(build_graph_mock.call_count, 2)

    def test_daemon_server_initializes_one_shared_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()

            with working_directory(repo_root):
                project, _ = initialize_project()

            store_mock = Mock()
            with patch(
                "loom.daemon.runtime.CoordinationStore",
                return_value=store_mock,
            ) as store_cls, patch(
                "loom.daemon.runtime.UnixStreamServer.__init__",
                return_value=None,
            ):
                server = daemon_runtime._LoomUnixServer(project)

            try:
                store_cls.assert_called_once_with(
                    project.db_path,
                    repo_root=project.repo_root,
                    reuse_connections=True,
                )
                store_mock.initialize.assert_called_once()
                store_mock.close_thread_connection.assert_called_once()
                self.assertIs(server.store, store_mock)
            finally:
                if hasattr(server, "socket"):
                    server.server_close()
                if project.socket_path.exists():
                    project.socket_path.unlink()

    def test_store_reuses_thread_connection_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
                reuse_connections=True,
            )
            store.initialize()
            store.close_thread_connection()

            sqlite_connect = sqlite3.connect
            with patch(
                "loom.local_store.store.sqlite3.connect",
                side_effect=sqlite_connect,
            ) as connect_mock:
                store.latest_event_sequence()
                store.latest_event_sequence()

            self.assertEqual(connect_mock.call_count, 1)

            store.close_thread_connection()
            with patch(
                "loom.local_store.store.sqlite3.connect",
                side_effect=sqlite_connect,
            ) as connect_mock:
                store.latest_event_sequence()

            self.assertEqual(connect_mock.call_count, 1)
            store.close_thread_connection()

    def test_daemon_request_handler_finish_closes_thread_connection(self) -> None:
        handler = daemon_runtime._LoomRequestHandler.__new__(daemon_runtime._LoomRequestHandler)
        handler.server = Mock(store=Mock())
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()

        with patch("loom.daemon.runtime.StreamRequestHandler.finish", return_value=None):
            handler.finish()

        handler.server.store.close_thread_connection.assert_called_once()

    def test_store_backfills_event_links_for_legacy_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            db_path = repo_root / ".loom" / "coordination.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)

            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE events (
                        id TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        actor_id TEXT NOT NULL,
                        payload_json TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO events (id, type, timestamp, actor_id, payload_json)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "event_legacy_01",
                        "claim.recorded",
                        "2026-03-14T20:00:00Z",
                        "agent-a",
                        json.dumps({"claim_id": "claim_legacy_01"}),
                    ),
                )
                connection.commit()
            finally:
                connection.close()

            store = CoordinationStore(db_path, repo_root=repo_root)
            store.initialize()

            claim_events = store.list_events_for_references(
                references=(("claim", "claim_legacy_01"),),
                limit=None,
                ascending=True,
            )
            agent_events = store.list_events_for_references(
                references=(("agent", "agent-a"),),
                limit=None,
                ascending=True,
            )

            self.assertEqual(len(claim_events), 1)
            self.assertEqual(claim_events[0].type, "claim.recorded")
            self.assertEqual(len(agent_events), 1)
            self.assertEqual(agent_events[0].payload["claim_id"], "claim_legacy_01")

    def test_store_sql_helper_validation_is_explicit(self) -> None:
        self.assertEqual(store_module._validated_git_branch_table_name("claims"), "claims")
        self.assertEqual(store_module._validated_row_order(ascending=True), "ASC")
        self.assertEqual(store_module._validated_row_order(ascending=False), "DESC")
        self.assertEqual(
            store_module._reference_pair_placeholders(2),
            "(?, ?), (?, ?)",
        )
        self.assertEqual(
            store_module._flatten_reference_pairs((("claim", "c1"), ("intent", "i1"))),
            ["claim", "c1", "intent", "i1"],
        )

        with self.assertRaises(ValueError):
            store_module._validated_git_branch_table_name("claims; DROP TABLE claims")
        with self.assertRaises(ValueError):
            store_module._reference_pair_placeholders(0)

    def test_agent_snapshot_uses_indexed_event_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()
            claim, _ = store.record_claim(
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth",),
                source="test",
            )
            context, _ = store.record_context(
                agent_id="agent-a",
                topic="auth-plan",
                body="Stabilizing auth boundary.",
                scope=("src/auth",),
                source="test",
            )
            store.acknowledge_context(
                context_id=context.id,
                agent_id="agent-b",
                status="read",
            )

            with patch.object(store, "list_events", side_effect=AssertionError("full scan")):
                snapshot = store.agent_snapshot(
                    agent_id="agent-a",
                    context_limit=5,
                    event_limit=10,
                )

            self.assertEqual(snapshot.claim.id, claim.id)
            self.assertEqual(
                tuple(event.type for event in snapshot.events),
                ("claim.recorded", "context.published", "context.acknowledged"),
            )

    def test_list_agent_events_supports_created_after_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()

            with patch(
                "loom.local_store.store.utc_now",
                side_effect=(
                    "2026-03-14T20:00:00Z",
                    "2026-03-14T20:05:00Z",
                ),
            ):
                store.record_claim(
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=("src/auth",),
                    source="test",
                )
                context, _ = store.record_context(
                    agent_id="agent-a",
                    topic="auth-plan",
                    body="Stabilizing auth boundary.",
                    scope=("src/auth",),
                    source="test",
                )

            all_events = store.list_agent_events(
                agent_id="agent-a",
                limit=None,
                ascending=True,
            )
            filtered_events = store.list_agent_events(
                agent_id="agent-a",
                limit=None,
                created_after="2026-03-14T20:00:00Z",
                ascending=True,
            )

            self.assertEqual(
                tuple(event.type for event in all_events),
                ("claim.recorded", "context.published"),
            )
            self.assertEqual(
                tuple(event.type for event in filtered_events),
                ("context.published",),
            )
            self.assertEqual(filtered_events[0].payload["context_id"], context.id)

    def test_inbox_snapshot_uses_indexed_event_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            store = CoordinationStore(
                repo_root / ".loom" / "coordination.db",
                repo_root=repo_root,
            )
            store.initialize()
            store.record_claim(
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth",),
                source="test",
            )
            store.record_context(
                agent_id="agent-b",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth",),
                source="test",
            )

            with patch.object(store, "list_events", side_effect=AssertionError("full scan")):
                snapshot = store.inbox_snapshot(
                    agent_id="agent-a",
                    context_limit=5,
                    event_limit=10,
                )

            self.assertEqual(len(snapshot.pending_context), 1)
            self.assertTrue(any(event.type == "context.published" for event in snapshot.events))
            self.assertTrue(any(event.type == "conflict.detected" for event in snapshot.events))

    def test_status_before_any_work_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["status"]), 0)

            output = stdout.getvalue()
            self.assertIn("Self:", output)
            self.assertIn("Terminal:", output)
            self.assertIn("Active claims (0):", output)
            self.assertIn("Active intents (0):", output)
            self.assertIn("Recent context (0):", output)
            self.assertIn("Active conflicts (0):", output)
            self.assertIn("Nothing is active yet.", output)
            if terminal_identity_is_stable():
                self.assertIn("loom start --bind <agent-name>", output)
            else:
                self.assertIn("export LOOM_AGENT=<agent-name>", output)
            self.assertIn(
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                output,
            )

    def test_status_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            init_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(init_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["--json", "status"]), 0)

            payload = json.loads(status_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertIn("identity", payload)
            self.assertEqual(payload["status"]["claims"][0]["description"], "Refactor auth flow")
            self.assertEqual(payload["status"]["claims"][0]["agent_id"], "agent-a")
            self.assertIn("not running", payload["daemon"]["detail"])
            self.assertEqual(payload["next_steps"][0], "loom agent")
            self.assertEqual(payload["next_action"]["command"], "loom agent")
            self.assertEqual(payload["next_action"]["confidence"], "medium")

    def test_status_surfaces_expired_current_agent_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(main(["whoami", "--bind", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                            "--lease-minutes",
                            "30",
                        ]
                    ),
                    0,
                )

            with patch("loom.guidance.is_past_utc_timestamp", return_value=True), patch(
                "loom.cli.is_past_utc_timestamp",
                return_value=True,
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["--json", "status"]), 0)

            payload = json.loads(status_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["next_action"]["command"], "loom renew")
            self.assertEqual(payload["next_steps"][0], "loom renew")
            self.assertEqual(payload["next_action"]["kind"], "lease")

    def test_cli_json_preserves_unicode_claims_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()

            with working_directory(repo_root):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(main(["whoami", "--bind", "agent-a"]), 0)

                claim_stdout = io.StringIO()
                with contextlib.redirect_stdout(claim_stdout):
                    claim_exit = main(
                        [
                            "--json",
                            "claim",
                            "Fix über auth 設計",
                            "--scope",
                            "src/über/設計 notes",
                        ]
                    )
                self.assertEqual(claim_exit, 0)
                claim_output = claim_stdout.getvalue()
                self.assertIn("über auth 設計", claim_output)
                self.assertNotIn("\\u00fc", claim_output)
                claim_payload = json.loads(claim_output)
                self.assertEqual(claim_payload["claim"]["description"], "Fix über auth 設計")
                self.assertEqual(claim_payload["claim"]["scope"], ["src/über/設計 notes"])

                context_stdout = io.StringIO()
                with contextlib.redirect_stdout(context_stdout):
                    context_exit = main(
                        [
                            "--json",
                            "context",
                            "write",
                            "über-topic",
                            "Body <unsafe> café 設計",
                            "--scope",
                            "src/über/設計 notes",
                        ]
                    )
                self.assertEqual(context_exit, 0)
                context_output = context_stdout.getvalue()
                self.assertIn("über-topic", context_output)
                self.assertIn("café 設計", context_output)
                self.assertNotIn("\\u8a2d", context_output)
                context_payload = json.loads(context_output)
                self.assertEqual(context_payload["context"]["topic"], "über-topic")
                self.assertEqual(
                    context_payload["context"]["body"],
                    "Body <unsafe> café 設計",
                )

    def test_status_marks_resolved_self_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(main(["whoami", "--bind", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            output = status_stdout.getvalue()
            self.assertIn("Self: agent-a (source: terminal)", output)
            self.assertIn("Terminal binding: agent-a", output)
            self.assertIn("- agent-a (you): Refactor auth flow", output)
            self.assertIn("- agent-b: Touch auth middleware", output)
            self.assertIn("Next:", output)
            self.assertIn("loom conflicts", output)
            self.assertIn("loom inbox", output)

    def test_agents_lists_known_agents_with_identity_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agents_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface",
                            "Refresh token required.",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "idle-note",
                            "Just a note.",
                            "--agent",
                            "agent-c",
                            "--scope",
                            "docs",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(agents_stdout):
                self.assertEqual(main(["agents"]), 0)

            output = agents_stdout.getvalue()
            self.assertIn("Active agents (2):", output)
            self.assertIn("Self: agent-a (source: project)", output)
            self.assertIn("Live active (2):", output)
            self.assertIn("- agent-a (you)", output)
            self.assertIn("claim: Refactor auth flow", output)
            self.assertIn("- agent-b", output)
            self.assertIn("intent: Touch auth middleware", output)
            self.assertIn("Idle history hidden (1).", output)
            self.assertNotIn("Idle (1):", output)
            self.assertIn("Next:", output)
            self.assertIn("loom agent", output)
            self.assertIn("loom inbox", output)

    def test_agents_all_separates_idle_agents_in_compact_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agents_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "idle-note",
                            "Just a note.",
                            "--agent",
                            "idle-agent",
                            "--scope",
                            "docs",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(agents_stdout):
                self.assertEqual(main(["agents", "--all"]), 0)

            output = agents_stdout.getvalue()
            # Active agent shows full claim detail
            self.assertIn("- agent-a (you)", output)
            self.assertIn("claim: Refactor auth flow", output)
            # Idle agent in compact section
            self.assertIn("Idle (1):", output)
            self.assertIn("idle-agent", output)
            # Idle section uses compact format — no "claim: none" or "intent: none"
            idle_section = output[output.index("Idle (1):"):]
            self.assertNotIn("claim: none", idle_section)
            self.assertNotIn("intent: none", idle_section)

    def test_agents_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agents_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(agents_stdout):
                self.assertEqual(main(["agents", "--json"]), 0)

            payload = json.loads(agents_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["identity"]["id"], "agent-a")
            self.assertEqual(len(payload["agents"]), 1)
            self.assertEqual(payload["agents"][0]["agent_id"], "agent-a")
            self.assertEqual(
                payload["agents"][0]["claim"]["description"],
                "Refactor auth flow",
            )
            self.assertEqual(payload["next_steps"][0], "loom agent")

    def test_agents_json_surfaces_dead_pid_cleanup_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            agents_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Legacy pid claim",
                            "--agent",
                            "dev@host:pid-101",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with patch(
                "loom.cli.terminal_identity_process_is_alive",
                side_effect=lambda agent_id: False if agent_id == "dev@host:pid-101" else None,
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(agents_stdout):
                    self.assertEqual(main(["agents", "--json"]), 0)

            payload = json.loads(agents_stdout.getvalue())
            self.assertEqual(payload["dead_session_agents"], ["dev@host:pid-101"])
            self.assertEqual(payload["next_steps"][0], "loom clean")

    def test_agents_uses_daemon_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agents_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            project = load_project(repo_root)
            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            client = Mock()
            client.project = project
            client.daemon_status.return_value = daemon_status
            client.read_agents.return_value = (
                AgentPresenceRecord(
                    agent_id="agent-a",
                    source="project",
                    created_at="2026-03-14T20:00:00Z",
                    last_seen_at="2099-03-14T20:02:00Z",
                    claim=ClaimRecord(
                        id="claim_agent_01",
                        agent_id="agent-a",
                        description="Refactor auth flow",
                        scope=("src/auth",),
                        status="active",
                        created_at="2026-03-14T20:00:00Z",
                    ),
                    intent=None,
                ),
            )

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(agents_stdout):
                    self.assertEqual(main(["agents"]), 0)

            client.read_agents.assert_called_once_with(limit=20)
            output = agents_stdout.getvalue()
            self.assertIn("Active agents (1):", output)
            self.assertIn("Live active (1):", output)
            self.assertIn("Daemon: running on daemon.sock", output)
            self.assertIn("Self: agent-a (source: project)", output)
            self.assertIn("claim: Refactor auth flow", output)
            self.assertIn("Next:", output)
            self.assertIn("loom status", output)

    def test_records_capture_git_branch_when_head_points_to_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            git_dir = repo_root / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text(
                "ref: refs/heads/feature/auth-coordination\n",
                encoding="utf-8",
            )
            setup_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            intent_stdout = io.StringIO()
            context_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                            "--json",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(intent_stdout):
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/middleware",
                            "--json",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(context_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                            "--json",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            claim_payload = json.loads(claim_stdout.getvalue())
            intent_payload = json.loads(intent_stdout.getvalue())
            context_payload = json.loads(context_stdout.getvalue())

            self.assertEqual(
                claim_payload["claim"]["git_branch"],
                "feature/auth-coordination",
            )
            self.assertEqual(
                intent_payload["intent"]["git_branch"],
                "feature/auth-coordination",
            )
            self.assertEqual(
                context_payload["context"]["git_branch"],
                "feature/auth-coordination",
            )

            status_output = status_stdout.getvalue()
            self.assertIn("branch: feature/auth-coordination", status_output)

    def test_context_read_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            read_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(read_stdout):
                self.assertEqual(main(["context", "read", "--json", "--limit", "5"]), 0)

            payload = json.loads(read_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["context"][0]["topic"], "auth-interface-change")
            self.assertEqual(payload["context"][0]["agent_id"], "agent-a")
            self.assertEqual(payload["context"][0]["scope"], ["src/auth"])

    def test_second_claim_supersedes_first_claim_for_same_agent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor billing flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/billing",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["status"]), 0)

            output = stdout.getvalue()
            self.assertIn("Refactor billing flow", output)
            self.assertNotIn("Refactor auth flow [", output)

    def test_claim_and_status_use_daemon_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            claim_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            claim = ClaimRecord(
                id="claim_daemon_01",
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth",),
                status="active",
                created_at="2026-03-14T20:00:00Z",
            )
            intent = IntentRecord(
                id="intent_daemon_01",
                agent_id="agent-b",
                description="Touch auth middleware",
                reason="Need rate limiting hook",
                scope=("src/auth/middleware",),
                status="active",
                created_at="2026-03-14T20:01:00Z",
                related_claim_id=None,
            )
            context = ContextRecord(
                id="context_daemon_01",
                agent_id="agent-a",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth",),
                created_at="2026-03-14T20:02:00Z",
                related_claim_id="claim_daemon_01",
                related_intent_id=None,
            )
            conflict = ConflictRecord(
                id="conflict_daemon_01",
                kind="scope_overlap",
                severity="warning",
                summary="agent-a claim overlaps agent-b intent on src/auth/middleware",
                object_type_a="claim",
                object_id_a="claim_daemon_01",
                object_type_b="intent",
                object_id_b="intent_daemon_01",
                scope=("src/auth/middleware",),
                created_at="2026-03-14T20:03:00Z",
            )
            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )

            claim_client = Mock()
            claim_client.create_claim.return_value = (claim, (conflict,))
            claim_client.daemon_status.return_value = daemon_status

            with patch("loom.cli._build_client", return_value=claim_client):
                with working_directory(repo_root), contextlib.redirect_stdout(claim_stdout):
                    self.assertEqual(
                        main(
                            [
                                "claim",
                                "Refactor auth flow",
                                "--agent",
                                "agent-a",
                                "--scope",
                                "src/auth",
                            ]
                        ),
                        0,
                    )

            status_client = Mock()
            status_client.project = type("Project", (), {"repo_root": repo_root})()
            status_client.read_status.return_value = StatusSnapshot(
                claims=(claim,),
                intents=(intent,),
                context=(context,),
                conflicts=(conflict,),
            )
            status_client.daemon_status.return_value = daemon_status

            with patch("loom.cli._build_client", return_value=status_client):
                with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status"]), 0)

            claim_client.create_claim.assert_called_once()
            status_client.read_status.assert_called_once()
            self.assertIn("Claim recorded: claim_daemon_01", claim_stdout.getvalue())
            self.assertIn("agent-a claim overlaps agent-b intent", claim_stdout.getvalue())
            self.assertIn("Daemon: running on daemon.sock", status_stdout.getvalue())
            self.assertIn("Active claims (1):", status_stdout.getvalue())
            self.assertIn("Recent context (1):", status_stdout.getvalue())

    def test_agent_view_surfaces_active_work_context_attention_and_activity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agent_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-plan",
                            "I am stabilizing the auth boundary.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            own_context_id = next(
                entry.id
                for entry in store.read_context(agent_id="agent-a", limit=5)
                if entry.topic == "auth-plan"
            )

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "ack",
                            own_context_id,
                            "--agent",
                            "agent-b",
                            "--status",
                            "read",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                self.assertEqual(
                    main(
                        [
                            "agent",
                            "--agent",
                            "agent-a",
                            "--context-limit",
                            "5",
                            "--event-limit",
                            "10",
                        ]
                    ),
                    0,
                )

            output = agent_stdout.getvalue()
            self.assertIn("Agent view for agent-a", output)
            self.assertIn("Active claim:", output)
            self.assertIn("Identity: agent-a (source: flag)", output)
            self.assertIn("Refactor auth flow", output)
            self.assertIn("Active intent:", output)
            self.assertIn("Touch auth middleware", output)
            self.assertIn("Active work started:", output)
            self.assertIn("Before you continue: 1 pending context, 2 active conflict(s)", output)
            self.assertIn("Do this first: conflict", output)
            self.assertIn("React now:", output)
            self.assertIn("next: loom context ack", output)
            self.assertIn('--status adapted --note "<what changed>"', output)
            self.assertIn('next: loom resolve conflict_', output)
            self.assertIn("Relevant changes since active work started", output)
            self.assertIn("Published context (1):", output)
            self.assertIn("auth-plan by agent-a", output)
            self.assertIn("acknowledgments: agent-b=read", output)
            self.assertIn("Relevant context (1):", output)
            self.assertIn("auth-interface-change by agent-b", output)
            self.assertIn("status for agent-a: pending", output)
            self.assertIn("reaction for agent-a: react now", output)
            self.assertIn("Active conflicts (2):", output)
            self.assertIn("contextual_dependency", output)
            self.assertIn("Recent activity", output)
            self.assertIn("context.acknowledged", output)
            self.assertIn("context.published", output)

    def test_agent_view_surfaces_worktree_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agent_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/billing/invoice.py",)):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a"]), 0)

            output = agent_stdout.getvalue()
            self.assertIn("Attention: 1 worktree drift path(s)", output)
            self.assertIn("Working tree:", output)
            self.assertIn("outside scope: src/billing/invoice.py", output)
            self.assertIn("suggested widened scope: src/auth, src/billing", output)
            self.assertIn("Scope adoption:", output)
            self.assertIn(
                '- loom intent "Describe the edit you\'re about to make" --scope src/auth --scope src/billing',
                output,
            )
            self.assertIn(
                'loom intent "Describe the edit you\'re about to make" --scope src/auth --scope src/billing',
                output,
            )

    def test_agent_view_suggests_finish_when_active_work_is_settled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agent_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a"]), 0)

            output = agent_stdout.getvalue()
            self.assertIn("Looks settled:", output)
            self.assertIn("next: loom finish", output)
            self.assertIn("Next:\n- loom finish", output)

    def test_agent_json_includes_structured_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agent_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a", "--json"]), 0)

            payload = json.loads(agent_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["next_steps"][0], "loom finish")
            self.assertEqual(payload["next_action"]["command"], "loom finish")
            self.assertEqual(payload["next_action"]["confidence"], "high")

    def test_agent_view_uses_daemon_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agent_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            claim = ClaimRecord(
                id="claim_agent_01",
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth",),
                status="active",
                created_at="2026-03-14T20:00:00Z",
            )
            published_context = ContextRecord(
                id="context_agent_01",
                agent_id="agent-a",
                topic="auth-plan",
                body="Stabilizing auth boundary.",
                scope=("src/auth",),
                created_at="2026-03-14T20:02:00Z",
                related_claim_id="claim_agent_01",
                related_intent_id=None,
                acknowledgments=(
                    ContextAckRecord(
                        id="ctxack_agent_01",
                        context_id="context_agent_01",
                        agent_id="agent-b",
                        status="read",
                        acknowledged_at="2026-03-14T20:03:00Z",
                    ),
                ),
            )
            event = EventRecord(
                sequence=1,
                id="event_agent_01",
                type="claim.recorded",
                timestamp="2026-03-14T20:00:00Z",
                actor_id="agent-a",
                payload={"claim_id": "claim_agent_01"},
            )
            snapshot = AgentSnapshot(
                agent_id="agent-a",
                claim=claim,
                intent=None,
                published_context=(published_context,),
                incoming_context=(),
                conflicts=(),
                events=(event,),
            )
            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )

            client = Mock()
            client.project = load_project(repo_root)
            client.read_agent_snapshot.return_value = snapshot
            client.daemon_status.return_value = daemon_status

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(agent_stdout):
                    self.assertEqual(main(["agent", "--agent", "agent-a"]), 0)

            client.read_agent_snapshot.assert_called_once()
            output = agent_stdout.getvalue()
            self.assertIn("Agent view for agent-a", output)
            self.assertIn("Daemon: running on daemon.sock", output)
            self.assertIn("Identity: agent-a (source: flag)", output)
            self.assertIn("Attention: clear", output)
            self.assertIn("Published context (1):", output)
            self.assertIn("auth-plan by agent-a", output)
            self.assertIn("Recent activity (1):", output)
            self.assertIn("Looks settled:", output)
            self.assertIn("Next:", output)
            self.assertIn("loom finish", output)

    def test_inbox_surfaces_pending_context_conflicts_and_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            inbox_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            context_id = next(
                entry.id
                for entry in store.read_context(agent_id="agent-b", limit=5)
                if entry.topic == "auth-interface-change"
            )
            conflicts = store.list_conflicts()

            with working_directory(repo_root), contextlib.redirect_stdout(inbox_stdout):
                self.assertEqual(main(["inbox", "--agent", "agent-a"]), 0)

            output = inbox_stdout.getvalue()
            self.assertIn("Inbox for agent-a", output)
            self.assertIn("Identity: agent-a (source: flag)", output)
            self.assertIn("Attention: 1 pending context, 2 active conflicts", output)
            self.assertIn("Pending context (1):", output)
            self.assertIn("auth-interface-change by agent-b", output)
            self.assertIn(
                f"next: loom context ack {context_id} --agent agent-a --status read",
                output,
            )
            self.assertIn('--status adapted --note "<what changed>"', output)
            self.assertIn("Active conflicts (2):", output)
            self.assertIn("contextual_dependency", output)
            for conflict in conflicts:
                self.assertIn(
                    f'next: loom resolve {conflict.id} --agent agent-a --note "<resolution>"',
                    output,
                )
            self.assertIn("Recent triggers", output)
            self.assertIn("context.published", output)
            self.assertIn("conflict.detected", output)

    def test_inbox_json_prefers_resolving_top_conflict_in_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            inbox_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(inbox_stdout):
                self.assertEqual(main(["inbox", "--agent", "agent-a", "--json"]), 0)

            payload = json.loads(inbox_stdout.getvalue())
            self.assertEqual(payload["attention"]["active_conflicts"], 1)
            self.assertTrue(payload["next_action"]["command"].startswith("loom resolve conflict_"))
            self.assertEqual(payload["next_action"]["kind"], "conflict")
            self.assertEqual(payload["next_action"]["confidence"], "high")

    def test_inbox_clear_state_suggests_starting_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            inbox_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command("--agent", "agent-a")), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(inbox_stdout):
                self.assertEqual(main(["inbox", "--agent", "agent-a"]), 0)

            output = inbox_stdout.getvalue()
            self.assertIn("Attention: clear", output)
            self.assertIn("Inbox is clear.", output)
            self.assertIn(
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
                output,
            )

    def test_inbox_uses_daemon_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            inbox_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            context = ContextRecord(
                id="context_inbox_01",
                agent_id="agent-b",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth",),
                created_at="2026-03-14T20:01:00Z",
                related_claim_id=None,
                related_intent_id=None,
            )
            conflict = ConflictRecord(
                id="conflict_inbox_01",
                kind="contextual_dependency",
                severity="warning",
                summary="agent-a claim may depend on agent-b context auth-interface-change on src/auth",
                object_type_a="claim",
                object_id_a="claim_agent_01",
                object_type_b="context",
                object_id_b="context_inbox_01",
                scope=("src/auth",),
                created_at="2026-03-14T20:02:00Z",
            )
            event = EventRecord(
                sequence=1,
                id="event_inbox_01",
                type="context.published",
                timestamp="2026-03-14T20:01:00Z",
                actor_id="agent-b",
                payload={"context_id": "context_inbox_01"},
            )
            snapshot = InboxSnapshot(
                agent_id="agent-a",
                pending_context=(context,),
                conflicts=(conflict,),
                events=(event,),
            )
            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )

            client = Mock()
            client.read_inbox_snapshot.return_value = snapshot
            client.daemon_status.return_value = daemon_status

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(inbox_stdout):
                    self.assertEqual(main(["inbox", "--agent", "agent-a"]), 0)

            client.read_inbox_snapshot.assert_called_once()
            output = inbox_stdout.getvalue()
            self.assertIn("Inbox for agent-a", output)
            self.assertIn("Daemon: running on daemon.sock", output)
            self.assertIn("Identity: agent-a (source: flag)", output)
            self.assertIn("Attention: 1 pending context, 1 active conflicts", output)
            self.assertIn("Pending context (1):", output)
            self.assertIn("Recent triggers (1):", output)

    def test_inbox_follow_streams_updates_in_direct_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()

            def publish_context_note() -> None:
                time.sleep(0.05)
                store.record_context(
                    agent_id="agent-b",
                    topic="auth-interface-change",
                    body="UserSession now requires refresh_token.",
                    scope=["src/auth"],
                    source="test",
                )

            worker = threading.Thread(target=publish_context_note)
            worker.start()
            try:
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "inbox",
                                "--agent",
                                "agent-a",
                                "--follow",
                                "--poll-interval",
                                "0.01",
                                "--max-follow-updates",
                                "1",
                            ]
                        ),
                        0,
                    )
            finally:
                worker.join(timeout=1)

            output = follow_stdout.getvalue()
            self.assertIn("Inbox for agent-a", output)
            self.assertIn("Identity: agent-a (source: flag)", output)
            self.assertIn("Pending context (0):", output)
            self.assertIn("Inbox update after context.published", output)
            self.assertIn("auth-interface-change by agent-b", output)
            self.assertIn("Attention: 1 pending context", output)
            self.assertIn("Recent triggers", output)

    def test_inbox_follow_uses_daemon_stream_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            streamed_event = EventRecord(
                sequence=9,
                id="event_inbox_stream_01",
                type="context.published",
                timestamp="2026-03-14T21:35:00Z",
                actor_id="agent-b",
                payload={"context_id": "context_inbox_stream_01"},
            )
            initial_snapshot = InboxSnapshot(
                agent_id="agent-a",
                pending_context=(),
                conflicts=(),
                events=(),
            )
            updated_context = ContextRecord(
                id="context_inbox_stream_01",
                agent_id="agent-b",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth",),
                created_at="2026-03-14T21:35:00Z",
                related_claim_id=None,
                related_intent_id=None,
            )
            updated_snapshot = InboxSnapshot(
                agent_id="agent-a",
                pending_context=(updated_context,),
                conflicts=(),
                events=(streamed_event,),
            )

            client = Mock()
            client.read_inbox_snapshot.side_effect = (initial_snapshot, updated_snapshot)
            client.follow_events.return_value = iter((streamed_event,))
            client.daemon_status.return_value = daemon_status
            client.store = Mock()
            client.store.latest_event_sequence.return_value = 0

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "inbox",
                                "--agent",
                                "agent-a",
                                "--follow",
                                "--max-follow-updates",
                                "1",
                            ]
                        ),
                        0,
                    )

            client.follow_events.assert_called_once()
            self.assertEqual(client.read_inbox_snapshot.call_count, 2)
            output = follow_stdout.getvalue()
            self.assertIn("Inbox for agent-a", output)
            self.assertIn("Daemon: running on daemon.sock", output)
            self.assertIn("Identity: agent-a (source: flag)", output)
            self.assertIn("Inbox update after context.published [event_inbox_stream_01]", output)
            self.assertIn("auth-interface-change by agent-b", output)
            self.assertIn("Attention: 1 pending context", output)

    def test_inbox_follow_falls_back_to_polling_when_daemon_stream_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            streamed_event = EventRecord(
                sequence=9,
                id="event_inbox_stream_02",
                type="context.published",
                timestamp="2026-03-14T21:36:00Z",
                actor_id="agent-b",
                payload={"context_id": "context_inbox_stream_02"},
            )
            initial_snapshot = InboxSnapshot(
                agent_id="agent-a",
                pending_context=(),
                conflicts=(),
                events=(),
            )
            updated_context = ContextRecord(
                id="context_inbox_stream_02",
                agent_id="agent-b",
                topic="auth-interface-change",
                body="Refresh token required for session reuse.",
                scope=("src/auth",),
                created_at="2026-03-14T21:36:00Z",
                related_claim_id=None,
                related_intent_id=None,
            )
            updated_snapshot = InboxSnapshot(
                agent_id="agent-a",
                pending_context=(updated_context,),
                conflicts=(),
                events=(streamed_event,),
            )

            client = Mock()
            client.read_inbox_snapshot.side_effect = (initial_snapshot, updated_snapshot)
            client.follow_events.side_effect = RuntimeError("stream_closed")
            client.read_events.return_value = (streamed_event,)
            client.daemon_status.return_value = daemon_status
            client.store = Mock()
            client.store.latest_event_sequence.return_value = 0

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "inbox",
                                "--agent",
                                "agent-a",
                                "--follow",
                                "--poll-interval",
                                "0.01",
                                "--max-follow-updates",
                                "1",
                            ]
                        ),
                        0,
                    )

            client.follow_events.assert_called_once()
            client.read_events.assert_called_once_with(
                limit=None,
                event_type=None,
                after_sequence=0,
                ascending=True,
            )
            self.assertEqual(client.read_inbox_snapshot.call_count, 2)
            output = follow_stdout.getvalue()
            self.assertIn("Inbox for agent-a", output)
            self.assertIn("Inbox update after context.published [event_inbox_stream_02]", output)
            self.assertIn("Refresh token required for session reuse.", output)

    def test_context_write_read_and_status_show_recent_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            write_stdout = io.StringIO()
            read_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(write_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                            "--scope",
                            "src/api",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(read_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "read",
                            "--scope",
                            "src/api",
                            "--limit",
                            "5",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            write_output = write_stdout.getvalue()
            self.assertIn("Context recorded:", write_output)
            self.assertIn("Topic: auth-interface-change", write_output)
            self.assertIn("Related claim:", write_output)
            self.assertIn("Related intent:", write_output)
            self.assertIn("Context dependencies surfaced: none", write_output)
            self.assertIn("Next:", write_output)
            self.assertIn("loom inbox", write_output)
            self.assertIn("loom status", write_output)

            read_output = read_stdout.getvalue()
            self.assertIn("Context results (1):", read_output)
            self.assertIn("auth-interface-change by agent-a", read_output)
            self.assertIn("UserSession now requires refresh_token.", read_output)
            self.assertIn("scope: src/auth, src/api", read_output)

            status_output = status_stdout.getvalue()
            self.assertIn("Recent context (1):", status_output)
            self.assertIn("auth-interface-change by agent-a", status_output)

    def test_status_surfaces_worktree_drift_and_guides_next_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/billing/invoice.py",)):
                with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status"]), 0)

            output = status_stdout.getvalue()
            self.assertIn("Working tree:", output)
            self.assertIn("changed paths: 1", output)
            self.assertIn("current claim/intent scope: src/auth", output)
            self.assertIn("outside scope: src/billing/invoice.py", output)
            self.assertIn("suggested widened scope: src/auth, src/billing", output)
            self.assertIn(
                'loom intent "Describe the edit you\'re about to make" --scope src/auth --scope src/billing',
                output,
            )

    def test_context_ack_surfaces_read_state_in_read_status_and_log(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            ack_stdout = io.StringIO()
            read_stdout = io.StringIO()
            status_stdout = io.StringIO()
            log_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            context_id = store.read_context(limit=1)[0].id

            with working_directory(repo_root), contextlib.redirect_stdout(ack_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "ack",
                            context_id,
                            "--agent",
                            "agent-b",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(read_stdout):
                self.assertEqual(main(["context", "read", "--limit", "5"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(log_stdout):
                self.assertEqual(
                    main(["log", "--type", "context.acknowledged", "--limit", "5"]),
                    0,
                )

            ack_output = ack_stdout.getvalue()
            self.assertIn(f"Context acknowledged: {context_id}", ack_output)
            self.assertIn("Agent: agent-b", ack_output)
            self.assertIn("Status: read", ack_output)

            self.assertIn("acknowledgments: agent-b=read", read_stdout.getvalue())
            self.assertIn("acknowledgments: agent-b=read", status_stdout.getvalue())

            log_output = log_stdout.getvalue()
            self.assertIn("Recent events (1):", log_output)
            self.assertIn("context.acknowledged", log_output)
            self.assertIn(f"context_id={context_id}", log_output)
            self.assertIn("status=read", log_output)

    def test_context_ack_upgrades_to_adapted_without_downgrading(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            adapted_stdout = io.StringIO()
            read_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            context_id = store.read_context(limit=1)[0].id

            with working_directory(repo_root), contextlib.redirect_stdout(adapted_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "ack",
                            context_id,
                            "--agent",
                            "agent-b",
                            "--status",
                            "adapted",
                            "--note",
                            "Shifted work away from auth middleware.",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "ack",
                            context_id,
                            "--agent",
                            "agent-b",
                            "--status",
                            "read",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(read_stdout):
                self.assertEqual(main(["context", "read", "--limit", "5"]), 0)

            adapted_output = adapted_stdout.getvalue()
            self.assertIn("Status: adapted", adapted_output)
            self.assertIn("Note: Shifted work away from auth middleware.", adapted_output)
            self.assertIn("Next:", adapted_output)
            self.assertIn("loom inbox", adapted_output)
            self.assertIn("loom status", adapted_output)

            read_output = read_stdout.getvalue()
            self.assertIn("acknowledgments: agent-b=adapted", read_output)
            self.assertIn("Next:", read_output)
            self.assertIn("loom inbox", read_output)

    def test_context_ack_uses_daemon_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            ack_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            ack = ContextAckRecord(
                id="ctxack_01",
                context_id="context_01",
                agent_id="agent-b",
                status="adapted",
                acknowledged_at="2026-03-14T22:00:00Z",
                note="Shifted work away from auth middleware.",
            )

            client = Mock()
            client.acknowledge_context.return_value = ack
            client.daemon_status.return_value = daemon_status

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(ack_stdout):
                    self.assertEqual(
                        main(
                            [
                                "context",
                                "ack",
                                "context_01",
                                "--agent",
                                "agent-b",
                                "--status",
                                "adapted",
                                "--note",
                                "Shifted work away from auth middleware.",
                            ]
                        ),
                        0,
                    )

            client.acknowledge_context.assert_called_once()
            output = ack_stdout.getvalue()
            self.assertIn("Context acknowledged: context_01", output)
            self.assertIn("Status: adapted", output)
            self.assertIn("Note: Shifted work away from auth middleware.", output)
            self.assertIn("Next:", output)
            self.assertIn("loom status", output)

    def test_context_ack_missing_context_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["context", "ack", "context_missing", "--agent", "agent-b"])

            self.assertEqual(exit_code, 1)
            self.assertIn("Context not found: context_missing.", stderr.getvalue())

    def test_context_read_filters_non_matching_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "billing-change",
                            "Invoices now include payment terms.",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/billing",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "read",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            output = stdout.getvalue()
            self.assertIn("Context results (0):", output)
            self.assertIn("- none", output)

    def test_context_write_surfaces_contextual_dependency_for_overlapping_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            write_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(write_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            write_output = write_stdout.getvalue()
            self.assertIn("Context dependencies surfaced:", write_output)
            self.assertIn(
                "agent-b claim may depend on agent-a context auth-interface-change on src/auth",
                write_output,
            )

            conflicts_output = conflicts_stdout.getvalue()
            self.assertIn("contextual_dependency", conflicts_output)
            self.assertIn("objects: claim=", conflicts_output)
            self.assertIn("context=", conflicts_output)

    def test_context_write_surfaces_contextual_dependency_through_python_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.py").write_text(
                "class UserSession:\n    pass\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.py").write_text(
                "from auth.session import UserSession\n\n"
                "def handle_request() -> UserSession:\n"
                "    return UserSession()\n",
                encoding="utf-8",
            )

            setup_stdout = io.StringIO()
            write_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Update API handler return shape",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/api/handlers.py",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(write_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session.py",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            write_output = write_stdout.getvalue()
            self.assertIn("Context dependencies surfaced:", write_output)
            self.assertIn(
                "agent-b claim may depend on agent-a context auth-interface-change via "
                "src/api/handlers.py -> src/auth/session.py",
                write_output,
            )

            conflicts_output = conflicts_stdout.getvalue()
            self.assertIn("contextual_dependency", conflicts_output)
            self.assertIn("src/api/handlers.py, src/auth/session.py", conflicts_output)

    def test_context_write_surfaces_contextual_dependency_through_javascript_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "src" / "auth").mkdir(parents=True)
            (repo_root / "src" / "api").mkdir(parents=True)
            (repo_root / "src" / "auth" / "session.js").write_text(
                "function createSession() {\n"
                "    return 'session';\n"
                "}\n\n"
                "module.exports = { createSession };\n",
                encoding="utf-8",
            )
            (repo_root / "src" / "api" / "handlers.js").write_text(
                'const { createSession } = require("../auth/session");\n\n'
                "function handleRequest() {\n"
                "    return createSession();\n"
                "}\n\n"
                "module.exports = { handleRequest };\n",
                encoding="utf-8",
            )

            setup_stdout = io.StringIO()
            write_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Update API handler return shape",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/api/handlers.js",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(write_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "createSession now requires refreshToken.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/session.js",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            write_output = write_stdout.getvalue()
            self.assertIn("Context dependencies surfaced:", write_output)
            self.assertIn(
                "agent-b claim may depend on agent-a context auth-interface-change via "
                "src/api/handlers.js -> src/auth/session.js",
                write_output,
            )

            conflicts_output = conflicts_stdout.getvalue()
            self.assertIn("contextual_dependency", conflicts_output)
            self.assertIn("src/api/handlers.js, src/auth/session.js", conflicts_output)

    def test_log_shows_recent_events_and_type_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            log_stdout = io.StringIO()
            filtered_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(log_stdout):
                self.assertEqual(main(["log", "--limit", "10"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(filtered_stdout):
                self.assertEqual(
                    main(
                        [
                            "log",
                            "--limit",
                            "10",
                            "--type",
                            "context.published",
                        ]
                    ),
                    0,
                )

            output = log_stdout.getvalue()
            self.assertIn("Recent events (5):", output)
            self.assertIn("claim.recorded", output)
            self.assertIn("intent.declared", output)
            self.assertIn("conflict.detected", output)
            self.assertIn("context.published", output)
            self.assertIn("payload: context_id=", output)
            self.assertIn("Next:", output)
            self.assertIn("loom status", output)

            filtered_output = filtered_stdout.getvalue()
            self.assertIn("Recent events (1):", filtered_output)
            self.assertIn("context.published", filtered_output)
            self.assertNotIn("claim.recorded", filtered_output)

    def test_log_follow_streams_new_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()

            def emit_event() -> None:
                time.sleep(0.05)
                store.record_claim(
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=["src/auth"],
                    source="test",
                )

            worker = threading.Thread(target=emit_event)
            worker.start()
            try:
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "log",
                                "--follow",
                                "--limit",
                                "1",
                                "--poll-interval",
                                "0.01",
                                "--max-follow-events",
                                "1",
                            ]
                        ),
                        0,
                    )
            finally:
                worker.join(timeout=1)

            output = follow_stdout.getvalue()
            self.assertIn("Recent events (0):", output)
            self.assertIn("claim.recorded", output)
            self.assertIn("payload: claim_id=", output)

    def test_log_follow_supports_json_stream_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()

            def create_claim_event() -> None:
                time.sleep(0.05)
                store.record_claim(
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=("src/auth",),
                    source="test",
                )

            worker = threading.Thread(target=create_claim_event)
            worker.start()
            try:
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "log",
                                "--json",
                                "--follow",
                                "--limit",
                                "1",
                                "--max-follow-events",
                                "1",
                            ]
                        ),
                        0,
                    )
            finally:
                worker.join()

            lines = [line for line in follow_stdout.getvalue().splitlines() if line.strip()]
            self.assertEqual(len(lines), 2)
            snapshot = json.loads(lines[0])
            event = json.loads(lines[1])
            self.assertTrue(snapshot["ok"])
            self.assertEqual(snapshot["stream"], "events")
            self.assertEqual(snapshot["phase"], "snapshot")
            self.assertEqual(snapshot["events"], [])
            self.assertTrue(event["ok"])
            self.assertEqual(event["stream"], "events")
            self.assertEqual(event["phase"], "event")
            self.assertEqual(event["event"]["type"], "claim.recorded")

    def test_log_follow_uses_daemon_stream_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            streamed_event = EventRecord(
                sequence=7,
                id="event_stream_01",
                type="context.published",
                timestamp="2026-03-14T21:30:00Z",
                actor_id="agent-a",
                payload={"context_id": "context_stream_01"},
            )

            client = Mock()
            client.read_events.return_value = ()
            client.follow_events.return_value = iter((streamed_event,))
            client.daemon_status.return_value = daemon_status

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "log",
                                "--follow",
                                "--limit",
                                "1",
                                "--max-follow-events",
                                "1",
                            ]
                        ),
                        0,
                    )

            client.follow_events.assert_called_once()
            output = follow_stdout.getvalue()
            self.assertIn("Recent events (0):", output)
            self.assertIn("context.published", output)
            self.assertIn("payload: context_id=context_stream_01", output)

    def test_log_follow_falls_back_to_polling_when_daemon_stream_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            streamed_event = EventRecord(
                sequence=7,
                id="event_stream_01b",
                type="context.published",
                timestamp="2026-03-14T21:30:30Z",
                actor_id="agent-a",
                payload={"context_id": "context_stream_01b"},
            )

            client = Mock()
            client.read_events.side_effect = ((), (streamed_event,))
            client.follow_events.side_effect = RuntimeError("stream_closed")
            client.daemon_status.return_value = daemon_status

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "log",
                                "--follow",
                                "--limit",
                                "1",
                                "--poll-interval",
                                "0.01",
                                "--max-follow-events",
                                "1",
                            ]
                        ),
                        0,
                    )

            client.follow_events.assert_called_once()
            self.assertEqual(client.read_events.call_count, 2)
            self.assertEqual(client.read_events.call_args_list[1].kwargs["after_sequence"], 0)
            self.assertTrue(client.read_events.call_args_list[1].kwargs["ascending"])
            output = follow_stdout.getvalue()
            self.assertIn("Recent events (0):", output)
            self.assertIn("context.published", output)
            self.assertIn("payload: context_id=context_stream_01b", output)

    def test_log_follow_returns_130_on_keyboard_interrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()
            follow_stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            client = Mock()
            client.read_events.return_value = ()
            client.follow_events.side_effect = KeyboardInterrupt()
            client.daemon_status.return_value = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout), contextlib.redirect_stderr(follow_stderr):
                    self.assertEqual(
                        main(
                            [
                                "log",
                                "--follow",
                                "--limit",
                                "1",
                            ]
                        ),
                        130,
                    )

            self.assertIn("Recent events (0):", follow_stdout.getvalue())
            self.assertTrue(follow_stderr.getvalue().endswith("\n"))

    def test_timeline_for_claim_shows_linked_context_conflicts_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            timeline_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            claim_id = next(
                event.payload["claim_id"]
                for event in store.list_events(limit=None, ascending=True)
                if event.type == "claim.recorded"
            )
            context_id = store.read_context(limit=1)[0].id

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "ack",
                            context_id,
                            "--agent",
                            "agent-b",
                            "--status",
                            "adapted",
                            "--note",
                            "Shifted work away from auth middleware.",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(timeline_stdout):
                self.assertEqual(main(["timeline", claim_id, "--limit", "10"]), 0)

            output = timeline_stdout.getvalue()
            self.assertIn(f"Timeline for claim {claim_id}", output)
            self.assertIn("Description: Refactor auth flow", output)
            self.assertIn("Related conflicts (1):", output)
            self.assertIn("scope_overlap", output)
            self.assertIn("Linked context (1):", output)
            self.assertIn("auth-interface-change by agent-a", output)
            self.assertIn("acknowledgments: agent-b=adapted", output)
            self.assertIn("Events (4):", output)
            self.assertIn("claim.recorded", output)
            self.assertIn("context.published", output)
            self.assertIn("context.acknowledged", output)
            self.assertIn("Next:", output)
            self.assertIn("loom conflicts", output)

    def test_timeline_uses_indexed_event_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            timeline_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            claim_id = next(
                event.payload["claim_id"]
                for event in store.list_events_for_references(
                    references=(("agent", "agent-a"),),
                    limit=None,
                    ascending=True,
                )
                if event.type == "claim.recorded"
            )

            client = Mock()
            client.store = store
            client.read_events.side_effect = AssertionError("full scan")

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(timeline_stdout):
                    self.assertEqual(main(["timeline", claim_id, "--limit", "10"]), 0)

            output = timeline_stdout.getvalue()
            self.assertIn(f"Timeline for claim {claim_id}", output)
            self.assertIn("claim.recorded", output)

    def test_timeline_for_conflict_shows_resolution_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            timeline_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            conflict_id = store.list_conflicts()[0].id

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    main(
                        [
                            "resolve",
                            conflict_id,
                            "--agent",
                            "agent-b",
                            "--note",
                            "Waiting on agent-a before proceeding.",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(timeline_stdout):
                self.assertEqual(main(["timeline", conflict_id, "--limit", "10"]), 0)

            output = timeline_stdout.getvalue()
            self.assertIn(f"Timeline for conflict {conflict_id}", output)
            self.assertIn("Kind: scope_overlap", output)
            self.assertIn("Status: resolved", output)
            self.assertIn("Resolved by: agent-b", output)
            self.assertIn("Resolution note: Waiting on agent-a before proceeding.", output)
            self.assertIn("Events (2):", output)
            self.assertIn("conflict.detected", output)
            self.assertIn("conflict.resolved", output)
            self.assertIn("Next:", output)
            self.assertIn("loom conflicts", output)
            self.assertIn("loom inbox", output)

    def test_timeline_missing_object_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["timeline", "claim_missing"])

            self.assertEqual(exit_code, 1)
            self.assertIn("Object not found: claim_missing.", stderr.getvalue())
            self.assertIn("loom status", stderr.getvalue())

    def test_context_read_follow_streams_new_context_in_direct_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()

            def publish_context_note() -> None:
                time.sleep(0.05)
                store.record_context(
                    agent_id="agent-a",
                    topic="auth-interface-change",
                    body="UserSession now requires refresh_token.",
                    scope=["src/auth"],
                    source="test",
                )

            worker = threading.Thread(target=publish_context_note)
            worker.start()
            try:
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "context",
                                "read",
                                "--follow",
                                "--scope",
                                "src/auth",
                                "--poll-interval",
                                "0.01",
                                "--max-follow-entries",
                                "1",
                            ]
                        ),
                        0,
                    )
            finally:
                worker.join(timeout=1)

            output = follow_stdout.getvalue()
            self.assertIn("Context results (0):", output)
            self.assertIn("auth-interface-change by agent-a", output)
            self.assertIn("UserSession now requires refresh_token.", output)

    def test_context_read_follow_uses_daemon_stream_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            streamed_event = EventRecord(
                sequence=8,
                id="event_stream_02",
                type="context.published",
                timestamp="2026-03-14T21:31:00Z",
                actor_id="agent-a",
                payload={"context_id": "context_stream_02"},
            )
            streamed_context = ContextRecord(
                id="context_stream_02",
                agent_id="agent-a",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth", "src/api"),
                created_at="2026-03-14T21:31:00Z",
                related_claim_id="claim_01",
                related_intent_id="intent_01",
            )

            client = Mock()
            client.read_context_entries.return_value = ()
            client.follow_events.return_value = iter((streamed_event,))
            client.get_context_entry.return_value = streamed_context
            client.daemon_status.return_value = daemon_status
            client.store = Mock()
            client.store.latest_event_sequence.return_value = 0

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "context",
                                "read",
                                "--follow",
                                "--scope",
                                "src/auth",
                                "--max-follow-entries",
                                "1",
                            ]
                        ),
                        0,
                    )

            client.follow_events.assert_called_once()
            client.get_context_entry.assert_called_once()
            output = follow_stdout.getvalue()
            self.assertIn("Context results (0):", output)
            self.assertIn("auth-interface-change by agent-a", output)
            self.assertIn("related claim: claim_01", output)
            self.assertIn("related intent: intent_01", output)

    def test_context_read_follow_falls_back_to_polling_when_daemon_stream_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            follow_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            daemon_status = DaemonStatus(
                running=True,
                detail="running on daemon.sock",
            )
            streamed_event = EventRecord(
                sequence=8,
                id="event_stream_02b",
                type="context.published",
                timestamp="2026-03-14T21:31:30Z",
                actor_id="agent-a",
                payload={"context_id": "context_stream_02b"},
            )
            streamed_context = ContextRecord(
                id="context_stream_02b",
                agent_id="agent-a",
                topic="auth-interface-change",
                body="UserSession now requires refresh_token.",
                scope=("src/auth", "src/api"),
                created_at="2026-03-14T21:31:30Z",
                related_claim_id="claim_01",
                related_intent_id="intent_01",
            )

            client = Mock()
            client.read_context_entries.return_value = ()
            client.follow_events.side_effect = RuntimeError("stream_closed")
            client.read_events.return_value = (streamed_event,)
            client.get_context_entry.return_value = streamed_context
            client.daemon_status.return_value = daemon_status
            client.store = Mock()
            client.store.latest_event_sequence.return_value = 0

            with patch("loom.cli._build_client", return_value=client):
                with working_directory(repo_root), contextlib.redirect_stdout(follow_stdout):
                    self.assertEqual(
                        main(
                            [
                                "context",
                                "read",
                                "--follow",
                                "--scope",
                                "src/auth",
                                "--poll-interval",
                                "0.01",
                                "--max-follow-entries",
                                "1",
                            ]
                        ),
                        0,
                    )

            client.follow_events.assert_called_once()
            client.read_events.assert_called_once_with(
                limit=None,
                event_type="context.published",
                after_sequence=0,
                ascending=True,
            )
            client.get_context_entry.assert_called_once_with(context_id="context_stream_02b")
            output = follow_stdout.getvalue()
            self.assertIn("Context results (0):", output)
            self.assertIn("auth-interface-change by agent-a", output)
            self.assertIn("related claim: claim_01", output)

    def test_conflicts_command_and_unclaim_clear_claim_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()
            unclaim_stdout = io.StringIO()
            status_stdout = io.StringIO()
            log_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(unclaim_stdout):
                self.assertEqual(main(["unclaim", "--agent", "agent-a"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(log_stdout):
                self.assertEqual(main(["log", "--type", "claim.released", "--limit", "5"]), 0)

            conflicts_output = conflicts_stdout.getvalue()
            self.assertIn("Open conflicts (1):", conflicts_output)
            self.assertIn("scope_overlap", conflicts_output)
            self.assertIn("objects: claim=", conflicts_output)

            unclaim_output = unclaim_stdout.getvalue()
            self.assertIn("Claim released:", unclaim_output)
            self.assertIn("Agent: agent-a", unclaim_output)
            self.assertIn("Next:", unclaim_output)
            self.assertIn("loom status", unclaim_output)

            status_output = status_stdout.getvalue()
            self.assertIn("Active claims (1):", status_output)
            self.assertIn("Touch auth middleware", status_output)
            self.assertNotIn("Refactor auth flow [", status_output)
            self.assertIn("Active conflicts (0):", status_output)

            log_output = log_stdout.getvalue()
            self.assertIn("Recent events (1):", log_output)
            self.assertIn("claim.released", log_output)
            self.assertIn("payload: claim_id=", log_output)
            self.assertIn("Next:", log_output)
            self.assertIn("loom inbox", log_output)

    def test_superseding_claim_deactivates_conflicts_for_old_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Alpha docs and release truthfulness",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "README.md",
                            "--scope",
                            "docs/alpha",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            self.assertEqual(store.list_conflicts(), ())

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            status_output = status_stdout.getvalue()
            self.assertIn("Active claims (1):", status_output)
            self.assertIn("Active intents (1):", status_output)
            self.assertIn("Active conflicts (0):", status_output)
            self.assertIn("Alpha docs and release truthfulness", status_output)

    def test_initialize_deactivates_conflicts_for_superseded_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            conflict = store.list_conflicts()[0]
            claim_id = (
                conflict.object_id_a
                if conflict.object_type_a == "claim"
                else conflict.object_id_b
            )

            connection = sqlite3.connect(repo_root / ".loom" / "coordination.db")
            try:
                connection.execute(
                    """
                    UPDATE claims
                    SET status = 'superseded', superseded_at = '2026-03-15T00:00:00Z'
                    WHERE id = ?
                    """,
                    (claim_id,),
                )
                connection.commit()
            finally:
                connection.close()

            repaired_store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            repaired_store.initialize()
            self.assertEqual(repaired_store.list_conflicts(), ())

    def test_resolve_conflict_moves_it_to_history_and_emits_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            resolve_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()
            history_stdout = io.StringIO()
            log_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )

            store = CoordinationStore(repo_root / ".loom" / "coordination.db")
            store.initialize()
            conflict_id = store.list_conflicts()[0].id

            with working_directory(repo_root), contextlib.redirect_stdout(resolve_stdout):
                self.assertEqual(
                    main(
                        [
                            "resolve",
                            conflict_id,
                            "--agent",
                            "agent-b",
                            "--note",
                            "Waiting on agent-a before proceeding.",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(history_stdout):
                self.assertEqual(main(["conflicts", "--all"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(log_stdout):
                self.assertEqual(
                    main(["log", "--type", "conflict.resolved", "--limit", "5"]),
                    0,
                )

            resolve_output = resolve_stdout.getvalue()
            self.assertIn(f"Conflict resolved: {conflict_id}", resolve_output)
            self.assertIn("Resolved by: agent-b", resolve_output)
            self.assertIn("Note: Waiting on agent-a before proceeding.", resolve_output)
            self.assertIn("Next:", resolve_output)
            self.assertIn("loom conflicts", resolve_output)
            self.assertIn("loom status", resolve_output)

            self.assertIn("Open conflicts (0):", conflicts_stdout.getvalue())

            history_output = history_stdout.getvalue()
            self.assertIn("Conflicts (1):", history_output)
            self.assertIn("resolved warning scope_overlap", history_output)
            self.assertIn("resolved by: agent-b", history_output)
            self.assertIn("note: Waiting on agent-a before proceeding.", history_output)

            log_output = log_stdout.getvalue()
            self.assertIn("Recent events (1):", log_output)
            self.assertIn("conflict.resolved", log_output)
            self.assertIn(f"payload: conflict_id={conflict_id}", log_output)

    def test_resolve_missing_conflict_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["resolve", "conflict_missing", "--agent", "agent-a"])

            self.assertEqual(exit_code, 1)
            self.assertIn("Conflict not found: conflict_missing.", stderr.getvalue())
            self.assertIn("loom conflicts", stderr.getvalue())

    def test_unclaim_without_active_claim_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["unclaim", "--agent", "agent-a"])

            self.assertEqual(exit_code, 1)
            self.assertIn("No active claim for agent-a.", stderr.getvalue())
            self.assertIn("loom status", stderr.getvalue())

    def test_finish_releases_active_intent_and_claim_and_records_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            finish_stdout = io.StringIO()
            status_stdout = io.StringIO()
            log_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth/middleware",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(finish_stdout):
                self.assertEqual(
                    main(
                        [
                            "finish",
                            "--agent",
                            "agent-a",
                            "--note",
                            "Paused here; auth middleware work resumes tomorrow.",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(log_stdout):
                self.assertEqual(main(["log", "--limit", "10"]), 0)

            finish_output = finish_stdout.getvalue()
            self.assertIn("Session finished for agent-a", finish_output)
            self.assertIn("Context recorded: context_", finish_output)
            self.assertIn("Intent released: intent_", finish_output)
            self.assertIn("Claim released: claim_", finish_output)
            self.assertIn("Idle agent history: pruned", finish_output)
            self.assertIn("loom start", finish_output)

            status_output = status_stdout.getvalue()
            self.assertIn("Active claims (0):", status_output)
            self.assertIn("Active intents (0):", status_output)
            self.assertIn("Recent context (1):", status_output)
            self.assertIn("session-handoff by agent-a", status_output)

            log_output = log_stdout.getvalue()
            self.assertIn("intent.released", log_output)
            self.assertIn("claim.released", log_output)
            self.assertIn("context.published", log_output)

            with working_directory(repo_root):
                project = load_project(repo_root)
                store = CoordinationStore(project.db_path, repo_root=project.repo_root)
                store.initialize()
                self.assertEqual(store.list_agents(limit=None), ())

    def test_finish_can_keep_idle_agent_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            finish_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Refactor auth flow",
                            "--agent",
                            "agent-a",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(finish_stdout):
                self.assertEqual(main(["finish", "--agent", "agent-a", "--keep-idle"]), 0)

            self.assertIn("Idle agent history: kept (--keep-idle)", finish_stdout.getvalue())

            with working_directory(repo_root):
                project = load_project(repo_root)
                store = CoordinationStore(project.db_path, repo_root=project.repo_root)
                store.initialize()
                self.assertEqual(
                    tuple(presence.agent_id for presence in store.list_agents(limit=None)),
                    ("agent-a",),
                )

    def test_start_surfaces_recent_self_handoff_when_no_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "finish",
                            "--agent",
                            "agent-a",
                            "--note",
                            "Paused after auth pass. Resume with auth cleanup.",
                        ]
                    ),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "active")
            self.assertIn("recent handoff", payload["summary"])
            self.assertIsNotNone(payload["handoff"])
            self.assertEqual(payload["handoff"]["topic"], "session-handoff")
            self.assertEqual(payload["handoff"]["scope"], ["src/auth"])
            self.assertEqual(
                payload["next_steps"],
                [
                    'loom claim "Describe the work you\'re starting" --scope src/auth',
                    "loom status",
                    "loom agent",
                ],
            )

    def test_start_ready_empty_repo_uses_shared_followup_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(start_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "ready")
            self.assertEqual(
                payload["next_steps"],
                [
                    'loom claim "Describe the work you\'re starting" --scope path/to/area',
                    "loom status",
                    "loom agent",
                ],
            )
            self.assertEqual(
                payload["next_action"]["command"],
                'loom claim "Describe the work you\'re starting" --scope path/to/area',
            )

    def test_finish_without_active_work_or_note_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stderr = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with working_directory(repo_root), contextlib.redirect_stderr(stderr):
                exit_code = main(["finish", "--agent", "agent-a"])

            self.assertEqual(exit_code, 1)
            self.assertIn("No active claim or intent for agent-a.", stderr.getvalue())
            self.assertIn("loom finish --note", stderr.getvalue())

    def test_resume_advances_checkpoint_and_surfaces_new_relevant_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            first_resume_stdout = io.StringIO()
            second_resume_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(first_resume_stdout):
                self.assertEqual(main(["resume", "--agent", "agent-a"]), 0)

            first_project = load_project(repo_root)
            first_checkpoint = first_project.resume_sequences.get("agent-a")
            self.assertIsNotNone(first_checkpoint)
            self.assertGreater(first_checkpoint, 0)

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/billing/invoice.py",)):
                with working_directory(repo_root), contextlib.redirect_stdout(second_resume_stdout):
                    self.assertEqual(main(["resume", "--agent", "agent-a"]), 0)

            second_project = load_project(repo_root)
            second_checkpoint = second_project.resume_sequences.get("agent-a")
            self.assertIsNotNone(second_checkpoint)
            assert first_checkpoint is not None
            assert second_checkpoint is not None
            self.assertGreater(second_checkpoint, first_checkpoint)

            first_output = first_resume_stdout.getvalue()
            self.assertIn("Loom resume for agent-a", first_output)
            self.assertIn("From checkpoint: 0", first_output)
            self.assertIn("Checkpoint advanced to:", first_output)
            self.assertIn("Active work started:", first_output)
            self.assertIn("Before you continue: 0 pending context, 0 active conflict(s)", first_output)
            self.assertIn("Looks settled:", first_output)
            self.assertIn("next: loom finish", first_output)
            self.assertIn("Relevant changes since active work started (0):", first_output)
            self.assertIn("Relevant changes since last resume (1):", first_output)
            self.assertIn("Next:\n- loom finish", first_output)
            self.assertIn("claim.recorded", first_output)

            second_output = second_resume_stdout.getvalue()
            self.assertIn(f"From checkpoint: {first_checkpoint}", second_output)
            self.assertIn("Active work started:", second_output)
            self.assertIn("Before you continue: 1 pending context, 1 active conflict(s)", second_output)
            self.assertIn("Do this first: conflict", second_output)
            self.assertIn("React now:", second_output)
            self.assertIn("- context auth-interface-change", second_output)
            self.assertIn("next: loom context ack", second_output)
            self.assertIn('next: loom resolve conflict_', second_output)
            self.assertIn("Working tree:", second_output)
            self.assertIn("outside scope: src/billing/invoice.py", second_output)
            self.assertIn("suggested widened scope: src/auth, src/billing", second_output)
            self.assertIn("Scope adoption:", second_output)
            self.assertIn(
                '- loom intent "Describe the edit you\'re about to make" --scope src/auth --scope src/billing',
                second_output,
            )
            self.assertIn("Relevant changes since active work started", second_output)
            self.assertIn("Pending context (1):", second_output)
            self.assertIn("auth-interface-change by agent-b", second_output)
            self.assertIn("Summary: 2 relevant event(s), 1 pending context, 1 active conflict(s)", second_output)
            self.assertIn("Next:\n- loom resolve conflict_", second_output)
            self.assertIn("context.published", second_output)
            self.assertIn("conflict.detected", second_output)
            self.assertIn("payload: context_id=context_", second_output)
            self.assertIn("contextual_dependency", second_output)
            self.assertIn("loom inbox", second_output)

    def test_resume_surfaces_recent_self_handoff_when_no_active_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            resume_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "finish",
                            "--agent",
                            "agent-a",
                            "--note",
                            "Paused after auth pass. Resume with auth cleanup.",
                        ]
                    ),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=()):
                with working_directory(repo_root), contextlib.redirect_stdout(resume_stdout):
                    self.assertEqual(main(["resume", "--agent", "agent-a"]), 0)

            output = resume_stdout.getvalue()
            self.assertIn("Recent handoff:", output)
            self.assertIn("session-handoff by agent-a", output)
            self.assertIn("Paused after auth pass. Resume with auth cleanup.", output)
            self.assertIn('next: loom claim "Describe the work you\'re starting" --scope src/auth', output)
            self.assertIn("Next:\n- loom claim \"Describe the work you're starting\" --scope src/auth", output)

    def test_resume_json_supports_no_checkpoint_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            resume_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with patch("loom.guidance.current_worktree_paths", return_value=("src/billing/invoice.py",)):
                with working_directory(repo_root), contextlib.redirect_stdout(resume_stdout):
                    self.assertEqual(
                        main(["resume", "--agent", "agent-a", "--json", "--no-checkpoint"]),
                        0,
                    )

            payload = json.loads(resume_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["identity"]["id"], "agent-a")
            self.assertEqual(payload["after_sequence"], 0)
            self.assertGreater(payload["latest_relevant_sequence"], 0)
            self.assertEqual(
                payload["resume_after_sequence"],
                payload["latest_relevant_sequence"],
            )
            self.assertFalse(payload["checkpoint_updated"])
            self.assertEqual(payload["active_work"]["started_at"], payload["agent"]["claim"]["created_at"])
            self.assertEqual(payload["active_work"]["events"], [])
            self.assertEqual(payload["active_work"]["pending_context"], [])
            self.assertEqual(payload["active_work"]["react_now_context"], [])
            self.assertEqual(payload["active_work"]["review_soon_context"], [])
            self.assertEqual(payload["active_work"]["conflicts"], [])
            self.assertIsNone(payload["active_work"]["priority"])
            self.assertEqual(payload["worktree"]["drift_paths"], ["src/billing/invoice.py"])
            self.assertEqual(payload["worktree"]["suggested_scope"], ["src/auth", "src/billing"])
            self.assertEqual(len(payload["events"]), 1)
            self.assertEqual(payload["events"][0]["type"], "claim.recorded")
            self.assertEqual(
                payload["next_steps"][0],
                'loom intent "Describe the edit you\'re about to make" --scope src/auth --scope src/billing',
            )
            self.assertEqual(
                payload["next_action"]["command"],
                'loom intent "Describe the edit you\'re about to make" --scope src/auth --scope src/billing',
            )
            self.assertEqual(payload["next_action"]["confidence"], "high")

            project = load_project(repo_root)
            self.assertEqual(project.resume_sequences, {})

    def test_conflicts_json_includes_structured_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            conflicts_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--agent",
                            "agent-b",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(conflicts_stdout):
                self.assertEqual(main(["conflicts", "--json"]), 0)

            payload = json.loads(conflicts_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(len(payload["conflicts"]), 1)
            self.assertTrue(payload["next_action"]["command"].startswith("loom resolve conflict_"))
            self.assertEqual(payload["next_action"]["kind"], "conflict")
            self.assertEqual(payload["next_action"]["confidence"], "high")

    def test_agents_separate_stale_active_records_from_live_active_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            agents_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            connection = sqlite3.connect(repo_root / ".loom" / "coordination.db")
            try:
                connection.execute(
                    """
                    UPDATE agents
                    SET last_seen_at = '2026-03-01T00:00:00Z'
                    WHERE id = 'agent-a'
                    """
                )
                connection.commit()
            finally:
                connection.close()

            with working_directory(repo_root), contextlib.redirect_stdout(agents_stdout):
                self.assertEqual(main(["agents"]), 0)

            output = agents_stdout.getvalue()
            self.assertIn("Active agents (1):", output)
            self.assertIn("Stale active (1):", output)
            self.assertIn("loom finish", output)
            self.assertIn("loom unclaim", output)
            self.assertIn("claim: Refactor auth flow", output)

    def test_agents_treat_expired_leases_as_stale_active_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            agents_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background dependency hygiene",
                            "--scope",
                            "src/deps",
                            "--lease-minutes",
                            "30",
                        ]
                    ),
                    0,
                )

            with patch("loom.cli.is_past_utc_timestamp", return_value=True):
                with working_directory(repo_root), contextlib.redirect_stdout(agents_stdout):
                    self.assertEqual(main(["agents"]), 0)

            output = agents_stdout.getvalue()
            self.assertIn("Active agents (1):", output)
            self.assertIn("Stale active (1):", output)
            self.assertIn("expired leases", output)
            self.assertIn("loom renew", output)

    def test_clean_closes_dead_pid_work_and_prunes_idle_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            clean_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Legacy pid claim",
                            "--agent",
                            "dev@host:pid-101",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Legacy pid intent",
                            "--agent",
                            "dev@host:pid-101",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "idle-note",
                            "Historical note only.",
                            "--agent",
                            "agent-idle",
                            "--scope",
                            "docs",
                        ]
                    ),
                    0,
                )

            with patch(
                "loom.cli.terminal_identity_process_is_alive",
                side_effect=lambda agent_id: False if agent_id == "dev@host:pid-101" else None,
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(clean_stdout):
                    self.assertEqual(main(["clean"]), 0)

            output = clean_stdout.getvalue()
            self.assertIn("Cleanup complete.", output)
            self.assertIn("Closed dead pid sessions: 1", output)
            self.assertIn("Released claims: 1", output)
            self.assertIn("Released intents: 1", output)
            self.assertIn("Pruned idle agents: 2", output)

            with working_directory(repo_root):
                project = load_project(repo_root)
                store = CoordinationStore(project.db_path, repo_root=project.repo_root)
                store.initialize()
                self.assertEqual(store.list_agents(limit=None), ())
                self.assertEqual(store.status().claims, ())
                self.assertEqual(store.status().intents, ())

    def test_clean_can_keep_idle_agent_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            clean_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "idle-note",
                            "Historical note only.",
                            "--agent",
                            "agent-idle",
                            "--scope",
                            "docs",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(clean_stdout):
                self.assertEqual(main(["clean", "--keep-idle"]), 0)

            output = clean_stdout.getvalue()
            self.assertIn("Board already clean.", output)
            self.assertIn("Pruned idle agents: skipped (--keep-idle)", output)

            with working_directory(repo_root):
                project = load_project(repo_root)
                store = CoordinationStore(project.db_path, repo_root=project.repo_root)
                store.initialize()
                self.assertEqual(
                    tuple(presence.agent_id for presence in store.list_agents(limit=None)),
                    ("agent-idle",),
                )

    def test_status_marks_stale_active_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            connection = sqlite3.connect(repo_root / ".loom" / "coordination.db")
            try:
                connection.execute(
                    """
                    UPDATE agents
                    SET last_seen_at = '2026-03-01T00:00:00Z'
                    WHERE id = 'agent-a'
                    """
                )
                connection.commit()
            finally:
                connection.close()

            with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                self.assertEqual(main(["status"]), 0)

            output = status_stdout.getvalue()
            self.assertIn("Stale active records:", output)
            self.assertIn("went quiet for more than", output)
            self.assertIn("agent-a (you) (stale): Refactor auth flow", output)

    def test_status_json_prefers_clean_when_dead_pid_sessions_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Legacy pid claim",
                            "--agent",
                            "dev@host:pid-101",
                            "--scope",
                            "src/auth",
                        ]
                    ),
                    0,
                )

            with patch(
                "loom.cli.terminal_identity_process_is_alive",
                side_effect=lambda agent_id: False if agent_id == "dev@host:pid-101" else None,
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status", "--json"]), 0)

            payload = json.loads(status_stdout.getvalue())
            self.assertEqual(payload["dead_session_agents"], ["dev@host:pid-101"])
            self.assertEqual(payload["next_action"]["command"], "loom clean")
            self.assertEqual(payload["next_action"]["kind"], "cleanup")
            self.assertEqual(
                payload["next_steps"],
                ["loom clean", "loom status", "loom agents --all"],
            )

    def test_status_marks_expired_leased_active_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            status_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(
                        [
                            "claim",
                            "Background dependency hygiene",
                            "--scope",
                            "src/deps",
                            "--lease-minutes",
                            "30",
                        ]
                    ),
                    0,
                )

            with patch("loom.cli.is_past_utc_timestamp", return_value=True):
                with working_directory(repo_root), contextlib.redirect_stdout(status_stdout):
                    self.assertEqual(main(["status"]), 0)

            output = status_stdout.getvalue()
            self.assertIn("Stale active records:", output)
            self.assertIn("expired active-work leases", output)
            self.assertIn("loom finish", output)

    def test_daemon_status_command_reports_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with patch(
                "loom.cli.get_daemon_status",
                return_value=DaemonStatus(
                    running=True,
                    detail="running on daemon.sock",
                    pid=4242,
                    started_at="2026-03-14T20:00:00Z",
                    log_path=repo_root / ".loom" / "daemon.log",
                ),
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["daemon", "status"]), 0)

            output = stdout.getvalue()
            self.assertIn("running on daemon.sock", output)
            self.assertIn("PID: 4242", output)
            self.assertIn("Started: 2026-03-14T20:00:00Z", output)
            self.assertIn("Log:", output)

    def test_protocol_command_supports_json_output(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["protocol", "--json"]), 0)

        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["protocol"]["name"], "loom.local")
        self.assertEqual(payload["protocol"]["version"], 1)
        self.assertIn("protocol.describe", payload["protocol"]["operations"])
        self.assertIn("context.ack", payload["protocol"]["operations"])
        self.assertIn("operation_schemas", payload["protocol"])
        self.assertIn("object_schemas", payload["protocol"])
        self.assertIn(
            "claim.create",
            payload["protocol"]["operation_schemas"],
        )
        self.assertIn(
            "request",
            payload["protocol"]["operation_schemas"]["claim.create"],
        )

    def test_protocol_command_prints_human_readable_summary(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            self.assertEqual(main(["protocol"]), 0)

        output = stdout.getvalue()
        self.assertIn("Protocol: loom.local v1", output)
        self.assertIn("Transport:", output)
        self.assertIn("Operations (", output)
        self.assertIn("protocol.describe", output)
        self.assertIn("Schema detail:", output)

    def test_daemon_ping_reports_protocol_when_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with patch(
                "loom.cli.get_daemon_status",
                return_value=DaemonStatus(
                    running=True,
                    detail="running on daemon.sock",
                ),
            ), patch(
                "loom.cli.describe_daemon_protocol",
                return_value={
                    "name": "loom.local",
                    "version": 1,
                    "operations": ["ping", "protocol.describe"],
                },
            ) as describe_protocol_mock:
                with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                    self.assertEqual(main(["daemon", "ping"]), 0)

            output = stdout.getvalue()
            describe_protocol_mock.assert_called_once()
            self.assertIn("running on daemon.sock", output)
            self.assertIn("Protocol: loom.local v1", output)

    def test_daemon_start_and_stop_commands_report_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            start_stdout = io.StringIO()
            stop_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(init_command()), 0)

            with patch(
                "loom.cli.start_daemon",
                return_value=DaemonControlResult(
                    detail="Daemon started.",
                    pid=5252,
                    log_path=repo_root / ".loom" / "daemon.log",
                ),
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(start_stdout):
                    self.assertEqual(main(["daemon", "start"]), 0)

            with patch(
                "loom.cli.stop_daemon",
                return_value=DaemonControlResult(
                    detail="Daemon stopped.",
                    pid=5252,
                    log_path=repo_root / ".loom" / "daemon.log",
                ),
            ):
                with working_directory(repo_root), contextlib.redirect_stdout(stop_stdout):
                    self.assertEqual(main(["daemon", "stop"]), 0)

            self.assertIn("Daemon started.", start_stdout.getvalue())
            self.assertIn("PID: 5252", start_stdout.getvalue())
            self.assertIn("Log:", start_stdout.getvalue())
            self.assertIn("Daemon stopped.", stop_stdout.getvalue())
            self.assertIn("PID: 5252", stop_stdout.getvalue())

    def test_daemon_signal_handlers_shutdown_server_and_restore_previous_handlers(self) -> None:
        server = Mock()
        previous_handlers = {
            signal.SIGTERM: object(),
            signal.SIGINT: object(),
        }
        installed_handlers: dict[int, object] = {}
        restored_handlers: dict[int, object] = {}

        def fake_signal(signum: int, handler: object) -> None:
            if signum not in installed_handlers:
                installed_handlers[signum] = handler
            else:
                restored_handlers[signum] = handler

        class _ImmediateThread:
            def __init__(self, *, target: object, name: str, daemon: bool) -> None:
                self._target = target
                self.name = name
                self.daemon = daemon

            def start(self) -> None:
                assert callable(self._target)
                self._target()

        with patch.object(
            daemon_runtime.signal,
            "getsignal",
            side_effect=lambda signum: previous_handlers[signum],
        ), patch.object(
            daemon_runtime.signal,
            "signal",
            side_effect=fake_signal,
        ), patch.object(
            daemon_runtime.threading,
            "Thread",
            side_effect=lambda **kwargs: _ImmediateThread(**kwargs),
        ):
            with daemon_runtime._daemon_signal_handlers(server):
                term_handler = installed_handlers[signal.SIGTERM]
                int_handler = installed_handlers[signal.SIGINT]
                assert callable(term_handler)
                assert callable(int_handler)
                term_handler(signal.SIGTERM, None)
                int_handler(signal.SIGINT, None)

        self.assertEqual(server.shutdown.call_count, 2)
        self.assertEqual(restored_handlers[signal.SIGTERM], previous_handlers[signal.SIGTERM])
        self.assertEqual(restored_handlers[signal.SIGINT], previous_handlers[signal.SIGINT])

    def test_daemon_signal_handlers_skip_install_off_main_thread(self) -> None:
        server = Mock()
        with patch.object(
            daemon_runtime.threading,
            "current_thread",
            return_value=Mock(),
        ), patch.object(
            daemon_runtime.threading,
            "main_thread",
            return_value=Mock(),
        ), patch.object(
            daemon_runtime.signal,
            "signal",
        ) as signal_mock, patch.object(
            daemon_runtime.signal,
            "getsignal",
        ) as getsignal_mock:
            with daemon_runtime._daemon_signal_handlers(server):
                pass

        signal_mock.assert_not_called()
        getsignal_mock.assert_not_called()

    def test_report_writes_html_snapshot_with_scope_heat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            report_path = repo_root / "coordination.html"
            (repo_root / ".git").mkdir()
            setup_stdout = io.StringIO()
            report_stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "intent",
                            "Touch auth middleware",
                            "--scope",
                            "src/auth/middleware",
                            "--agent",
                            "agent-b",
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    main(
                        [
                            "context",
                            "write",
                            "auth-interface-change",
                            "UserSession now requires refresh_token.",
                            "--scope",
                            "src/auth",
                            "--scope",
                            "src/api",
                        ]
                    ),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(report_stdout):
                self.assertEqual(
                    main(["report", "--output", str(report_path)]),
                    0,
                )

            output = report_stdout.getvalue()
            html = report_path.read_text(encoding="utf-8")

            self.assertIn("Loom coordination report written:", output)
            self.assertIn("Top hotspots", output)
            self.assertIn("src/auth", output)
            self.assertTrue(report_path.exists())
            self.assertIn("Loom Coordination Report", html)
            self.assertIn("src/auth", html)
            self.assertIn("agent-a", html)
            self.assertIn("agent-b", html)

    def test_report_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            report_path = repo_root / "coordination.json.html"
            setup_stdout = io.StringIO()
            report_stdout = io.StringIO()
            (repo_root / ".git").mkdir()

            with working_directory(repo_root), contextlib.redirect_stdout(setup_stdout):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)
                self.assertEqual(
                    main(["claim", "Refactor auth flow", "--scope", "src/auth"]),
                    0,
                )

            with working_directory(repo_root), contextlib.redirect_stdout(report_stdout):
                self.assertEqual(
                    main(["report", "--json", "--output", str(report_path)]),
                    0,
                )

            payload = json.loads(report_stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["output_path"], str(report_path.resolve()))
            self.assertEqual(payload["report"]["summary"]["active_claims"], 1)
            self.assertEqual(payload["report"]["summary"]["live_active_agents"], 1)
            self.assertEqual(payload["report"]["summary"]["stale_active_agents"], 0)
            self.assertTrue(payload["report"]["hotspots"])
            self.assertEqual(payload["report"]["hotspots"][0]["scope"], "src/auth")

    def test_version_flag(self) -> None:
        stdout = io.StringIO()

        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exit_info:
                main(["--version"])

        self.assertEqual(exit_info.exception.code, 0)
        self.assertIn(__version__, stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
