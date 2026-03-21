from __future__ import annotations

from .local_store import (
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


def agent_presence_to_wire(presence: AgentPresenceRecord) -> dict[str, object]:
    return {
        "agent_id": presence.agent_id,
        "source": presence.source,
        "created_at": presence.created_at,
        "last_seen_at": presence.last_seen_at,
        "claim": None if presence.claim is None else claim_to_wire(presence.claim),
        "intent": None if presence.intent is None else intent_to_wire(presence.intent),
    }


def agent_presence_from_wire(payload: object) -> AgentPresenceRecord:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_agent_presence_payload")
    try:
        return AgentPresenceRecord(
            agent_id=str(payload["agent_id"]),
            source=str(payload["source"]),
            created_at=str(payload["created_at"]),
            last_seen_at=str(payload["last_seen_at"]),
            claim=None if payload.get("claim") is None else claim_from_wire(payload["claim"]),
            intent=None if payload.get("intent") is None else intent_from_wire(payload["intent"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_agent_presence_payload") from error


def status_snapshot_to_wire(snapshot: StatusSnapshot) -> dict[str, object]:
    return {
        "claims": [claim_to_wire(item) for item in snapshot.claims],
        "intents": [intent_to_wire(item) for item in snapshot.intents],
        "context": [context_to_wire(item) for item in snapshot.context],
        "conflicts": [conflict_to_wire(item) for item in snapshot.conflicts],
    }


def status_snapshot_from_wire(payload: object) -> StatusSnapshot:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_status_snapshot_payload")
    try:
        return StatusSnapshot(
            claims=tuple(claim_from_wire(item) for item in _object_list(payload["claims"])),
            intents=tuple(intent_from_wire(item) for item in _object_list(payload["intents"])),
            context=tuple(context_from_wire(item) for item in _object_list(payload["context"])),
            conflicts=tuple(
                conflict_from_wire(item)
                for item in _object_list(payload["conflicts"])
            ),
        )
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        raise RuntimeError("invalid_status_snapshot_payload") from error


def event_to_wire(event: EventRecord) -> dict[str, object]:
    return {
        "sequence": event.sequence,
        "id": event.id,
        "type": event.type,
        "timestamp": event.timestamp,
        "actor_id": event.actor_id,
        "payload": event.payload,
    }


def event_from_wire(payload: object) -> EventRecord:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_event_payload")
    try:
        raw_payload = payload.get("payload", {})
        if not isinstance(raw_payload, dict):
            raw_payload = {}
        return EventRecord(
            sequence=int(payload["sequence"]),
            id=str(payload["id"]),
            type=str(payload["type"]),
            timestamp=str(payload["timestamp"]),
            actor_id=str(payload["actor_id"]),
            payload={str(key): str(value) for key, value in raw_payload.items()},
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_event_payload") from error


def agent_snapshot_to_wire(snapshot: AgentSnapshot) -> dict[str, object]:
    return {
        "agent_id": snapshot.agent_id,
        "claim": None if snapshot.claim is None else claim_to_wire(snapshot.claim),
        "intent": None if snapshot.intent is None else intent_to_wire(snapshot.intent),
        "published_context": [context_to_wire(entry) for entry in snapshot.published_context],
        "incoming_context": [context_to_wire(entry) for entry in snapshot.incoming_context],
        "conflicts": [conflict_to_wire(conflict) for conflict in snapshot.conflicts],
        "events": [event_to_wire(event) for event in snapshot.events],
    }


def agent_snapshot_from_wire(payload: object) -> AgentSnapshot:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_agent_snapshot_payload")
    try:
        return AgentSnapshot(
            agent_id=str(payload["agent_id"]),
            claim=None if payload.get("claim") is None else claim_from_wire(payload["claim"]),
            intent=None if payload.get("intent") is None else intent_from_wire(payload["intent"]),
            published_context=tuple(
                context_from_wire(item) for item in _object_list(payload.get("published_context"))
            ),
            incoming_context=tuple(
                context_from_wire(item) for item in _object_list(payload.get("incoming_context"))
            ),
            conflicts=tuple(
                conflict_from_wire(item) for item in _object_list(payload.get("conflicts"))
            ),
            events=tuple(event_from_wire(item) for item in _object_list(payload.get("events"))),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_agent_snapshot_payload") from error


def inbox_snapshot_to_wire(snapshot: InboxSnapshot) -> dict[str, object]:
    return {
        "agent_id": snapshot.agent_id,
        "pending_context": [context_to_wire(entry) for entry in snapshot.pending_context],
        "conflicts": [conflict_to_wire(conflict) for conflict in snapshot.conflicts],
        "events": [event_to_wire(event) for event in snapshot.events],
    }


def inbox_snapshot_from_wire(payload: object) -> InboxSnapshot:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_inbox_snapshot_payload")
    try:
        return InboxSnapshot(
            agent_id=str(payload["agent_id"]),
            pending_context=tuple(
                context_from_wire(item) for item in _object_list(payload.get("pending_context"))
            ),
            conflicts=tuple(
                conflict_from_wire(item) for item in _object_list(payload.get("conflicts"))
            ),
            events=tuple(event_from_wire(item) for item in _object_list(payload.get("events"))),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_inbox_snapshot_payload") from error


def claim_to_wire(claim: ClaimRecord) -> dict[str, object]:
    return {
        "id": claim.id,
        "agent_id": claim.agent_id,
        "description": claim.description,
        "scope": list(claim.scope),
        "status": claim.status,
        "created_at": claim.created_at,
        "git_branch": claim.git_branch,
        "lease_expires_at": claim.lease_expires_at,
        "lease_policy": claim.lease_policy,
    }


def claim_from_wire(payload: object) -> ClaimRecord:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_claim_payload")
    try:
        return ClaimRecord(
            id=str(payload["id"]),
            agent_id=str(payload["agent_id"]),
            description=str(payload["description"]),
            scope=tuple(_string_list(payload.get("scope"))),
            status=str(payload["status"]),
            created_at=str(payload["created_at"]),
            git_branch=_string_or_none(payload.get("git_branch")),
            lease_expires_at=_string_or_none(payload.get("lease_expires_at")),
            lease_policy=_string_or_none(payload.get("lease_policy")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_claim_payload") from error


def intent_to_wire(intent: IntentRecord) -> dict[str, object]:
    return {
        "id": intent.id,
        "agent_id": intent.agent_id,
        "description": intent.description,
        "reason": intent.reason,
        "scope": list(intent.scope),
        "status": intent.status,
        "created_at": intent.created_at,
        "related_claim_id": intent.related_claim_id,
        "git_branch": intent.git_branch,
        "lease_expires_at": intent.lease_expires_at,
        "lease_policy": intent.lease_policy,
    }


def intent_from_wire(payload: object) -> IntentRecord:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_intent_payload")
    try:
        return IntentRecord(
            id=str(payload["id"]),
            agent_id=str(payload["agent_id"]),
            description=str(payload["description"]),
            reason=str(payload["reason"]),
            scope=tuple(_string_list(payload.get("scope"))),
            status=str(payload["status"]),
            created_at=str(payload["created_at"]),
            related_claim_id=_string_or_none(payload.get("related_claim_id")),
            git_branch=_string_or_none(payload.get("git_branch")),
            lease_expires_at=_string_or_none(payload.get("lease_expires_at")),
            lease_policy=_string_or_none(payload.get("lease_policy")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_intent_payload") from error


def conflict_to_wire(conflict: ConflictRecord) -> dict[str, object]:
    return {
        "id": conflict.id,
        "kind": conflict.kind,
        "severity": conflict.severity,
        "summary": conflict.summary,
        "object_type_a": conflict.object_type_a,
        "object_id_a": conflict.object_id_a,
        "object_type_b": conflict.object_type_b,
        "object_id_b": conflict.object_id_b,
        "scope": list(conflict.scope),
        "created_at": conflict.created_at,
        "is_active": conflict.is_active,
        "resolved_at": conflict.resolved_at,
        "resolved_by": conflict.resolved_by,
        "resolution_note": conflict.resolution_note,
    }


def conflict_from_wire(payload: object) -> ConflictRecord:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_conflict_payload")
    try:
        return ConflictRecord(
            id=str(payload["id"]),
            kind=str(payload["kind"]),
            severity=str(payload["severity"]),
            summary=str(payload["summary"]),
            object_type_a=str(payload["object_type_a"]),
            object_id_a=str(payload["object_id_a"]),
            object_type_b=str(payload["object_type_b"]),
            object_id_b=str(payload["object_id_b"]),
            scope=tuple(_string_list(payload.get("scope"))),
            created_at=str(payload["created_at"]),
            is_active=bool(payload.get("is_active", True)),
            resolved_at=_string_or_none(payload.get("resolved_at")),
            resolved_by=_string_or_none(payload.get("resolved_by")),
            resolution_note=_string_or_none(payload.get("resolution_note")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_conflict_payload") from error


def context_to_wire(context: ContextRecord) -> dict[str, object]:
    return {
        "id": context.id,
        "agent_id": context.agent_id,
        "topic": context.topic,
        "body": context.body,
        "scope": list(context.scope),
        "created_at": context.created_at,
        "related_claim_id": context.related_claim_id,
        "related_intent_id": context.related_intent_id,
        "git_branch": context.git_branch,
        "acknowledgments": [context_ack_to_wire(ack) for ack in context.acknowledgments],
    }


def context_from_wire(payload: object) -> ContextRecord:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_context_payload")
    try:
        return ContextRecord(
            id=str(payload["id"]),
            agent_id=str(payload["agent_id"]),
            topic=str(payload["topic"]),
            body=str(payload["body"]),
            scope=tuple(_string_list(payload.get("scope"))),
            created_at=str(payload["created_at"]),
            related_claim_id=_string_or_none(payload.get("related_claim_id")),
            related_intent_id=_string_or_none(payload.get("related_intent_id")),
            git_branch=_string_or_none(payload.get("git_branch")),
            acknowledgments=tuple(
                context_ack_from_wire(item)
                for item in _object_list(payload.get("acknowledgments"))
            ),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_context_payload") from error


def context_ack_to_wire(ack: ContextAckRecord) -> dict[str, object]:
    return {
        "id": ack.id,
        "context_id": ack.context_id,
        "agent_id": ack.agent_id,
        "status": ack.status,
        "acknowledged_at": ack.acknowledged_at,
        "note": ack.note,
    }


def context_ack_from_wire(payload: object) -> ContextAckRecord:
    if not isinstance(payload, dict):
        raise RuntimeError("invalid_context_ack_payload")
    try:
        return ContextAckRecord(
            id=str(payload["id"]),
            context_id=str(payload["context_id"]),
            agent_id=str(payload["agent_id"]),
            status=str(payload["status"]),
            acknowledged_at=str(payload["acknowledged_at"]),
            note=_string_or_none(payload.get("note")),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("invalid_context_ack_payload") from error


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    raise RuntimeError("invalid_string_list")


def _object_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    raise RuntimeError("invalid_object_list")
