from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .action_errors import (
    ConflictNotFoundError,
    ContextNotFoundError,
    NoActiveClaimError,
    NoActiveWorkError,
    ObjectNotFoundError,
    WhoamiSelectionError,
    recoverable_error_code,
)
from .authority import (
    authority_focus_reason as _authority_focus_reason,
    authority_focus_scope as _authority_focus_scope,
    authority_focus_summary as _authority_focus_summary,
    read_authority_summary as _read_authority_summary,
)
from .client import CoordinationClient
from .cli_actions import (
    agent_next_action as _agent_next_action,
    agent_next_steps as _agent_next_steps,
    agents_next_steps as _agents_next_steps,
    claim_command as _claim_command,
    command_action as _command_action,
    conflicts_next_action as _conflicts_next_action,
    conflicts_next_steps as _conflicts_next_steps,
    context_ack_next_steps as _context_ack_next_steps,
    context_read_next_steps as _context_read_next_steps,
    context_write_next_steps as _context_write_next_steps,
    error_next_steps as _error_next_steps,
    finish_next_steps as _finish_next_steps,
    handoff_resume_command as _handoff_resume_command,
    identity_env_binding_command as _identity_env_binding_command,
    inbox_next_action as _inbox_next_action,
    inbox_next_steps as _inbox_next_steps,
    intent_command as _intent_command,
    log_next_steps as _log_next_steps,
    onboarding_commands as _onboarding_commands,
    post_write_next_steps as _post_write_next_steps,
    priority_command_action as _priority_command_action,
    renew_command as _renew_command,
    renew_next_steps as _renew_next_steps,
    report_next_steps as _report_next_steps,
    resolve_next_steps as _resolve_next_steps,
    resume_next_action as _resume_next_action,
    resume_next_steps as _resume_next_steps,
    start_next_action as _start_next_action,
    start_next_steps as _start_next_steps,
    status_next_action as _status_next_action,
    status_next_steps as _status_next_steps,
    timeline_next_steps as _timeline_next_steps,
    unclaim_next_steps as _unclaim_next_steps,
    whoami_next_steps as _whoami_next_steps,
)
from .cli_follow import (
    emit_inbox_follow_update as _emit_inbox_follow_update,
    handle_context_follow as _handle_context_follow,
    handle_inbox_follow as _handle_inbox_follow,
    handle_log_follow as _handle_log_follow,
    read_event_batch as _read_event_batch,
)
from .cli_parser import build_parser as _build_parser
from .cli_runtime import (
    active_work_completion_ready as _active_work_completion_ready,
    active_work_context_reaction as _active_work_context_reaction,
    active_work_recovery as _active_work_recovery,
    active_work_with_repo_yield_alert as _active_work_with_repo_yield_alert,
    agent_activity_payload as _runtime_agent_activity_payload,
    build_client as _build_client,
    coerce_agent_presence_batch as _coerce_agent_presence_batch,
    daemon_result_payload as _daemon_result_payload,
    daemon_status_payload as _daemon_status_payload,
    identity_payload as _identity_payload,
    latest_recent_handoff as _latest_recent_handoff,
    partition_agents_by_activity as _runtime_partition_agents_by_activity,
    resolve_agent_identity_for_project as _resolve_agent_identity_for_project,
    stale_agent_ids as _runtime_stale_agent_ids,
    validated_lease_minutes as _validated_lease_minutes,
    validated_lease_policy as _validated_lease_policy,
)
from .cli_scope import (
    active_scope_for_worktree as _active_scope_for_worktree,
    infer_finish_scope as _infer_finish_scope,
    resolve_claim_scope as _resolve_claim_scope,
    resolve_intent_scope as _resolve_intent_scope,
    worktree_signal as _worktree_signal,
)
from .cli_output import (
    activity_suffix as _activity_suffix,
    context_ack_status_for_agent as _context_ack_status_for_agent,
    format_body as _format_body,
    format_context_ack_summary as _format_context_ack_summary,
    format_event_payload as _format_event_payload,
    format_repo_lane_summary as _format_repo_lane_summary,
    format_repo_program_summary as _format_repo_program_summary,
    format_scope_list as _format_scope_list,
    print_agent_presence as _print_agent_presence,
    print_conflict_details as _print_conflict_details,
    print_conflicts as _print_conflicts,
    print_context_dependencies as _print_context_dependencies,
    print_context_entries as _print_context_entries,
    print_context_entry as _print_context_entry,
    print_event as _print_event,
    print_event_batch as _print_event_batch,
    print_identity_summary as _print_identity_summary,
    print_idle_agents as _print_idle_agents,
    print_inbox_snapshot as _print_inbox_snapshot,
    print_lease_details as _print_lease_details,
    print_active_work_recovery as _output_print_active_work_recovery,
    print_recent_handoff as _print_recent_handoff,
    print_scope_resolution as _print_scope_resolution,
    print_timeline_target as _print_timeline_target,
    print_worktree_signal as _output_print_worktree_signal,
    worktree_adoption_command as _output_worktree_adoption_command,
)
from .daemon import (
    describe_protocol as describe_daemon_protocol,
    get_daemon_status,
    run_daemon,
    start_daemon,
    stop_daemon,
    DaemonControlResult,
    DaemonStatus,
)
from .identity import (
    current_terminal_identity,
    terminal_identity_process_is_alive,
)
from .guidance import (
    DEFAULT_RENEW_LEASE_MINUTES,
    agent_attention_payload as guidance_agent_attention_payload,
    agent_attention_text as guidance_agent_attention_text,
    inbox_attention_payload as guidance_inbox_attention_payload,
    repo_lanes_payload as guidance_repo_lanes_payload,
    start_attention_payload as guidance_start_attention_payload,
    start_summary as guidance_start_summary,
)
from .local_store import (
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    CoordinationStore,
    EventRecord,
    InboxSnapshot,
    IntentRecord,
)
from .mcp import run_mcp_server
from .protocol import describe_local_protocol
from .project import (
    LoomProject,
    LoomProjectError,
    clear_terminal_agent,
    initialize_project,
    load_project,
    set_resume_sequence,
    set_default_agent,
    set_terminal_agent,
)
from .reporting import build_coordination_report, render_coordination_report_html
from .util import infer_object_type as _infer_object_type
from .util import json_ready as _json_ready
from .util import (
    ACTIVE_RECORD_STALE_AFTER_HOURS,
    current_worktree_paths,
    is_past_utc_timestamp,
    is_stale_utc_timestamp,
    overlapping_scopes,
)

RECENT_HANDOFF_WINDOW_HOURS = 24 * 7

STATUS_AGENT_ACTIVITY_LIMIT = 100

START_QUICK_LOOP = (
    "start: run loom start, follow the next action, then loop back if needed",
    "claim: say what you're working on before edits",
    "intent: say what you're about to touch only when the scope gets specific",
    "inbox: react to context or conflicts before continuing",
    "finish: release work cleanly when you're done for now",
)

START_COMMAND_GUIDE = (
    {
        "command": "loom start",
        "summary": "Read the board, then follow Loom's best next move.",
    },
    {
        "command": "loom claim",
        "summary": "Reserve the work before edits.",
    },
    {
        "command": "loom intent",
        "summary": "Narrow to the exact scope once the edit is specific.",
    },
    {
        "command": "loom inbox",
        "summary": "React to context or conflicts before continuing.",
    },
    {
        "command": "loom finish",
        "summary": "Release work cleanly when you are done for now.",
    },
)

START_AGENT_RULES = (
    "Use Loom only for coordination in this repository.",
    "Do not inspect `.loom/`, `.loom-reports/`, Loom docs, or Loom source unless Loom's available commands are insufficient for the task.",
    "Follow the `Do this first` command above, then loop back with `loom start` if you need another move.",
)


def build_parser() -> argparse.ArgumentParser:
    return _build_parser(
        handlers={
            "init": _handle_init,
            "start": _handle_start,
            "whoami": _handle_whoami,
            "claim": _handle_claim,
            "intent": _handle_intent,
            "unclaim": _handle_unclaim,
            "finish": _handle_finish,
            "clean": _handle_clean,
            "renew": _handle_renew,
            "status": _handle_status,
            "report": _handle_report,
            "resume": _handle_resume,
            "agents": _handle_agents,
            "agent": _handle_agent,
            "inbox": _handle_inbox,
            "conflicts": _handle_conflicts,
            "resolve": _handle_resolve,
            "log": _handle_log,
            "timeline": _handle_timeline,
            "context_write": _handle_context_write,
            "context_ack": _handle_context_ack,
            "context_read": _handle_context_read,
            "protocol": _handle_protocol,
            "mcp": _handle_mcp,
            "daemon_start": _handle_daemon_start,
            "daemon_stop": _handle_daemon_stop,
            "daemon_status": _handle_daemon_status,
            "daemon_run": _handle_daemon_run,
            "daemon_ping": _handle_daemon_ping,
        },
    )


def _worktree_adoption_command(worktree_signal: dict[str, object]) -> str:
    return _output_worktree_adoption_command(
        worktree_signal,
        intent_command=_intent_command,
        claim_command=_claim_command,
    )


def _print_worktree_signal(
    worktree_signal: dict[str, object],
    *,
    heading: str,
    current_scope_label: str,
    show_next: bool = True,
) -> None:
    _output_print_worktree_signal(
        worktree_signal,
        heading=heading,
        current_scope_label=current_scope_label,
        intent_command=_intent_command,
        claim_command=_claim_command,
        show_next=show_next,
    )


def _self_suffix(agent_id: str, *, current_agent_id: str) -> str:
    return " (you)" if agent_id == current_agent_id else ""


def _emit_json(args: argparse.Namespace, **payload: object) -> bool:
    if not getattr(args, "json", False):
        return False
    _write_json_line({"ok": True, **payload})
    return True


def _write_json_line(payload: dict[str, object], *, stream: object | None = None) -> None:
    target = sys.stdout if stream is None else stream
    print(json.dumps(_json_ready(payload), sort_keys=True, ensure_ascii=False), file=target)


def _partition_agents_by_activity(
    agents,
):
    return _runtime_partition_agents_by_activity(
        agents,
        is_stale_timestamp=is_stale_utc_timestamp,
        is_past_timestamp=is_past_utc_timestamp,
    )


def _agent_activity_payload(
    agents,
):
    return _runtime_agent_activity_payload(
        agents,
        is_stale_timestamp=is_stale_utc_timestamp,
        is_past_timestamp=is_past_utc_timestamp,
    )


def _stale_agent_ids(
    agents,
):
    return _runtime_stale_agent_ids(
        agents,
        is_stale_timestamp=is_stale_utc_timestamp,
        is_past_timestamp=is_past_utc_timestamp,
    )


