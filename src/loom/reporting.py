from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path

from . import __version__
from .daemon import DaemonStatus
from .local_store import (
    AgentPresenceRecord,
    ClaimRecord,
    ConflictRecord,
    ContextRecord,
    EventRecord,
    IntentRecord,
    StatusSnapshot,
)
from .util import (
    ACTIVE_RECORD_STALE_AFTER_HOURS,
    is_past_utc_timestamp,
    is_stale_utc_timestamp,
    json_ready,
    utc_now,
)


@dataclass(frozen=True)
class ScopeHotspot:
    scope: str
    status: str
    score: int
    claim_count: int
    intent_count: int
    context_count: int
    conflict_count: int
    agents: tuple[str, ...]


def build_coordination_report(
    *,
    project_root: Path,
    daemon_status: DaemonStatus,
    status_snapshot: StatusSnapshot,
    agents: tuple[AgentPresenceRecord, ...],
    recent_events: tuple[EventRecord, ...],
) -> dict[str, object]:
    live_active_agents, stale_active_agents, idle_agents = _partition_agents_by_activity(agents)
    active_agents = live_active_agents + stale_active_agents
    hotspots = summarize_scope_hotspots(status_snapshot)
    return {
        "generated_at": utc_now(),
        "loom_version": __version__,
        "project_root": str(project_root),
        "daemon": {
            "running": daemon_status.running,
            "detail": daemon_status.describe(),
            "pid": daemon_status.pid,
            "started_at": daemon_status.started_at,
        },
        "summary": {
            "active_claims": len(status_snapshot.claims),
            "active_intents": len(status_snapshot.intents),
            "recent_context": len(status_snapshot.context),
            "active_conflicts": len(status_snapshot.conflicts),
            "known_agents": len(agents),
            "active_agents": len(active_agents),
            "live_active_agents": len(live_active_agents),
            "stale_active_agents": len(stale_active_agents),
            "idle_agents": len(idle_agents),
            "stale_after_hours": ACTIVE_RECORD_STALE_AFTER_HOURS,
            "hotspots": len(hotspots),
            "recent_events": len(recent_events),
        },
        "active_agents": [json_ready(agent) for agent in active_agents],
        "live_active_agents": [json_ready(agent) for agent in live_active_agents],
        "stale_active_agents": [json_ready(agent) for agent in stale_active_agents],
        "idle_agents": [json_ready(agent) for agent in idle_agents],
        "hotspots": [json_ready(hotspot) for hotspot in hotspots],
        "conflicts": [json_ready(conflict) for conflict in status_snapshot.conflicts],
        "recent_context": [json_ready(entry) for entry in status_snapshot.context],
        "recent_events": [json_ready(event) for event in recent_events],
    }


