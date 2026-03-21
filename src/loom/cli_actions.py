from __future__ import annotations

from typing import Callable

from .guidance import (
    DEFAULT_RENEW_LEASE_MINUTES,
    active_work_completion_ready as guidance_active_work_completion_ready,
    agent_recommendation as guidance_agent_recommendation,
    agent_step_order as guidance_agent_step_order,
    agents_step_order as guidance_agents_step_order,
    conflicts_recommendation as guidance_conflicts_recommendation,
    identity_has_stable_coordination as guidance_identity_has_stable_coordination,
    identity_needs_env_binding as guidance_identity_needs_env_binding,
    inbox_recommendation as guidance_inbox_recommendation,
    onboarding_step_order as guidance_onboarding_step_order,
    priority_recommendation as guidance_priority_recommendation,
    resume_recommendation as guidance_resume_recommendation,
    start_drift_step_order as guidance_start_drift_step_order,
    start_followup_step_order as guidance_start_followup_step_order,
    start_recommendation as guidance_start_recommendation,
    start_step_order as guidance_start_step_order,
    status_recommendation as guidance_status_recommendation,
    status_step_order as guidance_status_step_order,
)
from .local_store import (
    AgentSnapshot,
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    CoordinationStore,
    InboxSnapshot,
    IntentRecord,
)
from .project import LoomProject
from .util import is_past_utc_timestamp
from .action_errors import (
    recoverable_error_code,
)


def _scope_args(scope: tuple[str, ...]) -> str:
    return "".join(f" --scope {item}" for item in scope)


def _action_first_bind_command(identity: dict[str, object]) -> str:
    if guidance_identity_needs_env_binding(identity):
        return "export LOOM_AGENT=<agent-name>"
    return "loom start --bind <agent-name>"


def claim_command(*, scope: tuple[str, ...] = ()) -> str:
    command = 'loom claim "Describe the work you\'re starting"'
    if not scope:
        return command
    return f"{command}{_scope_args(scope)}"


def intent_command(*, scope: tuple[str, ...] = ()) -> str:
    command = 'loom intent "Describe the edit you\'re about to make"'
    if not scope:
        return command
    return f"{command}{_scope_args(scope)}"


def renew_command(*, lease_minutes: int = DEFAULT_RENEW_LEASE_MINUTES) -> str:
    if lease_minutes == DEFAULT_RENEW_LEASE_MINUTES:
        return "loom renew"
    return f"loom renew --lease-minutes {lease_minutes}"


def command_action(
    *,
    command: str,
    summary: str,
    reason: str,
    confidence: str,
    urgency: str | None = None,
    kind: str | None = None,
    action_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": command,
        "summary": summary,
        "reason": reason,
        "confidence": confidence,
    }
    if urgency:
        payload["urgency"] = urgency
    if kind:
        payload["kind"] = kind
    if action_id:
        payload["id"] = action_id
    return payload