def _dead_session_agent_ids(
    agents,
):
    return tuple(
        str(presence.agent_id)
        for presence in agents
        if terminal_identity_process_is_alive(str(presence.agent_id)) is False
    )


def _start_command_guide(
    *,
    include_init: bool,
    bind_command: str | None,
    include_cleanup: bool,
) -> tuple[dict[str, str], ...]:
    guide = list(START_COMMAND_GUIDE)
    if include_init:
        guide.insert(
            1,
            {
                "command": "loom init --no-daemon",
                "summary": "Initialize Loom in this repository before coordination begins.",
            },
        )
    if bind_command:
        guide.insert(
            2 if include_init else 1,
            {
                "command": bind_command,
                "summary": "Pin a stable agent identity before coordinated work.",
            },
        )
    if include_cleanup:
        guide.append(
            {
                "command": "loom clean",
                "summary": "Sweep dead pid sessions off the board and prune idle history.",
            },
    )
    return tuple(guide)


def _print_start_next_action(next_action: dict[str, object] | None) -> None:
    if not isinstance(next_action, dict):
        return
    summary = str(next_action.get("summary", "")).strip()
    command = str(next_action.get("command", "")).strip()
    reason = str(next_action.get("reason", "")).strip()
    if summary:
        print(f"Do this first: {summary}")
    if command:
        print(f"  next: {command}")
    if reason:
        print(f"  why: {reason}")


def _print_start_agent_rules() -> None:
    print("Coordination rule:")
    for rule in START_AGENT_RULES:
        print(f"- {rule}")


def _authority_summary(
    *,
    project: LoomProject | None,
    changed_paths: tuple[str, ...] = (),
    claims: tuple[ClaimRecord, ...] = (),
    intents: tuple[IntentRecord, ...] = (),
) -> dict[str, object]:
    if project is None:
        return {
            "enabled": False,
            "status": "absent",
            "config_path": "loom.yaml",
            "surface_count": 0,
            "surfaces": (),
            "changed_surfaces": (),
            "changed_scope_hints": (),
            "declaration_changed": False,
            "issues": (),
            "error_code": None,
            "next_steps": (),
            "affected_active_work": (),
        }
    effective_changed_paths = changed_paths or current_worktree_paths(project.repo_root)
    return _read_authority_summary(
        project.repo_root,
        changed_paths=tuple(str(path) for path in effective_changed_paths),
        claims=claims,
        intents=intents,
    )


def _print_authority_summary(authority: dict[str, object] | None) -> None:
    if not isinstance(authority, dict):
        return
    status = str(authority.get("status", "absent"))
    if status == "absent":
        return
    config_path = str(authority.get("config_path", "loom.yaml"))
    print("Authority:")
    if status == "invalid":
        print(f"- invalid declaration in {config_path}")
        issues = tuple(authority.get("issues", ()))
        if issues and isinstance(issues[0], dict):
            message = str(issues[0].get("message", "")).strip()
            if message:
                print(f"  reason: {message}")
        next_steps = tuple(str(step) for step in authority.get("next_steps", ()))
        if next_steps:
            print("  next:")
            for step in next_steps:
                print(f"  - {step}")
        return
    surface_count = int(authority.get("surface_count", 0))
    print(f"- {surface_count} declared surface(s) in {config_path}")
    changed_surfaces = tuple(authority.get("changed_surfaces", ()))
    if changed_surfaces:
        print(f"- changed authority surface(s): {len(changed_surfaces)}")
        for surface in changed_surfaces[:3]:
            if not isinstance(surface, dict):
                continue
            path = str(surface.get("path", "")).strip()
            role = str(surface.get("role", "")).strip()
            if path and role:
                print(f"  - {path} ({role})")
            elif path:
                print(f"  - {path}")
        if len(changed_surfaces) > 3:
            print(f"  - {len(changed_surfaces) - 3} more changed authority surface(s)")
    changed_scope_hints = tuple(str(path) for path in authority.get("changed_scope_hints", ()))
    if changed_scope_hints:
        print(f"- changed authority scope hint(s): {len(changed_scope_hints)}")
        for path in changed_scope_hints[:3]:
            print(f"  - {path}")
        if len(changed_scope_hints) > 3:
            print(f"  - {len(changed_scope_hints) - 3} more changed authority scope hint(s)")
    affected_active_work = tuple(authority.get("affected_active_work", ()))
    if affected_active_work:
        print(f"- affected active work: {len(affected_active_work)}")
        for item in affected_active_work[:3]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "work")).strip() or "work"
            agent_id = str(item.get("agent_id", "")).strip()
            overlap_scope = tuple(str(path).strip() for path in item.get("overlap_scope", ()))
            overlap_label = ", ".join(path for path in overlap_scope if path)
            if agent_id and overlap_label:
                print(f"  - {kind} by {agent_id} on {overlap_label}")
            elif agent_id:
                print(f"  - {kind} by {agent_id}")
            elif overlap_label:
                print(f"  - {kind} on {overlap_label}")
        if len(affected_active_work) > 3:
            print(f"  - {len(affected_active_work) - 3} more affected active work item(s)")


def _authority_recovery_action(
    authority: dict[str, object] | None,
    *,
    rerun_command: str,
) -> dict[str, object] | None:
    if not isinstance(authority, dict) or authority.get("status") != "invalid":
        return None
    config_path = str(authority.get("config_path", "loom.yaml"))
    reason = f"Loom cannot trust declared repository truth until {config_path} is valid."
    issues = tuple(authority.get("issues", ()))
    if issues and isinstance(issues[0], dict):
        message = str(issues[0].get("message", "")).strip()
        if message:
            reason = message
    return {
        "command": f"fix {config_path}",
        "summary": f"Fix the declared authority configuration in {config_path}.",
        "reason": reason,
        "confidence": "high",
        "kind": "authority",
        "rerun_command": rerun_command,
    }


def _authority_recovery_steps(
    authority: dict[str, object] | None,
    *,
    rerun_command: str,
) -> tuple[str, ...]:
    action = _authority_recovery_action(authority, rerun_command=rerun_command)
    if action is None:
        return ()
    return (
        str(action["command"]),
        rerun_command,
    )


def _authority_focus_action(
    authority: dict[str, object] | None,
) -> dict[str, object] | None:
    if not isinstance(authority, dict) or authority.get("status") != "valid":
        return None
    scope = _authority_focus_scope(authority)
    if not scope:
        return None
    return _command_action(
        command=_claim_command(scope=scope),
        summary=_authority_focus_summary(authority)
        or "Review the repo surfaces affected by the authority change.",
        reason=_authority_focus_reason(authority)
        or "Loom is treating these affected authority surfaces as the first repository truth to coordinate.",
        confidence="high",
        kind="authority",
    )


def _authority_focus_steps(authority: dict[str, object] | None) -> tuple[str, ...]:
    action = _authority_focus_action(authority)
    if action is None:
        return ()
    return (
        str(action["command"]),
        "loom status",
    )


def _should_promote_authority_focus(
    authority: dict[str, object] | None,
    *,
    next_action: dict[str, object] | None,
    has_active_work: bool,
) -> bool:
    if _authority_focus_action(authority) is None or has_active_work:
        return False
    if not isinstance(next_action, dict):
        return True
    command = str(next_action.get("command", "")).strip()
    return command in {"loom start", "loom status"} or command.startswith("loom claim ")


def _adopt_bound_terminal_work(
    *,
    project: LoomProject,
    terminal_identity: str,
    bound_agent_id: str,
) -> dict[str, object]:
    if terminal_identity == bound_agent_id:
        return {
            "source_had_work": False,
            "target_had_work": False,
            "adopted_claim": None,
            "adopted_intent": None,
        }
    client = _build_client(project)
    try:
        return client.store.adopt_agent_work(
            from_agent_id=terminal_identity,
            to_agent_id=bound_agent_id,
            source="terminal",
        )
    finally:
        client.close()


