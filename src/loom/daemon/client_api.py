from __future__ import annotations

import socket
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import BinaryIO

from ..local_store import (
    AgentPresenceRecord,
    AgentSnapshot,
    ClaimRecord,
    ConflictRecord,
    ContextAckRecord,
    ContextRecord,
    EventRecord,
    InboxSnapshot,
    IntentRecord,
    StatusSnapshot,
)
from ..protocol import ProtocolError, encode_message
from ..wire import (
    agent_presence_from_wire as _agent_presence_from_wire,
    agent_snapshot_from_wire as _agent_snapshot_from_wire,
    claim_from_wire as _claim_from_wire,
    conflict_from_wire as _conflict_from_wire,
    context_ack_from_wire as _context_ack_from_wire,
    context_from_wire as _context_from_wire,
    event_from_wire as _event_from_wire,
    inbox_snapshot_from_wire as _inbox_snapshot_from_wire,
    intent_from_wire as _intent_from_wire,
    status_snapshot_from_wire as _status_snapshot_from_wire,
)

FOLLOW_STREAM_IDLE_TIMEOUT_SECONDS = 6.0
FOLLOW_STREAM_HEARTBEAT = "events"


def read_events(
    socket_path: Path,
    *,
    limit: int = 20,
    event_type: str | None = None,
    after_sequence: int | None = None,
    ascending: bool = False,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> tuple[EventRecord, ...]:
    response = request_fn(
        socket_path,
        payload={
            "type": "events.read",
            "limit": limit,
            "event_type": event_type,
            "after_sequence": after_sequence,
            "ascending": ascending,
        },
        timeout=timeout,
    )
    events = _response_list(response, "events", error="invalid_events_payload")
    return tuple(_event_from_wire(event) for event in events)


def follow_events(
    socket_path: Path,
    *,
    event_type: str | None = None,
    after_sequence: int | None = None,
    timeout: float = 0.5,
    socket_factory: Callable[[int, int], socket.socket],
    read_response_message_fn: Callable[[BinaryIO], dict[str, object] | None],
) -> Iterator[EventRecord]:
    client: socket.socket | None = None
    try:
        client = socket_factory(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(
            encode_message(
                {
                    "type": "events.follow",
                    "event_type": event_type,
                    "after_sequence": after_sequence,
                }
            )
        )
        with client.makefile("rb") as reader:
            data = read_response_message_fn(reader)
            if data is None:
                raise RuntimeError("daemon_closed_connection")
            if data.get("stream") != "events":
                raise RuntimeError("invalid_follow_payload")

            client.settimeout(FOLLOW_STREAM_IDLE_TIMEOUT_SECONDS)
            while True:
                try:
                    payload = read_response_message_fn(reader)
                except TimeoutError as error:
                    raise RuntimeError("follow_timeout") from error
                if payload is None:
                    break
                event = _follow_event_from_payload(payload)
                if event is None:
                    continue
                yield event
    except OSError as error:
        raise RuntimeError("socket_unavailable") from error
    except ProtocolError as error:
        raise RuntimeError(str(error)) from error
    finally:
        if client is not None:
            client.close()


def describe_protocol(
    socket_path: Path,
    *,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> dict[str, object]:
    response = request_fn(
        socket_path,
        payload={"type": "protocol.describe"},
        timeout=timeout,
    )
    protocol = response.get("protocol")
    if not isinstance(protocol, dict):
        raise RuntimeError("invalid_protocol_payload")
    return {str(key): value for key, value in protocol.items()}


def read_agents(
    socket_path: Path,
    *,
    limit: int = 20,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> tuple[AgentPresenceRecord, ...]:
    response = request_fn(
        socket_path,
        payload={
            "type": "agents.read",
            "limit": limit,
        },
        timeout=timeout,
    )
    agents = _response_list(response, "agents", error="invalid_agents_payload")
    return tuple(_agent_presence_from_wire(item) for item in agents)


def create_claim(
    socket_path: Path,
    *,
    agent_id: str,
    description: str,
    scope: list[str] | tuple[str, ...],
    source: str,
    lease_minutes: int | None = None,
    lease_policy: str | None = None,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> tuple[ClaimRecord, tuple[ConflictRecord, ...]]:
    response = request_fn(
        socket_path,
        payload={
            "type": "claim.create",
            "agent_id": agent_id,
            "description": description,
            "scope": list(scope),
            "source": source,
            "lease_minutes": lease_minutes,
            "lease_policy": lease_policy,
        },
        timeout=timeout,
    )
    claim = _response_required_object(response, "claim", error="invalid_claim_payload")
    conflicts = _response_list(response, "conflicts", error="invalid_conflicts_payload")
    return (
        _claim_from_wire(claim),
        tuple(_conflict_from_wire(item) for item in conflicts),
    )


def release_claim(
    socket_path: Path,
    *,
    agent_id: str,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> ClaimRecord | None:
    response = request_fn(
        socket_path,
        payload={
            "type": "claim.release",
            "agent_id": agent_id,
        },
        timeout=timeout,
    )
    claim = _response_optional_object(response, "claim", error="invalid_claim_payload")
    if claim is None:
        return None
    return _claim_from_wire(claim)


def renew_claim(
    socket_path: Path,
    *,
    agent_id: str,
    lease_minutes: int,
    source: str,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> ClaimRecord | None:
    response = request_fn(
        socket_path,
        payload={
            "type": "claim.renew",
            "agent_id": agent_id,
            "lease_minutes": lease_minutes,
            "source": source,
        },
        timeout=timeout,
    )
    claim = _response_optional_object(response, "claim", error="invalid_claim_payload")
    if claim is None:
        return None
    return _claim_from_wire(claim)


def declare_intent(
    socket_path: Path,
    *,
    agent_id: str,
    description: str,
    reason: str,
    scope: list[str] | tuple[str, ...],
    source: str,
    lease_minutes: int | None = None,
    lease_policy: str | None = None,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> tuple[IntentRecord, tuple[ConflictRecord, ...]]:
    response = request_fn(
        socket_path,
        payload={
            "type": "intent.declare",
            "agent_id": agent_id,
            "description": description,
            "reason": reason,
            "scope": list(scope),
            "source": source,
            "lease_minutes": lease_minutes,
            "lease_policy": lease_policy,
        },
        timeout=timeout,
    )
    intent = _response_required_object(response, "intent", error="invalid_intent_payload")
    conflicts = _response_list(response, "conflicts", error="invalid_conflicts_payload")
    return (
        _intent_from_wire(intent),
        tuple(_conflict_from_wire(item) for item in conflicts),
    )


def release_intent(
    socket_path: Path,
    *,
    agent_id: str,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> IntentRecord | None:
    response = request_fn(
        socket_path,
        payload={
            "type": "intent.release",
            "agent_id": agent_id,
        },
        timeout=timeout,
    )
    intent = _response_optional_object(response, "intent", error="invalid_intent_payload")
    if intent is None:
        return None
    return _intent_from_wire(intent)


def renew_intent(
    socket_path: Path,
    *,
    agent_id: str,
    lease_minutes: int,
    source: str,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> IntentRecord | None:
    response = request_fn(
        socket_path,
        payload={
            "type": "intent.renew",
            "agent_id": agent_id,
            "lease_minutes": lease_minutes,
            "source": source,
        },
        timeout=timeout,
    )
    intent = _response_optional_object(response, "intent", error="invalid_intent_payload")
    if intent is None:
        return None
    return _intent_from_wire(intent)


def publish_context(
    socket_path: Path,
    *,
    agent_id: str,
    topic: str,
    body: str,
    scope: list[str] | tuple[str, ...],
    source: str,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> tuple[ContextRecord, tuple[ConflictRecord, ...]]:
    response = request_fn(
        socket_path,
        payload={
            "type": "context.publish",
            "agent_id": agent_id,
            "topic": topic,
            "body": body,
            "scope": list(scope),
            "source": source,
        },
        timeout=timeout,
    )
    context = _response_required_object(response, "context", error="invalid_context_payload")
    conflicts = _response_list(response, "conflicts", error="invalid_conflicts_payload")
    return (
        _context_from_wire(context),
        tuple(_conflict_from_wire(item) for item in conflicts),
    )


def read_context_entries(
    socket_path: Path,
    *,
    topic: str | None = None,
    agent_id: str | None = None,
    scope: list[str] | tuple[str, ...] = (),
    limit: int = 10,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> tuple[ContextRecord, ...]:
    response = request_fn(
        socket_path,
        payload={
            "type": "context.read",
            "topic": topic,
            "agent_id": agent_id,
            "scope": list(scope),
            "limit": limit,
        },
        timeout=timeout,
    )
    context = _response_list(response, "context", error="invalid_context_payload")
    return tuple(_context_from_wire(item) for item in context)


def get_context_entry(
    socket_path: Path,
    *,
    context_id: str,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> ContextRecord | None:
    response = request_fn(
        socket_path,
        payload={
            "type": "context.get",
            "context_id": context_id,
        },
        timeout=timeout,
    )
    context = _response_optional_object(response, "context", error="invalid_context_payload")
    if context is None:
        return None
    return _context_from_wire(context)


def acknowledge_context(
    socket_path: Path,
    *,
    context_id: str,
    agent_id: str,
    status: str,
    note: str | None = None,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> ContextAckRecord | None:
    response = request_fn(
        socket_path,
        payload={
            "type": "context.ack",
            "context_id": context_id,
            "agent_id": agent_id,
            "status": status,
            "note": note,
        },
        timeout=timeout,
    )
    ack = _response_optional_object(response, "ack", error="invalid_context_ack_payload")
    if ack is None:
        return None
    return _context_ack_from_wire(ack)


def read_status(
    socket_path: Path,
    *,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> StatusSnapshot:
    response = request_fn(
        socket_path,
        payload={"type": "status.read"},
        timeout=timeout,
    )
    for key in ("claims", "intents", "context", "conflicts"):
        _response_list(response, key, error="invalid_status_payload")
    return _status_snapshot_from_wire(response)


def read_agent_snapshot(
    socket_path: Path,
    *,
    agent_id: str,
    context_limit: int = 5,
    event_limit: int = 10,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> AgentSnapshot:
    response = request_fn(
        socket_path,
        payload={
            "type": "agent.read",
            "agent_id": agent_id,
            "context_limit": context_limit,
            "event_limit": event_limit,
        },
        timeout=timeout,
    )
    agent = _response_object(response, "agent", error="invalid_agent_payload")
    return _agent_snapshot_from_wire(agent)


def read_inbox_snapshot(
    socket_path: Path,
    *,
    agent_id: str,
    context_limit: int = 5,
    event_limit: int = 10,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> InboxSnapshot:
    response = request_fn(
        socket_path,
        payload={
            "type": "inbox.read",
            "agent_id": agent_id,
            "context_limit": context_limit,
            "event_limit": event_limit,
        },
        timeout=timeout,
    )
    inbox = _response_object(response, "inbox", error="invalid_inbox_payload")
    return _inbox_snapshot_from_wire(inbox)


def read_conflicts(
    socket_path: Path,
    *,
    include_resolved: bool = False,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> tuple[ConflictRecord, ...]:
    response = request_fn(
        socket_path,
        payload={
            "type": "conflicts.read",
            "include_resolved": include_resolved,
        },
        timeout=timeout,
    )
    conflicts = _response_list(response, "conflicts", error="invalid_conflicts_payload")
    return tuple(_conflict_from_wire(item) for item in conflicts)


def resolve_conflict(
    socket_path: Path,
    *,
    conflict_id: str,
    agent_id: str,
    resolution_note: str | None = None,
    timeout: float = 0.5,
    request_fn: Callable[..., dict[str, object]],
) -> ConflictRecord | None:
    response = request_fn(
        socket_path,
        payload={
            "type": "conflict.resolve",
            "conflict_id": conflict_id,
            "agent_id": agent_id,
            "resolution_note": resolution_note,
        },
        timeout=timeout,
    )
    conflict = _response_optional_object(response, "conflict", error="invalid_conflict_payload")
    if conflict is None:
        return None
    return _conflict_from_wire(conflict)


def _response_list(
    payload: dict[str, object],
    key: str,
    *,
    error: str,
) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise RuntimeError(error)
    return value


def _response_object(
    payload: dict[str, object],
    key: str,
    *,
    error: str,
) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise RuntimeError(error)
    return value


def _response_required_object(
    payload: dict[str, object],
    key: str,
    *,
    error: str,
) -> dict[str, object]:
    return _response_object(payload, key, error=error)


def _response_optional_object(
    payload: dict[str, object],
    key: str,
    *,
    error: str,
) -> dict[str, object] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(error)
    return value


def _follow_event_from_payload(payload: dict[str, object]) -> EventRecord | None:
    heartbeat = payload.get("heartbeat")
    if heartbeat is not None:
        if heartbeat == FOLLOW_STREAM_HEARTBEAT:
            return None
        raise RuntimeError("invalid_follow_payload")

    event = _response_required_object(payload, "event", error="invalid_follow_payload")
    try:
        return _event_from_wire(event)
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        raise RuntimeError("invalid_follow_payload") from error
