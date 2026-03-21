from __future__ import annotations

import json
from collections.abc import Callable

from .action_errors import (
    recoverable_error_code,
)
from .guidance import (
    DEFAULT_RENEW_LEASE_MINUTES,
    active_work_completion_ready as guidance_active_work_completion_ready,
    agent_step_order as guidance_agent_step_order,
    agents_step_order as guidance_agents_step_order,
    identity_has_stable_coordination as guidance_identity_has_stable_coordination,
    onboarding_step_order as guidance_onboarding_step_order,
    start_drift_step_order as guidance_start_drift_step_order,
    start_followup_step_order as guidance_start_followup_step_order,
    start_step_order as guidance_start_step_order,
    status_step_order as guidance_status_step_order,
)
from .util import is_past_utc_timestamp


def tool_onboarding_steps(*, has_stable_identity: bool) -> tuple[str, ...]:
    steps: list[str] = []
    for key in guidance_onboarding_step_order(has_stable_identity=has_stable_identity):
        if key == "start":
            steps.append("Call loom_start to ask Loom what to do next in this repository.")
        elif key == "bind":
            steps.append(tool_bind_step())
        elif key == "claim":
            if has_stable_identity:
                steps.append(
                    'Call loom_claim with description="Describe the work you\'re starting" '
                    'and scope=["path/to/area"].'
                )
            else:
                steps.append(
                    'Call loom_claim with description="Describe the work you\'re starting" '
                    'and scope=["path/to/area"], or keep passing agent_id on write tools.'
                )
        elif key == "status":
            steps.append("Call loom_status to confirm the current coordination state.")
    return tuple(steps)


def tool_claim_step(
    *,
    scope: tuple[str, ...] = (),
    description: str = "Describe the work you're starting",
) -> str:
    if not scope:
        return f'Call loom_claim with description="{description}" and scope=["path/to/area"].'
    return (
        f'Call loom_claim with description="{description}" '
        f"and scope={json.dumps(list(scope))}."
    )


def tool_intent_step(*, scope: tuple[str, ...] = ()) -> str:
    if not scope:
        return (
            'Call loom_intent with description="Describe the edit you\'re about to make" '
            'and scope=["path/to/area"].'
        )
    return (
        'Call loom_intent with description="Describe the edit you\'re about to make" '
        f"and scope={json.dumps(list(scope))}."
    )


def tool_renew_step(*, lease_minutes: int = DEFAULT_RENEW_LEASE_MINUTES) -> str:
    if lease_minutes == DEFAULT_RENEW_LEASE_MINUTES:
        return "Call loom_renew to extend the current coordination lease."
    return (
        f"Call loom_renew with lease_minutes={lease_minutes} "
        "to extend the current coordination lease."
    )


def tool_finish_step() -> str:
    return "Call loom_finish to publish an optional handoff and release current work."


def tool_clean_step() -> str:
    return "Call loom_clean to close dead pid-based session work and prune idle history."


def tool_clean_next_steps() -> tuple[str, ...]:
    return (
        "Call loom_status to compare the updated repo state.",
        "Call loom_agents to inspect the remaining agents.",
        "Call loom_start to ask Loom what to do next in this repository.",
    )


def tool_bind_step() -> str:
    return 'Call loom_bind with agent_id="<agent-name>" to pin this MCP session to a stable agent identity.'


def tool_priority_step(priority: dict[str, object]) -> str:
    tool_name = str(priority.get("tool_name", "")).strip()
    tool_arguments = priority.get("tool_arguments", {})
    if tool_name == "loom_resolve" and isinstance(tool_arguments, dict):
        conflict_id = str(tool_arguments.get("conflict_id", "")).strip()
        if conflict_id:
            return (
                f'Call loom_resolve with conflict_id="{conflict_id}" '
                'and note="<resolution>".'
            )
    if tool_name == "loom_context_ack" and isinstance(tool_arguments, dict):
        context_id = str(tool_arguments.get("context_id", "")).strip()
        status = str(tool_arguments.get("status", "")).strip() or "read"
        if context_id:
            return (
                f'Call loom_context_ack with context_id="{context_id}" '
                f'and status="{status}".'
            )
    if tool_name == "loom_renew":
        lease_minutes = DEFAULT_RENEW_LEASE_MINUTES
        if isinstance(tool_arguments, dict) and "lease_minutes" in tool_arguments:
            raw_lease_minutes = tool_arguments.get("lease_minutes")
            if isinstance(raw_lease_minutes, int) and raw_lease_minutes > 0:
                lease_minutes = raw_lease_minutes
        return tool_renew_step(lease_minutes=lease_minutes)
    if tool_name == "loom_finish":
        return tool_finish_step()
    next_step = str(priority.get("next_step", "")).strip()
    if next_step:
        return f"Use {next_step}."
    return "Call loom_agent for a focused agent view."


