from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TypeVar

from .daemon import (
    acknowledge_context as daemon_acknowledge_context,
    create_claim as daemon_create_claim,
    declare_intent as daemon_declare_intent,
    follow_events as daemon_follow_events,
    get_context_entry as daemon_get_context_entry,
    get_daemon_status,
    publish_context as daemon_publish_context,
    read_agents as daemon_read_agents,
    read_agent_snapshot as daemon_read_agent_snapshot,
    read_conflicts as daemon_read_conflicts,
    read_context_entries as daemon_read_context_entries,
    read_events as daemon_read_events,
    read_inbox_snapshot as daemon_read_inbox_snapshot,
    read_status as daemon_read_status,
    release_claim as daemon_release_claim,
    release_intent as daemon_release_intent,
    renew_claim as daemon_renew_claim,
    renew_intent as daemon_renew_intent,
    resolve_conflict as daemon_resolve_conflict,
    DaemonStatus,
)
from .local_store import (
    AgentPresenceRecord,
    AgentSnapshot,
    ClaimRecord,
    ConflictRecord,
    ContextAckRecord,
    ContextRecord,
    CoordinationStore,
    EventRecord,
    InboxSnapshot,
    IntentRecord,
    StatusSnapshot,
)
from .protocol import ProtocolResponseError
from .project import LoomProject


T = TypeVar("T")
_DAEMON_FALLBACK_ERROR_CODES = {
    "socket_unavailable",
    "daemon_closed_connection",
    "unsupported_protocol",
    "unsupported_protocol_version",
}


