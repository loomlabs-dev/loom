from __future__ import annotations

import json

from .authority import (
    authority_focus_reason,
    authority_focus_scope,
    authority_focus_summary,
)
from .client import CoordinationClient
from .guidance import (
    agent_recommendation as guidance_agent_recommendation,
    claim_recommendation as guidance_claim_recommendation,
    conflicts_recommendation as guidance_conflicts_recommendation,
    identity_has_stable_coordination as guidance_identity_has_stable_coordination,
    inbox_recommendation as guidance_inbox_recommendation,
    priority_recommendation as guidance_priority_recommendation,
    start_recommendation as guidance_start_recommendation,
    status_recommendation as guidance_status_recommendation,
)
from .local_store import ConflictRecord
from .mcp_steps import (
    tool_agent_next_steps,
    tool_agents_next_steps,
    tool_clean_next_steps,
    tool_claim_step,
    tool_conflicts_next_steps,
    tool_context_ack_next_steps,
    tool_context_read_next_steps,
    tool_context_write_next_steps,
    tool_error_next_steps,
    tool_finish_next_steps,
    tool_finish_step,
    tool_inbox_next_steps,
    tool_intent_step,
    tool_log_next_steps,
    tool_onboarding_steps,
    tool_post_write_steps,
    tool_priority_step,
    tool_renew_next_steps,
    tool_renew_step,
    tool_resolve_next_steps,
    tool_start_next_steps,
    tool_start_step,
    tool_status_next_steps as _steps_tool_status_next_steps,
    tool_timeline_next_steps,
    tool_unclaim_next_steps,
    tool_whoami_next_steps,
)
from .util import is_past_utc_timestamp, json_ready as _json_ready


def tool_content(summary: str, structured: dict[str, object]) -> list[dict[str, str]]:
    structured_json = json.dumps(_json_ready(structured), sort_keys=True, ensure_ascii=False)
    if summary == structured_json:
        return [{"type": "text", "text": summary}]
    return [
        {"type": "text", "text": summary},
        {"type": "text", "text": structured_json},
    ]


def prompt_message(text: str) -> dict[str, object]:
    return {
        "role": "user",
        "content": {
            "type": "text",
            "text": text,
        },
    }


def json_text(payload: dict[str, object]) -> str:
    return json.dumps(_json_ready(payload), sort_keys=True, ensure_ascii=False)

