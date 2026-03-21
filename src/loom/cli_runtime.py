from __future__ import annotations

from .client import CoordinationClient
from .daemon import DaemonControlResult, DaemonStatus
from .identity import (
    current_terminal_identity,
    resolve_agent_identity,
    terminal_identity_is_stable,
)
from .guidance import (
    active_work_completion_ready as guidance_active_work_completion_ready,
    active_work_context_reaction as guidance_active_work_context_reaction,
    active_work_nearby_yield_alert as guidance_active_work_nearby_yield_alert,
    active_work_recovery as guidance_active_work_recovery,
    latest_recent_handoff as guidance_latest_recent_handoff,
)
from .local_store import (
    AgentPresenceRecord,
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    CoordinationStore,
    IntentRecord,
)
from .project import LoomProject, load_project
from .util import (
    ACTIVE_RECORD_STALE_AFTER_HOURS,
    DEFAULT_LEASE_POLICY,
    is_past_utc_timestamp,
    is_stale_utc_timestamp,
    json_ready as _json_ready,
    normalize_lease_policy,
)


def build_client(project: LoomProject | None = None) -> CoordinationClient:
    return CoordinationClient(project or load_project())


def resolve_agent_identity_for_project(
    *,
    args: str | None,
    project: LoomProject | None,
) -> tuple[str, str]:
    default_agent = None if project is None else getattr(project, "default_agent", None)
    terminal_aliases = None if project is None else getattr(project, "terminal_aliases", None)
    return resolve_agent_identity(
        args,
        default_agent=default_agent,
        terminal_aliases=terminal_aliases,
    )


def identity_payload(
    *,
    project: LoomProject | None,
    agent_id: str,
    source: str,
) -> dict[str, object]:
    terminal_identity = current_terminal_identity()
    stable_terminal_identity = terminal_identity_is_stable(terminal_identity)
    terminal_binding = None
    project_default = None
    if project is not None:
        terminal_aliases = getattr(project, "terminal_aliases", {})
        if isinstance(terminal_aliases, dict):
            terminal_binding = terminal_aliases.get(terminal_identity)
        project_default = getattr(project, "default_agent", None)
    identity_warning = None
    if not stable_terminal_identity:
        identity_warning = (
            "This shell has no stable terminal identity. "
            "Use LOOM_AGENT or --agent for repeatable agent identity."
        )
    return {
        "id": agent_id,
        "source": source,
        "terminal_identity": terminal_identity,
        "stable_terminal_identity": stable_terminal_identity,
        "terminal_binding": terminal_binding,
        "project_default_agent": project_default,
        "project_initialized": project is not None,
        "identity_warning": identity_warning,
    }


def validated_lease_minutes(value: int | None) -> int | None:
    if value is None:
        return None
    if value <= 0:
        raise ValueError("Lease minutes must be positive.")
    return value


def validated_lease_policy(
    value: str | None,
    *,
    lease_minutes: int | None,
) -> str | None:
    if value is None:
        if lease_minutes is None:
            return None
        return DEFAULT_LEASE_POLICY
    if lease_minutes is None:
        raise ValueError("Lease policy requires --lease-minutes.")
    return normalize_lease_policy(value)


def active_work_with_repo_yield_alert(
    *,
    store: CoordinationStore,
    active_work: dict[str, object],
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    snapshot: object | None,
    stale_agent_ids: set[str] | None = None,
) -> dict[str, object]:
    if active_work.get("started_at") is None or active_work.get("yield_alert") is not None:
        return active_work
    nearby_yield_alert = guidance_active_work_nearby_yield_alert(
        agent_id=agent_id,
        claim=claim,
        intent=intent,
        snapshot=snapshot,
        store=store,
        stale_agent_ids=stale_agent_ids,
    )
    if nearby_yield_alert is None:
        return active_work
    return {
        **active_work,
        "yield_alert": nearby_yield_alert,
        "needs_attention": True,
    }


def active_work_recovery(
    *,
    store: CoordinationStore,
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    pending_context: tuple[ContextRecord, ...],
    conflicts: tuple[ConflictRecord, ...],
    context_limit: int = 5,
    event_limit: int = 10,
) -> dict[str, object]:
    return guidance_active_work_recovery(
        store=store,
        agent_id=agent_id,
        claim=claim,
        intent=intent,
        pending_context=pending_context,
        conflicts=conflicts,
        context_limit=context_limit,
        event_limit=event_limit,
    )