def _handle_init(args: argparse.Namespace) -> int:
    project, created = initialize_project()
    if args.agent:
        project = set_default_agent(args.agent, project.repo_root)
    store = CoordinationStore(project.db_path)
    store.initialize()
    daemon_payload: dict[str, object]
    agent_id, source = _resolve_agent_identity_for_project(args=None, project=project)
    identity = _identity_payload(project=project, agent_id=agent_id, source=source)

    if created:
        init_message = f"Initialized Loom in {project.loom_dir}"
    else:
        init_message = f"Loom is already initialized in {project.repo_root}"
    next_steps = _onboarding_commands(default_agent=project.default_agent, identity=identity)
    next_command = next_steps[1] if project.default_agent else next_steps[0]

    if args.no_daemon:
        daemon_payload = {
            "requested": False,
            "detail": "skipped (--no-daemon)",
        }
    else:
        try:
            result = start_daemon(project, timeout=0.75)
            daemon_payload = {
                "requested": True,
                "result": _daemon_result_payload(result),
            }
        except RuntimeError as error:
            daemon_payload = {
                "requested": True,
                "detail": "direct SQLite mode",
                "error": str(error),
            }

    if _emit_json(
        args,
        project=project,
        created=created,
        default_agent=project.default_agent,
        daemon=daemon_payload,
        next_command=next_command,
        next_steps=next_steps,
    ):
        return 0

    print(init_message)
    print(f"Store: {project.db_path}")
    print(f"Daemon socket: {project.socket_path}")
    if project.default_agent:
        print(f"Default agent: {project.default_agent}")
    if args.no_daemon:
        print("Daemon: skipped (--no-daemon)")
    elif "result" in daemon_payload:
        result_payload = daemon_payload["result"]
        print(f"Daemon: {result_payload['detail']}")
        if result_payload.get("pid") is not None:
            print(f"PID: {result_payload['pid']}")
    else:
        print("Daemon: direct SQLite mode")
        print(f"Reason: {daemon_payload['error']}")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_start(args: argparse.Namespace) -> int:
    try:
        project = load_project()
    except LoomProjectError:
        project = None
    bound_adoption: dict[str, object] | None = None
    if args.bind and project is not None:
        terminal_identity = current_terminal_identity()
        project = set_terminal_agent(
            args.bind,
            terminal_identity=terminal_identity,
        )
        bound_adoption = {
            "terminal_identity": terminal_identity,
            **_adopt_bound_terminal_work(
                project=project,
                terminal_identity=terminal_identity,
                bound_agent_id=args.bind,
            ),
        }

    agent_id, source = _resolve_agent_identity_for_project(
        args=None,
        project=project,
    )
    identity = _identity_payload(project=project, agent_id=agent_id, source=source)

    snapshot = None
    agent_snapshot = None
    inbox_snapshot = None
    daemon_status = None
    active_work = None
    recent_handoff = None
    worktree_signal = None
    repo_lanes = {
        "acknowledged_migration_lanes": 0,
        "fresh_acknowledged_migration_lanes": 0,
        "ongoing_acknowledged_migration_lanes": 0,
        "acknowledged_migration_programs": 0,
        "fresh_acknowledged_migration_programs": 0,
        "ongoing_acknowledged_migration_programs": 0,
        "agents": (),
        "lanes": (),
        "programs": (),
    }
    dead_session_ids: tuple[str, ...] = ()
    authority = _authority_summary(project=project)

    if project is not None:
        client = _build_client(project)
        snapshot = client.read_status()
        daemon_status = client.daemon_status()
        agents = _coerce_agent_presence_batch(client.read_agents(limit=STATUS_AGENT_ACTIVITY_LIMIT))
        dead_session_ids = _dead_session_agent_ids(agents)
        stale_agent_ids = _stale_agent_ids(agents)
        repo_lanes = guidance_repo_lanes_payload(
            agents=agents,
            snapshot=snapshot,
            store=client.store,
            stale_agent_ids=stale_agent_ids,
        )
        if identity["source"] != "tty":
            agent_snapshot = client.read_agent_snapshot(
                agent_id=agent_id,
                context_limit=5,
                event_limit=10,
            )
            inbox_snapshot = client.read_inbox_snapshot(
                agent_id=agent_id,
                context_limit=5,
                event_limit=10,
            )
            active_work = _active_work_recovery(
                store=client.store,
                agent_id=agent_id,
                claim=agent_snapshot.claim,
                intent=agent_snapshot.intent,
                pending_context=inbox_snapshot.pending_context,
                conflicts=tuple(agent_snapshot.conflicts),
                context_limit=5,
                event_limit=10,
            )
            active_work = _active_work_with_repo_yield_alert(
                store=client.store,
                active_work=active_work,
                agent_id=agent_id,
                claim=agent_snapshot.claim,
                intent=agent_snapshot.intent,
                snapshot=snapshot,
                stale_agent_ids=stale_agent_ids,
            )
            worktree_signal = _worktree_signal(
                project_root=project.repo_root,
                claim=agent_snapshot.claim,
                intent=agent_snapshot.intent,
            )
            if active_work is not None and active_work.get("started_at") is None:
                recent_handoff = _latest_recent_handoff(
                    store=client.store,
                    agent_id=agent_id,
                )
        authority = _authority_summary(
            project=project,
            changed_paths=tuple(str(path) for path in current_worktree_paths(project.repo_root)),
            claims=snapshot.claims,
            intents=snapshot.intents,
        )

    mode, summary = guidance_start_summary(
        project_initialized=project is not None,
        identity=identity,
        snapshot=snapshot,
        agent_snapshot=agent_snapshot,
        inbox_snapshot=inbox_snapshot,
        active_work=active_work,
        repo_lanes=repo_lanes,
        recent_handoff=recent_handoff,
        worktree_signal=worktree_signal,
    )
    next_steps = _start_next_steps(
        project=project,
        identity=identity,
        dead_session_count=len(dead_session_ids),
        snapshot=snapshot,
        agent_snapshot=agent_snapshot,
        inbox_snapshot=inbox_snapshot,
        active_work=active_work,
        recent_handoff=recent_handoff,
        worktree_signal=worktree_signal,
        is_past_timestamp=is_past_utc_timestamp,
    )
    attention = guidance_start_attention_payload(
        snapshot=snapshot,
        inbox_snapshot=inbox_snapshot,
        worktree_signal=worktree_signal,
        repo_lanes=repo_lanes,
    )
    next_action = _start_next_action(
        project=project,
        identity=identity,
        dead_session_count=len(dead_session_ids),
        snapshot=snapshot,
        agent_snapshot=agent_snapshot,
        inbox_snapshot=inbox_snapshot,
        active_work=active_work,
        repo_lanes=repo_lanes,
        recent_handoff=recent_handoff,
        worktree_signal=worktree_signal,
    )
    authority_recovery = _authority_recovery_action(authority, rerun_command="loom start")
    if authority_recovery is not None:
        config_path = str(authority.get("config_path", "loom.yaml"))
        mode = "attention"
        summary = (
            f"Declared authority is invalid in {config_path}; "
            "fix it before starting new coordinated work."
        )
        next_action = authority_recovery
        next_steps = _authority_recovery_steps(authority, rerun_command="loom start")
    elif _should_promote_authority_focus(
        authority,
        next_action=next_action,
        has_active_work=bool(active_work is not None and active_work.get("started_at") is not None),
    ):
        mode = "attention"
        summary = _authority_focus_summary(authority) or "Authority changed; coordinate the affected truth surfaces before other work."
        next_action = _authority_focus_action(authority)
        next_steps = _authority_focus_steps(authority)
    bind_command = None
    if identity["source"] == "tty":
        bind_command = (
            "loom start --bind <agent-name>"
            if identity.get("stable_terminal_identity", True)
            else _identity_env_binding_command(identity)
        )
    elif (
        identity["source"] == "terminal"
        and not identity.get("stable_terminal_identity", True)
    ):
        bind_command = _identity_env_binding_command(identity)
    command_guide = _start_command_guide(
        include_init=project is None,
        bind_command=bind_command,
        include_cleanup=bool(dead_session_ids),
    )

    if _emit_json(
        args,
        mode=mode,
        summary=summary,
        project=project,
        identity=identity,
        daemon=None if daemon_status is None else _daemon_status_payload(daemon_status),
        attention=attention,
        repo_lanes=repo_lanes,
        active_work=active_work,
        handoff=recent_handoff,
        worktree=worktree_signal,
        authority=authority,
        dead_session_agents=dead_session_ids,
        quick_loop=START_QUICK_LOOP,
        command_guide=command_guide,
        next_action=next_action,
        next_steps=next_steps,
    ):
        return 0

    print("Loom start")
    if project is None:
        print("Project: not initialized")
    else:
        print(f"Project: {project.repo_root}")
        print(f"Daemon: {daemon_status.describe()}")
    if args.bind and project is not None:
        terminal_identity = str(identity["terminal_identity"])
        print(f"Terminal binding set: {project.terminal_aliases.get(terminal_identity)}")
        print(
            "Coordination rule: Loom is already active here. Do not inspect `.loom/`, `.loom-reports/`, or Loom internals; run `loom start` and follow the returned next action."
        )
        if bound_adoption is not None:
            adopted_claim = bound_adoption.get("adopted_claim")
            adopted_intent = bound_adoption.get("adopted_intent")
            source_had_work = bool(bound_adoption.get("source_had_work"))
            target_had_work = bool(bound_adoption.get("target_had_work"))
            if adopted_claim is not None or adopted_intent is not None:
                print(f"Adopted active work from: {terminal_identity}")
                if adopted_claim is not None:
                    print(f"- Claim: {adopted_claim.id}")
                if adopted_intent is not None:
                    print(f"- Intent: {adopted_intent.id}")
            elif source_had_work and target_had_work:
                print(f"Active work under {terminal_identity} was left in place.")
                print(
                    f"Reason: {args.bind} already has active Loom work. "
                    f"Use `loom clean` or `loom finish --agent {terminal_identity}` if you want to clear it."
                )
    _print_identity_summary(label="Identity", identity=identity)
    print(f"Mode: {mode}")
    print(f"Summary: {summary}")
    _print_authority_summary(authority)
    if dead_session_ids:
        print(f"Dead pid sessions: {len(dead_session_ids)}")
        print("Cleanup: run `loom clean` to close dead session work and prune idle history.")
    authority_invalid = authority.get("status") == "invalid"
    if active_work is None or active_work.get("started_at") is None:
        _print_start_next_action(next_action)
        if not authority_invalid:
            _print_start_agent_rules()
    if not authority_invalid and active_work is None and mode in {"uninitialized", "needs_identity", "ready"}:
        print("Quick loop:")
        for step in START_QUICK_LOOP:
            print(f"- {step}")
        print("Command guide:")
        for entry in command_guide:
            print(f"- {entry['command']}: {entry['summary']}")
    if any(attention.values()):
        print(
            "Attention: "
            f"{attention['claims']} claim(s), "
            f"{attention['intents']} intent(s), "
            f"{attention['context']} context note(s), "
            f"{attention['conflicts']} conflict(s)"
        )
        if attention["pending_context"] or attention["agent_conflicts"]:
            print(
                "For you: "
                f"{attention['pending_context']} pending context, "
                f"{attention['agent_conflicts']} active conflicts"
            )
        if attention["worktree_drift"]:
            print(f"Worktree drift: {attention['worktree_drift']} changed path(s) outside current Loom scope")
        if attention["acknowledged_migration_lanes"]:
            print(
                "Migration lanes: "
                f"{attention['acknowledged_migration_lanes']} acknowledged lane(s) already in flight"
            )
            if repo_lanes["acknowledged_migration_programs"]:
                print(
                    "Migration programs: "
                    f"{repo_lanes['acknowledged_migration_programs']} grouped program(s)"
                )
            top_lane = tuple(repo_lanes.get("lanes", ()))[0] if tuple(repo_lanes.get("lanes", ())) else None
            if isinstance(top_lane, dict):
                print(f"Top lane: {_format_repo_lane_summary(top_lane)}")
                if attention["acknowledged_migration_lanes"] > 1:
                    print(
                        "Other lanes: "
                        f"{attention['acknowledged_migration_lanes'] - 1} more acknowledged lane(s)"
                    )
    if active_work is not None and active_work.get("started_at") is not None:
        print()
        _print_active_work_recovery(
            active_work=active_work,
            agent_id=agent_id,
            worktree_signal=worktree_signal,
        )
    if worktree_signal is not None:
        print()
        _print_worktree_signal(
            worktree_signal,
            heading="Working tree",
            current_scope_label="current claim/intent scope",
            show_next=active_work is None or active_work.get("started_at") is None,
        )
    if recent_handoff is not None:
        print()
        _print_recent_handoff(
            recent_handoff,
            handoff_resume_command=_handoff_resume_command,
        )
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_whoami(args: argparse.Namespace) -> int:
    action_count = sum(
        1
        for flag in (bool(args.set_agent), bool(args.bind), bool(args.unbind))
        if flag
    )
    if action_count > 1:
        raise WhoamiSelectionError()

    project: LoomProject | None = None
    bound_adoption: dict[str, object] | None = None
    if args.bind:
        terminal_identity = current_terminal_identity()
        project = set_terminal_agent(
            args.bind,
            terminal_identity=terminal_identity,
        )
        bound_adoption = {
            "terminal_identity": terminal_identity,
            **_adopt_bound_terminal_work(
                project=project,
                terminal_identity=terminal_identity,
                bound_agent_id=args.bind,
            ),
        }
    elif args.unbind:
        terminal_identity = current_terminal_identity()
        project = clear_terminal_agent(
            terminal_identity=terminal_identity,
        )
    elif args.set_agent:
        project = set_default_agent(args.set_agent)
    else:
        try:
            project = load_project()
        except LoomProjectError:
            project = None

    agent_id, source = _resolve_agent_identity_for_project(
        args=None,
        project=project,
    )
    payload = _identity_payload(project=project, agent_id=agent_id, source=source)
    next_steps = _whoami_next_steps(project=project, identity=payload)
    terminal_identity = str(payload["terminal_identity"])
    if _emit_json(
        args,
        agent=payload,
        project=project,
        next_steps=next_steps,
        binding_adoption=bound_adoption,
    ):
        return 0

    if args.set_agent:
        print(f"Default agent set: {project.default_agent}")
    elif args.bind:
        print(f"Terminal binding set: {project.terminal_aliases.get(terminal_identity)}")
        print(
            "Coordination rule: Loom is already active here. Do not inspect `.loom/`, `.loom-reports/`, or Loom internals; run `loom start` and follow the returned next action."
        )
        if bound_adoption is not None:
            adopted_claim = bound_adoption.get("adopted_claim")
            adopted_intent = bound_adoption.get("adopted_intent")
            source_had_work = bool(bound_adoption.get("source_had_work"))
            target_had_work = bool(bound_adoption.get("target_had_work"))
            if adopted_claim is not None or adopted_intent is not None:
                print(f"Adopted active work from: {terminal_identity}")
                if adopted_claim is not None:
                    print(f"- Claim: {adopted_claim.id}")
                if adopted_intent is not None:
                    print(f"- Intent: {adopted_intent.id}")
            elif source_had_work and target_had_work:
                print(f"Active work under {terminal_identity} was left in place.")
                print(
                    f"Reason: {args.bind} already has active Loom work. "
                    f"Use `loom clean` or `loom finish --agent {terminal_identity}` if you want to clear it."
                )
    elif args.unbind:
        print(f"Terminal binding cleared: {terminal_identity}")
    _print_identity_summary(label="Agent", identity=payload)
    if project is not None:
        print(f"Project: {project.repo_root}")
    else:
        print("Project: not initialized")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_claim(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    scope, scope_resolution = _resolve_claim_scope(
        project_root=client.project.repo_root,
        description=args.description,
        explicit_scope=args.scope,
    )
    lease_minutes = _validated_lease_minutes(args.lease_minutes)
    lease_policy = _validated_lease_policy(
        args.lease_policy,
        lease_minutes=lease_minutes,
    )
    claim, conflicts = client.create_claim(
        agent_id=agent_id,
        description=args.description,
        scope=scope,
        source=source,
        lease_minutes=lease_minutes,
        lease_policy=lease_policy,
    )
    next_steps = _post_write_next_steps(has_conflicts=bool(conflicts))

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        claim=claim,
        scope_resolution=scope_resolution,
        conflicts=conflicts,
        next_steps=next_steps,
    ):
        return 0

    print(f"Claim recorded: {claim.id}")
    print(f"Agent: {claim.agent_id}")
    print(f"Description: {claim.description}")
    print(f"Scope: {_format_scope_list(claim.scope)}")
    _print_scope_resolution(scope_resolution)
    if claim.git_branch:
        print(f"Branch: {claim.git_branch}")
    _print_lease_details(
        claim.lease_expires_at,
        label="Lease until",
        lease_policy=claim.lease_policy,
    )
    _print_conflicts(conflicts)
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_intent(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    scope, scope_resolution = _resolve_intent_scope(
        project_root=client.project.repo_root,
        description=args.description,
        explicit_scope=args.scope,
    )
    if not scope:
        raise ValueError(str(scope_resolution["reason"]))
    lease_minutes = _validated_lease_minutes(args.lease_minutes)
    lease_policy = _validated_lease_policy(
        args.lease_policy,
        lease_minutes=lease_minutes,
    )
    intent, conflicts = client.declare_intent(
        agent_id=agent_id,
        description=args.description,
        reason=args.reason or args.description,
        scope=scope,
        source=source,
        lease_minutes=lease_minutes,
        lease_policy=lease_policy,
    )
    next_steps = _post_write_next_steps(has_conflicts=bool(conflicts))

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        intent=intent,
        scope_resolution=scope_resolution,
        conflicts=conflicts,
        next_steps=next_steps,
    ):
        return 0

    print(f"Intent recorded: {intent.id}")
    print(f"Agent: {intent.agent_id}")
    print(f"Description: {intent.description}")
    print(f"Reason: {intent.reason}")
    print(f"Scope: {_format_scope_list(intent.scope)}")
    _print_scope_resolution(scope_resolution)
    if intent.git_branch:
        print(f"Branch: {intent.git_branch}")
    _print_lease_details(
        intent.lease_expires_at,
        label="Lease until",
        lease_policy=intent.lease_policy,
    )
    if intent.related_claim_id:
        print(f"Related claim: {intent.related_claim_id}")
    _print_conflicts(conflicts)
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_unclaim(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, _ = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    claim = client.release_claim(agent_id=agent_id)
    if claim is None:
        raise NoActiveClaimError(agent_id)
    next_steps = _unclaim_next_steps()

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        claim=claim,
        next_steps=next_steps,
    ):
        return 0

    print(f"Claim released: {claim.id}")
    print(f"Agent: {claim.agent_id}")
    print(f"Description: {claim.description}")
    print(f"Scope: {_format_scope_list(claim.scope)}")
    if claim.git_branch:
        print(f"Branch: {claim.git_branch}")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_renew(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    lease_minutes = _validated_lease_minutes(args.lease_minutes) or DEFAULT_RENEW_LEASE_MINUTES
    renewed_claim = client.renew_claim(
        agent_id=agent_id,
        lease_minutes=lease_minutes,
        source=source,
    )
    renewed_intent = client.renew_intent(
        agent_id=agent_id,
        lease_minutes=lease_minutes,
        source=source,
    )
    if renewed_claim is None and renewed_intent is None:
        raise NoActiveWorkError(agent_id)
    next_steps = _renew_next_steps()

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        identity=_identity_payload(project=client.project, agent_id=agent_id, source=source),
        lease_minutes=lease_minutes,
        claim=renewed_claim,
        intent=renewed_intent,
        next_steps=next_steps,
    ):
        return 0

    print(f"Lease renewed for {agent_id}")
    print(f"Lease window: {lease_minutes} minute(s)")
    if renewed_claim is not None:
        print(f"Claim renewed: {renewed_claim.id}")
        print(f"Claim: {renewed_claim.description}")
        _print_lease_details(
            renewed_claim.lease_expires_at,
            label="Claim lease until",
            lease_policy=renewed_claim.lease_policy,
        )
    else:
        print("Claim renewed: none")
    if renewed_intent is not None:
        print(f"Intent renewed: {renewed_intent.id}")
        print(f"Intent: {renewed_intent.description}")
        _print_lease_details(
            renewed_intent.lease_expires_at,
            label="Intent lease until",
            lease_policy=renewed_intent.lease_policy,
        )
    else:
        print("Intent renewed: none")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_finish(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    snapshot = client.read_agent_snapshot(agent_id=agent_id)
    if snapshot.claim is None and snapshot.intent is None and not args.note:
        raise NoActiveWorkError(
            agent_id,
            detail="Use --note to publish a handoff without active work.",
        )

    context = None
    context_conflicts: tuple[object, ...] = ()
    if args.note:
        context, context_conflicts = client.publish_context(
            agent_id=agent_id,
            topic=args.topic,
            body=args.note,
            scope=_infer_finish_scope(
                explicit_scope=args.scope,
                claim=snapshot.claim,
                intent=snapshot.intent,
            ),
            source=source,
        )
    released_intent = client.release_intent(agent_id=agent_id)
    released_claim = client.release_claim(agent_id=agent_id)
    pruned_idle_agents: tuple[str, ...] = ()
    if not args.keep_idle:
        pruned_idle_agents = client.store.prune_idle_agents(agent_ids=(agent_id,))
    next_steps = _finish_next_steps(wrote_context=context is not None)

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        identity=_identity_payload(project=client.project, agent_id=agent_id, source=source),
        context=context,
        context_conflicts=context_conflicts,
        intent=released_intent,
        claim=released_claim,
        pruned_idle_agents=pruned_idle_agents,
        next_steps=next_steps,
    ):
        return 0

    print(f"Session finished for {agent_id}")
    if context is not None:
        print(f"Context recorded: {context.id}")
        print(f"Topic: {context.topic}")
        print(f"Scope: {_format_scope_list(context.scope)}")
        _print_context_dependencies(context_conflicts)
    if released_intent is not None:
        print(f"Intent released: {released_intent.id}")
        print(f"Intent: {released_intent.description}")
    else:
        print("Intent released: none")
    if released_claim is not None:
        print(f"Claim released: {released_claim.id}")
        print(f"Claim: {released_claim.description}")
    else:
        print("Claim released: none")
    if args.keep_idle:
        print("Idle agent history: kept (--keep-idle)")
    elif pruned_idle_agents:
        print("Idle agent history: pruned")
    else:
        print("Idle agent history: already clear")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_clean(args: argparse.Namespace) -> int:
    client = _build_client()
    daemon_status = client.daemon_status()
    agent_id, source = _resolve_agent_identity_for_project(
        args=None,
        project=client.project,
    )
    identity = _identity_payload(
        project=client.project,
        agent_id=agent_id,
        source=source,
    )

    agents_before = client.store.list_agents(limit=None)
    dead_session_ids = tuple(
        presence.agent_id
        for presence in agents_before
        if terminal_identity_process_is_alive(presence.agent_id) is False
    )

    released_claims: list[str] = []
    released_intents: list[str] = []
    for stale_agent_id in dead_session_ids:
        released_intent = client.release_intent(agent_id=stale_agent_id)
        released_claim = client.release_claim(agent_id=stale_agent_id)
        if released_intent is not None:
            released_intents.append(released_intent.id)
        if released_claim is not None:
            released_claims.append(released_claim.id)

    agents_after_release = client.store.list_agents(limit=None)
    pruned_idle_agents = ()
    if not args.keep_idle:
        idle_agent_ids = tuple(
            presence.agent_id
            for presence in agents_after_release
            if presence.claim is None and presence.intent is None
        )
        pruned_idle_agents = client.store.prune_idle_agents(agent_ids=idle_agent_ids)

    next_steps = ("loom status", "loom agents", "loom start")
    if _emit_json(
        args,
        project=client.project,
        daemon=_daemon_status_payload(daemon_status),
        identity=identity,
        closed_dead_sessions=dead_session_ids,
        released_claim_ids=tuple(released_claims),
        released_intent_ids=tuple(released_intents),
        pruned_idle_agents=tuple(pruned_idle_agents),
        next_steps=next_steps,
    ):
        return 0

    if dead_session_ids or released_claims or released_intents or pruned_idle_agents:
        print("Cleanup complete.")
    else:
        print("Board already clean.")
    print(f"Daemon: {daemon_status.describe()}")
    _print_identity_summary(label="Self", identity=identity)
    print(f"Closed dead pid sessions: {len(dead_session_ids)}")
    if dead_session_ids:
        for stale_agent_id in dead_session_ids:
            print(f"- {stale_agent_id}")
    print(f"Released claims: {len(released_claims)}")
    print(f"Released intents: {len(released_intents)}")
    if args.keep_idle:
        print("Pruned idle agents: skipped (--keep-idle)")
    else:
        print(f"Pruned idle agents: {len(pruned_idle_agents)}")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_status(args: argparse.Namespace) -> int:
    client = _build_client()
    snapshot = client.read_status()
    agents = _coerce_agent_presence_batch(
        client.read_agents(limit=STATUS_AGENT_ACTIVITY_LIMIT)
    )
    daemon_status = client.daemon_status()
    agent_id, source = _resolve_agent_identity_for_project(
        args=None,
        project=client.project,
    )
    identity = _identity_payload(
        project=client.project,
        agent_id=agent_id,
        source=source,
    )
    agent_activity = _agent_activity_payload(agents)
    dead_session_ids = _dead_session_agent_ids(agents)
    stale_agent_ids = _stale_agent_ids(agents)
    repo_lanes = guidance_repo_lanes_payload(
        agents=agents,
        snapshot=snapshot,
        store=client.store,
        stale_agent_ids=stale_agent_ids,
    )
    current_agent_snapshot = client.read_agent_snapshot(
        agent_id=agent_id,
        context_limit=5,
        event_limit=10,
    )
    worktree_signal = _worktree_signal(
        project_root=client.project.repo_root,
        claim=current_agent_snapshot.claim,
        intent=current_agent_snapshot.intent,
    )
    authority = _authority_summary(
        project=client.project,
        changed_paths=tuple(str(path) for path in current_worktree_paths(client.project.repo_root)),
        claims=snapshot.claims,
        intents=snapshot.intents,
    )
    next_steps = _status_next_steps(
        snapshot=snapshot,
        identity=identity,
        dead_session_count=len(dead_session_ids),
        worktree_signal=worktree_signal,
        is_past_timestamp=is_past_utc_timestamp,
    )
    next_action = _status_next_action(
        store=client.store,
        snapshot=snapshot,
        identity=identity,
        dead_session_count=len(dead_session_ids),
        worktree_signal=worktree_signal,
        stale_agent_ids=stale_agent_ids,
        repo_lanes=repo_lanes,
    )
    authority_recovery = _authority_recovery_action(authority, rerun_command="loom status")
    if authority_recovery is not None:
        next_action = authority_recovery
        next_steps = _authority_recovery_steps(authority, rerun_command="loom status")
    elif _should_promote_authority_focus(
        authority,
        next_action=next_action,
        has_active_work=bool(current_agent_snapshot.claim is not None or current_agent_snapshot.intent is not None),
    ):
        next_action = _authority_focus_action(authority)
        next_steps = _authority_focus_steps(authority)

    if _emit_json(
        args,
        project=client.project,
        daemon=_daemon_status_payload(daemon_status),
        identity=identity,
        status=snapshot,
        agent_activity=agent_activity,
        dead_session_agents=dead_session_ids,
        repo_lanes=repo_lanes,
        worktree=worktree_signal,
        authority=authority,
        next_action=next_action,
        next_steps=next_steps,
    ):
        return 0

    print(f"Loom status for {client.project.repo_root}")
    print(f"Daemon: {daemon_status.describe()}")
    _print_identity_summary(label="Self", identity=identity)
    print()

    if agent_activity["stale_active_agents"]:
        print(
            "Stale active records: "
            f"{agent_activity['stale_active_agents']} agent(s) either went quiet for more than "
            f"{ACTIVE_RECORD_STALE_AFTER_HOURS}h or still hold expired active-work leases."
        )
        print("Clean up with `loom finish` or `loom unclaim` when that work is truly done.")
        print()
    if dead_session_ids:
        print(f"Dead pid sessions: {len(dead_session_ids)}")
        print("Run `loom clean` to close dead session work and prune idle history.")
        print()
    if authority.get("status") != "absent":
        _print_authority_summary(authority)
        print()

    if repo_lanes["acknowledged_migration_lanes"]:
        print(
            "Acknowledged migration lanes: "
            f"{repo_lanes['acknowledged_migration_lanes']} total "
            f"({repo_lanes['fresh_acknowledged_migration_lanes']} fresh, "
            f"{repo_lanes['ongoing_acknowledged_migration_lanes']} ongoing)."
        )
        if repo_lanes["acknowledged_migration_programs"]:
            print(
                "Acknowledged migration programs: "
                f"{repo_lanes['acknowledged_migration_programs']} total "
                f"({repo_lanes['fresh_acknowledged_migration_programs']} fresh, "
                f"{repo_lanes['ongoing_acknowledged_migration_programs']} ongoing)."
            )
        top_lane = tuple(repo_lanes.get("lanes", ()))[0] if tuple(repo_lanes.get("lanes", ())) else None
        if isinstance(top_lane, dict):
            print(f"Top lane: {_format_repo_lane_summary(top_lane)}")
            if repo_lanes["acknowledged_migration_lanes"] > 1:
                print(
                    "Other lanes: "
                    f"{repo_lanes['acknowledged_migration_lanes'] - 1} more acknowledged lane(s)."
                )
        top_program = (
            tuple(repo_lanes.get("programs", ()))[0]
            if tuple(repo_lanes.get("programs", ()))
            else None
        )
        if isinstance(top_program, dict):
            print(f"Top program: {_format_repo_program_summary(top_program)}")
        print()

    _print_worktree_signal(
        worktree_signal,
        heading="Working tree",
        current_scope_label="current claim/intent scope",
    )
    if worktree_signal["changed_paths"]:
        print()

    print(f"Active claims ({len(snapshot.claims)}):")
    if snapshot.claims:
        for claim in snapshot.claims:
            print(
                f"- {claim.agent_id}{_self_suffix(claim.agent_id, current_agent_id=agent_id)}"
                f"{_activity_suffix(claim.agent_id, stale_agent_ids=stale_agent_ids)}: "
                f"{claim.description} [{claim.id}]"
            )
            print(f"  scope: {_format_scope_list(claim.scope)}")
            if claim.git_branch:
                print(f"  branch: {claim.git_branch}")
            _print_lease_details(
                claim.lease_expires_at,
                label="  lease until",
                lease_policy=claim.lease_policy,
            )
    else:
        print("- none")

    print()
    print(f"Active intents ({len(snapshot.intents)}):")
    if snapshot.intents:
        for intent in snapshot.intents:
            print(
                f"- {intent.agent_id}{_self_suffix(intent.agent_id, current_agent_id=agent_id)}"
                f"{_activity_suffix(intent.agent_id, stale_agent_ids=stale_agent_ids)}: "
                f"{intent.description} [{intent.id}]"
            )
            print(f"  scope: {_format_scope_list(intent.scope)}")
            if intent.git_branch:
                print(f"  branch: {intent.git_branch}")
            _print_lease_details(
                intent.lease_expires_at,
                label="  lease until",
                lease_policy=intent.lease_policy,
            )
            print(f"  reason: {intent.reason}")
    else:
        print("- none")

    print()
    print(f"Recent context ({len(snapshot.context)}):")
    if snapshot.context:
        for entry in snapshot.context:
            _print_context_entry(entry)
    else:
        print("- none")

    print()
    print(f"Active conflicts ({len(snapshot.conflicts)}):")
    if snapshot.conflicts:
        _print_conflict_details(snapshot.conflicts)
    else:
        print("- none")

    if not snapshot.claims and not snapshot.intents and not snapshot.context and not snapshot.conflicts:
        print()
        print("Nothing is active yet.")
        print("Start here:")
        for step in next_steps:
            print(f"- {step}")
    else:
        print()
        print("Next:")
        for step in next_steps:
            print(f"- {step}")

    return 0


