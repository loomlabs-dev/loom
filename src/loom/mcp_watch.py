from __future__ import annotations

import threading

from .mcp_resources import project_resource_uris as resource_project_resource_uris


def _next_retry_seconds(*, current: float, maximum: float) -> float:
    return min(maximum, current * 2.0)


def subscription_snapshot(server) -> tuple[str, ...]:
    with server._state_lock:
        return tuple(server._resource_subscriptions)


def watch_snapshot(server) -> dict[str, object]:
    with server._state_lock:
        watch_thread = server._watch_thread
        return {
            "active": watch_thread is not None and watch_thread.is_alive(),
            "thread_name": None if watch_thread is None else watch_thread.name,
            "state": server._watch_state,
            "last_sequence": server._watch_last_sequence,
            "last_error": server._watch_last_error,
        }


def set_watch_diagnostics(
    server,
    *,
    state: str | None = None,
    last_sequence: int | object,
    last_error: str | None | object,
    unchanged_sentinel: object,
    notify: bool = True,
) -> None:
    state_changed = False
    error_changed = False
    with server._state_lock:
        if state is not None and state != server._watch_state:
            server._watch_state = state
            state_changed = True
        if last_sequence is not unchanged_sentinel:
            server._watch_last_sequence = None if last_sequence is None else int(last_sequence)
        if last_error is not unchanged_sentinel and last_error != server._watch_last_error:
            server._watch_last_error = last_error
            error_changed = True
    if notify and (state_changed or error_changed):
        server._notify_resource_updated("loom://mcp")


def maybe_start_background_watch(
    server,
    *,
    daemon_retry_seconds: float,
    stream_retry_seconds: float,
) -> None:
    del daemon_retry_seconds, stream_retry_seconds
    with server._state_lock:
        if not server._initialized:
            return
        if server._writer is None or not server._resource_subscriptions:
            return
        if server._watch_thread is not None and server._watch_thread.is_alive():
            return
    client = server._maybe_client_for_project_resources()
    if client is None:
        return
    last_sequence = client.store.latest_event_sequence()
    stop_event = threading.Event()
    watch_thread = threading.Thread(
        target=server._background_watch_loop,
        args=(stop_event, last_sequence),
        name="loom-mcp-watch",
        daemon=True,
    )
    with server._state_lock:
        if server._watch_thread is not None and server._watch_thread.is_alive():
            return
        server._watch_stop = stop_event
        server._watch_thread = watch_thread
    server._set_watch_diagnostics(
        state="starting",
        last_sequence=last_sequence,
        last_error=None,
    )
    watch_thread.start()


def stop_background_watch(server) -> None:
    with server._state_lock:
        watch_thread = server._watch_thread
        stop_event = server._watch_stop
    if watch_thread is None:
        stop_event.set()
        server._set_watch_diagnostics(state="idle")
        return
    if watch_thread is threading.current_thread():
        stop_event.set()
        with server._state_lock:
            if server._watch_thread is watch_thread:
                server._watch_thread = None
        server._set_watch_diagnostics(state="idle")
        return
    server._set_watch_diagnostics(state="stopping")
    stop_event.set()
    watch_thread.join(timeout=0.2)
    if watch_thread.is_alive():
        return
    with server._state_lock:
        if server._watch_thread is watch_thread:
            server._watch_thread = None
    server._set_watch_diagnostics(state="idle")


def background_watch_loop(
    server,
    stop_event,
    after_sequence: int,
    *,
    daemon_retry_seconds: float,
    stream_retry_seconds: float,
) -> None:
    client = server._maybe_client_for_project_resources()
    if client is None:
        return
    should_restart = False
    daemon_retry_delay = daemon_retry_seconds
    stream_retry_delay = stream_retry_seconds
    max_daemon_retry_seconds = max(daemon_retry_seconds, 2.0)
    max_stream_retry_seconds = max(stream_retry_seconds, 1.0)
    try:
        while not stop_event.is_set():
            if server._writer is None or not server._subscription_snapshot():
                break
            status = client.daemon_status(refresh=True)
            if not status.running:
                server._set_watch_diagnostics(state="waiting_for_daemon")
                stop_event.wait(daemon_retry_delay)
                daemon_retry_delay = _next_retry_seconds(
                    current=daemon_retry_delay,
                    maximum=max_daemon_retry_seconds,
                )
                continue
            daemon_retry_delay = daemon_retry_seconds
            try:
                server._set_watch_diagnostics(state="watching", last_error=None)
                delivered_event = False
                for event in client.follow_events(after_sequence=after_sequence):
                    delivered_event = True
                    stream_retry_delay = stream_retry_seconds
                    after_sequence = int(getattr(event, "sequence"))
                    server._set_watch_diagnostics(
                        last_sequence=after_sequence,
                        notify=False,
                    )
                    server._notify_followed_event_updates(event)
                    if stop_event.is_set():
                        break
                if stop_event.is_set():
                    break
                stop_event.wait(stream_retry_delay)
                if not delivered_event:
                    stream_retry_delay = _next_retry_seconds(
                        current=stream_retry_delay,
                        maximum=max_stream_retry_seconds,
                    )
            except RuntimeError as error:
                server._set_watch_diagnostics(
                    state="retrying",
                    last_error=str(error),
                )
                stop_event.wait(stream_retry_delay)
                stream_retry_delay = _next_retry_seconds(
                    current=stream_retry_delay,
                    maximum=max_stream_retry_seconds,
                )
    finally:
        with server._state_lock:
            if server._watch_thread is threading.current_thread():
                server._watch_thread = None
            server._watch_state = "idle"
            should_restart = (
                server._initialized
                and server._writer is not None
                and bool(server._resource_subscriptions)
            )
        if should_restart:
            server._maybe_start_background_watch()


def notify_followed_event_updates(server, event: object) -> None:
    structured = {"event": event}
    for uri in server._project_resource_uris(include_identity=False):
        server._notify_resource_updated(uri)
    for uri in server._event_feed_subscription_uris():
        server._notify_resource_updated(uri)
    for uri in server._agent_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._activity_feed_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._object_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._timeline_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._timeline_alias_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)


def notify_tool_resource_updates(
    server,
    *,
    name: str,
    before_resources: tuple[str, ...],
    structured: dict[str, object],
) -> None:
    after_resources = server._resource_uris()
    if before_resources != after_resources:
        server._emit_notification("notifications/resources/list_changed")

    include_identity = name == "loom_init"
    for uri in server._project_resource_uris(include_identity=include_identity):
        server._notify_resource_updated(uri)
    for uri in server._agent_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._activity_feed_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._object_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._timeline_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._timeline_alias_resource_uris_for_structured(structured):
        server._notify_resource_updated(uri)
    for uri in server._event_feed_subscription_uris():
        server._notify_resource_updated(uri)


def project_resource_uris(server, *, include_identity: bool) -> tuple[str, ...]:
    return resource_project_resource_uris(
        resource_map=server._resource_map(),
        include_identity=include_identity,
    )


def notify_resource_updated(server, uri: str) -> None:
    if uri not in server._subscription_snapshot():
        return
    server._emit_notification("notifications/resources/updated", {"uri": uri})


def event_feed_subscription_uris(server) -> tuple[str, ...]:
    return tuple(
        sorted(
            uri
            for uri in server._subscription_snapshot()
            if uri.startswith("loom://events/after/")
        )
    )
