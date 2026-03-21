from __future__ import annotations

from pathlib import Path

from .authority import read_authority_summary
from .guidance import (
    repo_lanes_payload as guidance_repo_lanes_payload,
    stale_agent_ids as guidance_stale_agent_ids,
)
from .identity import terminal_identity_process_is_alive
from .mcp_support import (
    json_text as _json_text,
    tool_agent_action as _tool_agent_action,
    tool_agent_next_steps as _tool_agent_next_steps,
    tool_agents_next_steps as _tool_agents_next_steps,
    tool_conflicts_action as _tool_conflicts_action,
    tool_conflicts_next_steps as _tool_conflicts_next_steps,
    tool_inbox_action as _tool_inbox_action,
    tool_inbox_next_steps as _tool_inbox_next_steps,
    tool_status_action as _tool_status_action,
    tool_status_next_steps as _tool_status_next_steps,
)
from .util import current_worktree_paths


def _dead_session_agent_ids(server, agents: tuple[object, ...]) -> tuple[str, ...]:
    helper = getattr(server, "_dead_session_agent_ids", None)
    if callable(helper):
        return tuple(helper(agents))
    return tuple(
        str(getattr(presence, "agent_id"))
        for presence in agents
        if terminal_identity_process_is_alive(str(getattr(presence, "agent_id"))) is False
    )


def _authority_summary(
    server,
    project: object | None,
    *,
    claims: tuple[object, ...] = (),
    intents: tuple[object, ...] = (),
) -> dict[str, object]:
    helper = getattr(server, "_authority_summary", None)
    if callable(helper):
        return dict(helper(project, claims=claims, intents=intents))
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
    return read_authority_summary(
        repo_root,
        changed_paths=tuple(str(path) for path in current_worktree_paths(repo_root)),
        claims=tuple(claims),
        intents=tuple(intents),
    )


