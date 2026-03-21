from __future__ import annotations

import contextlib
import io
import pathlib
import queue
import sys
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import loom.daemon.runtime as daemon_runtime  # noqa: E402
from loom.local_store import ClaimRecord, EventRecord  # noqa: E402
from loom.protocol import (  # noqa: E402
    LOCAL_PROTOCOL_NAME,
    LOCAL_PROTOCOL_VERSION,
    MAX_MESSAGE_BYTES,
    ProtocolError,
    ProtocolResponseError,
    describe_local_protocol,
    encode_message,
    error_payload,
    read_message,
    require_compatible_message,
    success_payload,
)


class ProtocolTest(unittest.TestCase):
    def test_describe_local_protocol_lists_core_operations(self) -> None:
        descriptor = describe_local_protocol()

        self.assertEqual(descriptor["name"], LOCAL_PROTOCOL_NAME)
        self.assertEqual(descriptor["version"], LOCAL_PROTOCOL_VERSION)
        self.assertIn("protocol.describe", descriptor["operations"])
        self.assertIn("claim.create", descriptor["operations"])
        self.assertIn("claim.renew", descriptor["operations"])
        self.assertIn("intent.renew", descriptor["operations"])
        self.assertIn("agents.read", descriptor["operations"])
        self.assertIn("events.follow", descriptor["operations"])
        self.assertIn("semantic_overlap", descriptor["conflict_kinds"])
        self.assertEqual(descriptor["context_ack_statuses"], ["read", "adapted"])
        self.assertIn("operation_schemas", descriptor)
        self.assertIn("object_schemas", descriptor)
        claim_request = descriptor["operation_schemas"]["claim.create"]["request"]
        self.assertEqual(
            claim_request["required"],
            ["type", "agent_id", "description", "scope"],
        )
        self.assertIn("agent_id", claim_request["properties"])
        self.assertIn("description", claim_request["properties"])
        self.assertIn("scope", claim_request["properties"])
        self.assertIn("lease_minutes", claim_request["properties"])
        self.assertIn("lease_policy", claim_request["properties"])
        self.assertIn(
            "stream_response",
            descriptor["operation_schemas"]["events.follow"],
        )
        stream_response = descriptor["operation_schemas"]["events.follow"]["stream_response"]
        self.assertIn("oneOf", stream_response)
        self.assertEqual(
            stream_response["oneOf"][1]["properties"]["heartbeat"]["const"],
            "events",
        )

    def test_protocol_descriptor_includes_core_object_schemas(self) -> None:
        descriptor = describe_local_protocol()

        object_schemas = descriptor["object_schemas"]
        self.assertIn("claim", object_schemas)
        self.assertIn("context", object_schemas)
        self.assertIn("event", object_schemas)
        self.assertIn("agent_presence", object_schemas)
        self.assertIn("agent_snapshot", object_schemas)
        self.assertIn("inbox_snapshot", object_schemas)
        self.assertIn("error_code", object_schemas["error_response"]["properties"])
        self.assertIn("lease_expires_at", object_schemas["claim"]["properties"])
        self.assertIn("lease_policy", object_schemas["claim"]["properties"])
        self.assertIn("lease_expires_at", object_schemas["intent"]["properties"])
        self.assertIn("lease_policy", object_schemas["intent"]["properties"])
        self.assertEqual(
            object_schemas["context_ack"]["properties"]["status"]["enum"],
            ["read", "adapted"],
        )
        self.assertEqual(
            descriptor["operation_schemas"]["agents.read"]["response"]["properties"]["agents"][
                "items"
            ]["$ref"],
            "#/object_schemas/agent_presence",
        )

    def test_encode_message_round_trips_protocol_envelope(self) -> None:
        payload = {"type": "ping", "service": "loomd"}

        message = read_message(io.BytesIO(encode_message(payload)))

        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message["protocol"], LOCAL_PROTOCOL_NAME)
        self.assertEqual(message["protocol_version"], LOCAL_PROTOCOL_VERSION)
        self.assertEqual(message["type"], "ping")
        self.assertEqual(message["service"], "loomd")

    def test_read_message_preserves_message_boundaries(self) -> None:
        stream = io.BytesIO(
            encode_message({"type": "ping"}) + encode_message({"type": "status.read"})
        )

        first = read_message(stream)
        second = read_message(stream)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        assert first is not None
        assert second is not None
        self.assertEqual(first["type"], "ping")
        self.assertEqual(second["type"], "status.read")

    def test_read_message_rejects_oversized_payloads(self) -> None:
        with self.assertRaises(ProtocolError) as error:
            read_message(io.BytesIO(b"x" * (MAX_MESSAGE_BYTES + 1)))

        self.assertEqual(str(error.exception), "message_too_large")

    def test_require_compatible_message_rejects_wrong_protocol_version(self) -> None:
        with self.assertRaises(ProtocolError) as error:
            require_compatible_message(
                {
                    "protocol": LOCAL_PROTOCOL_NAME,
                    "protocol_version": LOCAL_PROTOCOL_VERSION + 1,
                    "ok": True,
                }
            )

        self.assertEqual(str(error.exception), "unsupported_protocol_version")

    def test_runtime_response_reader_surfaces_daemon_errors(self) -> None:
        stream = io.BytesIO(
            encode_message(
                error_payload(
                    "unsupported_message",
                    error_code="unsupported_message",
                    detail="The daemon rejected the request type.",
                )
            )
        )

        with self.assertRaises(ProtocolResponseError) as error:
            daemon_runtime._read_response_message(stream)

        self.assertEqual(str(error.exception), "unsupported_message")
        self.assertEqual(error.exception.code, "unsupported_message")
        self.assertEqual(error.exception.detail, "The daemon rejected the request type.")

    def test_runtime_response_reader_accepts_success_payload(self) -> None:
        stream = io.BytesIO(encode_message(success_payload(service="loomd")))

        response = daemon_runtime._read_response_message(stream)

        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response["ok"])
        self.assertEqual(response["service"], "loomd")

    def test_runtime_describe_protocol_returns_protocol_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "protocol": describe_local_protocol()},
        ) as request_mock:
            response = daemon_runtime.describe_protocol(pathlib.Path("/tmp/loom.sock"))

        request_mock.assert_called_once()
        self.assertEqual(response["name"], LOCAL_PROTOCOL_NAME)
        self.assertIn("protocol.describe", response["operations"])

    def test_runtime_follow_events_rejects_invalid_stream_handshake(self) -> None:
        fake_socket = Mock()
        fake_socket.makefile.return_value = contextlib.nullcontext(io.BytesIO())

        with patch.object(daemon_runtime.socket, "socket", return_value=fake_socket), patch.object(
            daemon_runtime,
            "_read_response_message",
            side_effect=(
                success_payload(stream="status"),
            ),
        ):
            with self.assertRaises(RuntimeError) as error:
                tuple(daemon_runtime.follow_events(pathlib.Path("/tmp/loom.sock")))

        self.assertEqual(str(error.exception), "invalid_follow_payload")
        fake_socket.connect.assert_called_once_with("/tmp/loom.sock")
        fake_socket.close.assert_called_once()

    def test_runtime_follow_events_rejects_missing_event_midstream(self) -> None:
        fake_socket = Mock()
        fake_socket.makefile.return_value = contextlib.nullcontext(io.BytesIO())

        with patch.object(daemon_runtime.socket, "socket", return_value=fake_socket), patch.object(
            daemon_runtime,
            "_read_response_message",
            side_effect=(
                success_payload(stream="events"),
                success_payload(),
            ),
        ):
            with self.assertRaises(RuntimeError) as error:
                tuple(daemon_runtime.follow_events(pathlib.Path("/tmp/loom.sock")))

        self.assertEqual(str(error.exception), "invalid_follow_payload")
        fake_socket.close.assert_called_once()

    def test_runtime_follow_events_rejects_malformed_event_midstream(self) -> None:
        fake_socket = Mock()
        fake_socket.makefile.return_value = contextlib.nullcontext(io.BytesIO())

        with patch.object(daemon_runtime.socket, "socket", return_value=fake_socket), patch.object(
            daemon_runtime,
            "_read_response_message",
            side_effect=(
                success_payload(stream="events"),
                success_payload(event={"id": "event_missing_fields"}),
            ),
        ):
            with self.assertRaises(RuntimeError) as error:
                tuple(daemon_runtime.follow_events(pathlib.Path("/tmp/loom.sock")))

        self.assertEqual(str(error.exception), "invalid_follow_payload")
        fake_socket.close.assert_called_once()

    def test_runtime_follow_events_ignores_heartbeat_frames(self) -> None:
        fake_socket = Mock()
        fake_socket.makefile.return_value = contextlib.nullcontext(io.BytesIO())
        event_payload = {
            "sequence": 12,
            "id": "event_12",
            "type": "claim.recorded",
            "timestamp": "2026-03-18T10:00:00Z",
            "actor_id": "agent-a",
            "payload": {"claim_id": "claim_01"},
        }

        with patch.object(daemon_runtime.socket, "socket", return_value=fake_socket), patch.object(
            daemon_runtime,
            "_read_response_message",
            side_effect=(
                success_payload(stream="events"),
                success_payload(heartbeat="events"),
                success_payload(event=event_payload),
                None,
            ),
        ):
            events = tuple(daemon_runtime.follow_events(pathlib.Path("/tmp/loom.sock")))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].sequence, 12)
        fake_socket.settimeout.assert_any_call(daemon_runtime.FOLLOW_STREAM_IDLE_TIMEOUT_SECONDS)
        fake_socket.close.assert_called_once()

    def test_runtime_follow_events_times_out_when_stream_goes_idle_without_heartbeat(
        self,
    ) -> None:
        fake_socket = Mock()
        fake_socket.makefile.return_value = contextlib.nullcontext(io.BytesIO())

        with patch.object(daemon_runtime.socket, "socket", return_value=fake_socket), patch.object(
            daemon_runtime,
            "_read_response_message",
            side_effect=(
                success_payload(stream="events"),
                TimeoutError("timed out"),
            ),
        ):
            with self.assertRaises(RuntimeError) as error:
                tuple(daemon_runtime.follow_events(pathlib.Path("/tmp/loom.sock")))

        self.assertEqual(str(error.exception), "follow_timeout")
        fake_socket.close.assert_called_once()

    def test_request_handler_follow_events_emits_heartbeat_when_idle(self) -> None:
        event = EventRecord(
            sequence=13,
            id="event_13",
            type="claim.recorded",
            timestamp="2026-03-18T10:05:00Z",
            actor_id="agent-a",
            payload={"claim_id": "claim_02"},
        )
        subscriber = Mock()
        subscriber.queue = Mock()
        subscriber.queue.get.side_effect = [
            queue.Empty(),
            event,
            queue.Empty(),
        ]
        store = Mock()
        store.list_events.return_value = ()
        server = Mock(store=store)
        server.add_event_subscriber.return_value = subscriber

        handler = daemon_runtime._LoomRequestHandler.__new__(daemon_runtime._LoomRequestHandler)
        handler.server = server
        emitted: list[dict[str, object]] = []

        def record_response(payload: dict[str, object]) -> None:
            emitted.append(payload)
            if len(emitted) >= 4:
                raise BrokenPipeError

        handler._write_response = record_response  # type: ignore[method-assign]

        handler._follow_events(
            store=store,
            event_type="claim.recorded",
            after_sequence=None,
        )

        self.assertEqual(
            emitted[:3],
            [
                success_payload(stream="events"),
                success_payload(heartbeat="events"),
                success_payload(event=daemon_runtime._event_to_wire(event)),
            ],
        )
        subscriber.queue.get.assert_called_with(
            timeout=daemon_runtime.FOLLOW_STREAM_HEARTBEAT_SECONDS
        )
        server.remove_event_subscriber.assert_called_once_with(subscriber)

    def test_runtime_read_events_rejects_invalid_events_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "events": "not-a-list"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.read_events(pathlib.Path("/tmp/loom.sock"))

        self.assertEqual(str(error.exception), "invalid_events_payload")

    def test_runtime_read_agents_rejects_invalid_agents_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "agents": "not-a-list"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.read_agents(pathlib.Path("/tmp/loom.sock"))

        self.assertEqual(str(error.exception), "invalid_agents_payload")

    def test_runtime_read_agent_snapshot_rejects_invalid_agent_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "agent": "not-an-object"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.read_agent_snapshot(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                )

        self.assertEqual(str(error.exception), "invalid_agent_payload")

    def test_runtime_read_status_rejects_invalid_status_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={
                "ok": True,
                "claims": "not-a-list",
                "intents": [],
                "context": [],
                "conflicts": [],
            },
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.read_status(pathlib.Path("/tmp/loom.sock"))

        self.assertEqual(str(error.exception), "invalid_status_payload")

    def test_runtime_read_inbox_snapshot_rejects_invalid_inbox_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "inbox": "not-an-object"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.read_inbox_snapshot(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                )

        self.assertEqual(str(error.exception), "invalid_inbox_payload")

    def test_runtime_create_claim_rejects_invalid_claim_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "claim": "not-an-object", "conflicts": []},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.create_claim(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=["src/auth"],
                    source="daemon",
                )

        self.assertEqual(str(error.exception), "invalid_claim_payload")

    def test_runtime_release_claim_rejects_invalid_claim_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "claim": "not-an-object"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.release_claim(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                )

        self.assertEqual(str(error.exception), "invalid_claim_payload")

    def test_runtime_renew_claim_rejects_invalid_claim_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "claim": "not-an-object"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.renew_claim(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                    lease_minutes=60,
                    source="daemon",
                )

        self.assertEqual(str(error.exception), "invalid_claim_payload")

    def test_runtime_create_claim_rejects_invalid_conflicts_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={
                "ok": True,
                "claim": {
                    "id": "claim_01",
                    "agent_id": "agent-a",
                    "description": "Refactor auth flow",
                    "scope": ["src/auth"],
                    "status": "active",
                    "created_at": "2026-03-14T20:00:00Z",
                },
                "conflicts": "not-a-list",
            },
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.create_claim(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                    description="Refactor auth flow",
                    scope=["src/auth"],
                    source="daemon",
                )

        self.assertEqual(str(error.exception), "invalid_conflicts_payload")

    def test_runtime_acknowledge_context_rejects_invalid_ack_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "ack": "not-an-object"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.acknowledge_context(
                    pathlib.Path("/tmp/loom.sock"),
                    context_id="context-1",
                    agent_id="agent-a",
                    status="read",
                )

        self.assertEqual(str(error.exception), "invalid_context_ack_payload")

    def test_runtime_declare_intent_rejects_invalid_conflicts_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={
                "ok": True,
                "intent": {
                    "id": "intent_01",
                    "agent_id": "agent-a",
                    "description": "Touch auth middleware",
                    "reason": "Need to update auth flow",
                    "scope": ["src/auth"],
                    "status": "active",
                    "created_at": "2026-03-14T20:05:00Z",
                },
                "conflicts": "not-a-list",
            },
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.declare_intent(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                    description="Touch auth middleware",
                    reason="Need to update auth flow",
                    scope=["src/auth"],
                    source="daemon",
                )

        self.assertEqual(str(error.exception), "invalid_conflicts_payload")

    def test_runtime_renew_intent_rejects_invalid_intent_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "intent": "not-an-object"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.renew_intent(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                    lease_minutes=60,
                    source="daemon",
                )

        self.assertEqual(str(error.exception), "invalid_intent_payload")

    def test_runtime_resolve_conflict_rejects_invalid_conflict_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={"ok": True, "conflict": "not-an-object"},
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.resolve_conflict(
                    pathlib.Path("/tmp/loom.sock"),
                    conflict_id="conflict-1",
                    agent_id="agent-a",
                )

        self.assertEqual(str(error.exception), "invalid_conflict_payload")

    def test_runtime_publish_context_rejects_invalid_conflicts_payload(self) -> None:
        with patch(
            "loom.daemon.runtime._request",
            return_value={
                "ok": True,
                "context": {
                    "id": "context_01",
                    "agent_id": "agent-a",
                    "topic": "auth-interface",
                    "body": "Refresh token required.",
                    "scope": ["src/auth"],
                    "created_at": "2026-03-14T20:10:00Z",
                    "acknowledgments": [],
                },
                "conflicts": "not-a-list",
            },
        ):
            with self.assertRaises(RuntimeError) as error:
                daemon_runtime.publish_context(
                    pathlib.Path("/tmp/loom.sock"),
                    agent_id="agent-a",
                    topic="auth-interface",
                    body="Refresh token required.",
                    scope=["src/auth"],
                    source="daemon",
                )

        self.assertEqual(str(error.exception), "invalid_conflicts_payload")

    def test_request_handler_dispatches_mutating_requests_and_publishes_events(self) -> None:
        claim = ClaimRecord(
            id="claim_01",
            agent_id="agent-a",
            description="Refactor auth flow",
            scope=("src/auth",),
            status="active",
            created_at="2026-03-14T20:00:00Z",
        )
        event = EventRecord(
            sequence=8,
            id="event_01",
            type="claim.recorded",
            timestamp="2026-03-14T20:00:00Z",
            actor_id="agent-a",
            payload={"claim_id": "claim_01"},
        )
        store = Mock()
        store.latest_event_sequence.return_value = 7
        store.record_claim.return_value = (claim, ())
        store.list_events.return_value = (event,)

        handler = daemon_runtime._LoomRequestHandler.__new__(daemon_runtime._LoomRequestHandler)
        handler.server = Mock(store=store)
        handler.rfile = io.BytesIO(
            encode_message(
                {
                    "type": "claim.create",
                    "agent_id": "agent-a",
                    "description": "Refactor auth flow",
                    "scope": ["src/auth"],
                    "lease_minutes": 30,
                    "lease_policy": "yield",
                }
            )
        )
        handler.wfile = io.BytesIO()

        handler.handle()

        store.latest_event_sequence.assert_called_once()
        store.record_claim.assert_called_once_with(
            agent_id="agent-a",
            description="Refactor auth flow",
            scope=["src/auth"],
            source="daemon",
            lease_minutes=30,
            lease_policy="yield",
        )
        store.list_events.assert_called_once_with(
            after_sequence=7,
            ascending=True,
            limit=None,
        )
        handler.server.publish_events.assert_called_once_with((event,))

        response = read_message(io.BytesIO(handler.wfile.getvalue()))
        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response["ok"])
        self.assertEqual(response["claim"]["id"], "claim_01")
        self.assertEqual(response["claim"]["agent_id"], "agent-a")

    def test_request_handler_dispatches_claim_renew_requests(self) -> None:
        claim = ClaimRecord(
            id="claim_01",
            agent_id="agent-a",
            description="Refactor auth flow",
            scope=("src/auth",),
            status="active",
            created_at="2026-03-14T20:00:00Z",
            lease_expires_at="2026-03-14T21:30:00Z",
        )
        event = EventRecord(
            sequence=9,
            id="event_02",
            type="claim.renewed",
            timestamp="2026-03-14T20:30:00Z",
            actor_id="agent-a",
            payload={"claim_id": "claim_01"},
        )
        store = Mock()
        store.latest_event_sequence.return_value = 8
        store.renew_claim.return_value = claim
        store.list_events.return_value = (event,)

        handler = daemon_runtime._LoomRequestHandler.__new__(daemon_runtime._LoomRequestHandler)
        handler.server = Mock(store=store)
        handler.rfile = io.BytesIO(
            encode_message(
                {
                    "type": "claim.renew",
                    "agent_id": "agent-a",
                    "lease_minutes": 60,
                }
            )
        )
        handler.wfile = io.BytesIO()

        handler.handle()

        store.renew_claim.assert_called_once_with(
            agent_id="agent-a",
            lease_minutes=60,
            source="daemon",
        )
        response = read_message(io.BytesIO(handler.wfile.getvalue()))
        self.assertIsNotNone(response)
        assert response is not None
        self.assertTrue(response["ok"])
        self.assertEqual(response["claim"]["id"], "claim_01")

    def test_request_handler_rejects_unsupported_messages_via_dispatch(self) -> None:
        handler = daemon_runtime._LoomRequestHandler.__new__(daemon_runtime._LoomRequestHandler)
        handler.server = Mock(store=Mock())
        handler.rfile = io.BytesIO(encode_message({"type": "not.real"}))
        handler.wfile = io.BytesIO()

        handler.handle()

        response = read_message(io.BytesIO(handler.wfile.getvalue()))
        self.assertIsNotNone(response)
        assert response is not None
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"], "unsupported_message")
        self.assertEqual(response["error_code"], "unsupported_message")


if __name__ == "__main__":
    unittest.main()
