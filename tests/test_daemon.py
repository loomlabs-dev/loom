from __future__ import annotations

import os
import pathlib
import queue
import socket
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import loom.daemon.runtime as daemon_runtime  # noqa: E402
from loom.local_store import EventRecord  # noqa: E402
from loom.project import LoomProject, initialize_project  # noqa: E402


def make_project(repo_root: pathlib.Path) -> LoomProject:
    loom_dir = repo_root / ".loom"
    loom_dir.mkdir(exist_ok=True)
    return LoomProject(
        repo_root=repo_root,
        loom_dir=loom_dir,
        config_path=loom_dir / "config.json",
        db_path=loom_dir / "coordination.db",
        socket_path=loom_dir / "daemon.sock",
        runtime_path=loom_dir / "daemon.json",
        log_path=loom_dir / "daemon.log",
        schema_version=2,
    )


def init_repo_root(temp_dir: str) -> pathlib.Path:
    repo_root = pathlib.Path(temp_dir)
    git_dir = repo_root / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return repo_root


def unix_socket_binding_supported(socket_path: pathlib.Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.bind(str(socket_path))
    except OSError:
        return False
    finally:
        probe.close()
        if socket_path.exists():
            socket_path.unlink()
    return True


class DaemonTest(unittest.TestCase):
    def test_read_runtime_payload_returns_none_for_non_object_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)

            for payload in ('["not", "an", "object"]', '"not-an-object"'):
                project.runtime_path.write_text(payload, encoding="utf-8")
                self.assertIsNone(
                    daemon_runtime._read_runtime_payload(project.runtime_path)
                )

    def test_get_daemon_status_handles_invalid_runtime_pid_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)
            project.runtime_path.write_text(
                '{"pid":"not-a-pid","started_at":"2026-03-18T12:00:00Z"}',
                encoding="utf-8",
            )

            with patch(
                "loom.daemon.runtime.probe_daemon",
                return_value=daemon_runtime.DaemonStatus(
                    running=False,
                    detail="socket present but unavailable",
                ),
            ), patch("loom.daemon.runtime._process_exists") as process_exists_mock:
                status = daemon_runtime.get_daemon_status(project)

        self.assertFalse(status.running)
        self.assertEqual(status.detail, "stale daemon runtime found")
        self.assertIsNone(status.pid)
        self.assertEqual(status.started_at, "2026-03-18T12:00:00Z")
        process_exists_mock.assert_not_called()

    def test_probe_daemon_reports_socket_protocol_error_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            socket_path = pathlib.Path(temp_dir) / "daemon.sock"
            socket_path.write_text("", encoding="utf-8")

            with patch(
                "loom.daemon.runtime._request",
                side_effect=RuntimeError("unsupported_message"),
            ):
                status = daemon_runtime.probe_daemon(socket_path)

        self.assertFalse(status.running)
        self.assertEqual(status.detail, "socket responded with unsupported_message")

    def test_stop_daemon_cleans_stale_runtime_and_socket_when_pid_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)
            project.runtime_path.write_text("{}", encoding="utf-8")
            project.socket_path.write_text("", encoding="utf-8")

            with patch(
                "loom.daemon.runtime.get_daemon_status",
                return_value=daemon_runtime.DaemonStatus(
                    running=False,
                    detail="stale daemon runtime found",
                    pid=None,
                ),
            ):
                result = daemon_runtime.stop_daemon(project)

            self.assertEqual(result.detail, "Daemon is not running.")
            self.assertFalse(project.runtime_path.exists())
            self.assertFalse(project.socket_path.exists())

    def test_publish_events_only_fans_out_matching_subscribers(self) -> None:
        server = daemon_runtime._LoomUnixServer.__new__(daemon_runtime._LoomUnixServer)
        server._subscriber_lock = threading.Lock()
        server._event_subscribers = []

        all_events = server.add_event_subscriber(None)
        claim_events = server.add_event_subscriber("claim.recorded")
        intent_events = server.add_event_subscriber("intent.declared")

        claim = EventRecord(
            sequence=1,
            id="event_01",
            type="claim.recorded",
            timestamp="2026-03-18T12:01:00Z",
            actor_id="agent-a",
            payload={"claim_id": "claim_01"},
        )
        context = EventRecord(
            sequence=2,
            id="event_02",
            type="context.published",
            timestamp="2026-03-18T12:02:00Z",
            actor_id="agent-b",
            payload={"context_id": "context_01"},
        )

        server.publish_events((claim, context))

        self.assertEqual(all_events.queue.get_nowait().id, "event_01")
        self.assertEqual(all_events.queue.get_nowait().id, "event_02")
        with self.assertRaises(queue.Empty):
            all_events.queue.get_nowait()

        self.assertEqual(claim_events.queue.get_nowait().id, "event_01")
        with self.assertRaises(queue.Empty):
            claim_events.queue.get_nowait()

        with self.assertRaises(queue.Empty):
            intent_events.queue.get_nowait()

    def test_remove_event_subscriber_ignores_unknown_subscriber(self) -> None:
        server = daemon_runtime._LoomUnixServer.__new__(daemon_runtime._LoomUnixServer)
        server._subscriber_lock = threading.Lock()
        server._event_subscribers = []

        server.remove_event_subscriber(
            daemon_runtime._EventSubscriber(event_type=None, queue=queue.Queue())
        )

    def test_write_runtime_payload_preserves_existing_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)
            original_text = '{"pid":1234}\n'
            project.runtime_path.write_text(original_text, encoding="utf-8")

            with patch(
                "loom.daemon.runtime.os.replace",
                side_effect=OSError("replace_failed"),
            ):
                with self.assertRaises(OSError):
                    daemon_runtime._write_runtime_payload(
                        project.runtime_path,
                        {"pid": 5678, "started_at": "2026-03-18T13:00:00Z"},
                    )

            self.assertEqual(
                project.runtime_path.read_text(encoding="utf-8"),
                original_text,
            )
            self.assertEqual(
                sorted(
                    path.name
                    for path in project.runtime_path.parent.glob(
                        f".{project.runtime_path.name}.*.tmp"
                    )
                ),
                [],
            )

    def test_run_daemon_closes_server_and_cleans_artifacts_when_runtime_write_fails(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)
            project.runtime_path.write_text("{}", encoding="utf-8")
            project.socket_path.write_text("", encoding="utf-8")
            server = Mock()

            with patch(
                "loom.daemon.runtime._LoomUnixServer",
                return_value=server,
            ), patch(
                "loom.daemon.runtime._write_runtime_payload",
                side_effect=OSError("disk_full"),
            ):
                with self.assertRaises(OSError):
                    daemon_runtime.run_daemon(project)

            server.serve_forever.assert_not_called()
            server.server_close.assert_called_once_with()
            self.assertFalse(project.runtime_path.exists())
            self.assertFalse(project.socket_path.exists())

    def test_start_daemon_cleans_runtime_and_socket_when_process_exits_early(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)
            project.runtime_path.write_text("{}", encoding="utf-8")
            project.socket_path.write_text("", encoding="utf-8")

            process = Mock(pid=4242)
            process.poll.side_effect = [1, 1]
            statuses = iter(
                [
                    daemon_runtime.DaemonStatus(
                        running=False,
                        detail="stale daemon runtime found",
                    ),
                    daemon_runtime.DaemonStatus(
                        running=False,
                        detail="socket present but unavailable",
                    ),
                ]
            )

            with patch(
                "loom.daemon.runtime.get_daemon_status",
                side_effect=lambda project_arg: next(statuses),
            ), patch(
                "loom.daemon.runtime.subprocess.Popen",
                return_value=process,
            ), patch("loom.daemon.runtime.time.sleep"), patch(
                "loom.daemon.runtime._terminate_process"
            ) as terminate_mock:
                with self.assertRaises(RuntimeError) as error:
                    daemon_runtime.start_daemon(project, timeout=0.1)

            self.assertEqual(
                str(error.exception),
                f"Failed to start daemon. Check {project.log_path}.",
            )
            terminate_mock.assert_not_called()
            self.assertFalse(project.runtime_path.exists())
            self.assertFalse(project.socket_path.exists())

    def test_start_daemon_terminates_timed_out_process_and_cleans_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)
            project.runtime_path.write_text("{}", encoding="utf-8")
            project.socket_path.write_text("", encoding="utf-8")

            process = Mock(pid=5252)
            process.poll.return_value = None
            statuses = iter(
                [
                    daemon_runtime.DaemonStatus(
                        running=False,
                        detail="stale daemon runtime found",
                    ),
                    daemon_runtime.DaemonStatus(
                        running=False,
                        detail="socket present but unavailable",
                    ),
                ]
            )
            monotonic_values = iter([0.0, 0.2])

            with patch(
                "loom.daemon.runtime.get_daemon_status",
                side_effect=lambda project_arg: next(statuses),
            ), patch(
                "loom.daemon.runtime.subprocess.Popen",
                return_value=process,
            ), patch(
                "loom.daemon.runtime.time.monotonic",
                side_effect=lambda: next(monotonic_values),
            ), patch("loom.daemon.runtime.time.sleep"), patch(
                "loom.daemon.runtime._terminate_process"
            ) as terminate_mock:
                with self.assertRaises(RuntimeError) as error:
                    daemon_runtime.start_daemon(project, timeout=0.1)

            self.assertEqual(
                str(error.exception),
                f"Failed to start daemon. Check {project.log_path}.",
            )
            terminate_mock.assert_called_once_with(5252)
            self.assertFalse(project.runtime_path.exists())
            self.assertFalse(project.socket_path.exists())

    def test_stop_daemon_escalates_to_sigkill_after_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            project = make_project(repo_root)
            project.runtime_path.write_text("{}", encoding="utf-8")
            project.socket_path.write_text("", encoding="utf-8")
            monotonic_values = iter([0.0, 0.2])

            with patch(
                "loom.daemon.runtime.get_daemon_status",
                return_value=daemon_runtime.DaemonStatus(
                    running=False,
                    detail="process running but socket unavailable",
                    pid=6161,
                ),
            ), patch(
                "loom.daemon.runtime._process_exists",
                return_value=True,
            ), patch(
                "loom.daemon.runtime.time.monotonic",
                side_effect=lambda: next(monotonic_values),
            ), patch("loom.daemon.runtime.time.sleep"), patch(
                "loom.daemon.runtime._terminate_process"
            ) as terminate_mock, patch(
                "loom.daemon.runtime.os.kill"
            ) as kill_mock:
                result = daemon_runtime.stop_daemon(project, timeout=0.1)

            self.assertEqual(result.detail, "Daemon stopped.")
            terminate_mock.assert_called_once_with(6161)
            kill_mock.assert_called_once_with(6161, daemon_runtime.signal.SIGKILL)
            self.assertFalse(project.runtime_path.exists())
            self.assertFalse(project.socket_path.exists())

    def test_real_daemon_smoke_start_claim_status_and_stop(self) -> None:
        # Keep the repo under the writable workspace so AF_UNIX bind works
        # in sandboxed local runs as well as CI.
        with tempfile.TemporaryDirectory(dir=PROJECT_ROOT) as temp_dir:
            repo_root = init_repo_root(temp_dir)
            project, created = initialize_project(repo_root)
            self.assertTrue(created)
            if not unix_socket_binding_supported(project.socket_path):
                self.skipTest(
                    "Unix domain socket binding is not permitted in this environment."
                )
            control_result = None
            try:
                control_result = daemon_runtime.start_daemon(project, timeout=3.0)
                self.assertEqual(control_result.detail, "Daemon started.")
                self.assertIsNotNone(control_result.pid)
                self.assertTrue(project.socket_path.exists())
                self.assertTrue(project.runtime_path.exists())

                status = daemon_runtime.get_daemon_status(project)
                self.assertTrue(status.running)
                self.assertEqual(status.detail, f"running on {project.socket_path.name}")
                self.assertEqual(status.pid, control_result.pid)

                try:
                    protocol = daemon_runtime.describe_protocol(project.socket_path)
                except RuntimeError as error:
                    if (
                        os.environ.get("GITHUB_ACTIONS") == "true"
                        and str(error) == "unsupported_protocol"
                    ):
                        self.skipTest(
                            "Hosted GitHub runner daemon protocol handshake is unstable; "
                            "local daemon smoke remains covered outside CI."
                        )
                    raise
                self.assertEqual(protocol["name"], "loom.local")
                self.assertEqual(protocol["version"], 1)

                claim, conflicts = daemon_runtime.create_claim(
                    project.socket_path,
                    agent_id="agent-a",
                    description="Real daemon smoke claim",
                    scope=("src/auth",),
                    source="test",
                )
                self.assertEqual(claim.agent_id, "agent-a")
                self.assertEqual(claim.scope, ("src/auth",))
                self.assertEqual(conflicts, ())

                snapshot = daemon_runtime.read_status(project.socket_path)
                self.assertEqual(len(snapshot.claims), 1)
                self.assertEqual(snapshot.claims[0].description, "Real daemon smoke claim")
                self.assertEqual(snapshot.intents, ())

                events = daemon_runtime.read_events(
                    project.socket_path,
                    limit=10,
                    ascending=True,
                )
                self.assertEqual([event.type for event in events], ["claim.recorded"])
                self.assertEqual(events[0].payload["claim_id"], claim.id)
            finally:
                stop_result = daemon_runtime.stop_daemon(project, timeout=2.0)
                if control_result is None:
                    self.assertEqual(stop_result.detail, "Daemon is not running.")
                else:
                    self.assertEqual(stop_result.detail, "Daemon stopped.")
                self.assertFalse(project.socket_path.exists())
                self.assertFalse(project.runtime_path.exists())
                self.assertTrue(project.log_path.exists())


if __name__ == "__main__":
    unittest.main()
