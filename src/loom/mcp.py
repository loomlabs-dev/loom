from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, TextIO

from . import __version__
from .action_errors import (
    ConflictNotFoundError,
    ContextNotFoundError,
    NoActiveClaimError,
    NoActiveWorkError,
    recoverable_error_code,
)
from .authority import (
    authority_focus_summary as _authority_focus_summary,
    read_authority_summary as _read_authority_summary,
)
from .client import CoordinationClient
from .guidance import (
    DEFAULT_RENEW_LEASE_MINUTES,
    active_work_completion_ready as guidance_active_work_completion_ready,
    active_work_nearby_yield_alert as guidance_active_work_nearby_yield_alert,
    inbox_attention_payload as guidance_inbox_attention_payload,
    active_work_recovery as guidance_active_work_recovery,
    latest_recent_handoff as guidance_latest_recent_handoff,
    repo_lanes_payload as guidance_repo_lanes_payload,
    stale_agent_ids as guidance_stale_agent_ids,
    start_attention_payload as guidance_start_attention_payload,
    start_summary as guidance_start_summary,
    worktree_signal as guidance_worktree_signal,
)
from .identity import (
    current_terminal_identity,
    resolve_agent_identity,
    terminal_identity_process_is_alive,
)
from .mcp_graph import (
    activity_feed_resource_uris_for_structured as _mcp_activity_feed_resource_uris_for_structured,
    agent_ids_for_object_ids as _mcp_agent_ids_for_object_ids,
    agent_resource_uris_for_structured as _mcp_agent_resource_uris_for_structured,
    event_payload as _mcp_event_payload,
    event_payloads as _mcp_event_payloads,
    event_uri as _mcp_event_uri,
    extract_agent_ids as _mcp_extract_agent_ids,
    extract_object_ids as _mcp_extract_object_ids,
    object_relationships as _mcp_object_relationships,
    object_resource_uri_for_object_id as _mcp_object_resource_uri_for_object_id,
    object_resource_uris_for_structured as _mcp_object_resource_uris_for_structured,
    resolve_agent_ids_from_object_ids as _mcp_resolve_agent_ids_from_object_ids,
    timeline_alias_resource_uris_for_structured as _mcp_timeline_alias_resource_uris_for_structured,
    timeline_alias_uri_for_object_id as _mcp_timeline_alias_uri_for_object_id,
    timeline_details as _mcp_timeline_details,
    timeline_object_id_for_alias_uri as _mcp_timeline_object_id_for_alias_uri,
    timeline_payload as _mcp_timeline_payload,
    timeline_resource_uris_for_structured as _mcp_timeline_resource_uris_for_structured,
)
from .mcp_support import (
    json_text as _json_text,
    tool_action_from_recommendation as _tool_action_from_recommendation,
    tool_agent_action as _tool_agent_action,
    tool_agent_next_steps as _tool_agent_next_steps,
    tool_agents_next_steps as _tool_agents_next_steps,
    tool_clean_next_steps as _tool_clean_next_steps,
    tool_claim_step as _tool_claim_step,
    tool_conflicts_action as _tool_conflicts_action,
    tool_conflicts_next_steps as _tool_conflicts_next_steps,
    tool_content as _tool_content,
    tool_context_ack_next_steps as _tool_context_ack_next_steps,
    tool_context_read_next_steps as _tool_context_read_next_steps,
    tool_context_write_next_steps as _tool_context_write_next_steps,
    tool_error_next_steps as _tool_error_next_steps,
    tool_finish_next_steps as _tool_finish_next_steps,
    tool_finish_step as _tool_finish_step,
    tool_inbox_action as _tool_inbox_action,
    tool_inbox_next_steps as _tool_inbox_next_steps,
    tool_intent_step as _tool_intent_step,
    tool_log_next_steps as _tool_log_next_steps,
    tool_onboarding_steps as _tool_onboarding_steps,
    tool_post_write_steps as _tool_post_write_steps,
    tool_priority_action as _tool_priority_action,
    tool_priority_step as _tool_priority_step,
    tool_renew_next_steps as _tool_renew_next_steps,
    tool_renew_step as _tool_renew_step,
    tool_resolve_next_steps as _tool_resolve_next_steps,
    tool_start_action as _tool_start_action,
    tool_start_next_steps as _tool_start_next_steps,
    tool_start_step as _tool_start_step,
    tool_status_action as _tool_status_action,
    tool_status_next_steps as _tool_status_next_steps,
    tool_timeline_next_steps as _tool_timeline_next_steps,
    tool_unclaim_next_steps as _tool_unclaim_next_steps,
    tool_whoami_next_steps as _tool_whoami_next_steps,
)
from .mcp_prompts import PromptExecutionError, build_prompts
from .mcp_links import (
    tool_agent_links as _tool_links_agent,
    tool_agents_links as _tool_links_agents,
    tool_claim_links as _tool_links_claim,
    tool_conflicts_links as _tool_links_conflicts,
    tool_context_ack_links as _tool_links_context_ack,
    tool_context_read_links as _tool_links_context_read,
    tool_context_write_links as _tool_links_context_write,
    tool_inbox_links as _tool_links_inbox,
    tool_intent_links as _tool_links_intent,
    tool_log_links as _tool_links_log,
    tool_resolve_links as _tool_links_resolve,
    tool_status_links as _tool_links_status,
    tool_timeline_links as _tool_links_timeline,
)
from .mcp_readers import (
    read_activity_feed_resource_for as _mcp_read_activity_feed_resource_for,
    read_activity_resource as _mcp_read_activity_resource,
    read_activity_resource_for as _mcp_read_activity_resource_for,
    read_agent_resource as _mcp_read_agent_resource,
    read_agent_resource_for as _mcp_read_agent_resource_for,
    read_agents_resource as _mcp_read_agents_resource,
    read_conflict_history_resource as _mcp_read_conflict_history_resource,
    read_conflicts_resource as _mcp_read_conflicts_resource,
    read_context_feed_resource as _mcp_read_context_feed_resource,
    read_events_after_resource as _mcp_read_events_after_resource,
    read_inbox_resource as _mcp_read_inbox_resource,
    read_inbox_resource_for as _mcp_read_inbox_resource_for,
    read_log_resource as _mcp_read_log_resource,
    read_status_resource as _mcp_read_status_resource,
    read_timeline_resource as _mcp_read_timeline_resource,
    render_claim_resource as _mcp_render_claim_resource,
    render_conflict_resource as _mcp_render_conflict_resource,
    render_context_resource as _mcp_render_context_resource,
    render_event_resource as _mcp_render_event_resource,
    render_intent_resource as _mcp_render_intent_resource,
)
from .mcp_resources import (
    Resource,
    ResourceTemplate,
    activity_feed_target as resource_activity_feed_target,
    build_resource_map,
    build_resource_templates,
    build_resource_uris,
    build_resources,
    dynamic_resource_target as resource_dynamic_resource_target,
)
from .protocol import describe_local_protocol
from .project import (
    LoomProjectError,
    ProjectNotInitializedError,
    initialize_project,
    load_project,
    set_default_agent,
    set_terminal_agent,
)
from .mcp_watch import (
    background_watch_loop as _mcp_background_watch_loop,
    event_feed_subscription_uris as _mcp_event_feed_subscription_uris,
    maybe_start_background_watch as _mcp_maybe_start_background_watch,
    notify_followed_event_updates as _mcp_notify_followed_event_updates,
    notify_resource_updated as _mcp_notify_resource_updated,
    notify_tool_resource_updates as _mcp_notify_tool_resource_updates,
    project_resource_uris as _mcp_project_resource_uris,
    set_watch_diagnostics as _mcp_set_watch_diagnostics,
    stop_background_watch as _mcp_stop_background_watch,
    subscription_snapshot as _mcp_subscription_snapshot,
    watch_snapshot as _mcp_watch_snapshot,
)
from .util import (
    current_worktree_paths,
    infer_object_type,
    is_past_utc_timestamp,
    json_ready as _json_ready,
    LEASE_POLICIES,
    normalize_lease_policy,
)


MCP_PROTOCOL_VERSION = "2025-11-25"
JSONRPC_VERSION = "2.0"
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
RESOURCE_NOT_FOUND = -32002
BACKGROUND_WATCH_DAEMON_RETRY_SECONDS = 0.25
BACKGROUND_WATCH_STREAM_RETRY_SECONDS = 0.1
_WATCH_UNCHANGED = object()
STATUS_AGENT_ACTIVITY_LIMIT = 100
MCP_START_QUICK_LOOP = (
    "start: call loom_start, execute next_action, then loop back if needed",
    "claim: say what you're working on before edits",
    "intent: say what you're about to touch only when the scope gets specific",
    "inbox: react to context or conflicts before continuing",
    "finish: release work cleanly when you're done for now",
)
MCP_START_COMMAND_GUIDE = (
    {
        "tool": "loom_start",
        "summary": "Read the board, then follow Loom's best next move.",
    },
    {
        "tool": "loom_claim",
        "summary": "Reserve the work before edits.",
    },
    {
        "tool": "loom_intent",
        "summary": "Narrow to the exact scope once the edit is specific.",
    },
    {
        "tool": "loom_inbox",
        "summary": "React to context or conflicts before continuing.",
    },
    {
        "tool": "loom_finish",
        "summary": "Release work cleanly when you are done for now.",
    },
)


def _dead_session_agent_ids(agents: tuple[object, ...]) -> tuple[str, ...]:
    return tuple(
        str(getattr(presence, "agent_id"))
        for presence in agents
        if terminal_identity_process_is_alive(str(getattr(presence, "agent_id"))) is False
    )


def _mcp_start_command_guide(
    *,
    include_init: bool,
    include_bind: bool,
    include_cleanup: bool,
) -> tuple[dict[str, str], ...]:
    guide = list(MCP_START_COMMAND_GUIDE)
    if include_init:
        guide.insert(
            1,
            {
                "tool": "loom_init",
                "summary": "Initialize Loom in this repository before coordination begins.",
            },
        )
    if include_bind:
        guide.insert(
            2 if include_init else 1,
            {
                "tool": "loom_bind",
                "summary": (
                    "Bind this MCP session to a stable Loom agent identity."
                    if not include_init
                    else "Bind this MCP session to a stable Loom agent identity after initialization."
                ),
            },
        )
    if include_cleanup:
        guide.append(
            {
                "tool": "loom_clean",
                "summary": "Sweep dead pid sessions off the board and prune idle history.",
            },
        )
    return tuple(guide)


def _start_tool_text(payload: dict[str, object]) -> str:
    summary = str(payload.get("summary", "")).strip()
    next_action = payload.get("next_action")
    if not isinstance(next_action, dict):
        return summary
    tool_name = str(next_action.get("tool", "")).strip()
    if not tool_name:
        return summary
    arguments = next_action.get("arguments")
    arguments_suffix = ""
    if isinstance(arguments, dict) and arguments:
        arguments_suffix = f" {json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
    reason = str(next_action.get("reason", "")).strip()
    text = f"{summary} Next: {tool_name}{arguments_suffix}."
    if reason:
        text += f" Why: {reason}"
    return text


def _authority_summary(
    project: object | None,
    *,
    claims: tuple[object, ...] = (),
    intents: tuple[object, ...] = (),
) -> dict[str, object]:
    if project is None or not hasattr(project, "repo_root"):
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
    repo_root = Path(getattr(project, "repo_root"))
    return _read_authority_summary(
        repo_root,
        changed_paths=tuple(str(path) for path in current_worktree_paths(repo_root)),
        claims=tuple(claims),
        intents=tuple(intents),
    )