def _handle_report(args: argparse.Namespace) -> int:
    if args.agent_limit <= 0:
        raise ValueError("Report agent limit must be positive.")
    if args.event_limit <= 0:
        raise ValueError("Report event limit must be positive.")

    client = _build_client()
    daemon_status = client.daemon_status()
    snapshot = client.read_status()
    agents = _coerce_agent_presence_batch(client.read_agents(limit=args.agent_limit))
    agent_activity = _agent_activity_payload(agents)
    events = _read_event_batch(
        client=client,
        limit=args.event_limit,
        event_type=None,
        after_sequence=None,
        ascending=False,
    )
    report = build_coordination_report(
        project_root=client.project.repo_root,
        daemon_status=daemon_status,
        status_snapshot=snapshot,
        agents=agents,
        recent_events=events,
    )
    output_path = _resolve_report_output_path(
        project=client.project,
        requested=args.output,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_coordination_report_html(report), encoding="utf-8")
    next_steps = _report_next_steps(
        conflict_count=len(snapshot.conflicts),
        stale_active_count=agent_activity["stale_active_agents"],
    )

    if _emit_json(
        args,
        project=client.project,
        daemon=_daemon_status_payload(daemon_status),
        output_path=str(output_path),
        report=report,
        agent_activity=agent_activity,
        next_steps=next_steps,
    ):
        return 0

    print(f"Loom coordination report written: {output_path}")
    print(f"Project: {client.project.repo_root}")
    print(f"Daemon: {daemon_status.describe()}")
    summary = report["summary"]
    print(
        "Summary: "
        f"{summary['live_active_agents']} live active agent(s), "
        f"{summary['stale_active_agents']} stale active record(s), "
        f"{summary['active_conflicts']} conflict(s), "
        f"{summary['hotspots']} hotspot(s), "
        f"{summary['recent_events']} recent event(s)"
    )
    hotspots = report["hotspots"]
    print(f"Top hotspots ({len(hotspots)}):")
    if hotspots:
        for hotspot in hotspots[:5]:
            print(
                f"- {hotspot['status']} {hotspot['scope']}: "
                f"{len(hotspot['agents'])} agent(s), "
                f"{hotspot['claim_count']} claim, "
                f"{hotspot['intent_count']} intent, "
                f"{hotspot['context_count']} context, "
                f"{hotspot['conflict_count']} conflict"
            )
    else:
        print("- none")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_resume(args: argparse.Namespace) -> int:
    if args.limit <= 0:
        raise ValueError("Resume event limit must be positive.")

    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    identity = _identity_payload(
        project=client.project,
        agent_id=agent_id,
        source=source,
    )
    snapshot = client.read_agent_snapshot(
        agent_id=agent_id,
        context_limit=5,
        event_limit=min(args.limit, 10),
    )
    inbox = client.read_inbox_snapshot(
        agent_id=agent_id,
        context_limit=5,
        event_limit=min(args.limit, 10),
    )
    daemon_status = client.daemon_status()
    worktree_signal = _worktree_signal(
        project_root=client.project.repo_root,
        claim=snapshot.claim,
        intent=snapshot.intent,
    )
    recent_handoff = None
    previous_sequence = int(client.project.resume_sequences.get(agent_id, 0))
    events, latest_relevant_sequence = client.store.agent_event_feed(
        agent_id=agent_id,
        context_limit=5,
        limit=args.limit,
        after_sequence=previous_sequence,
        ascending=True,
    )
    active_work = _active_work_recovery(
        store=client.store,
        agent_id=agent_id,
        claim=snapshot.claim,
        intent=snapshot.intent,
        pending_context=inbox.pending_context,
        conflicts=inbox.conflicts,
        context_limit=5,
        event_limit=args.limit,
    )
    repo_snapshot = client.read_status()
    stale_agent_ids = _stale_agent_ids(
        _coerce_agent_presence_batch(client.read_agents(limit=STATUS_AGENT_ACTIVITY_LIMIT))
    )
    active_work = _active_work_with_repo_yield_alert(
        store=client.store,
        active_work=active_work,
        agent_id=agent_id,
        claim=snapshot.claim,
        intent=snapshot.intent,
        snapshot=repo_snapshot,
        stale_agent_ids=stale_agent_ids,
    )
    if active_work["started_at"] is None:
        recent_handoff = _latest_recent_handoff(
            store=client.store,
            agent_id=agent_id,
        )
    resume_after_sequence = max(previous_sequence, latest_relevant_sequence)
    checkpoint_updated = False
    if not args.no_checkpoint and resume_after_sequence != previous_sequence:
        set_resume_sequence(
            agent_id,
            resume_after_sequence,
            start=client.project.repo_root,
        )
        checkpoint_updated = True

    next_steps = _resume_next_steps(
        pending_context=len(inbox.pending_context),
        conflict_count=len(inbox.conflicts),
        has_claim=snapshot.claim is not None,
        has_intent=snapshot.intent is not None,
        has_priority_attention=bool(
            active_work.get("lease_alert")
            or active_work.get("yield_alert")
            or active_work.get("priority")
        ),
        priority_command=(
            _renew_command()
            if active_work.get("lease_alert") is not None
            else "loom finish"
            if active_work.get("yield_alert") is not None
            else None
            if active_work["priority"] is None
            else str(active_work["priority"]["next_step"])
        ),
        worktree_drift_count=len(tuple(worktree_signal.get("drift_paths", ()))),
        suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ())),
        completion_ready=_active_work_completion_ready(
            active_work=active_work,
            worktree_signal=worktree_signal,
        ),
        recent_handoff=recent_handoff,
    )
    next_action = _resume_next_action(
        snapshot=snapshot,
        active_work=active_work,
        worktree_signal=worktree_signal,
        recent_handoff=recent_handoff,
    )

    if _emit_json(
        args,
        project=client.project,
        daemon=_daemon_status_payload(daemon_status),
        identity=identity,
        agent=snapshot,
        inbox=inbox,
        after_sequence=previous_sequence,
        latest_relevant_sequence=latest_relevant_sequence,
        resume_after_sequence=resume_after_sequence,
        checkpoint_updated=checkpoint_updated,
        events=events,
        active_work=active_work,
        handoff=recent_handoff,
        worktree=worktree_signal,
        next_action=next_action,
        next_steps=next_steps,
    ):
        return 0

    print(f"Loom resume for {agent_id}")
    print(f"Daemon: {daemon_status.describe()}")
    _print_identity_summary(label="Identity", identity=identity)
    print(f"From checkpoint: {previous_sequence}")
    print(f"Latest relevant sequence: {latest_relevant_sequence}")
    if checkpoint_updated:
        print(f"Checkpoint advanced to: {resume_after_sequence}")
    elif args.no_checkpoint:
        print("Checkpoint: unchanged (--no-checkpoint)")
    else:
        print("Checkpoint: unchanged")
    print(
        "Summary: "
        f"{len(events)} relevant event(s), "
        f"{len(inbox.pending_context)} pending context, "
        f"{len(inbox.conflicts)} active conflict(s)"
    )
    print()

    print("Active claim:")
    if snapshot.claim is None:
        print("- none")
    else:
        print(f"- {snapshot.claim.description} [{snapshot.claim.id}]")
        print(f"  scope: {_format_scope_list(snapshot.claim.scope)}")
        if snapshot.claim.git_branch:
            print(f"  branch: {snapshot.claim.git_branch}")
        _print_lease_details(
            snapshot.claim.lease_expires_at,
            label="  lease until",
            lease_policy=snapshot.claim.lease_policy,
        )

    print()
    print("Active intent:")
    if snapshot.intent is None:
        print("- none")
    else:
        print(f"- {snapshot.intent.description} [{snapshot.intent.id}]")
        print(f"  scope: {_format_scope_list(snapshot.intent.scope)}")
        if snapshot.intent.git_branch:
            print(f"  branch: {snapshot.intent.git_branch}")
        _print_lease_details(
            snapshot.intent.lease_expires_at,
            label="  lease until",
            lease_policy=snapshot.intent.lease_policy,
        )
        print(f"  reason: {snapshot.intent.reason}")
        if snapshot.intent.related_claim_id:
            print(f"  related claim: {snapshot.intent.related_claim_id}")

    print()
    _print_worktree_signal(
        worktree_signal,
        heading="Working tree",
        current_scope_label="active claim/intent scope",
        show_next=active_work["started_at"] is None,
    )

    if active_work["started_at"] is not None:
        print()
        _print_active_work_recovery(
            active_work=active_work,
            agent_id=agent_id,
            worktree_signal=worktree_signal,
        )
    elif recent_handoff is not None:
        print()
        _print_recent_handoff(
            recent_handoff,
            handoff_resume_command=_handoff_resume_command,
        )

    print()
    _print_context_entries(inbox.pending_context, heading="Pending context")
    print()
    print(f"Active conflicts ({len(inbox.conflicts)}):")
    if inbox.conflicts:
        _print_conflict_details(inbox.conflicts)
    else:
        print("- none")
    print()
    _print_event_batch(events, heading="Relevant changes since last resume")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_agents(args: argparse.Namespace) -> int:
    if args.limit <= 0:
        raise ValueError("Agent limit must be positive.")

    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=None,
        project=client.project,
    )
    identity = _identity_payload(
        project=client.project,
        agent_id=agent_id,
        source=source,
    )
    agents = _coerce_agent_presence_batch(client.read_agents(limit=args.limit))
    daemon_status = client.daemon_status()
    live_active, stale_active, idle = _partition_agents_by_activity(agents)
    dead_session_ids = _dead_session_agent_ids(agents)
    visible_agents = agents if args.all else tuple((*live_active, *stale_active))
    agent_activity = _agent_activity_payload(agents)
    next_steps = _agents_next_steps(agent_count=len(agents), identity=identity)
    if dead_session_ids:
        next_steps = ("loom clean", *tuple(step for step in next_steps if step != "loom clean"))

    if _emit_json(
        args,
        project=client.project,
        daemon=_daemon_status_payload(daemon_status),
        identity=identity,
        agents=visible_agents,
        agent_activity=agent_activity,
        dead_session_agents=dead_session_ids,
        showing_idle_history=args.all,
        next_steps=next_steps,
    ):
        return 0

    if args.all:
        print(f"Known agents ({len(agents)}):")
    else:
        print(f"Active agents ({len(visible_agents)}):")
    print(f"Daemon: {daemon_status.describe()}")
    _print_identity_summary(label="Self", identity=identity)
    if not visible_agents:
        print()
        print("- none")
        if idle and not args.all:
            print()
            print(f"Idle history hidden ({len(idle)}). Use `loom agents --all` to inspect.")
        print()
        print("Next:")
        for step in next_steps:
            print(f"- {step}")
        return 0

    if live_active:
        print()
        print(f"Live active ({len(live_active)}):")
        for presence in live_active:
            _print_agent_presence(presence, current_agent_id=agent_id)
    if stale_active:
        print()
        print(f"Stale active ({len(stale_active)}):")
        print(
            f"  last seen more than {ACTIVE_RECORD_STALE_AFTER_HOURS}h ago or holding expired leases; "
            "clean up with `loom finish`, `loom renew`, or `loom unclaim` when appropriate."
        )
        for presence in stale_active:
            _print_agent_presence(presence, current_agent_id=agent_id)
    if dead_session_ids:
        print()
        print(f"Dead pid sessions ({len(dead_session_ids)}):")
        print("  run `loom clean` to close dead session work and prune idle history.")
        for stale_agent_id in dead_session_ids:
            print(f"  - {stale_agent_id}")
    if idle and args.all:
        _print_idle_agents(list(idle), current_agent_id=agent_id)
    elif idle and not args.all:
        print()
        print(f"Idle history hidden ({len(idle)}). Use `loom agents --all` to inspect.")
    print()
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_agent(args: argparse.Namespace) -> int:
    if args.context_limit <= 0:
        raise ValueError("Agent context limit must be positive.")
    if args.event_limit <= 0:
        raise ValueError("Agent event limit must be positive.")

    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    identity = _identity_payload(
        project=client.project,
        agent_id=agent_id,
        source=source,
    )
    snapshot = client.read_agent_snapshot(
        agent_id=agent_id,
        context_limit=args.context_limit,
        event_limit=args.event_limit,
    )
    daemon_status = client.daemon_status()
    worktree_signal = _worktree_signal(
        project_root=client.project.repo_root,
        claim=snapshot.claim,
        intent=snapshot.intent,
    )

    pending_context = sum(
        1
        for entry in snapshot.incoming_context
        if _context_ack_status_for_agent(entry, snapshot.agent_id) is None
    )
    pending_context_entries = tuple(
        entry
        for entry in snapshot.incoming_context
        if _context_ack_status_for_agent(entry, snapshot.agent_id) is None
    )
    active_work = _active_work_recovery(
        store=client.store,
        agent_id=snapshot.agent_id,
        claim=snapshot.claim,
        intent=snapshot.intent,
        pending_context=pending_context_entries,
        conflicts=snapshot.conflicts,
        context_limit=args.context_limit,
        event_limit=args.event_limit,
    )
    repo_snapshot = client.read_status()
    stale_agent_ids = _stale_agent_ids(
        _coerce_agent_presence_batch(client.read_agents(limit=STATUS_AGENT_ACTIVITY_LIMIT))
    )
    active_work = _active_work_with_repo_yield_alert(
        store=client.store,
        active_work=active_work,
        agent_id=snapshot.agent_id,
        claim=snapshot.claim,
        intent=snapshot.intent,
        snapshot=repo_snapshot,
        stale_agent_ids=stale_agent_ids,
    )
    attention = guidance_agent_attention_payload(
        pending_context_count=pending_context,
        conflict_count=len(snapshot.conflicts),
        worktree_drift_count=len(worktree_signal["drift_paths"]),
        expired_lease_count=len(tuple(active_work.get("expired_leases", ()))),
    )
    next_steps = _agent_next_steps(
        has_claim=snapshot.claim is not None,
        has_intent=snapshot.intent is not None,
        has_published_context=bool(snapshot.published_context),
        pending_context=pending_context,
        conflict_count=len(snapshot.conflicts),
        has_priority_attention=bool(
            active_work.get("lease_alert")
            or active_work.get("yield_alert")
            or active_work.get("priority")
        ),
        priority_command=(
            _renew_command()
            if active_work.get("lease_alert") is not None
            else "loom finish"
            if active_work.get("yield_alert") is not None
            else None
            if active_work["priority"] is None
            else str(active_work["priority"]["next_step"])
        ),
        worktree_drift_count=len(worktree_signal["drift_paths"]),
        suggested_scope=tuple(str(path) for path in worktree_signal.get("suggested_scope", ())),
        completion_ready=_active_work_completion_ready(
            active_work=active_work,
            worktree_signal=worktree_signal,
        ),
    )
    next_action = _agent_next_action(
        snapshot=snapshot,
        active_work=active_work,
        worktree_signal=worktree_signal,
    )

    if _emit_json(
        args,
        project=client.project,
        daemon=_daemon_status_payload(daemon_status),
        identity=identity,
        agent=snapshot,
        attention=attention,
        active_work=active_work,
        worktree=worktree_signal,
        next_action=next_action,
        next_steps=next_steps,
    ):
        return 0

    print(f"Agent view for {snapshot.agent_id}")
    print(f"Daemon: {daemon_status.describe()}")
    _print_identity_summary(label="Identity", identity=identity)
    print(
        "Attention: "
        + guidance_agent_attention_text(
            pending_context_count=attention["pending_context"],
            conflict_count=attention["active_conflicts"],
            worktree_drift_count=attention["worktree_drift"],
            expired_lease_count=attention["expired_leases"],
        )
    )
    print()

    print("Active claim:")
    if snapshot.claim is None:
        print("- none")
    else:
        print(f"- {snapshot.claim.description} [{snapshot.claim.id}]")
        print(f"  scope: {_format_scope_list(snapshot.claim.scope)}")
        if snapshot.claim.git_branch:
            print(f"  branch: {snapshot.claim.git_branch}")
        _print_lease_details(
            snapshot.claim.lease_expires_at,
            label="  lease until",
            lease_policy=snapshot.claim.lease_policy,
        )

    print()
    print("Active intent:")
    if snapshot.intent is None:
        print("- none")
    else:
        print(f"- {snapshot.intent.description} [{snapshot.intent.id}]")
        print(f"  scope: {_format_scope_list(snapshot.intent.scope)}")
        if snapshot.intent.git_branch:
            print(f"  branch: {snapshot.intent.git_branch}")
        _print_lease_details(
            snapshot.intent.lease_expires_at,
            label="  lease until",
            lease_policy=snapshot.intent.lease_policy,
        )
        print(f"  reason: {snapshot.intent.reason}")
        if snapshot.intent.related_claim_id:
            print(f"  related claim: {snapshot.intent.related_claim_id}")

    if active_work["started_at"] is not None:
        print()
        _print_active_work_recovery(
            active_work=active_work,
            agent_id=snapshot.agent_id,
            worktree_signal=worktree_signal,
        )

    print()
    _print_worktree_signal(
        worktree_signal,
        heading="Working tree",
        current_scope_label="active claim/intent scope",
        show_next=active_work["started_at"] is None,
    )

    print()
    print(f"Published context ({len(snapshot.published_context)}):")
    if snapshot.published_context:
        for entry in snapshot.published_context:
            _print_context_entry(entry)
    else:
        print("- none")

    print()
    print(f"Relevant context ({len(snapshot.incoming_context)}):")
    if snapshot.incoming_context:
        active_scope = _active_scope_for_worktree(
            claim=snapshot.claim,
            intent=snapshot.intent,
        )
        for entry in snapshot.incoming_context:
            _print_context_entry(entry)
            status = _context_ack_status_for_agent(entry, snapshot.agent_id) or "pending"
            print(f"  status for {snapshot.agent_id}: {status}")
            reaction = _active_work_context_reaction(
                entry,
                claim=snapshot.claim,
                intent=snapshot.intent,
                active_scope=active_scope,
            )
            print(f"  reaction for {snapshot.agent_id}: {reaction}")
    else:
        print("- none")

    print()
    print(f"Active conflicts ({len(snapshot.conflicts)}):")
    if snapshot.conflicts:
        _print_conflict_details(snapshot.conflicts)
    else:
        print("- none")

    print()
    _print_event_batch(snapshot.events, heading="Recent activity")
    if next_steps:
        print()
        print("Next:")
        for step in next_steps:
            print(f"- {step}")
    return 0


