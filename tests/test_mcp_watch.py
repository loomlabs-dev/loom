from __future__ import annotations

import pathlib
import sys
import threading
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.mcp_resources import Resource  # noqa: E402
from loom.mcp_watch import (  # noqa: E402
    _next_retry_seconds,
    maybe_start_background_watch,
    notify_resource_updated,
    notify_tool_resource_updates,
    project_resource_uris,
    set_watch_diagnostics,
    subscription_snapshot,
    watch_snapshot,
)


class _FakeThread:
    def __init__(self, *, alive: bool = False, name: str = "loom-mcp-watch") -> None:
        self._alive = alive
        self.name = name
        self.started = False

    def is_alive(self) -> bool:
        return self._alive

    def start(self) -> None:
        self.started = True


class _FakeStore:
    def latest_event_sequence(self) -> int:
        return 17


class _FakeClient:
    def __init__(self) -> None:
        self.store = _FakeStore()


class _FakeServer:
    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self._resource_subscriptions = {"loom://status", "loom://agent/agent-a"}
        self._watch_thread = None
        self._watch_stop = threading.Event()
        self._watch_state = "idle"
        self._watch_last_sequence = None
        self._watch_last_error = None
        self._initialized = True
        self._writer = object()
        self.notified: list[str] = []
        self.notifications: list[tuple[str, dict[str, object] | None]] = []
        self._resources = (
            Resource(
                uri="loom://start",
                name="Start",
                description="start",
                mime_type="application/json",
                reader=lambda: {},
            ),
            Resource(
                uri="loom://status",
                name="Status",
                description="status",
                mime_type="application/json",
                reader=lambda: {},
            ),
            Resource(
                uri="loom://identity",
                name="Identity",
                description="identity",
                mime_type="application/json",
                reader=lambda: {},
            ),
            Resource(
                uri="loom://mcp",
                name="MCP",
                description="mcp",
                mime_type="application/json",
                reader=lambda: {},
            ),
        )

    def _notify_resource_updated(self, uri: str) -> None:
        self.notified.append(uri)

    def _emit_notification(self, name: str, payload: dict[str, object] | None = None) -> None:
        self.notifications.append((name, payload))

    def _subscription_snapshot(self) -> tuple[str, ...]:
        return subscription_snapshot(self)

    def _project_resource_uris(self, *, include_identity: bool) -> tuple[str, ...]:
        return project_resource_uris(self, include_identity=include_identity)

    def _agent_resource_uris_for_structured(self, structured: dict[str, object]) -> tuple[str, ...]:
        del structured
        return ("loom://agent/agent-a",)

    def _activity_feed_resource_uris_for_structured(
        self, structured: dict[str, object]
    ) -> tuple[str, ...]:
        del structured
        return ("loom://activity/agent-a/after/0",)

    def _object_resource_uris_for_structured(self, structured: dict[str, object]) -> tuple[str, ...]:
        del structured
        return ("loom://claim/claim_123",)

    def _timeline_resource_uris_for_structured(self, structured: dict[str, object]) -> tuple[str, ...]:
        del structured
        return ("loom://timeline/claim_123",)

    def _timeline_alias_resource_uris_for_structured(
        self, structured: dict[str, object]
    ) -> tuple[str, ...]:
        del structured
        return ("loom://claim/claim_123/timeline",)

    def _event_feed_subscription_uris(self) -> tuple[str, ...]:
        return ("loom://events/after/0",)

    def _resource_uris(self) -> tuple[str, ...]:
        return tuple(resource.uri for resource in self._resources)

    def _resource_map(self) -> dict[str, Resource]:
        return {resource.uri: resource for resource in self._resources}

    def _maybe_client_for_project_resources(self):
        return _FakeClient()

    def _set_watch_diagnostics(self, **kwargs) -> None:
        set_watch_diagnostics(self, unchanged_sentinel=object(), **kwargs)

    def _background_watch_loop(self, stop_event, last_sequence) -> None:
        del stop_event, last_sequence

    def _maybe_start_background_watch(self) -> None:
        self.notified.append("restart")


