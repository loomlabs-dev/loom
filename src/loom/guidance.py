from __future__ import annotations

from pathlib import Path

from .guidance_actions import (
    claim_recommendation,
    conflicts_recommendation,
    finish_recommendation,
    focus_agent_recommendation,
    handoff_recommendation,
    inbox_recommendation,
    inspect_conflicts_recommendation,
    inspect_inbox_recommendation,
    intent_recommendation,
    lease_alert_recommendation,
    priority_recommendation,
    recommendation,
    worktree_adoption_recommendation,
    yield_alert_recommendation,
)
from .guidance_state import (
    active_scope_for_worktree,
    active_work_nearby_yield_alert as _state_active_work_nearby_yield_alert,
    active_work_started_at,
    agent_presence_has_expired_lease as _state_agent_presence_has_expired_lease,
    agent_presence_is_stale as _state_agent_presence_is_stale,
    compact_scope_suggestion,
    latest_recent_handoff as _state_latest_recent_handoff,
    repo_lanes_payload as _state_repo_lanes_payload,
    scopes_overlap_for_inference,
    stale_agent_ids as _state_stale_agent_ids,
    worktree_scope_candidate,
)
from .local_store import (
    AgentPresenceRecord,
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    CoordinationStore,
    IntentRecord,
)
from .util import (
    current_worktree_paths,
    DEFAULT_LEASE_POLICY,
    is_past_utc_timestamp,
    is_stale_utc_timestamp,
    normalize_lease_policy,
    overlapping_scopes,
    parse_utc_timestamp,
)

DEFAULT_RENEW_LEASE_MINUTES = 60
WORKTREE_IGNORED_PREFIXES = (".loom", ".loom-reports")


def identity_has_stable_coordination(
    *,
    identity: dict[str, object] | None = None,
    default_agent: str | None = None,
) -> bool:
    if identity is None:
        return default_agent is not None
    stable_terminal_binding = bool(identity.get("terminal_binding")) and not identity_needs_env_binding(
        identity
    )
    return bool(
        stable_terminal_binding
        or identity.get("project_default_agent")
        or identity.get("source") == "env"
    )


def identity_needs_env_binding(identity: dict[str, object]) -> bool:
    return not bool(identity.get("stable_terminal_identity", True))


def onboarding_step_order(*, has_stable_identity: bool) -> tuple[str, ...]:
    if has_stable_identity:
        return ("start", "claim", "status")
    return ("start", "bind", "claim")


def status_step_order(
    *,
    is_empty: bool,
    has_conflicts: bool,
    has_context: bool,
    has_stable_identity: bool,
) -> tuple[str, ...]:
    if is_empty:
        return onboarding_step_order(has_stable_identity=has_stable_identity)
    if has_conflicts:
        return ("conflicts", "inbox", "agent")
    if has_context:
        return ("inbox", "agent", "log")
    return ("agent", "inbox", "log")


def agents_step_order(*, agent_count: int, has_stable_identity: bool) -> tuple[str, ...]:
    if agent_count == 0:
        return onboarding_step_order(has_stable_identity=has_stable_identity)
    return ("agent", "inbox", "status")


def agent_step_order(
    *,
    has_pending_attention: bool,
    has_claim: bool,
    has_intent: bool,
    has_published_context: bool,
) -> tuple[str, ...]:
    if has_pending_attention:
        return ("inbox", "status")
    if not has_claim and not has_intent and not has_published_context:
        return ("claim", "status")
    if has_claim and not has_intent:
        return ("intent", "status")
    return ("status",)


def start_step_order(
    *,
    project_initialized: bool,
    has_raw_terminal_identity: bool,
    has_inbox_attention: bool,
    has_priority: bool,
) -> tuple[str, ...]:
    if not project_initialized:
        return ("init", "bind", "claim")
    if has_raw_terminal_identity:
        return ("bind", "start", "claim")
    if has_inbox_attention:
        if has_priority:
            return ("priority", "inbox", "status")
        return ("inbox", "conflicts", "status")
    return ()


def start_followup_step_order(
    *,
    has_recent_handoff: bool,
    completion_ready: bool,
    repo_is_empty: bool,
) -> tuple[str, ...]:
    if has_recent_handoff:
        return ("handoff", "status", "agent")
    if completion_ready:
        return ("finish", "status", "agent")
    if repo_is_empty:
        return ("claim", "status", "agent")
    return ()


def start_drift_step_order(*, has_active_scope: bool) -> tuple[str, ...]:
    if has_active_scope:
        return ("intent", "agent", "status")
    return ("claim", "status", "agent")


