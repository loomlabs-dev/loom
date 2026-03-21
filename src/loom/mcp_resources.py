from __future__ import annotations

from typing import Any, Callable


class Resource:
    def __init__(
        self,
        *,
        uri: str,
        name: str,
        description: str,
        mime_type: str,
        reader: Any,
    ) -> None:
        self.uri = uri
        self.name = name
        self.description = description
        self.mime_type = mime_type
        self.reader = reader

    def describe(self) -> dict[str, object]:
        return {
            "uri": self.uri,
            "name": self.name,
            "description": self.description,
            "mimeType": self.mime_type,
        }

    def read(self) -> dict[str, object]:
        return self.reader()


class ResourceTemplate:
    def __init__(
        self,
        *,
        uri_template: str,
        name: str,
        title: str,
        description: str,
        mime_type: str,
    ) -> None:
        self.uri_template = uri_template
        self.name = name
        self.title = title
        self.description = description
        self.mime_type = mime_type

    def describe(self) -> dict[str, object]:
        return {
            "uriTemplate": self.uri_template,
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "mimeType": self.mime_type,
        }


def build_resource_map(resources: tuple[Resource, ...]) -> dict[str, Resource]:
    return {resource.uri: resource for resource in resources}


def build_resource_uris(resources: tuple[Resource, ...]) -> tuple[str, ...]:
    return tuple(build_resource_map(resources))


def build_resource_templates() -> tuple[ResourceTemplate, ...]:
    return (
        ResourceTemplate(
            uri_template="loom://claim/{claim_id}",
            name="Loom Claim",
            title="Loom Claim",
            description="Read one Loom claim by id with linked coordination state.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://claim/{claim_id}/timeline",
            name="Loom Claim Timeline",
            title="Loom Claim Timeline",
            description="Read the Loom timeline for one claim id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://intent/{intent_id}",
            name="Loom Intent",
            title="Loom Intent",
            description="Read one Loom intent by id with linked coordination state.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://intent/{intent_id}/timeline",
            name="Loom Intent Timeline",
            title="Loom Intent Timeline",
            description="Read the Loom timeline for one intent id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://agent/{agent_id}",
            name="Loom Agent View",
            title="Loom Agent View",
            description="Read the Loom coordination view for one explicit agent id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://inbox/{agent_id}",
            name="Loom Inbox",
            title="Loom Inbox",
            description="Read the Loom inbox for one explicit agent id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://activity/{agent_id}",
            name="Loom Activity",
            title="Loom Activity",
            description="Read recent Loom coordination activity for one explicit agent id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://activity/{agent_id}/after/{sequence}",
            name="Loom Activity Feed",
            title="Loom Activity Feed",
            description="Read Loom coordination events for one explicit agent after a sequence cursor.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://conflict/{conflict_id}",
            name="Loom Conflict",
            title="Loom Conflict",
            description="Read one Loom conflict record by id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://context/{context_id}",
            name="Loom Context",
            title="Loom Context",
            description="Read one Loom context note by id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://conflict/{conflict_id}/timeline",
            name="Loom Conflict Timeline",
            title="Loom Conflict Timeline",
            description="Read the Loom timeline for one conflict id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://context/{context_id}/timeline",
            name="Loom Context Timeline",
            title="Loom Context Timeline",
            description="Read the Loom timeline for one context id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://timeline/{object_id}",
            name="Loom Timeline",
            title="Loom Timeline",
            description="Read the Loom timeline for one claim, intent, context, or conflict id.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://event/{sequence}",
            name="Loom Event",
            title="Loom Event",
            description="Read one Loom coordination event by sequence number.",
            mime_type="application/json",
        ),
        ResourceTemplate(
            uri_template="loom://events/after/{sequence}",
            name="Loom Event Feed",
            title="Loom Event Feed",
            description="Read Loom coordination events after one event sequence cursor.",
            mime_type="application/json",
        ),
    )