class JsonRpcError(RuntimeError):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolExecutionError(RuntimeError):
    def __init__(self, message: str, *, structured: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.structured = structured or {}


class LoomMcpServer:
    def __init__(self, *, cwd: Path | None = None) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self._client: CoordinationClient | None = None
        self._writer: TextIO | None = None
        self._resource_subscriptions: set[str] = set()
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._initialized = False
        self._watch_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._watch_state = "idle"
        self._watch_last_sequence: int | None = None
        self._watch_last_error: str | None = None
        self._tools = {
            "loom_init": _Tool(
                name="loom_init",
                title="Initialize Loom",
                description="Initialize Loom in the current Git repository for local coordination.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "default_agent": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    created={"type": "boolean"},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                    idempotent=True,
                ),
                handler=self._tool_init,
            ),
            "loom_bind": _Tool(
                name="loom_bind",
                title="Bind Agent",
                description="Bind this MCP session to one Loom agent in the current checkout.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                    },
                    "required": ["agent_id"],
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    agent={"type": "object"},
                    project={"type": "object"},
                    binding_adoption={"type": ["object", "null"]},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                    idempotent=True,
                ),
                handler=self._tool_bind,
            ),
            "loom_whoami": _Tool(
                name="loom_whoami",
                title="Resolve Agent",
                description="Resolve the active Loom agent identity for this MCP server and checkout.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    agent={"type": "object"},
                    project={"type": "object"},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_whoami,
            ),
            "loom_start": _Tool(
                name="loom_start",
                title="Read Start Guidance",
                description="Recommend the best next Loom action for this repository and agent.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    project={"type": ["object", "null"]},
                    identity={"type": "object"},
                    daemon={"type": ["object", "null"]},
                    mcp={"type": "object"},
                    mode={"type": "string"},
                    summary={"type": "string"},
                    authority={"type": "object"},
                    dead_session_agents={"type": "array", "items": {"type": "string"}},
                    quick_loop={"type": "array", "items": {"type": "string"}},
                    command_guide={
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "tool": {"type": "string"},
                                "summary": {"type": "string"},
                            },
                            "required": ["tool", "summary"],
                            "additionalProperties": False,
                        },
                    },
                    attention={
                        "type": "object",
                        "properties": {
                            "claims": {"type": "integer"},
                            "intents": {"type": "integer"},
                            "context": {"type": "integer"},
                            "conflicts": {"type": "integer"},
                            "pending_context": {"type": "integer"},
                            "agent_conflicts": {"type": "integer"},
                            "worktree_drift": {"type": "integer"},
                            "acknowledged_migration_lanes": {"type": "integer"},
                        },
                        "required": [
                            "claims",
                            "intents",
                            "context",
                            "conflicts",
                            "pending_context",
                            "agent_conflicts",
                            "worktree_drift",
                            "acknowledged_migration_lanes",
                        ],
                        "additionalProperties": False,
                    },
                    repo_lanes={
                        "type": "object",
                        "properties": {
                            "acknowledged_migration_lanes": {"type": "integer"},
                            "fresh_acknowledged_migration_lanes": {"type": "integer"},
                            "ongoing_acknowledged_migration_lanes": {"type": "integer"},
                            "acknowledged_migration_programs": {"type": "integer"},
                            "fresh_acknowledged_migration_programs": {"type": "integer"},
                            "ongoing_acknowledged_migration_programs": {"type": "integer"},
                            "agents": {"type": "array", "items": {"type": "object"}},
                            "lanes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "scope": {"type": "array", "items": {"type": "string"}},
                                        "relationship": {"type": "string"},
                                        "urgency": {"type": "string"},
                                        "confidence": {"type": "string"},
                                        "participant_count": {"type": "integer"},
                                        "agents": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": [
                                        "scope",
                                        "relationship",
                                        "urgency",
                                        "confidence",
                                        "participant_count",
                                        "agents",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "programs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "scope_hint": {"type": ["string", "null"]},
                                        "urgency": {"type": "string"},
                                        "confidence": {"type": "string"},
                                        "lane_count": {"type": "integer"},
                                        "participant_count": {"type": "integer"},
                                        "relationships": {"type": "array", "items": {"type": "string"}},
                                        "agents": {"type": "array", "items": {"type": "string"}},
                                        "lane_scopes": {
                                            "type": "array",
                                            "items": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                    },
                                    "required": [
                                        "scope_hint",
                                        "urgency",
                                        "confidence",
                                        "lane_count",
                                        "participant_count",
                                        "relationships",
                                        "agents",
                                        "lane_scopes",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "acknowledged_migration_lanes",
                            "fresh_acknowledged_migration_lanes",
                            "ongoing_acknowledged_migration_lanes",
                            "acknowledged_migration_programs",
                            "fresh_acknowledged_migration_programs",
                            "ongoing_acknowledged_migration_programs",
                            "agents",
                            "lanes",
                            "programs",
                        ],
                        "additionalProperties": False,
                    },
                    active_work={"type": ["object", "null"]},
                    worktree={"type": "object"},
                    handoff={"type": ["object", "null"]},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_start,
            ),
            "loom_protocol": _Tool(
                name="loom_protocol",
                title="Describe Protocol",
                description="Describe the local Loom protocol and operation schemas.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    protocol={"type": "object"},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_protocol,
            ),
            "loom_claim": _Tool(
                name="loom_claim",
                title="Claim Work",
                description="Claim a unit of work for one agent.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "description": {"type": "string"},
                        "scope": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                        "lease_minutes": {"type": "integer"},
                        "lease_policy": {"type": "string", "enum": list(LEASE_POLICIES)},
                    },
                    "required": ["description"],
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    claim={"type": "object"},
                    conflicts={"type": "array", "items": {"type": "object"}},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_claim,
            ),
            "loom_unclaim": _Tool(
                name="loom_unclaim",
                title="Release Claim",
                description="Release the active claim for one agent.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    claim={"type": "object"},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_unclaim,
            ),
            "loom_finish": _Tool(
                name="loom_finish",
                title="Finish Work",
                description="Publish an optional handoff note and release current Loom work.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "summary": {"type": "string"},
                        "keep_idle": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    context={"type": ["object", "null"]},
                    context_conflicts={"type": "array", "items": {"type": "object"}},
                    intent={"type": ["object", "null"]},
                    claim={"type": ["object", "null"]},
                    pruned_idle_agents={"type": "array", "items": {"type": "string"}},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_finish,
            ),
            "loom_clean": _Tool(
                name="loom_clean",
                title="Clean Board",
                description="Close dead pid-based session work and prune idle agent history.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "keep_idle": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    closed_dead_sessions={"type": "array", "items": {"type": "string"}},
                    released_claim_ids={"type": "array", "items": {"type": "string"}},
                    released_intent_ids={"type": "array", "items": {"type": "string"}},
                    pruned_idle_agents={"type": "array", "items": {"type": "string"}},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                    idempotent=True,
                ),
                handler=self._tool_clean,
            ),
            "loom_renew": _Tool(
                name="loom_renew",
                title="Renew Lease",
                description="Renew the current coordination lease for one agent's active work.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "lease_minutes": {"type": "integer", "default": DEFAULT_RENEW_LEASE_MINUTES},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    lease_minutes={"type": "integer"},
                    claim={"type": ["object", "null"]},
                    intent={"type": ["object", "null"]},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_renew,
            ),
            "loom_intent": _Tool(
                name="loom_intent",
                title="Declare Intent",
                description="Declare planned impact for one agent.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "description": {"type": "string"},
                        "reason": {"type": "string"},
                        "scope": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "lease_minutes": {"type": "integer"},
                        "lease_policy": {"type": "string", "enum": list(LEASE_POLICIES)},
                    },
                    "required": ["description", "scope"],
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    intent={"type": "object"},
                    conflicts={"type": "array", "items": {"type": "object"}},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_intent,
            ),
            "loom_context_write": _Tool(
                name="loom_context_write",
                title="Publish Context",
                description="Publish shared context for other agents in the repo.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "topic": {"type": "string"},
                        "body": {"type": "string"},
                        "scope": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                    },
                    "required": ["topic", "body"],
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    context={"type": "object"},
                    conflicts={"type": "array", "items": {"type": "object"}},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_context_write,
            ),
            "loom_context_read": _Tool(
                name="loom_context_read",
                title="Read Context",
                description="Read recent shared context notes for the current repository.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "scope": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                        "limit": {"type": "integer", "minimum": 1, "default": 10},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    context={"type": "array", "items": {"type": "object"}},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_context_read,
            ),
            "loom_context_ack": _Tool(
                name="loom_context_ack",
                title="Acknowledge Context",
                description="Mark a shared context note as read or adapted for one agent.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "context_id": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["read", "adapted"],
                            "default": "read",
                        },
                        "note": {"type": "string"},
                    },
                    "required": ["context_id"],
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    acknowledgment={"type": "object"},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_context_ack,
            ),
            "loom_log": _Tool(
                name="loom_log",
                title="Read Event Log",
                description="Read recent coordination events for the current repository.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "default": 20},
                        "event_type": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    events={"type": "array", "items": {"type": "object"}},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_log,
            ),
            "loom_status": _Tool(
                name="loom_status",
                title="Read Status",
                description="Read the active coordination state for the repository.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    status={"type": "object"},
                    authority={"type": "object"},
                    repo_lanes={
                        "type": "object",
                        "properties": {
                            "acknowledged_migration_lanes": {"type": "integer"},
                            "fresh_acknowledged_migration_lanes": {"type": "integer"},
                            "ongoing_acknowledged_migration_lanes": {"type": "integer"},
                            "acknowledged_migration_programs": {"type": "integer"},
                            "fresh_acknowledged_migration_programs": {"type": "integer"},
                            "ongoing_acknowledged_migration_programs": {"type": "integer"},
                            "agents": {"type": "array", "items": {"type": "object"}},
                            "lanes": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "scope": {"type": "array", "items": {"type": "string"}},
                                        "relationship": {"type": "string"},
                                        "urgency": {"type": "string"},
                                        "confidence": {"type": "string"},
                                        "participant_count": {"type": "integer"},
                                        "agents": {"type": "array", "items": {"type": "string"}},
                                    },
                                    "required": [
                                        "scope",
                                        "relationship",
                                        "urgency",
                                        "confidence",
                                        "participant_count",
                                        "agents",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "programs": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "scope_hint": {"type": ["string", "null"]},
                                        "urgency": {"type": "string"},
                                        "confidence": {"type": "string"},
                                        "lane_count": {"type": "integer"},
                                        "participant_count": {"type": "integer"},
                                        "relationships": {"type": "array", "items": {"type": "string"}},
                                        "agents": {"type": "array", "items": {"type": "string"}},
                                        "lane_scopes": {
                                            "type": "array",
                                            "items": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                            },
                                        },
                                    },
                                    "required": [
                                        "scope_hint",
                                        "urgency",
                                        "confidence",
                                        "lane_count",
                                        "participant_count",
                                        "relationships",
                                        "agents",
                                        "lane_scopes",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": [
                            "acknowledged_migration_lanes",
                            "fresh_acknowledged_migration_lanes",
                            "ongoing_acknowledged_migration_lanes",
                            "acknowledged_migration_programs",
                            "fresh_acknowledged_migration_programs",
                            "ongoing_acknowledged_migration_programs",
                            "agents",
                            "lanes",
                            "programs",
                        ],
                        "additionalProperties": False,
                    },
                    dead_session_agents={"type": "array", "items": {"type": "string"}},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_status,
            ),
            "loom_agents": _Tool(
                name="loom_agents",
                title="Read Agents",
                description="Read the Loom agents recently active in this repository.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "minimum": 1, "default": 20},
                        "include_idle": {"type": "boolean", "default": False},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    agents={"type": "array", "items": {"type": "object"}},
                    dead_session_agents={"type": "array", "items": {"type": "string"}},
                    showing_idle_history={"type": "boolean"},
                    idle_history_hidden_count={"type": "integer"},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_agents,
            ),
            "loom_agent": _Tool(
                name="loom_agent",
                title="Read Agent View",
                description="Read the coordination state for one agent, including active work and relevant context.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "context_limit": {"type": "integer", "minimum": 1, "default": 5},
                        "event_limit": {"type": "integer", "minimum": 1, "default": 10},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    agent={"type": "object"},
                    active_work={"type": ["object", "null"]},
                    worktree={"type": "object"},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_agent,
            ),
            "loom_timeline": _Tool(
                name="loom_timeline",
                title="Read Timeline",
                description="Read the coordination timeline for one Loom object.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "object_id": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "default": 20},
                    },
                    "required": ["object_id"],
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    object_type={"type": "string"},
                    object_id={"type": "string"},
                    target={"type": "object"},
                    related_conflicts={"type": "array", "items": {"type": "object"}},
                    linked_context={"type": "array", "items": {"type": "object"}},
                    events={"type": "array", "items": {"type": "object"}},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_timeline,
            ),
            "loom_conflicts": _Tool(
                name="loom_conflicts",
                title="Read Conflicts",
                description="Read active or historical coordination conflicts.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "include_resolved": {
                            "type": "boolean",
                            "default": False,
                        },
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    conflicts={"type": "array", "items": {"type": "object"}},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_conflicts,
            ),
            "loom_resolve": _Tool(
                name="loom_resolve",
                title="Resolve Conflict",
                description="Resolve one coordination conflict with an agent note.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "conflict_id": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "note": {"type": "string"},
                        "resolution_note": {"type": "string"},
                    },
                    "required": ["conflict_id"],
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    conflict={"type": "object"},
                ),
                annotations=_tool_annotations(
                    read_only=False,
                    destructive=False,
                ),
                handler=self._tool_resolve,
            ),
            "loom_inbox": _Tool(
                name="loom_inbox",
                title="Read Inbox",
                description="Read the pending coordination inbox for one agent.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "context_limit": {"type": "integer", "minimum": 1, "default": 5},
                        "event_limit": {"type": "integer", "minimum": 1, "default": 10},
                    },
                    "additionalProperties": False,
                },
                output_schema=_tool_result_schema(
                    daemon={"type": "object"},
                    project={"type": "object"},
                    identity={"type": "object"},
                    mcp={"type": "object"},
                    inbox={"type": "object"},
                ),
                annotations=_tool_annotations(
                    read_only=True,
                ),
                handler=self._tool_inbox,
            ),
        }

        self._prompts = build_prompts()

    def _active_work_with_repo_yield_alert(
        self,
        *,
        client: CoordinationClient | None = None,
        active_work: dict[str, object],
        agent_id: str,
        claim: object | None,
        intent: object | None,
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
            store=None if client is None else client.store,
            stale_agent_ids=stale_agent_ids,
        )
        if nearby_yield_alert is None:
            return active_work
        return {
            **active_work,
            "yield_alert": nearby_yield_alert,
            "needs_attention": True,
        }

    def _dead_session_agent_ids(
        self,
        agents: tuple[object, ...],
    ) -> tuple[str, ...]:
        return _dead_session_agent_ids(agents)

    def _authority_summary(
        self,
        project: object | None,
        *,
        claims: tuple[object, ...] = (),
        intents: tuple[object, ...] = (),
    ) -> dict[str, object]:
        return _authority_summary(project, claims=claims, intents=intents)

    def run(
        self,
        *,
        in_stream: TextIO | None = None,
        out_stream: TextIO | None = None,
    ) -> int:
        reader = in_stream or sys.stdin
        writer = out_stream or sys.stdout
        self._writer = writer
        try:
            while True:
                line = reader.readline()
                if line == "":
                    return 0
                if not line.strip():
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    if not self._write_response_or_detach_writer(
                        writer,
                        self._error_response(None, PARSE_ERROR, "Parse error."),
                    ):
                        return 0
                    continue
                response = self.handle_message(message)
                if response is not None:
                    if not self._write_response_or_detach_writer(writer, response):
                        return 0
        finally:
            with self._write_lock:
                self._writer = None
            self._stop_background_watch()

    def close(self) -> None:
        self._stop_background_watch()
        with self._state_lock:
            client = self._client
            self._client = None
        if client is not None:
            client.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def handle_message(self, message: object) -> dict[str, object] | None:
        if not isinstance(message, dict):
            return self._error_response(None, INVALID_REQUEST, "Invalid Request.")
        if message.get("jsonrpc") != JSONRPC_VERSION:
            return self._error_response(message.get("id"), INVALID_REQUEST, "Invalid Request.")

        method = message.get("method")
        if not isinstance(method, str):
            return self._error_response(message.get("id"), INVALID_REQUEST, "Invalid Request.")

        message_id = message.get("id")
        params = message.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._error_response(message_id, INVALID_PARAMS, "Invalid params.")

        try:
            if method == "initialize":
                return self._success_response(
                    message_id,
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {
                            "tools": {
                                "listChanged": False,
                            },
                            "prompts": {
                                "listChanged": False,
                            },
                            "resources": {
                                "listChanged": True,
                                "subscribe": True,
                            },
                        },
                        "serverInfo": {
                            "name": "loom",
                            "version": __version__,
                        },
                        "instructions": (
                            "Loom coordinates multi-agent work in the current Git repository. "
                            "Use loom_init once per repo, then claim work, declare intent, and "
                            "share or acknowledge context through the provided tools."
                        ),
                    },
                )
            if method == "notifications/initialized":
                with self._state_lock:
                    self._initialized = True
                self._maybe_start_background_watch()
                return None
            if method == "ping":
                return self._success_response(message_id, {})
            if method == "tools/list":
                return self._success_response(
                    message_id,
                    {
                        "tools": [tool.describe() for tool in self._tools.values()],
                    },
                )
            if method == "tools/call":
                return self._handle_tools_call(message_id, params)
            if method == "prompts/list":
                return self._success_response(
                    message_id,
                    {
                        "prompts": [prompt.describe() for prompt in self._prompts.values()],
                    },
                )
            if method == "prompts/get":
                return self._handle_prompts_get(message_id, params)
            if method == "resources/list":
                return self._success_response(
                    message_id,
                    {
                        "resources": [resource.describe() for resource in self._resources()],
                    },
                )
            if method == "resources/templates/list":
                return self._success_response(
                    message_id,
                    {
                        "resourceTemplates": [
                            template.describe() for template in self._resource_templates()
                        ],
                    },
                )
            if method == "resources/read":
                return self._handle_resources_read(message_id, params)
            if method == "resources/subscribe":
                return self._handle_resources_subscribe(message_id, params)
            if method == "resources/unsubscribe":
                return self._handle_resources_unsubscribe(message_id, params)
            return self._error_response(message_id, METHOD_NOT_FOUND, "Method not found.")
        except JsonRpcError as error:
            return self._error_response(message_id, error.code, error.message)
        except Exception as error:
            return self._error_response(message_id, INTERNAL_ERROR, str(error))

    def _handle_tools_call(
        self,
        message_id: object,
        params: dict[str, object],
    ) -> dict[str, object]:
        name = _required_string(params, "name")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "Invalid params.")

        tool = self._tools.get(name)
        if tool is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown tool: {name}.")

        before_resources = self._resource_uris()
        try:
            result = tool.handler(arguments)
        except ToolExecutionError as error:
            root_error = error.__cause__ if error.__cause__ is not None else error
            structured = {"ok": False, "error": str(error), **error.structured}
            if "error_code" not in structured:
                error_code = recoverable_error_code(root_error)
                if error_code is not None:
                    structured["error_code"] = error_code
            if "next_steps" not in structured:
                next_steps = _tool_error_next_steps(root_error)
                if next_steps:
                    structured["next_steps"] = next_steps
            return self._success_response(
                message_id,
                {
                    "content": _tool_content(str(error), structured),
                    "structuredContent": structured,
                    "isError": True,
                },
            )

        if not tool.annotations["readOnlyHint"]:
            self._notify_tool_resource_updates(
                name=name,
                before_resources=before_resources,
                structured=result["structured"],
            )
        self._maybe_start_background_watch()
        structured = {"ok": True, **result["structured"]}
        return self._success_response(
            message_id,
            {
                "content": _tool_content(result["text"], structured),
                "structuredContent": structured,
                "isError": False,
            },
        )

    def _handle_prompts_get(
        self,
        message_id: object,
        params: dict[str, object],
    ) -> dict[str, object]:
        name = _required_string(params, "name")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(INVALID_PARAMS, "Invalid params.")
        prompt = self._prompts.get(name)
        if prompt is None:
            raise JsonRpcError(INVALID_PARAMS, f"Unknown prompt: {name}.")
        try:
            result = prompt.handler(arguments, self._prompt_context())
        except PromptExecutionError as error:
            raise JsonRpcError(INVALID_PARAMS, str(error)) from error
        return self._success_response(
            message_id,
            {
                "description": prompt.description,
                "messages": result["messages"],
            },
        )

    def _prompt_context(self) -> dict[str, object]:
        project = self._maybe_load_project()
        if project is None:
            return {"start": self._start_payload_no_project()}
        client = self._client_for_tools()
        return {"start": self._start_payload_for_client(client, refresh_daemon=True)}

    def _handle_resources_read(
        self,
        message_id: object,
        params: dict[str, object],
    ) -> dict[str, object]:
        uri = _required_string(params, "uri")
        contents = self._read_resource(uri)
        return self._success_response(
            message_id,
            {
                "contents": [contents],
            },
        )

    def _handle_resources_subscribe(
        self,
        message_id: object,
        params: dict[str, object],
    ) -> dict[str, object]:
        uri = _required_string(params, "uri")
        self._ensure_resource_exists(uri)
        with self._state_lock:
            self._resource_subscriptions.add(uri)
        self._maybe_start_background_watch()
        return self._success_response(message_id, {})

    def _handle_resources_unsubscribe(
        self,
        message_id: object,
        params: dict[str, object],
    ) -> dict[str, object]:
        uri = _required_string(params, "uri")
        self._ensure_resource_exists(uri)
        should_stop_watch = False
        with self._state_lock:
            self._resource_subscriptions.discard(uri)
            should_stop_watch = not self._resource_subscriptions
        if should_stop_watch:
            self._stop_background_watch()
        return self._success_response(message_id, {})

    def _tool_init(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("default_agent",))
        default_agent = _optional_string(arguments, "default_agent")
        try:
            project, created = initialize_project(self.cwd)
            if default_agent is not None:
                project = set_default_agent(default_agent, project.repo_root)
        except LoomProjectError as error:
            raise ToolExecutionError(str(error)) from error

        client = CoordinationClient(project)
        client.store.initialize()
        with self._state_lock:
            self._client = client
        next_steps = _tool_onboarding_steps(has_stable_identity=default_agent is not None)
        return {
            "text": (
                f"Initialized Loom in {project.loom_dir}."
                if created
                else f"Loom is already initialized in {project.repo_root}."
            ),
            "structured": {
                "project": project,
                "created": created,
                "daemon": {
                    "requested": False,
                    "detail": "skipped (MCP server mode)",
                },
                "next_steps": next_steps,
            },
        }

    def _tool_whoami(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ())
        project = self._maybe_load_project()
        agent_id, source = resolve_agent_identity(
            None,
            default_agent=None if project is None else project.default_agent,
            terminal_aliases=None if project is None else project.terminal_aliases,
        )
        terminal_identity = current_terminal_identity()
        agent = {
            "id": agent_id,
            "source": source,
            "terminal_identity": terminal_identity,
            "terminal_binding": (
                None
                if project is None
                else project.terminal_aliases.get(terminal_identity)
            ),
            "project_default_agent": None if project is None else project.default_agent,
            "project_initialized": project is not None,
        }
        return {
            "text": f"Resolved Loom agent: {agent_id}.",
            "structured": {
                "agent": agent,
                "project": project,
                "next_steps": _tool_whoami_next_steps(project=project, identity=agent),
            },
        }

    def _tool_bind(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id",))
        bound_agent_id = _required_string(arguments, "agent_id")
        project = self._maybe_load_project()
        if project is None:
            error = ProjectNotInitializedError(
                "Loom is not initialized in this repository. Run `loom init` first."
            )
            raise ToolExecutionError(
                str(error),
                structured={"next_tool": "loom_init"},
            ) from error

        terminal_identity = current_terminal_identity()
        try:
            project = set_terminal_agent(
                bound_agent_id,
                terminal_identity=terminal_identity,
                start=project.repo_root,
            )
        except LoomProjectError as error:
            raise ToolExecutionError(str(error)) from error

        client = CoordinationClient(project)
        adoption = client.store.adopt_agent_work(
            from_agent_id=terminal_identity,
            to_agent_id=bound_agent_id,
            source="terminal",
        )

        with self._state_lock:
            previous_client = self._client
            self._client = client
        if previous_client is not None and previous_client is not client:
            previous_client.close()

        identity = self._identity_payload(client)
        binding_adoption = {
            "terminal_identity": terminal_identity,
            "source_had_work": bool(adoption.get("source_had_work")),
            "target_had_work": bool(adoption.get("target_had_work")),
            "adopted_claim_id": (
                None
                if adoption.get("adopted_claim") is None
                else getattr(adoption["adopted_claim"], "id")
            ),
            "adopted_intent_id": (
                None
                if adoption.get("adopted_intent") is None
                else getattr(adoption["adopted_intent"], "id")
            ),
        }
        text = f"Bound Loom session to agent: {bound_agent_id}."
        if (
            binding_adoption["adopted_claim_id"] is not None
            or binding_adoption["adopted_intent_id"] is not None
        ):
            text += f" Adopted active work from {terminal_identity}."
        return {
            "text": text,
            "structured": self._read_tool_structured(
                client=client,
                agent=identity,
                binding_adoption=binding_adoption,
                next_steps=_tool_whoami_next_steps(project=project, identity=identity),
                links={
                    "start": "loom://start",
                    "status": "loom://status",
                    "agent": f"loom://agent/{identity['id']}",
                },
            ),
        }

    def _tool_start(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ())
        project = self._maybe_load_project()
        if project is None:
            payload = self._start_payload_no_project()
            diagnostics = self._mcp_diagnostics_payload(client=None, refresh_daemon=False)
            return {
                "text": _start_tool_text(payload),
                "structured": {
                    **payload,
                    "mcp": diagnostics["mcp"],
                },
            }

        client = self._client_for_tools()
        payload = self._start_payload_for_client(client, refresh_daemon=False)
        return {
            "text": _start_tool_text(payload),
            "structured": self._read_tool_structured(
                client=client,
                mode=payload["mode"],
                summary=payload["summary"],
                authority=payload["authority"],
                dead_session_agents=payload["dead_session_agents"],
                quick_loop=payload["quick_loop"],
                command_guide=payload["command_guide"],
                attention=payload["attention"],
                next_action=payload["next_action"],
                active_work=payload["active_work"],
                worktree=payload["worktree"],
                handoff=payload["handoff"],
                links=payload["links"],
                next_steps=tuple(payload["next_steps"]),
            ),
        }

    def _tool_protocol(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ())
        protocol = describe_local_protocol()
        return {
            "text": (
                f"Protocol {protocol['name']} v{protocol['version']} with "
                f"{len(protocol['operations'])} operation(s)."
            ),
            "structured": {
                "protocol": protocol,
            },
        }

    def _tool_claim(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id", "description", "scope", "lease_minutes", "lease_policy"))
        client = self._client_for_tools()
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        description = _required_string(arguments, "description")
        scope = _string_list(arguments.get("scope", ()), field="scope")
        lease_minutes = (
            None
            if "lease_minutes" not in arguments
            else _positive_int(arguments.get("lease_minutes"), field="lease_minutes")
        )
        lease_policy = _optional_string(arguments, "lease_policy")
        if lease_policy is not None and lease_minutes is None:
            raise ToolExecutionError("lease_policy requires lease_minutes.")
        try:
            normalized_lease_policy = (
                None
                if lease_policy is None
                else normalize_lease_policy(lease_policy)
            )
        except ValueError as error:
            raise ToolExecutionError(str(error)) from error
        claim, conflicts = client.create_claim(
            agent_id=agent_id,
            description=description,
            scope=scope,
            source="mcp",
            lease_minutes=lease_minutes,
            lease_policy=normalized_lease_policy,
        )
        return {
            "text": f"Claim recorded: {claim.id}",
            "structured": self._read_tool_structured(
                client=client,
                claim=claim,
                conflicts=conflicts,
                links=_tool_links_claim(
                    agent_id=agent_id,
                    claim=claim,
                    conflicts=conflicts,
                ),
                next_steps=_tool_post_write_steps(has_conflicts=bool(conflicts)),
            ),
        }

    def _tool_unclaim(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id",))
        client = self._client_for_tools()
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        claim = client.release_claim(agent_id=agent_id)
        if claim is None:
            error = NoActiveClaimError(agent_id)
            raise ToolExecutionError(str(error)) from error
        return {
            "text": f"Claim released: {claim.id}",
            "structured": self._read_tool_structured(
                client=client,
                claim=claim,
                links=_tool_links_claim(agent_id=agent_id, claim=claim),
                next_steps=_tool_unclaim_next_steps(),
            ),
        }

    def _tool_finish(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id", "summary", "keep_idle"))
        client = self._client_for_tools()
        agent_id, source = self._resolve_agent_id(arguments, client=client)
        summary = _optional_string(arguments, "summary")
        keep_idle = _boolean(arguments.get("keep_idle", False), field="keep_idle")
        snapshot = client.read_agent_snapshot(agent_id=agent_id)
        if snapshot.claim is None and snapshot.intent is None and summary is None:
            error = NoActiveWorkError(
                agent_id,
                detail="Use summary to publish a handoff without active work.",
            )
            raise ToolExecutionError(str(error)) from error

        scope: tuple[str, ...]
        if snapshot.claim is not None and snapshot.intent is not None:
            scope = tuple(dict.fromkeys((*snapshot.claim.scope, *snapshot.intent.scope)))
        elif snapshot.claim is not None:
            scope = tuple(snapshot.claim.scope)
        elif snapshot.intent is not None:
            scope = tuple(snapshot.intent.scope)
        else:
            scope = (".",)

        context = None
        context_conflicts: tuple[object, ...] = ()
        if summary is not None:
            context, context_conflicts = client.publish_context(
                agent_id=agent_id,
                topic="session-handoff",
                body=summary,
                scope=scope,
                source=source,
            )
        released_intent = client.release_intent(agent_id=agent_id)
        released_claim = client.release_claim(agent_id=agent_id)
        pruned_idle_agents: tuple[str, ...] = ()
        if not keep_idle:
            pruned_idle_agents = client.store.prune_idle_agents(agent_ids=(agent_id,))

        links = {
            "start": "loom://start",
            "status": "loom://status",
            "agents": "loom://agents",
            "context": None if context is None else f"loom://context/{context.id}",
            "claim": None if released_claim is None else f"loom://claim/{released_claim.id}",
            "intent": None if released_intent is None else f"loom://intent/{released_intent.id}",
        }
        return {
            "text": f"Finished Loom work for {agent_id}.",
            "structured": self._read_tool_structured(
                client=client,
                context=context,
                context_conflicts=context_conflicts,
                intent=released_intent,
                claim=released_claim,
                pruned_idle_agents=pruned_idle_agents,
                links=links,
                next_steps=_tool_finish_next_steps(wrote_context=context is not None),
            ),
        }

    def _tool_clean(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("keep_idle",))
        client = self._client_for_tools()
        keep_idle = _boolean(arguments.get("keep_idle", False), field="keep_idle")

        agents_before = tuple(client.store.list_agents(limit=None))
        dead_session_ids = _dead_session_agent_ids(agents_before)

        released_claim_ids: list[str] = []
        released_intent_ids: list[str] = []
        for stale_agent_id in dead_session_ids:
            released_intent = client.release_intent(agent_id=stale_agent_id)
            released_claim = client.release_claim(agent_id=stale_agent_id)
            if released_intent is not None:
                released_intent_ids.append(released_intent.id)
            if released_claim is not None:
                released_claim_ids.append(released_claim.id)

        pruned_idle_agents: tuple[str, ...] = ()
        if not keep_idle:
            agents_after_release = tuple(client.store.list_agents(limit=None))
            idle_agent_ids = tuple(
                str(presence.agent_id)
                for presence in agents_after_release
                if presence.claim is None and presence.intent is None
            )
            pruned_idle_agents = client.store.prune_idle_agents(agent_ids=idle_agent_ids)

        text = (
            "Cleanup complete."
            if dead_session_ids or released_claim_ids or released_intent_ids or pruned_idle_agents
            else "Board already clean."
        )
        return {
            "text": text,
            "structured": self._read_tool_structured(
                client=client,
                closed_dead_sessions=dead_session_ids,
                released_claim_ids=tuple(released_claim_ids),
                released_intent_ids=tuple(released_intent_ids),
                pruned_idle_agents=tuple(pruned_idle_agents),
                links={
                    "start": "loom://start",
                    "status": "loom://status",
                    "agents": "loom://agents",
                },
                next_steps=_tool_clean_next_steps(),
            ),
        }

    def _tool_renew(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id", "lease_minutes"))
        client = self._client_for_tools()
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        lease_minutes = (
            DEFAULT_RENEW_LEASE_MINUTES
            if "lease_minutes" not in arguments
            else _positive_int(arguments.get("lease_minutes"), field="lease_minutes")
        )
        claim = client.renew_claim(
            agent_id=agent_id,
            lease_minutes=lease_minutes,
            source="mcp",
        )
        intent = client.renew_intent(
            agent_id=agent_id,
            lease_minutes=lease_minutes,
            source="mcp",
        )
        if claim is None and intent is None:
            error = NoActiveWorkError(agent_id)
            raise ToolExecutionError(str(error)) from error
        return {
            "text": f"Lease renewed for {agent_id}",
            "structured": self._read_tool_structured(
                client=client,
                lease_minutes=lease_minutes,
                claim=claim,
                intent=intent,
                next_steps=_tool_renew_next_steps(),
            ),
        }

    def _tool_intent(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id", "description", "reason", "scope", "lease_minutes", "lease_policy"))
        client = self._client_for_tools()
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        description = _required_string(arguments, "description")
        reason = _optional_string(arguments, "reason") or description
        scope = _string_list(arguments.get("scope"), field="scope")
        if not scope:
            raise ToolExecutionError("Intent scope must not be empty.")
        lease_minutes = (
            None
            if "lease_minutes" not in arguments
            else _positive_int(arguments.get("lease_minutes"), field="lease_minutes")
        )
        lease_policy = _optional_string(arguments, "lease_policy")
        if lease_policy is not None and lease_minutes is None:
            raise ToolExecutionError("lease_policy requires lease_minutes.")
        try:
            normalized_lease_policy = (
                None
                if lease_policy is None
                else normalize_lease_policy(lease_policy)
            )
        except ValueError as error:
            raise ToolExecutionError(str(error)) from error
        intent, conflicts = client.declare_intent(
            agent_id=agent_id,
            description=description,
            reason=reason,
            scope=scope,
            source="mcp",
            lease_minutes=lease_minutes,
            lease_policy=normalized_lease_policy,
        )
        return {
            "text": f"Intent recorded: {intent.id}",
            "structured": self._read_tool_structured(
                client=client,
                intent=intent,
                conflicts=conflicts,
                links=_tool_links_intent(
                    agent_id=agent_id,
                    intent=intent,
                    conflicts=conflicts,
                ),
                next_steps=_tool_post_write_steps(has_conflicts=bool(conflicts)),
            ),
        }

    def _tool_context_write(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id", "topic", "body", "scope"))
        client = self._client_for_tools()
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        topic = _required_string(arguments, "topic")
        body = _required_string(arguments, "body")
        scope = _string_list(arguments.get("scope", ()), field="scope")
        context, conflicts = client.publish_context(
            agent_id=agent_id,
            topic=topic,
            body=body,
            scope=scope,
            source="mcp",
        )
        return {
            "text": f"Context recorded: {context.id}",
            "structured": self._read_tool_structured(
                client=client,
                context=context,
                conflicts=conflicts,
                links=_tool_links_context_write(
                    agent_id=agent_id,
                    context=context,
                    conflicts=conflicts,
                ),
                next_steps=_tool_context_write_next_steps(has_conflicts=bool(conflicts)),
            ),
        }

    def _tool_context_read(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("topic", "agent_id", "scope", "limit"))
        client = self._client_for_tools()
        topic = _optional_string(arguments, "topic")
        agent_id = _optional_string(arguments, "agent_id")
        scope = _string_list(arguments.get("scope", ()), field="scope")
        limit = _positive_int(arguments.get("limit", 10), field="limit")
        context = client.read_context_entries(
            topic=topic,
            agent_id=agent_id,
            scope=scope,
            limit=limit,
        )
        identity = self._identity_payload(client)
        return {
            "text": f"Read {len(context)} context note(s).",
            "structured": self._read_tool_structured(
                client=client,
                context=context,
                links=_tool_links_context_read(
                    agent_id=str(identity["id"]),
                    context=context,
                ),
                next_steps=_tool_context_read_next_steps(entry_count=len(context)),
            ),
        }

    def _tool_context_ack(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("context_id", "agent_id", "status", "note"))
        client = self._client_for_tools()
        context_id = _required_string(arguments, "context_id")
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        status = _optional_string(arguments, "status") or "read"
        note = _optional_string(arguments, "note")
        ack = client.acknowledge_context(
            context_id=context_id,
            agent_id=agent_id,
            status=status,
            note=note,
        )
        if ack is None:
            error = ContextNotFoundError(context_id)
            raise ToolExecutionError(str(error)) from error
        return {
            "text": f"Context acknowledged: {ack.context_id}",
            "structured": self._read_tool_structured(
                client=client,
                acknowledgment=ack,
                links=_tool_links_context_ack(
                    agent_id=agent_id,
                    acknowledgment=ack,
                ),
                next_steps=_tool_context_ack_next_steps(status=ack.status),
            ),
        }

    def _tool_status(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ())
        client = self._client_for_tools()
        snapshot = client.read_status()
        agents = tuple(client.read_agents(limit=STATUS_AGENT_ACTIVITY_LIMIT))
        dead_session_ids = _dead_session_agent_ids(agents)
        authority = _authority_summary(
            client.project,
            claims=snapshot.claims,
            intents=snapshot.intents,
        )
        stale_agent_ids = guidance_stale_agent_ids(agents)
        repo_lanes = guidance_repo_lanes_payload(
            agents=agents,
            snapshot=snapshot,
            store=client.store,
            stale_agent_ids=stale_agent_ids,
        )
        identity = self._identity_payload(client)
        return {
            "text": (
                f"Status read: {len(snapshot.claims)} claim(s), "
                f"{len(snapshot.intents)} intent(s), {len(snapshot.conflicts)} conflict(s)."
            ),
            "structured": self._read_tool_structured(
                client=client,
                status=snapshot,
                authority=authority,
                repo_lanes=repo_lanes,
                next_action=_tool_status_action(
                    client=client,
                    snapshot=snapshot,
                    identity=identity,
                    authority=authority,
                    dead_session_count=len(dead_session_ids),
                    stale_agent_ids=stale_agent_ids,
                    repo_lanes=repo_lanes,
                ),
                dead_session_agents=dead_session_ids,
                links=_tool_links_status(
                    agent_id=str(identity["id"]),
                    snapshot=snapshot,
                ),
                next_steps=_tool_status_next_steps(
                    snapshot=snapshot,
                    identity=identity,
                    authority=authority,
                    dead_session_count=len(dead_session_ids),
                ),
            ),
        }

    def _tool_agents(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("limit", "include_idle"))
        client = self._client_for_tools()
        limit = _positive_int(arguments.get("limit", 20), field="limit")
        include_idle = _boolean(arguments.get("include_idle", False), field="include_idle")
        agents = tuple(client.read_agents(limit=limit))
        dead_session_ids = _dead_session_agent_ids(agents)
        visible_agents = (
            agents
            if include_idle
            else tuple(
                presence
                for presence in agents
                if getattr(presence, "claim", None) is not None
                or getattr(presence, "intent", None) is not None
            )
        )
        idle_history_hidden_count = max(0, len(agents) - len(visible_agents))
        identity = self._identity_payload(client)
        return {
            "text": f"Read {len(visible_agents)} Loom agent(s).",
            "structured": self._read_tool_structured(
                client=client,
                agents=visible_agents,
                dead_session_agents=dead_session_ids,
                showing_idle_history=include_idle,
                idle_history_hidden_count=idle_history_hidden_count,
                links=_tool_links_agents(
                    agent_id=str(identity["id"]),
                    agents=visible_agents,
                ),
                next_steps=_tool_agents_next_steps(
                    agent_count=len(visible_agents),
                    identity=identity,
                    dead_session_count=len(dead_session_ids),
                    idle_history_hidden_count=idle_history_hidden_count,
                ),
            ),
        }

    def _pending_context_for_agent(
        self,
        *,
        agent_id: str,
        entries: tuple[object, ...],
    ) -> tuple[object, ...]:
        return tuple(
            entry
            for entry in entries
            if not any(
                str(getattr(ack, "agent_id", "")) == agent_id
                for ack in tuple(getattr(entry, "acknowledgments", ()))
            )
        )

    def _agent_runtime_payload(
        self,
        *,
        client: CoordinationClient,
        agent_id: str,
        context_limit: int,
        event_limit: int,
    ) -> dict[str, object]:
        status_snapshot = client.read_status()
        stale_agent_ids = guidance_stale_agent_ids(
            tuple(client.read_agents(limit=STATUS_AGENT_ACTIVITY_LIMIT))
        )
        agent = client.read_agent_snapshot(
            agent_id=agent_id,
            context_limit=context_limit,
            event_limit=event_limit,
        )
        worktree = guidance_worktree_signal(
            project_root=client.project.repo_root,
            claim=getattr(agent, "claim", None),
            intent=getattr(agent, "intent", None),
        )
        pending_context = self._pending_context_for_agent(
            agent_id=agent_id,
            entries=tuple(getattr(agent, "incoming_context", ())),
        )
        active_work = guidance_active_work_recovery(
            store=client.store,
            agent_id=agent_id,
            claim=getattr(agent, "claim", None),
            intent=getattr(agent, "intent", None),
            pending_context=pending_context,
            conflicts=tuple(getattr(agent, "conflicts", ())),
            context_limit=context_limit,
            event_limit=event_limit,
        )
        active_work = self._active_work_with_repo_yield_alert(
            client=client,
            active_work=active_work,
            agent_id=agent_id,
            claim=getattr(agent, "claim", None),
            intent=getattr(agent, "intent", None),
            snapshot=status_snapshot,
            stale_agent_ids=stale_agent_ids,
        )
        return {
            "agent": agent,
            "recovery": active_work,
            "worktree": worktree,
            "active_work": None
            if active_work.get("started_at") is None
            else {
                **active_work,
                "completion_ready": guidance_active_work_completion_ready(
                    active_work=active_work,
                    worktree_signal=worktree,
                ),
            },
        }

    def _tool_log(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("limit", "event_type"))
        client = self._client_for_tools()
        limit = _positive_int(arguments.get("limit", 20), field="limit")
        event_type = _optional_string(arguments, "event_type")
        events = client.read_events(
            limit=limit,
            event_type=event_type,
            after_sequence=None,
            ascending=False,
        )
        identity = self._identity_payload(client)
        return {
            "text": f"Read {len(events)} coordination event(s).",
            "structured": self._read_tool_structured(
                client=client,
                events=events,
                links=_tool_links_log(
                    agent_id=str(identity["id"]),
                    events=events,
                ),
                next_steps=_tool_log_next_steps(event_count=len(events)),
            ),
        }

    def _tool_agent(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id", "context_limit", "event_limit"))
        client = self._client_for_tools()
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        context_limit = _positive_int(
            arguments.get("context_limit", 5),
            field="context_limit",
        )
        event_limit = _positive_int(arguments.get("event_limit", 10), field="event_limit")
        payload = self._agent_runtime_payload(
            client=client,
            agent_id=agent_id,
            context_limit=context_limit,
            event_limit=event_limit,
        )
        agent = payload["agent"]
        return {
            "text": (
                f"Agent read for {agent.agent_id}: "
                f"{len(agent.incoming_context)} relevant context note(s), "
                f"{len(agent.conflicts)} conflict(s)."
            ),
            "structured": self._read_tool_structured(
                client=client,
                agent=agent,
                active_work=payload["active_work"],
                worktree=payload["worktree"],
                next_action=_tool_agent_action(
                    agent=agent,
                    active_work=payload["recovery"],
                    worktree_signal=payload["worktree"],
                ),
                links=_tool_links_agent(agent=agent),
                next_steps=_tool_agent_next_steps(
                    agent=agent,
                    active_work=payload["recovery"],
                    worktree_signal=payload["worktree"],
                ),
            ),
        }

    def _tool_timeline(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("object_id", "limit"))
        client = self._client_for_tools()
        object_id = _required_string(arguments, "object_id")
        limit = _positive_int(arguments.get("limit", 20), field="limit")
        timeline = self._timeline_details(client, object_id=object_id, limit=limit)
        identity = self._identity_payload(client)
        return {
            "text": f"Timeline read for {timeline['object_type']} {object_id}.",
            "structured": self._read_tool_structured(
                client=client,
                **timeline,
                links=_tool_links_timeline(
                    agent_id=str(identity["id"]),
                    object_id=object_id,
                    linked_context=tuple(timeline["linked_context"]),
                    related_conflicts=tuple(timeline["related_conflicts"]),
                    object_resource_uri_for_object_id=self._object_resource_uri_for_object_id,
                    timeline_alias_uri_for_object_id=self._timeline_alias_uri_for_object_id,
                ),
                next_steps=_tool_timeline_next_steps(
                    object_type=str(timeline["object_type"]),
                    related_conflict_count=len(tuple(timeline["related_conflicts"])),
                ),
            ),
        }

    def _tool_conflicts(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("include_resolved",))
        client = self._client_for_tools()
        include_resolved = _boolean(
            arguments.get("include_resolved", False),
            field="include_resolved",
        )
        conflicts = client.read_conflicts(include_resolved=include_resolved)
        identity = self._identity_payload(client)
        return {
            "text": f"Read {len(conflicts)} conflict(s).",
            "structured": self._read_tool_structured(
                client=client,
                conflicts=conflicts,
                next_action=_tool_conflicts_action(conflicts=conflicts),
                links=_tool_links_conflicts(
                    agent_id=str(identity["id"]),
                    conflicts=conflicts,
                ),
                next_steps=_tool_conflicts_next_steps(conflict_count=len(conflicts)),
            ),
        }

    def _tool_resolve(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("conflict_id", "agent_id", "note", "resolution_note"))
        client = self._client_for_tools()
        conflict_id = _required_string(arguments, "conflict_id")
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        resolution_note = _optional_string(arguments, "resolution_note")
        if resolution_note is None:
            resolution_note = _optional_string(arguments, "note")
        conflict = client.resolve_conflict(
            conflict_id=conflict_id,
            agent_id=agent_id,
            resolution_note=resolution_note,
        )
        if conflict is None:
            error = ConflictNotFoundError(conflict_id)
            raise ToolExecutionError(str(error)) from error
        if conflict.is_active:
            raise ToolExecutionError(f"Conflict is still active: {conflict_id}.")
        return {
            "text": f"Conflict resolved: {conflict.id}",
            "structured": self._read_tool_structured(
                client=client,
                conflict=conflict,
                links=_tool_links_resolve(
                    agent_id=agent_id,
                    conflict=conflict,
                    object_resource_uri_for_object_id=self._object_resource_uri_for_object_id,
                ),
                next_steps=_tool_resolve_next_steps(),
            ),
        }

    def _tool_inbox(self, arguments: dict[str, object]) -> dict[str, object]:
        _reject_extra_arguments(arguments, ("agent_id", "context_limit", "event_limit"))
        client = self._client_for_tools()
        agent_id, _ = self._resolve_agent_id(arguments, client=client)
        context_limit = _positive_int(
            arguments.get("context_limit", 5),
            field="context_limit",
        )
        event_limit = _positive_int(arguments.get("event_limit", 10), field="event_limit")
        inbox = client.read_inbox_snapshot(
            agent_id=agent_id,
            context_limit=context_limit,
            event_limit=event_limit,
        )
        attention = guidance_inbox_attention_payload(
            pending_context_count=len(inbox.pending_context),
            conflict_count=len(inbox.conflicts),
        )
        return {
            "text": (
                f"Inbox read for {inbox.agent_id}: "
                f"{attention['pending_context']} pending context note(s), "
                f"{attention['active_conflicts']} conflict(s)."
            ),
            "structured": self._read_tool_structured(
                client=client,
                inbox=inbox,
                next_action=_tool_inbox_action(inbox=inbox),
                links=_tool_links_inbox(inbox=inbox),
                next_steps=_tool_inbox_next_steps(inbox=inbox),
            ),
        }

    def _client_for_tools(self) -> CoordinationClient:
        with self._state_lock:
            if self._client is not None:
                return self._client
            project = self._maybe_load_project()
            if project is None:
                error = ProjectNotInitializedError(
                    "Loom is not initialized in this repository. Run `loom init` first."
                )
                raise ToolExecutionError(
                    str(error),
                    structured={"next_tool": "loom_init"},
                ) from error
            self._client = CoordinationClient(project)
            return self._client

    def _maybe_load_project(self):
        try:
            return load_project(self.cwd)
        except LoomProjectError:
            return None

    def _resolve_agent_id(
        self,
        arguments: dict[str, object],
        *,
        client: CoordinationClient,
        field: str = "agent_id",
    ) -> tuple[str, str]:
        explicit = _optional_string(arguments, field)
        return resolve_agent_identity(
            explicit,
            default_agent=client.project.default_agent,
            terminal_aliases=client.project.terminal_aliases,
        )

    def _identity_payload(self, client: CoordinationClient) -> dict[str, object]:
        agent_id, source = resolve_agent_identity(
            None,
            default_agent=client.project.default_agent,
            terminal_aliases=client.project.terminal_aliases,
        )
        terminal_identity = current_terminal_identity()
        return {
            "id": agent_id,
            "source": source,
            "terminal_identity": terminal_identity,
            "terminal_binding": client.project.terminal_aliases.get(terminal_identity),
            "project_default_agent": client.project.default_agent,
            "project_initialized": True,
        }

    def _start_payload_no_project(self) -> dict[str, object]:
        agent_id, source = resolve_agent_identity(None)
        terminal_identity = current_terminal_identity()
        identity = {
            "id": agent_id,
            "source": source,
            "terminal_identity": terminal_identity,
            "terminal_binding": None,
            "project_default_agent": None,
            "project_initialized": False,
        }
        mode, summary = guidance_start_summary(
            project_initialized=False,
            identity=identity,
        )
        return {
            "project": None,
            "identity": identity,
            "daemon": None,
            "mode": mode,
            "summary": summary,
            "authority": _authority_summary(None),
            "dead_session_agents": (),
            "quick_loop": MCP_START_QUICK_LOOP,
            "command_guide": _mcp_start_command_guide(
                include_init=True,
                include_bind=False,
                include_cleanup=False,
            ),
            "attention": guidance_start_attention_payload(),
            "repo_lanes": {
                "acknowledged_migration_lanes": 0,
                "fresh_acknowledged_migration_lanes": 0,
                "ongoing_acknowledged_migration_lanes": 0,
                "acknowledged_migration_programs": 0,
                "fresh_acknowledged_migration_programs": 0,
                "ongoing_acknowledged_migration_programs": 0,
                "agents": (),
                "lanes": (),
                "programs": (),
            },
            "next_action": _tool_start_action(
                project=None,
                identity=identity,
                authority=_authority_summary(None),
            ),
            "active_work": None,
            "worktree": {
                "changed_paths": (),
                "in_scope_paths": (),
                "drift_paths": (),
                "active_scope": (),
                "suggested_scope": (),
                "has_active_scope": False,
                "has_drift": False,
            },
            "handoff": None,
            "next_steps": _tool_start_next_steps(
                project=None,
                identity=identity,
                authority=_authority_summary(None),
            ),
            "links": {
                "identity": "loom://identity",
                "mcp": "loom://mcp",
                "protocol": "loom://protocol",
            },
        }

    def _start_payload_for_client(
        self,
        client: CoordinationClient,
        *,
        refresh_daemon: bool,
    ) -> dict[str, object]:
        identity = self._identity_payload(client)
        snapshot = client.read_status()
        agents = tuple(client.read_agents(limit=STATUS_AGENT_ACTIVITY_LIMIT))
        dead_session_ids = _dead_session_agent_ids(agents)
        authority = _authority_summary(
            client.project,
            claims=snapshot.claims,
            intents=snapshot.intents,
        )
        stale_agent_ids = guidance_stale_agent_ids(agents)
        repo_lanes = guidance_repo_lanes_payload(
            agents=agents,
            snapshot=snapshot,
            store=client.store,
            stale_agent_ids=stale_agent_ids,
        )
        agent_snapshot = None
        inbox_snapshot = None
        active_work = None
        worktree_signal = {
            "changed_paths": (),
            "in_scope_paths": (),
            "drift_paths": (),
            "active_scope": (),
            "suggested_scope": (),
            "has_active_scope": False,
            "has_drift": False,
        }
        recent_handoff = None
        if identity["source"] != "tty":
            agent_snapshot = client.read_agent_snapshot(
                agent_id=str(identity["id"]),
                context_limit=5,
                event_limit=10,
            )
            inbox_snapshot = client.read_inbox_snapshot(
                agent_id=str(identity["id"]),
                context_limit=5,
                event_limit=10,
            )
            worktree_signal = guidance_worktree_signal(
                project_root=client.project.repo_root,
                claim=getattr(agent_snapshot, "claim", None),
                intent=getattr(agent_snapshot, "intent", None),
            )
            active_work = guidance_active_work_recovery(
                store=client.store,
                agent_id=str(identity["id"]),
                claim=getattr(agent_snapshot, "claim", None),
                intent=getattr(agent_snapshot, "intent", None),
                pending_context=tuple(getattr(inbox_snapshot, "pending_context", ())),
                conflicts=tuple(getattr(inbox_snapshot, "conflicts", ())),
                context_limit=5,
                event_limit=10,
            )
            active_work = self._active_work_with_repo_yield_alert(
                client=client,
                active_work=active_work,
                agent_id=str(identity["id"]),
                claim=getattr(agent_snapshot, "claim", None),
                intent=getattr(agent_snapshot, "intent", None),
                snapshot=snapshot,
                stale_agent_ids=stale_agent_ids,
            )
            if (
                getattr(agent_snapshot, "claim", None) is None
                and getattr(agent_snapshot, "intent", None) is None
            ):
                recent_handoff = guidance_latest_recent_handoff(
                    store=client.store,
                    agent_id=str(identity["id"]),
                )
        mode, summary = guidance_start_summary(
            project_initialized=True,
            identity=identity,
            snapshot=snapshot,
            agent_snapshot=agent_snapshot,
            inbox_snapshot=inbox_snapshot,
            active_work=active_work,
            repo_lanes=repo_lanes,
            worktree_signal=worktree_signal,
            recent_handoff=recent_handoff,
        )
        next_action = _tool_start_action(
            project=client.project,
            identity=identity,
            authority=authority,
            dead_session_count=len(dead_session_ids),
            snapshot=snapshot,
            agent_snapshot=agent_snapshot,
            inbox_snapshot=inbox_snapshot,
            active_work=active_work,
            repo_lanes=repo_lanes,
            worktree_signal=worktree_signal,
            recent_handoff=recent_handoff,
        )
        if (
            isinstance(next_action, dict)
            and str(authority.get("status", "")) == "invalid"
        ):
            mode = "attention"
            summary = "Declared authority is invalid in loom.yaml; claim and fix it before other coordination."
        elif (
            isinstance(next_action, dict)
            and str(authority.get("status", "")) == "valid"
            and bool(authority.get("changed_surfaces"))
            and str(next_action.get("tool", "")) == "loom_claim"
        ):
            summary = _authority_focus_summary(authority) or "Authority changed; coordinate the affected truth surfaces before other work."
            mode = "attention"
        return {
            "project": client.project,
            "identity": identity,
            "daemon": client.daemon_status(refresh=refresh_daemon),
            "mode": mode,
            "summary": summary,
            "authority": authority,
            "dead_session_agents": dead_session_ids,
            "quick_loop": MCP_START_QUICK_LOOP,
            "command_guide": _mcp_start_command_guide(
                include_init=False,
                include_bind=identity["source"] == "tty",
                include_cleanup=bool(dead_session_ids),
            ),
            "attention": guidance_start_attention_payload(
                snapshot=snapshot,
                inbox_snapshot=inbox_snapshot,
                worktree_signal=worktree_signal,
                repo_lanes=repo_lanes,
            ),
            "repo_lanes": repo_lanes,
            "next_action": next_action,
            "active_work": None
            if active_work is None or active_work.get("started_at") is None
            else {
                **active_work,
                "completion_ready": guidance_active_work_completion_ready(
                    active_work=active_work,
                    worktree_signal=worktree_signal,
                ),
            },
            "worktree": worktree_signal,
            "handoff": recent_handoff,
            "next_steps": _tool_start_next_steps(
                project=client.project,
                identity=identity,
                authority=authority,
                dead_session_count=len(dead_session_ids),
                snapshot=snapshot,
                agent_snapshot=agent_snapshot,
                inbox_snapshot=inbox_snapshot,
                active_work=active_work,
                worktree_signal=worktree_signal,
                recent_handoff=recent_handoff,
            ),
            "links": {
                "identity": "loom://identity",
                "mcp": "loom://mcp",
                "status": "loom://status",
                "agent": f"loom://agent/{identity['id']}",
                "inbox": f"loom://inbox/{identity['id']}",
                "context": "loom://context",
                "conflicts": "loom://conflicts",
            },
        }

    def _resource_map(self) -> dict[str, Resource]:
        return build_resource_map(self._resources())

    def _resource_uris(self) -> tuple[str, ...]:
        return build_resource_uris(self._resources())

    def _resource_templates(self) -> tuple[ResourceTemplate, ...]:
        return build_resource_templates()

    def _read_resource(self, uri: str) -> dict[str, object]:
        resource = self._resource_map().get(uri)
        if resource is not None:
            return resource.read()
        activity_feed_target = self._activity_feed_target(uri)
        if activity_feed_target is not None:
            agent_id, after_sequence = activity_feed_target
            return self._read_activity_feed_resource_for(
                uri=uri,
                agent_id=agent_id,
                after_sequence=after_sequence,
            )
        target = self._dynamic_resource_target(uri)
        if target is not None:
            target_type, identifier = target
            if target_type == "timeline":
                return self._read_timeline_resource(uri=uri, object_id=identifier)
            if target_type == "claim":
                return self._read_claim_resource(uri=uri, claim_id=identifier)
            if target_type == "intent":
                return self._read_intent_resource(uri=uri, intent_id=identifier)
            if target_type == "agent":
                return self._read_agent_resource_for(uri=uri, agent_id=identifier)
            if target_type == "inbox":
                return self._read_inbox_resource_for(uri=uri, agent_id=identifier)
            if target_type == "activity":
                return self._read_activity_resource_for(uri=uri, agent_id=identifier)
            if target_type == "conflict":
                return self._read_conflict_resource(uri=uri, conflict_id=identifier)
            if target_type == "context":
                return self._read_context_resource(uri=uri, context_id=identifier)
            if target_type == "event":
                return self._read_event_resource(uri=uri, sequence=self._event_sequence(identifier))
            if target_type == "event_feed":
                return self._read_events_after_resource(
                    uri=uri,
                    after_sequence=self._after_sequence(identifier),
                )
        raise JsonRpcError(RESOURCE_NOT_FOUND, f"Resource not found: {uri}.")

    def _ensure_resource_exists(self, uri: str) -> None:
        if uri in self._resource_map():
            return

        activity_feed_target = self._activity_feed_target(uri)
        if activity_feed_target is not None:
            agent_id, _ = activity_feed_target
            if agent_id:
                return

        target = self._dynamic_resource_target(uri)
        if target is not None:
            target_type, identifier = target
            if target_type in {"claim", "intent", "conflict", "context", "timeline"}:
                self._ensure_object_exists(identifier)
                return
            if target_type == "event":
                self._ensure_event_exists(self._event_sequence(identifier))
                return
            if target_type == "event_feed":
                self._after_sequence(identifier)
                return
            if target_type in {"agent", "inbox", "activity"}:
                return

        raise JsonRpcError(RESOURCE_NOT_FOUND, f"Resource not found: {uri}.")

    def _dynamic_resource_target(self, uri: str) -> tuple[str, str] | None:
        return resource_dynamic_resource_target(
            uri,
            timeline_object_id_for_alias_uri=self._timeline_object_id_for_alias_uri,
        )

    def _activity_feed_target(self, uri: str) -> tuple[str, int] | None:
        return resource_activity_feed_target(uri, after_sequence=self._after_sequence)

    def _ensure_object_exists(self, object_id: str) -> None:
        client = self._maybe_client_for_project_resources()
        if client is None:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Resource not found: {object_id}.")

        store = client.store
        try:
            object_type = infer_object_type(object_id)
        except ValueError as error:
            raise JsonRpcError(RESOURCE_NOT_FOUND, str(error)) from error
        if object_type == "claim" and store.get_claim(object_id) is not None:
            return
        if object_type == "intent" and store.get_intent(object_id) is not None:
            return
        if object_type == "context" and store.get_context(object_id) is not None:
            return
        if object_type == "conflict" and store.get_conflict(object_id) is not None:
            return
        raise JsonRpcError(RESOURCE_NOT_FOUND, f"Resource not found: {object_id}.")

    def _ensure_event_exists(self, sequence: int) -> None:
        client = self._maybe_client_for_project_resources()
        if client is None or client.store.get_event(sequence) is None:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Resource not found: event {sequence}.")

    def _event_sequence(self, identifier: str) -> int:
        try:
            sequence = int(identifier)
        except ValueError as error:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Resource not found: event {identifier}.") from error
        if sequence <= 0:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Resource not found: event {identifier}.")
        return sequence

    def _after_sequence(self, identifier: str) -> int:
        try:
            sequence = int(identifier)
        except ValueError as error:
            raise JsonRpcError(
                RESOURCE_NOT_FOUND,
                f"Resource not found: events after {identifier}.",
            ) from error
        if sequence < 0:
            raise JsonRpcError(
                RESOURCE_NOT_FOUND,
                f"Resource not found: events after {identifier}.",
            )
        return sequence

    def _maybe_client_for_project_resources(self) -> CoordinationClient | None:
        with self._state_lock:
            if self._client is not None:
                return self._client
            project = self._maybe_load_project()
            if project is None:
                return None
            self._client = CoordinationClient(project)
            return self._client

    def _subscription_snapshot(self) -> tuple[str, ...]:
        return _mcp_subscription_snapshot(self)

    def _watch_snapshot(self) -> dict[str, object]:
        return _mcp_watch_snapshot(self)

    def _set_watch_diagnostics(
        self,
        *,
        state: str | None = None,
        last_sequence: int | object = _WATCH_UNCHANGED,
        last_error: str | None | object = _WATCH_UNCHANGED,
        notify: bool = True,
    ) -> None:
        _mcp_set_watch_diagnostics(
            self,
            state=state,
            last_sequence=last_sequence,
            last_error=last_error,
            unchanged_sentinel=_WATCH_UNCHANGED,
            notify=notify,
        )

    def _maybe_start_background_watch(self) -> None:
        _mcp_maybe_start_background_watch(
            self,
            daemon_retry_seconds=BACKGROUND_WATCH_DAEMON_RETRY_SECONDS,
            stream_retry_seconds=BACKGROUND_WATCH_STREAM_RETRY_SECONDS,
        )

    def _stop_background_watch(self) -> None:
        _mcp_stop_background_watch(self)

    def _background_watch_loop(self, stop_event: threading.Event, after_sequence: int) -> None:
        _mcp_background_watch_loop(
            self,
            stop_event,
            after_sequence,
            daemon_retry_seconds=BACKGROUND_WATCH_DAEMON_RETRY_SECONDS,
            stream_retry_seconds=BACKGROUND_WATCH_STREAM_RETRY_SECONDS,
        )

    def _notify_followed_event_updates(self, event: object) -> None:
        _mcp_notify_followed_event_updates(self, event)

    def _notify_tool_resource_updates(
        self,
        *,
        name: str,
        before_resources: tuple[str, ...],
        structured: dict[str, object],
    ) -> None:
        _mcp_notify_tool_resource_updates(
            self,
            name=name,
            before_resources=before_resources,
            structured=structured,
        )

    def _project_resource_uris(self, *, include_identity: bool) -> tuple[str, ...]:
        return _mcp_project_resource_uris(self, include_identity=include_identity)

    def _notify_resource_updated(self, uri: str) -> None:
        _mcp_notify_resource_updated(self, uri)

    def _event_feed_subscription_uris(self) -> tuple[str, ...]:
        return _mcp_event_feed_subscription_uris(self)

    def _activity_feed_resource_uris_for_structured(self, value: object) -> tuple[str, ...]:
        return _mcp_activity_feed_resource_uris_for_structured(self, value)

    def _agent_resource_uris_for_structured(self, value: object) -> tuple[str, ...]:
        return _mcp_agent_resource_uris_for_structured(self, value)

    def _agent_ids_for_object_ids(self, object_ids: set[str]) -> set[str]:
        return _mcp_agent_ids_for_object_ids(self, object_ids)

    def _resolve_agent_ids_from_object_ids(
        self,
        store,
        *,
        object_ids: set[str],
        visited: set[str],
    ) -> set[str]:
        return _mcp_resolve_agent_ids_from_object_ids(
            store,
            object_ids=object_ids,
            visited=visited,
        )

    def _timeline_resource_uris_for_structured(
        self,
        value: object,
    ) -> tuple[str, ...]:
        return _mcp_timeline_resource_uris_for_structured(value)

    def _timeline_alias_resource_uris_for_structured(
        self,
        value: object,
    ) -> tuple[str, ...]:
        return _mcp_timeline_alias_resource_uris_for_structured(value)

    def _object_resource_uris_for_structured(self, value: object) -> tuple[str, ...]:
        return _mcp_object_resource_uris_for_structured(value)

    def _extract_object_ids(self, value: object) -> set[str]:
        return _mcp_extract_object_ids(value)

    def _timeline_alias_uri_for_object_id(self, object_id: str) -> str | None:
        return _mcp_timeline_alias_uri_for_object_id(object_id)

    def _timeline_object_id_for_alias_uri(self, uri: str) -> str | None:
        return _mcp_timeline_object_id_for_alias_uri(uri)

    def _object_resource_uri_for_object_id(self, object_id: str) -> str | None:
        return _mcp_object_resource_uri_for_object_id(object_id)

    def _extract_agent_ids(self, value: object, *, field_name: str | None = None) -> set[str]:
        return _mcp_extract_agent_ids(value, field_name=field_name)

    def _resources(self) -> tuple[Resource, ...]:
        return build_resources(
            project_available=self._maybe_load_project() is not None,
            read_protocol=self._read_protocol_resource,
            read_start=self._read_start_resource,
            read_identity=self._read_identity_resource,
            read_mcp=self._read_mcp_resource,
            read_activity=self._read_activity_resource,
            read_log=self._read_log_resource,
            read_context_feed=self._read_context_feed_resource,
            read_status=self._read_status_resource,
            read_agents=self._read_agents_resource,
            read_conflicts=self._read_conflicts_resource,
            read_conflict_history=self._read_conflict_history_resource,
            read_agent=self._read_agent_resource,
            read_inbox=self._read_inbox_resource,
        )

    def _read_protocol_resource(self) -> dict[str, object]:
        return {
            "uri": "loom://protocol",
            "mimeType": "application/json",
            "text": _json_text({"protocol": describe_local_protocol()}),
        }

    def _read_identity_resource(self) -> dict[str, object]:
        project = self._maybe_load_project()
        if project is None:
            agent_id, source = resolve_agent_identity(None)
            terminal_identity = current_terminal_identity()
            identity = {
                "id": agent_id,
                "source": source,
                "terminal_identity": terminal_identity,
                "terminal_binding": None,
                "project_default_agent": None,
                "project_initialized": False,
            }
        else:
            client = self._client_for_tools()
            identity = self._identity_payload(client)
        return {
            "uri": "loom://identity",
            "mimeType": "application/json",
            "text": _json_text(
                {
                    "identity": identity,
                    "links": {
                        "start": "loom://start",
                        "protocol": "loom://protocol",
                        "mcp": "loom://mcp",
                        "status": None if project is None else "loom://status",
                    },
                }
            ),
        }

    def _read_start_resource(self) -> dict[str, object]:
        project = self._maybe_load_project()
        if project is None:
            payload = self._start_payload_no_project()
        else:
            client = self._client_for_tools()
            payload = self._start_payload_for_client(client, refresh_daemon=True)
        return {
            "uri": "loom://start",
            "mimeType": "application/json",
            "text": _json_text(payload),
        }

    def _read_mcp_resource(self) -> dict[str, object]:
        client = self._maybe_client_for_project_resources()
        diagnostics = self._mcp_diagnostics_payload(client=client, refresh_daemon=True)
        project = diagnostics["project"]
        identity = diagnostics["identity"]
        daemon_status = diagnostics["daemon"]
        subscriptions = tuple(sorted(self._subscription_snapshot()))
        return {
            "uri": "loom://mcp",
            "mimeType": "application/json",
            "text": _json_text(
                {
                    "mcp": {
                        "cwd": self.cwd,
                        "protocol_version": MCP_PROTOCOL_VERSION,
                        "server_version": __version__,
                        "initialized": self._initialized,
                        "writer_attached": self._writer is not None,
                        "subscription_count": len(subscriptions),
                        "subscriptions": subscriptions,
                        "watcher": self._watch_snapshot(),
                    },
                    "project": project,
                    "identity": identity,
                    "links": {
                        "protocol": "loom://protocol",
                        "start": "loom://start",
                        "identity": "loom://identity",
                        "status": None if project is None else "loom://status",
                        "context": None if project is None else "loom://context",
                        "current_agent": None if project is None else f"loom://agent/{identity['id']}",
                        "current_inbox": None if project is None else f"loom://inbox/{identity['id']}",
                        "current_activity": (
                            None if project is None else f"loom://activity/{identity['id']}"
                        ),
                    },
                    "daemon": daemon_status,
                }
            ),
        }

    def _mcp_diagnostics_payload(
        self,
        *,
        client: CoordinationClient | None,
        refresh_daemon: bool,
    ) -> dict[str, object]:
        if client is None:
            agent_id, source = resolve_agent_identity(None)
            terminal_identity = current_terminal_identity()
            identity = {
                "id": agent_id,
                "source": source,
                "terminal_identity": terminal_identity,
                "terminal_binding": None,
                "project_default_agent": None,
                "project_initialized": False,
            }
            project = None
            daemon_status = None
        else:
            identity = self._identity_payload(client)
            project = client.project
            daemon_status = client.daemon_status(refresh=refresh_daemon)
        return {
            "project": project,
            "identity": identity,
            "daemon": daemon_status,
            "mcp": {
                "initialized": self._initialized,
                "subscription_count": len(self._subscription_snapshot()),
                "watcher": self._watch_snapshot(),
            },
        }

    def _read_tool_structured(
        self,
        *,
        client: CoordinationClient,
        next_steps: tuple[str, ...] = (),
        **payload: object,
    ) -> dict[str, object]:
        diagnostics = self._mcp_diagnostics_payload(client=client, refresh_daemon=False)
        next_action = payload.get("next_action")
        if payload.get("next_tool") is None and isinstance(next_action, dict):
            tool_name = str(next_action.get("tool", "")).strip()
            if tool_name:
                payload["next_tool"] = tool_name
        structured = {
            "project": diagnostics["project"],
            "identity": diagnostics["identity"],
            **payload,
            "daemon": diagnostics["daemon"],
            "mcp": diagnostics["mcp"],
            "next_steps": next_steps,
        }
        return structured

    def _read_status_resource(self) -> dict[str, object]:
        return _mcp_read_status_resource(
            self,
            status_agent_activity_limit=STATUS_AGENT_ACTIVITY_LIMIT,
        )

    def _read_context_feed_resource(self) -> dict[str, object]:
        return _mcp_read_context_feed_resource(self)

    def _read_log_resource(self) -> dict[str, object]:
        return _mcp_read_log_resource(self)

    def _read_activity_resource(self) -> dict[str, object]:
        return _mcp_read_activity_resource(self)

    def _read_activity_resource_for(self, *, uri: str, agent_id: str) -> dict[str, object]:
        return _mcp_read_activity_resource_for(self, uri=uri, agent_id=agent_id)

    def _read_agents_resource(self) -> dict[str, object]:
        return _mcp_read_agents_resource(self)

    def _read_conflicts_resource(self) -> dict[str, object]:
        return _mcp_read_conflicts_resource(self)

    def _read_conflict_history_resource(self) -> dict[str, object]:
        return _mcp_read_conflict_history_resource(self)

    def _read_agent_resource(self) -> dict[str, object]:
        return _mcp_read_agent_resource(self)

    def _read_agent_resource_for(self, *, uri: str, agent_id: str) -> dict[str, object]:
        return _mcp_read_agent_resource_for(self, uri=uri, agent_id=agent_id)

    def _read_inbox_resource(self) -> dict[str, object]:
        return _mcp_read_inbox_resource(self)

    def _read_inbox_resource_for(self, *, uri: str, agent_id: str) -> dict[str, object]:
        return _mcp_read_inbox_resource_for(self, uri=uri, agent_id=agent_id)

    def _read_claim_resource(self, *, uri: str, claim_id: str) -> dict[str, object]:
        client = self._client_for_tools()
        claim = client.store.get_claim(claim_id)
        if claim is None:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Claim not found: {claim_id}.")
        linked_context, related_conflicts = self._object_relationships(
            client.store,
            object_type="claim",
            object_id=claim_id,
        )
        return _mcp_render_claim_resource(
            self,
            uri=uri,
            client=client,
            claim=claim,
            linked_context=linked_context,
            related_conflicts=related_conflicts,
        )

    def _read_intent_resource(self, *, uri: str, intent_id: str) -> dict[str, object]:
        client = self._client_for_tools()
        intent = client.store.get_intent(intent_id)
        if intent is None:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Intent not found: {intent_id}.")
        linked_context, related_conflicts = self._object_relationships(
            client.store,
            object_type="intent",
            object_id=intent_id,
        )
        return _mcp_render_intent_resource(
            self,
            uri=uri,
            client=client,
            intent=intent,
            linked_context=linked_context,
            related_conflicts=related_conflicts,
        )

    def _read_conflict_resource(self, *, uri: str, conflict_id: str) -> dict[str, object]:
        client = self._client_for_tools()
        conflict = client.store.get_conflict(conflict_id)
        if conflict is None:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Conflict not found: {conflict_id}.")
        return _mcp_render_conflict_resource(
            self,
            uri=uri,
            client=client,
            conflict=conflict,
        )

    def _read_context_resource(self, *, uri: str, context_id: str) -> dict[str, object]:
        client = self._client_for_tools()
        context = client.get_context_entry(context_id=context_id)
        if context is None:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Context not found: {context_id}.")
        return _mcp_render_context_resource(
            self,
            uri=uri,
            client=client,
            context=context,
        )

    def _read_event_resource(self, *, uri: str, sequence: int) -> dict[str, object]:
        client = self._client_for_tools()
        event = client.store.get_event(sequence)
        if event is None:
            raise JsonRpcError(RESOURCE_NOT_FOUND, f"Event not found: {sequence}.")
        return _mcp_render_event_resource(
            self,
            uri=uri,
            client=client,
            event=event,
        )

    def _read_events_after_resource(self, *, uri: str, after_sequence: int) -> dict[str, object]:
        return _mcp_read_events_after_resource(
            self,
            uri=uri,
            after_sequence=after_sequence,
        )

    def _read_activity_feed_resource_for(
        self,
        *,
        uri: str,
        agent_id: str,
        after_sequence: int,
    ) -> dict[str, object]:
        return _mcp_read_activity_feed_resource_for(
            self,
            uri=uri,
            agent_id=agent_id,
            after_sequence=after_sequence,
        )

    def _read_timeline_resource(self, *, uri: str, object_id: str) -> dict[str, object]:
        client = self._client_for_tools()
        try:
            timeline = self._timeline_details(client, object_id=object_id, limit=20)
        except ToolExecutionError as error:
            raise JsonRpcError(RESOURCE_NOT_FOUND, str(error)) from error
        return _mcp_read_timeline_resource(
            self,
            uri=uri,
            client=client,
            timeline=timeline,
        )

    def _object_relationships(
        self,
        store,
        *,
        object_type: str,
        object_id: str,
    ) -> tuple[tuple[object, ...], tuple[object, ...]]:
        return _mcp_object_relationships(
            store,
            object_type=object_type,
            object_id=object_id,
        )

    def _timeline_details(
        self,
        client: CoordinationClient,
        *,
        object_id: str,
        limit: int,
    ) -> dict[str, object]:
        return _mcp_timeline_details(
            self,
            client,
            object_id=object_id,
            limit=limit,
            error_cls=ToolExecutionError,
        )

    def _timeline_payload(
        self,
        *,
        object_type: str,
        object_id: str,
        target: object,
        related_conflicts: object,
        linked_context: object,
        events: object,
    ) -> dict[str, object]:
        return _mcp_timeline_payload(
            object_type=object_type,
            object_id=object_id,
            target=target,
            related_conflicts=related_conflicts,
            linked_context=linked_context,
            events=events,
        )

    def _event_uri(self, sequence: int) -> str:
        return _mcp_event_uri(sequence)

    def _event_payloads(self, events: tuple[object, ...] | list[object]) -> list[dict[str, object]]:
        return _mcp_event_payloads(self, events)

    def _event_payload(self, event: object) -> dict[str, object]:
        return _mcp_event_payload(self, event)

    def _emit_notification(
        self,
        method: str,
        params: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "jsonrpc": JSONRPC_VERSION,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        with self._write_lock:
            writer = self._writer
            if writer is None:
                return
            try:
                self._write_message_unlocked(writer, payload)
            except (BrokenPipeError, OSError, ValueError):
                self._writer = None

    def _write_message(self, stream: TextIO, payload: dict[str, object]) -> None:
        with self._write_lock:
            self._write_message_unlocked(stream, payload)

    def _write_response_or_detach_writer(self, stream: TextIO, payload: dict[str, object]) -> bool:
        try:
            self._write_message(stream, payload)
            return True
        except (BrokenPipeError, OSError, ValueError):
            with self._write_lock:
                if self._writer is stream:
                    self._writer = None
            return False

    def _write_message_unlocked(self, stream: TextIO, payload: dict[str, object]) -> None:
        stream.write(f"{json.dumps(_json_ready(payload), sort_keys=True)}\n")
        stream.flush()

    def _success_response(self, message_id: object, result: dict[str, object]) -> dict[str, object]:
        return _json_ready(
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": message_id,
                "result": result,
            }
        )

    def _error_response(self, message_id: object, code: int, message: str) -> dict[str, object]:
        return _json_ready(
            {
                "jsonrpc": JSONRPC_VERSION,
                "id": message_id,
                "error": {
                    "code": code,
                    "message": message,
                },
            }
        )


class _Tool:
    def __init__(
        self,
        *,
        name: str,
        title: str,
        description: str,
        input_schema: dict[str, object],
        output_schema: dict[str, object],
        annotations: dict[str, object],
        handler: Any,
    ) -> None:
        self.name = name
        self.title = title
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.annotations = annotations
        self.handler = handler

    def describe(self) -> dict[str, object]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "outputSchema": self.output_schema,
            "annotations": self.annotations,
        }


def run_mcp_server(*, cwd: Path | None = None) -> int:
    return LoomMcpServer(cwd=cwd).run()


def _required_string(arguments: dict[str, object], field: str) -> str:
    value = arguments.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError(f"{field} must be a non-empty string.")
    return value.strip()


def _optional_string(arguments: dict[str, object], field: str) -> str | None:
    value = arguments.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolExecutionError(f"{field} must be a string when provided.")
    stripped = value.strip()
    return stripped or None


def _string_list(value: object, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ToolExecutionError(f"{field} must be a list of strings.")
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            raise ToolExecutionError(f"{field} must contain only non-empty strings.")
        items.append(entry.strip())
    return items


def _positive_int(value: object, *, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ToolExecutionError(f"{field} must be a positive integer.")
    return value


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise ToolExecutionError(f"{field} must be a boolean.")
    return value


def _reject_extra_arguments(arguments: dict[str, object], allowed: tuple[str, ...]) -> None:
    extras = sorted(set(arguments) - set(allowed))
    if extras:
        raise ToolExecutionError(f"Unexpected arguments: {', '.join(extras)}.")


def _tool_annotations(
    *,
    read_only: bool,
    destructive: bool = False,
    idempotent: bool = False,
) -> dict[str, object]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": False if read_only else destructive,
        "idempotentHint": True if read_only else idempotent,
        "openWorldHint": False,
    }


def _tool_result_schema(**properties: dict[str, object]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "error": {"type": "string"},
            "next_tool": {"type": "string"},
            "next_action": {
                "type": ["object", "null"],
                "properties": {
                    "tool": {"type": "string"},
                    "arguments": {"type": "object"},
                    "summary": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "string"},
                    "urgency": {"type": "string"},
                },
                "required": ["tool", "arguments", "summary", "reason", "confidence"],
                "additionalProperties": False,
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "links": {"type": "object"},
            **properties,
        },
        "required": ["ok"],
        "additionalProperties": False,
    }