def worktree_signal(
    *,
    project_root: Path,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> dict[str, object]:
    changed_paths = tuple(
        path
        for path in current_worktree_paths(project_root)
        if not should_ignore_worktree_path(path)
    )
    active_scope = active_scope_for_worktree(claim=claim, intent=intent)
    if not changed_paths:
        return {
            "changed_paths": (),
            "in_scope_paths": (),
            "drift_paths": (),
            "active_scope": active_scope,
            "suggested_scope": (),
            "has_active_scope": bool(active_scope),
            "has_drift": False,
        }

    if not active_scope:
        suggested_scope = suggest_scope_update(active_scope=(), drift_paths=changed_paths)
        return {
            "changed_paths": changed_paths,
            "in_scope_paths": (),
            "drift_paths": changed_paths,
            "active_scope": (),
            "suggested_scope": suggested_scope,
            "has_active_scope": False,
            "has_drift": bool(changed_paths),
        }

    in_scope_paths: list[str] = []
    drift_paths: list[str] = []
    for path in changed_paths:
        if overlapping_scopes((path,), active_scope):
            in_scope_paths.append(path)
        else:
            drift_paths.append(path)
    return {
        "changed_paths": changed_paths,
        "in_scope_paths": tuple(in_scope_paths),
        "drift_paths": tuple(drift_paths),
        "active_scope": active_scope,
        "suggested_scope": suggest_scope_update(
            active_scope=active_scope,
            drift_paths=tuple(drift_paths),
        ),
        "has_active_scope": True,
        "has_drift": bool(drift_paths),
    }


def should_ignore_worktree_path(path: str) -> bool:
    return path in WORKTREE_IGNORED_PREFIXES or any(
        path.startswith(f"{prefix}/")
        for prefix in WORKTREE_IGNORED_PREFIXES
    )


def suggest_scope_update(
    *,
    active_scope: tuple[str, ...],
    drift_paths: tuple[str, ...],
) -> tuple[str, ...]:
    if not drift_paths:
        return ()
    candidates = [
        *active_scope,
        *(worktree_scope_candidate(path) for path in drift_paths),
    ]
    return compact_scope_suggestion(candidates)


def active_work_context_reaction(
    entry: ContextRecord,
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    active_scope: tuple[str, ...],
) -> str:
    claim_id = None if claim is None else claim.id
    intent_id = None if intent is None else intent.id
    if entry.related_claim_id == claim_id or entry.related_intent_id == intent_id:
        return "react now"
    if active_scope and overlapping_scopes(entry.scope, active_scope):
        return "react now"
    return "review soon"


def prioritize_active_work_context(
    entries: tuple[ContextRecord, ...],
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    active_scope: tuple[str, ...],
) -> tuple[ContextRecord, ...]:
    if not entries:
        return ()

    claim_id = None if claim is None else claim.id
    intent_id = None if intent is None else intent.id

    def sort_key(entry: ContextRecord) -> tuple[int, int, int, float]:
        reaction = active_work_context_reaction(
            entry,
            claim=claim,
            intent=intent,
            active_scope=active_scope,
        )
        directly_related = entry.related_claim_id == claim_id or entry.related_intent_id == intent_id
        scope_overlap = bool(overlapping_scopes(entry.scope, active_scope))
        return (
            0 if reaction == "react now" else 1,
            0 if directly_related else 1,
            0 if scope_overlap else 1,
            -parse_utc_timestamp(entry.created_at).timestamp(),
        )

    return tuple(sorted(entries, key=sort_key))


def prioritize_active_work_conflicts(
    conflicts: tuple[ConflictRecord, ...],
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> tuple[ConflictRecord, ...]:
    if not conflicts:
        return ()

    current_object_ids = {
        object_id
        for object_id in (
            None if claim is None else claim.id,
            None if intent is None else intent.id,
        )
        if object_id is not None
    }

    def severity_rank(value: str) -> int:
        normalized = value.strip().lower()
        if normalized == "critical":
            return 0
        if normalized == "error":
            return 1
        if normalized == "warning":
            return 2
        return 3

    def sort_key(conflict: ConflictRecord) -> tuple[int, int, float]:
        touches_current = (
            conflict.object_id_a in current_object_ids
            or conflict.object_id_b in current_object_ids
        )
        return (
            severity_rank(conflict.severity),
            0 if touches_current else 1,
            -parse_utc_timestamp(conflict.created_at).timestamp(),
        )

    return tuple(sorted(conflicts, key=sort_key))


def active_work_priority(
    *,
    pending_context: tuple[ContextRecord, ...],
    conflicts: tuple[ConflictRecord, ...],
    react_now_context: tuple[ContextRecord, ...] = (),
) -> dict[str, object] | None:
    if conflicts:
        conflict = conflicts[0]
        return {
            "kind": "conflict",
            "id": conflict.id,
            "summary": conflict.summary,
            "next_step": f'loom resolve {conflict.id} --note "<resolution>"',
            "tool_name": "loom_resolve",
            "tool_arguments": {"conflict_id": conflict.id},
            "reason": "Loom found an active conflict touching the current work.",
            "confidence": "high",
        }
    if react_now_context:
        entry = react_now_context[0]
        return {
            "kind": "context",
            "id": entry.id,
            "summary": f"{entry.topic} from {entry.agent_id}",
            "next_step": f"loom context ack {entry.id} --status read",
            "tool_name": "loom_context_ack",
            "tool_arguments": {"context_id": entry.id, "status": "read"},
            "reason": "Loom found pending context directly related to the current work.",
            "confidence": "high",
        }
    if pending_context:
        entry = pending_context[0]
        return {
            "kind": "context",
            "id": entry.id,
            "summary": f"{entry.topic} from {entry.agent_id}",
            "next_step": f"loom context ack {entry.id} --status read",
            "tool_name": "loom_context_ack",
            "tool_arguments": {"context_id": entry.id, "status": "read"},
            "reason": "Loom found pending context that may affect the current work.",
            "confidence": "medium",
        }
    return None


def _expired_lease_entries(
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> tuple[dict[str, str], ...]:
    expired: list[dict[str, str]] = []
    if claim is not None and claim.lease_expires_at and is_past_utc_timestamp(claim.lease_expires_at):
        expired.append(
            {
                "kind": "claim",
                "id": claim.id,
                "description": claim.description,
                "lease_expires_at": claim.lease_expires_at,
                "lease_policy": normalize_lease_policy(
                    claim.lease_policy,
                    allow_none=True,
                )
                or DEFAULT_LEASE_POLICY,
            }
        )
    if intent is not None and intent.lease_expires_at and is_past_utc_timestamp(intent.lease_expires_at):
        expired.append(
            {
                "kind": "intent",
                "id": intent.id,
                "description": intent.description,
                "lease_expires_at": intent.lease_expires_at,
                "lease_policy": normalize_lease_policy(
                    intent.lease_policy,
                    allow_none=True,
                )
                or DEFAULT_LEASE_POLICY,
            }
        )
    return tuple(expired)


def active_work_lease_alert(
    *,
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> dict[str, object] | None:
    expired = _expired_lease_entries(claim=claim, intent=intent)
    if not expired:
        return None
    if len(expired) == 1:
        subject = f"{expired[0]['kind']} lease"
    else:
        subject = "claim and intent leases"
    policies = {
        str(item.get("lease_policy", DEFAULT_LEASE_POLICY) or DEFAULT_LEASE_POLICY)
        for item in expired
    }
    if "yield" in policies:
        return {
            "expired": expired,
            "policy": "yield",
            "summary": f"Yield the expired {subject} before continuing current work.",
            "next_step": "loom finish",
            "tool_name": "loom_finish",
            "tool_arguments": {"agent_id": agent_id},
            "reason": "Loom found active work configured to yield when its coordination lease expires.",
            "confidence": "high",
        }
    if "finish" in policies:
        return {
            "expired": expired,
            "policy": "finish",
            "summary": f"Finish the expired {subject} instead of renewing it.",
            "next_step": "loom finish",
            "tool_name": "loom_finish",
            "tool_arguments": {"agent_id": agent_id},
            "reason": "Loom found active work configured to finish when its coordination lease expires.",
            "confidence": "high",
        }
    return {
        "expired": expired,
        "policy": "renew",
        "summary": f"Renew the expired {subject} before continuing current work.",
        "next_step": "loom renew",
        "tool_name": "loom_renew",
        "tool_arguments": {"agent_id": agent_id},
        "reason": "Loom found active work whose coordination lease has expired.",
        "confidence": "high",
    }


def active_work_yield_alert(
    *,
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    react_now_context: tuple[ContextRecord, ...],
    conflicts: tuple[ConflictRecord, ...],
) -> dict[str, object] | None:
    if not conflicts and not react_now_context:
        return None
    has_yield_policy = any(
        normalize_lease_policy(getattr(record, "lease_policy", None), allow_none=True) == "yield"
        for record in (claim, intent)
        if record is not None and getattr(record, "lease_expires_at", None)
    )
    if not has_yield_policy:
        return None
    if conflicts:
        reason = "Loom found higher-priority conflict pressure and this leased work is configured to yield."
    else:
        reason = "Loom found directly relevant context and this leased work is configured to yield."
    return {
        "policy": "yield",
        "summary": "Yield the current leased work before continuing under coordination pressure.",
        "next_step": "loom finish",
        "tool_name": "loom_finish",
        "tool_arguments": {"agent_id": agent_id},
        "reason": reason,
        "confidence": "high",
    }


def latest_recent_handoff(
    *,
    store: CoordinationStore,
    agent_id: str,
) -> ContextRecord | None:
    return _state_latest_recent_handoff(
        store=store,
        agent_id=agent_id,
        is_stale_timestamp=is_stale_utc_timestamp,
    )


def agent_presence_is_stale(presence: AgentPresenceRecord) -> bool:
    return _state_agent_presence_is_stale(
        presence,
        is_stale_timestamp=is_stale_utc_timestamp,
    )


def agent_presence_has_expired_lease(presence: AgentPresenceRecord) -> bool:
    return _state_agent_presence_has_expired_lease(
        presence,
        is_past_timestamp=is_past_utc_timestamp,
    )


def stale_agent_ids(agents: tuple[AgentPresenceRecord, ...]) -> set[str]:
    return _state_stale_agent_ids(
        agents,
        is_stale_timestamp=is_stale_utc_timestamp,
        is_past_timestamp=is_past_utc_timestamp,
    )


def active_work_nearby_yield_alert(
    *,
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    snapshot: object | None,
    store: CoordinationStore | None = None,
    stale_agent_ids: set[str] | None = None,
) -> dict[str, object] | None:
    return _state_active_work_nearby_yield_alert(
        agent_id=agent_id,
        claim=claim,
        intent=intent,
        snapshot=snapshot,
        store=store,
        stale_agent_ids=stale_agent_ids,
        is_stale_timestamp=is_stale_utc_timestamp,
        is_past_timestamp=is_past_utc_timestamp,
    )


def repo_lanes_payload(
    *,
    agents: tuple[AgentPresenceRecord, ...],
    snapshot: object | None,
    store: CoordinationStore | None,
    stale_agent_ids: set[str] | None = None,
) -> dict[str, object]:
    return _state_repo_lanes_payload(
        agents=agents,
        snapshot=snapshot,
        store=store,
        stale_agent_ids=stale_agent_ids,
        is_stale_timestamp=is_stale_utc_timestamp,
        is_past_timestamp=is_past_utc_timestamp,
    )


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
    started_at = active_work_started_at(claim=claim, intent=intent)
    if started_at is None:
        return {
            "started_at": None,
            "pending_context": (),
            "react_now_context": (),
            "review_soon_context": (),
            "conflicts": (),
            "events": (),
            "needs_attention": False,
            "priority": None,
            "context_reactions": {},
            "lease_alert": None,
            "yield_alert": None,
            "expired_leases": (),
        }

    started_at_value = parse_utc_timestamp(started_at)
    active_scope = active_scope_for_worktree(claim=claim, intent=intent)
    lease_alert = active_work_lease_alert(
        agent_id=agent_id,
        claim=claim,
        intent=intent,
    )
    context_reactions = {
        entry.id: active_work_context_reaction(
            entry,
            claim=claim,
            intent=intent,
            active_scope=active_scope,
        )
        for entry in pending_context
    }
    prioritized_context = prioritize_active_work_context(
        pending_context,
        claim=claim,
        intent=intent,
        active_scope=active_scope,
    )
    prioritized_conflicts = prioritize_active_work_conflicts(
        conflicts,
        claim=claim,
        intent=intent,
    )
    react_now_context = tuple(
        entry
        for entry in prioritized_context
        if context_reactions.get(entry.id, "review soon") == "react now"
    )
    review_soon_context = tuple(
        entry
        for entry in prioritized_context
        if context_reactions.get(entry.id, "review soon") != "react now"
    )
    priority = active_work_priority(
        pending_context=prioritized_context,
        conflicts=prioritized_conflicts,
        react_now_context=react_now_context,
    )
    yield_alert = None
    if lease_alert is None:
        yield_alert = active_work_yield_alert(
            agent_id=agent_id,
            claim=claim,
            intent=intent,
            react_now_context=react_now_context,
            conflicts=prioritized_conflicts,
        )
    history = store.list_agent_events(
        agent_id=agent_id,
        context_limit=context_limit,
        limit=None,
        created_after=started_at,
        ascending=True,
    )
    if not isinstance(history, (list, tuple)):
        history = ()
    events = tuple(
        event
        for event in history
        if parse_utc_timestamp(event.timestamp) > started_at_value
    )
    if event_limit > 0 and len(events) > event_limit:
        events = events[-event_limit:]
    return {
        "started_at": started_at,
        "pending_context": prioritized_context,
        "react_now_context": react_now_context,
        "review_soon_context": review_soon_context,
        "conflicts": prioritized_conflicts,
        "events": events,
        "needs_attention": bool(
            prioritized_context or prioritized_conflicts or lease_alert or yield_alert
        ),
        "priority": priority,
        "context_reactions": context_reactions,
        "lease_alert": lease_alert,
        "yield_alert": yield_alert,
        "expired_leases": () if lease_alert is None else tuple(lease_alert.get("expired", ())),
    }


def agent_recommendation(
    *,
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    has_published_context: bool,
    active_work: dict[str, object],
    worktree_signal: dict[str, object],
) -> dict[str, object] | None:
    lease_alert = lease_alert_recommendation(active_work.get("lease_alert"))
    yield_alert = yield_alert_recommendation(active_work.get("yield_alert"))
    if lease_alert is not None and active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    ):
        return finish_recommendation()
    if lease_alert is not None:
        return lease_alert
    if yield_alert is not None:
        return yield_alert
    priority = priority_recommendation(active_work.get("priority"))
    if priority is not None:
        return priority
    if active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    ):
        return finish_recommendation()
    if worktree_signal.get("has_drift"):
        return worktree_adoption_recommendation(
            has_active_scope=claim is not None or intent is not None,
            suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ())),
            agent_id=agent_id,
        )
    if claim is None and intent is None and not has_published_context:
        return claim_recommendation(
            summary="Start a new claimed task for this agent.",
            reason="This agent has no active claim, intent, or published context.",
            confidence="medium",
            agent_id=agent_id,
        )
    if claim is not None and intent is None:
        return intent_recommendation(
            summary="Declare intent before broadening the edit for this agent.",
            reason="This agent has an active claim but no intent yet.",
            confidence="medium",
            agent_id=agent_id,
        )
    return recommendation(
        command="loom status",
        tool_name="loom_status",
        tool_arguments={},
        summary="Compare this agent with the rest of the repository.",
        reason="This agent already has active coordination state and Loom does not see a sharper single next move.",
        confidence="low",
    )


