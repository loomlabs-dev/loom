from __future__ import annotations

from typing import Callable

from .guidance import inbox_attention_text as guidance_inbox_attention_text
from .local_store import (
    AgentPresenceRecord,
    ContextAckRecord,
    ContextRecord,
    EventRecord,
    InboxSnapshot,
)
from .util import is_past_utc_timestamp


def _self_suffix(agent_id: str, *, current_agent_id: str) -> str:
    return " (you)" if agent_id == current_agent_id else ""


def print_conflicts(conflicts: list[object]) -> None:
    if conflicts:
        print("Conflicts detected:")
        for conflict in conflicts:
            print(f"- {conflict.summary}")
    else:
        print("Conflicts detected: none")


def print_context_dependencies(conflicts: tuple[object, ...] | list[object]) -> None:
    if conflicts:
        print("Context dependencies surfaced:")
        for conflict in conflicts:
            print(f"- {conflict.summary}")
    else:
        print("Context dependencies surfaced: none")


def print_idle_agents(
    idle: list[AgentPresenceRecord],
    *,
    current_agent_id: str,
) -> None:
    print()
    print(f"Idle ({len(idle)}):")
    for presence in idle:
        suffix = _self_suffix(presence.agent_id, current_agent_id=current_agent_id)
        print(f"  - {presence.agent_id}{suffix} [last seen {presence.last_seen_at}]")


def print_agent_presence(
    presence: AgentPresenceRecord,
    *,
    current_agent_id: str,
) -> None:
    print()
    print(
        f"- {presence.agent_id}"
        f"{_self_suffix(presence.agent_id, current_agent_id=current_agent_id)} "
        f"[last seen {presence.last_seen_at}]"
    )
    print(f"  source: {presence.source}")
    print(f"  created: {presence.created_at}")
    if presence.claim is None:
        print("  claim: none")
    else:
        print(f"  claim: {presence.claim.description} [{presence.claim.id}]")
        print(f"  claim scope: {format_scope_list(presence.claim.scope)}")
        if presence.claim.git_branch:
            print(f"  claim branch: {presence.claim.git_branch}")
        print_lease_details(
            presence.claim.lease_expires_at,
            label="  claim lease until",
            lease_policy=presence.claim.lease_policy,
        )
    if presence.intent is None:
        print("  intent: none")
    else:
        print(f"  intent: {presence.intent.description} [{presence.intent.id}]")
        print(f"  intent scope: {format_scope_list(presence.intent.scope)}")
        if presence.intent.git_branch:
            print(f"  intent branch: {presence.intent.git_branch}")
        print_lease_details(
            presence.intent.lease_expires_at,
            label="  intent lease until",
            lease_policy=presence.intent.lease_policy,
        )


