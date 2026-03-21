from __future__ import annotations

from .local_store import ConflictRecord, ContextRecord


def recommendation(
    *,
    command: str,
    tool_name: str,
    tool_arguments: dict[str, object],
    summary: str,
    reason: str,
    confidence: str,
    urgency: str | None = None,
    kind: str | None = None,
    action_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "command": command,
        "tool_name": tool_name,
        "tool_arguments": dict(tool_arguments),
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


def _scope_args(scope: tuple[str, ...]) -> str:
    return "".join(f" --scope {item}" for item in scope)


def claim_recommendation(
    *,
    summary: str,
    reason: str,
    confidence: str,
    scope: tuple[str, ...] = ("path/to/area",),
    agent_id: str | None = None,
) -> dict[str, object]:
    command = 'loom claim "Describe the work you\'re starting"'
    if scope:
        command = f"{command}{_scope_args(scope)}"
    arguments: dict[str, object] = {
        "description": "Describe the work you're starting",
        "scope": list(scope or ("path/to/area",)),
    }
    if agent_id:
        arguments["agent_id"] = agent_id
    return recommendation(
        command=command,
        tool_name="loom_claim",
        tool_arguments=arguments,
        summary=summary,
        reason=reason,
        confidence=confidence,
    )


def intent_recommendation(
    *,
    summary: str,
    reason: str,
    confidence: str,
    scope: tuple[str, ...] = ("path/to/area",),
    agent_id: str | None = None,
) -> dict[str, object]:
    command = 'loom intent "Describe the edit you\'re about to make"'
    if scope:
        command = f"{command}{_scope_args(scope)}"
    arguments: dict[str, object] = {
        "description": "Describe the edit you're about to make",
        "scope": list(scope or ("path/to/area",)),
    }
    if agent_id:
        arguments["agent_id"] = agent_id
    return recommendation(
        command=command,
        tool_name="loom_intent",
        tool_arguments=arguments,
        summary=summary,
        reason=reason,
        confidence=confidence,
    )


def finish_recommendation() -> dict[str, object]:
    return recommendation(
        command="loom finish",
        tool_name="loom_finish",
        tool_arguments={},
        summary="Finish the current work truthfully.",
        reason="Current work looks settled and Loom does not see pending attention or drift.",
        confidence="high",
    )


def priority_recommendation(priority: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(priority, dict):
        return None
    command = str(priority.get("next_step", "")).strip()
    tool_name = str(priority.get("tool_name", "")).strip()
    tool_arguments = priority.get("tool_arguments", {})
    if not command or not tool_name or not isinstance(tool_arguments, dict):
        return None
    kind = str(priority.get("kind", "")).strip() or None
    action_id = str(priority.get("id", "")).strip() or None
    return recommendation(
        command=command,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        summary=str(priority.get("summary", "")).strip() or "React to Loom's top priority.",
        reason=(
            str(priority.get("reason", "")).strip()
            or "Loom found a concrete top-priority coordination item for the current work."
        ),
        confidence=str(priority.get("confidence", "")).strip() or "high",
        kind=kind,
        action_id=action_id,
    )


def lease_alert_recommendation(lease_alert: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(lease_alert, dict):
        return None
    command = str(lease_alert.get("next_step", "")).strip()
    tool_name = str(lease_alert.get("tool_name", "")).strip()
    tool_arguments = lease_alert.get("tool_arguments", {})
    if not command or not tool_name or not isinstance(tool_arguments, dict):
        return None
    return recommendation(
        command=command,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        summary=(
            str(lease_alert.get("summary", "")).strip()
            or "Renew the expired coordination lease before continuing."
        ),
        reason=(
            str(lease_alert.get("reason", "")).strip()
            or "Loom found active work whose coordination lease has expired."
        ),
        confidence=str(lease_alert.get("confidence", "")).strip() or "high",
        kind="lease",
    )


def yield_alert_recommendation(yield_alert: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(yield_alert, dict):
        return None
    command = str(yield_alert.get("next_step", "")).strip()
    tool_name = str(yield_alert.get("tool_name", "")).strip()
    tool_arguments = yield_alert.get("tool_arguments", {})
    if not command or not tool_name or not isinstance(tool_arguments, dict):
        return None
    return recommendation(
        command=command,
        tool_name=tool_name,
        tool_arguments=tool_arguments,
        summary=(
            str(yield_alert.get("summary", "")).strip()
            or "Yield the current leased work before continuing."
        ),
        reason=(
            str(yield_alert.get("reason", "")).strip()
            or "Loom found higher-priority coordination pressure and this leased work is configured to yield."
        ),
        confidence=str(yield_alert.get("confidence", "")).strip() or "high",
        urgency=str(yield_alert.get("urgency", "")).strip() or None,
        kind="yield",
    )


def worktree_adoption_recommendation(
    *,
    has_active_scope: bool,
    suggested_scope: tuple[str, ...],
    agent_id: str | None = None,
) -> dict[str, object]:
    scope = suggested_scope or ("path/to/area",)
    if has_active_scope:
        return intent_recommendation(
            summary="Adopt the widened scope Loom inferred from worktree drift.",
            reason="Changed files fall outside the current claim or intent scope.",
            confidence="high",
            scope=scope,
            agent_id=agent_id,
        )
    return claim_recommendation(
        summary="Claim the work Loom inferred from the changed files.",
        reason="There are changed files but no active claim or intent for them yet.",
        confidence="high",
        scope=scope,
        agent_id=agent_id,
    )


def handoff_recommendation(
    *,
    handoff: ContextRecord,
    agent_id: str | None = None,
) -> dict[str, object]:
    scope = tuple(getattr(handoff, "scope", ())) or ("path/to/area",)
    return claim_recommendation(
        summary="Reclaim the recent handoff from the prior session.",
        reason="Loom found a recent self-handoff with no current active work.",
        confidence="high",
        scope=scope,
        agent_id=agent_id,
    )


def inbox_recommendation(
    *,
    agent_id: str,
    pending_context: tuple[ContextRecord, ...],
    conflicts: tuple[ConflictRecord, ...],
    prefer_conflict_inspection: bool = False,
) -> dict[str, object]:
    if conflicts:
        conflict = conflicts[0]
        if prefer_conflict_inspection:
            return inspect_conflicts_recommendation(
                summary="Inspect active conflicts affecting this agent.",
                reason="The inbox contains one or more active conflicts.",
                confidence="high",
            )
        return recommendation(
            command=f'loom resolve {conflict.id} --note "<resolution>"',
            tool_name="loom_resolve",
            tool_arguments={"conflict_id": conflict.id},
            summary="Resolve or inspect the highest-priority conflict Loom found.",
            reason="The inbox contains one or more active conflicts.",
            confidence="high",
            kind="conflict",
            action_id=conflict.id,
        )
    if pending_context:
        entry = pending_context[0]
        return recommendation(
            command=f"loom context ack {entry.id} --status read",
            tool_name="loom_context_ack",
            tool_arguments={
                "context_id": entry.id,
                "agent_id": agent_id,
                "status": "read",
            },
            summary="Acknowledge the most relevant pending context note.",
            reason="The inbox contains pending context and no conflict takes priority over it.",
            confidence="high",
            kind="context",
            action_id=entry.id,
        )
    return claim_recommendation(
        summary="Start a new claimed task for this agent.",
        reason="The inbox is clear, so Loom is falling back to the default next task start.",
        confidence="medium",
        agent_id=agent_id,
    )


def conflicts_recommendation(
    conflicts: tuple[ConflictRecord, ...],
) -> dict[str, object]:
    if conflicts:
        conflict = conflicts[0]
        return recommendation(
            command=f'loom resolve {conflict.id} --note "<resolution>"',
            tool_name="loom_resolve",
            tool_arguments={"conflict_id": conflict.id},
            summary="Resolve or inspect the first active conflict Loom found.",
            reason="The conflict list is non-empty and Loom orders the first active conflict as the top item.",
            confidence="high",
            kind="conflict",
            action_id=conflict.id,
        )
    return claim_recommendation(
        summary="Start the next coordinated task now that conflicts are clear.",
        reason="The active conflict set is clear, so Loom falls back to the default next task start.",
        confidence="medium",
    )


def inspect_inbox_recommendation(
    *,
    agent_id: str,
    summary: str,
    reason: str,
    confidence: str,
) -> dict[str, object]:
    return recommendation(
        command="loom inbox",
        tool_name="loom_inbox",
        tool_arguments={"agent_id": agent_id},
        summary=summary,
        reason=reason,
        confidence=confidence,
    )


def inspect_conflicts_recommendation(
    *,
    summary: str,
    reason: str,
    confidence: str,
) -> dict[str, object]:
    return recommendation(
        command="loom conflicts",
        tool_name="loom_conflicts",
        tool_arguments={},
        summary=summary,
        reason=reason,
        confidence=confidence,
    )


def focus_agent_recommendation(
    *,
    agent_id: str,
    summary: str,
    reason: str,
    confidence: str,
) -> dict[str, object]:
    return recommendation(
        command="loom agent",
        tool_name="loom_agent",
        tool_arguments={"agent_id": agent_id},
        summary=summary,
        reason=reason,
        confidence=confidence,
    )
