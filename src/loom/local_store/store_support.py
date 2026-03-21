from __future__ import annotations

import json
import sqlite3

from ..dependency_graph import DependencyLink
from ..util import overlapping_scopes
from .records import (
    ClaimRecord,
    ConflictRecord,
    ContextAckRecord,
    ContextRecord,
    EventRecord,
    IntentRecord,
)

_GIT_BRANCH_MIGRATION_TABLES = frozenset({"claims", "intents", "context"})
_LEASE_MIGRATION_TABLES = frozenset({"claims", "intents"})
_LEASE_POLICY_MIGRATION_TABLES = frozenset({"claims", "intents"})


def validated_git_branch_table_name(table: str) -> str:
    if table not in _GIT_BRANCH_MIGRATION_TABLES:
        raise ValueError(f"Unsupported migration table: {table}")
    return table


def validated_lease_table_name(table: str) -> str:
    if table not in _LEASE_MIGRATION_TABLES:
        raise ValueError(f"Unsupported lease table: {table}")
    return table


def validated_lease_policy_table_name(table: str) -> str:
    if table not in _LEASE_POLICY_MIGRATION_TABLES:
        raise ValueError(f"Unsupported lease policy table: {table}")
    return table


def validated_row_order(*, ascending: bool) -> str:
    return "ASC" if ascending else "DESC"


def reference_pair_placeholders(reference_count: int) -> str:
    if reference_count <= 0:
        raise ValueError("reference_count must be positive")
    return ", ".join("(?, ?)" for _ in range(reference_count))


def flatten_reference_pairs(references: tuple[tuple[str, str], ...]) -> list[object]:
    parameters: list[object] = []
    for object_type, object_id in references:
        parameters.extend((object_type, object_id))
    return parameters


def claim_from_row(row: sqlite3.Row) -> ClaimRecord:
    return ClaimRecord(
        id=row["id"],
        agent_id=row["agent_id"],
        description=row["description"],
        scope=tuple(load_json(row["scope_json"])),
        status=row["status"],
        created_at=row["created_at"],
        git_branch=row["git_branch"] if "git_branch" in row.keys() else None,
        lease_expires_at=(
            row["lease_expires_at"] if "lease_expires_at" in row.keys() else None
        ),
        lease_policy=row["lease_policy"] if "lease_policy" in row.keys() else None,
    )


def intent_from_row(row: sqlite3.Row) -> IntentRecord:
    return IntentRecord(
        id=row["id"],
        agent_id=row["agent_id"],
        description=row["description"],
        reason=row["reason"],
        scope=tuple(load_json(row["scope_json"])),
        status=row["status"],
        created_at=row["created_at"],
        related_claim_id=row["related_claim_id"],
        git_branch=row["git_branch"] if "git_branch" in row.keys() else None,
        lease_expires_at=(
            row["lease_expires_at"] if "lease_expires_at" in row.keys() else None
        ),
        lease_policy=row["lease_policy"] if "lease_policy" in row.keys() else None,
    )


def conflict_from_row(row: sqlite3.Row) -> ConflictRecord:
    return ConflictRecord(
        id=row["id"],
        kind=row["kind"],
        severity=row["severity"],
        summary=row["summary"],
        object_type_a=row["object_type_a"],
        object_id_a=row["object_id_a"],
        object_type_b=row["object_type_b"],
        object_id_b=row["object_id_b"],
        scope=tuple(load_json(row["scope_json"])),
        created_at=row["created_at"],
        is_active=bool(row["is_active"]) if "is_active" in row.keys() else True,
        resolved_at=row["resolved_at"] if "resolved_at" in row.keys() else None,
        resolved_by=row["resolved_by"] if "resolved_by" in row.keys() else None,
        resolution_note=(
            row["resolution_note"] if "resolution_note" in row.keys() else None
        ),
    )


def context_from_row(row: sqlite3.Row) -> ContextRecord:
    return ContextRecord(
        id=row["id"],
        agent_id=row["agent_id"],
        topic=row["topic"],
        body=row["body"],
        scope=tuple(load_json(row["scope_json"])),
        created_at=row["created_at"],
        related_claim_id=row["related_claim_id"],
        related_intent_id=row["related_intent_id"],
        git_branch=row["git_branch"] if "git_branch" in row.keys() else None,
    )