def print_timeline_target(*, object_type: str, target: object) -> None:
    if object_type == "claim":
        claim = target
        print(f"Agent: {claim.agent_id}")
        print(f"Status: {claim.status}")
        print(f"Description: {claim.description}")
        print(f"Scope: {format_scope_list(claim.scope)}")
        if claim.git_branch:
            print(f"Branch: {claim.git_branch}")
        print_lease_details(
            claim.lease_expires_at,
            label="Lease until",
            lease_policy=claim.lease_policy,
        )
        print(f"Created: {claim.created_at}")
        return

    if object_type == "intent":
        intent = target
        print(f"Agent: {intent.agent_id}")
        print(f"Status: {intent.status}")
        print(f"Description: {intent.description}")
        print(f"Reason: {intent.reason}")
        print(f"Scope: {format_scope_list(intent.scope)}")
        if intent.git_branch:
            print(f"Branch: {intent.git_branch}")
        print_lease_details(
            intent.lease_expires_at,
            label="Lease until",
            lease_policy=intent.lease_policy,
        )
        print(f"Created: {intent.created_at}")
        if intent.related_claim_id:
            print(f"Related claim: {intent.related_claim_id}")
        return

    if object_type == "context":
        context = target
        print(f"Agent: {context.agent_id}")
        print(f"Topic: {context.topic}")
        print(f"Body: {format_body(context.body)}")
        print(f"Scope: {format_scope_list(context.scope)}")
        if context.git_branch:
            print(f"Branch: {context.git_branch}")
        print(f"Created: {context.created_at}")
        if context.acknowledgments:
            print(f"Acknowledgments: {format_context_ack_summary(context.acknowledgments)}")
        if context.related_claim_id:
            print(f"Related claim: {context.related_claim_id}")
        if context.related_intent_id:
            print(f"Related intent: {context.related_intent_id}")
        return

    if object_type == "conflict":
        conflict = target
        print(f"Kind: {conflict.kind}")
        print(f"Severity: {conflict.severity}")
        print(f"Status: {'active' if conflict.is_active else 'resolved'}")
        print(f"Summary: {conflict.summary}")
        print(f"Scope: {format_scope_list(conflict.scope)}")
        print(
            "Objects: "
            f"{conflict.object_type_a}={conflict.object_id_a}, "
            f"{conflict.object_type_b}={conflict.object_id_b}"
        )
        print(f"Created: {conflict.created_at}")
        if conflict.resolved_by:
            print(f"Resolved by: {conflict.resolved_by}")
        if conflict.resolved_at:
            print(f"Resolved at: {conflict.resolved_at}")
        if conflict.resolution_note:
            print(f"Resolution note: {conflict.resolution_note}")
        return

    raise ValueError(f"Unsupported timeline object type: {object_type}.")


def print_conflict_details(conflicts: tuple[object, ...] | list[object]) -> None:
    for conflict in conflicts:
        status = "active" if conflict.is_active else "resolved"
        print(
            f"- {status} {conflict.severity} {conflict.kind}: {conflict.summary} "
            f"[{conflict.id}]"
        )
        print(f"  scope: {format_scope_list(conflict.scope)}")
        print(
            "  objects: "
            f"{conflict.object_type_a}={conflict.object_id_a}, "
            f"{conflict.object_type_b}={conflict.object_id_b}"
        )
        if conflict.resolved_by:
            print(f"  resolved by: {conflict.resolved_by}")
        if conflict.resolved_at:
            print(f"  resolved at: {conflict.resolved_at}")
        if conflict.resolution_note:
            print(f"  note: {conflict.resolution_note}")


def print_recent_handoff(
    entry: ContextRecord,
    *,
    handoff_resume_command: Callable[[ContextRecord], str],
) -> None:
    print("Recent handoff:")
    print_context_entry(entry)
    print(f"  next: {handoff_resume_command(entry)}")


def print_context_entries(entries: tuple[object, ...], *, heading: str) -> None:
    print(f"{heading} ({len(entries)}):")
    if not entries:
        print("- none")
        return
    for entry in entries:
        print_context_entry(entry)


def print_context_entry(entry: ContextRecord) -> None:
    print(f"- {entry.topic} by {entry.agent_id} [{entry.id}]")
    if entry.scope:
        print(f"  scope: {format_scope_list(entry.scope)}")
    if entry.git_branch:
        print(f"  branch: {entry.git_branch}")
    print(f"  body: {format_body(entry.body)}")
    if entry.acknowledgments:
        print(f"  acknowledgments: {format_context_ack_summary(entry.acknowledgments)}")
    if entry.related_claim_id:
        print(f"  related claim: {entry.related_claim_id}")
    if entry.related_intent_id:
        print(f"  related intent: {entry.related_intent_id}")


def print_identity_summary(
    *,
    label: str,
    identity: dict[str, object],
) -> None:
    print(f"{label}: {identity['id']} (source: {identity['source']})")
    print(f"Terminal: {identity['terminal_identity']}")
    if identity.get("terminal_binding"):
        print(f"Terminal binding: {identity['terminal_binding']}")
    if identity.get("project_default_agent"):
        print(f"Project default: {identity['project_default_agent']}")
    if identity.get("identity_warning"):
        print(f"Identity note: {identity['identity_warning']}")