def _handle_inbox(args: argparse.Namespace) -> int:
    if args.context_limit <= 0:
        raise ValueError("Inbox context limit must be positive.")
    if args.event_limit <= 0:
        raise ValueError("Inbox event limit must be positive.")
    if args.poll_interval <= 0:
        raise ValueError("Inbox poll interval must be positive.")
    if args.max_follow_updates is not None and args.max_follow_updates <= 0:
        raise ValueError("Max follow updates must be positive when provided.")

    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    identity = _identity_payload(
        project=client.project,
        agent_id=agent_id,
        source=source,
    )
    last_sequence = client.store.latest_event_sequence()
    snapshot = client.read_inbox_snapshot(
        agent_id=agent_id,
        context_limit=args.context_limit,
        event_limit=args.event_limit,
    )
    daemon_status = client.daemon_status()
    attention = guidance_inbox_attention_payload(
        pending_context_count=len(snapshot.pending_context),
        conflict_count=len(snapshot.conflicts),
    )
    next_steps = _inbox_next_steps(snapshot)
    next_action = _inbox_next_action(snapshot)

    if args.follow and args.json:
        _write_json_line(
            {
                "ok": True,
                "stream": "inbox",
                "phase": "snapshot",
                "project": client.project,
                "daemon": _daemon_status_payload(daemon_status),
                "identity": identity,
                "inbox": snapshot,
                "attention": attention,
                "next_action": next_action,
                "next_steps": next_steps,
            }
        )
    elif _emit_json(
        args,
        project=client.project,
        daemon=_daemon_status_payload(daemon_status),
        identity=identity,
        inbox=snapshot,
        attention=attention,
        next_action=next_action,
        next_steps=next_steps,
    ):
        return 0
    else:
        _print_inbox_snapshot(
            snapshot,
            daemon_status=daemon_status,
            identity=identity,
            next_steps=next_steps,
            identity_summary_printer=_print_identity_summary,
        )

    if args.follow:
        return _handle_inbox_follow(
            client=client,
            agent_id=snapshot.agent_id,
            context_limit=args.context_limit,
            event_limit=args.event_limit,
            poll_interval=args.poll_interval,
            max_follow_updates=args.max_follow_updates,
            json_mode=args.json,
            initial_snapshot=snapshot,
            after_sequence=last_sequence,
            identity=identity,
            emit_inbox_update=lambda **payload: _emit_inbox_follow_update(
                **payload,
                write_json_line=_write_json_line,
                identity_summary_printer=_print_identity_summary,
            ),
        )

    return 0