def summarize_scope_hotspots(
    status_snapshot: StatusSnapshot,
) -> tuple[ScopeHotspot, ...]:
    claim_agents = {claim.id: claim.agent_id for claim in status_snapshot.claims}
    intent_agents = {intent.id: intent.agent_id for intent in status_snapshot.intents}
    context_agents = {entry.id: entry.agent_id for entry in status_snapshot.context}

    buckets: dict[str, dict[str, object]] = {}

    def ensure_bucket(scope: str) -> dict[str, object]:
        bucket = buckets.get(scope)
        if bucket is None:
            bucket = {
                "claim_count": 0,
                "intent_count": 0,
                "context_count": 0,
                "conflict_count": 0,
                "agents": set(),
            }
            buckets[scope] = bucket
        return bucket

    def add_record_scopes(
        *,
        scope_values: tuple[str, ...],
        agent_id: str | None,
        field: str,
    ) -> None:
        for scope in _scopes_or_repo(scope_values):
            bucket = ensure_bucket(scope)
            bucket[field] = int(bucket[field]) + 1
            if agent_id:
                cast_agents = bucket["agents"]
                assert isinstance(cast_agents, set)
                cast_agents.add(agent_id)

    for claim in status_snapshot.claims:
        add_record_scopes(scope_values=claim.scope, agent_id=claim.agent_id, field="claim_count")
    for intent in status_snapshot.intents:
        add_record_scopes(scope_values=intent.scope, agent_id=intent.agent_id, field="intent_count")
    for entry in status_snapshot.context:
        add_record_scopes(scope_values=entry.scope, agent_id=entry.agent_id, field="context_count")

    for conflict in status_snapshot.conflicts:
        for scope in _scopes_or_repo(conflict.scope):
            bucket = ensure_bucket(scope)
            bucket["conflict_count"] = int(bucket["conflict_count"]) + 1
            for agent_id in _conflict_agent_ids(
                conflict,
                claim_agents=claim_agents,
                intent_agents=intent_agents,
                context_agents=context_agents,
            ):
                cast_agents = bucket["agents"]
                assert isinstance(cast_agents, set)
                cast_agents.add(agent_id)

    hotspots = [
        ScopeHotspot(
            scope=scope,
            status=_hotspot_status(
                conflict_count=int(bucket["conflict_count"]),
                intent_count=int(bucket["intent_count"]),
                claim_count=int(bucket["claim_count"]),
                context_count=int(bucket["context_count"]),
            ),
            score=_hotspot_score(
                conflict_count=int(bucket["conflict_count"]),
                intent_count=int(bucket["intent_count"]),
                claim_count=int(bucket["claim_count"]),
                context_count=int(bucket["context_count"]),
            ),
            claim_count=int(bucket["claim_count"]),
            intent_count=int(bucket["intent_count"]),
            context_count=int(bucket["context_count"]),
            conflict_count=int(bucket["conflict_count"]),
            agents=tuple(sorted(str(agent_id) for agent_id in bucket["agents"])),
        )
        for scope, bucket in buckets.items()
    ]
    return tuple(
        sorted(
            hotspots,
            key=lambda item: (
                -item.score,
                -item.conflict_count,
                -item.intent_count,
                -item.claim_count,
                item.scope,
            ),
        )
    )


def _partition_agents_by_activity(
    agents: tuple[AgentPresenceRecord, ...],
) -> tuple[tuple[AgentPresenceRecord, ...], tuple[AgentPresenceRecord, ...], tuple[AgentPresenceRecord, ...]]:
    live_active: list[AgentPresenceRecord] = []
    stale_active: list[AgentPresenceRecord] = []
    idle: list[AgentPresenceRecord] = []
    for presence in agents:
        if presence.claim is None and presence.intent is None:
            idle.append(presence)
            continue
        has_expired_lease = any(
            record is not None
            and getattr(record, "status", "") == "active"
            and bool(getattr(record, "lease_expires_at", None))
            and is_past_utc_timestamp(str(getattr(record, "lease_expires_at")))
            for record in (presence.claim, presence.intent)
        )
        if has_expired_lease or is_stale_utc_timestamp(
            presence.last_seen_at,
            stale_after_hours=ACTIVE_RECORD_STALE_AFTER_HOURS,
        ):
            stale_active.append(presence)
        else:
            live_active.append(presence)
    return tuple(live_active), tuple(stale_active), tuple(idle)