def tool_start_step(
    key: str,
    *,
    project_initialized: bool,
    priority: dict[str, object] | None = None,
    recent_handoff: object | None = None,
    suggested_scope: tuple[str, ...] = (),
) -> str:
    if key == "init":
        return "Call loom_init to initialize Loom in this repository."
    if key == "bind":
        if project_initialized:
            return tool_bind_step()
        return 'Call loom_init with default_agent="<agent-name>" to pin a stable agent identity.'
    if key == "claim":
        return tool_claim_step(scope=suggested_scope)
    if key == "intent":
        return tool_intent_step(scope=suggested_scope)
    if key == "clean":
        return tool_clean_step()
    if key == "start":
        return "Call loom_start to ask Loom what to do next in this repository."
    if key == "priority" and isinstance(priority, dict):
        return tool_priority_step(priority)
    if key == "inbox":
        return "Call loom_inbox for the affected agent."
    if key == "conflicts":
        return "Call loom_conflicts to inspect active overlaps."
    if key == "status":
        return "Call loom_status to compare the repo state."
    if key == "agent":
        return "Call loom_agent for a focused agent view."
    if key == "finish":
        return tool_finish_step()
    if key == "handoff":
        return tool_claim_step(scope=tuple(getattr(recent_handoff, "scope", ())))
    raise ValueError(f"Unsupported MCP start step key: {key}")


def tool_start_next_steps(
    *,
    project: object | None,
    identity: dict[str, object],
    dead_session_count: int = 0,
    snapshot: object | None = None,
    agent_snapshot: object | None = None,
    inbox_snapshot: object | None = None,
    active_work: dict[str, object] | None = None,
    worktree_signal: dict[str, object] | None = None,
    recent_handoff: object | None = None,
    authority: dict[str, object] | None = None,
) -> tuple[str, ...]:
    authority_recovery_steps = _tool_authority_recovery_steps(
        authority,
        rerun_step="Call loom_start to ask Loom what to do next in this repository.",
    )
    if authority_recovery_steps:
        return authority_recovery_steps
    if project is not None and dead_session_count:
        return (
            tool_clean_step(),
            "Call loom_status to compare the updated repo state.",
            "Call loom_agents to inspect the remaining agents.",
        )
    completion_ready = guidance_active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    )
    has_worktree_drift = bool(worktree_signal is not None and worktree_signal.get("has_drift"))
    priority = None
    if active_work is not None:
        priority = (
            active_work.get("lease_alert")
            or active_work.get("yield_alert")
            or active_work.get("priority")
        )
    step_order = guidance_start_step_order(
        project_initialized=project is not None,
        has_raw_terminal_identity=identity.get("source") == "tty",
        has_inbox_attention=bool(
            inbox_snapshot is not None
            and (
                tuple(getattr(inbox_snapshot, "pending_context", ()))
                or tuple(getattr(inbox_snapshot, "conflicts", ()))
            )
        ),
        has_priority=isinstance(priority, dict)
        and bool(str(priority.get("next_step", "")).strip()),
    )
    if step_order:
        return tuple(
            tool_start_step(
                key,
                project_initialized=project is not None,
                priority=priority if isinstance(priority, dict) else None,
            )
            for key in step_order
        )
    repo_is_empty = bool(
        snapshot is not None
        and not tuple(getattr(snapshot, "claims", ()))
        and not tuple(getattr(snapshot, "intents", ()))
        and not tuple(getattr(snapshot, "context", ()))
        and not tuple(getattr(snapshot, "conflicts", ()))
    )
    followup_order = guidance_start_followup_step_order(
        has_recent_handoff=recent_handoff is not None and not has_worktree_drift,
        completion_ready=completion_ready,
        repo_is_empty=repo_is_empty and not has_worktree_drift,
    )
    if followup_order:
        return tuple(
            tool_start_step(
                key,
                project_initialized=project is not None,
                recent_handoff=recent_handoff,
                suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
                if worktree_signal is not None
                else (),
            )
            for key in followup_order
        )
    authority_focus_steps = _tool_authority_focus_steps(
        authority,
        rerun_step="Call loom_status to compare the repo state.",
    )
    if authority_focus_steps:
        return authority_focus_steps
    if worktree_signal is not None and worktree_signal.get("has_drift") and agent_snapshot is not None:
        suggested_scope = tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
        return tuple(
            tool_start_step(
                key,
                project_initialized=project is not None,
                suggested_scope=suggested_scope,
            )
            for key in guidance_start_drift_step_order(
                has_active_scope=getattr(agent_snapshot, "claim", None) is not None
                or getattr(agent_snapshot, "intent", None) is not None,
            )
        )
    if snapshot is not None:
        claims = tuple(getattr(snapshot, "claims", ()))
        intents = tuple(getattr(snapshot, "intents", ()))
        context = tuple(getattr(snapshot, "context", ()))
        conflicts = tuple(getattr(snapshot, "conflicts", ()))
        if conflicts or context:
            return tool_status_next_steps(snapshot=snapshot, identity=identity)
    if agent_snapshot is not None:
        return tool_agent_next_steps(
            agent=agent_snapshot,
            active_work=active_work,
            worktree_signal=worktree_signal,
        )
    return (
        "Call loom_status to compare the repo state.",
        "Call loom_agent for a focused agent view.",
        "Call loom_inbox for pending coordination work.",
    )


