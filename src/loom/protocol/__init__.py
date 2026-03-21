from __future__ import annotations

import json
from typing import BinaryIO

from ..util import LEASE_POLICIES


LOCAL_PROTOCOL_NAME = "loom.local"
LOCAL_PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 1_048_576
LOCAL_PROTOCOL_TRANSPORT = "unix-domain-socket"
LOCAL_PROTOCOL_ENCODING = "json"
LOCAL_PROTOCOL_FRAMING = "newline-delimited"
LOCAL_PROTOCOL_OPERATIONS = (
    "ping",
    "protocol.describe",
    "claim.create",
    "claim.release",
    "claim.renew",
    "intent.declare",
    "intent.release",
    "intent.renew",
    "context.publish",
    "context.read",
    "context.get",
    "context.ack",
    "status.read",
    "agents.read",
    "agent.read",
    "inbox.read",
    "conflicts.read",
    "conflict.resolve",
    "events.read",
    "events.follow",
)
LOCAL_PROTOCOL_STREAMS = ("events",)
LOCAL_CONFLICT_KINDS = (
    "scope_overlap",
    "semantic_overlap",
    "contextual_dependency",
)
LOCAL_CONTEXT_ACK_STATUSES = ("read", "adapted")


class ProtocolError(RuntimeError):
    """Raised when a daemon protocol message is invalid or incompatible."""