def build_resources(
    *,
    project_available: bool,
    read_protocol: Any,
    read_start: Any,
    read_identity: Any,
    read_mcp: Any,
    read_activity: Any,
    read_log: Any,
    read_context_feed: Any,
    read_status: Any,
    read_agents: Any,
    read_conflicts: Any,
    read_conflict_history: Any,
    read_agent: Any,
    read_inbox: Any,
) -> tuple[Resource, ...]:
    resources: list[Resource] = [
        Resource(
            uri="loom://protocol",
            name="Loom Protocol",
            description="The local Loom protocol descriptor and schemas.",
            mime_type="application/json",
            reader=read_protocol,
        ),
        Resource(
            uri="loom://start",
            name="Loom Start",
            description="Repo-aware guidance for the best next Loom action in this checkout.",
            mime_type="application/json",
            reader=read_start,
        ),
        Resource(
            uri="loom://identity",
            name="Loom Identity",
            description="The resolved Loom identity for this MCP server process.",
            mime_type="application/json",
            reader=read_identity,
        ),
        Resource(
            uri="loom://mcp",
            name="Loom MCP Diagnostics",
            description="Diagnostics for this Loom MCP server, including subscriptions and passive watch state.",
            mime_type="application/json",
            reader=read_mcp,
        ),
    ]
    if project_available:
        resources.extend(
            [
                Resource(
                    uri="loom://activity",
                    name="Loom Current Activity",
                    description="Recent Loom coordination activity relevant to the resolved current agent.",
                    mime_type="application/json",
                    reader=read_activity,
                ),
                Resource(
                    uri="loom://log",
                    name="Loom Log",
                    description="Recent coordination activity for this repository.",
                    mime_type="application/json",
                    reader=read_log,
                ),
                Resource(
                    uri="loom://context",
                    name="Loom Context",
                    description="Recent Loom context notes for this repository.",
                    mime_type="application/json",
                    reader=read_context_feed,
                ),
                Resource(
                    uri="loom://status",
                    name="Loom Status",
                    description="The current repository-wide Loom coordination state.",
                    mime_type="application/json",
                    reader=read_status,
                ),
                Resource(
                    uri="loom://agents",
                    name="Loom Agents",
                    description="Known Loom agents recently active in this repository.",
                    mime_type="application/json",
                    reader=read_agents,
                ),
                Resource(
                    uri="loom://conflicts",
                    name="Loom Conflicts",
                    description="The current active Loom conflicts for this repository.",
                    mime_type="application/json",
                    reader=read_conflicts,
                ),
                Resource(
                    uri="loom://conflicts/history",
                    name="Loom Conflict History",
                    description="Active and resolved Loom conflicts for this repository.",
                    mime_type="application/json",
                    reader=read_conflict_history,
                ),
                Resource(
                    uri="loom://agent",
                    name="Loom Current Agent",
                    description="The resolved current agent view for this MCP server.",
                    mime_type="application/json",
                    reader=read_agent,
                ),
                Resource(
                    uri="loom://inbox",
                    name="Loom Current Inbox",
                    description="The resolved current agent inbox for this MCP server.",
                    mime_type="application/json",
                    reader=read_inbox,
                ),
            ]
        )
    return tuple(resources)


def dynamic_resource_target(
    uri: str,
    *,
    timeline_object_id_for_alias_uri: Callable[[str], str | None],
) -> tuple[str, str] | None:
    timeline_alias_object_id = timeline_object_id_for_alias_uri(uri)
    if timeline_alias_object_id is not None:
        return ("timeline", timeline_alias_object_id)

    dynamic_prefixes = (
        ("loom://events/after/", "event_feed"),
        ("loom://claim/", "claim"),
        ("loom://intent/", "intent"),
        ("loom://agent/", "agent"),
        ("loom://inbox/", "inbox"),
        ("loom://activity/", "activity"),
        ("loom://conflict/", "conflict"),
        ("loom://context/", "context"),
        ("loom://timeline/", "timeline"),
        ("loom://event/", "event"),
    )
    for prefix, target_type in dynamic_prefixes:
        if not uri.startswith(prefix):
            continue
        identifier = uri[len(prefix) :]
        if not identifier:
            return None
        if target_type in {"claim", "intent", "conflict", "context"} and "/timeline" in identifier:
            return None
        return (target_type, identifier)
    return None


def activity_feed_target(
    uri: str,
    *,
    after_sequence: Callable[[str], int],
) -> tuple[str, int] | None:
    prefix = "loom://activity/"
    if not uri.startswith(prefix):
        return None
    suffix = uri[len(prefix) :]
    if "/after/" not in suffix:
        return None
    agent_id, sequence_text = suffix.split("/after/", 1)
    if not agent_id:
        return None
    return (agent_id, after_sequence(sequence_text))


def project_resource_uris(
    *,
    resource_map: dict[str, Resource],
    include_identity: bool,
) -> tuple[str, ...]:
    uris: list[str] = []
    if include_identity:
        uris.append("loom://identity")
    uris.extend(
        [
            "loom://start",
            "loom://mcp",
            "loom://activity",
            "loom://log",
            "loom://context",
            "loom://status",
            "loom://agents",
            "loom://conflicts",
            "loom://conflicts/history",
            "loom://agent",
            "loom://inbox",
        ]
    )
    return tuple(uri for uri in uris if uri in resource_map)