def tool_whoami_next_steps(
    *,
    project: object | None,
    identity: dict[str, object],
) -> tuple[str, ...]:
    if project is None:
        return ('Call loom_init to initialize Loom in this repository.',)
    if identity.get("source") == "tty":
        return (
            tool_bind_step(),
            "Call loom_start to ask Loom what to do next in this repository.",
            'Call loom_claim with description="Describe the work you\'re starting" '
            'and scope=["path/to/area"].',
        )
    return (
        "Call loom_start to ask Loom what to do next in this repository.",
        'Call loom_claim with description="Describe the work you\'re starting" '
        'and scope=["path/to/area"].',
        "Call loom_status to confirm the current coordination state.",
    )


def tool_post_write_steps(*, has_conflicts: bool) -> tuple[str, ...]:
    if has_conflicts:
        return (
            "Call loom_conflicts to inspect the overlap.",
            "Call loom_inbox for the affected agent.",
            "Call loom_status to re-read repo coordination.",
        )
    return (
        "Call loom_status to confirm the updated coordination state.",
        "Call loom_context_write if you learn something another agent should know.",
    )


def tool_context_write_next_steps(*, has_conflicts: bool) -> tuple[str, ...]:
    if has_conflicts:
        return (
            "Call loom_conflicts to inspect the overlap.",
            "Call loom_inbox for the affected agent.",
            "Call loom_status to re-read repo coordination.",
        )
    return (
        "Call loom_inbox for the affected agent to watch for reactions.",
        "Call loom_status to confirm the updated coordination state.",
    )