def _handle_conflicts(args: argparse.Namespace) -> int:
    client = _build_client()
    conflicts = client.read_conflicts(include_resolved=args.all)
    next_steps = _conflicts_next_steps(conflict_count=len(conflicts))
    next_action = _conflicts_next_action(conflicts)
    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        conflicts=conflicts,
        include_resolved=args.all,
        next_action=next_action,
        next_steps=next_steps,
    ):
        return 0
    heading = "Conflicts" if args.all else "Open conflicts"
    print(f"{heading} ({len(conflicts)}):")
    if conflicts:
        _print_conflict_details(conflicts)
    else:
        print("- none")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_resolve(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, _ = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    conflict = client.resolve_conflict(
        conflict_id=args.conflict_id,
        agent_id=agent_id,
        resolution_note=args.note,
    )
    if conflict is None:
        raise ConflictNotFoundError(args.conflict_id)
    if conflict.is_active:
        raise ValueError(f"Conflict is still active: {args.conflict_id}.")
    next_steps = _resolve_next_steps()

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        conflict=conflict,
        next_steps=next_steps,
    ):
        return 0

    print(f"Conflict resolved: {conflict.id}")
    print(f"Kind: {conflict.kind}")
    print(f"Summary: {conflict.summary}")
    if conflict.resolved_by:
        print(f"Resolved by: {conflict.resolved_by}")
    if conflict.resolved_at:
        print(f"Resolved at: {conflict.resolved_at}")
    if conflict.resolution_note:
        print(f"Note: {conflict.resolution_note}")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_log(args: argparse.Namespace) -> int:
    if args.limit <= 0:
        raise ValueError("Log limit must be positive.")
    if args.poll_interval <= 0:
        raise ValueError("Log poll interval must be positive.")
    if args.max_follow_events is not None and args.max_follow_events <= 0:
        raise ValueError("Max follow events must be positive when provided.")

    client = _build_client()
    if args.follow:
        return _handle_log_follow(
            client=client,
            event_type=args.event_type,
            limit=args.limit,
            poll_interval=args.poll_interval,
            max_follow_events=args.max_follow_events,
            json_mode=args.json,
            write_json_line=_write_json_line,
            daemon_status_payload=_daemon_status_payload,
        )

    events = _read_event_batch(
        client=client,
        limit=args.limit,
        event_type=args.event_type,
        after_sequence=None,
        ascending=False,
    )
    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        events=events,
        next_steps=_log_next_steps(event_count=len(events)),
    ):
        return 0
    _print_event_batch(events, heading="Recent events")
    print("Next:")
    for step in _log_next_steps(event_count=len(events)):
        print(f"- {step}")
    return 0


