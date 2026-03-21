from __future__ import annotations

import time
from typing import Callable

from .cli_output import (
    print_context_entry,
    print_event,
    print_event_batch,
    print_inbox_snapshot,
)
from .client import CoordinationClient
from .guidance import inbox_attention_payload as guidance_inbox_attention_payload
from .local_store import EventRecord, InboxSnapshot
from .util import normalize_scopes


def _run_follow_loop(
    *,
    client: CoordinationClient,
    after_sequence: int,
    max_follow_items: int | None,
    poll_interval: float,
    follow_event_type: str | None,
    handle_event: Callable[[EventRecord], bool],
    read_poll_events: Callable[[int], tuple[EventRecord, ...]],
) -> int:
    last_sequence = after_sequence
    followed_items = 0

    def _record_event(event: EventRecord) -> bool:
        nonlocal last_sequence, followed_items
        last_sequence = event.sequence
        if not handle_event(event):
            return False
        followed_items += 1
        return True

    daemon_running = client.daemon_status().running
    if daemon_running:
        try:
            for event in client.follow_events(
                event_type=follow_event_type,
                after_sequence=last_sequence,
            ):
                _record_event(event)
                if max_follow_items is not None and followed_items >= max_follow_items:
                    break
            return 0
        except RuntimeError:
            daemon_running = False

    while max_follow_items is None or followed_items < max_follow_items:
        events = read_poll_events(last_sequence)
        if events:
            for event in events:
                _record_event(event)
                if max_follow_items is not None and followed_items >= max_follow_items:
                    break
            continue
        time.sleep(poll_interval)
    return 0


def read_event_batch(
    *,
    client: CoordinationClient,
    limit: int,
    event_type: str | None,
    after_sequence: int | None,
    ascending: bool,
) -> tuple[EventRecord, ...]:
    return client.read_events(
        limit=limit,
        event_type=event_type,
        after_sequence=after_sequence,
        ascending=ascending,
    )


def emit_inbox_follow_update(
    *,
    snapshot: InboxSnapshot,
    event: EventRecord,
    json_mode: bool,
    identity: dict[str, object],
    write_json_line: Callable[[dict[str, object]], None],
    identity_summary_printer: Callable[..., None],
) -> None:
    if json_mode:
        write_json_line(
            {
                "ok": True,
                "stream": "inbox",
                "phase": "update",
                "event": event,
                "identity": identity,
                "inbox": snapshot,
                "attention": guidance_inbox_attention_payload(
                    pending_context_count=len(snapshot.pending_context),
                    conflict_count=len(snapshot.conflicts),
                ),
            }
        )
        return

    print()
    print_inbox_snapshot(
        snapshot,
        heading=f"Inbox update after {event.type} [{event.id}]",
        identity=identity,
        identity_summary_printer=identity_summary_printer,
    )


def handle_log_follow(
    *,
    client: CoordinationClient,
    event_type: str | None,
    limit: int,
    poll_interval: float,
    max_follow_events: int | None,
    json_mode: bool,
    write_json_line: Callable[[dict[str, object]], None],
    daemon_status_payload: Callable[[object], dict[str, object]],
) -> int:
    initial_events = read_event_batch(
        client=client,
        limit=limit,
        event_type=event_type,
        after_sequence=None,
        ascending=False,
    )
    initial_events = tuple(reversed(initial_events))
    if json_mode:
        write_json_line(
            {
                "ok": True,
                "stream": "events",
                "phase": "snapshot",
                "daemon": daemon_status_payload(client.daemon_status()),
                "events": initial_events,
            }
        )
    else:
        print_event_batch(initial_events, heading="Recent events")

    def _handle_event(event: EventRecord) -> bool:
        if json_mode:
            write_json_line(
                {
                    "ok": True,
                    "stream": "events",
                    "phase": "event",
                    "event": event,
                }
            )
        else:
            print_event(event)
        return True

    return _run_follow_loop(
        client=client,
        after_sequence=initial_events[-1].sequence if initial_events else 0,
        max_follow_items=max_follow_events,
        poll_interval=poll_interval,
        follow_event_type=event_type,
        handle_event=_handle_event,
        read_poll_events=lambda last_sequence: read_event_batch(
            client=client,
            limit=limit,
            event_type=event_type,
            after_sequence=last_sequence,
            ascending=True,
        ),
    )


def handle_context_follow(
    *,
    client: CoordinationClient,
    topic: str | None,
    agent_id: str | None,
    scope: list[str],
    poll_interval: float,
    max_follow_entries: int | None,
    json_mode: bool,
    context_matches_filters: Callable[..., bool],
    write_json_line: Callable[[dict[str, object]], None],
) -> int:
    normalized_scope = normalize_scopes(scope)

    def _handle_event(event: EventRecord) -> bool:
        context_id = event.payload.get("context_id")
        if not context_id:
            return False
        entry = client.get_context_entry(context_id=context_id)
        if entry is None or not context_matches_filters(
            entry,
            topic=topic,
            agent_id=agent_id,
            scope=normalized_scope,
        ):
            return False
        if json_mode:
            write_json_line(
                {
                    "ok": True,
                    "stream": "context",
                    "phase": "entry",
                    "context": entry,
                }
            )
        else:
            print_context_entry(entry)
        return True

    return _run_follow_loop(
        client=client,
        after_sequence=client.store.latest_event_sequence(),
        max_follow_items=max_follow_entries,
        poll_interval=poll_interval,
        follow_event_type="context.published",
        handle_event=_handle_event,
        read_poll_events=lambda last_sequence: client.read_events(
            limit=None,
            event_type="context.published",
            after_sequence=last_sequence,
            ascending=True,
        ),
    )


def handle_inbox_follow(
    *,
    client: CoordinationClient,
    agent_id: str,
    context_limit: int,
    event_limit: int,
    poll_interval: float,
    max_follow_updates: int | None,
    json_mode: bool,
    initial_snapshot: InboxSnapshot,
    after_sequence: int,
    identity: dict[str, object],
    emit_inbox_update: Callable[..., None],
) -> int:
    last_snapshot = initial_snapshot

    def _handle_event(event: EventRecord) -> bool:
        nonlocal last_snapshot
        snapshot = client.read_inbox_snapshot(
            agent_id=agent_id,
            context_limit=context_limit,
            event_limit=event_limit,
        )
        if snapshot == last_snapshot:
            return False
        emit_inbox_update(
            snapshot=snapshot,
            event=event,
            json_mode=json_mode,
            identity=identity,
        )
        last_snapshot = snapshot
        return True

    return _run_follow_loop(
        client=client,
        after_sequence=after_sequence,
        max_follow_items=max_follow_updates,
        poll_interval=poll_interval,
        follow_event_type=None,
        handle_event=_handle_event,
        read_poll_events=lambda last_sequence: client.read_events(
            limit=None,
            event_type=None,
            after_sequence=last_sequence,
            ascending=True,
        ),
    )