def tool_agent_next_steps(
    *,
    agent: object,
    active_work: dict[str, object] | None,
    worktree_signal: dict[str, object] | None,
) -> tuple[str, ...]:
    claim = getattr(agent, "claim", None)
    intent = getattr(agent, "intent", None)
    published_context = tuple(getattr(agent, "published_context", ()))
    conflicts = tuple(getattr(agent, "conflicts", ()))
    pending_context = () if active_work is None else tuple(active_work.get("pending_context", ()))
    priority = None if active_work is None else active_work.get("priority")
    lease_alert = None if active_work is None else active_work.get("lease_alert")
    yield_alert = None if active_work is None else active_work.get("yield_alert")
    if guidance_active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    ):
        return (
            tool_finish_step(),
            "Call loom_status to compare this agent with the rest of the repo.",
        )
    if lease_alert is not None:
        return (
            tool_renew_step(),
            "Call loom_agent for a focused agent view.",
            "Call loom_status to compare this agent with the rest of the repo.",
        )
    if yield_alert is not None:
        return (
            tool_finish_step(),
            "Call loom_inbox for this agent to inspect the coordination pressure.",
            "Call loom_status to compare this agent with the rest of the repo.",
        )
    if pending_context or conflicts:
        if isinstance(priority, dict):
            return (
                tool_priority_step(priority),
                "Call loom_inbox for this agent to react to pending coordination.",
                "Call loom_status to compare this agent with the rest of the repo.",
            )
        return (
            "Call loom_inbox for this agent to react to pending coordination.",
            "Call loom_status to compare this agent with the rest of the repo.",
        )
    if worktree_signal is not None and worktree_signal.get("has_drift"):
        suggested_scope = tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
        if claim is not None or intent is not None:
            return (
                tool_intent_step(scope=suggested_scope),
                "Call loom_agent for a focused agent view.",
            )
        return (
            tool_claim_step(scope=suggested_scope),
            "Call loom_status to compare this agent with the rest of the repo.",
        )
    steps: list[str] = []
    for key in guidance_agent_step_order(
        has_pending_attention=False,
        has_claim=claim is not None,
        has_intent=intent is not None,
        has_published_context=bool(published_context),
    ):
        if key == "inbox":
            steps.append("Call loom_inbox for this agent to react to pending coordination.")
        elif key == "claim":
            steps.append(
                'Call loom_claim with description="Describe the work you\'re starting" '
                'and scope=["path/to/area"].'
            )
        elif key == "intent":
            steps.append(
                'Call loom_intent with description, scope, and an optional reason before '
                "you broaden the edit."
            )
        elif key == "status":
            steps.append("Call loom_status to compare this agent with the rest of the repo.")
    return tuple(steps)


def tool_inbox_next_steps(*, inbox: object) -> tuple[str, ...]:
    pending_context = tuple(getattr(inbox, "pending_context", ()))
    conflicts = tuple(getattr(inbox, "conflicts", ()))
    if pending_context or conflicts:
        return ()
    return (
        'Call loom_claim with description="Describe the work you\'re starting" '
        'and scope=["path/to/area"].',
        "Call loom_status to confirm the current coordination state.",
    )


def tool_status_next_steps(
    *,
    snapshot: object,
    identity: dict[str, object],
    dead_session_count: int = 0,
    authority: dict[str, object] | None = None,
    is_past_timestamp: Callable[[str], bool] = is_past_utc_timestamp,
) -> tuple[str, ...]:
    authority_recovery_steps = _tool_authority_recovery_steps(
        authority,
        rerun_step="Call loom_status to compare the updated repo state.",
    )
    if authority_recovery_steps:
        return authority_recovery_steps
    if dead_session_count:
        return (
            tool_clean_step(),
            "Call loom_status to compare the updated repo state.",
            "Call loom_agents to inspect the remaining agents.",
        )
    authority_focus_steps = _tool_authority_focus_steps(
        authority,
        rerun_step="Call loom_status to compare the repo state.",
    )
    if authority_focus_steps:
        return authority_focus_steps
    claims = tuple(getattr(snapshot, "claims", ()))
    intents = tuple(getattr(snapshot, "intents", ()))
    context = tuple(getattr(snapshot, "context", ()))
    conflicts = tuple(getattr(snapshot, "conflicts", ()))
    agent_id = str(identity["id"])
    current_agent_has_expired_lease = any(
        getattr(record, "agent_id", None) == agent_id
        and getattr(record, "status", "") == "active"
        and bool(getattr(record, "lease_expires_at", None))
        and is_past_timestamp(str(getattr(record, "lease_expires_at")))
        for record in (*claims, *intents)
    )
    if current_agent_has_expired_lease:
        return (
            tool_renew_step(),
            "Call loom_agent for a focused agent view.",
            "Call loom_status to confirm the current coordination state.",
        )
    has_stable_identity = guidance_identity_has_stable_coordination(identity=identity)
    steps: list[str] = []
    for key in guidance_status_step_order(
        is_empty=not claims and not intents and not context and not conflicts,
        has_conflicts=bool(conflicts),
        has_context=bool(context),
        has_stable_identity=has_stable_identity,
    ):
        if key == "start":
            steps.append("Call loom_start to ask Loom what to do next in this repository.")
        elif key == "bind":
            steps.append(tool_bind_step())
        elif key == "claim":
            if has_stable_identity:
                steps.append(
                    'Call loom_claim with description="Describe the work you\'re starting" '
                    'and scope=["path/to/area"].'
                )
            else:
                steps.append(
                    'Call loom_claim with description="Describe the work you\'re starting" '
                    'and scope=["path/to/area"], or keep passing agent_id on write tools.'
                )
        elif key == "status":
            steps.append("Call loom_status to confirm the current coordination state.")
        elif key == "conflicts":
            steps.append("Call loom_conflicts to inspect active overlaps.")
        elif key == "inbox":
            steps.append("Call loom_inbox for the affected agent.")
        elif key == "agent":
            steps.append("Call loom_agent for a focused agent view.")
        elif key == "log":
            steps.append("Call loom_log for recent coordination history.")
    return tuple(steps)