def print_scope_resolution(scope_resolution: dict[str, object]) -> None:
    mode = str(scope_resolution.get("mode", ""))
    if mode == "inferred":
        matched_tokens = tuple(scope_resolution.get("matched_tokens", ()))
        print(
            "Scope source: "
            f"inferred ({scope_resolution['confidence']} confidence; matched "
            f"{', '.join(str(token) for token in matched_tokens) or 'repo structure'})"
        )
    elif mode == "unscoped":
        print(f"Scope source: {scope_resolution['reason']}")


def worktree_adoption_command(
    worktree_signal: dict[str, object],
    *,
    intent_command: Callable[..., str],
    claim_command: Callable[..., str],
) -> str:
    suggested_scope = tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
    has_active_scope = bool(worktree_signal.get("has_active_scope", False))
    if has_active_scope:
        return intent_command(scope=suggested_scope)
    return claim_command(scope=suggested_scope)


def print_worktree_signal(
    worktree_signal: dict[str, object],
    *,
    heading: str,
    current_scope_label: str,
    intent_command: Callable[..., str],
    claim_command: Callable[..., str],
    show_next: bool = True,
) -> None:
    changed_paths = tuple(str(path) for path in worktree_signal.get("changed_paths", ()))
    drift_paths = tuple(str(path) for path in worktree_signal.get("drift_paths", ()))
    active_scope = tuple(str(path) for path in worktree_signal.get("active_scope", ()))
    suggested_scope = tuple(str(path) for path in worktree_signal.get("suggested_scope", ()))
    print(f"{heading}:")
    if not changed_paths:
        print("- clean")
        return
    print(f"- changed paths: {len(changed_paths)}")
    if active_scope:
        print(f"  {current_scope_label}: {format_scope_list(active_scope)}")
    else:
        print(f"  {current_scope_label}: (none)")
    if drift_paths:
        print(f"  outside scope: {format_scope_list(drift_paths)}")
        if suggested_scope:
            print(f"  suggested widened scope: {format_scope_list(suggested_scope)}")
            if show_next:
                print(
                    "  next: "
                    + worktree_adoption_command(
                        worktree_signal,
                        intent_command=intent_command,
                        claim_command=claim_command,
                    )
                )
    else:
        print("  outside scope: none")


def activity_suffix(agent_id: str, *, stale_agent_ids: set[str]) -> str:
    if agent_id in stale_agent_ids:
        return " (stale)"
    return ""


