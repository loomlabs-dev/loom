from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.client import CoordinationClient  # noqa: E402
from loom.daemon import DaemonStatus  # noqa: E402
from loom.protocol import ProtocolResponseError  # noqa: E402
from loom.project import LoomProject  # noqa: E402


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


class ClientTest(unittest.TestCase):
    def test_daemon_status_caches_until_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            first = DaemonStatus(running=False, detail="not running")
            second = DaemonStatus(running=True, detail="running on daemon.sock")

            with patch(
                "loom.client.get_daemon_status",
                side_effect=(first, second),
            ) as get_status_mock:
                self.assertIs(client.daemon_status(), first)
                self.assertIs(client.daemon_status(), first)
                self.assertIs(client.daemon_status(refresh=True), second)

            self.assertEqual(get_status_mock.call_count, 2)

    def test_store_property_initializes_store_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            store_instance = Mock()

            with patch(
                "loom.client.CoordinationStore",
                return_value=store_instance,
            ) as store_class_mock:
                self.assertIs(client.store, store_instance)
                self.assertIs(client.store, store_instance)

            store_class_mock.assert_called_once_with(
                project.db_path,
                repo_root=project.repo_root,
            )
            store_instance.initialize.assert_called_once_with()

    def test_close_releases_store_and_clears_cached_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            store_instance = Mock()
            client._store = store_instance
            client._daemon_status = DaemonStatus(running=True, detail="running on daemon.sock")

            client.close()

            store_instance.close_thread_connection.assert_called_once_with()
            self.assertIsNone(client._store)
            self.assertIsNone(client._daemon_status)

    def test_create_claim_uses_daemon_when_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            client._store = Mock()
            expected = ("daemon-claim", ("daemon-conflict",))

            with patch(
                "loom.client.get_daemon_status",
                return_value=DaemonStatus(running=True, detail="running on daemon.sock"),
            ), patch(
                "loom.client.daemon_create_claim",
                return_value=expected,
            ) as daemon_create_mock:
                result = client.create_claim(
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=("src/auth",),
                    source="test",
                    lease_minutes=30,
                    lease_policy="yield",
                )

            self.assertEqual(result, expected)
            daemon_create_mock.assert_called_once_with(
                project.socket_path,
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth",),
                source="test",
                lease_minutes=30,
                lease_policy="yield",
            )
            client._store.record_claim.assert_not_called()

    def test_create_claim_falls_back_to_store_after_daemon_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            client._store = Mock()
            client._store.record_claim.return_value = ("direct-claim", ("direct-conflict",))

            with patch(
                "loom.client.get_daemon_status",
                side_effect=(
                    DaemonStatus(running=True, detail="running on daemon.sock"),
                    DaemonStatus(running=False, detail="not running"),
                ),
            ) as get_status_mock, patch(
                "loom.client.daemon_create_claim",
                side_effect=RuntimeError("socket_unavailable"),
            ) as daemon_create_mock:
                result = client.create_claim(
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=("src/auth",),
                    source="test",
                )

            self.assertEqual(result, ("direct-claim", ("direct-conflict",)))
            daemon_create_mock.assert_called_once()
            client._store.record_claim.assert_called_once_with(
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth",),
                source="test",
                lease_minutes=None,
                lease_policy=None,
            )
            self.assertEqual(get_status_mock.call_count, 2)

    def test_create_claim_preserves_structured_daemon_application_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            client._store = Mock()

            with patch(
                "loom.client.get_daemon_status",
                return_value=DaemonStatus(running=True, detail="running on daemon.sock"),
            ), patch(
                "loom.client.daemon_create_claim",
                side_effect=ProtocolResponseError(
                    "No active claim for agent-a.",
                    code="no_active_claim",
                ),
            ):
                with self.assertRaises(ProtocolResponseError) as error:
                    client.create_claim(
                        agent_id="agent-a",
                        description="Refactor auth flow",
                        scope=("src/auth",),
                        source="test",
                    )

            self.assertEqual(str(error.exception), "No active claim for agent-a.")
            self.assertEqual(error.exception.code, "no_active_claim")
            client._store.record_claim.assert_not_called()

    def test_create_claim_does_not_fallback_on_malformed_daemon_payload_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            client._store = Mock()

            with patch(
                "loom.client.get_daemon_status",
                return_value=DaemonStatus(running=True, detail="running on daemon.sock"),
            ), patch(
                "loom.client.daemon_create_claim",
                side_effect=RuntimeError("invalid_claim_payload"),
            ):
                with self.assertRaisesRegex(RuntimeError, "invalid_claim_payload"):
                    client.create_claim(
                        agent_id="agent-a",
                        description="Refactor auth flow",
                        scope=("src/auth",),
                        source="test",
                    )

            client._store.record_claim.assert_not_called()

    def test_read_events_with_unbounded_limit_bypasses_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            client._store = Mock()
            client._store.list_events.return_value = ("event-a", "event-b")

            with patch("loom.client.get_daemon_status") as get_status_mock, patch(
                "loom.client.daemon_read_events"
            ) as daemon_read_events_mock:
                result = client.read_events(
                    limit=None,
                    event_type="claim.recorded",
                    after_sequence=10,
                    ascending=True,
                )

            self.assertEqual(result, ("event-a", "event-b"))
            client._store.list_events.assert_called_once_with(
                limit=None,
                event_type="claim.recorded",
                after_sequence=10,
                ascending=True,
            )
            get_status_mock.assert_not_called()
            daemon_read_events_mock.assert_not_called()

    def test_follow_events_requires_running_daemon(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)

            with patch(
                "loom.client.get_daemon_status",
                return_value=DaemonStatus(running=False, detail="not running"),
            ):
                with self.assertRaises(RuntimeError) as error:
                    client.follow_events(event_type="claim.recorded", after_sequence=5)

            self.assertEqual(str(error.exception), "Daemon is not running.")

    def test_follow_events_uses_daemon_stream_when_running(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project = make_project(pathlib.Path(temp_dir))
            client = CoordinationClient(project)
            stream = iter(("event-a",))

            with patch(
                "loom.client.get_daemon_status",
                return_value=DaemonStatus(running=True, detail="running on daemon.sock"),
            ), patch(
                "loom.client.daemon_follow_events",
                return_value=stream,
            ) as follow_mock:
                result = client.follow_events(
                    event_type="claim.recorded",
                    after_sequence=5,
                )

            self.assertIs(result, stream)
            follow_mock.assert_called_once_with(
                project.socket_path,
                event_type="claim.recorded",
                after_sequence=5,
            )


if __name__ == "__main__":
    unittest.main()