def resume_recommendation(
    *,
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    active_work: dict[str, object],
    worktree_signal: dict[str, object],
    recent_handoff: ContextRecord | None = None,
) -> dict[str, object] | None:
    lease_alert = lease_alert_recommendation(active_work.get("lease_alert"))
    yield_alert = yield_alert_recommendation(active_work.get("yield_alert"))
    if lease_alert is not None and active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    ):
        return finish_recommendation()
    if lease_alert is not None:
        return lease_alert
    if yield_alert is not None:
        return yield_alert
    priority = priority_recommendation(active_work.get("priority"))
    if priority is not None:
        return priority
    if active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    ):
        return finish_recommendation()
    if recent_handoff is not None and active_work.get("started_at") is None:
        return handoff_recommendation(handoff=recent_handoff, agent_id=agent_id)
    if worktree_signal.get("has_drift"):
        return worktree_adoption_recommendation(
            has_active_scope=claim is not None or intent is not None,
            suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ())),
            agent_id=agent_id,
        )
    if claim is not None or intent is not None:
        return recommendation(
            command="loom agent",
            tool_name="loom_agent",
            tool_arguments={"agent_id": agent_id},
            summary="Focus on this agent's active work before continuing.",
            reason="This agent still has active work and Loom does not see a sharper recovery action.",
            confidence="medium",
        )
    return recommendation(
        command="loom start",
        tool_name="loom_start",
        tool_arguments={},
        summary="Ask Loom what this agent should do next before resuming work.",
        reason="There is no active work or recent handoff for this agent yet.",
        confidence="medium",
    )