class CoordinationClient:
    def __init__(self, project: LoomProject) -> None:
        self.project = project
        self._store: CoordinationStore | None = None
        self._daemon_status: DaemonStatus | None = None

    def close(self) -> None:
        if self._store is not None:
            self._store.close_thread_connection()
            self._store = None
        self._daemon_status = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    @property
    def store(self) -> CoordinationStore:
        if self._store is None:
            self._store = CoordinationStore(
                self.project.db_path,
                repo_root=self.project.repo_root,
            )
            self._store.initialize()
        return self._store

    def daemon_status(self, *, refresh: bool = False) -> DaemonStatus:
        if refresh or self._daemon_status is None:
            self._daemon_status = get_daemon_status(self.project)
        return self._daemon_status

    def create_claim(
        self,
        *,
        agent_id: str,
        description: str,
        scope: list[str] | tuple[str, ...],
        source: str,
        lease_minutes: int | None = None,
        lease_policy: str | None = None,
    ) -> tuple[ClaimRecord, tuple[ConflictRecord, ...]]:
        return self._call(
            daemon_call=lambda: daemon_create_claim(
                self.project.socket_path,
                agent_id=agent_id,
                description=description,
                scope=scope,
                source=source,
                lease_minutes=lease_minutes,
                lease_policy=lease_policy,
            ),
            direct_call=lambda store: store.record_claim(
                agent_id=agent_id,
                description=description,
                scope=scope,
                source=source,
                lease_minutes=lease_minutes,
                lease_policy=lease_policy,
            ),
        )

    def release_claim(self, *, agent_id: str) -> ClaimRecord | None:
        return self._call(
            daemon_call=lambda: daemon_release_claim(
                self.project.socket_path,
                agent_id=agent_id,
            ),
            direct_call=lambda store: store.release_claim(agent_id=agent_id),
        )

    def renew_claim(
        self,
        *,
        agent_id: str,
        lease_minutes: int,
        source: str,
    ) -> ClaimRecord | None:
        return self._call(
            daemon_call=lambda: daemon_renew_claim(
                self.project.socket_path,
                agent_id=agent_id,
                lease_minutes=lease_minutes,
                source=source,
            ),
            direct_call=lambda store: store.renew_claim(
                agent_id=agent_id,
                lease_minutes=lease_minutes,
                source=source,
            ),
        )

    def declare_intent(
        self,
        *,
        agent_id: str,
        description: str,
        reason: str,
        scope: list[str] | tuple[str, ...],
        source: str,
        lease_minutes: int | None = None,
        lease_policy: str | None = None,
    ) -> tuple[IntentRecord, tuple[ConflictRecord, ...]]:
        return self._call(
            daemon_call=lambda: daemon_declare_intent(
                self.project.socket_path,
                agent_id=agent_id,
                description=description,
                reason=reason,
                scope=scope,
                source=source,
                lease_minutes=lease_minutes,
                lease_policy=lease_policy,
            ),
            direct_call=lambda store: store.record_intent(
                agent_id=agent_id,
                description=description,
                reason=reason,
                scope=scope,
                source=source,
                lease_minutes=lease_minutes,
                lease_policy=lease_policy,
            ),
        )

    def release_intent(self, *, agent_id: str) -> IntentRecord | None:
        return self._call(
            daemon_call=lambda: daemon_release_intent(
                self.project.socket_path,
                agent_id=agent_id,
            ),
            direct_call=lambda store: store.release_intent(agent_id=agent_id),
        )

    def renew_intent(
        self,
        *,
        agent_id: str,
        lease_minutes: int,
        source: str,
    ) -> IntentRecord | None:
        return self._call(
            daemon_call=lambda: daemon_renew_intent(
                self.project.socket_path,
                agent_id=agent_id,
                lease_minutes=lease_minutes,
                source=source,
            ),
            direct_call=lambda store: store.renew_intent(
                agent_id=agent_id,
                lease_minutes=lease_minutes,
                source=source,
            ),
        )

    def publish_context(
        self,
        *,
        agent_id: str,
        topic: str,
        body: str,
        scope: list[str] | tuple[str, ...],
        source: str,
    ) -> tuple[ContextRecord, tuple[ConflictRecord, ...]]:
        return self._call(
            daemon_call=lambda: daemon_publish_context(
                self.project.socket_path,
                agent_id=agent_id,
                topic=topic,
                body=body,
                scope=scope,
                source=source,
            ),
            direct_call=lambda store: store.record_context(
                agent_id=agent_id,
                topic=topic,
                body=body,
                scope=scope,
                source=source,
            ),
        )

    def acknowledge_context(
        self,
        *,
        context_id: str,
        agent_id: str,
        status: str,
        note: str | None = None,
    ) -> ContextAckRecord | None:
        return self._call(
            daemon_call=lambda: daemon_acknowledge_context(
                self.project.socket_path,
                context_id=context_id,
                agent_id=agent_id,
                status=status,
                note=note,
            ),
            direct_call=lambda store: store.acknowledge_context(
                context_id=context_id,
                agent_id=agent_id,
                status=status,
                note=note,
            ),
        )

    def read_status(self) -> StatusSnapshot:
        return self._call(
            daemon_call=lambda: daemon_read_status(self.project.socket_path),
            direct_call=lambda store: store.status(),
        )

    def read_agents(
        self,
        *,
        limit: int = 20,
    ) -> tuple[AgentPresenceRecord, ...]:
        return self._call(
            daemon_call=lambda: daemon_read_agents(
                self.project.socket_path,
                limit=limit,
            ),
            direct_call=lambda store: store.list_agents(limit=limit),
        )

    def read_agent_snapshot(
        self,
        *,
        agent_id: str,
        context_limit: int = 5,
        event_limit: int = 10,
    ) -> AgentSnapshot:
        return self._call(
            daemon_call=lambda: daemon_read_agent_snapshot(
                self.project.socket_path,
                agent_id=agent_id,
                context_limit=context_limit,
                event_limit=event_limit,
            ),
            direct_call=lambda store: store.agent_snapshot(
                agent_id=agent_id,
                context_limit=context_limit,
                event_limit=event_limit,
            ),
        )

    def read_inbox_snapshot(
        self,
        *,
        agent_id: str,
        context_limit: int = 5,
        event_limit: int = 10,
    ) -> InboxSnapshot:
        return self._call(
            daemon_call=lambda: daemon_read_inbox_snapshot(
                self.project.socket_path,
                agent_id=agent_id,
                context_limit=context_limit,
                event_limit=event_limit,
            ),
            direct_call=lambda store: store.inbox_snapshot(
                agent_id=agent_id,
                context_limit=context_limit,
                event_limit=event_limit,
            ),
        )

    def read_conflicts(self, *, include_resolved: bool = False) -> tuple[ConflictRecord, ...]:
        return self._call(
            daemon_call=lambda: daemon_read_conflicts(
                self.project.socket_path,
                include_resolved=include_resolved,
            ),
            direct_call=lambda store: store.list_conflicts(include_resolved=include_resolved),
        )

    def resolve_conflict(
        self,
        *,
        conflict_id: str,
        agent_id: str,
        resolution_note: str | None = None,
    ) -> ConflictRecord | None:
        return self._call(
            daemon_call=lambda: daemon_resolve_conflict(
                self.project.socket_path,
                conflict_id=conflict_id,
                agent_id=agent_id,
                resolution_note=resolution_note,
            ),
            direct_call=lambda store: store.resolve_conflict(
                conflict_id=conflict_id,
                agent_id=agent_id,
                resolution_note=resolution_note,
            ),
        )

    def read_context_entries(
        self,
        *,
        topic: str | None = None,
        agent_id: str | None = None,
        scope: list[str] | tuple[str, ...] = (),
        limit: int = 10,
    ) -> tuple[ContextRecord, ...]:
        return self._call(
            daemon_call=lambda: daemon_read_context_entries(
                self.project.socket_path,
                topic=topic,
                agent_id=agent_id,
                scope=scope,
                limit=limit,
            ),
            direct_call=lambda store: store.read_context(
                topic=topic,
                agent_id=agent_id,
                scope=scope,
                limit=limit,
            ),
        )

    def get_context_entry(self, *, context_id: str) -> ContextRecord | None:
        return self._call(
            daemon_call=lambda: daemon_get_context_entry(
                self.project.socket_path,
                context_id=context_id,
            ),
            direct_call=lambda store: store.get_context(context_id),
        )

    def read_events(
        self,
        *,
        limit: int | None = 20,
        event_type: str | None = None,
        after_sequence: int | None = None,
        ascending: bool = False,
    ) -> tuple[EventRecord, ...]:
        if limit is None:
            return self.store.list_events(
                limit=None,
                event_type=event_type,
                after_sequence=after_sequence,
                ascending=ascending,
            )
        return self._call(
            daemon_call=lambda: daemon_read_events(
                self.project.socket_path,
                limit=limit,
                event_type=event_type,
                after_sequence=after_sequence,
                ascending=ascending,
            ),
            direct_call=lambda store: store.list_events(
                limit=limit,
                event_type=event_type,
                after_sequence=after_sequence,
                ascending=ascending,
            ),
        )

    def follow_events(
        self,
        *,
        event_type: str | None = None,
        after_sequence: int | None = None,
    ) -> Iterator[EventRecord]:
        status = self.daemon_status()
        if not status.running:
            raise RuntimeError("Daemon is not running.")
        return daemon_follow_events(
            self.project.socket_path,
            event_type=event_type,
            after_sequence=after_sequence,
        )

    def _call(
        self,
        *,
        daemon_call: Callable[[], T],
        direct_call: Callable[[CoordinationStore], T],
    ) -> T:
        status = self.daemon_status()
        if status.running:
            try:
                return daemon_call()
            except RuntimeError as error:
                if not _should_fallback_from_daemon_error(error):
                    raise
                self._daemon_status = None
        result = direct_call(self.store)
        self.daemon_status(refresh=True)
        return result


def _should_fallback_from_daemon_error(error: RuntimeError) -> bool:
    if isinstance(error, ProtocolResponseError):
        return False
    return str(error) in _DAEMON_FALLBACK_ERROR_CODES
