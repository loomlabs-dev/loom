from __future__ import annotations

from dataclasses import fields, is_dataclass

from .util import infer_object_type


def activity_feed_resource_uris_for_structured(server, value: object) -> tuple[str, ...]:
    agent_ids = extract_agent_ids(value)
    agent_ids.update(agent_ids_for_object_ids(server, extract_object_ids(value)))
    uris: list[str] = []
    for uri in sorted(server._subscription_snapshot()):
        target = server._activity_feed_target(uri)
        if target is None:
            continue
        agent_id, _ = target
        if agent_id in agent_ids:
            uris.append(uri)
    return tuple(uris)


def agent_resource_uris_for_structured(server, value: object) -> tuple[str, ...]:
    agent_ids = extract_agent_ids(value)
    agent_ids.update(agent_ids_for_object_ids(server, extract_object_ids(value)))
    uris: list[str] = []
    for agent_id in sorted(agent_ids):
        uris.extend(
            [
                f"loom://agent/{agent_id}",
                f"loom://inbox/{agent_id}",
                f"loom://activity/{agent_id}",
            ]
        )
    return tuple(uris)


def agent_ids_for_object_ids(server, object_ids: set[str]) -> set[str]:
    if not object_ids or server._client is None:
        return set()
    return resolve_agent_ids_from_object_ids(
        server._client.store,
        object_ids=object_ids,
        visited=set(),
    )


def resolve_agent_ids_from_object_ids(
    store,
    *,
    object_ids: set[str],
    visited: set[str],
) -> set[str]:
    agent_ids: set[str] = set()
    pending = list(object_ids)
    while pending:
        object_id = pending.pop()
        if object_id in visited:
            continue
        visited.add(object_id)
        try:
            object_type = infer_object_type(object_id)
        except ValueError:
            continue
        if object_type == "claim":
            claim = store.get_claim(object_id)
            if claim is not None:
                agent_ids.add(claim.agent_id)
        elif object_type == "intent":
            intent = store.get_intent(object_id)
            if intent is not None:
                agent_ids.add(intent.agent_id)
                if intent.related_claim_id is not None:
                    pending.append(intent.related_claim_id)
        elif object_type == "context":
            context = store.get_context(object_id)
            if context is not None:
                agent_ids.add(context.agent_id)
                for related_id in (
                    context.related_claim_id,
                    context.related_intent_id,
                ):
                    if related_id is not None:
                        pending.append(related_id)
        elif object_type == "conflict":
            conflict = store.get_conflict(object_id)
            if conflict is not None:
                if conflict.resolved_by is not None:
                    agent_ids.add(conflict.resolved_by)
                pending.extend((conflict.object_id_a, conflict.object_id_b))
    return agent_ids


def timeline_resource_uris_for_structured(value: object) -> tuple[str, ...]:
    object_ids = extract_object_ids(value)
    return tuple(f"loom://timeline/{object_id}" for object_id in sorted(object_ids))


def timeline_alias_resource_uris_for_structured(value: object) -> tuple[str, ...]:
    uris: list[str] = []
    for object_id in sorted(extract_object_ids(value)):
        alias_uri = timeline_alias_uri_for_object_id(object_id)
        if alias_uri is not None:
            uris.append(alias_uri)
    return tuple(uris)


def object_resource_uris_for_structured(value: object) -> tuple[str, ...]:
    uris: list[str] = []
    for object_id in sorted(extract_object_ids(value)):
        if object_id.startswith("claim_"):
            uris.append(f"loom://claim/{object_id}")
        elif object_id.startswith("intent_"):
            uris.append(f"loom://intent/{object_id}")
        elif object_id.startswith("conflict_"):
            uris.append(f"loom://conflict/{object_id}")
        elif object_id.startswith("context_"):
            uris.append(f"loom://context/{object_id}")
    return tuple(uris)


def extract_object_ids(value: object) -> set[str]:
    object_ids: set[str] = set()
    pending = [value]
    seen_containers: set[int] = set()
    while pending:
        current = pending.pop()
        if is_dataclass(current):
            container_id = id(current)
            if container_id in seen_containers:
                continue
            seen_containers.add(container_id)
            for field in fields(current):
                pending.append(getattr(current, field.name))
            continue
        if isinstance(current, dict):
            container_id = id(current)
            if container_id in seen_containers:
                continue
            seen_containers.add(container_id)
            pending.extend(current.values())
            continue
        if isinstance(current, (list, tuple, set)):
            container_id = id(current)
            if container_id in seen_containers:
                continue
            seen_containers.add(container_id)
            pending.extend(current)
            continue
        if isinstance(current, str) and any(
            current.startswith(prefix)
            for prefix in ("claim_", "intent_", "context_", "conflict_")
        ):
            object_ids.add(current)
    return object_ids


def timeline_alias_uri_for_object_id(object_id: str) -> str | None:
    if object_id.startswith("claim_"):
        return f"loom://claim/{object_id}/timeline"
    if object_id.startswith("intent_"):
        return f"loom://intent/{object_id}/timeline"
    if object_id.startswith("context_"):
        return f"loom://context/{object_id}/timeline"
    if object_id.startswith("conflict_"):
        return f"loom://conflict/{object_id}/timeline"
    return None


def timeline_object_id_for_alias_uri(uri: str) -> str | None:
    for prefix in (
        "loom://claim/",
        "loom://intent/",
        "loom://context/",
        "loom://conflict/",
    ):
        if not uri.startswith(prefix):
            continue
        suffix = uri[len(prefix) :]
        if not suffix.endswith("/timeline"):
            continue
        object_id = suffix[: -len("/timeline")]
        if object_id:
            return object_id
    return None