def inbox_attention_payload(
    *,
    pending_context_count: int,
    conflict_count: int,
) -> dict[str, int]:
    return {
        "pending_context": pending_context_count,
        "active_conflicts": conflict_count,
    }


def inbox_attention_text(
    *,
    pending_context_count: int,
    conflict_count: int,
) -> str:
    attention: list[str] = []
    if pending_context_count:
        attention.append(f"{pending_context_count} pending context")
    if conflict_count:
        attention.append(f"{conflict_count} active conflicts")
    return "clear" if not attention else ", ".join(attention)


def agent_attention_payload(
    *,
    pending_context_count: int,
    conflict_count: int,
    worktree_drift_count: int,
    expired_lease_count: int = 0,
) -> dict[str, int]:
    return {
        "pending_context": pending_context_count,
        "active_conflicts": conflict_count,
        "worktree_drift": worktree_drift_count,
        "expired_leases": expired_lease_count,
    }


def agent_attention_text(
    *,
    pending_context_count: int,
    conflict_count: int,
    worktree_drift_count: int,
    expired_lease_count: int = 0,
) -> str:
    attention: list[str] = []
    if pending_context_count:
        attention.append(f"{pending_context_count} pending context")
    if conflict_count:
        attention.append(f"{conflict_count} active conflicts")
    if worktree_drift_count:
        attention.append(f"{worktree_drift_count} worktree drift path(s)")
    if expired_lease_count:
        attention.append(f"{expired_lease_count} expired lease(s)")
    return "clear" if not attention else ", ".join(attention)