def context_ack_from_row(row: sqlite3.Row) -> ContextAckRecord:
    return ContextAckRecord(
        id=row["id"],
        context_id=row["context_id"],
        agent_id=row["agent_id"],
        status=row["status"],
        acknowledged_at=row["acknowledged_at"],
        note=row["note"],
    )


def event_from_row(row: sqlite3.Row) -> EventRecord:
    loaded_payload = json.loads(row["payload_json"])
    payload = {str(key): str(value) for key, value in loaded_payload.items()}
    return EventRecord(
        sequence=int(row["sequence"]),
        id=row["id"],
        type=row["type"],
        timestamp=row["timestamp"],
        actor_id=row["actor_id"],
        payload=payload,
    )


def canonical_conflict_sides(
    *,
    left_type: str,
    left_id: str,
    right_type: str,
    right_id: str,
) -> tuple[tuple[str, str], tuple[str, str]]:
    left = (left_type, left_id)
    right = (right_type, right_id)
    return (left, right) if left <= right else (right, left)


def semantic_overlap_summary(
    *,
    agent_id: str,
    object_type: str,
    other_agent_id: str,
    other_object_type: str,
    dependency_links: tuple[DependencyLink, ...],
) -> str:
    link = dependency_links[0]
    return (
        f"{agent_id} {object_type} is semantically entangled with "
        f"{other_agent_id} {other_object_type} via "
        f"{link.source} -> {link.target}"
    )


def dependency_link_scope(dependency_links: tuple[DependencyLink, ...]) -> tuple[str, ...]:
    paths: list[str] = []
    for link in dependency_links:
        for path in (link.source, link.target):
            if path not in paths:
                paths.append(path)
            if len(paths) >= 4:
                return tuple(paths)
    return tuple(paths)


def normalize_context_ack_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized not in {"read", "adapted"}:
        raise ValueError("Context acknowledgment status must be `read` or `adapted`.")
    return normalized


def merge_context_ack_status(existing: str, requested: str) -> str:
    rank = {"read": 1, "adapted": 2}
    return existing if rank[existing] > rank[requested] else requested


def context_has_ack(entry: ContextRecord, agent_id: str) -> bool:
    return any(ack.agent_id == agent_id for ack in entry.acknowledgments)


def merge_scopes(*scope_sets: tuple[str, ...]) -> tuple[str, ...]:
    merged: list[str] = []
    for scope_set in scope_sets:
        for scope in scope_set:
            if scope not in merged:
                merged.append(scope)
    return tuple(merged)


def dump_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def load_json(value: str) -> list[str]:
    loaded = json.loads(value)
    if isinstance(loaded, list):
        return [str(item) for item in loaded]
    if isinstance(loaded, dict):
        return [f"{key}:{loaded[key]}" for key in loaded]
    return [str(loaded)]


def normalize_event_references(
    references: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for object_type, object_id in references:
        normalized.append((str(object_type), str(object_id)))
    return tuple(dict.fromkeys(normalized))


def event_references(
    *,
    actor_id: str,
    payload: dict[str, str],
) -> tuple[tuple[str, str, str], ...]:
    references: list[tuple[str, str, str]] = [("actor_id", "agent", actor_id)]
    for key, value in payload.items():
        object_type = object_type_for_reference_key(key)
        if object_type is None:
            continue
        references.append((key, object_type, str(value)))
    return tuple(dict.fromkeys(references))


def object_type_for_reference_key(key: str) -> str | None:
    if key in {"actor_id", "agent_id"}:
        return "agent"
    if not key.endswith("_id"):
        return None

    object_type = key[:-3]
    if object_type.startswith("related_"):
        object_type = object_type[len("related_") :]
    return object_type or None


def scope_filter_matches(
    record_scope: tuple[str, ...],
    requested_scope: tuple[str, ...],
) -> bool:
    if not requested_scope:
        return True
    if not record_scope:
        return True
    return bool(overlapping_scopes(record_scope, requested_scope))