def _handle_timeline(args: argparse.Namespace) -> int:
    if args.limit <= 0:
        raise ValueError("Timeline limit must be positive.")

    client = _build_client()
    store = client.store

    object_type = _infer_object_type(args.object_id)
    if object_type == "claim":
        target = store.get_claim(args.object_id)
        linked_context = store.list_context_for_claim(args.object_id)
        related_conflicts = store.list_conflicts_for_object(
            object_type="claim",
            object_id=args.object_id,
            include_resolved=True,
        )
    elif object_type == "intent":
        target = store.get_intent(args.object_id)
        linked_context = store.list_context_for_intent(args.object_id)
        related_conflicts = store.list_conflicts_for_object(
            object_type="intent",
            object_id=args.object_id,
            include_resolved=True,
        )
    elif object_type == "context":
        target = store.get_context(args.object_id)
        linked_context = ()
        related_conflicts = store.list_conflicts_for_object(
            object_type="context",
            object_id=args.object_id,
            include_resolved=True,
        )
    elif object_type == "conflict":
        target = store.get_conflict(args.object_id)
        linked_context = ()
        related_conflicts = ()
    else:
        target = None
        linked_context = ()
        related_conflicts = ()

    if target is None:
        raise ObjectNotFoundError(args.object_id)

    related_references = [(object_type, args.object_id)]
    related_references.extend(("conflict", conflict.id) for conflict in related_conflicts)
    related_references.extend(("context", entry.id) for entry in linked_context)
    related_events = tuple(
        reversed(
            store.list_events_for_references(
                references=related_references,
                limit=args.limit,
                ascending=False,
            )
        )
    )
    next_steps = _timeline_next_steps(
        object_type=object_type,
        related_conflict_count=len(related_conflicts),
    )

    if _emit_json(
        args,
        object_type=object_type,
        object_id=args.object_id,
        target=target,
        related_conflicts=related_conflicts,
        linked_context=linked_context,
        events=related_events,
        next_steps=next_steps,
    ):
        return 0

    print(f"Timeline for {object_type} {args.object_id}")
    print()
    _print_timeline_target(object_type=object_type, target=target)

    if related_conflicts:
        print()
        print(f"Related conflicts ({len(related_conflicts)}):")
        _print_conflict_details(related_conflicts)

    if linked_context:
        print()
        print(f"Linked context ({len(linked_context)}):")
        for entry in linked_context:
            _print_context_entry(entry)

    print()
    _print_event_batch(related_events, heading="Events")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_context_write(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, source = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    context, conflicts = client.publish_context(
        agent_id=agent_id,
        topic=args.topic,
        body=args.body,
        scope=args.scope,
        source=source,
    )
    next_steps = _context_write_next_steps(has_conflicts=bool(conflicts))

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        context=context,
        conflicts=conflicts,
        next_steps=next_steps,
    ):
        return 0

    print(f"Context recorded: {context.id}")
    print(f"Agent: {context.agent_id}")
    print(f"Topic: {context.topic}")
    print(f"Body: {_format_body(context.body)}")
    print(f"Scope: {_format_scope_list(context.scope)}")
    if context.git_branch:
        print(f"Branch: {context.git_branch}")
    if context.related_claim_id:
        print(f"Related claim: {context.related_claim_id}")
    if context.related_intent_id:
        print(f"Related intent: {context.related_intent_id}")
    _print_context_dependencies(conflicts)
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_context_ack(args: argparse.Namespace) -> int:
    client = _build_client()
    agent_id, _ = _resolve_agent_identity_for_project(
        args=args.agent,
        project=client.project,
    )
    ack = client.acknowledge_context(
        context_id=args.context_id,
        agent_id=agent_id,
        status=args.status,
        note=args.note,
    )

    if ack is None:
        raise ContextNotFoundError(args.context_id)
    next_steps = _context_ack_next_steps(status=ack.status)

    if _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        acknowledgment=ack,
        next_steps=next_steps,
    ):
        return 0

    print(f"Context acknowledged: {ack.context_id}")
    print(f"Agent: {ack.agent_id}")
    print(f"Status: {ack.status}")
    print(f"Acknowledged at: {ack.acknowledged_at}")
    if ack.note:
        print(f"Note: {ack.note}")
    print("Next:")
    for step in next_steps:
        print(f"- {step}")
    return 0