def render_coordination_report_html(report: dict[str, object]) -> str:
    summary = report.get("summary", {})
    daemon = report.get("daemon", {})
    hotspots = [item for item in report.get("hotspots", []) if isinstance(item, dict)]
    conflicts = [item for item in report.get("conflicts", []) if isinstance(item, dict)]
    live_active_agents = [
        item for item in report.get("live_active_agents", []) if isinstance(item, dict)
    ]
    stale_active_agents = [
        item for item in report.get("stale_active_agents", []) if isinstance(item, dict)
    ]
    recent_events = [
        item for item in report.get("recent_events", []) if isinstance(item, dict)
    ]
    recent_context = [
        item for item in report.get("recent_context", []) if isinstance(item, dict)
    ]
    max_score = max((int(item.get("score", 0)) for item in hotspots), default=0)
    raw_json = escape(
        json.dumps(json_ready(report), indent=2, sort_keys=True, ensure_ascii=False),
        quote=False,
    )
    hotspots_html = "".join(_render_hotspot_card(item, max_score=max_score) for item in hotspots)
    live_agents_html = "".join(_render_agent_card(agent, tone="live") for agent in live_active_agents)
    stale_agents_html = "".join(
        _render_agent_card(agent, tone="stale") for agent in stale_active_agents
    )
    conflicts_html = "".join(_render_conflict_item(conflict) for conflict in conflicts)
    context_html = "".join(_render_context_item(entry) for entry in recent_context)
    events_html = "".join(_render_event_item(event) for event in recent_events)

    hotspots_block = (
        f"""
        <section>
          <h2>Scope Heat</h2>
          <div class="tile-grid heat-grid">
            {hotspots_html}
          </div>
        </section>
        """
        if hotspots_html
        else ""
    )
    live_agents_block = (
        f"""
        <section>
          <h2>Live Active Agents</h2>
          <div class="agent-grid">{live_agents_html}</div>
        </section>
        """
        if live_agents_html
        else ""
    )
    stale_agents_block = (
        f"""
        <section>
          <h2>Stale Active Records</h2>
          <p class="lede" style="margin-top:0;">These agents still have active claims or intents, but their last seen timestamps are older than {escape(str(summary.get('stale_after_hours', ACTIVE_RECORD_STALE_AFTER_HOURS)))} hours.</p>
          <div class="agent-grid">{stale_agents_html}</div>
        </section>
        """
        if stale_agents_html
        else ""
    )
    conflicts_block = (
        f"""
        <section>
          <h2>Active Conflicts</h2>
          <div class="stack">{conflicts_html}</div>
        </section>
        """
        if conflicts_html
        else ""
    )
    context_block = (
        f"""
        <section>
          <h2>Recent Context</h2>
          <div class="stack">{context_html}</div>
        </section>
        """
        if context_html
        else ""
    )
    events_block = (
        f"""
        <section>
          <h2>Recent Events</h2>
          <div class="stack">{events_html}</div>
        </section>
        """
        if events_html
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Loom Coordination Report</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;1,300&family=Syne:wght@400;500;600;700;800&family=JetBrains+Mono:wght@300;400&display=swap" rel="stylesheet">
  <style>
    :root {{
      color-scheme: dark;
      --black: #000000;
      --obsidian: #0a0a0a;
      --teal: #4dd4a8;
      --teal-deep: #0e7a5e;
      --teal-dark: #043828;
      --teal-glow: rgba(77, 212, 168, 0.12);
      --teal-ghost: rgba(77, 212, 168, 0.04);
      --text-1: rgba(245, 245, 247, 0.88);
      --text-2: rgba(245, 245, 247, 0.45);
      --text-3: rgba(245, 245, 247, 0.18);
      --line: rgba(245, 245, 247, 0.08);
      --red: #f17b7b;
      --red-soft: rgba(241, 123, 123, 0.16);
      --blue: #7fd8ff;
      --blue-soft: rgba(127, 216, 255, 0.14);
      --amber: #f0b25c;
      --amber-soft: rgba(240, 178, 92, 0.14);
      --font-display: "Syne", system-ui, sans-serif;
      --font-body: "DM Sans", system-ui, sans-serif;
      --font-mono: "JetBrains Mono", monospace;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      font-family: var(--font-body);
      font-weight: 300;
      color: var(--text-1);
      background:
        radial-gradient(circle at top center, rgba(77, 212, 168, 0.14), transparent 32rem),
        radial-gradient(circle at right center, rgba(77, 212, 168, 0.08), transparent 26rem),
        linear-gradient(180deg, #060909 0%, #000000 100%);
      overflow-x: hidden;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }}
    main {{
      max-width: 78rem;
      margin: 0 auto;
      padding: 2.75rem 1.25rem 4rem;
      position: relative;
    }}
    h1, h2 {{
      margin: 0 0 0.8rem;
      font-family: var(--font-display);
      font-weight: 700;
      letter-spacing: -0.03em;
    }}
    h1 {{
      font-size: clamp(2.7rem, 6vw, 4.9rem);
      line-height: 0.92;
      max-width: 14ch;
    }}
    p {{
      line-height: 1.5;
      color: var(--text-2);
      overflow-wrap: anywhere;
    }}
    .lede {{
      max-width: 42rem;
      margin: 0.85rem 0 1.75rem;
      font-size: 1.05rem;
    }}
    .meta, .agent-grid, .tile-grid {{
      display: grid;
      gap: 0.9rem;
      grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
    }}
    .agent-grid {{
      grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr));
    }}
    .heat-grid {{
      grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
    }}
    .panel, .card {{
      background: linear-gradient(180deg, rgba(10, 10, 10, 0.94), rgba(5, 12, 10, 0.92));
      border: 1px solid var(--line);
      border-radius: 1rem;
      box-shadow: 0 0.5rem 1.6rem rgba(0, 0, 0, 0.25);
      backdrop-filter: blur(10px);
      min-width: 0;
      overflow: hidden;
    }}
    .card {{
      padding: 1rem 1.05rem 1.05rem;
    }}
    .label {{
      display: block;
      color: var(--teal);
      font-family: var(--font-mono);
      font-size: 0.7rem;
      text-transform: uppercase;
      letter-spacing: 0.18em;
      margin-bottom: 0.3rem;
      overflow-wrap: anywhere;
    }}
    .value {{
      font-size: clamp(1.2rem, 2vw, 1.6rem);
      font-family: var(--font-display);
      font-weight: 700;
      line-height: 1.08;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    section {{
      margin-top: 2rem;
    }}
    .scope-name {{
      font-family: var(--font-display);
      font-weight: 700;
      font-size: 1.15rem;
      color: var(--text-1);
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .tag {{
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      border-radius: 999px;
      padding: 0.25rem 0.55rem;
      font-size: 0.72rem;
      font-weight: 500;
      font-family: var(--font-mono);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      max-width: 100%;
      overflow-wrap: anywhere;
    }}
    .tag.active {{
      background: var(--teal-glow);
      color: var(--teal);
    }}
    .tag.context {{
      background: var(--blue-soft);
      color: var(--blue);
    }}
    .tag.conflict {{
      background: var(--red-soft);
      color: var(--red);
    }}
    .tag.stale {{
      background: var(--amber-soft);
      color: var(--amber);
    }}
    .heat-shell {{
      min-width: 0;
      height: 0.7rem;
      background: rgba(255, 255, 255, 0.06);
      border-radius: 999px;
      overflow: hidden;
      margin-top: 0.35rem;
    }}
    .heat-bar {{
      height: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--teal-deep), var(--teal));
    }}
    .heat-bar.context {{
      background: linear-gradient(90deg, var(--blue), #b3edff);
    }}
    .heat-bar.conflict {{
      background: linear-gradient(90deg, #ff9c9c, var(--red));
    }}
    .signal-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
    }}
    .signal {{
      padding: 0.2rem 0.45rem;
      border-radius: 0.6rem;
      background: rgba(255, 255, 255, 0.05);
      color: var(--text-2);
      font-size: 0.8rem;
      overflow-wrap: anywhere;
    }}
    strong {{
      font-weight: 500;
      color: var(--text-1);
    }}
    .stack {{
      display: grid;
      gap: 0.8rem;
      grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
    }}
    .stack .card p {{
      margin: 0.4rem 0 0;
    }}
    .muted {{
      color: var(--text-2);
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .meta .card,
    .agent-grid .card,
    .stack .card,
    .tile-grid .card {{
      min-width: 0;
    }}
    .meta .card *,
    .agent-grid .card *,
    .stack .card *,
    .tile-grid .card * {{
      min-width: 0;
    }}
    .card p,
    .card .value,
    .card .scope-name,
    .card .mono,
    .card .agents-list,
    .card .signal,
    .card .label {{
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .row {{
      display: flex;
      justify-content: space-between;
      gap: 0.8rem;
      align-items: flex-start;
      margin-top: 0.7rem;
    }}
    .row > * {{
      min-width: 0;
      flex: 1 1 0;
    }}
    .mono {{
      font-family: var(--font-mono);
      font-size: 0.78rem;
      color: var(--text-2);
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    .heat-score {{
      font-family: var(--font-mono);
      font-size: 0.82rem;
      color: var(--text-2);
      margin-bottom: 0.15rem;
    }}
    .agents-list {{
      margin-top: 0.75rem;
      color: var(--text-2);
      font-size: 0.92rem;
      overflow-wrap: anywhere;
      word-break: break-word;
    }}
    pre {{
      overflow: auto;
      background: #07100e;
      color: #dbfff4;
      border: 1px solid var(--line);
      padding: 1rem;
      border-radius: 1rem;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    details {{
      margin-top: 2rem;
    }}
    summary {{
      cursor: pointer;
      color: var(--text-2);
    }}
    @media (max-width: 760px) {{
      main {{
        padding: 1.8rem 1rem 3rem;
      }}
      .meta,
      .agent-grid,
      .tile-grid,
      .stack {{
        grid-template-columns: 1fr;
      }}
      .row {{
        flex-direction: column;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <h1>Loom Coordination Report</h1>
    <p class="lede">A self-contained local snapshot of what is active in this repo right now: who is working, where the hotspots are, and where coordination needs attention.</p>
    <section class="meta">
      <div class="card"><span class="label">Project</span><div class="value">{escape(str(report.get("project_root", "")))}</div></div>
      <div class="card"><span class="label">Generated</span><div class="value">{escape(str(report.get("generated_at", "")))}</div></div>
      <div class="card"><span class="label">Daemon</span><div class="value">{escape(str(daemon.get("detail", "")))}</div></div>
      <div class="card"><span class="label">Loom</span><div class="value">{escape(str(report.get("loom_version", "")))}</div></div>
      <div class="card"><span class="label">Live Active</span><div class="value">{escape(str(summary.get("live_active_agents", 0)))}</div></div>
      <div class="card"><span class="label">Stale Active</span><div class="value">{escape(str(summary.get("stale_active_agents", 0)))}</div></div>
      <div class="card"><span class="label">Hotspots</span><div class="value">{escape(str(summary.get("hotspots", 0)))}</div></div>
      <div class="card"><span class="label">Active Conflicts</span><div class="value">{escape(str(summary.get("active_conflicts", 0)))}</div></div>
      <div class="card"><span class="label">Recent Events</span><div class="value">{escape(str(summary.get("recent_events", 0)))}</div></div>
    </section>
    {hotspots_block}
    {live_agents_block}
    {stale_agents_block}
    {conflicts_block}
    {context_block}
    {events_block}
    <details>
      <summary>Raw JSON</summary>
      <pre>{raw_json}</pre>
    </details>
  </main>
</body>
</html>
"""


def _scopes_or_repo(scope_values: tuple[str, ...]) -> tuple[str, ...]:
    return scope_values or ("(repo)",)


def _hotspot_status(
    *,
    conflict_count: int,
    intent_count: int,
    claim_count: int,
    context_count: int,
) -> str:
    if conflict_count:
        return "conflict"
    if intent_count or claim_count:
        return "active"
    if context_count:
        return "context"
    return "active"


def _hotspot_score(
    *,
    conflict_count: int,
    intent_count: int,
    claim_count: int,
    context_count: int,
) -> int:
    return (conflict_count * 8) + (intent_count * 4) + (claim_count * 3) + (context_count * 2)


def _conflict_agent_ids(
    conflict: ConflictRecord,
    *,
    claim_agents: dict[str, str],
    intent_agents: dict[str, str],
    context_agents: dict[str, str],
) -> tuple[str, ...]:
    agent_ids: list[str] = []
    for object_type, object_id in (
        (conflict.object_type_a, conflict.object_id_a),
        (conflict.object_type_b, conflict.object_id_b),
    ):
        agent_id = _agent_for_object(
            object_type,
            object_id,
            claim_agents=claim_agents,
            intent_agents=intent_agents,
            context_agents=context_agents,
        )
        if agent_id and agent_id not in agent_ids:
            agent_ids.append(agent_id)
    return tuple(agent_ids)


def _agent_for_object(
    object_type: str,
    object_id: str,
    *,
    claim_agents: dict[str, str],
    intent_agents: dict[str, str],
    context_agents: dict[str, str],
) -> str | None:
    if object_type == "claim":
        return claim_agents.get(object_id)
    if object_type == "intent":
        return intent_agents.get(object_id)
    if object_type == "context":
        return context_agents.get(object_id)
    return None


def _render_hotspot_row(item: dict[str, object], *, max_score: int) -> str:
    score = int(item.get("score", 0))
    width = 100.0 if max_score <= 0 else max(6.0, (score / max_score) * 100.0)
    status = str(item.get("status", "active"))
    agents = item.get("agents", [])
    agents_text = ", ".join(str(agent) for agent in agents) if agents else "-"
    signals = [
        f"{item.get('claim_count', 0)} claim",
        f"{item.get('intent_count', 0)} intent",
        f"{item.get('context_count', 0)} context",
        f"{item.get('conflict_count', 0)} conflict",
    ]
    signals_html = "".join(
        f"<span class=\"signal\">{escape(signal)}</span>" for signal in signals
    )
    return (
        "<tr>"
        f"<td><div class=\"scope-name\">{escape(str(item.get('scope', '')))}</div></td>"
        f"<td><span class=\"tag {escape(status)}\">{escape(status)}</span></td>"
        f"<td>{escape(agents_text)}</td>"
        f"<td><div>{escape(str(score))}</div><div class=\"heat-shell\"><div class=\"heat-bar {escape(status)}\" style=\"width: {width:.1f}%\"></div></div></td>"
        f"<td><div class=\"signal-list\">{signals_html}</div></td>"
        "</tr>"
    )


def _render_hotspot_card(item: dict[str, object], *, max_score: int) -> str:
    score = int(item.get("score", 0))
    width = 100.0 if max_score <= 0 else max(6.0, (score / max_score) * 100.0)
    status = str(item.get("status", "active"))
    agents = item.get("agents", [])
    agents_text = ", ".join(str(agent) for agent in agents) if agents else "-"
    signals = [
        f"{item.get('claim_count', 0)} claim",
        f"{item.get('intent_count', 0)} intent",
        f"{item.get('context_count', 0)} context",
        f"{item.get('conflict_count', 0)} conflict",
    ]
    signals_html = "".join(f"<span class=\"signal\">{escape(signal)}</span>" for signal in signals)
    return (
        "<article class=\"card\">"
        f"<span class=\"tag {escape(status)}\">{escape(status)}</span>"
        f"<p class=\"scope-name\">{escape(str(item.get('scope', '')))}</p>"
        f"<div class=\"row\">"
        f"<div><div class=\"heat-score\">Heat {escape(str(score))}</div>"
        f"<div class=\"heat-shell\"><div class=\"heat-bar {escape(status)}\" style=\"width: {width:.1f}%\"></div></div></div>"
        f"<div class=\"mono\">{len(agents)} agent(s)</div>"
        "</div>"
        f"<div class=\"agents-list\">Agents: {escape(agents_text)}</div>"
        f"<div class=\"signal-list\" style=\"margin-top:0.75rem;\">{signals_html}</div>"
        "</article>"
    )


def _render_agent_card(agent: dict[str, object], *, tone: str) -> str:
    claim = agent.get("claim")
    intent = agent.get("intent")
    claim_text = "none"
    claim_lease_text = ""
    if isinstance(claim, dict):
        claim_text = str(claim.get("description", "claim"))
        claim_lease = claim.get("lease_expires_at")
        claim_policy = str(claim.get("lease_policy", "")).strip()
        if isinstance(claim_lease, str) and claim_lease:
            suffix = " (expired)" if is_past_utc_timestamp(claim_lease) else ""
            policy_suffix = f" [policy: {claim_policy}]" if claim_policy else ""
            claim_lease_text = (
                f"<p class=\"muted\">Claim lease: {escape(claim_lease)}{escape(suffix)}"
                f"{escape(policy_suffix)}</p>"
            )
    intent_text = "none"
    intent_lease_text = ""
    if isinstance(intent, dict):
        intent_text = str(intent.get("description", "intent"))
        intent_lease = intent.get("lease_expires_at")
        intent_policy = str(intent.get("lease_policy", "")).strip()
        if isinstance(intent_lease, str) and intent_lease:
            suffix = " (expired)" if is_past_utc_timestamp(intent_lease) else ""
            policy_suffix = f" [policy: {intent_policy}]" if intent_policy else ""
            intent_lease_text = (
                f"<p class=\"muted\">Intent lease: {escape(intent_lease)}{escape(suffix)}"
                f"{escape(policy_suffix)}</p>"
            )
    tone_tag = "stale" if tone == "stale" else "active"
    tone_label = "stale" if tone == "stale" else "live"
    return (
        "<div class=\"card\">"
        f"<span class=\"tag {tone_tag}\">{escape(tone_label)}</span>"
        f"<span class=\"label\">Agent</span><div class=\"value\">{escape(str(agent.get('agent_id', '')))}</div>"
        f"<p><strong>Claim:</strong> {escape(claim_text)}</p>"
        f"{claim_lease_text}"
        f"<p><strong>Intent:</strong> {escape(intent_text)}</p>"
        f"{intent_lease_text}"
        f"<p class=\"muted\">Last seen: {escape(str(agent.get('last_seen_at', '')))}</p>"
        "</div>"
    )


def _render_conflict_item(conflict: dict[str, object]) -> str:
    return (
        "<div class=\"card\">"
        f"<span class=\"tag conflict\">{escape(str(conflict.get('severity', 'conflict')))}</span>"
        f"<p><strong>{escape(str(conflict.get('summary', '')))}</strong></p>"
        f"<p class=\"muted\">Scope: {escape(', '.join(conflict.get('scope', []) or ['(none)']))}</p>"
        "</div>"
    )


def _render_context_item(entry: dict[str, object]) -> str:
    return (
        "<div class=\"card\">"
        f"<span class=\"label\">{escape(str(entry.get('agent_id', '')))}</span>"
        f"<div class=\"value\">{escape(str(entry.get('topic', '')))}</div>"
        f"<p>{escape(_format_body(str(entry.get('body', ''))))}</p>"
        f"<p class=\"muted\">Scope: {escape(', '.join(entry.get('scope', []) or ['(none)']))}</p>"
        "</div>"
    )


def _render_event_item(event: dict[str, object]) -> str:
    payload = event.get("payload", {})
    payload_text = ", ".join(
        f"{key}={value}" for key, value in sorted(payload.items())
    ) if isinstance(payload, dict) else ""
    return (
        "<div class=\"card\">"
        f"<span class=\"label\">{escape(str(event.get('timestamp', '')))}</span>"
        f"<div class=\"value\">{escape(str(event.get('type', '')))}</div>"
        f"<p><strong>Actor:</strong> {escape(str(event.get('actor_id', '')))}</p>"
        f"<p class=\"muted\">{escape(payload_text)}</p>"
        "</div>"
    )


def _format_body(body: str) -> str:
    return " ".join(part.strip() for part in body.splitlines() if part.strip()) or "(empty)"