class ProtocolResponseError(RuntimeError):
    """Raised when a compatible daemon response reports an application error."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.code = code
        self.detail = detail
        super().__init__(message)


def _string_schema(*, nullable: bool = False) -> dict[str, object]:
    if nullable:
        return {"type": ["string", "null"]}
    return {"type": "string"}


def _integer_schema(*, nullable: bool = False) -> dict[str, object]:
    if nullable:
        return {"type": ["integer", "null"]}
    return {"type": "integer"}


def _boolean_schema(*, nullable: bool = False) -> dict[str, object]:
    if nullable:
        return {"type": ["boolean", "null"]}
    return {"type": "boolean"}


def _enum_schema(values: tuple[str, ...]) -> dict[str, object]:
    return {"type": "string", "enum": list(values)}


def _nullable_enum_schema(values: tuple[str, ...]) -> dict[str, object]:
    return {"oneOf": [{"type": "null"}, _enum_schema(values)]}


def _const_schema(value: object) -> dict[str, object]:
    return {"const": value}


def _array_schema(items: dict[str, object]) -> dict[str, object]:
    return {"type": "array", "items": items}


def _ref_schema(name: str) -> dict[str, object]:
    return {"$ref": f"#/object_schemas/{name}"}


def _nullable_ref_schema(name: str) -> dict[str, object]:
    return {"oneOf": [{"type": "null"}, _ref_schema(name)]}


def _object_schema(
    properties: dict[str, dict[str, object]],
    *,
    required: tuple[str, ...] = (),
    additional_properties: bool | dict[str, object] = False,
) -> dict[str, object]:
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _success_response_schema(
    properties: dict[str, dict[str, object]] | None = None,
    *,
    required: tuple[str, ...] = (),
) -> dict[str, object]:
    combined_properties = {"ok": _const_schema(True)}
    if properties:
        combined_properties.update(properties)
    return _object_schema(
        combined_properties,
        required=("ok", *required),
    )


def _one_of_schema(*schemas: dict[str, object]) -> dict[str, object]:
    return {"oneOf": list(schemas)}


LOCAL_PROTOCOL_ERROR_SCHEMA = _object_schema(
    {
        "ok": _const_schema(False),
        "error": _string_schema(),
        "error_code": _string_schema(nullable=True),
        "detail": _string_schema(nullable=True),
    },
    required=("ok", "error"),
)


LOCAL_PROTOCOL_OBJECT_SCHEMAS = {
    "error_response": LOCAL_PROTOCOL_ERROR_SCHEMA,
    "claim": _object_schema(
        {
            "id": _string_schema(),
            "agent_id": _string_schema(),
            "description": _string_schema(),
            "scope": _array_schema(_string_schema()),
            "status": _enum_schema(("active", "superseded", "released")),
            "created_at": _string_schema(),
            "git_branch": _string_schema(nullable=True),
            "lease_expires_at": _string_schema(nullable=True),
            "lease_policy": _nullable_enum_schema(LEASE_POLICIES),
        },
        required=(
            "id",
            "agent_id",
            "description",
            "scope",
            "status",
            "created_at",
            "git_branch",
            "lease_expires_at",
            "lease_policy",
        ),
    ),
    "intent": _object_schema(
        {
            "id": _string_schema(),
            "agent_id": _string_schema(),
            "description": _string_schema(),
            "reason": _string_schema(),
            "scope": _array_schema(_string_schema()),
            "status": _enum_schema(("active", "superseded", "released")),
            "created_at": _string_schema(),
            "related_claim_id": _string_schema(nullable=True),
            "git_branch": _string_schema(nullable=True),
            "lease_expires_at": _string_schema(nullable=True),
            "lease_policy": _nullable_enum_schema(LEASE_POLICIES),
        },
        required=(
            "id",
            "agent_id",
            "description",
            "reason",
            "scope",
            "status",
            "created_at",
            "related_claim_id",
            "git_branch",
            "lease_expires_at",
            "lease_policy",
        ),
    ),
    "conflict": _object_schema(
        {
            "id": _string_schema(),
            "kind": _enum_schema(LOCAL_CONFLICT_KINDS),
            "severity": _string_schema(),
            "summary": _string_schema(),
            "object_type_a": _string_schema(),
            "object_id_a": _string_schema(),
            "object_type_b": _string_schema(),
            "object_id_b": _string_schema(),
            "scope": _array_schema(_string_schema()),
            "created_at": _string_schema(),
            "is_active": _boolean_schema(),
            "resolved_at": _string_schema(nullable=True),
            "resolved_by": _string_schema(nullable=True),
            "resolution_note": _string_schema(nullable=True),
        },
        required=(
            "id",
            "kind",
            "severity",
            "summary",
            "object_type_a",
            "object_id_a",
            "object_type_b",
            "object_id_b",
            "scope",
            "created_at",
            "is_active",
            "resolved_at",
            "resolved_by",
            "resolution_note",
        ),
    ),
    "context_ack": _object_schema(
        {
            "id": _string_schema(),
            "context_id": _string_schema(),
            "agent_id": _string_schema(),
            "status": _enum_schema(LOCAL_CONTEXT_ACK_STATUSES),
            "acknowledged_at": _string_schema(),
            "note": _string_schema(nullable=True),
        },
        required=(
            "id",
            "context_id",
            "agent_id",
            "status",
            "acknowledged_at",
            "note",
        ),
    ),
    "context": _object_schema(
        {
            "id": _string_schema(),
            "agent_id": _string_schema(),
            "topic": _string_schema(),
            "body": _string_schema(),
            "scope": _array_schema(_string_schema()),
            "created_at": _string_schema(),
            "related_claim_id": _string_schema(nullable=True),
            "related_intent_id": _string_schema(nullable=True),
            "git_branch": _string_schema(nullable=True),
            "acknowledgments": _array_schema(_ref_schema("context_ack")),
        },
        required=(
            "id",
            "agent_id",
            "topic",
            "body",
            "scope",
            "created_at",
            "related_claim_id",
            "related_intent_id",
            "git_branch",
            "acknowledgments",
        ),
    ),
    "event": _object_schema(
        {
            "sequence": _integer_schema(),
            "id": _string_schema(),
            "type": _string_schema(),
            "timestamp": _string_schema(),
            "actor_id": _string_schema(),
            "payload": _object_schema(
                {},
                additional_properties=_string_schema(),
            ),
        },
        required=("sequence", "id", "type", "timestamp", "actor_id", "payload"),
    ),
    "status_snapshot": _object_schema(
        {
            "claims": _array_schema(_ref_schema("claim")),
            "intents": _array_schema(_ref_schema("intent")),
            "context": _array_schema(_ref_schema("context")),
            "conflicts": _array_schema(_ref_schema("conflict")),
        },
        required=("claims", "intents", "context", "conflicts"),
    ),
    "agent_snapshot": _object_schema(
        {
            "agent_id": _string_schema(),
            "claim": _nullable_ref_schema("claim"),
            "intent": _nullable_ref_schema("intent"),
            "published_context": _array_schema(_ref_schema("context")),
            "incoming_context": _array_schema(_ref_schema("context")),
            "conflicts": _array_schema(_ref_schema("conflict")),
            "events": _array_schema(_ref_schema("event")),
        },
        required=(
            "agent_id",
            "claim",
            "intent",
            "published_context",
            "incoming_context",
            "conflicts",
            "events",
        ),
    ),
    "agent_presence": _object_schema(
        {
            "agent_id": _string_schema(),
            "source": _string_schema(),
            "created_at": _string_schema(),
            "last_seen_at": _string_schema(),
            "claim": _nullable_ref_schema("claim"),
            "intent": _nullable_ref_schema("intent"),
        },
        required=(
            "agent_id",
            "source",
            "created_at",
            "last_seen_at",
            "claim",
            "intent",
        ),
    ),
    "inbox_snapshot": _object_schema(
        {
            "agent_id": _string_schema(),
            "pending_context": _array_schema(_ref_schema("context")),
            "conflicts": _array_schema(_ref_schema("conflict")),
            "events": _array_schema(_ref_schema("event")),
        },
        required=("agent_id", "pending_context", "conflicts", "events"),
    ),
}

LOCAL_PROTOCOL_MESSAGE_ENVELOPE = {
    "request": _object_schema(
        {
            "protocol": _const_schema(LOCAL_PROTOCOL_NAME),
            "protocol_version": _const_schema(LOCAL_PROTOCOL_VERSION),
            "type": _string_schema(),
        },
        required=("protocol", "protocol_version", "type"),
        additional_properties=True,
    ),
    "response": _object_schema(
        {
            "protocol": _const_schema(LOCAL_PROTOCOL_NAME),
            "protocol_version": _const_schema(LOCAL_PROTOCOL_VERSION),
            "ok": _boolean_schema(),
        },
        required=("protocol", "protocol_version", "ok"),
        additional_properties=True,
    ),
}

LOCAL_PROTOCOL_OPERATION_SCHEMAS = {
    "ping": {
        "request": _object_schema(
            {"type": _const_schema("ping")},
            required=("type",),
        ),
        "response": _success_response_schema(
            {
                "service": _string_schema(),
                "version": _string_schema(),
                "protocol": _string_schema(),
                "protocol_version": _integer_schema(),
                "timestamp": _string_schema(),
            },
            required=("service", "version", "protocol", "protocol_version", "timestamp"),
        ),
    },
    "protocol.describe": {
        "request": _object_schema(
            {"type": _const_schema("protocol.describe")},
            required=("type",),
        ),
        "response": _success_response_schema(
            {
                "protocol": _object_schema(
                    {
                        "name": _string_schema(),
                        "version": _integer_schema(),
                        "transport": _string_schema(),
                        "encoding": _string_schema(),
                        "framing": _string_schema(),
                        "max_message_bytes": _integer_schema(),
                        "operations": _array_schema(_string_schema()),
                        "streams": _array_schema(_string_schema()),
                        "conflict_kinds": _array_schema(_string_schema()),
                        "context_ack_statuses": _array_schema(_string_schema()),
                        "message_envelope": _object_schema({}, additional_properties=True),
                        "error_response": _ref_schema("error_response"),
                        "object_schemas": _object_schema({}, additional_properties=True),
                        "operation_schemas": _object_schema({}, additional_properties=True),
                    },
                    required=(
                        "name",
                        "version",
                        "transport",
                        "encoding",
                        "framing",
                        "max_message_bytes",
                        "operations",
                        "streams",
                        "conflict_kinds",
                        "context_ack_statuses",
                        "message_envelope",
                        "error_response",
                        "object_schemas",
                        "operation_schemas",
                    ),
                )
            },
            required=("protocol",),
        ),
    },
    "claim.create": {
        "request": _object_schema(
            {
                "type": _const_schema("claim.create"),
                "agent_id": _string_schema(),
                "description": _string_schema(),
                "scope": _array_schema(_string_schema()),
                "source": _string_schema(),
                "lease_minutes": _integer_schema(nullable=True),
                "lease_policy": _nullable_enum_schema(LEASE_POLICIES),
            },
            required=("type", "agent_id", "description", "scope"),
        ),
        "response": _success_response_schema(
            {
                "claim": _ref_schema("claim"),
                "conflicts": _array_schema(_ref_schema("conflict")),
            },
            required=("claim", "conflicts"),
        ),
    },
    "claim.release": {
        "request": _object_schema(
            {
                "type": _const_schema("claim.release"),
                "agent_id": _string_schema(),
            },
            required=("type", "agent_id"),
        ),
        "response": _success_response_schema(
            {"claim": _nullable_ref_schema("claim")},
            required=("claim",),
        ),
    },
    "claim.renew": {
        "request": _object_schema(
            {
                "type": _const_schema("claim.renew"),
                "agent_id": _string_schema(),
                "lease_minutes": _integer_schema(),
                "source": _string_schema(),
            },
            required=("type", "agent_id", "lease_minutes"),
        ),
        "response": _success_response_schema(
            {"claim": _nullable_ref_schema("claim")},
            required=("claim",),
        ),
    },
    "intent.declare": {
        "request": _object_schema(
            {
                "type": _const_schema("intent.declare"),
                "agent_id": _string_schema(),
                "description": _string_schema(),
                "reason": _string_schema(),
                "scope": _array_schema(_string_schema()),
                "source": _string_schema(),
                "lease_minutes": _integer_schema(nullable=True),
                "lease_policy": _nullable_enum_schema(LEASE_POLICIES),
            },
            required=("type", "agent_id", "description", "reason", "scope"),
        ),
        "response": _success_response_schema(
            {
                "intent": _ref_schema("intent"),
                "conflicts": _array_schema(_ref_schema("conflict")),
            },
            required=("intent", "conflicts"),
        ),
    },
    "intent.release": {
        "request": _object_schema(
            {
                "type": _const_schema("intent.release"),
                "agent_id": _string_schema(),
            },
            required=("type", "agent_id"),
        ),
        "response": _success_response_schema(
            {"intent": _nullable_ref_schema("intent")},
            required=("intent",),
        ),
    },
    "intent.renew": {
        "request": _object_schema(
            {
                "type": _const_schema("intent.renew"),
                "agent_id": _string_schema(),
                "lease_minutes": _integer_schema(),
                "source": _string_schema(),
            },
            required=("type", "agent_id", "lease_minutes"),
        ),
        "response": _success_response_schema(
            {"intent": _nullable_ref_schema("intent")},
            required=("intent",),
        ),
    },
    "context.publish": {
        "request": _object_schema(
            {
                "type": _const_schema("context.publish"),
                "agent_id": _string_schema(),
                "topic": _string_schema(),
                "body": _string_schema(),
                "scope": _array_schema(_string_schema()),
                "source": _string_schema(),
            },
            required=("type", "agent_id", "topic", "body", "scope"),
        ),
        "response": _success_response_schema(
            {
                "context": _ref_schema("context"),
                "conflicts": _array_schema(_ref_schema("conflict")),
            },
            required=("context", "conflicts"),
        ),
    },
    "context.read": {
        "request": _object_schema(
            {
                "type": _const_schema("context.read"),
                "topic": _string_schema(),
                "agent_id": _string_schema(),
                "scope": _array_schema(_string_schema()),
                "limit": _integer_schema(),
            },
            required=("type",),
        ),
        "response": _success_response_schema(
            {"context": _array_schema(_ref_schema("context"))},
            required=("context",),
        ),
    },
    "context.get": {
        "request": _object_schema(
            {
                "type": _const_schema("context.get"),
                "context_id": _string_schema(),
            },
            required=("type", "context_id"),
        ),
        "response": _success_response_schema(
            {"context": _nullable_ref_schema("context")},
            required=("context",),
        ),
    },
    "context.ack": {
        "request": _object_schema(
            {
                "type": _const_schema("context.ack"),
                "context_id": _string_schema(),
                "agent_id": _string_schema(),
                "status": _enum_schema(LOCAL_CONTEXT_ACK_STATUSES),
                "note": _string_schema(),
            },
            required=("type", "context_id", "agent_id", "status"),
        ),
        "response": _success_response_schema(
            {"ack": _nullable_ref_schema("context_ack")},
            required=("ack",),
        ),
    },
    "status.read": {
        "request": _object_schema(
            {"type": _const_schema("status.read")},
            required=("type",),
        ),
        "response": _success_response_schema(
            {
                "claims": _array_schema(_ref_schema("claim")),
                "intents": _array_schema(_ref_schema("intent")),
                "context": _array_schema(_ref_schema("context")),
                "conflicts": _array_schema(_ref_schema("conflict")),
            },
            required=("claims", "intents", "context", "conflicts"),
        ),
    },
    "agents.read": {
        "request": _object_schema(
            {
                "type": _const_schema("agents.read"),
                "limit": _integer_schema(),
            },
            required=("type",),
        ),
        "response": _success_response_schema(
            {"agents": _array_schema(_ref_schema("agent_presence"))},
            required=("agents",),
        ),
    },
    "agent.read": {
        "request": _object_schema(
            {
                "type": _const_schema("agent.read"),
                "agent_id": _string_schema(),
                "context_limit": _integer_schema(),
                "event_limit": _integer_schema(),
            },
            required=("type", "agent_id"),
        ),
        "response": _success_response_schema(
            {"agent": _ref_schema("agent_snapshot")},
            required=("agent",),
        ),
    },
    "inbox.read": {
        "request": _object_schema(
            {
                "type": _const_schema("inbox.read"),
                "agent_id": _string_schema(),
                "context_limit": _integer_schema(),
                "event_limit": _integer_schema(),
            },
            required=("type", "agent_id"),
        ),
        "response": _success_response_schema(
            {"inbox": _ref_schema("inbox_snapshot")},
            required=("inbox",),
        ),
    },
    "conflicts.read": {
        "request": _object_schema(
            {
                "type": _const_schema("conflicts.read"),
                "include_resolved": _boolean_schema(),
            },
            required=("type",),
        ),
        "response": _success_response_schema(
            {"conflicts": _array_schema(_ref_schema("conflict"))},
            required=("conflicts",),
        ),
    },
    "conflict.resolve": {
        "request": _object_schema(
            {
                "type": _const_schema("conflict.resolve"),
                "conflict_id": _string_schema(),
                "agent_id": _string_schema(),
                "resolution_note": _string_schema(),
            },
            required=("type", "conflict_id", "agent_id"),
        ),
        "response": _success_response_schema(
            {"conflict": _nullable_ref_schema("conflict")},
            required=("conflict",),
        ),
    },
    "events.read": {
        "request": _object_schema(
            {
                "type": _const_schema("events.read"),
                "limit": _integer_schema(),
                "event_type": _string_schema(),
                "after_sequence": _integer_schema(),
                "ascending": _boolean_schema(),
            },
            required=("type",),
        ),
        "response": _success_response_schema(
            {"events": _array_schema(_ref_schema("event"))},
            required=("events",),
        ),
    },
    "events.follow": {
        "request": _object_schema(
            {
                "type": _const_schema("events.follow"),
                "event_type": _string_schema(),
                "after_sequence": _integer_schema(),
            },
            required=("type",),
        ),
        "response": _success_response_schema(
            {"stream": _const_schema("events")},
            required=("stream",),
        ),
        "stream_response": _one_of_schema(
            _success_response_schema(
                {"event": _ref_schema("event")},
                required=("event",),
            ),
            _success_response_schema(
                {"heartbeat": _const_schema("events")},
                required=("heartbeat",),
            ),
        ),
    },
}


def describe_local_protocol() -> dict[str, object]:
    return {
        "name": LOCAL_PROTOCOL_NAME,
        "version": LOCAL_PROTOCOL_VERSION,
        "transport": LOCAL_PROTOCOL_TRANSPORT,
        "encoding": LOCAL_PROTOCOL_ENCODING,
        "framing": LOCAL_PROTOCOL_FRAMING,
        "max_message_bytes": MAX_MESSAGE_BYTES,
        "operations": list(LOCAL_PROTOCOL_OPERATIONS),
        "streams": list(LOCAL_PROTOCOL_STREAMS),
        "conflict_kinds": list(LOCAL_CONFLICT_KINDS),
        "context_ack_statuses": list(LOCAL_CONTEXT_ACK_STATUSES),
        "message_envelope": LOCAL_PROTOCOL_MESSAGE_ENVELOPE,
        "error_response": LOCAL_PROTOCOL_ERROR_SCHEMA,
        "object_schemas": LOCAL_PROTOCOL_OBJECT_SCHEMAS,
        "operation_schemas": LOCAL_PROTOCOL_OPERATION_SCHEMAS,
    }


def encode_message(payload: dict[str, object]) -> bytes:
    envelope = {
        "protocol": LOCAL_PROTOCOL_NAME,
        "protocol_version": LOCAL_PROTOCOL_VERSION,
        **payload,
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8") + b"\n"


def read_message(
    stream: BinaryIO,
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> dict[str, object] | None:
    line = stream.readline(max_bytes + 1)
    if not line:
        return None
    if len(line) > max_bytes and not line.endswith(b"\n"):
        raise ProtocolError("message_too_large")
    if not line.endswith(b"\n"):
        raise ProtocolError("truncated_message")

    try:
        payload = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError as error:
        raise ProtocolError("invalid_json") from error
    if not isinstance(payload, dict):
        raise ProtocolError("invalid_message")
    return {str(key): value for key, value in payload.items()}


def require_compatible_message(message: dict[str, object]) -> None:
    protocol = message.get("protocol")
    version = message.get("protocol_version")
    if protocol != LOCAL_PROTOCOL_NAME:
        raise ProtocolError("unsupported_protocol")
    if version != LOCAL_PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol_version")


def success_payload(**payload: object) -> dict[str, object]:
    return {"ok": True, **payload}


def error_payload(
    error: str,
    *,
    error_code: str | None = None,
    detail: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"ok": False, "error": error}
    if error_code:
        payload["error_code"] = error_code
    if detail:
        payload["detail"] = detail
    return payload