def _handle_context_read(args: argparse.Namespace) -> int:
    if args.limit <= 0:
        raise ValueError("Context read limit must be positive.")
    if args.poll_interval <= 0:
        raise ValueError("Context read poll interval must be positive.")
    if args.max_follow_entries is not None and args.max_follow_entries <= 0:
        raise ValueError("Max follow entries must be positive when provided.")

    client = _build_client()
    entries = client.read_context_entries(
        topic=args.topic,
        agent_id=args.agent,
        scope=args.scope,
        limit=args.limit,
    )
    next_steps = _context_read_next_steps(entry_count=len(entries))
    if args.follow and args.json:
        _write_json_line(
            {
                "ok": True,
                "stream": "context",
                "phase": "snapshot",
                "daemon": _daemon_status_payload(client.daemon_status()),
                "context": entries,
                "next_steps": next_steps,
            }
        )
    elif _emit_json(
        args,
        daemon=_daemon_status_payload(client.daemon_status()),
        context=entries,
        next_steps=next_steps,
    ):
        return 0
    else:
        _print_context_entries(entries, heading="Context results")
        print("Next:")
        for step in next_steps:
            print(f"- {step}")
    if args.follow:
        return _handle_context_follow(
            client=client,
            topic=args.topic,
            agent_id=args.agent,
            scope=args.scope,
            poll_interval=args.poll_interval,
            max_follow_entries=args.max_follow_entries,
            json_mode=args.json,
            context_matches_filters=_context_matches_filters,
            write_json_line=_write_json_line,
        )
    return 0


def _handle_daemon_run(args: argparse.Namespace) -> int:
    project = load_project()
    run_daemon(project)
    return 0


def _handle_daemon_start(args: argparse.Namespace) -> int:
    project = load_project()
    try:
        result = start_daemon(project)
    except RuntimeError as error:
        raise ValueError(str(error)) from error
    if _emit_json(
        args,
        daemon=_daemon_result_payload(result),
    ):
        return 0
    print(result.detail)
    if result.pid is not None:
        print(f"PID: {result.pid}")
    if result.log_path is not None:
        print(f"Log: {result.log_path}")
    return 0


def _handle_daemon_stop(args: argparse.Namespace) -> int:
    project = load_project()
    result = stop_daemon(project)
    if _emit_json(
        args,
        daemon=_daemon_result_payload(result),
    ):
        return 0
    print(result.detail)
    if result.pid is not None:
        print(f"PID: {result.pid}")
    return 0


def _handle_daemon_status(args: argparse.Namespace) -> int:
    project = load_project()
    status = get_daemon_status(project)
    if _emit_json(
        args,
        daemon=_daemon_status_payload(status),
    ):
        return 0 if status.running else 1
    print(status.describe())
    if status.pid is not None:
        print(f"PID: {status.pid}")
    if status.started_at is not None:
        print(f"Started: {status.started_at}")
    if status.log_path is not None:
        print(f"Log: {status.log_path}")
    return 0 if status.running else 1


def _handle_daemon_ping(args: argparse.Namespace) -> int:
    project = load_project()
    status = get_daemon_status(project)
    protocol: dict[str, object] | None = None
    if status.running:
        try:
            protocol = describe_daemon_protocol(project.socket_path)
        except RuntimeError:
            protocol = None
    if _emit_json(
        args,
        daemon=_daemon_status_payload(status),
        protocol=protocol,
    ):
        return 0 if status.running else 1
    print(status.describe())
    if protocol is not None:
        print(f"Protocol: {protocol['name']} v{protocol['version']}")
    return 0 if status.running else 1


def _handle_protocol(args: argparse.Namespace) -> int:
    protocol = describe_local_protocol()
    if _emit_json(args, protocol=protocol):
        return 0
    operations = ", ".join(str(item) for item in protocol["operations"])
    operation_schemas = protocol.get("operation_schemas", {})
    object_schemas = protocol.get("object_schemas", {})
    print(f"Protocol: {protocol['name']} v{protocol['version']}")
    print(f"Transport: {protocol['transport']}")
    print(f"Encoding: {protocol['encoding']} ({protocol['framing']})")
    print(f"Message limit: {protocol['max_message_bytes']} bytes")
    print(f"Operations ({len(protocol['operations'])}): {operations}")
    print(
        "Schema detail: "
        f"{len(operation_schemas)} operations, {len(object_schemas)} objects"
    )
    return 0


def _handle_mcp(args: argparse.Namespace) -> int:
    del args
    return run_mcp_server()


def _print_active_work_recovery(
    *,
    active_work: dict[str, object],
    agent_id: str,
    worktree_signal: dict[str, object] | None = None,
) -> None:
    _output_print_active_work_recovery(
        active_work=active_work,
        agent_id=agent_id,
        active_work_completion_ready=_active_work_completion_ready,
        renew_command=_renew_command,
        intent_command=_intent_command,
        claim_command=_claim_command,
        worktree_signal=worktree_signal,
    )


def _context_matches_filters(
    entry: ContextRecord,
    *,
    topic: str | None,
    agent_id: str | None,
    scope: tuple[str, ...],
) -> bool:
    if topic and entry.topic != topic:
        return False
    if agent_id and entry.agent_id != agent_id:
        return False
    return _scope_filter_matches(entry.scope, scope)


def _scope_filter_matches(
    record_scope: tuple[str, ...],
    requested_scope: tuple[str, ...],
) -> bool:
    if not requested_scope:
        return True
    if not record_scope:
        return True
    return bool(overlapping_scopes(record_scope, requested_scope))


def _resolve_report_output_path(
    *,
    project: LoomProject,
    requested: Path | None,
) -> Path:
    if requested is not None:
        output_path = requested.expanduser()
        if not output_path.is_absolute():
            return (Path.cwd() / output_path).resolve()
        return output_path.resolve()
    return (project.repo_root / ".loom-reports" / "coordination" / "latest.html").resolve()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "json_global", False):
        args.json = True
    elif not hasattr(args, "json"):
        args.json = False

    if getattr(args, "command", None) is None:
        parser.print_help()
        return 0

    try:
        return args.handler(args)
    except (LoomProjectError, RuntimeError, ValueError) as error:
        next_steps = _error_next_steps(error)
        if getattr(args, "json", False):
            payload: dict[str, object] = {"ok": False, "error": str(error)}
            error_code = recoverable_error_code(error)
            if error_code is not None:
                payload["error_code"] = error_code
            if next_steps:
                payload["next_steps"] = next_steps
            _write_json_line(payload, stream=sys.stderr)
        else:
            print(error, file=sys.stderr)
            if next_steps:
                print("Next:", file=sys.stderr)
                for step in next_steps:
                    print(f"- {step}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