def object_resource_uri_for_object_id(object_id: str) -> str | None:
    if object_id.startswith("claim_"):
        return f"loom://claim/{object_id}"
    if object_id.startswith("intent_"):
        return f"loom://intent/{object_id}"
    if object_id.startswith("context_"):
        return f"loom://context/{object_id}"
    if object_id.startswith("conflict_"):
        return f"loom://conflict/{object_id}"
    return None


def extract_agent_ids(value: object, *, field_name: str | None = None) -> set[str]:
    agent_ids: set[str] = set()
    pending: list[tuple[object, str | None]] = [(value, field_name)]
    seen_containers: set[int] = set()
    while pending:
        current, current_field_name = pending.pop()
        if is_dataclass(current):
            container_id = id(current)
            if container_id in seen_containers:
                continue
            seen_containers.add(container_id)
            for field in fields(current):
                pending.append((getattr(current, field.name), field.name))
            continue
        if isinstance(current, dict):
            container_id = id(current)
            if container_id in seen_containers:
                continue
            seen_containers.add(container_id)
            for key, nested in current.items():
                key_name = key if isinstance(key, str) else None
                pending.append((nested, key_name))
            continue
        if isinstance(current, (list, tuple, set)):
            container_id = id(current)
            if container_id in seen_containers:
                continue
            seen_containers.add(container_id)
            for nested in current:
                pending.append((nested, current_field_name))
            continue
        if (
            isinstance(current, str)
            and current_field_name in {"agent_id", "resolved_by", "actor_id"}
            and current
        ):
            agent_ids.add(current)
    return agent_ids


def object_relationships(
    store,
    *,
    object_type: str,
    object_id: str,
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    if object_type == "claim":
        linked_context = tuple(store.list_context_for_claim(object_id))
        related_conflicts = tuple(
            store.list_conflicts_for_object(
                object_type="claim",
                object_id=object_id,
                include_resolved=True,
            )
        )
        return linked_context, related_conflicts
    if object_type == "intent":
        linked_context = tuple(store.list_context_for_intent(object_id))
        related_conflicts = tuple(
            store.list_conflicts_for_object(
                object_type="intent",
                object_id=object_id,
                include_resolved=True,
            )
        )
        return linked_context, related_conflicts
    if object_type == "context":
        return (), tuple(
            store.list_conflicts_for_object(
                object_type="context",
                object_id=object_id,
                include_resolved=True,
            )
        )
    return (), ()


def timeline_details(
    server,
    client,
    *,
    object_id: str,
    limit: int,
    error_cls,
) -> dict[str, object]:
    store = client.store
    try:
        object_type = infer_object_type(object_id)
    except ValueError as error:
        raise error_cls(str(error)) from error

    if object_type == "claim":
        target = store.get_claim(object_id)
    elif object_type == "intent":
        target = store.get_intent(object_id)
    elif object_type == "context":
        target = store.get_context(object_id)
    elif object_type == "conflict":
        target = store.get_conflict(object_id)
    else:
        target = None

    if target is None:
        raise error_cls(f"Object not found: {object_id}.")

    linked_context, related_conflicts = object_relationships(
        store,
        object_type=object_type,
        object_id=object_id,
    )

    related_references = [(object_type, object_id)]
    related_references.extend(("conflict", conflict.id) for conflict in related_conflicts)
    related_references.extend(("context", entry.id) for entry in linked_context)
    events = tuple(
        reversed(
            store.list_events_for_references(
                references=related_references,
                limit=limit,
                ascending=False,
            )
        )
    )
    return timeline_payload(
        object_type=object_type,
        object_id=object_id,
        target=target,
        related_conflicts=related_conflicts,
        linked_context=linked_context,
        events=event_payloads(server, events),
    )


def timeline_payload(
    *,
    object_type: str,
    object_id: str,
    target: object,
    related_conflicts: object,
    linked_context: object,
    events: object,
) -> dict[str, object]:
    return {
        "object_type": object_type,
        "object_id": object_id,
        "target": target,
        "related_conflicts": related_conflicts,
        "linked_context": linked_context,
        "events": events,
    }


def event_uri(sequence: int) -> str:
    return f"loom://event/{sequence}"


def event_payloads(server, events: tuple[object, ...] | list[object]) -> list[dict[str, object]]:
    return [event_payload(server, event) for event in events]


def event_payload(server, event: object) -> dict[str, object]:
    sequence = int(getattr(event, "sequence"))
    actor_id = str(getattr(event, "actor_id"))
    payload = dict(getattr(event, "payload"))
    object_ids = sorted(extract_object_ids(payload))
    object_links = [
        uri
        for object_id in object_ids
        if (uri := object_resource_uri_for_object_id(object_id)) is not None
    ]
    timeline_links = [
        uri
        for object_id in object_ids
        if (uri := timeline_alias_uri_for_object_id(object_id)) is not None
    ]
    return {
        "sequence": sequence,
        "id": str(getattr(event, "id")),
        "type": str(getattr(event, "type")),
        "timestamp": str(getattr(event, "timestamp")),
        "actor_id": actor_id,
        "payload": payload,
        "resource_uri": event_uri(sequence),
        "links": {
            "actor": f"loom://agent/{actor_id}",
            "actor_activity": f"loom://activity/{actor_id}",
            "objects": object_links,
            "timelines": timeline_links,
        },
    }