def read_status_resource(server, *, status_agent_activity_limit: int) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    status = client.read_status()
    agents = tuple(client.read_agents(limit=status_agent_activity_limit))
    dead_session_ids = _dead_session_agent_ids(server, agents)
    authority = _authority_summary(
        server,
        client.project,
        claims=status.claims,
        intents=status.intents,
    )
    stale_agent_ids = guidance_stale_agent_ids(agents)
    repo_lanes = guidance_repo_lanes_payload(
        agents=agents,
        snapshot=status,
        store=client.store,
        stale_agent_ids=stale_agent_ids,
    )
    agent_id = str(identity["id"])
    return {
        "uri": "loom://status",
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "status": status,
                "authority": authority,
                "repo_lanes": repo_lanes,
                "next_action": _tool_status_action(
                    client=client,
                    snapshot=status,
                    identity=identity,
                    authority=authority,
                    dead_session_count=len(dead_session_ids),
                    stale_agent_ids=stale_agent_ids,
                    repo_lanes=repo_lanes,
                ),
                "dead_session_agents": dead_session_ids,
                "next_steps": _tool_status_next_steps(
                    snapshot=status,
                    identity=identity,
                    authority=authority,
                    dead_session_count=len(dead_session_ids),
                ),
                "links": {
                    "start": "loom://start",
                    "identity": "loom://identity",
                    "log": "loom://log",
                    "context_feed": "loom://context",
                    "agents": "loom://agents",
                    "conflicts": "loom://conflicts",
                    "conflict_history": "loom://conflicts/history",
                    "current_agent": f"loom://agent/{agent_id}",
                    "current_inbox": f"loom://inbox/{agent_id}",
                    "current_activity": f"loom://activity/{agent_id}",
                    "claims": [f"loom://claim/{claim.id}" for claim in status.claims],
                    "intents": [f"loom://intent/{intent.id}" for intent in status.intents],
                    "context": [f"loom://context/{entry.id}" for entry in status.context],
                    "active_conflicts": [
                        f"loom://conflict/{conflict.id}" for conflict in status.conflicts
                    ],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_context_feed_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    agent_id = str(identity["id"])
    context_entries = client.read_context_entries(limit=20)
    return {
        "uri": "loom://context",
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "context": context_entries,
                "links": {
                    "start": "loom://start",
                    "status": "loom://status",
                    "log": "loom://log",
                    "current_agent": f"loom://agent/{agent_id}",
                    "current_inbox": f"loom://inbox/{agent_id}",
                    "items": [f"loom://context/{entry.id}" for entry in context_entries],
                    "authors": sorted(
                        {f"loom://agent/{entry.agent_id}" for entry in context_entries}
                    ),
                    "related_claims": sorted(
                        {
                            f"loom://claim/{entry.related_claim_id}"
                            for entry in context_entries
                            if entry.related_claim_id is not None
                        }
                    ),
                    "related_intents": sorted(
                        {
                            f"loom://intent/{entry.related_intent_id}"
                            for entry in context_entries
                            if entry.related_intent_id is not None
                        }
                    ),
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_log_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    agent_id = str(identity["id"])
    events = client.read_events(
        limit=20,
        event_type=None,
        after_sequence=None,
        ascending=False,
    )
    return {
        "uri": "loom://log",
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "events": server._event_payloads(events),
                "links": {
                    "start": "loom://start",
                    "status": "loom://status",
                    "context_feed": "loom://context",
                    "agents": "loom://agents",
                    "conflicts": "loom://conflicts",
                    "current_activity": f"loom://activity/{agent_id}",
                    "events": [server._event_uri(event.sequence) for event in events],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_activity_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    return read_activity_resource_for(
        server,
        uri="loom://activity",
        agent_id=str(identity["id"]),
    )


def read_activity_resource_for(
    server,
    *,
    uri: str,
    agent_id: str,
) -> dict[str, object]:
    client = server._client_for_tools()
    agent = client.read_agent_snapshot(
        agent_id=agent_id,
        context_limit=5,
        event_limit=20,
    )
    claim_uri = None if agent.claim is None else f"loom://claim/{agent.claim.id}"
    intent_uri = None if agent.intent is None else f"loom://intent/{agent.intent.id}"
    resume_after_sequence = 0 if not agent.events else int(getattr(agent.events[-1], "sequence"))
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "events": server._event_payloads(agent.events),
                "agent": {
                    "id": agent.agent_id,
                    "claim_id": None if agent.claim is None else agent.claim.id,
                    "intent_id": None if agent.intent is None else agent.intent.id,
                    "pending_context_count": len(agent.incoming_context),
                    "conflict_count": len(agent.conflicts),
                },
                "links": {
                    "start": "loom://start",
                    "agent": f"loom://agent/{agent.agent_id}",
                    "inbox": f"loom://inbox/{agent.agent_id}",
                    "context_feed": "loom://context",
                    "claim": claim_uri,
                    "intent": intent_uri,
                    "published_context": [
                        f"loom://context/{entry.id}" for entry in agent.published_context
                    ],
                    "incoming_context": [
                        f"loom://context/{entry.id}" for entry in agent.incoming_context
                    ],
                    "conflicts": [
                        f"loom://conflict/{conflict.id}" for conflict in agent.conflicts
                    ],
                    "log": "loom://log",
                    "events": [server._event_uri(event.sequence) for event in agent.events],
                    "feed": f"loom://activity/{agent.agent_id}/after/{resume_after_sequence}",
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_agents_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    agents = tuple(client.read_agents(limit=20))
    dead_session_ids = _dead_session_agent_ids(server, agents)
    visible_agents = tuple(
        presence
        for presence in agents
        if getattr(presence, "claim", None) is not None
        or getattr(presence, "intent", None) is not None
    )
    idle_history_hidden_count = max(0, len(agents) - len(visible_agents))
    return {
        "uri": "loom://agents",
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "agents": visible_agents,
                "dead_session_agents": dead_session_ids,
                "showing_idle_history": False,
                "idle_history_hidden_count": idle_history_hidden_count,
                "next_steps": _tool_agents_next_steps(
                    agent_count=len(visible_agents),
                    identity=identity,
                    dead_session_count=len(dead_session_ids),
                    idle_history_hidden_count=idle_history_hidden_count,
                ),
                "links": {
                    "start": "loom://start",
                    "status": "loom://status",
                    "conflicts": "loom://conflicts",
                    "current_agent": f"loom://agent/{identity['id']}",
                    "agent_views": [f"loom://agent/{entry.agent_id}" for entry in visible_agents],
                    "inboxes": [f"loom://inbox/{entry.agent_id}" for entry in visible_agents],
                    "activity": [f"loom://activity/{entry.agent_id}" for entry in visible_agents],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_conflicts_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    conflicts = client.read_conflicts(include_resolved=False)
    return {
        "uri": "loom://conflicts",
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "conflicts": conflicts,
                "next_action": _tool_conflicts_action(conflicts=conflicts),
                "next_steps": _tool_conflicts_next_steps(conflict_count=len(conflicts)),
                "links": {
                    "start": "loom://start",
                    "status": "loom://status",
                    "history": "loom://conflicts/history",
                    "items": [f"loom://conflict/{conflict.id}" for conflict in conflicts],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_conflict_history_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    conflicts = client.read_conflicts(include_resolved=True)
    return {
        "uri": "loom://conflicts/history",
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "conflicts": conflicts,
                "links": {
                    "start": "loom://start",
                    "status": "loom://status",
                    "active": "loom://conflicts",
                    "items": [f"loom://conflict/{conflict.id}" for conflict in conflicts],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_agent_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    return read_agent_resource_for(
        server,
        uri="loom://agent",
        agent_id=str(identity["id"]),
    )


def read_agent_resource_for(
    server,
    *,
    uri: str,
    agent_id: str,
) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    payload = server._agent_runtime_payload(
        client=client,
        agent_id=agent_id,
        context_limit=5,
        event_limit=10,
    )
    agent = payload["agent"]
    claim_uri = None if agent.claim is None else f"loom://claim/{agent.claim.id}"
    intent_uri = None if agent.intent is None else f"loom://intent/{agent.intent.id}"
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "agent": agent,
                "active_work": payload["active_work"],
                "worktree": payload["worktree"],
                "next_action": _tool_agent_action(
                    agent=agent,
                    active_work=payload["recovery"],
                    worktree_signal=payload["worktree"],
                ),
                "next_steps": _tool_agent_next_steps(
                    agent=agent,
                    active_work=payload["recovery"],
                    worktree_signal=payload["worktree"],
                ),
                "links": {
                    "start": "loom://start",
                    "activity": f"loom://activity/{agent.agent_id}",
                    "inbox": f"loom://inbox/{agent.agent_id}",
                    "context_feed": "loom://context",
                    "claim": claim_uri,
                    "intent": intent_uri,
                    "published_context": [
                        f"loom://context/{entry.id}" for entry in agent.published_context
                    ],
                    "incoming_context": [
                        f"loom://context/{entry.id}" for entry in agent.incoming_context
                    ],
                    "conflicts": [
                        f"loom://conflict/{conflict.id}" for conflict in agent.conflicts
                    ],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_inbox_resource(server) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    return read_inbox_resource_for(
        server,
        uri="loom://inbox",
        agent_id=str(identity["id"]),
    )


def read_inbox_resource_for(
    server,
    *,
    uri: str,
    agent_id: str,
) -> dict[str, object]:
    client = server._client_for_tools()
    identity = server._identity_payload(client)
    inbox = client.read_inbox_snapshot(
        agent_id=agent_id,
        context_limit=5,
        event_limit=10,
    )
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": identity,
                "inbox": inbox,
                "next_action": _tool_inbox_action(inbox=inbox),
                "next_steps": _tool_inbox_next_steps(inbox=inbox),
                "links": {
                    "start": "loom://start",
                    "agent": f"loom://agent/{inbox.agent_id}",
                    "activity": f"loom://activity/{inbox.agent_id}",
                    "context_feed": "loom://context",
                    "pending_context": [
                        f"loom://context/{entry.id}" for entry in inbox.pending_context
                    ],
                    "conflicts": [
                        f"loom://conflict/{conflict.id}" for conflict in inbox.conflicts
                    ],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def render_claim_resource(
    server,
    *,
    uri: str,
    client,
    claim,
    linked_context,
    related_conflicts,
) -> dict[str, object]:
    linked_context_uris = [f"loom://context/{entry.id}" for entry in linked_context]
    related_conflict_uris = [f"loom://conflict/{conflict.id}" for conflict in related_conflicts]
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "claim": claim,
                "linked_context": linked_context,
                "related_conflicts": related_conflicts,
                "timeline_uri": server._timeline_alias_uri_for_object_id(claim.id),
                "links": {
                    "start": "loom://start",
                    "agent": f"loom://agent/{claim.agent_id}",
                    "activity": f"loom://activity/{claim.agent_id}",
                    "timeline": server._timeline_alias_uri_for_object_id(claim.id),
                    "related_context": linked_context_uris,
                    "related_conflicts": related_conflict_uris,
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def render_intent_resource(
    server,
    *,
    uri: str,
    client,
    intent,
    linked_context,
    related_conflicts,
) -> dict[str, object]:
    linked_context_uris = [f"loom://context/{entry.id}" for entry in linked_context]
    related_conflict_uris = [f"loom://conflict/{conflict.id}" for conflict in related_conflicts]
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "intent": intent,
                "linked_context": linked_context,
                "related_conflicts": related_conflicts,
                "timeline_uri": server._timeline_alias_uri_for_object_id(intent.id),
                "links": {
                    "start": "loom://start",
                    "agent": f"loom://agent/{intent.agent_id}",
                    "activity": f"loom://activity/{intent.agent_id}",
                    "timeline": server._timeline_alias_uri_for_object_id(intent.id),
                    "related_claim": (
                        None
                        if intent.related_claim_id is None
                        else f"loom://claim/{intent.related_claim_id}"
                    ),
                    "related_context": linked_context_uris,
                    "related_conflicts": related_conflict_uris,
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def render_conflict_resource(
    server,
    *,
    uri: str,
    client,
    conflict,
) -> dict[str, object]:
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "conflict": conflict,
                "timeline_uri": server._timeline_alias_uri_for_object_id(conflict.id),
                "links": {
                    "start": "loom://start",
                    "timeline": server._timeline_alias_uri_for_object_id(conflict.id),
                    "object_a": server._object_resource_uri_for_object_id(conflict.object_id_a),
                    "object_b": server._object_resource_uri_for_object_id(conflict.object_id_b),
                    "object_a_timeline": server._timeline_alias_uri_for_object_id(
                        conflict.object_id_a
                    ),
                    "object_b_timeline": server._timeline_alias_uri_for_object_id(
                        conflict.object_id_b
                    ),
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def render_context_resource(
    server,
    *,
    uri: str,
    client,
    context,
) -> dict[str, object]:
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "context": context,
                "timeline_uri": server._timeline_alias_uri_for_object_id(context.id),
                "links": {
                    "start": "loom://start",
                    "agent": f"loom://agent/{context.agent_id}",
                    "activity": f"loom://activity/{context.agent_id}",
                    "timeline": server._timeline_alias_uri_for_object_id(context.id),
                    "related_claim": (
                        None
                        if context.related_claim_id is None
                        else f"loom://claim/{context.related_claim_id}"
                    ),
                    "related_intent": (
                        None
                        if context.related_intent_id is None
                        else f"loom://intent/{context.related_intent_id}"
                    ),
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def render_event_resource(
    server,
    *,
    uri: str,
    client,
    event,
) -> dict[str, object]:
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "event": server._event_payload(event),
                "links": {
                    "start": "loom://start",
                    "log": "loom://log",
                    "actor": f"loom://agent/{event.actor_id}",
                    "actor_activity": f"loom://activity/{event.actor_id}",
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_events_after_resource(
    server,
    *,
    uri: str,
    after_sequence: int,
) -> dict[str, object]:
    client = server._client_for_tools()
    events = client.read_events(
        limit=50,
        event_type=None,
        after_sequence=after_sequence,
        ascending=True,
    )
    latest_sequence = client.store.latest_event_sequence()
    resume_after_sequence = (
        after_sequence if not events else int(getattr(events[-1], "sequence"))
    )
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "after_sequence": after_sequence,
                "latest_sequence": latest_sequence,
                "resume_after_sequence": resume_after_sequence,
                "events": server._event_payloads(events),
                "links": {
                    "start": "loom://start",
                    "log": "loom://log",
                    "resume": f"loom://events/after/{resume_after_sequence}",
                    "events": [server._event_uri(event.sequence) for event in events],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_activity_feed_resource_for(
    server,
    *,
    uri: str,
    agent_id: str,
    after_sequence: int,
) -> dict[str, object]:
    client = server._client_for_tools()
    events, latest_relevant_sequence = client.store.agent_event_feed(
        agent_id=agent_id,
        context_limit=5,
        limit=50,
        after_sequence=after_sequence,
        ascending=True,
    )
    latest_relevant_sequence = max(after_sequence, latest_relevant_sequence)
    resume_after_sequence = (
        after_sequence if not events else int(getattr(events[-1], "sequence"))
    )
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                "agent_id": agent_id,
                "after_sequence": after_sequence,
                "latest_relevant_sequence": latest_relevant_sequence,
                "resume_after_sequence": resume_after_sequence,
                "events": server._event_payloads(events),
                "links": {
                    "start": "loom://start",
                    "agent": f"loom://agent/{agent_id}",
                    "activity": f"loom://activity/{agent_id}",
                    "inbox": f"loom://inbox/{agent_id}",
                    "resume": f"loom://activity/{agent_id}/after/{resume_after_sequence}",
                    "events": [server._event_uri(event.sequence) for event in events],
                },
                "daemon": client.daemon_status(),
            }
        ),
    }


def read_timeline_resource(
    server,
    *,
    uri: str,
    client,
    timeline: dict[str, object],
) -> dict[str, object]:
    return {
        "uri": uri,
        "mimeType": "application/json",
        "text": _json_text(
            {
                "project": client.project,
                "identity": server._identity_payload(client),
                **timeline,
                "links": {
                    "start": "loom://start",
                    "status": "loom://status",
                },
                "daemon": client.daemon_status(),
            }
        ),
    }