def start_attention_payload(
    *,
    snapshot: object | None = None,
    inbox_snapshot: object | None = None,
    worktree_signal: dict[str, object] | None = None,
    repo_lanes: dict[str, object] | None = None,
) -> dict[str, int]:
    return {
        "claims": 0 if snapshot is None else len(tuple(getattr(snapshot, "claims", ()))),
        "intents": 0 if snapshot is None else len(tuple(getattr(snapshot, "intents", ()))),
        "context": 0 if snapshot is None else len(tuple(getattr(snapshot, "context", ()))),
        "conflicts": 0 if snapshot is None else len(tuple(getattr(snapshot, "conflicts", ()))),
        "pending_context": (
            0
            if inbox_snapshot is None
            else len(tuple(getattr(inbox_snapshot, "pending_context", ())))
        ),
        "agent_conflicts": (
            0
            if inbox_snapshot is None
            else len(tuple(getattr(inbox_snapshot, "conflicts", ())))
        ),
        "worktree_drift": (
            0
            if worktree_signal is None
            else len(tuple(worktree_signal.get("drift_paths", ())))
        ),
        "acknowledged_migration_lanes": (
            0
            if repo_lanes is None
            else int(repo_lanes.get("acknowledged_migration_lanes", 0))
        ),
    }


def start_summary(
    *,
    project_initialized: bool,
    identity: dict[str, object],
    snapshot: object | None = None,
    agent_snapshot: object | None = None,
    inbox_snapshot: object | None = None,
    active_work: dict[str, object] | None = None,
    repo_lanes: dict[str, object] | None = None,
    recent_handoff: object | None = None,
    worktree_signal: dict[str, object] | None = None,
) -> tuple[str, str]:
    agent_id = str(identity["id"])
    if not project_initialized:
        return ("uninitialized", "Loom is not initialized in this repository yet.")
    if identity.get("source") == "tty":
        return (
            "needs_identity",
            f"{agent_id} is a raw terminal identity. Resolve a stable agent before coordinated work.",
        )
    if identity.get("source") == "terminal" and identity_needs_env_binding(identity):
        return (
            "needs_identity",
            f"{agent_id} is bound for this command, but this shell still needs LOOM_AGENT for repeatable coordination.",
        )
    if active_work is not None and active_work.get("started_at") is not None:
        if active_work.get("lease_alert") is not None:
            lease_policy = str(active_work["lease_alert"].get("policy", DEFAULT_LEASE_POLICY))
            if active_work_completion_ready(
                active_work=active_work,
                worktree_signal=worktree_signal,
            ):
                return (
                    "active",
                    f"{agent_id}'s current work looks settled and its coordination lease expired; finish truthfully if this session is done.",
                )
            if lease_policy == "yield":
                return (
                    "attention",
                    f"{agent_id}'s current work lease expired and should yield or finish before continuing.",
                )
            if lease_policy == "finish":
                return (
                    "attention",
                    f"{agent_id}'s current work lease expired and should be finished before continuing.",
                )
            return (
                "attention",
                f"{agent_id}'s current work lease expired and should be renewed or finished before continuing.",
            )
        if active_work.get("yield_alert") is not None:
            return (
                "attention",
                f"{agent_id}'s current work is configured to yield and Loom found higher-priority coordination pressure.",
            )
        priority = active_work.get("priority")
        if isinstance(priority, dict):
            return (
                "attention",
                f"{agent_id} should react to {priority['kind']} {priority['id']} before continuing current work.",
            )
        if active_work_completion_ready(
            active_work=active_work,
            worktree_signal=worktree_signal,
        ):
            return (
                "active",
                f"{agent_id}'s current work looks settled; finish truthfully if this session is done.",
            )
    attention = start_attention_payload(
        snapshot=snapshot,
        inbox_snapshot=inbox_snapshot,
        worktree_signal=worktree_signal,
        repo_lanes=repo_lanes,
    )
    if attention["pending_context"] or attention["agent_conflicts"]:
        parts: list[str] = []
        if attention["pending_context"]:
            parts.append(f"{attention['pending_context']} pending context")
        if attention["agent_conflicts"]:
            parts.append(f"{attention['agent_conflicts']} active conflicts")
        return ("attention", f"{agent_id} has {', '.join(parts)}.")
    if attention["worktree_drift"]:
        if agent_snapshot is not None and (
            getattr(agent_snapshot, "claim", None) is not None
            or getattr(agent_snapshot, "intent", None) is not None
        ):
            return (
                "attention",
                f"{agent_id} has {attention['worktree_drift']} changed path(s) outside the current claim/intent scope.",
            )
        return (
            "attention",
            f"{agent_id} has {attention['worktree_drift']} changed path(s) with no active claim or intent.",
        )
    if recent_handoff is not None:
        return (
            "active",
            f"{agent_id} has a recent handoff from a prior session worth resuming.",
        )
    if attention["acknowledged_migration_lanes"]:
        return (
            "active",
            "The repository already has acknowledged migration work in flight.",
        )
    claims = 0 if snapshot is None else len(tuple(getattr(snapshot, "claims", ())))
    intents = 0 if snapshot is None else len(tuple(getattr(snapshot, "intents", ())))
    context = 0 if snapshot is None else len(tuple(getattr(snapshot, "context", ())))
    conflicts = 0 if snapshot is None else len(tuple(getattr(snapshot, "conflicts", ())))
    if claims == 0 and intents == 0 and context == 0 and conflicts == 0:
        return (
            "ready",
            f"{agent_id} is ready to start the first coordinated task.",
        )
    if agent_snapshot is not None:
        claim = getattr(agent_snapshot, "claim", None)
        intent = getattr(agent_snapshot, "intent", None)
        if claim is not None and intent is None:
            return (
                "active",
                f"{agent_id} has an active claim and may want to declare intent before widening the edit.",
            )
    if conflicts:
        return ("attention", f"The repo has {conflicts} active conflict(s).")
    if context:
        return (
            "active",
            f"The repo has {context} recent context note(s) worth checking.",
        )
    return (
        "active",
        f"The repo is active with {claims} claim(s) and {intents} intent(s).",
    )