class McpWatchTest(unittest.TestCase):
    def test_next_retry_seconds_caps_exponential_growth(self) -> None:
        self.assertEqual(_next_retry_seconds(current=0.5, maximum=2.0), 1.0)
        self.assertEqual(_next_retry_seconds(current=2.0, maximum=2.0), 2.0)

    def test_watch_snapshot_and_set_watch_diagnostics_track_state_and_notify_only_on_state_or_error(self) -> None:
        server = _FakeServer()
        unchanged = object()

        set_watch_diagnostics(
            server,
            state="watching",
            last_sequence=5,
            last_error=None,
            unchanged_sentinel=unchanged,
        )
        snapshot = watch_snapshot(server)
        self.assertEqual(snapshot["state"], "watching")
        self.assertEqual(snapshot["last_sequence"], 5)
        self.assertEqual(snapshot["last_error"], None)
        self.assertEqual(server.notified, ["loom://mcp"])

        server.notified.clear()
        set_watch_diagnostics(
            server,
            state=None,
            last_sequence=6,
            last_error=unchanged,
            unchanged_sentinel=unchanged,
        )
        self.assertEqual(server._watch_last_sequence, 6)
        self.assertEqual(server.notified, [])

    def test_notify_resource_updated_respects_subscription_filter(self) -> None:
        server = _FakeServer()

        notify_resource_updated(server, "loom://status")
        notify_resource_updated(server, "loom://log")

        self.assertEqual(
            server.notifications,
            [("notifications/resources/updated", {"uri": "loom://status"})],
        )

    def test_notify_tool_resource_updates_fans_out_and_emits_list_changed_for_resource_delta(self) -> None:
        server = _FakeServer()
        before_resources = ("loom://start",)

        notify_tool_resource_updates(
            server,
            name="loom_init",
            before_resources=before_resources,
            structured={"claim": "claim_123"},
        )

        self.assertEqual(
            server.notifications[0],
            ("notifications/resources/list_changed", None),
        )
        self.assertIn("loom://identity", server.notified)
        self.assertIn("loom://start", server.notified)
        self.assertIn("loom://mcp", server.notified)
        self.assertIn("loom://agent/agent-a", server.notified)
        self.assertIn("loom://activity/agent-a/after/0", server.notified)
        self.assertIn("loom://claim/claim_123", server.notified)
        self.assertIn("loom://timeline/claim_123", server.notified)
        self.assertIn("loom://claim/claim_123/timeline", server.notified)
        self.assertIn("loom://events/after/0", server.notified)

    def test_maybe_start_background_watch_requires_initialized_writer_and_subscriptions(self) -> None:
        server = _FakeServer()
        server._initialized = False
        maybe_start_background_watch(server, daemon_retry_seconds=0.5, stream_retry_seconds=0.25)
        self.assertIsNone(server._watch_thread)

        server._initialized = True
        server._writer = None
        maybe_start_background_watch(server, daemon_retry_seconds=0.5, stream_retry_seconds=0.25)
        self.assertIsNone(server._watch_thread)

        server._writer = object()
        server._resource_subscriptions.clear()
        maybe_start_background_watch(server, daemon_retry_seconds=0.5, stream_retry_seconds=0.25)
        self.assertIsNone(server._watch_thread)

    def test_maybe_start_background_watch_starts_thread_with_latest_sequence(self) -> None:
        server = _FakeServer()
        created: list[_FakeThread] = []

        def fake_thread(*, target, args, name, daemon):
            del target, args, daemon
            thread = _FakeThread(alive=False, name=name)
            created.append(thread)
            return thread

        with patch("loom.mcp_watch.threading.Thread", side_effect=fake_thread):
            maybe_start_background_watch(
                server,
                daemon_retry_seconds=0.5,
                stream_retry_seconds=0.25,
            )

        self.assertEqual(len(created), 1)
        self.assertTrue(created[0].started)
        self.assertIs(server._watch_thread, created[0])
        self.assertEqual(server._watch_state, "starting")
        self.assertEqual(server._watch_last_sequence, 17)
        self.assertIn("loom://mcp", server.notified)


if __name__ == "__main__":
    unittest.main()
