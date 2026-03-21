from __future__ import annotations

from typing import Callable


def tool_base_links(*, agent_id: str) -> dict[str, object]:
    return {
        "start": "loom://start",
        "identity": "loom://identity",
        "mcp": "loom://mcp",
        "status": "loom://status",
        "agents": "loom://agents",
        "log": "loom://log",
        "context": "loom://context",
        "conflicts": "loom://conflicts",
        "conflict_history": "loom://conflicts/history",
        "agent": f"loom://agent/{agent_id}",
        "inbox": f"loom://inbox/{agent_id}",
        "activity": f"loom://activity/{agent_id}",
    }


def tool_claim_links(
    *,
    agent_id: str,
    claim: object,
    conflicts: tuple[object, ...] = (),
) -> dict[str, object]:
    claim_id = str(getattr(claim, "id"))
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "claim": f"loom://claim/{claim_id}",
            "claim_timeline": f"loom://claim/{claim_id}/timeline",
            "conflicts_for_claim": [f"loom://conflict/{conflict.id}" for conflict in conflicts],
        }
    )
    return links


def tool_intent_links(
    *,
    agent_id: str,
    intent: object,
    conflicts: tuple[object, ...] = (),
) -> dict[str, object]:
    intent_id = str(getattr(intent, "id"))
    related_claim_id = getattr(intent, "related_claim_id", None)
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "intent": f"loom://intent/{intent_id}",
            "intent_timeline": f"loom://intent/{intent_id}/timeline",
            "related_claim": (
                None if related_claim_id is None else f"loom://claim/{related_claim_id}"
            ),
            "conflicts_for_intent": [f"loom://conflict/{conflict.id}" for conflict in conflicts],
        }
    )
    return links


def tool_context_write_links(
    *,
    agent_id: str,
    context: object,
    conflicts: tuple[object, ...] = (),
) -> dict[str, object]:
    context_id = str(getattr(context, "id"))
    related_claim_id = getattr(context, "related_claim_id", None)
    related_intent_id = getattr(context, "related_intent_id", None)
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "context_item": f"loom://context/{context_id}",
            "context_timeline": f"loom://context/{context_id}/timeline",
            "related_claim": (
                None if related_claim_id is None else f"loom://claim/{related_claim_id}"
            ),
            "related_intent": (
                None if related_intent_id is None else f"loom://intent/{related_intent_id}"
            ),
            "conflicts_for_context": [
                f"loom://conflict/{conflict.id}" for conflict in conflicts
            ],
        }
    )
    return links


def tool_context_read_links(
    *,
    agent_id: str,
    context: tuple[object, ...],
) -> dict[str, object]:
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "items": [f"loom://context/{entry.id}" for entry in context],
            "authors": sorted({f"loom://agent/{entry.agent_id}" for entry in context}),
        }
    )
    return links


def tool_context_ack_links(*, agent_id: str, acknowledgment: object) -> dict[str, object]:
    context_id = str(getattr(acknowledgment, "context_id"))
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "context_item": f"loom://context/{context_id}",
            "context_timeline": f"loom://context/{context_id}/timeline",
        }
    )
    return links


def tool_resolve_links(
    *,
    agent_id: str,
    conflict: object,
    object_resource_uri_for_object_id: Callable[[str], str | None],
) -> dict[str, object]:
    conflict_id = str(getattr(conflict, "id"))
    object_id_a = str(getattr(conflict, "object_id_a"))
    object_id_b = str(getattr(conflict, "object_id_b"))
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "conflict": f"loom://conflict/{conflict_id}",
            "conflict_timeline": f"loom://conflict/{conflict_id}/timeline",
            "object_a": object_resource_uri_for_object_id(object_id_a),
            "object_b": object_resource_uri_for_object_id(object_id_b),
        }
    )
    return links


def tool_status_links(*, agent_id: str, snapshot: object) -> dict[str, object]:
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "claims": [f"loom://claim/{claim.id}" for claim in tuple(getattr(snapshot, "claims", ()))],
            "intents": [
                f"loom://intent/{intent.id}" for intent in tuple(getattr(snapshot, "intents", ()))
            ],
            "context_items": [
                f"loom://context/{entry.id}" for entry in tuple(getattr(snapshot, "context", ()))
            ],
            "active_conflicts": [
                f"loom://conflict/{conflict.id}"
                for conflict in tuple(getattr(snapshot, "conflicts", ()))
            ],
        }
    )
    return links


def tool_agents_links(*, agent_id: str, agents: tuple[object, ...]) -> dict[str, object]:
    links = tool_base_links(agent_id=agent_id)
    links["items"] = [f"loom://agent/{record.agent_id}" for record in agents]
    return links


def tool_log_links(*, agent_id: str, events: tuple[object, ...]) -> dict[str, object]:
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "events_feed": "loom://events/after/0",
            "events": [f"loom://event/{event.sequence}" for event in events],
            "activity_feed": f"loom://activity/{agent_id}/after/0",
        }
    )
    return links


def tool_agent_links(*, agent: object) -> dict[str, object]:
    agent_id = str(getattr(agent, "agent_id"))
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "claim": None if getattr(agent, "claim") is None else f"loom://claim/{agent.claim.id}",
            "intent": None if getattr(agent, "intent") is None else f"loom://intent/{agent.intent.id}",
            "incoming_context": [f"loom://context/{entry.id}" for entry in agent.incoming_context],
            "conflicts": [f"loom://conflict/{conflict.id}" for conflict in agent.conflicts],
        }
    )
    return links


def tool_inbox_links(*, inbox: object) -> dict[str, object]:
    agent_id = str(getattr(inbox, "agent_id"))
    links = tool_base_links(agent_id=agent_id)
    links.update(
        {
            "pending_context": [f"loom://context/{entry.id}" for entry in inbox.pending_context],
            "conflicts": [f"loom://conflict/{conflict.id}" for conflict in inbox.conflicts],
            "activity_feed": f"loom://activity/{agent_id}/after/0",
        }
    )
    return links


def tool_conflicts_links(
    *,
    agent_id: str,
    conflicts: tuple[object, ...],
) -> dict[str, object]:
    links = tool_base_links(agent_id=agent_id)
    links["items"] = [f"loom://conflict/{conflict.id}" for conflict in conflicts]
    return links


def tool_timeline_links(
    *,
    agent_id: str,
    object_id: str,
    linked_context: tuple[object, ...],
    related_conflicts: tuple[object, ...],
    object_resource_uri_for_object_id: Callable[[str], str | None],
    timeline_alias_uri_for_object_id: Callable[[str], str | None],
) -> dict[str, object]:
    links = tool_base_links(agent_id=agent_id)
    object_uri = object_resource_uri_for_object_id(object_id)
    timeline_uri = timeline_alias_uri_for_object_id(object_id)
    links.update(
        {
            "object": object_uri,
            "timeline": timeline_uri or f"loom://timeline/{object_id}",
            "linked_context": [f"loom://context/{entry.id}" for entry in linked_context],
            "related_conflicts": [
                f"loom://conflict/{conflict.id}" for conflict in related_conflicts
            ],
        }
    )
    return links