def active_work_completion_ready(
    *,
    active_work: dict[str, object] | None,
    worktree_signal: dict[str, object] | None = None,
) -> bool:
    return guidance_active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    )


def latest_recent_handoff(
    *,
    store: CoordinationStore,
    agent_id: str,
) -> ContextRecord | None:
    return guidance_latest_recent_handoff(
        store=store,
        agent_id=agent_id,
    )


def active_work_context_reaction(
    entry: ContextRecord,
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    active_scope: tuple[str, ...],
) -> str:
    return guidance_active_work_context_reaction(
        entry,
        claim=claim,
        intent=intent,
        active_scope=active_scope,
    )


def coerce_agent_presence_batch(
    value: object,
) -> tuple[AgentPresenceRecord, ...]:
    if isinstance(value, tuple) and all(isinstance(item, AgentPresenceRecord) for item in value):
        return value
    if isinstance(value, list) and all(isinstance(item, AgentPresenceRecord) for item in value):
        return tuple(value)
    return ()


def _agent_presence_is_stale(presence: AgentPresenceRecord) -> bool:
    return is_stale_utc_timestamp(
        presence.last_seen_at,
        stale_after_hours=ACTIVE_RECORD_STALE_AFTER_HOURS,
    )


def _agent_presence_has_expired_lease(
    presence: AgentPresenceRecord,
    *,
    is_past_timestamp=is_past_utc_timestamp,
) -> bool:
    active_records = tuple(
        record
        for record in (presence.claim, presence.intent)
        if record is not None and getattr(record, "status", "") == "active"
    )
    return any(
        bool(getattr(record, "lease_expires_at", None))
        and is_past_timestamp(str(getattr(record, "lease_expires_at")))
        for record in active_records
    )


def partition_agents_by_activity(
    agents: tuple[AgentPresenceRecord, ...],
    *,
    is_stale_timestamp=is_stale_utc_timestamp,
    is_past_timestamp=is_past_utc_timestamp,
) -> tuple[tuple[AgentPresenceRecord, ...], tuple[AgentPresenceRecord, ...], tuple[AgentPresenceRecord, ...]]:
    live_active: list[AgentPresenceRecord] = []
    stale_active: list[AgentPresenceRecord] = []
    idle: list[AgentPresenceRecord] = []
    for presence in agents:
        if presence.claim is None and presence.intent is None:
            idle.append(presence)
            continue
        if is_stale_timestamp(
            presence.last_seen_at,
            stale_after_hours=ACTIVE_RECORD_STALE_AFTER_HOURS,
        ) or _agent_presence_has_expired_lease(
            presence,
            is_past_timestamp=is_past_timestamp,
        ):
            stale_active.append(presence)
        else:
            live_active.append(presence)
    return tuple(live_active), tuple(stale_active), tuple(idle)


def agent_activity_payload(
    agents: tuple[AgentPresenceRecord, ...],
    *,
    is_stale_timestamp=is_stale_utc_timestamp,
    is_past_timestamp=is_past_utc_timestamp,
) -> dict[str, int]:
    live_active, stale_active, idle = partition_agents_by_activity(
        agents,
        is_stale_timestamp=is_stale_timestamp,
        is_past_timestamp=is_past_timestamp,
    )
    return {
        "known_agents": len(agents),
        "live_active_agents": len(live_active),
        "stale_active_agents": len(stale_active),
        "idle_agents": len(idle),
        "stale_after_hours": ACTIVE_RECORD_STALE_AFTER_HOURS,
    }


def stale_agent_ids(
    agents: tuple[AgentPresenceRecord, ...],
    *,
    is_stale_timestamp=is_stale_utc_timestamp,
    is_past_timestamp=is_past_utc_timestamp,
) -> set[str]:
    live_active, stale_active, _idle = partition_agents_by_activity(
        agents,
        is_stale_timestamp=is_stale_timestamp,
        is_past_timestamp=is_past_timestamp,
    )
    del live_active
    return {
        presence.agent_id
        for presence in stale_active
    }


def daemon_status_payload(status: DaemonStatus) -> dict[str, object]:
    return _json_ready(status)


def daemon_result_payload(result: DaemonControlResult) -> dict[str, object]:
    return _json_ready(result)