def start_recommendation(
    *,
    project_initialized: bool,
    identity_recommendation: dict[str, object] | None,
    agent_id: str,
    snapshot: object | None = None,
    agent_snapshot: object | None = None,
    inbox_snapshot: object | None = None,
    active_work: dict[str, object] | None = None,
    repo_lanes: dict[str, object] | None = None,
    worktree_signal: dict[str, object] | None = None,
    recent_handoff: ContextRecord | None = None,
) -> dict[str, object] | None:
    if not project_initialized:
        return recommendation(
            command="loom init --no-daemon",
            tool_name="loom_init",
            tool_arguments={},
            summary="Initialize Loom in this repository.",
            reason="Loom is not initialized yet.",
            confidence="high",
        )
    if identity_recommendation is not None:
        return identity_recommendation
    lease_alert = None if active_work is None else lease_alert_recommendation(active_work.get("lease_alert"))
    yield_alert = None if active_work is None else yield_alert_recommendation(active_work.get("yield_alert"))
    if lease_alert is not None and active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    ):
        return finish_recommendation()
    if lease_alert is not None:
        return lease_alert
    if yield_alert is not None:
        return yield_alert
    priority = None if active_work is None else priority_recommendation(active_work.get("priority"))
    if priority is not None:
        return priority
    if inbox_snapshot is not None and (
        tuple(getattr(inbox_snapshot, "pending_context", ()))
        or tuple(getattr(inbox_snapshot, "conflicts", ()))
    ):
        return inspect_inbox_recommendation(
            agent_id=agent_id,
            summary="Inspect pending coordination for this agent.",
            reason="The inbox has pending coordination items but Loom does not see a single stronger priority than reviewing them.",
            confidence="high",
        )
    if worktree_signal is not None and worktree_signal.get("has_drift"):
        claim = None if agent_snapshot is None else getattr(agent_snapshot, "claim", None)
        intent = None if agent_snapshot is None else getattr(agent_snapshot, "intent", None)
        return worktree_adoption_recommendation(
            has_active_scope=claim is not None or intent is not None,
            suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ())),
            agent_id=agent_id,
        )
    if recent_handoff is not None:
        return handoff_recommendation(
            handoff=recent_handoff,
            agent_id=agent_id,
        )
    if (
        isinstance(repo_lanes, dict)
        and int(repo_lanes.get("acknowledged_migration_lanes", 0))
    ):
        return recommendation(
            command="loom status",
            tool_name="loom_status",
            tool_arguments={},
            summary="Inspect the acknowledged migration work already active in this repository.",
            reason="Loom sees acknowledged long-running coordinated change already in flight.",
            confidence="medium",
        )
    if active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    ):
        return finish_recommendation()
    if snapshot is not None:
        claims = tuple(getattr(snapshot, "claims", ()))
        intents = tuple(getattr(snapshot, "intents", ()))
        context = tuple(getattr(snapshot, "context", ()))
        conflicts = tuple(getattr(snapshot, "conflicts", ()))
        if not claims and not intents and not context and not conflicts:
            return claim_recommendation(
                summary="Start the first coordinated task in this repository.",
                reason="The repository is initialized and currently has no active coordination state.",
                confidence="medium",
                agent_id=agent_id,
            )
        if conflicts:
            return inspect_conflicts_recommendation(
                summary="Inspect active overlaps in the repository.",
                reason="The repository has active conflicts that should be understood first.",
                confidence="high",
            )
        if context:
            return inspect_inbox_recommendation(
                agent_id=agent_id,
                summary="Inspect recent coordination that may affect this agent.",
                reason="The repository has recent context that may affect this agent's plan.",
                confidence="medium",
            )
    if agent_snapshot is not None:
        claim = getattr(agent_snapshot, "claim", None)
        intent = getattr(agent_snapshot, "intent", None)
        if claim is not None and intent is None:
            return intent_recommendation(
                summary="Declare intent before broadening the edit.",
                reason="This agent has an active claim but no intent yet.",
                confidence="medium",
                agent_id=agent_id,
            )
    return None


