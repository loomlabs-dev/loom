from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from ..dependency_graph import (
    SOURCE_EXTENSIONS,
    DependencyGraph,
    DependencyLink,
    source_fingerprint,
)
from ..util import (
    current_git_branch,
    DEFAULT_LEASE_POLICY,
    make_id,
    normalize_lease_policy,
    normalize_scopes,
    overlapping_scopes,
    utc_after_minutes,
    utc_now,
)
from .records import (
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
from .store_support import (
    canonical_conflict_sides as _canonical_conflict_sides,
    claim_from_row as _claim_from_row,
    conflict_from_row as _conflict_from_row,
    context_ack_from_row as _context_ack_from_row,
    context_from_row as _context_from_row,
    context_has_ack as _context_has_ack,
    dependency_link_scope as _dependency_link_scope,
    dump_json as _dump_json,
    event_from_row as _event_from_row,
    event_references as _event_references,
    flatten_reference_pairs as _flatten_reference_pairs,
    intent_from_row as _intent_from_row,
    load_json as _load_json,
    merge_context_ack_status as _merge_context_ack_status,
    merge_scopes as _merge_scopes,
    normalize_context_ack_status as _normalize_context_ack_status,
    normalize_event_references as _normalize_event_references,
    reference_pair_placeholders as _reference_pair_placeholders,
    scope_filter_matches as _scope_filter_matches,
    semantic_overlap_summary as _semantic_overlap_summary,
    validated_git_branch_table_name as _validated_git_branch_table_name,
    validated_lease_policy_table_name as _validated_lease_policy_table_name,
    validated_lease_table_name as _validated_lease_table_name,
    validated_row_order as _validated_row_order,
)


@dataclass(frozen=True)
class _DependencyGraphCacheEntry:
    fingerprint: tuple[tuple[str, int, int], ...]
    fingerprint_by_path: dict[str, tuple[int, int]]
    checked_at_monotonic: float
    checked_at_ns: int
    graph: DependencyGraph


@dataclass(frozen=True)
class _AgentState:
    claim: ClaimRecord | None
    intent: IntentRecord | None
    published_context: tuple[ContextRecord, ...]
    incoming_context: tuple[ContextRecord, ...]
    conflicts: tuple[ConflictRecord, ...]


@dataclass
class _ConnectionState:
    connection: sqlite3.Connection | None = None
    depth: int = 0
    failed: bool = False


DEFAULT_DEPENDENCY_GRAPH_RECHECK_SECONDS = 1.0


class CoordinationStore:
    def __init__(
        self,
        db_path: Path,
        repo_root: Path | None = None,
        *,
        reuse_connections: bool = False,
        dependency_graph_recheck_seconds: float = DEFAULT_DEPENDENCY_GRAPH_RECHECK_SECONDS,
    ) -> None:
        self._db_path = db_path
        self._repo_root = (repo_root or db_path.parent.parent).resolve()
        self._reuse_connections = reuse_connections
        self._dependency_graph_recheck_seconds = max(0.0, dependency_graph_recheck_seconds)
        self._connection_state = threading.local()
        self._dependency_graph_lock = threading.Lock()
        self._dependency_graph_cache: _DependencyGraphCacheEntry | None = None

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS claims (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    git_branch TEXT,
                    lease_policy TEXT,
                    superseded_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_claims_active
                ON claims (status, created_at);

                CREATE TABLE IF NOT EXISTS intents (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    related_claim_id TEXT,
                    description TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    git_branch TEXT,
                    lease_policy TEXT,
                    superseded_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_intents_active
                ON intents (status, created_at);

                CREATE TABLE IF NOT EXISTS conflicts (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    object_type_a TEXT NOT NULL,
                    object_id_a TEXT NOT NULL,
                    object_type_b TEXT NOT NULL,
                    object_id_b TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    resolved_at TEXT,
                    resolved_by TEXT,
                    resolution_note TEXT
                );

                CREATE TABLE IF NOT EXISTS context (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    related_claim_id TEXT,
                    related_intent_id TEXT,
                    topic TEXT NOT NULL,
                    body TEXT NOT NULL,
                    scope_json TEXT NOT NULL,
                    git_branch TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_context_created_at
                ON context (created_at DESC);

                CREATE TABLE IF NOT EXISTS context_acknowledgments (
                    id TEXT PRIMARY KEY,
                    context_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    note TEXT,
                    acknowledged_at TEXT NOT NULL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_context_acknowledgments_pair
                ON context_acknowledgments (context_id, agent_id);

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON events (timestamp DESC);

                CREATE TABLE IF NOT EXISTS event_links (
                    event_sequence INTEGER NOT NULL,
                    relation_key TEXT NOT NULL,
                    object_type TEXT NOT NULL,
                    object_id TEXT NOT NULL,
                    PRIMARY KEY (event_sequence, relation_key, object_type, object_id)
                );

                CREATE INDEX IF NOT EXISTS idx_event_links_object
                ON event_links (object_type, object_id, event_sequence DESC);
                """
            )
            connection.execute(
                """
                INSERT INTO metadata (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("schema_version", "4"),
            )
            self._migrate_conflicts_schema(connection)
            self._migrate_git_branch_schema(connection)
            self._migrate_lease_schema(connection)
            self._migrate_lease_policy_schema(connection)
            self._migrate_event_links_schema(connection)
            self._deactivate_stale_conflicts(connection)

    def record_claim(
        self,
        *,
        agent_id: str,
        description: str,
        scope: list[str] | tuple[str, ...],
        source: str,
        lease_minutes: int | None = None,
        lease_policy: str | None = None,
    ) -> tuple[ClaimRecord, list[ConflictRecord]]:
        normalized_scope = normalize_scopes(scope)
        created_at = utc_now()
        if lease_minutes is None:
            if lease_policy is not None:
                raise ValueError("Lease policy requires a positive lease.")
            normalized_lease_policy = None
        else:
            normalized_lease_policy = normalize_lease_policy(
                lease_policy or DEFAULT_LEASE_POLICY
            )
        claim = ClaimRecord(
            id=make_id("claim"),
            agent_id=agent_id,
            description=description,
            scope=normalized_scope,
            status="active",
            created_at=created_at,
            git_branch=current_git_branch(self._repo_root),
            lease_expires_at=(
                None if lease_minutes is None else utc_after_minutes(lease_minutes, from_timestamp=created_at)
            ),
            lease_policy=normalized_lease_policy,
        )

        with self._connect() as connection:
            self._upsert_agent(connection, agent_id=agent_id, source=source, seen_at=created_at)
            self._supersede_active_records(connection, table="claims", agent_id=agent_id, timestamp=created_at)
            connection.execute(
                """
                INSERT INTO claims (
                    id,
                    agent_id,
                    description,
                    scope_json,
                    status,
                    created_at,
                    git_branch,
                    lease_expires_at,
                    lease_policy
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    claim.id,
                    claim.agent_id,
                    claim.description,
                    _dump_json(claim.scope),
                    claim.status,
                    claim.created_at,
                    claim.git_branch,
                    claim.lease_expires_at,
                    claim.lease_policy,
                ),
            )
            self._record_event(
                connection,
                event_type="claim.recorded",
                actor_id=agent_id,
                payload={"claim_id": claim.id},
                timestamp=created_at,
            )
            conflicts = self._detect_conflicts(
                connection,
                object_type="claim",
                object_id=claim.id,
                agent_id=agent_id,
                scope=claim.scope,
                timestamp=created_at,
            )
        return claim, conflicts

    def release_claim(
        self,
        *,
        agent_id: str,
    ) -> ClaimRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, agent_id, description, scope_json, status, created_at, git_branch, lease_expires_at, lease_policy
                FROM claims
                WHERE agent_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
            if row is None:
                return None

            released_at = utc_now()
            connection.execute(
                """
                UPDATE claims
                SET status = 'released', superseded_at = ?
                WHERE id = ?
                """,
                (released_at, row["id"]),
            )
            connection.execute(
                """
                UPDATE conflicts
                SET is_active = 0
                WHERE is_active = 1
                  AND (
                    (object_type_a = 'claim' AND object_id_a = ?)
                    OR
                    (object_type_b = 'claim' AND object_id_b = ?)
                  )
                """,
                (row["id"], row["id"]),
            )
            self._record_event(
                connection,
                event_type="claim.released",
                actor_id=agent_id,
                payload={"claim_id": row["id"]},
                timestamp=released_at,
            )

        return ClaimRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            description=row["description"],
            scope=tuple(_load_json(row["scope_json"])),
            status="released",
            created_at=row["created_at"],
            git_branch=row["git_branch"],
            lease_expires_at=row["lease_expires_at"] if "lease_expires_at" in row.keys() else None,
            lease_policy=row["lease_policy"] if "lease_policy" in row.keys() else None,
        )

    def renew_claim(
        self,
        *,
        agent_id: str,
        lease_minutes: int,
        source: str,
    ) -> ClaimRecord | None:
        renewed_at = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, agent_id, description, scope_json, status, created_at, git_branch, lease_expires_at, lease_policy
                FROM claims
                WHERE agent_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
            if row is None:
                return None

            renewed_lease = utc_after_minutes(lease_minutes, from_timestamp=renewed_at)
            self._upsert_agent(connection, agent_id=agent_id, source=source, seen_at=renewed_at)
            connection.execute(
                """
                UPDATE claims
                SET lease_expires_at = ?
                WHERE id = ?
                """,
                (renewed_lease, row["id"]),
            )
            self._record_event(
                connection,
                event_type="claim.renewed",
                actor_id=agent_id,
                payload={
                    "claim_id": row["id"],
                    "lease_expires_at": renewed_lease,
                },
                timestamp=renewed_at,
            )

        return ClaimRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            description=row["description"],
            scope=tuple(_load_json(row["scope_json"])),
            status=row["status"],
            created_at=row["created_at"],
            git_branch=row["git_branch"],
            lease_expires_at=renewed_lease,
            lease_policy=row["lease_policy"] if "lease_policy" in row.keys() else None,
        )

    def get_claim(self, claim_id: str) -> ClaimRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, agent_id, description, scope_json, status, created_at, git_branch, lease_expires_at, lease_policy
                FROM claims
                WHERE id = ?
                LIMIT 1
                """,
                (claim_id,),
            ).fetchone()
        if row is None:
            return None
        return _claim_from_row(row)

    def record_intent(
        self,
        *,
        agent_id: str,
        description: str,
        reason: str,
        scope: list[str] | tuple[str, ...],
        source: str,
        lease_minutes: int | None = None,
        lease_policy: str | None = None,
    ) -> tuple[IntentRecord, list[ConflictRecord]]:
        normalized_scope = normalize_scopes(scope)
        created_at = utc_now()
        if lease_minutes is None:
            if lease_policy is not None:
                raise ValueError("Lease policy requires a positive lease.")
            normalized_lease_policy = None
        else:
            normalized_lease_policy = normalize_lease_policy(
                lease_policy or DEFAULT_LEASE_POLICY
            )
        with self._connect() as connection:
            self._upsert_agent(connection, agent_id=agent_id, source=source, seen_at=created_at)
            self._supersede_active_records(connection, table="intents", agent_id=agent_id, timestamp=created_at)
            related_claim_id = self._active_claim_id_for_agent(connection, agent_id=agent_id)
            intent = IntentRecord(
                id=make_id("intent"),
                agent_id=agent_id,
                description=description,
                reason=reason,
                scope=normalized_scope,
                status="active",
                created_at=created_at,
                related_claim_id=related_claim_id,
                git_branch=current_git_branch(self._repo_root),
                lease_expires_at=(
                    None if lease_minutes is None else utc_after_minutes(lease_minutes, from_timestamp=created_at)
                ),
                lease_policy=normalized_lease_policy,
            )
            connection.execute(
                """
                INSERT INTO intents (
                    id,
                    agent_id,
                    related_claim_id,
                    description,
                    reason,
                    scope_json,
                    status,
                    created_at,
                    git_branch,
                    lease_expires_at,
                    lease_policy
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.id,
                    intent.agent_id,
                    intent.related_claim_id,
                    intent.description,
                    intent.reason,
                    _dump_json(intent.scope),
                    intent.status,
                    intent.created_at,
                    intent.git_branch,
                    intent.lease_expires_at,
                    intent.lease_policy,
                ),
            )
            self._record_event(
                connection,
                event_type="intent.declared",
                actor_id=agent_id,
                payload={"intent_id": intent.id},
                timestamp=created_at,
            )
            conflicts = self._detect_conflicts(
                connection,
                object_type="intent",
                object_id=intent.id,
                agent_id=agent_id,
                scope=intent.scope,
                timestamp=created_at,
            )
        return intent, conflicts

    def get_intent(self, intent_id: str) -> IntentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    description,
                    reason,
                    scope_json,
                    status,
                    created_at,
                    git_branch,
                    lease_expires_at,
                    lease_policy
                FROM intents
                WHERE id = ?
                LIMIT 1
                """,
                (intent_id,),
            ).fetchone()
        if row is None:
            return None
        return _intent_from_row(row)

    def release_intent(
        self,
        *,
        agent_id: str,
    ) -> IntentRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    description,
                    reason,
                    scope_json,
                    status,
                    created_at,
                    git_branch,
                    lease_expires_at,
                    lease_policy
                FROM intents
                WHERE agent_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
            if row is None:
                return None

            released_at = utc_now()
            connection.execute(
                """
                UPDATE intents
                SET status = 'released', superseded_at = ?
                WHERE id = ?
                """,
                (released_at, row["id"]),
            )
            self._deactivate_conflicts_for_objects(
                connection,
                object_type="intent",
                object_ids=(str(row["id"]),),
            )
            self._record_event(
                connection,
                event_type="intent.released",
                actor_id=agent_id,
                payload={"intent_id": row["id"]},
                timestamp=released_at,
            )

        return IntentRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            description=row["description"],
            reason=row["reason"],
            scope=tuple(_load_json(row["scope_json"])),
            status="released",
            created_at=row["created_at"],
            related_claim_id=row["related_claim_id"],
            git_branch=row["git_branch"],
            lease_expires_at=row["lease_expires_at"] if "lease_expires_at" in row.keys() else None,
            lease_policy=row["lease_policy"] if "lease_policy" in row.keys() else None,
        )

    def renew_intent(
        self,
        *,
        agent_id: str,
        lease_minutes: int,
        source: str,
    ) -> IntentRecord | None:
        renewed_at = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    description,
                    reason,
                    scope_json,
                    status,
                    created_at,
                    git_branch,
                    lease_expires_at,
                    lease_policy
                FROM intents
                WHERE agent_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (agent_id,),
            ).fetchone()
            if row is None:
                return None

            renewed_lease = utc_after_minutes(lease_minutes, from_timestamp=renewed_at)
            self._upsert_agent(connection, agent_id=agent_id, source=source, seen_at=renewed_at)
            connection.execute(
                """
                UPDATE intents
                SET lease_expires_at = ?
                WHERE id = ?
                """,
                (renewed_lease, row["id"]),
            )
            self._record_event(
                connection,
                event_type="intent.renewed",
                actor_id=agent_id,
                payload={
                    "intent_id": row["id"],
                    "lease_expires_at": renewed_lease,
                },
                timestamp=renewed_at,
            )

        return IntentRecord(
            id=row["id"],
            agent_id=row["agent_id"],
            description=row["description"],
            reason=row["reason"],
            scope=tuple(_load_json(row["scope_json"])),
            status=row["status"],
            created_at=row["created_at"],
            related_claim_id=row["related_claim_id"],
            git_branch=row["git_branch"],
            lease_expires_at=renewed_lease,
            lease_policy=row["lease_policy"] if "lease_policy" in row.keys() else None,
        )

    def adopt_agent_work(
        self,
        *,
        from_agent_id: str,
        to_agent_id: str,
        source: str,
    ) -> dict[str, object]:
        from_value = from_agent_id.strip()
        to_value = to_agent_id.strip()
        if not from_value or not to_value:
            raise ValueError("Agent ids must not be empty.")
        if from_value == to_value:
            return {
                "source_had_work": False,
                "target_had_work": False,
                "adopted_claim": None,
                "adopted_intent": None,
            }

        with self._connect() as connection:
            claim_row = connection.execute(
                """
                SELECT id, agent_id, description, scope_json, status, created_at, git_branch, lease_expires_at, lease_policy
                FROM claims
                WHERE agent_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (from_value,),
            ).fetchone()
            intent_row = connection.execute(
                """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    description,
                    reason,
                    scope_json,
                    status,
                    created_at,
                    git_branch,
                    lease_expires_at,
                    lease_policy
                FROM intents
                WHERE agent_id = ? AND status = 'active'
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (from_value,),
            ).fetchone()

            source_had_work = claim_row is not None or intent_row is not None
            target_had_work = (
                self._active_claim_id_for_agent(connection, agent_id=to_value) is not None
                or self._active_intent_id_for_agent(connection, agent_id=to_value) is not None
            )
            if not source_had_work or target_had_work:
                return {
                    "source_had_work": source_had_work,
                    "target_had_work": target_had_work,
                    "adopted_claim": None,
                    "adopted_intent": None,
                }

            adopted_at = utc_now()
            self._upsert_agent(connection, agent_id=to_value, source=source, seen_at=adopted_at)

            adopted_claim: ClaimRecord | None = None
            adopted_intent: IntentRecord | None = None

            if claim_row is not None:
                connection.execute(
                    """
                    UPDATE claims
                    SET agent_id = ?
                    WHERE id = ?
                    """,
                    (to_value, claim_row["id"]),
                )
                self._deactivate_conflicts_for_objects(
                    connection,
                    object_type="claim",
                    object_ids=(str(claim_row["id"]),),
                )
                adopted_claim = ClaimRecord(
                    id=claim_row["id"],
                    agent_id=to_value,
                    description=claim_row["description"],
                    scope=tuple(_load_json(claim_row["scope_json"])),
                    status=claim_row["status"],
                    created_at=claim_row["created_at"],
                    git_branch=claim_row["git_branch"],
                    lease_expires_at=(
                        claim_row["lease_expires_at"]
                        if "lease_expires_at" in claim_row.keys()
                        else None
                    ),
                    lease_policy=(
                        claim_row["lease_policy"]
                        if "lease_policy" in claim_row.keys()
                        else None
                    ),
                )
                self._record_event(
                    connection,
                    event_type="claim.adopted",
                    actor_id=to_value,
                    payload={
                        "claim_id": adopted_claim.id,
                        "agent_id": to_value,
                    },
                    timestamp=adopted_at,
                )

            if intent_row is not None:
                related_claim_id = self._active_claim_id_for_agent(connection, agent_id=to_value)
                if related_claim_id is None:
                    related_claim_id = intent_row["related_claim_id"]
                connection.execute(
                    """
                    UPDATE intents
                    SET agent_id = ?, related_claim_id = ?
                    WHERE id = ?
                    """,
                    (to_value, related_claim_id, intent_row["id"]),
                )
                self._deactivate_conflicts_for_objects(
                    connection,
                    object_type="intent",
                    object_ids=(str(intent_row["id"]),),
                )
                adopted_intent = IntentRecord(
                    id=intent_row["id"],
                    agent_id=to_value,
                    description=intent_row["description"],
                    reason=intent_row["reason"],
                    scope=tuple(_load_json(intent_row["scope_json"])),
                    status=intent_row["status"],
                    created_at=intent_row["created_at"],
                    related_claim_id=related_claim_id,
                    git_branch=intent_row["git_branch"],
                    lease_expires_at=(
                        intent_row["lease_expires_at"]
                        if "lease_expires_at" in intent_row.keys()
                        else None
                    ),
                    lease_policy=(
                        intent_row["lease_policy"]
                        if "lease_policy" in intent_row.keys()
                        else None
                    ),
                )
                payload = {
                    "intent_id": adopted_intent.id,
                    "agent_id": to_value,
                }
                if related_claim_id is not None:
                    payload["related_claim_id"] = related_claim_id
                self._record_event(
                    connection,
                    event_type="intent.adopted",
                    actor_id=to_value,
                    payload=payload,
                    timestamp=adopted_at,
                )

            if adopted_claim is not None:
                self._detect_conflicts(
                    connection,
                    object_type="claim",
                    object_id=adopted_claim.id,
                    agent_id=to_value,
                    scope=adopted_claim.scope,
                    timestamp=adopted_at,
                )
            if adopted_intent is not None:
                self._detect_conflicts(
                    connection,
                    object_type="intent",
                    object_id=adopted_intent.id,
                    agent_id=to_value,
                    scope=adopted_intent.scope,
                    timestamp=adopted_at,
                )

        return {
            "source_had_work": source_had_work,
            "target_had_work": target_had_work,
            "adopted_claim": adopted_claim,
            "adopted_intent": adopted_intent,
        }

    def record_context(
        self,
        *,
        agent_id: str,
        topic: str,
        body: str,
        scope: list[str] | tuple[str, ...],
        source: str,
    ) -> tuple[ContextRecord, list[ConflictRecord]]:
        normalized_scope = normalize_scopes(scope)
        created_at = utc_now()
        with self._connect() as connection:
            self._upsert_agent(connection, agent_id=agent_id, source=source, seen_at=created_at)
            context = ContextRecord(
                id=make_id("context"),
                agent_id=agent_id,
                topic=topic,
                body=body,
                scope=normalized_scope,
                created_at=created_at,
                related_claim_id=self._active_claim_id_for_agent(connection, agent_id=agent_id),
                related_intent_id=self._active_intent_id_for_agent(connection, agent_id=agent_id),
                git_branch=current_git_branch(self._repo_root),
            )
            connection.execute(
                """
                INSERT INTO context (
                    id,
                    agent_id,
                    related_claim_id,
                    related_intent_id,
                    topic,
                    body,
                    scope_json,
                    git_branch,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    context.id,
                    context.agent_id,
                    context.related_claim_id,
                    context.related_intent_id,
                    context.topic,
                    context.body,
                    _dump_json(context.scope),
                    context.git_branch,
                    context.created_at,
                ),
            )
            self._record_event(
                connection,
                event_type="context.published",
                actor_id=agent_id,
                payload={"context_id": context.id},
                timestamp=created_at,
            )
            conflicts = self._detect_context_dependencies(
                connection,
                context=context,
                timestamp=created_at,
            )
        return context, conflicts

    def read_context(
        self,
        *,
        topic: str | None = None,
        agent_id: str | None = None,
        scope: list[str] | tuple[str, ...] = (),
        limit: int = 10,
    ) -> tuple[ContextRecord, ...]:
        normalized_scope = normalize_scopes(scope)
        with self._connect() as connection:
            query = """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    related_intent_id,
                    topic,
                    body,
                    scope_json,
                    git_branch,
                    created_at
                FROM context
            """
            predicates: list[str] = []
            parameters: list[object] = []
            if topic:
                predicates.append("topic = ?")
                parameters.append(topic)
            if agent_id:
                predicates.append("agent_id = ?")
                parameters.append(agent_id)
            if predicates:
                query += " WHERE " + " AND ".join(predicates)
            query += " ORDER BY created_at DESC"

            rows = tuple(connection.execute(query, parameters))

        matches: list[ContextRecord] = []
        for row in rows:
            entry = _context_from_row(row)
            if _scope_filter_matches(entry.scope, normalized_scope):
                matches.append(entry)
            if len(matches) >= limit:
                break
        return self._hydrate_context_acknowledgments(tuple(matches))

    def get_context(
        self,
        context_id: str,
    ) -> ContextRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    related_intent_id,
                    topic,
                    body,
                    scope_json,
                    git_branch,
                    created_at
                FROM context
                WHERE id = ?
                LIMIT 1
                """,
                (context_id,),
            ).fetchone()
        if row is None:
            return None
        return self._hydrate_context_acknowledgments((_context_from_row(row),))[0]

    def list_context_for_claim(self, claim_id: str) -> tuple[ContextRecord, ...]:
        return self._list_related_context("related_claim_id", claim_id)

    def list_context_for_intent(self, intent_id: str) -> tuple[ContextRecord, ...]:
        return self._list_related_context("related_intent_id", intent_id)

    def acknowledge_context(
        self,
        *,
        context_id: str,
        agent_id: str,
        status: str,
        note: str | None = None,
    ) -> ContextAckRecord | None:
        normalized_status = _normalize_context_ack_status(status)
        with self._connect() as connection:
            context_row = connection.execute(
                """
                SELECT id
                FROM context
                WHERE id = ?
                LIMIT 1
                """,
                (context_id,),
            ).fetchone()
            if context_row is None:
                return None

            existing_row = connection.execute(
                """
                SELECT
                    id,
                    context_id,
                    agent_id,
                    status,
                    note,
                    acknowledged_at
                FROM context_acknowledgments
                WHERE context_id = ? AND agent_id = ?
                LIMIT 1
                """,
                (context_id, agent_id),
            ).fetchone()

            acknowledged_at = utc_now()
            if existing_row is None:
                ack = ContextAckRecord(
                    id=make_id("ctxack"),
                    context_id=context_id,
                    agent_id=agent_id,
                    status=normalized_status,
                    acknowledged_at=acknowledged_at,
                    note=note,
                )
                connection.execute(
                    """
                    INSERT INTO context_acknowledgments (
                        id,
                        context_id,
                        agent_id,
                        status,
                        note,
                        acknowledged_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ack.id,
                        ack.context_id,
                        ack.agent_id,
                        ack.status,
                        ack.note,
                        ack.acknowledged_at,
                    ),
                )
            else:
                existing_ack = _context_ack_from_row(existing_row)
                effective_status = _merge_context_ack_status(
                    existing_ack.status,
                    normalized_status,
                )
                effective_note = note if note is not None else existing_ack.note
                ack = ContextAckRecord(
                    id=existing_ack.id,
                    context_id=existing_ack.context_id,
                    agent_id=existing_ack.agent_id,
                    status=effective_status,
                    acknowledged_at=acknowledged_at,
                    note=effective_note,
                )
                connection.execute(
                    """
                    UPDATE context_acknowledgments
                    SET
                        status = ?,
                        note = ?,
                        acknowledged_at = ?
                    WHERE id = ?
                    """,
                    (
                        ack.status,
                        ack.note,
                        ack.acknowledged_at,
                        ack.id,
                    ),
                )

            self._record_event(
                connection,
                event_type="context.acknowledged",
                actor_id=agent_id,
                payload={
                    "context_id": context_id,
                    "status": ack.status,
                },
                timestamp=acknowledged_at,
            )
        return ack

    def list_conflicts(self, *, include_resolved: bool = False) -> tuple[ConflictRecord, ...]:
        with self._connect() as connection:
            query = """
                SELECT
                    id,
                    kind,
                    severity,
                    summary,
                    object_type_a,
                    object_id_a,
                    object_type_b,
                    object_id_b,
                    scope_json,
                    created_at,
                    is_active,
                    resolved_at,
                    resolved_by,
                    resolution_note
                FROM conflicts
            """
            if not include_resolved:
                query += " WHERE is_active = 1"
            query += " ORDER BY created_at ASC"
            rows = tuple(
                connection.execute(query)
            )
        return tuple(_conflict_from_row(row) for row in rows)

    def get_conflict(self, conflict_id: str) -> ConflictRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    kind,
                    severity,
                    summary,
                    object_type_a,
                    object_id_a,
                    object_type_b,
                    object_id_b,
                    scope_json,
                    created_at,
                    is_active,
                    resolved_at,
                    resolved_by,
                    resolution_note
                FROM conflicts
                WHERE id = ?
                LIMIT 1
                """,
                (conflict_id,),
            ).fetchone()
        if row is None:
            return None
        return _conflict_from_row(row)

    def list_conflicts_for_object(
        self,
        *,
        object_type: str,
        object_id: str,
        include_resolved: bool = True,
    ) -> tuple[ConflictRecord, ...]:
        with self._connect() as connection:
            query = """
                SELECT
                    id,
                    kind,
                    severity,
                    summary,
                    object_type_a,
                    object_id_a,
                    object_type_b,
                    object_id_b,
                    scope_json,
                    created_at,
                    is_active,
                    resolved_at,
                    resolved_by,
                    resolution_note
                FROM conflicts
                WHERE (
                    (object_type_a = ? AND object_id_a = ?)
                    OR
                    (object_type_b = ? AND object_id_b = ?)
                )
            """
            parameters: list[object] = [object_type, object_id, object_type, object_id]
            if not include_resolved:
                query += " AND is_active = 1"
            query += " ORDER BY created_at ASC"
            rows = tuple(connection.execute(query, parameters))
        return tuple(_conflict_from_row(row) for row in rows)

    def latest_resolved_conflict_between_references(
        self,
        *,
        left_refs: tuple[tuple[str, str], ...],
        right_refs: tuple[tuple[str, str], ...],
    ) -> ConflictRecord | None:
        unique_left = tuple(dict.fromkeys(left_refs))
        unique_right = tuple(dict.fromkeys(right_refs))
        if not unique_left or not unique_right:
            return None

        left_placeholders = _reference_pair_placeholders(len(unique_left))
        right_placeholders = _reference_pair_placeholders(len(unique_right))
        parameters = [
            *_flatten_reference_pairs(unique_left),
            *_flatten_reference_pairs(unique_right),
            *_flatten_reference_pairs(unique_right),
            *_flatten_reference_pairs(unique_left),
        ]
        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT
                    id,
                    kind,
                    severity,
                    summary,
                    object_type_a,
                    object_id_a,
                    object_type_b,
                    object_id_b,
                    scope_json,
                    created_at,
                    is_active,
                    resolved_at,
                    resolved_by,
                    resolution_note
                FROM conflicts
                WHERE is_active = 0
                  AND resolved_at IS NOT NULL
                  AND (
                        (
                            (object_type_a, object_id_a) IN ({left_placeholders})
                            AND (object_type_b, object_id_b) IN ({right_placeholders})
                        )
                     OR (
                            (object_type_a, object_id_a) IN ({right_placeholders})
                            AND (object_type_b, object_id_b) IN ({left_placeholders})
                        )
                  )
                ORDER BY resolved_at DESC, created_at DESC
                LIMIT 1
                """,
                parameters,
            ).fetchone()
        if row is None:
            return None
        return _conflict_from_row(row)

    def resolve_conflict(
        self,
        *,
        conflict_id: str,
        agent_id: str,
        resolution_note: str | None = None,
    ) -> ConflictRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    kind,
                    severity,
                    summary,
                    object_type_a,
                    object_id_a,
                    object_type_b,
                    object_id_b,
                    scope_json,
                    created_at,
                    is_active,
                    resolved_at,
                    resolved_by,
                    resolution_note
                FROM conflicts
                WHERE id = ?
                LIMIT 1
                """,
                (conflict_id,),
            ).fetchone()
            if row is None:
                return None

            conflict = _conflict_from_row(row)
            if not conflict.is_active:
                return conflict

            resolved_at = utc_now()
            connection.execute(
                """
                UPDATE conflicts
                SET
                    is_active = 0,
                    resolved_at = ?,
                    resolved_by = ?,
                    resolution_note = ?
                WHERE id = ?
                """,
                (resolved_at, agent_id, resolution_note, conflict_id),
            )
            self._record_event(
                connection,
                event_type="conflict.resolved",
                actor_id=agent_id,
                payload={"conflict_id": conflict_id},
                timestamp=resolved_at,
            )
            resolved_row = connection.execute(
                """
                SELECT
                    id,
                    kind,
                    severity,
                    summary,
                    object_type_a,
                    object_id_a,
                    object_type_b,
                    object_id_b,
                    scope_json,
                    created_at,
                    is_active,
                    resolved_at,
                    resolved_by,
                    resolution_note
                FROM conflicts
                WHERE id = ?
                LIMIT 1
                """,
                (conflict_id,),
            ).fetchone()
        return _conflict_from_row(resolved_row)

    def list_events(
        self,
        *,
        limit: int | None = 20,
        event_type: str | None = None,
        after_sequence: int | None = None,
        created_after: str | None = None,
        ascending: bool = False,
    ) -> tuple[EventRecord, ...]:
        query = """
            SELECT
                rowid AS sequence,
                id,
                type,
                timestamp,
                actor_id,
                payload_json
            FROM events
        """
        predicates: list[str] = []
        parameters: list[object] = []
        if event_type:
            predicates.append("type = ?")
            parameters.append(event_type)
        if after_sequence is not None:
            predicates.append("rowid > ?")
            parameters.append(after_sequence)
        if created_after is not None:
            predicates.append("timestamp > ?")
            parameters.append(created_after)
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += f" ORDER BY rowid {_validated_row_order(ascending=ascending)}"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        with self._connect() as connection:
            rows = tuple(connection.execute(query, parameters))
        return tuple(_event_from_row(row) for row in rows)

    def get_event(self, sequence: int) -> EventRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT
                    rowid AS sequence,
                    id,
                    type,
                    timestamp,
                    actor_id,
                    payload_json
                FROM events
                WHERE rowid = ?
                LIMIT 1
                """,
                (sequence,),
            ).fetchone()
        if row is None:
            return None
        return _event_from_row(row)

    def list_events_for_references(
        self,
        *,
        references: list[tuple[str, str]] | tuple[tuple[str, str], ...],
        limit: int | None = 20,
        after_sequence: int | None = None,
        created_after: str | None = None,
        ascending: bool = False,
    ) -> tuple[EventRecord, ...]:
        normalized_references = _normalize_event_references(references)
        with self._connect() as connection:
            return self._list_events_for_references(
                connection,
                references=normalized_references,
                limit=limit,
                after_sequence=after_sequence,
                created_after=created_after,
                ascending=ascending,
            )

    def latest_event_sequence(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(rowid), 0) AS sequence
                FROM events
                """
            ).fetchone()
        return int(row["sequence"]) if row is not None else 0

    def status(self) -> StatusSnapshot:
        with self._connect() as connection:
            claims = tuple(
                _claim_from_row(row)
                for row in connection.execute(
                    """
                    SELECT id, agent_id, description, scope_json, status, created_at, git_branch, lease_expires_at, lease_policy
                    FROM claims
                    WHERE status = 'active'
                    ORDER BY created_at ASC
                    """
                )
            )
            intents = tuple(
                _intent_from_row(row)
                for row in connection.execute(
                    """
                    SELECT
                        id,
                        agent_id,
                        related_claim_id,
                        description,
                        reason,
                        scope_json,
                        status,
                        created_at,
                        git_branch,
                        lease_expires_at,
                        lease_policy
                    FROM intents
                    WHERE status = 'active'
                    ORDER BY created_at ASC
                    """
                )
            )
            context = tuple(
                _context_from_row(row)
                for row in connection.execute(
                    """
                    SELECT
                        id,
                        agent_id,
                        related_claim_id,
                        related_intent_id,
                        topic,
                        body,
                        scope_json,
                        git_branch,
                        created_at
                    FROM context
                    ORDER BY created_at DESC
                    LIMIT 5
                    """
                )
            )
            conflicts = self.list_conflicts()
        return StatusSnapshot(
            claims=claims,
            intents=intents,
            context=self._hydrate_context_acknowledgments(context),
            conflicts=conflicts,
        )

    def agent_snapshot(
        self,
        *,
        agent_id: str,
        context_limit: int = 5,
        event_limit: int = 10,
    ) -> AgentSnapshot:
        if context_limit <= 0:
            raise ValueError("Agent context limit must be positive.")
        if event_limit <= 0:
            raise ValueError("Agent event limit must be positive.")

        with self._connect() as connection:
            state = self._load_agent_state(
                connection,
                agent_id=agent_id,
                context_limit=context_limit,
            )
            event_references = [
                ("agent", agent_id),
                *self._agent_state_event_references(state),
            ]
            events = tuple(
                reversed(
                    self._list_events_for_references(
                        connection,
                        references=_normalize_event_references(event_references),
                        limit=event_limit,
                        ascending=False,
                    )
                )
            )

        return AgentSnapshot(
            agent_id=agent_id,
            claim=state.claim,
            intent=state.intent,
            published_context=state.published_context,
            incoming_context=state.incoming_context,
            conflicts=state.conflicts,
            events=events,
        )

    def list_agent_events(
        self,
        *,
        agent_id: str,
        context_limit: int = 5,
        limit: int | None = 20,
        after_sequence: int | None = None,
        created_after: str | None = None,
        ascending: bool = False,
    ) -> tuple[EventRecord, ...]:
        if context_limit <= 0:
            raise ValueError("Agent context limit must be positive.")
        if limit is not None and limit <= 0:
            raise ValueError("Agent event limit must be positive.")

        with self._connect() as connection:
            state = self._load_agent_state(
                connection,
                agent_id=agent_id,
                context_limit=context_limit,
            )
            event_references = [
                ("agent", agent_id),
                *self._agent_state_event_references(state),
            ]
            return self._list_events_for_references(
                connection,
                references=_normalize_event_references(event_references),
                limit=limit,
                after_sequence=after_sequence,
                created_after=created_after,
                ascending=ascending,
            )

    def agent_event_feed(
        self,
        *,
        agent_id: str,
        context_limit: int = 5,
        limit: int | None = 20,
        after_sequence: int | None = None,
        ascending: bool = True,
    ) -> tuple[tuple[EventRecord, ...], int]:
        if context_limit <= 0:
            raise ValueError("Agent context limit must be positive.")
        if limit is not None and limit <= 0:
            raise ValueError("Agent event limit must be positive.")

        with self._connect() as connection:
            state = self._load_agent_state(
                connection,
                agent_id=agent_id,
                context_limit=context_limit,
            )
            event_references = _normalize_event_references(
                [
                    ("agent", agent_id),
                    *self._agent_state_event_references(state),
                ]
            )
            events = self._list_events_for_references(
                connection,
                references=event_references,
                limit=limit,
                after_sequence=after_sequence,
                ascending=ascending,
            )
            latest_relevant_sequence = self._latest_event_sequence_for_references(
                connection,
                references=event_references,
            )
        return events, latest_relevant_sequence

    def inbox_snapshot(
        self,
        *,
        agent_id: str,
        context_limit: int = 5,
        event_limit: int = 10,
    ) -> InboxSnapshot:
        if context_limit <= 0:
            raise ValueError("Inbox context limit must be positive.")
        if event_limit <= 0:
            raise ValueError("Inbox event limit must be positive.")

        with self._connect() as connection:
            state = self._load_agent_state(
                connection,
                agent_id=agent_id,
                context_limit=context_limit,
            )
            pending_context = tuple(
                entry
                for entry in state.incoming_context
                if not _context_has_ack(entry, agent_id)
            )
            event_references = [
                *(("context", entry.id) for entry in pending_context),
                *(("conflict", conflict.id) for conflict in state.conflicts),
            ]
            events = tuple(
                reversed(
                    self._list_events_for_references(
                        connection,
                        references=_normalize_event_references(event_references),
                        limit=event_limit,
                        ascending=False,
                    )
                )
            )
        return InboxSnapshot(
            agent_id=agent_id,
            pending_context=pending_context,
            conflicts=state.conflicts,
            events=events,
        )

    def list_agents(
        self,
        *,
        limit: int | None = 20,
    ) -> tuple[AgentPresenceRecord, ...]:
        if limit is not None and limit <= 0:
            raise ValueError("Agent limit must be positive when provided.")

        with self._connect() as connection:
            query = """
                SELECT id, source, created_at, last_seen_at
                FROM agents
                ORDER BY last_seen_at DESC, created_at DESC, id ASC
            """
            parameters: list[object] = []
            if limit is not None:
                query += " LIMIT ?"
                parameters.append(limit)
            rows = tuple(connection.execute(query, parameters))
            agent_ids = tuple(str(row["id"]) for row in rows)
            claims_by_agent = self._active_claims_by_agent(
                connection,
                agent_ids=agent_ids,
            )
            intents_by_agent = self._active_intents_by_agent(
                connection,
                agent_ids=agent_ids,
            )

        return tuple(
            AgentPresenceRecord(
                agent_id=str(row["id"]),
                source=str(row["source"]),
                created_at=str(row["created_at"]),
                last_seen_at=str(row["last_seen_at"]),
                claim=claims_by_agent.get(str(row["id"])),
                intent=intents_by_agent.get(str(row["id"])),
            )
            for row in rows
        )

    def prune_idle_agents(
        self,
        *,
        agent_ids: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        with self._connect() as connection:
            parameters: list[object] = []
            filter_sql = ""
            if agent_ids is not None:
                if not agent_ids:
                    return ()
                placeholders = ", ".join("?" for _ in agent_ids)
                filter_sql = f" AND id IN ({placeholders})"
                parameters.extend(agent_ids)

            rows = tuple(
                connection.execute(
                    f"""
                    SELECT id
                    FROM agents
                    WHERE NOT EXISTS (
                        SELECT 1
                        FROM claims
                        WHERE claims.agent_id = agents.id
                          AND claims.status = 'active'
                    )
                      AND NOT EXISTS (
                        SELECT 1
                        FROM intents
                        WHERE intents.agent_id = agents.id
                          AND intents.status = 'active'
                    )
                    {filter_sql}
                    ORDER BY last_seen_at DESC, created_at DESC, id ASC
                    """,
                    parameters,
                )
            )
            pruned_ids = tuple(str(row["id"]) for row in rows)
            if not pruned_ids:
                return ()

            placeholders = ", ".join("?" for _ in pruned_ids)
            connection.execute(
                f"""
                DELETE FROM agents
                WHERE id IN ({placeholders})
                """,
                pruned_ids,
            )
        return pruned_ids

    def close_thread_connection(self) -> None:
        state = self._current_connection_state()
        connection = state.connection
        if connection is None:
            return
        connection.close()
        state.connection = None
        state.depth = 0
        state.failed = False

    def close(self) -> None:
        self.close_thread_connection()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):
            self.close()

    @contextmanager
    def _connect(self) -> sqlite3.Connection:
        if not self._reuse_connections:
            connection = self._create_connection()
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            return

        state = self._current_connection_state()
        if state.connection is None:
            state.connection = self._create_connection()
        state.depth += 1
        try:
            yield state.connection
        except Exception:
            state.failed = True
            raise
        finally:
            state.depth -= 1
            if state.depth == 0 and state.connection is not None:
                try:
                    if state.failed:
                        state.connection.rollback()
                    else:
                        state.connection.commit()
                finally:
                    state.failed = False

    def _create_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _current_connection_state(self) -> _ConnectionState:
        state = getattr(self._connection_state, "state", None)
        if state is None:
            state = _ConnectionState()
            self._connection_state.state = state
        return state

    def _migrate_conflicts_schema(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(conflicts)")
        }
        if "resolved_at" not in existing_columns:
            connection.execute("ALTER TABLE conflicts ADD COLUMN resolved_at TEXT")
        if "resolved_by" not in existing_columns:
            connection.execute("ALTER TABLE conflicts ADD COLUMN resolved_by TEXT")
        if "resolution_note" not in existing_columns:
            connection.execute("ALTER TABLE conflicts ADD COLUMN resolution_note TEXT")

        connection.execute("DROP INDEX IF EXISTS idx_conflicts_pair")
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_conflicts_active_pair
            ON conflicts (
                object_type_a,
                object_id_a,
                object_type_b,
                object_id_b,
                kind
            )
            WHERE is_active = 1
            """
        )

    def _migrate_git_branch_schema(self, connection: sqlite3.Connection) -> None:
        for table in ("claims", "intents", "context"):
            validated_table = _validated_git_branch_table_name(table)
            existing_columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({validated_table})")
            }
            if "git_branch" not in existing_columns:
                connection.execute(
                    f"ALTER TABLE {validated_table} ADD COLUMN git_branch TEXT"
                )

    def _migrate_lease_schema(self, connection: sqlite3.Connection) -> None:
        for table in ("claims", "intents"):
            validated_table = _validated_lease_table_name(table)
            existing_columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({validated_table})")
            }
            if "lease_expires_at" not in existing_columns:
                connection.execute(
                    f"ALTER TABLE {validated_table} ADD COLUMN lease_expires_at TEXT"
                )

    def _migrate_lease_policy_schema(self, connection: sqlite3.Connection) -> None:
        for table in ("claims", "intents"):
            validated_table = _validated_lease_policy_table_name(table)
            existing_columns = {
                row["name"]
                for row in connection.execute(f"PRAGMA table_info({validated_table})")
            }
            if "lease_policy" not in existing_columns:
                connection.execute(
                    f"ALTER TABLE {validated_table} ADD COLUMN lease_policy TEXT"
                )

    def _migrate_event_links_schema(self, connection: sqlite3.Connection) -> None:
        rows = tuple(
            connection.execute(
                """
                SELECT
                    rowid AS sequence,
                    actor_id,
                    payload_json
                FROM events
                WHERE rowid NOT IN (
                    SELECT DISTINCT event_sequence
                    FROM event_links
                )
                ORDER BY rowid ASC
                """
            )
        )
        for row in rows:
            loaded_payload = json.loads(row["payload_json"])
            if not isinstance(loaded_payload, dict):
                continue
            payload = {str(key): str(value) for key, value in loaded_payload.items()}
            self._record_event_links(
                connection,
                event_sequence=int(row["sequence"]),
                actor_id=str(row["actor_id"]),
                payload=payload,
            )

    def _hydrate_context_acknowledgments(
        self,
        entries: tuple[ContextRecord, ...],
    ) -> tuple[ContextRecord, ...]:
        if not entries:
            return entries
        context_ids = tuple(entry.id for entry in entries)
        with self._connect() as connection:
            ack_map = self._load_context_acknowledgments(
                connection,
                context_ids=context_ids,
            )
        return tuple(
            replace(entry, acknowledgments=ack_map.get(entry.id, ()))
            for entry in entries
        )

    def _list_related_context(
        self,
        relation_column: str,
        relation_id: str,
    ) -> tuple[ContextRecord, ...]:
        with self._connect() as connection:
            rows = tuple(
                connection.execute(
                    f"""
                    SELECT
                        id,
                        agent_id,
                        related_claim_id,
                        related_intent_id,
                        topic,
                        body,
                        scope_json,
                        git_branch,
                        created_at
                    FROM context
                    WHERE {relation_column} = ?
                    ORDER BY created_at ASC
                    """,
                    (relation_id,),
                )
            )
        entries = tuple(_context_from_row(row) for row in rows)
        return self._hydrate_context_acknowledgments(entries)

    def _relevant_context_for_agent(
        self,
        connection: sqlite3.Connection,
        *,
        agent_id: str,
        active_scope: tuple[str, ...],
        limit: int,
    ) -> tuple[ContextRecord, ...]:
        if not active_scope:
            return ()

        rows = tuple(
            connection.execute(
                """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    related_intent_id,
                    topic,
                    body,
                    scope_json,
                    git_branch,
                    created_at
                FROM context
                WHERE agent_id != ?
                ORDER BY created_at DESC
                """,
                (agent_id,),
            )
        )
        dependency_graph = self._dependency_graph(refresh_hint=active_scope)
        matches: list[ContextRecord] = []
        for row in rows:
            entry = _context_from_row(row)
            if overlapping_scopes(entry.scope, active_scope):
                matches.append(entry)
            elif entry.scope and dependency_graph.direct_links_between(entry.scope, active_scope):
                matches.append(entry)
            if len(matches) >= limit:
                break

        return self._hydrate_context_acknowledgments(tuple(matches))

    def _load_agent_state(
        self,
        connection: sqlite3.Connection,
        *,
        agent_id: str,
        context_limit: int,
    ) -> _AgentState:
        claim_row = connection.execute(
            """
            SELECT id, agent_id, description, scope_json, status, created_at, git_branch, lease_expires_at, lease_policy
            FROM claims
            WHERE agent_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
        claim = _claim_from_row(claim_row) if claim_row is not None else None

        intent_row = connection.execute(
            """
            SELECT
                id,
                agent_id,
                related_claim_id,
                description,
                reason,
                scope_json,
                status,
                created_at,
                git_branch,
                lease_expires_at,
                lease_policy
            FROM intents
            WHERE agent_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
        intent = _intent_from_row(intent_row) if intent_row is not None else None

        published_rows = tuple(
            connection.execute(
                """
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    related_intent_id,
                    topic,
                    body,
                    scope_json,
                    git_branch,
                    created_at
                FROM context
                WHERE agent_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (agent_id, context_limit),
            )
        )
        published_context = self._hydrate_context_acknowledgments(
            tuple(_context_from_row(row) for row in published_rows)
        )

        active_scope = _merge_scopes(
            claim.scope if claim is not None else (),
            intent.scope if intent is not None else (),
        )
        incoming_context = self._relevant_context_for_agent(
            connection,
            agent_id=agent_id,
            active_scope=active_scope,
            limit=context_limit,
        )

        conflicts = self._list_conflicts_for_objects(
            connection,
            object_refs=self._agent_state_event_references(
                _AgentState(
                    claim=claim,
                    intent=intent,
                    published_context=published_context,
                    incoming_context=incoming_context,
                    conflicts=(),
                )
            ),
        )
        return _AgentState(
            claim=claim,
            intent=intent,
            published_context=published_context,
            incoming_context=incoming_context,
            conflicts=conflicts,
        )

    def _agent_state_event_references(
        self,
        state: _AgentState,
    ) -> tuple[tuple[str, str], ...]:
        references: list[tuple[str, str]] = []
        if state.claim is not None:
            references.append(("claim", state.claim.id))
        if state.intent is not None:
            references.append(("intent", state.intent.id))
        references.extend(("context", entry.id) for entry in state.published_context)
        references.extend(("context", entry.id) for entry in state.incoming_context)
        references.extend(("conflict", conflict.id) for conflict in state.conflicts)
        return _normalize_event_references(references)

    def _list_conflicts_for_objects(
        self,
        connection: sqlite3.Connection,
        *,
        object_refs: tuple[tuple[str, str], ...],
    ) -> tuple[ConflictRecord, ...]:
        unique_refs = tuple(dict.fromkeys(object_refs))
        if not unique_refs:
            return ()

        placeholders = _reference_pair_placeholders(len(unique_refs))
        parameters = [
            *_flatten_reference_pairs(unique_refs),
            *_flatten_reference_pairs(unique_refs),
        ]

        rows = tuple(
            connection.execute(
                f"""
                SELECT
                    id,
                    kind,
                    severity,
                    summary,
                    object_type_a,
                    object_id_a,
                    object_type_b,
                    object_id_b,
                    scope_json,
                    created_at,
                    is_active,
                    resolved_at,
                    resolved_by,
                    resolution_note
                FROM conflicts
                WHERE is_active = 1
                  AND (
                        (object_type_a, object_id_a) IN ({placeholders})
                     OR (object_type_b, object_id_b) IN ({placeholders})
                  )
                ORDER BY created_at ASC
                """,
                parameters,
            )
        )
        return tuple(_conflict_from_row(row) for row in rows)

    def _list_events_for_references(
        self,
        connection: sqlite3.Connection,
        *,
        references: tuple[tuple[str, str], ...],
        limit: int | None,
        after_sequence: int | None = None,
        created_after: str | None = None,
        ascending: bool,
    ) -> tuple[EventRecord, ...]:
        if not references:
            return ()

        parameters = _flatten_reference_pairs(references)
        placeholders = _reference_pair_placeholders(len(references))
        query = f"""
            SELECT
                rowid AS sequence,
                id,
                type,
                timestamp,
                actor_id,
                payload_json
            FROM events
            WHERE rowid IN (
                SELECT event_sequence
                FROM event_links
                WHERE (object_type, object_id) IN ({placeholders})
            )
        """
        if after_sequence is not None:
            query += " AND rowid > ?"
            parameters.append(after_sequence)
        if created_after is not None:
            query += " AND timestamp > ?"
            parameters.append(created_after)
        query += f" ORDER BY rowid {_validated_row_order(ascending=ascending)}"
        if limit is not None:
            query += " LIMIT ?"
            parameters.append(limit)

        rows = tuple(connection.execute(query, parameters))
        return tuple(_event_from_row(row) for row in rows)

    def _latest_event_sequence_for_references(
        self,
        connection: sqlite3.Connection,
        *,
        references: tuple[tuple[str, str], ...],
    ) -> int:
        if not references:
            return 0

        placeholders = _reference_pair_placeholders(len(references))
        parameters = _flatten_reference_pairs(references)

        row = connection.execute(
            f"""
            SELECT COALESCE(MAX(event_sequence), 0) AS sequence
            FROM event_links
            WHERE (object_type, object_id) IN ({placeholders})
            """,
            parameters,
        ).fetchone()
        return 0 if row is None else int(row["sequence"])

    def _upsert_agent(
        self,
        connection: sqlite3.Connection,
        *,
        agent_id: str,
        source: str,
        seen_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO agents (id, source, created_at, last_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                source = excluded.source,
                last_seen_at = excluded.last_seen_at
            """,
            (agent_id, source, seen_at, seen_at),
        )

    def _supersede_active_records(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        agent_id: str,
        timestamp: str,
    ) -> None:
        rows = tuple(
            connection.execute(
                f"""
                SELECT id
                FROM {table}
                WHERE agent_id = ? AND status = 'active'
                """,
                (agent_id,),
            )
        )
        record_ids = [row["id"] for row in rows]
        if not record_ids:
            return

        placeholders = ", ".join("?" for _ in record_ids)
        connection.execute(
            f"""
            UPDATE {table}
            SET status = 'superseded', superseded_at = ?
            WHERE id IN ({placeholders})
            """,
            (timestamp, *record_ids),
        )
        object_type = {"claims": "claim", "intents": "intent"}.get(table)
        if object_type is not None:
            self._deactivate_conflicts_for_objects(
                connection,
                object_type=object_type,
                object_ids=tuple(record_ids),
            )

    def _deactivate_conflicts_for_objects(
        self,
        connection: sqlite3.Connection,
        *,
        object_type: str,
        object_ids: tuple[str, ...],
    ) -> None:
        if not object_ids:
            return
        placeholders = ", ".join("?" for _ in object_ids)
        connection.execute(
            f"""
            UPDATE conflicts
            SET is_active = 0
            WHERE is_active = 1
              AND (
                (object_type_a = ? AND object_id_a IN ({placeholders}))
                OR
                (object_type_b = ? AND object_id_b IN ({placeholders}))
              )
            """,
            (object_type, *object_ids, object_type, *object_ids),
        )

    def _deactivate_stale_conflicts(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            UPDATE conflicts
            SET is_active = 0
            WHERE is_active = 1
              AND (
                (object_type_a = 'claim' AND object_id_a IN (
                    SELECT id FROM claims WHERE status != 'active'
                ))
                OR
                (object_type_b = 'claim' AND object_id_b IN (
                    SELECT id FROM claims WHERE status != 'active'
                ))
                OR
                (object_type_a = 'intent' AND object_id_a IN (
                    SELECT id FROM intents WHERE status != 'active'
                ))
                OR
                (object_type_b = 'intent' AND object_id_b IN (
                    SELECT id FROM intents WHERE status != 'active'
                ))
              )
            """
        )

    def _active_claims_by_agent(
        self,
        connection: sqlite3.Connection,
        *,
        agent_ids: tuple[str, ...],
    ) -> dict[str, ClaimRecord]:
        if not agent_ids:
            return {}
        placeholders = ", ".join("?" for _ in agent_ids)
        rows = tuple(
            connection.execute(
                f"""
                SELECT id, agent_id, description, scope_json, status, created_at, git_branch, lease_expires_at, lease_policy
                FROM claims
                WHERE status = 'active' AND agent_id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                agent_ids,
            )
        )
        claims_by_agent: dict[str, ClaimRecord] = {}
        for row in rows:
            agent_id = str(row["agent_id"])
            claims_by_agent.setdefault(agent_id, _claim_from_row(row))
        return claims_by_agent

    def _active_intents_by_agent(
        self,
        connection: sqlite3.Connection,
        *,
        agent_ids: tuple[str, ...],
    ) -> dict[str, IntentRecord]:
        if not agent_ids:
            return {}
        placeholders = ", ".join("?" for _ in agent_ids)
        rows = tuple(
            connection.execute(
                f"""
                SELECT
                    id,
                    agent_id,
                    related_claim_id,
                    description,
                    reason,
                    scope_json,
                    status,
                    created_at,
                    git_branch,
                    lease_expires_at,
                    lease_policy
                FROM intents
                WHERE status = 'active' AND agent_id IN ({placeholders})
                ORDER BY created_at DESC
                """,
                agent_ids,
            )
        )
        intents_by_agent: dict[str, IntentRecord] = {}
        for row in rows:
            agent_id = str(row["agent_id"])
            intents_by_agent.setdefault(agent_id, _intent_from_row(row))
        return intents_by_agent

    def _active_claim_id_for_agent(
        self,
        connection: sqlite3.Connection,
        *,
        agent_id: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT id
            FROM claims
            WHERE agent_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
        return row["id"] if row else None

    def _active_intent_id_for_agent(
        self,
        connection: sqlite3.Connection,
        *,
        agent_id: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT id
            FROM intents
            WHERE agent_id = ? AND status = 'active'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (agent_id,),
        ).fetchone()
        return row["id"] if row else None

    def _detect_conflicts(
        self,
        connection: sqlite3.Connection,
        *,
        object_type: str,
        object_id: str,
        agent_id: str,
        scope: tuple[str, ...],
        timestamp: str,
    ) -> list[ConflictRecord]:
        if not scope:
            return []

        dependency_graph = self._dependency_graph(refresh_hint=scope)
        active_rows = tuple(
            connection.execute(
                """
                SELECT 'claim' AS object_type, id, agent_id, scope_json
                FROM claims
                WHERE status = 'active' AND agent_id != ?
                UNION ALL
                SELECT 'intent' AS object_type, id, agent_id, scope_json
                FROM intents
                WHERE status = 'active' AND agent_id != ?
                """,
                (agent_id, agent_id),
            )
        )

        conflicts: list[ConflictRecord] = []
        for row in active_rows:
            other_scope = tuple(_load_json(row["scope_json"]))
            overlaps = overlapping_scopes(scope, other_scope)
            if not overlaps:
                dependency_links = dependency_graph.direct_links_between(scope, other_scope)
                if not dependency_links:
                    continue
                summary = _semantic_overlap_summary(
                    agent_id=agent_id,
                    object_type=object_type,
                    other_agent_id=row["agent_id"],
                    other_object_type=row["object_type"],
                    dependency_links=dependency_links,
                )
                conflict_scope = _dependency_link_scope(dependency_links)
                conflict = self._upsert_conflict(
                    connection,
                    kind="semantic_overlap",
                    severity="warning",
                    summary=summary,
                    object_type=object_type,
                    object_id=object_id,
                    other_object_type=row["object_type"],
                    other_object_id=row["id"],
                    scope=conflict_scope,
                    actor_id=agent_id,
                    timestamp=timestamp,
                )
                conflicts.append(conflict)
                continue

            summary = (
                f"{agent_id} {object_type} overlaps {row['agent_id']} "
                f"{row['object_type']} on {', '.join(overlaps)}"
            )
            conflict = self._upsert_conflict(
                connection,
                kind="scope_overlap",
                severity="warning",
                summary=summary,
                object_type=object_type,
                object_id=object_id,
                other_object_type=row["object_type"],
                other_object_id=row["id"],
                scope=overlaps,
                actor_id=agent_id,
                timestamp=timestamp,
            )
            conflicts.append(conflict)

        return conflicts

    def _detect_context_dependencies(
        self,
        connection: sqlite3.Connection,
        *,
        context: ContextRecord,
        timestamp: str,
    ) -> list[ConflictRecord]:
        if not context.scope:
            return []

        dependency_graph = self._dependency_graph(refresh_hint=context.scope)
        active_rows = tuple(
            connection.execute(
                """
                SELECT 'claim' AS object_type, id, agent_id, scope_json
                FROM claims
                WHERE status = 'active' AND agent_id != ?
                UNION ALL
                SELECT 'intent' AS object_type, id, agent_id, scope_json
                FROM intents
                WHERE status = 'active' AND agent_id != ?
                """,
                (context.agent_id, context.agent_id),
            )
        )

        conflicts: list[ConflictRecord] = []
        for row in active_rows:
            other_scope = tuple(_load_json(row["scope_json"]))
            overlaps = overlapping_scopes(context.scope, other_scope)
            if overlaps:
                summary = (
                    f"{row['agent_id']} {row['object_type']} may depend on "
                    f"{context.agent_id} context {context.topic} on {', '.join(overlaps)}"
                )
                conflict = self._upsert_conflict(
                    connection,
                    kind="contextual_dependency",
                    severity="warning",
                    summary=summary,
                    object_type="context",
                    object_id=context.id,
                    other_object_type=row["object_type"],
                    other_object_id=row["id"],
                    scope=overlaps,
                    actor_id=context.agent_id,
                    timestamp=timestamp,
                )
                conflicts.append(conflict)
                continue

            dependency_links = dependency_graph.direct_links_between(context.scope, other_scope)
            if not dependency_links:
                continue

            summary = (
                f"{row['agent_id']} {row['object_type']} may depend on "
                f"{context.agent_id} context {context.topic} via "
                f"{dependency_links[0].source} -> {dependency_links[0].target}"
            )
            conflict = self._upsert_conflict(
                connection,
                kind="contextual_dependency",
                severity="warning",
                summary=summary,
                object_type="context",
                object_id=context.id,
                other_object_type=row["object_type"],
                other_object_id=row["id"],
                scope=_dependency_link_scope(dependency_links),
                actor_id=context.agent_id,
                timestamp=timestamp,
            )
            conflicts.append(conflict)

        return conflicts

    def _dependency_graph(
        self,
        *,
        refresh_hint: tuple[str, ...] = (),
    ) -> DependencyGraph:
        now = time.monotonic()
        with self._dependency_graph_lock:
            cached = self._dependency_graph_cache
            if (
                cached is not None
                and now < cached.checked_at_monotonic + self._dependency_graph_recheck_seconds
                and not self._scope_hints_require_dependency_graph_refresh(
                    cached,
                    refresh_hint=refresh_hint,
                )
            ):
                return cached.graph

            fingerprint = source_fingerprint(self._repo_root)
            checked_at_ns = time.time_ns()
            fingerprint_by_path = {
                relative_path: (mtime_ns, size)
                for relative_path, mtime_ns, size in fingerprint
            }
            if cached is not None and cached.fingerprint == fingerprint:
                self._dependency_graph_cache = _DependencyGraphCacheEntry(
                    fingerprint=fingerprint,
                    fingerprint_by_path=fingerprint_by_path,
                    checked_at_monotonic=now,
                    checked_at_ns=checked_at_ns,
                    graph=cached.graph,
                )
                return cached.graph

            graph = DependencyGraph.build(self._repo_root)
            self._dependency_graph_cache = _DependencyGraphCacheEntry(
                fingerprint=fingerprint,
                fingerprint_by_path=fingerprint_by_path,
                checked_at_monotonic=now,
                checked_at_ns=checked_at_ns,
                graph=graph,
            )
            return graph

    def dependency_scope_between_scopes(
        self,
        left_scope: tuple[str, ...],
        right_scope: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not left_scope or not right_scope:
            return ()
        dependency_links = self._dependency_graph(
            refresh_hint=tuple(left_scope) + tuple(right_scope)
        ).direct_links_between(left_scope, right_scope)
        if not dependency_links:
            return ()
        return _dependency_link_scope(dependency_links)

    def _scope_hints_require_dependency_graph_refresh(
        self,
        cached: _DependencyGraphCacheEntry,
        *,
        refresh_hint: tuple[str, ...],
    ) -> bool:
        if not refresh_hint:
            return False

        for scope_item in refresh_hint:
            if scope_item == ".":
                return True

            parts = PurePosixPath(scope_item).parts
            if not parts:
                continue
            scope_path = self._repo_root.joinpath(*parts)
            try:
                stat = scope_path.stat()
            except OSError:
                continue

            if scope_path.is_dir():
                if stat.st_mtime_ns > cached.checked_at_ns:
                    return True
                continue

            relative_path = scope_path.relative_to(self._repo_root).as_posix()
            if PurePosixPath(relative_path).suffix not in SOURCE_EXTENSIONS:
                continue
            cached_metadata = cached.fingerprint_by_path.get(relative_path)
            if cached_metadata is None:
                return True
            if cached_metadata != (stat.st_mtime_ns, stat.st_size):
                return True
        return False

    def _upsert_conflict(
        self,
        connection: sqlite3.Connection,
        *,
        kind: str,
        severity: str,
        summary: str,
        object_type: str,
        object_id: str,
        other_object_type: str,
        other_object_id: str,
        scope: tuple[str, ...],
        actor_id: str,
        timestamp: str,
    ) -> ConflictRecord:
        side_a, side_b = _canonical_conflict_sides(
            left_type=object_type,
            left_id=object_id,
            right_type=other_object_type,
            right_id=other_object_id,
        )
        conflict_id = make_id("conflict")
        connection.execute(
            """
            INSERT OR IGNORE INTO conflicts (
                id,
                kind,
                severity,
                summary,
                object_type_a,
                object_id_a,
                object_type_b,
                object_id_b,
                scope_json,
                created_at,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                conflict_id,
                kind,
                severity,
                summary,
                side_a[0],
                side_a[1],
                side_b[0],
                side_b[1],
                _dump_json(scope),
                timestamp,
            ),
        )
        stored_conflict = connection.execute(
            """
            SELECT
                id,
                kind,
                severity,
                summary,
                object_type_a,
                object_id_a,
                object_type_b,
                object_id_b,
                scope_json,
                created_at,
                is_active,
                resolved_at,
                resolved_by,
                resolution_note
            FROM conflicts
            WHERE object_type_a = ?
              AND object_id_a = ?
              AND object_type_b = ?
              AND object_id_b = ?
              AND is_active = 1
            """,
            (side_a[0], side_a[1], side_b[0], side_b[1]),
        ).fetchone()
        conflict = _conflict_from_row(stored_conflict)
        self._record_event(
            connection,
            event_type="conflict.detected",
            actor_id=actor_id,
            payload={"conflict_id": conflict.id},
            timestamp=timestamp,
        )
        return conflict

    def _load_context_acknowledgments(
        self,
        connection: sqlite3.Connection,
        *,
        context_ids: tuple[str, ...],
    ) -> dict[str, tuple[ContextAckRecord, ...]]:
        placeholders = ", ".join("?" for _ in context_ids)
        rows = tuple(
            connection.execute(
                f"""
                SELECT
                    id,
                    context_id,
                    agent_id,
                    status,
                    note,
                    acknowledged_at
                FROM context_acknowledgments
                WHERE context_id IN ({placeholders})
                ORDER BY acknowledged_at ASC, agent_id ASC
                """,
                context_ids,
            )
        )
        ack_map: dict[str, list[ContextAckRecord]] = {context_id: [] for context_id in context_ids}
        for row in rows:
            ack = _context_ack_from_row(row)
            ack_map.setdefault(ack.context_id, []).append(ack)
        return {
            context_id: tuple(acks)
            for context_id, acks in ack_map.items()
            if acks
        }

    def _record_event(
        self,
        connection: sqlite3.Connection,
        *,
        event_type: str,
        actor_id: str,
        payload: dict[str, str],
        timestamp: str,
    ) -> None:
        cursor = connection.execute(
            """
            INSERT INTO events (id, type, timestamp, actor_id, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                make_id("event"),
                event_type,
                timestamp,
                actor_id,
                _dump_json(payload),
            ),
        )
        self._record_event_links(
            connection,
            event_sequence=int(cursor.lastrowid),
            actor_id=actor_id,
            payload=payload,
        )

    def _record_event_links(
        self,
        connection: sqlite3.Connection,
        *,
        event_sequence: int,
        actor_id: str,
        payload: dict[str, str],
    ) -> None:
        references = _event_references(actor_id=actor_id, payload=payload)
        if not references:
            return
        connection.executemany(
            """
            INSERT OR IGNORE INTO event_links (
                event_sequence,
                relation_key,
                object_type,
                object_id
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                (event_sequence, relation_key, object_type, object_id)
                for relation_key, object_type, object_id in references
            ),
        )