def print_active_work_recovery(
    *,
    active_work: dict[str, object],
    agent_id: str,
    active_work_completion_ready: Callable[..., bool],
    renew_command: Callable[..., str],
    intent_command: Callable[..., str],
    claim_command: Callable[..., str],
    worktree_signal: dict[str, object] | None = None,
) -> None:
    started_at = active_work.get("started_at")
    if started_at is None:
        return

    pending_context = tuple(active_work.get("pending_context", ()))
    conflicts = tuple(active_work.get("conflicts", ()))
    events = tuple(active_work.get("events", ()))
    priority = (
        active_work.get("lease_alert")
        or active_work.get("yield_alert")
        or active_work.get("priority")
    )
    react_now_context = tuple(active_work.get("react_now_context", ()))
    review_soon_context = tuple(active_work.get("review_soon_context", ()))
    expired_leases = tuple(active_work.get("expired_leases", ()))
    lease_alert = active_work.get("lease_alert")
    yield_alert = active_work.get("yield_alert")
    completion_ready = active_work_completion_ready(
        active_work=active_work,
        worktree_signal=worktree_signal,
    )

    print(f"Active work started: {started_at}")
    attention_parts = [
        f"{len(pending_context)} pending context",
        f"{len(conflicts)} active conflict(s)",
    ]
    if expired_leases:
        attention_parts.append(f"{len(expired_leases)} expired lease(s)")
    print("Before you continue: " + ", ".join(attention_parts))
    if isinstance(priority, dict):
        item_id = str(priority.get("id", "")).strip()
        identifier = "" if not item_id else f" [{item_id}]"
        kind = str(priority.get("kind", "")).strip()
        summary = str(priority.get("summary", "")).strip()
        label = " ".join(part for part in (kind, summary) if part).strip() or "top priority"
        print(f"Do this first: {label}{identifier}")
        next_step = str(priority.get("next_step", "")).strip()
        if next_step:
            print(f"  next: {next_step}")
    if expired_leases and not completion_ready:
        print()
        print("Lease attention:")
        for lease in expired_leases:
            print(
                f"- expired {lease['kind']} lease for {lease['description']} "
                f"[{lease['id']}] at {lease['lease_expires_at']}"
            )
        next_step = renew_command()
        if isinstance(lease_alert, dict):
            next_step = str(lease_alert.get("next_step", "")).strip() or next_step
        print(f"  next: {next_step}")
    if isinstance(yield_alert, dict):
        nearby = tuple(yield_alert.get("nearby", ()))
        print()
        print("Yield attention:")
        print(
            f"- {yield_alert.get('summary', 'Yield the current leased work before continuing.')}"
        )
        for item in nearby:
            if not isinstance(item, dict):
                continue
            overlap_scope = (
                ", ".join(str(part) for part in item.get("overlap_scope", ())) or "(none)"
            )
            print(
                f"- nearby {item.get('kind', 'work')} {item.get('id', '')} from {item.get('agent_id', '')}: "
                f"{item.get('description', '')}"
            )
            print(f"  overlap: {overlap_scope}")
        next_step = str(yield_alert.get("next_step", "")).strip() or "loom finish"
        print(f"  next: {next_step}")
    if conflicts or react_now_context:
        print()
        print("React now:")
        if react_now_context:
            for entry in react_now_context:
                print(f"- context {entry.topic} [{entry.id}] from {entry.agent_id}")
                print(
                    "  next: "
                    f"loom context ack {entry.id} --agent {agent_id} --status read"
                )
                print(
                    "  next: "
                    f"loom context ack {entry.id} --agent {agent_id} "
                    '--status adapted --note "<what changed>"'
                )
        if conflicts:
            for conflict in conflicts:
                print(f"- conflict {conflict.id}: {conflict.summary}")
                print(
                    "  next: "
                    f'loom resolve {conflict.id} --agent {agent_id} --note "<resolution>"'
                )
    if review_soon_context:
        print()
        print("Review soon:")
        for entry in review_soon_context:
            print(f"- context {entry.topic} [{entry.id}] from {entry.agent_id}")
            print(
                "  next: "
                f"loom context ack {entry.id} --agent {agent_id} --status read"
            )
    if completion_ready:
        print()
        print("Looks settled:")
        if expired_leases:
            print(
                "- no pending context, no active conflicts, no worktree drift, and the lease can be closed cleanly"
            )
        else:
            print("- no pending context, no active conflicts, and no worktree drift")
        print("  next: loom finish")
    if worktree_signal is not None and worktree_signal.get("has_drift"):
        print()
        print("Scope adoption:")
        print(
            "- "
            + worktree_adoption_command(
                worktree_signal,
                intent_command=intent_command,
                claim_command=claim_command,
            )
        )
    print()
    print_event_batch(events, heading="Relevant changes since active work started")


def format_context_ack_summary(acknowledgments: tuple[ContextAckRecord, ...]) -> str:
    return ", ".join(f"{ack.agent_id}={ack.status}" for ack in acknowledgments)


def context_ack_status_for_agent(
    entry: ContextRecord,
    agent_id: str,
) -> str | None:
    for ack in entry.acknowledgments:
        if ack.agent_id == agent_id:
            return ack.status
    return None