def _authority_scope(authority: dict[str, object] | None) -> tuple[str, ...]:
    if not isinstance(authority, dict):
        return ()
    scope_hints = tuple(str(path).strip() for path in authority.get("changed_scope_hints", ()))
    if scope_hints:
        return tuple(path for path in scope_hints if path)
    surfaces = tuple(authority.get("changed_surfaces", ()))
    return tuple(
        str(surface.get("path", "")).strip()
        for surface in surfaces
        if isinstance(surface, dict) and str(surface.get("path", "")).strip()
    )


def _tool_authority_recovery_steps(
    authority: dict[str, object] | None,
    *,
    rerun_step: str,
) -> tuple[str, ...]:
    if not isinstance(authority, dict) or authority.get("status") != "invalid":
        return ()
    return (
        tool_claim_step(
            scope=("loom.yaml",),
            description="Fix declared authority configuration",
        ),
        rerun_step,
    )


def _tool_authority_focus_steps(
    authority: dict[str, object] | None,
    *,
    rerun_step: str,
) -> tuple[str, ...]:
    if not isinstance(authority, dict) or authority.get("status") != "valid":
        return ()
    scope = _authority_scope(authority)
    if not scope:
        return ()
    return (
        tool_claim_step(
            scope=scope,
            description="Review repo surfaces affected by authority change",
        ),
        rerun_step,
    )


def tool_agents_next_steps(
    *,
    agent_count: int,
    identity: dict[str, object],
    dead_session_count: int = 0,
    idle_history_hidden_count: int = 0,
) -> tuple[str, ...]:
    if dead_session_count:
        return (
            tool_clean_step(),
            "Call loom_status to compare the updated repo state.",
            "Call loom_agents to inspect the remaining agents.",
        )
    if idle_history_hidden_count:
        return (
            "Call loom_agents with include_idle=true to inspect idle agent history.",
            "Call loom_status to compare the full repo state.",
            "Call loom_agent for one agent's focused view.",
        )
    has_stable_identity = guidance_identity_has_stable_coordination(identity=identity)
    steps: list[str] = []
    for key in guidance_agents_step_order(
        agent_count=agent_count,
        has_stable_identity=has_stable_identity,
    ):
        if key == "start":
            steps.append("Call loom_start to ask Loom what to do next in this repository.")
        elif key == "bind":
            steps.append(tool_bind_step())
        elif key == "claim":
            if has_stable_identity:
                steps.append(
                    'Call loom_claim with description="Describe the work you\'re starting" '
                    'and scope=["path/to/area"].'
                )
            else:
                steps.append(
                    'Call loom_claim with description="Describe the work you\'re starting" '
                    'and scope=["path/to/area"], or keep passing agent_id on write tools.'
                )
        elif key == "status":
            steps.append("Call loom_status to compare the full repo state.")
        elif key == "inbox":
            steps.append("Call loom_inbox for pending coordination work.")
        elif key == "agent":
            steps.append("Call loom_agent for one agent's focused view.")
    return tuple(steps)