def priority_command_action(priority: dict[str, object] | None) -> dict[str, object] | None:
    recommendation = guidance_priority_recommendation(priority)
    if recommendation is None:
        return None
    return command_action(
        command=str(recommendation["command"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        urgency=None if recommendation.get("urgency") is None else str(recommendation["urgency"]),
        kind=None if recommendation.get("kind") is None else str(recommendation["kind"]),
        action_id=None if recommendation.get("id") is None else str(recommendation["id"]),
    )


def onboarding_commands(
    *,
    default_agent: str | None = None,
    identity: dict[str, object] | None = None,
) -> tuple[str, str, str]:
    if identity is not None and identity.get("source") == "tty":
        if guidance_identity_needs_env_binding(identity):
            return (
                "export LOOM_AGENT=<agent-name>",
                "loom start",
                claim_command(scope=("path/to/area",)),
            )
        return (
            _action_first_bind_command(identity),
            claim_command(scope=("path/to/area",)),
            "loom status",
        )
    has_stable_identity = guidance_identity_has_stable_coordination(
        identity=identity,
        default_agent=default_agent,
    )
    steps: list[str] = []
    for key in guidance_onboarding_step_order(has_stable_identity=has_stable_identity):
        if key == "start":
            steps.append("loom start")
        elif key == "claim":
            steps.append(claim_command(scope=("path/to/area",)))
        elif key == "status":
            steps.append("loom status")
        elif key == "bind":
            if identity is not None and guidance_identity_needs_env_binding(identity):
                steps.append("export LOOM_AGENT=<agent-name>")
            else:
                steps.append("loom start --bind <agent-name>")
    return tuple(steps)


def whoami_next_steps(
    *,
    project: LoomProject | None,
    identity: dict[str, object],
) -> tuple[str, ...]:
    if project is None:
        if guidance_identity_needs_env_binding(identity):
            return (
                "loom init --no-daemon",
                "export LOOM_AGENT=<agent-name>",
                claim_command(scope=("path/to/area",)),
            )
        return ("loom init --no-daemon",)
    if identity.get("source") == "tty":
        if guidance_identity_needs_env_binding(identity):
            return (
                "export LOOM_AGENT=<agent-name>",
                "loom start",
                claim_command(scope=("path/to/area",)),
            )
        return (
            "loom start --bind <agent-name>",
            claim_command(scope=("path/to/area",)),
            "loom status",
        )
    return (
        "loom start",
        claim_command(scope=("path/to/area",)),
        "loom status",
    )


def handoff_resume_command(entry: ContextRecord) -> str:
    if entry.scope and entry.scope != (".",):
        return claim_command(scope=entry.scope)
    return claim_command()


def _start_step_command(
    key: str,
    *,
    identity: dict[str, object],
    priority: dict[str, object] | None = None,
    recent_handoff: ContextRecord | None = None,
    suggested_scope: tuple[str, ...] = (),
) -> str:
    if key == "init":
        return "loom init --no-daemon"
    if key == "bind":
        if guidance_identity_needs_env_binding(identity):
            return "export LOOM_AGENT=<agent-name>"
        return "loom start --bind <agent-name>"
    if key == "claim":
        return claim_command(scope=suggested_scope or ("path/to/area",))
    if key == "intent":
        return intent_command(scope=suggested_scope or ("path/to/area",))
    if key == "start":
        return "loom start"
    if key == "priority" and isinstance(priority, dict):
        next_step = str(priority.get("next_step", "")).strip()
        if next_step:
            return next_step
    if key == "inbox":
        return "loom inbox"
    if key == "conflicts":
        return "loom conflicts"
    if key == "status":
        return "loom status"
    if key == "agent":
        return "loom agent"
    if key == "finish":
        return "loom finish"
    if key == "handoff" and recent_handoff is not None:
        return handoff_resume_command(recent_handoff)
    raise ValueError(f"Unsupported start step key: {key}")


def start_next_steps(
    *,
    project: LoomProject | None,
    identity: dict[str, object],
    dead_session_count: int = 0,
    snapshot: object | None = None,
    agent_snapshot: object | None = None,
    inbox_snapshot: InboxSnapshot | None = None,
    active_work: dict[str, object] | None = None,
    recent_handoff: ContextRecord | None = None,
    worktree_signal: dict[str, object] | None = None,
    is_past_timestamp: Callable[[str], bool] = is_past_utc_timestamp,
) -> tuple[str, ...]:
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
    if dead_session_count:
        return (
            "loom clean",
            "loom status",
            "loom agents --all",
        )
    if (
        identity.get("source") == "tty"
        and not guidance_identity_needs_env_binding(identity)
    ):
        if project is None:
            return (
                "loom init --no-daemon",
                _action_first_bind_command(identity),
                claim_command(scope=("path/to/area",)),
            )
        return (
            _action_first_bind_command(identity),
            claim_command(scope=("path/to/area",)),
            "loom status",
        )
    if (
        project is not None
        and identity.get("source") == "tty"
        and guidance_identity_needs_env_binding(identity)
    ):
        return (
            "export LOOM_AGENT=<agent-name>",
            "loom start",
            claim_command(scope=("path/to/area",)),
        )
    step_order = guidance_start_step_order(
        project_initialized=project is not None,
        has_raw_terminal_identity=identity.get("source") == "tty",
        has_inbox_attention=bool(
            inbox_snapshot is not None
            and (inbox_snapshot.pending_context or inbox_snapshot.conflicts)
        ),
        has_priority=isinstance(priority, dict)
        and bool(str(priority.get("next_step", "")).strip()),
    )
    if step_order:
        return tuple(
            _start_step_command(
                key,
                identity=identity,
                priority=priority if isinstance(priority, dict) else None,
            )
            for key in step_order
        )
    repo_is_empty = bool(
        snapshot is not None
        and not snapshot.claims
        and not snapshot.intents
        and not snapshot.context
        and not snapshot.conflicts
    )
    followup_order = guidance_start_followup_step_order(
        has_recent_handoff=recent_handoff is not None and not has_worktree_drift,
        completion_ready=completion_ready,
        repo_is_empty=repo_is_empty and not has_worktree_drift,
    )
    if followup_order:
        return tuple(
            _start_step_command(
                key,
                identity=identity,
                recent_handoff=recent_handoff,
                suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
                if worktree_signal is not None
                else (),
            )
            for key in followup_order
        )
    if worktree_signal is not None and worktree_signal.get("has_drift") and agent_snapshot is not None:
        suggested_scope = tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
        return tuple(
            _start_step_command(
                key,
                identity=identity,
                suggested_scope=suggested_scope,
            )
            for key in guidance_start_drift_step_order(
                has_active_scope=agent_snapshot.claim is not None or agent_snapshot.intent is not None,
            )
        )
    if snapshot is not None:
        if snapshot.conflicts or snapshot.context:
            return status_next_steps(
                snapshot=snapshot,
                identity=identity,
                is_past_timestamp=is_past_timestamp,
            )
    if agent_snapshot is not None:
        return agent_next_steps(
            has_claim=agent_snapshot.claim is not None,
            has_intent=agent_snapshot.intent is not None,
            has_published_context=bool(agent_snapshot.published_context),
            pending_context=len(agent_snapshot.incoming_context),
            conflict_count=len(agent_snapshot.conflicts),
            has_priority_attention=isinstance(priority, dict)
            and bool(str(priority.get("next_step", "")).strip()),
            priority_command=None if not isinstance(priority, dict) else str(priority.get("next_step", "")),
            worktree_drift_count=0
            if worktree_signal is None
            else len(tuple(worktree_signal.get("drift_paths", ()))),
            suggested_scope=() if worktree_signal is None else tuple(str(path) for path in worktree_signal.get("suggested_scope", ())),
            completion_ready=completion_ready,
        )
    return (
        "loom status",
        "loom agent",
        "loom inbox",
    )


def start_next_action(
    *,
    project: LoomProject | None,
    identity: dict[str, object],
    dead_session_count: int = 0,
    snapshot: object | None = None,
    agent_snapshot: object | None = None,
    inbox_snapshot: InboxSnapshot | None = None,
    active_work: dict[str, object] | None = None,
    repo_lanes: dict[str, object] | None = None,
    recent_handoff: ContextRecord | None = None,
    worktree_signal: dict[str, object] | None = None,
) -> dict[str, object] | None:
    identity_recommendation = None
    if project is not None and identity.get("source") == "tty":
        if guidance_identity_needs_env_binding(identity):
            identity_recommendation = command_action(
                command="export LOOM_AGENT=<agent-name>",
                summary="Pin a stable Loom agent identity for this shell.",
                reason="This shell has no stable terminal identity for repeatable coordination.",
                confidence="high",
            )
        else:
            identity_recommendation = command_action(
                command=_action_first_bind_command(identity),
                summary="Bind this terminal and continue with Loom's first coordinated step.",
                reason="This shell is still using a raw terminal identity, and Loom can bind it inline.",
                confidence="high",
            )
    if project is not None and dead_session_count:
        return command_action(
            command="loom clean",
            summary="Sweep dead pid-based session work off the board.",
            reason="Loom sees closed terminal sessions still holding coordination state.",
            confidence="high",
            kind="cleanup",
        )
    recommendation = guidance_start_recommendation(
        project_initialized=project is not None,
        identity_recommendation=identity_recommendation,
        agent_id=str(identity["id"]),
        snapshot=snapshot,
        agent_snapshot=agent_snapshot,
        inbox_snapshot=inbox_snapshot,
        active_work=active_work,
        repo_lanes=repo_lanes,
        worktree_signal=worktree_signal,
        recent_handoff=recent_handoff,
    )
    if recommendation is None:
        return None
    return command_action(
        command=str(recommendation["command"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        urgency=None if recommendation.get("urgency") is None else str(recommendation["urgency"]),
        kind=None if recommendation.get("kind") is None else str(recommendation["kind"]),
        action_id=None if recommendation.get("id") is None else str(recommendation["id"]),
    )


def status_next_action(
    *,
    store: CoordinationStore,
    snapshot: object,
    identity: dict[str, object],
    dead_session_count: int = 0,
    worktree_signal: dict[str, object] | None = None,
    stale_agent_ids: set[str] | None = None,
    repo_lanes: dict[str, object] | None = None,
) -> dict[str, object] | None:
    if dead_session_count:
        return command_action(
            command="loom clean",
            summary="Sweep dead pid-based session work off the board.",
            reason="Loom sees closed terminal sessions still holding coordination state.",
            confidence="high",
            kind="cleanup",
        )
    has_stable_identity = guidance_identity_has_stable_coordination(identity=identity)
    identity_recommendation = None
    if not has_stable_identity:
        if guidance_identity_needs_env_binding(identity):
            identity_recommendation = command_action(
                command="export LOOM_AGENT=<agent-name>",
                summary="Pin a stable Loom agent identity for this shell.",
                reason="The repository is ready, but Loom does not see a stable agent identity yet.",
                confidence="high",
            )
        else:
            identity_recommendation = command_action(
                command=_action_first_bind_command(identity),
                summary="Bind this terminal and continue with Loom's first coordinated step.",
                reason="The repository is ready, but Loom does not see a stable agent identity yet.",
                confidence="high",
            )
    recommendation = guidance_status_recommendation(
        agent_id=str(identity["id"]),
        store=store,
        snapshot=snapshot,
        worktree_signal=worktree_signal,
        stale_agent_ids=stale_agent_ids,
        repo_lanes=repo_lanes,
        empty_recommendation=command_action(
            command="loom start",
            summary="Ask Loom for the first coordinated step in this repository.",
            reason="The repository is active but has no current claims, intents, context, or conflicts.",
            confidence="medium",
        ),
        identity_recommendation=identity_recommendation,
    )
    return command_action(
        command=str(recommendation["command"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        urgency=None if recommendation.get("urgency") is None else str(recommendation["urgency"]),
        kind=None if recommendation.get("kind") is None else str(recommendation["kind"]),
        action_id=None if recommendation.get("id") is None else str(recommendation["id"]),
    )


def agent_next_action(
    *,
    snapshot: AgentSnapshot,
    active_work: dict[str, object],
    worktree_signal: dict[str, object],
) -> dict[str, object] | None:
    recommendation = guidance_agent_recommendation(
        agent_id=snapshot.agent_id,
        claim=snapshot.claim,
        intent=snapshot.intent,
        has_published_context=bool(snapshot.published_context),
        active_work=active_work,
        worktree_signal=worktree_signal,
    )
    if recommendation is None:
        return None
    return command_action(
        command=str(recommendation["command"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        urgency=None if recommendation.get("urgency") is None else str(recommendation["urgency"]),
        kind=None if recommendation.get("kind") is None else str(recommendation["kind"]),
        action_id=None if recommendation.get("id") is None else str(recommendation["id"]),
    )


def resume_next_action(
    *,
    snapshot: AgentSnapshot,
    active_work: dict[str, object],
    worktree_signal: dict[str, object],
    recent_handoff: ContextRecord | None = None,
) -> dict[str, object] | None:
    recommendation = guidance_resume_recommendation(
        agent_id=snapshot.agent_id,
        claim=snapshot.claim,
        intent=snapshot.intent,
        active_work=active_work,
        worktree_signal=worktree_signal,
        recent_handoff=recent_handoff,
    )
    if recommendation is None:
        return None
    return command_action(
        command=str(recommendation["command"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        urgency=None if recommendation.get("urgency") is None else str(recommendation["urgency"]),
        kind=None if recommendation.get("kind") is None else str(recommendation["kind"]),
        action_id=None if recommendation.get("id") is None else str(recommendation["id"]),
    )


def inbox_next_action(snapshot: InboxSnapshot) -> dict[str, object] | None:
    recommendation = guidance_inbox_recommendation(
        agent_id=snapshot.agent_id,
        pending_context=tuple(snapshot.pending_context),
        conflicts=tuple(snapshot.conflicts),
    )
    return command_action(
        command=str(recommendation["command"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        urgency=None if recommendation.get("urgency") is None else str(recommendation["urgency"]),
        kind=None if recommendation.get("kind") is None else str(recommendation["kind"]),
        action_id=None if recommendation.get("id") is None else str(recommendation["id"]),
    )


def conflicts_next_action(conflicts: tuple[ConflictRecord, ...]) -> dict[str, object] | None:
    recommendation = guidance_conflicts_recommendation(conflicts)
    return command_action(
        command=str(recommendation["command"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        kind=None if recommendation.get("kind") is None else str(recommendation["kind"]),
        action_id=None if recommendation.get("id") is None else str(recommendation["id"]),
    )


def post_write_next_steps(*, has_conflicts: bool) -> tuple[str, ...]:
    if has_conflicts:
        return (
            "loom conflicts",
            "loom inbox",
            "loom status",
        )
    return (
        "loom status",
        'loom context write <topic> "<what others should know>" --scope path/to/area',
    )


def context_write_next_steps(*, has_conflicts: bool) -> tuple[str, ...]:
    if has_conflicts:
        return (
            "loom conflicts",
            "loom inbox",
            "loom status",
        )
    return (
        "loom inbox",
        "loom status",
    )


def agent_next_steps(
    *,
    has_claim: bool,
    has_intent: bool,
    has_published_context: bool,
    pending_context: int,
    conflict_count: int,
    has_priority_attention: bool = False,
    priority_command: str | None = None,
    worktree_drift_count: int = 0,
    suggested_scope: tuple[str, ...] = (),
    completion_ready: bool = False,
) -> tuple[str, ...]:
    if completion_ready:
        return (
            "loom finish",
            "loom status",
        )
    if has_priority_attention:
        if priority_command:
            return (
                priority_command,
                "loom inbox",
                "loom status",
            )
    if pending_context or conflict_count:
        return (
            "loom inbox",
            "loom status",
        )
    if worktree_drift_count:
        if has_claim or has_intent:
            return (
                intent_command(scope=suggested_scope),
                "loom agent",
            )
        return (
            claim_command(scope=suggested_scope),
            "loom status",
        )
    steps: list[str] = []
    for key in guidance_agent_step_order(
        has_pending_attention=False,
        has_claim=has_claim,
        has_intent=has_intent,
        has_published_context=has_published_context,
    ):
        if key == "claim":
            steps.append(claim_command(scope=("path/to/area",)))
        elif key == "intent":
            steps.append(intent_command(scope=("path/to/area",)))
        elif key == "status":
            steps.append("loom status")
    return tuple(steps)


def inbox_next_steps(snapshot: InboxSnapshot) -> tuple[str, ...]:
    if snapshot.pending_context or snapshot.conflicts:
        return ()
    return (
        claim_command(scope=("path/to/area",)),
        "loom status",
    )


def status_next_steps(
    *,
    snapshot: object,
    identity: dict[str, object],
    dead_session_count: int = 0,
    worktree_signal: dict[str, object] | None = None,
    is_past_timestamp: Callable[[str], bool] = is_past_utc_timestamp,
) -> tuple[str, ...]:
    if dead_session_count:
        return (
            "loom clean",
            "loom status",
            "loom agents --all",
        )
    agent_id = str(identity["id"])
    if worktree_signal is not None and worktree_signal.get("has_drift"):
        drift_count = len(tuple(worktree_signal.get("drift_paths", ())))
        suggested_scope = tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
        if drift_count and (snapshot.claims or snapshot.intents):
            return (
                "loom agent",
                intent_command(scope=suggested_scope),
                "loom status",
            )
        if drift_count:
            return (
                claim_command(scope=suggested_scope),
                "loom status",
                "loom agent",
            )
    current_agent_has_expired_lease = any(
        getattr(record, "agent_id", None) == agent_id
        and getattr(record, "status", "") == "active"
        and bool(getattr(record, "lease_expires_at", None))
        and is_past_timestamp(str(getattr(record, "lease_expires_at")))
        for record in (*tuple(snapshot.claims), *tuple(snapshot.intents))
    )
    if current_agent_has_expired_lease:
        return (
            renew_command(),
            "loom agent",
            "loom status",
        )
    step_order = guidance_status_step_order(
        is_empty=not snapshot.claims and not snapshot.intents and not snapshot.context and not snapshot.conflicts,
        has_conflicts=bool(snapshot.conflicts),
        has_context=bool(snapshot.context),
        has_stable_identity=guidance_identity_has_stable_coordination(identity=identity),
    )
    if (
        step_order == ("start", "bind", "claim")
        and identity.get("source") == "tty"
        and not guidance_identity_needs_env_binding(identity)
    ):
        return (
            _action_first_bind_command(identity),
            claim_command(scope=("path/to/area",)),
            "loom status",
        )
    steps: list[str] = []
    for key in step_order:
        if key == "start":
            steps.append("loom start")
        elif key == "bind":
            if guidance_identity_needs_env_binding(identity):
                steps.append("export LOOM_AGENT=<agent-name>")
            else:
                steps.append("loom start --bind <agent-name>")
        elif key == "claim":
            steps.append(claim_command(scope=("path/to/area",)))
        elif key == "status":
            steps.append("loom status")
        elif key == "conflicts":
            steps.append("loom conflicts")
        elif key == "inbox":
            steps.append("loom inbox")
        elif key == "agent":
            steps.append("loom agent")
        elif key == "log":
            steps.append("loom log --limit 10")
    return tuple(steps)


def agents_next_steps(*, agent_count: int, identity: dict[str, object]) -> tuple[str, ...]:
    if (
        agent_count == 0
        and identity.get("source") == "tty"
        and not guidance_identity_needs_env_binding(identity)
    ):
        return (
            _action_first_bind_command(identity),
            claim_command(scope=("path/to/area",)),
            "loom status",
        )
    steps: list[str] = []
    for key in guidance_agents_step_order(
        agent_count=agent_count,
        has_stable_identity=guidance_identity_has_stable_coordination(identity=identity),
    ):
        if key == "start":
            steps.append("loom start")
        elif key == "bind":
            if guidance_identity_needs_env_binding(identity):
                steps.append("export LOOM_AGENT=<agent-name>")
            else:
                steps.append("loom start --bind <agent-name>")
        elif key == "claim":
            steps.append(claim_command(scope=("path/to/area",)))
        elif key == "status":
            steps.append("loom status")
        elif key == "inbox":
            steps.append("loom inbox")
        elif key == "agent":
            steps.append("loom agent")
    return tuple(steps)


def report_next_steps(*, conflict_count: int, stale_active_count: int = 0) -> tuple[str, ...]:
    if stale_active_count:
        return (
            "loom agents",
            "loom status",
            "loom report --json",
        )
    if conflict_count:
        return (
            "loom conflicts",
            "loom inbox",
            "loom report --json",
        )
    return (
        "loom status",
        "loom agent",
        "loom report --json",
    )


def resume_next_steps(
    *,
    pending_context: int,
    conflict_count: int,
    has_claim: bool,
    has_intent: bool,
    has_priority_attention: bool = False,
    priority_command: str | None = None,
    worktree_drift_count: int = 0,
    suggested_scope: tuple[str, ...] = (),
    completion_ready: bool = False,
    recent_handoff: ContextRecord | None = None,
) -> tuple[str, ...]:
    if completion_ready:
        return (
            "loom finish",
            "loom agent",
            "loom status",
        )
    if has_priority_attention:
        if priority_command:
            return (
                priority_command,
                "loom inbox",
                "loom agent",
            )
    if pending_context or conflict_count:
        return (
            "loom inbox",
            "loom status",
            "loom agent",
        )
    if recent_handoff is not None:
        return (
            handoff_resume_command(recent_handoff),
            "loom status",
            "loom agent",
        )
    if worktree_drift_count:
        if has_claim or has_intent:
            return (
                intent_command(scope=suggested_scope),
                "loom agent",
                "loom status",
            )
        return (
            claim_command(scope=suggested_scope),
            "loom status",
            "loom agent",
        )
    if has_claim or has_intent:
        return (
            "loom agent",
            "loom status",
            "loom finish",
        )
    return (
        "loom start",
        'loom claim "Describe the work you\'re starting"',
        "loom status",
    )


def conflicts_next_steps(*, conflict_count: int) -> tuple[str, ...]:
    if conflict_count:
        return (
            "loom inbox",
            "loom status",
        )
    return (
        'loom claim "Describe the work you\'re starting" --scope path/to/area',
        "loom status",
    )


def context_read_next_steps(*, entry_count: int) -> tuple[str, ...]:
    if entry_count:
        return (
            "loom inbox",
            "loom status",
        )
    return (
        'loom context write <topic> "<what others should know>" --scope path/to/area',
        "loom status",
    )


def context_ack_next_steps(*, status: str) -> tuple[str, ...]:
    if status == "read":
        return (
            "loom inbox",
            'loom context ack <context-id> --status adapted --note "<what changed>"',
        )
    return (
        "loom inbox",
        "loom status",
    )


def resolve_next_steps() -> tuple[str, ...]:
    return (
        "loom conflicts",
        "loom status",
    )


def unclaim_next_steps() -> tuple[str, ...]:
    return (
        "loom status",
        'loom claim "Describe the work you\'re starting" --scope path/to/area',
    )


def renew_next_steps() -> tuple[str, ...]:
    return (
        "loom agent",
        "loom status",
        "loom finish",
    )


def finish_next_steps(*, wrote_context: bool) -> tuple[str, ...]:
    if wrote_context:
        return (
            "loom start",
            "loom inbox",
            "loom report",
        )
    return (
        "loom start",
        "loom status",
        "loom report",
    )


def log_next_steps(*, event_count: int) -> tuple[str, ...]:
    if event_count:
        return (
            "loom status",
            "loom inbox",
        )
    return (
        "loom status",
        'loom claim "Describe the work you\'re starting" --scope path/to/area',
    )


def timeline_next_steps(
    *,
    object_type: str,
    related_conflict_count: int,
) -> tuple[str, ...]:
    if object_type == "conflict" or related_conflict_count:
        return (
            "loom conflicts",
            "loom inbox",
        )
    return (
        "loom status",
        "loom log --limit 10",
    )


def error_next_steps(error: BaseException | str) -> tuple[str, ...]:
    code = recoverable_error_code(error)
    if code == "project_not_initialized":
        return ("loom init --no-daemon",)
    if code == "no_active_claim":
        return (
            "loom status",
            'loom claim "Describe the work you\'re starting" --scope path/to/area',
        )
    if code == "no_active_work":
        return (
            "loom status",
            'loom finish --note "What changed and what matters next."',
        )
    if code == "conflict_not_found":
        return (
            "loom conflicts",
            "loom status",
        )
    if code == "context_not_found":
        return (
            "loom context read --limit 10",
            "loom inbox",
        )
    if code == "object_not_found":
        return (
            "loom status",
            "loom log --limit 10",
        )
    if code == "whoami_selection":
        return ("loom whoami",)
    return ()