def print_inbox_snapshot(
    snapshot: InboxSnapshot,
    *,
    daemon_status: object | None = None,
    identity: dict[str, object] | None = None,
    heading: str | None = None,
    next_steps: tuple[str, ...] = (),
    identity_summary_printer: Callable[..., None] | None = None,
) -> None:
    print(heading or f"Inbox for {snapshot.agent_id}")
    if daemon_status is not None:
        print(f"Daemon: {daemon_status.describe()}")
    if identity is not None and identity_summary_printer is not None:
        identity_summary_printer(label="Identity", identity=identity)
    print(
        "Attention: "
        + guidance_inbox_attention_text(
            pending_context_count=len(snapshot.pending_context),
            conflict_count=len(snapshot.conflicts),
        )
    )
    print()

    print(f"Pending context ({len(snapshot.pending_context)}):")
    if snapshot.pending_context:
        for entry in snapshot.pending_context:
            print_context_entry(entry)
            print(
                "  next: "
                f"loom context ack {entry.id} --agent {snapshot.agent_id} --status read"
            )
            print(
                "  next: "
                f"loom context ack {entry.id} --agent {snapshot.agent_id} "
                '--status adapted --note "<what changed>"'
            )
    else:
        print("- none")

    print()
    print(f"Active conflicts ({len(snapshot.conflicts)}):")
    if snapshot.conflicts:
        print_conflict_details(snapshot.conflicts)
        for conflict in snapshot.conflicts:
            print(
                "  next: "
                f'loom resolve {conflict.id} --agent {snapshot.agent_id} --note "<resolution>"'
            )
    else:
        print("- none")

    if not snapshot.pending_context and not snapshot.conflicts and next_steps:
        print()
        print("Inbox is clear.")
        print("Next:")
        for step in next_steps:
            print(f"- {step}")

    print()
    print_event_batch(snapshot.events, heading="Recent triggers")


def format_scope_list(scope: tuple[str, ...]) -> str:
    if not scope:
        return "(none)"
    return ", ".join(scope)


def format_repo_lane_summary(lane: dict[str, object]) -> str:
    relationship = str(lane.get("relationship", "scope")).strip() or "scope"
    scope = tuple(str(item) for item in lane.get("scope", ()))
    participant_count = int(lane.get("participant_count", 0))
    urgency = str(lane.get("urgency", "ongoing")).strip() or "ongoing"
    label = "semantic lane" if relationship == "dependency" else "scope lane"
    return (
        f"{label} in {format_scope_list(scope)} "
        f"({participant_count} agent(s), {urgency})"
    )


def format_repo_program_summary(program: dict[str, object]) -> str:
    scope_hint = program.get("scope_hint")
    relationships = tuple(str(item) for item in program.get("relationships", ()))
    lane_count = int(program.get("lane_count", 0))
    participant_count = int(program.get("participant_count", 0))
    urgency = str(program.get("urgency", "ongoing")).strip() or "ongoing"
    relationship_label = "/".join(relationships) if relationships else "mixed"
    scope_label = str(scope_hint).strip() if scope_hint not in (None, "") else "cross-surface"
    return (
        f"{relationship_label} program around {scope_label} "
        f"({lane_count} lane(s), {participant_count} agent(s), {urgency})"
    )


def print_lease_details(
    lease_expires_at: str | None,
    *,
    label: str,
    lease_policy: str | None = None,
) -> None:
    if not lease_expires_at:
        return
    suffix_parts: list[str] = []
    if is_past_utc_timestamp(lease_expires_at):
        suffix_parts.append("expired")
    if lease_policy:
        suffix_parts.append(f"policy: {lease_policy}")
    suffix = f" ({'; '.join(suffix_parts)})" if suffix_parts else ""
    print(f"{label}: {lease_expires_at}{suffix}")


def format_body(body: str) -> str:
    return " ".join(part.strip() for part in body.splitlines() if part.strip()) or "(empty)"


def format_event_payload(payload: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(payload.items()))


def print_event_batch(events: tuple[object, ...], *, heading: str) -> None:
    print(f"{heading} ({len(events)}):")
    if not events:
        print("- none")
        return
    for event in events:
        print_event(event)


def print_event(event: EventRecord) -> None:
    print(f"- {event.timestamp} {event.type} by {event.actor_id} [{event.id}]")
    if event.payload:
        print(f"  payload: {format_event_payload(event.payload)}")