def tool_conflicts_next_steps(*, conflict_count: int) -> tuple[str, ...]:
    if conflict_count:
        return (
            "Call loom_inbox for the affected agent.",
            "Call loom_status to compare the full repo state.",
        )
    return (
        'Call loom_claim with description="Describe the work you\'re starting" '
        'and scope=["path/to/area"].',
        "Call loom_status to confirm the current coordination state.",
    )


def tool_context_read_next_steps(*, entry_count: int) -> tuple[str, ...]:
    if entry_count:
        return (
            "Call loom_context_ack for notes that changed your plan.",
            "Call loom_inbox for the affected agent.",
        )
    return (
        "Call loom_context_write when you learn something another agent should know.",
        "Call loom_status to confirm the current coordination state.",
    )


def tool_context_ack_next_steps(*, status: str) -> tuple[str, ...]:
    if status == "read":
        return (
            "Call loom_inbox to keep triaging pending coordination work.",
            'Call loom_context_ack again with status="adapted" once your plan changes.',
        )
    return (
        "Call loom_inbox to confirm there is no remaining pending context.",
        "Call loom_status to compare the updated repo state.",
    )


def tool_resolve_next_steps() -> tuple[str, ...]:
    return (
        "Call loom_conflicts to confirm the active set is clear.",
        "Call loom_status to compare the updated repo state.",
    )


def tool_unclaim_next_steps() -> tuple[str, ...]:
    return (
        "Call loom_status to confirm the updated coordination state.",
        'Call loom_claim with description="Describe the work you\'re starting" '
        'and scope=["path/to/area"] when you take on the next task.',
    )


def tool_finish_next_steps(*, wrote_context: bool) -> tuple[str, ...]:
    if wrote_context:
        return (
            "Call loom_start to ask Loom what to do next in this repository.",
            "Call loom_inbox for pending coordination work.",
            "Call loom_status to compare the updated repo state.",
        )
    return (
        "Call loom_start to ask Loom what to do next in this repository.",
        "Call loom_status to compare the updated repo state.",
        "Call loom_agents to inspect the remaining agents.",
    )


def tool_renew_next_steps() -> tuple[str, ...]:
    return (
        "Call loom_agent for a focused agent view.",
        "Call loom_status to compare the updated repo state.",
        "Call loom_finish when the current work is truthfully done.",
    )


def tool_log_next_steps(*, event_count: int) -> tuple[str, ...]:
    if event_count:
        return (
            "Call loom_status to compare the current repo state.",
            "Call loom_inbox for pending coordination work.",
        )
    return (
        "Call loom_status to confirm the current coordination state.",
        'Call loom_claim with description="Describe the work you\'re starting" '
        'and scope=["path/to/area"] when new work begins.',
    )


def tool_timeline_next_steps(
    *,
    object_type: str,
    related_conflict_count: int,
) -> tuple[str, ...]:
    if object_type == "conflict" or related_conflict_count:
        return (
            "Call loom_conflicts to inspect the active overlap set.",
            "Call loom_inbox for the affected agent.",
        )
    return (
        "Call loom_status to compare the broader repo state.",
        "Call loom_log for nearby coordination history.",
    )


def tool_error_next_steps(error: BaseException | str) -> tuple[str, ...]:
    code = recoverable_error_code(error)
    if code == "project_not_initialized":
        return ('Call loom_init to initialize Loom in this repository.',)
    if code == "no_active_claim":
        return (
            "Call loom_status to confirm the current coordination state.",
            'Call loom_claim with description="Describe the work you\'re starting" '
            'and scope=["path/to/area"].',
        )
    if code == "no_active_work":
        return (
            "Call loom_status to confirm the current coordination state.",
            "Call loom_finish to publish a handoff if the work is actually done.",
        )
    if code == "conflict_not_found":
        return (
            "Call loom_conflicts to re-read active conflicts.",
            "Call loom_status to compare the repo state.",
        )
    if code == "context_not_found":
        return (
            "Call loom_context_read to re-read recent shared context.",
            "Call loom_inbox for the affected agent.",
        )
    if code == "object_not_found":
        return (
            "Call loom_status to compare the current repo state.",
            "Call loom_log for recent coordination history.",
        )
    if code == "invalid_arguments":
        return ("Call loom_protocol to inspect the supported tool schemas.",)
    return ()
