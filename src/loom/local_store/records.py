from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimRecord:
    id: str
    agent_id: str
    description: str
    scope: tuple[str, ...]
    status: str
    created_at: str
    git_branch: str | None = None
    lease_expires_at: str | None = None
    lease_policy: str | None = None


@dataclass(frozen=True)
class IntentRecord:
    id: str
    agent_id: str
    description: str
    reason: str
    scope: tuple[str, ...]
    status: str
    created_at: str
    related_claim_id: str | None
    git_branch: str | None = None
    lease_expires_at: str | None = None
    lease_policy: str | None = None


@dataclass(frozen=True)
class ConflictRecord:
    id: str
    kind: str
    severity: str
    summary: str
    object_type_a: str
    object_id_a: str
    object_type_b: str
    object_id_b: str
    scope: tuple[str, ...]
    created_at: str
    is_active: bool = True
    resolved_at: str | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None


@dataclass(frozen=True)
class ContextRecord:
    id: str
    agent_id: str
    topic: str
    body: str
    scope: tuple[str, ...]
    created_at: str
    related_claim_id: str | None
    related_intent_id: str | None
    git_branch: str | None = None
    acknowledgments: tuple["ContextAckRecord", ...] = ()


@dataclass(frozen=True)
class ContextAckRecord:
    id: str
    context_id: str
    agent_id: str
    status: str
    acknowledged_at: str
    note: str | None = None


@dataclass(frozen=True)
class EventRecord:
    sequence: int
    id: str
    type: str
    timestamp: str
    actor_id: str
    payload: dict[str, str]


@dataclass(frozen=True)
class StatusSnapshot:
    claims: tuple[ClaimRecord, ...]
    intents: tuple[IntentRecord, ...]
    context: tuple[ContextRecord, ...]
    conflicts: tuple[ConflictRecord, ...]


@dataclass(frozen=True)
class AgentSnapshot:
    agent_id: str
    claim: ClaimRecord | None
    intent: IntentRecord | None
    published_context: tuple[ContextRecord, ...]
    incoming_context: tuple[ContextRecord, ...]
    conflicts: tuple[ConflictRecord, ...]
    events: tuple[EventRecord, ...]


@dataclass(frozen=True)
class InboxSnapshot:
    agent_id: str
    pending_context: tuple[ContextRecord, ...]
    conflicts: tuple[ConflictRecord, ...]
    events: tuple[EventRecord, ...]


@dataclass(frozen=True)
class AgentPresenceRecord:
    agent_id: str
    source: str
    created_at: str
    last_seen_at: str
    claim: ClaimRecord | None
    intent: IntentRecord | None
