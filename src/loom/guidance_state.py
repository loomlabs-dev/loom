from __future__ import annotations

from pathlib import PurePosixPath

from .local_store import (
    AgentPresenceRecord,
    ClaimRecord,
    ContextRecord,
    CoordinationStore,
    IntentRecord,
)
from .util import (
    DEFAULT_LEASE_POLICY,
    is_past_utc_timestamp,
    is_stale_utc_timestamp,
    normalize_lease_policy,
    normalize_scope,
    normalize_scopes,
    overlapping_scopes,
    parse_utc_timestamp,
)

MAX_SUGGESTED_DRIFT_SCOPES = 5
RECENT_HANDOFF_WINDOW_HOURS = 24 * 7
NEARBY_YIELD_FRESH_HOURS = 4


def active_scope_for_worktree(
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> tuple[str, ...]:
    scopes: list[str] = []
    if claim is not None:
        claim_scope = getattr(claim, "scope", ())
        if isinstance(claim_scope, (list, tuple)):
            scopes.extend(str(item) for item in claim_scope)
    if intent is not None:
        intent_scope = getattr(intent, "scope", ())
        if isinstance(intent_scope, (list, tuple)):
            scopes.extend(str(item) for item in intent_scope)
    if not scopes:
        return ()
    return normalize_scopes(scopes)


def worktree_scope_candidate(path: str) -> str:
    normalized = normalize_scope(path)
    pure_path = PurePosixPath(normalized)
    if pure_path.suffix and str(pure_path.parent) not in ("", "."):
        return str(pure_path.parent)
    return normalized


def compact_scope_suggestion(scopes: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if not scopes:
        return ()
    normalized = normalize_scopes(scopes)
    selected: list[str] = []
    for candidate in sorted(
        normalized,
        key=lambda item: (len(PurePosixPath(item).parts), item),
    ):
        candidate_parts = PurePosixPath(candidate).parts
        if any(
            scopes_overlap_for_inference(existing, candidate)
            and len(PurePosixPath(existing).parts) <= len(candidate_parts)
            for existing in selected
        ):
            continue
        selected = [
            existing
            for existing in selected
            if not (
                scopes_overlap_for_inference(existing, candidate)
                and len(candidate_parts) < len(PurePosixPath(existing).parts)
            )
        ]
        selected.append(candidate)
        if len(selected) >= MAX_SUGGESTED_DRIFT_SCOPES:
            break
    return tuple(selected)


def scopes_overlap_for_inference(left: str, right: str) -> bool:
    if left == right:
        return True
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    return (
        left_parts == right_parts[: len(left_parts)]
        or right_parts == left_parts[: len(right_parts)]
    )


def latest_recent_handoff(
    *,
    store: CoordinationStore,
    agent_id: str,
    is_stale_timestamp=is_stale_utc_timestamp,
) -> ContextRecord | None:
    handoffs = store.read_context(
        topic="session-handoff",
        agent_id=agent_id,
        limit=5,
    )
    for entry in handoffs:
        if not is_stale_timestamp(
            entry.created_at,
            stale_after_hours=RECENT_HANDOFF_WINDOW_HOURS,
        ):
            return entry
    return None


def active_work_started_at(
    *,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
) -> str | None:
    timestamps = [
        value
        for value in (
            None if claim is None else claim.created_at,
            None if intent is None else intent.created_at,
        )
        if value is not None
    ]
    if not timestamps:
        return None
    return max(timestamps, key=parse_utc_timestamp)


def agent_presence_is_stale(
    presence: AgentPresenceRecord,
    *,
    is_stale_timestamp=is_stale_utc_timestamp,
) -> bool:
    return is_stale_timestamp(presence.last_seen_at)


def agent_presence_has_expired_lease(
    presence: AgentPresenceRecord,
    *,
    is_past_timestamp=is_past_utc_timestamp,
) -> bool:
    active_records = tuple(
        record
        for record in (presence.claim, presence.intent)
        if record is not None and getattr(record, "status", "") == "active"
    )
    return any(
        bool(getattr(record, "lease_expires_at", None))
        and is_past_timestamp(str(getattr(record, "lease_expires_at")))
        for record in active_records
    )


def stale_agent_ids(
    agents: tuple[AgentPresenceRecord, ...],
    *,
    is_stale_timestamp=is_stale_utc_timestamp,
    is_past_timestamp=is_past_utc_timestamp,
) -> set[str]:
    return {
        presence.agent_id
        for presence in agents
        if (presence.claim is not None or presence.intent is not None)
        and (
            agent_presence_is_stale(presence, is_stale_timestamp=is_stale_timestamp)
            or agent_presence_has_expired_lease(presence, is_past_timestamp=is_past_timestamp)
        )
    }


def active_work_nearby_yield_alert(
    *,
    agent_id: str,
    claim: ClaimRecord | None,
    intent: IntentRecord | None,
    snapshot: object | None,
    store: CoordinationStore | None = None,
    stale_agent_ids: set[str] | None = None,
    is_stale_timestamp=is_stale_utc_timestamp,
    is_past_timestamp=is_past_utc_timestamp,
) -> dict[str, object] | None:
    if snapshot is None:
        return None
    has_yield_policy = any(
        normalize_lease_policy(getattr(record, "lease_policy", None), allow_none=True) == "yield"
        for record in (claim, intent)
        if record is not None and getattr(record, "lease_expires_at", None)
    )
    if not has_yield_policy:
        return None
    active_scope = active_scope_for_worktree(claim=claim, intent=intent)
    if not active_scope:
        return None
    active_started_at = active_work_started_at(claim=claim, intent=intent)
    active_refs = tuple(
        reference
        for reference in (
            None if claim is None else ("claim", claim.id),
            None if intent is None else ("intent", intent.id),
        )
        if reference is not None
    )

    nearby: list[dict[str, object]] = []
    for kind, records in (
        ("claim", tuple(getattr(snapshot, "claims", ()))),
        ("intent", tuple(getattr(snapshot, "intents", ()))),
    ):
        for record in records:
            record_agent_id = str(getattr(record, "agent_id", "")).strip()
            if not record_agent_id or record_agent_id == agent_id:
                continue
            if stale_agent_ids is not None and record_agent_id in stale_agent_ids:
                continue
            if str(getattr(record, "status", "")).strip() != "active":
                continue
            if bool(getattr(record, "lease_expires_at", None)) and is_past_timestamp(
                str(getattr(record, "lease_expires_at"))
            ):
                continue
            record_scope = tuple(str(item) for item in getattr(record, "scope", ()))
            overlap = overlapping_scopes(record_scope, active_scope)
            dependency_scope: tuple[str, ...] = ()
            if not overlap and store is not None:
                dependency_scope = store.dependency_scope_between_scopes(active_scope, record_scope)
            if not overlap and not dependency_scope:
                continue
            direct_overlap = any(item in record_scope for item in overlap)
            relationship = "dependency" if dependency_scope else "scope"
            related_scope = tuple(str(item) for item in (dependency_scope or overlap))
            acknowledged_conflict = None
            if store is not None and active_refs:
                acknowledged_conflict = store.latest_resolved_conflict_between_references(
                    left_refs=active_refs,
                    right_refs=((kind, str(getattr(record, "id", ""))),),
                )
            acknowledged = acknowledged_conflict is not None
            resolved_at = (
                None
                if acknowledged_conflict is None
                else str(acknowledged_conflict.resolved_at or "").strip() or None
            )
            record_created_at = str(getattr(record, "created_at", "")).strip()
            urgency = "ongoing"
            if record_created_at:
                if active_started_at is not None and parse_utc_timestamp(record_created_at) >= parse_utc_timestamp(
                    active_started_at
                ):
                    urgency = "fresh"
                elif not is_stale_timestamp(
                    record_created_at,
                    stale_after_hours=NEARBY_YIELD_FRESH_HOURS,
                ):
                    urgency = "fresh"
            risk = (
                "high"
                if kind == "intent" or relationship == "dependency"
                else "medium"
                if direct_overlap
                else "low"
            )
            nearby.append(
                {
                    "kind": kind,
                    "id": str(getattr(record, "id", "")),
                    "agent_id": record_agent_id,
                    "description": str(getattr(record, "description", kind)),
                    "relationship": relationship,
                    "overlap_scope": related_scope,
                    "acknowledged": acknowledged,
                    "resolved_at": resolved_at,
                    "urgency": urgency,
                    "risk": risk,
                }
            )
    actionable_nearby = tuple(item for item in nearby if str(item.get("risk", "")) != "low")
    if not actionable_nearby:
        return None

    def _nearby_priority(item: dict[str, object]) -> tuple[int, int, int, int, str, str]:
        risk = str(item.get("risk", ""))
        acknowledged = bool(item.get("acknowledged", False))
        urgency = str(item.get("urgency", ""))
        relationship = str(item.get("relationship", ""))
        kind = str(item.get("kind", ""))
        risk_rank = 0 if risk == "high" else 1
        acknowledged_rank = 1 if acknowledged else 0
        urgency_rank = 0 if urgency == "fresh" else 1
        relationship_rank = 0 if relationship == "dependency" else 1
        kind_rank = 0 if kind == "intent" else 1
        return (
            risk_rank,
            acknowledged_rank,
            urgency_rank,
            relationship_rank,
            kind_rank,
            str(item.get("agent_id", "")),
            str(item.get("id", "")),
        )

    nearby = sorted(
        actionable_nearby,
        key=_nearby_priority,
    )
    top_item = nearby[0]
    top_risk = str(top_item.get("risk", ""))
    top_acknowledged = bool(top_item.get("acknowledged", False))
    top_urgency = str(top_item.get("urgency", ""))
    if top_acknowledged:
        if top_risk == "high" and top_urgency == "fresh":
            confidence = "medium"
        else:
            confidence = "low"
    elif top_risk == "high" and top_urgency == "fresh":
        confidence = "high"
    elif top_risk == "high" or top_urgency == "fresh":
        confidence = "medium"
    else:
        confidence = "low"
    if len(nearby) == 1:
        subject = f"{nearby[0]['kind']} {nearby[0]['id']} from {nearby[0]['agent_id']}"
    else:
        subject = f"{len(nearby)} nearby active work item(s)"
    top_relationship = str(top_item.get("relationship", ""))
    if top_acknowledged:
        timing_phrase = (
            "fresh acknowledged nearby active work"
            if top_urgency == "fresh"
            else "acknowledged nearby active work that is still live"
        )
    else:
        timing_phrase = (
            "fresh nearby active work"
            if top_urgency == "fresh"
            else "longer-running nearby active work"
        )
    reason = (
        f"Loom found {timing_phrase}: {subject} is semantically entangled with the current leased work."
        if top_relationship == "dependency"
        else f"Loom found {timing_phrase}: {subject} overlaps the current leased work scope."
    )
    return {
        "policy": "yield",
        "nearby": tuple(nearby[:5]),
        "acknowledged": top_acknowledged,
        "urgency": top_urgency,
        "summary": "Yield the current leased work because other agents are active nearby.",
        "next_step": "loom finish",
        "tool_name": "loom_finish",
        "tool_arguments": {"agent_id": agent_id},
        "reason": reason,
        "confidence": confidence,
    }


def repo_lanes_payload(
    *,
    agents: tuple[AgentPresenceRecord, ...],
    snapshot: object | None,
    store: CoordinationStore | None,
    stale_agent_ids: set[str] | None = None,
    is_stale_timestamp=is_stale_utc_timestamp,
    is_past_timestamp=is_past_utc_timestamp,
) -> dict[str, object]:
    empty_payload = {
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
    if snapshot is None or store is None or not agents:
        return empty_payload

    def _urgency_rank(value: str) -> int:
        return 0 if value == "fresh" else 1

    def _confidence_rank(value: str) -> int:
        if value == "high":
            return 0
        if value == "medium":
            return 1
        return 2

    def _merge_urgency(left: str, right: str) -> str:
        return left if _urgency_rank(left) <= _urgency_rank(right) else right

    def _merge_confidence(left: str, right: str) -> str:
        return left if _confidence_rank(left) <= _confidence_rank(right) else right

    def _lane_confidence(*, relationship: str, kind: str, urgency: str) -> str:
        is_high_risk = kind == "intent" or relationship == "dependency"
        return "medium" if is_high_risk and urgency == "fresh" else "low"

    def _program_scope_hint(scope: tuple[str, ...]) -> str | None:
        roots: list[tuple[str, ...]] = []
        for item in scope:
            candidate = worktree_scope_candidate(str(item))
            parts = PurePosixPath(candidate).parts
            if parts:
                roots.append(parts)
        if not roots:
            return None
        if len(roots) == 1:
            parts = roots[0]
            if len(parts) >= 2:
                return "/".join(parts[:2])
            return None
        prefix: list[str] = []
        for index, value in enumerate(roots[0]):
            if all(len(parts) > index and parts[index] == value for parts in roots[1:]):
                prefix.append(value)
            else:
                break
        if len(prefix) >= 2:
            return "/".join(prefix)
        return None

    agent_index: dict[str, dict[str, object]] = {}
    lane_index: dict[tuple[object, ...], dict[str, object]] = {}
    for presence in agents:
        if stale_agent_ids is not None and presence.agent_id in stale_agent_ids:
            continue
        alert = active_work_nearby_yield_alert(
            agent_id=presence.agent_id,
            claim=presence.claim,
            intent=presence.intent,
            snapshot=snapshot,
            store=store,
            stale_agent_ids=stale_agent_ids,
            is_stale_timestamp=is_stale_timestamp,
            is_past_timestamp=is_past_timestamp,
        )
        if not isinstance(alert, dict):
            continue
        acknowledged_nearby = tuple(
            item
            for item in tuple(alert.get("nearby", ()))
            if isinstance(item, dict) and bool(item.get("acknowledged", False))
        )
        if not acknowledged_nearby:
            continue
        agent_urgency = str(alert.get("urgency", "")).strip() or "ongoing"
        agent_confidence = str(alert.get("confidence", "")).strip() or "low"
        existing_agent = agent_index.get(presence.agent_id)
        if existing_agent is None:
            agent_index[presence.agent_id] = {
                "agent_id": presence.agent_id,
                "urgency": agent_urgency,
                "confidence": agent_confidence,
            }
        else:
            existing_agent["urgency"] = _merge_urgency(
                str(existing_agent.get("urgency", "ongoing")),
                agent_urgency,
            )
            existing_agent["confidence"] = _merge_confidence(
                str(existing_agent.get("confidence", "low")),
                agent_confidence,
            )
        for item in acknowledged_nearby:
            relationship = str(item.get("relationship", "")).strip() or "scope"
            raw_scope = tuple(str(scope) for scope in item.get("overlap_scope", ()))
            lane_scope = compact_scope_suggestion(raw_scope)
            if not lane_scope:
                lane_scope = compact_scope_suggestion(
                    active_scope_for_worktree(
                        claim=presence.claim,
                        intent=presence.intent,
                    )
                )
            if not lane_scope:
                continue
            lane_key = (relationship, lane_scope)
            lane = lane_index.get(lane_key)
            item_urgency = str(item.get("urgency", "")).strip() or "ongoing"
            item_confidence = _lane_confidence(
                relationship=relationship,
                kind=str(item.get("kind", "")).strip() or "claim",
                urgency=item_urgency,
            )
            if lane is None:
                lane = {
                    "scope": lane_scope,
                    "relationship": relationship,
                    "urgency": item_urgency,
                    "confidence": item_confidence,
                    "_agents": set(),
                }
                lane_index[lane_key] = lane
            else:
                lane["urgency"] = _merge_urgency(
                    str(lane.get("urgency", "ongoing")),
                    item_urgency,
                )
                lane["confidence"] = _merge_confidence(
                    str(lane.get("confidence", "low")),
                    item_confidence,
                )
            lane_agents = lane["_agents"]
            assert isinstance(lane_agents, set)
            lane_agents.add(presence.agent_id)
            nearby_agent_id = str(item.get("agent_id", "")).strip()
            if nearby_agent_id:
                lane_agents.add(nearby_agent_id)

    if not lane_index:
        return empty_payload

    lanes: list[dict[str, object]] = []
    for lane in lane_index.values():
        lane_agents = sorted(
            str(agent_id)
            for agent_id in lane.pop("_agents")
        )
        lanes.append(
            {
                "scope": tuple(str(scope) for scope in lane["scope"]),
                "relationship": str(lane["relationship"]),
                "urgency": str(lane["urgency"]),
                "confidence": str(lane["confidence"]),
                "participant_count": len(lane_agents),
                "agents": tuple(lane_agents),
            }
        )
    lanes.sort(
        key=lambda item: (
            _urgency_rank(str(item.get("urgency", "ongoing"))),
            _confidence_rank(str(item.get("confidence", "low"))),
            0 if str(item.get("relationship", "scope")) == "dependency" else 1,
            -int(item.get("participant_count", 0)),
            tuple(str(scope) for scope in item.get("scope", ())),
        )
    )
    lane_agents = sorted(
        (
            {
                "agent_id": str(item["agent_id"]),
                "urgency": str(item["urgency"]),
                "confidence": str(item["confidence"]),
            }
            for item in agent_index.values()
        ),
        key=lambda item: (
            _urgency_rank(str(item.get("urgency", "ongoing"))),
            _confidence_rank(str(item.get("confidence", "low"))),
            str(item.get("agent_id", "")),
        ),
    )
    fresh_count = sum(1 for item in lanes if str(item.get("urgency", "")) == "fresh")
    ongoing_count = sum(1 for item in lanes if str(item.get("urgency", "")) != "fresh")

    program_index: dict[str, dict[str, object]] = {}
    for lane in lanes:
        lane_scope = tuple(str(scope) for scope in lane.get("scope", ()))
        scope_hint = _program_scope_hint(lane_scope)
        key = (
            scope_hint
            if scope_hint is not None
            else f"{str(lane.get('relationship', 'scope'))}:{'|'.join(lane_scope)}"
        )
        program = program_index.get(key)
        if program is None:
            program = {
                "scope_hint": scope_hint,
                "urgency": str(lane.get("urgency", "ongoing")),
                "confidence": str(lane.get("confidence", "low")),
                "_relationships": {str(lane.get("relationship", "scope"))},
                "_agents": set(str(agent_id) for agent_id in lane.get("agents", ())),
                "_lane_scopes": {lane_scope},
                "lane_count": 1,
            }
            program_index[key] = program
        else:
            program["urgency"] = _merge_urgency(
                str(program.get("urgency", "ongoing")),
                str(lane.get("urgency", "ongoing")),
            )
            program["confidence"] = _merge_confidence(
                str(program.get("confidence", "low")),
                str(lane.get("confidence", "low")),
            )
            relationships = program["_relationships"]
            agents = program["_agents"]
            lane_scopes = program["_lane_scopes"]
            assert isinstance(relationships, set)
            assert isinstance(agents, set)
            assert isinstance(lane_scopes, set)
            relationships.add(str(lane.get("relationship", "scope")))
            agents.update(str(agent_id) for agent_id in lane.get("agents", ()))
            lane_scopes.add(lane_scope)
            program["lane_count"] = int(program.get("lane_count", 0)) + 1

    programs: list[dict[str, object]] = []
    for program in program_index.values():
        program_scopes = sorted(
            tuple(str(scope) for scope in lane_scope)
            for lane_scope in program.pop("_lane_scopes")
        )
        program_agents = sorted(
            str(agent_id)
            for agent_id in program.pop("_agents")
        )
        program_relationships = sorted(
            str(relationship)
            for relationship in program.pop("_relationships")
        )
        programs.append(
            {
                "scope_hint": program.get("scope_hint"),
                "urgency": str(program["urgency"]),
                "confidence": str(program["confidence"]),
                "lane_count": int(program["lane_count"]),
                "participant_count": len(program_agents),
                "relationships": tuple(program_relationships),
                "agents": tuple(program_agents),
                "lane_scopes": tuple(program_scopes),
            }
        )
    programs.sort(
        key=lambda item: (
            _urgency_rank(str(item.get("urgency", "ongoing"))),
            _confidence_rank(str(item.get("confidence", "low"))),
            -int(item.get("lane_count", 0)),
            -int(item.get("participant_count", 0)),
            "" if item.get("scope_hint") is None else str(item.get("scope_hint")),
        )
    )
    fresh_program_count = sum(1 for item in programs if str(item.get("urgency", "")) == "fresh")
    ongoing_program_count = sum(1 for item in programs if str(item.get("urgency", "")) != "fresh")
    return {
        "acknowledged_migration_lanes": len(lanes),
        "fresh_acknowledged_migration_lanes": fresh_count,
        "ongoing_acknowledged_migration_lanes": ongoing_count,
        "acknowledged_migration_programs": len(programs),
        "fresh_acknowledged_migration_programs": fresh_program_count,
        "ongoing_acknowledged_migration_programs": ongoing_program_count,
        "agents": tuple(lane_agents[:5]),
        "lanes": tuple(lanes[:5]),
        "programs": tuple(programs[:5]),
    }