def tool_start_action(
    *,
    project: object | None,
    identity: dict[str, object],
    authority: dict[str, object] | None = None,
    dead_session_count: int = 0,
    snapshot: object | None = None,
    agent_snapshot: object | None = None,
    inbox_snapshot: object | None = None,
    active_work: dict[str, object] | None = None,
    repo_lanes: dict[str, object] | None = None,
    worktree_signal: dict[str, object] | None = None,
    recent_handoff: object | None = None,
) -> dict[str, object] | None:
    if project is not None and identity.get("source") == "tty":
        return tool_action(
            tool="loom_bind",
            arguments={"agent_id": "<agent-name>"},
            summary="Bind this MCP session to a stable Loom agent identity.",
            reason="The repository is ready, but Loom still sees a raw terminal identity for this session.",
            confidence="high",
        )
    authority_recovery = _tool_authority_recovery_action(authority)
    if authority_recovery is not None:
        return authority_recovery
    if project is not None and dead_session_count:
        return tool_action(
            tool="loom_clean",
            arguments={},
            summary="Sweep dead pid-based session work off the board.",
            reason="Loom sees closed terminal sessions still holding coordination state.",
            confidence="high",
        )
    recommendation = guidance_start_recommendation(
        project_initialized=project is not None,
        identity_recommendation=None,
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
        action = None
    else:
        action = tool_action_from_recommendation(recommendation)
    if _should_promote_authority_focus(
        authority,
        next_action=action,
        has_active_work=bool(active_work is not None and active_work.get("started_at") is not None),
    ):
        return _tool_authority_focus_action(authority)
    return action


def tool_priority_action(priority: dict[str, object]) -> dict[str, object] | None:
    recommendation = guidance_priority_recommendation(priority)
    if recommendation is None:
        return None
    return tool_action_from_recommendation(recommendation)


def tool_action(
    *,
    tool: str,
    arguments: dict[str, object],
    summary: str,
    reason: str,
    confidence: str,
    urgency: str | None = None,
) -> dict[str, object]:
    payload = {
        "tool": tool,
        "arguments": dict(arguments),
        "summary": summary,
        "reason": reason,
        "confidence": confidence,
    }
    if urgency:
        payload["urgency"] = urgency
    return payload


def tool_action_from_recommendation(recommendation: dict[str, object]) -> dict[str, object]:
    return tool_action(
        tool=str(recommendation["tool_name"]),
        arguments=dict(recommendation["tool_arguments"]),
        summary=str(recommendation["summary"]),
        reason=str(recommendation["reason"]),
        confidence=str(recommendation["confidence"]),
        urgency=None if recommendation.get("urgency") is None else str(recommendation["urgency"]),
    )


def tool_agent_action(
    *,
    agent: object,
    active_work: dict[str, object] | None,
    worktree_signal: dict[str, object] | None,
) -> dict[str, object] | None:
    agent_id = str(getattr(agent, "agent_id"))
    recommendation = guidance_agent_recommendation(
        agent_id=agent_id,
        claim=getattr(agent, "claim", None),
        intent=getattr(agent, "intent", None),
        has_published_context=bool(tuple(getattr(agent, "published_context", ()))),
        active_work=active_work or {"priority": None, "started_at": None},
        worktree_signal=worktree_signal or {"has_drift": False, "suggested_scope": ()},
    )
    if recommendation is None:
        return None
    return tool_action_from_recommendation(recommendation)


def tool_inbox_action(*, inbox: object) -> dict[str, object] | None:
    agent_id = str(getattr(inbox, "agent_id"))
    recommendation = guidance_inbox_recommendation(
        agent_id=agent_id,
        pending_context=tuple(getattr(inbox, "pending_context", ())),
        conflicts=tuple(getattr(inbox, "conflicts", ())),
        prefer_conflict_inspection=True,
    )
    return tool_action_from_recommendation(recommendation)


def tool_status_action(
    *,
    client: CoordinationClient,
    snapshot: object,
    identity: dict[str, object],
    authority: dict[str, object] | None = None,
    dead_session_count: int = 0,
    stale_agent_ids: set[str] | None = None,
    repo_lanes: dict[str, object] | None = None,
) -> dict[str, object] | None:
    authority_recovery = _tool_authority_recovery_action(authority)
    if authority_recovery is not None:
        return authority_recovery
    if dead_session_count:
        return tool_action(
            tool="loom_clean",
            arguments={},
            summary="Sweep dead pid-based session work off the board.",
            reason="Loom sees closed terminal sessions still holding coordination state.",
            confidence="high",
        )
    agent_id = str(identity["id"])
    has_stable_identity = guidance_identity_has_stable_coordination(identity=identity)
    identity_recommendation = None
    if not has_stable_identity:
        identity_recommendation = tool_action(
            tool="loom_bind",
            arguments={"agent_id": "<agent-name>"},
            summary="Bind this MCP session to a stable Loom agent identity before coordinated work.",
            reason="The repository is ready, but Loom does not see a stable agent identity yet.",
            confidence="high",
        )
    recommendation = guidance_status_recommendation(
        agent_id=agent_id,
        store=client.store,
        snapshot=snapshot,
        worktree_signal=None,
        stale_agent_ids=stale_agent_ids,
        repo_lanes=repo_lanes,
        empty_recommendation=guidance_claim_recommendation(
            summary="Start the first coordinated task in this repository.",
            reason="The repository is active but has no current claims, intents, context, or conflicts.",
            confidence="medium",
            agent_id=agent_id,
        ),
        identity_recommendation=None if identity_recommendation is None else {
            "command": 'loom_bind --agent-id "<agent-name>"',
            "tool_name": "loom_bind",
            "tool_arguments": {"agent_id": "<agent-name>"},
            "summary": identity_recommendation["summary"],
            "reason": identity_recommendation["reason"],
            "confidence": identity_recommendation["confidence"],
        },
    )
    action = tool_action_from_recommendation(recommendation)
    if _should_promote_authority_focus(
        authority,
        next_action=action,
        has_active_work=False,
    ):
        return _tool_authority_focus_action(authority)
    return action


def tool_status_next_steps(
    *,
    snapshot: object,
    identity: dict[str, object],
    dead_session_count: int = 0,
    authority: dict[str, object] | None = None,
) -> tuple[str, ...]:
    return _steps_tool_status_next_steps(
        snapshot=snapshot,
        identity=identity,
        dead_session_count=dead_session_count,
        authority=authority,
        is_past_timestamp=is_past_utc_timestamp,
    )


def tool_conflicts_action(*, conflicts: tuple[object, ...]) -> dict[str, object] | None:
    typed_conflicts = tuple(item for item in conflicts if isinstance(item, ConflictRecord))
    return tool_action_from_recommendation(
        guidance_conflicts_recommendation(typed_conflicts)
    )


def _authority_scope(authority: dict[str, object] | None) -> tuple[str, ...]:
    return authority_focus_scope(authority)


def _tool_authority_recovery_action(authority: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(authority, dict) or authority.get("status") != "invalid":
        return None
    reason = "Loom cannot trust declared repository truth until loom.yaml is valid."
    issues = tuple(authority.get("issues", ()))
    if issues and isinstance(issues[0], dict):
        message = str(issues[0].get("message", "")).strip()
        if message:
            reason = message
    return tool_action(
        tool="loom_claim",
        arguments={
            "description": "Fix declared authority configuration",
            "scope": ["loom.yaml"],
        },
        summary="Claim loom.yaml before fixing the declared authority configuration.",
        reason=reason,
        confidence="high",
    )


def _tool_authority_focus_action(authority: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(authority, dict) or authority.get("status") != "valid":
        return None
    scope = _authority_scope(authority)
    if not scope:
        return None
    return tool_action(
        tool="loom_claim",
        arguments={
            "description": "Review repo surfaces affected by authority change",
            "scope": list(scope),
        },
        summary=authority_focus_summary(authority)
        or "Claim the repo surfaces affected by the authority change.",
        reason=authority_focus_reason(authority)
        or "Loom is treating these affected authority surfaces as the first repository truth to coordinate.",
        confidence="high",
    )


def _should_promote_authority_focus(
    authority: dict[str, object] | None,
    *,
    next_action: dict[str, object] | None,
    has_active_work: bool,
) -> bool:
    if _tool_authority_focus_action(authority) is None or has_active_work:
        return False
    if not isinstance(next_action, dict):
        return True
    tool_name = str(next_action.get("tool", "")).strip()
    return tool_name in {"loom_start", "loom_status", "loom_claim"}