def status_recommendation(
    *,
    agent_id: str,
    store: CoordinationStore | None = None,
    snapshot: object,
    worktree_signal: dict[str, object] | None = None,
    stale_agent_ids: set[str] | None = None,
    repo_lanes: dict[str, object] | None = None,
    empty_recommendation: dict[str, object],
    identity_recommendation: dict[str, object] | None = None,
) -> dict[str, object]:
    claims = tuple(getattr(snapshot, "claims", ()))
    intents = tuple(getattr(snapshot, "intents", ()))
    context = tuple(getattr(snapshot, "context", ()))
    conflicts = tuple(getattr(snapshot, "conflicts", ()))
    current_claim = next(
        (claim for claim in claims if getattr(claim, "agent_id", None) == agent_id and getattr(claim, "status", "") == "active"),
        None,
    )
    current_intent = next(
        (intent for intent in intents if getattr(intent, "agent_id", None) == agent_id and getattr(intent, "status", "") == "active"),
        None,
    )
    lease_alert = lease_alert_recommendation(
        active_work_lease_alert(
            agent_id=agent_id,
            claim=current_claim,
            intent=current_intent,
        )
    )
    nearby_yield_alert = yield_alert_recommendation(
        active_work_nearby_yield_alert(
            agent_id=agent_id,
            claim=current_claim,
            intent=current_intent,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=stale_agent_ids,
        )
    )
    if worktree_signal is not None and worktree_signal.get("has_drift"):
        if claims or intents:
            return focus_agent_recommendation(
                agent_id=agent_id,
                summary="Focus on the current agent before widening Loom scope.",
                reason="Changed files fall outside the current Loom scope while the repository already has active coordination.",
                confidence="high",
            )
        return worktree_adoption_recommendation(
            has_active_scope=False,
            suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ())),
            agent_id=agent_id,
        )
    if lease_alert is not None:
        return lease_alert
    if nearby_yield_alert is not None:
        return nearby_yield_alert
    if not claims and not intents and not context and not conflicts:
        if identity_recommendation is not None:
            return identity_recommendation
        return empty_recommendation
    if conflicts:
        return inspect_conflicts_recommendation(
            summary="Inspect active overlaps in the repository.",
            reason="The repository has active conflicts that should be understood first.",
            confidence="high",
        )
    if context:
        return inspect_inbox_recommendation(
            agent_id=agent_id,
            summary="Inspect recent coordination for this agent.",
            reason="The repository has recent context that may affect this agent's plan.",
            confidence="medium",
        )
    if (
        isinstance(repo_lanes, dict)
        and int(repo_lanes.get("acknowledged_migration_lanes", 0))
    ):
        return focus_agent_recommendation(
            agent_id=agent_id,
            summary="Inspect the acknowledged migration work already active in this repository.",
            reason="Loom sees acknowledged long-running coordinated change already in flight.",
            confidence="medium",
        )
    return focus_agent_recommendation(
        agent_id=agent_id,
        summary="Focus on this agent's coordination state.",
        reason="The repository is active and the next best move is to narrow from repo state to this agent's state.",
        confidence="medium",
    )


def active_work_completion_ready(
    *,
    active_work: dict[str, object] | None,
    worktree_signal: dict[str, object] | None = None,
) -> bool:
    if active_work is None or active_work.get("started_at") is None:
        return False
    if bool(active_work.get("needs_attention")) and active_work.get("lease_alert") is None:
        return False
    if worktree_signal is not None and bool(worktree_signal.get("has_drift")):
        return False
    changed_paths = ()
    if worktree_signal is not None:
        changed_paths = tuple(str(path) for path in worktree_signal.get("changed_paths", ()))
    return not changed_paths
