from __future__ import annotations

import contextlib
import io
import pathlib
import socket
import sys
import unittest
from unittest.mock import Mock, patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.daemon import client_api  # noqa: E402
from loom.local_store import EventRecord  # noqa: E402
from loom.protocol import ProtocolError  # noqa: E402


class ClientApiTest(unittest.TestCase):
    def test_read_events_passes_expected_request_payload_and_decodes_results(self) -> None:
        event_payload = {
            "sequence": 3,
            "id": "event_3",
            "type": "claim.recorded",
            "timestamp": "2026-03-18T12:00:00Z",
            "actor_id": "agent-a",
            "payload": {"claim_id": "claim_123"},
        }
        request_fn = Mock(return_value={"events": [event_payload]})
        decoded_event = EventRecord(
            sequence=3,
            id="event_3",
            type="claim.recorded",
            timestamp="2026-03-18T12:00:00Z",
            actor_id="agent-a",
            payload={"claim_id": "claim_123"},
        )

        with patch("loom.daemon.client_api._event_from_wire", return_value=decoded_event) as decode_mock:
            events = client_api.read_events(
                pathlib.Path("/tmp/loom.sock"),
                limit=5,
                event_type="claim.recorded",
                after_sequence=2,
                ascending=True,
                request_fn=request_fn,
            )

        request_fn.assert_called_once_with(
            pathlib.Path("/tmp/loom.sock"),
            payload={
                "type": "events.read",
                "limit": 5,
                "event_type": "claim.recorded",
                "after_sequence": 2,
                "ascending": True,
            },
            timeout=0.5,
        )
        decode_mock.assert_called_once_with(event_payload)
        self.assertEqual(events, (decoded_event,))

    def test_create_claim_decodes_claim_and_conflicts(self) -> None:
        claim_payload = {"id": "claim_123"}
        conflict_payload = {"id": "conflict_123"}
        request_fn = Mock(return_value={"claim": claim_payload, "conflicts": [conflict_payload]})

        with (
            patch("loom.daemon.client_api._claim_from_wire", return_value="decoded-claim") as claim_mock,
            patch("loom.daemon.client_api._conflict_from_wire", return_value="decoded-conflict") as conflict_mock,
        ):
            claim, conflicts = client_api.create_claim(
                pathlib.Path("/tmp/loom.sock"),
                agent_id="agent-a",
                description="Claim work",
                scope=("src/api.py",),
                source="cli",
                lease_minutes=30,
                lease_policy="yield",
                request_fn=request_fn,
            )

        request_fn.assert_called_once_with(
            pathlib.Path("/tmp/loom.sock"),
            payload={
                "type": "claim.create",
                "agent_id": "agent-a",
                "description": "Claim work",
                "scope": ["src/api.py"],
                "source": "cli",
                "lease_minutes": 30,
                "lease_policy": "yield",
            },
            timeout=0.5,
        )
        claim_mock.assert_called_once_with(claim_payload)
        conflict_mock.assert_called_once_with(conflict_payload)
        self.assertEqual(claim, "decoded-claim")
        self.assertEqual(conflicts, ("decoded-conflict",))

    def test_read_status_validates_all_lists_before_decoding_snapshot(self) -> None:
        response = {
            "claims": [],
            "intents": [],
            "context": [],
            "conflicts": [],
        }
        request_fn = Mock(return_value=response)

        with patch(
            "loom.daemon.client_api._status_snapshot_from_wire",
            return_value="decoded-status",
        ) as decode_mock:
            status = client_api.read_status(
                pathlib.Path("/tmp/loom.sock"),
                request_fn=request_fn,
            )

        decode_mock.assert_called_once_with(response)
        self.assertEqual(status, "decoded-status")

    def test_follow_event_from_payload_handles_heartbeat_and_invalid_payloads(self) -> None:
        self.assertIsNone(client_api._follow_event_from_payload({"heartbeat": "events"}))
        with self.assertRaisesRegex(RuntimeError, "invalid_follow_payload"):
            client_api._follow_event_from_payload({"heartbeat": "other"})
        with self.assertRaisesRegex(RuntimeError, "invalid_follow_payload"):
            client_api._follow_event_from_payload({"event": {"id": "event_missing_fields"}})

    def test_follow_events_times_out_after_successful_handshake(self) -> None:
        fake_socket = Mock()
        fake_socket.makefile.return_value = contextlib.nullcontext(io.BytesIO())
        socket_factory = Mock(return_value=fake_socket)
        read_response = Mock(
            side_effect=(
                {"stream": "events"},
                TimeoutError("idle"),
            )
        )

        with self.assertRaisesRegex(RuntimeError, "follow_timeout"):
            tuple(
                client_api.follow_events(
                    pathlib.Path("/tmp/loom.sock"),
                    socket_factory=socket_factory,
                    read_response_message_fn=read_response,
                )
            )

        fake_socket.connect.assert_called_once_with("/tmp/loom.sock")
        fake_socket.settimeout.assert_any_call(0.5)
        fake_socket.settimeout.assert_any_call(client_api.FOLLOW_STREAM_IDLE_TIMEOUT_SECONDS)
        fake_socket.close.assert_called_once()

    def test_follow_events_maps_protocol_and_socket_errors_to_runtime_errors(self) -> None:
        fake_socket = Mock()
        fake_socket.makefile.return_value = contextlib.nullcontext(io.BytesIO())
        socket_factory = Mock(return_value=fake_socket)

        with self.assertRaisesRegex(RuntimeError, "unsupported_message"):
            tuple(
                client_api.follow_events(
                    pathlib.Path("/tmp/loom.sock"),
                    socket_factory=socket_factory,
                    read_response_message_fn=Mock(side_effect=ProtocolError("unsupported_message")),
                )
            )

        socket_factory = Mock(side_effect=OSError("socket down"))
        with self.assertRaisesRegex(RuntimeError, "socket_unavailable"):
            tuple(
                client_api.follow_events(
                    pathlib.Path("/tmp/loom.sock"),
                    socket_factory=socket_factory,
                    read_response_message_fn=Mock(),
                )
            )

    def test_response_optional_object_returns_none_for_missing_value(self) -> None:
        self.assertIsNone(
            client_api._response_optional_object(
                {},
                "claim",
                error="invalid_claim_payload",
            )
        )
        with self.assertRaisesRegex(RuntimeError, "invalid_claim_payload"):
            client_api._response_optional_object(
                {"claim": []},
                "claim",
                error="invalid_claim_payload",
            )


if __name__ == "__main__":
    unittest.main()
