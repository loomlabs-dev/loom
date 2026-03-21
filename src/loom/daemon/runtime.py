from __future__ import annotations

import json
import os
import queue
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from socketserver import StreamRequestHandler, ThreadingMixIn, UnixStreamServer
from typing import BinaryIO

from .. import __version__
from .client_api import (
    FOLLOW_STREAM_IDLE_TIMEOUT_SECONDS,
    acknowledge_context as _client_acknowledge_context,
    create_claim as _client_create_claim,
    declare_intent as _client_declare_intent,
    describe_protocol as _client_describe_protocol,
    follow_events as _client_follow_events,
    get_context_entry as _client_get_context_entry,
    publish_context as _client_publish_context,
    read_agent_snapshot as _client_read_agent_snapshot,
    read_agents as _client_read_agents,
    read_conflicts as _client_read_conflicts,
    read_context_entries as _client_read_context_entries,
    read_events as _client_read_events,
    read_inbox_snapshot as _client_read_inbox_snapshot,
    read_status as _client_read_status,
    release_claim as _client_release_claim,
    release_intent as _client_release_intent,
    renew_claim as _client_renew_claim,
    renew_intent as _client_renew_intent,
    resolve_conflict as _client_resolve_conflict,
)
from ..local_store import (
    AgentPresenceRecord,
    AgentSnapshot,
    ClaimRecord,
    ConflictRecord,
    ContextAckRecord,
    ContextRecord,
    CoordinationStore,
    EventRecord,
    InboxSnapshot,
    IntentRecord,
    StatusSnapshot,
)
from ..protocol import (
    LOCAL_PROTOCOL_NAME,
    LOCAL_PROTOCOL_VERSION,
    ProtocolError,
    ProtocolResponseError,
    describe_local_protocol,
    encode_message,
    error_payload,
    read_message,
    require_compatible_message,
    success_payload,
)
from ..project import LoomProject
from ..util import utc_now
from ..wire import (
    agent_presence_to_wire as _agent_presence_to_wire,
    agent_snapshot_to_wire as _agent_snapshot_to_wire,
    claim_to_wire as _claim_to_wire,
    conflict_to_wire as _conflict_to_wire,
    context_ack_to_wire as _context_ack_to_wire,
    context_to_wire as _context_to_wire,
    event_to_wire as _event_to_wire,
    inbox_snapshot_to_wire as _inbox_snapshot_to_wire,
    intent_to_wire as _intent_to_wire,
    status_snapshot_to_wire as _status_snapshot_to_wire,
)

FOLLOW_STREAM_HEARTBEAT_SECONDS = FOLLOW_STREAM_IDLE_TIMEOUT_SECONDS / 3


@dataclass(frozen=True)
class DaemonStatus:
    running: bool
    detail: str
    pid: int | None = None
    started_at: str | None = None
    log_path: Path | None = None

    def describe(self) -> str:
        return self.detail


@dataclass(frozen=True)
class DaemonControlResult:
    detail: str
    pid: int | None = None
    log_path: Path | None = None


@dataclass
class _EventSubscriber:
    event_type: str | None
    queue: queue.Queue[EventRecord]


def probe_daemon(socket_path: Path, timeout: float = 0.2) -> DaemonStatus:
    if not socket_path.exists():
        return DaemonStatus(
            running=False,
            detail="not running (direct SQLite mode)",
        )

    try:
        response = _request(
            socket_path,
            payload={"type": "ping"},
            timeout=timeout,
        )
        if response.get("ok"):
            return DaemonStatus(
                running=True,
                detail=f"running on {socket_path.name}",
            )
    except RuntimeError as error:
        if str(error) == "socket_unavailable":
            return DaemonStatus(
                running=False,
                detail="socket present but unavailable",
            )
        return DaemonStatus(
            running=False,
            detail=f"socket responded with {error}",
        )

    return DaemonStatus(
        running=False,
        detail="socket present but unavailable",
    )


def get_daemon_status(project: LoomProject) -> DaemonStatus:
    socket_status = probe_daemon(project.socket_path)
    runtime = _read_runtime_payload(project.runtime_path)
    if runtime is None:
        return socket_status

    pid = _runtime_pid_or_none(runtime.get("pid"))
    started_at = _string_or_none(runtime.get("started_at"))
    if socket_status.running:
        return DaemonStatus(
            running=True,
            detail=socket_status.detail,
            pid=pid,
            started_at=started_at,
            log_path=project.log_path,
        )

    if pid is not None and _process_exists(pid):
        return DaemonStatus(
            running=False,
            detail="process running but socket unavailable",
            pid=pid,
            started_at=started_at,
            log_path=project.log_path,
        )

    return DaemonStatus(
        running=False,
        detail="stale daemon runtime found",
        pid=pid,
        started_at=started_at,
        log_path=project.log_path,
    )


def read_events(
    socket_path: Path,
    *,
    limit: int = 20,
    event_type: str | None = None,
    after_sequence: int | None = None,
    ascending: bool = False,
    timeout: float = 0.5,
) -> tuple[EventRecord, ...]:
    return _client_read_events(
        socket_path,
        limit=limit,
        event_type=event_type,
        after_sequence=after_sequence,
        ascending=ascending,
        timeout=timeout,
        request_fn=_request,
    )


def follow_events(
    socket_path: Path,
    *,
    event_type: str | None = None,
    after_sequence: int | None = None,
    timeout: float = 0.5,
):
    return _client_follow_events(
        socket_path,
        event_type=event_type,
        after_sequence=after_sequence,
        timeout=timeout,
        socket_factory=socket.socket,
        read_response_message_fn=_read_response_message,
    )


def describe_protocol(
    socket_path: Path,
    *,
    timeout: float = 0.5,
) -> dict[str, object]:
    return _client_describe_protocol(
        socket_path,
        timeout=timeout,
        request_fn=_request,
    )


def read_agents(
    socket_path: Path,
    *,
    limit: int = 20,
    timeout: float = 0.5,
) -> tuple[AgentPresenceRecord, ...]:
    return _client_read_agents(
        socket_path,
        limit=limit,
        timeout=timeout,
        request_fn=_request,
    )


def create_claim(
    socket_path: Path,
    *,
    agent_id: str,
    description: str,
    scope: list[str] | tuple[str, ...],
    source: str,
    lease_minutes: int | None = None,
    lease_policy: str | None = None,
    timeout: float = 0.5,
) -> tuple[ClaimRecord, tuple[ConflictRecord, ...]]:
    return _client_create_claim(
        socket_path,
        agent_id=agent_id,
        description=description,
        scope=scope,
        source=source,
        lease_minutes=lease_minutes,
        lease_policy=lease_policy,
        timeout=timeout,
        request_fn=_request,
    )


def release_claim(
    socket_path: Path,
    *,
    agent_id: str,
    timeout: float = 0.5,
) -> ClaimRecord | None:
    return _client_release_claim(
        socket_path,
        agent_id=agent_id,
        timeout=timeout,
        request_fn=_request,
    )


def renew_claim(
    socket_path: Path,
    *,
    agent_id: str,
    lease_minutes: int,
    source: str,
    timeout: float = 0.5,
) -> ClaimRecord | None:
    return _client_renew_claim(
        socket_path,
        agent_id=agent_id,
        lease_minutes=lease_minutes,
        source=source,
        timeout=timeout,
        request_fn=_request,
    )


def declare_intent(
    socket_path: Path,
    *,
    agent_id: str,
    description: str,
    reason: str,
    scope: list[str] | tuple[str, ...],
    source: str,
    lease_minutes: int | None = None,
    lease_policy: str | None = None,
    timeout: float = 0.5,
) -> tuple[IntentRecord, tuple[ConflictRecord, ...]]:
    return _client_declare_intent(
        socket_path,
        agent_id=agent_id,
        description=description,
        reason=reason,
        scope=scope,
        source=source,
        lease_minutes=lease_minutes,
        lease_policy=lease_policy,
        timeout=timeout,
        request_fn=_request,
    )


def release_intent(
    socket_path: Path,
    *,
    agent_id: str,
    timeout: float = 0.5,
) -> IntentRecord | None:
    return _client_release_intent(
        socket_path,
        agent_id=agent_id,
        timeout=timeout,
        request_fn=_request,
    )


def renew_intent(
    socket_path: Path,
    *,
    agent_id: str,
    lease_minutes: int,
    source: str,
    timeout: float = 0.5,
) -> IntentRecord | None:
    return _client_renew_intent(
        socket_path,
        agent_id=agent_id,
        lease_minutes=lease_minutes,
        source=source,
        timeout=timeout,
        request_fn=_request,
    )


def publish_context(
    socket_path: Path,
    *,
    agent_id: str,
    topic: str,
    body: str,
    scope: list[str] | tuple[str, ...],
    source: str,
    timeout: float = 0.5,
) -> tuple[ContextRecord, tuple[ConflictRecord, ...]]:
    return _client_publish_context(
        socket_path,
        agent_id=agent_id,
        topic=topic,
        body=body,
        scope=scope,
        source=source,
        timeout=timeout,
        request_fn=_request,
    )


def read_context_entries(
    socket_path: Path,
    *,
    topic: str | None = None,
    agent_id: str | None = None,
    scope: list[str] | tuple[str, ...] = (),
    limit: int = 10,
    timeout: float = 0.5,
) -> tuple[ContextRecord, ...]:
    return _client_read_context_entries(
        socket_path,
        topic=topic,
        agent_id=agent_id,
        scope=scope,
        limit=limit,
        timeout=timeout,
        request_fn=_request,
    )


def get_context_entry(
    socket_path: Path,
    *,
    context_id: str,
    timeout: float = 0.5,
) -> ContextRecord | None:
    return _client_get_context_entry(
        socket_path,
        context_id=context_id,
        timeout=timeout,
        request_fn=_request,
    )


def acknowledge_context(
    socket_path: Path,
    *,
    context_id: str,
    agent_id: str,
    status: str,
    note: str | None = None,
    timeout: float = 0.5,
) -> ContextAckRecord | None:
    return _client_acknowledge_context(
        socket_path,
        context_id=context_id,
        agent_id=agent_id,
        status=status,
        note=note,
        timeout=timeout,
        request_fn=_request,
    )


def read_status(
    socket_path: Path,
    *,
    timeout: float = 0.5,
) -> StatusSnapshot:
    return _client_read_status(
        socket_path,
        timeout=timeout,
        request_fn=_request,
    )


def read_agent_snapshot(
    socket_path: Path,
    *,
    agent_id: str,
    context_limit: int = 5,
    event_limit: int = 10,
    timeout: float = 0.5,
) -> AgentSnapshot:
    return _client_read_agent_snapshot(
        socket_path,
        agent_id=agent_id,
        context_limit=context_limit,
        event_limit=event_limit,
        timeout=timeout,
        request_fn=_request,
    )


def read_inbox_snapshot(
    socket_path: Path,
    *,
    agent_id: str,
    context_limit: int = 5,
    event_limit: int = 10,
    timeout: float = 0.5,
) -> InboxSnapshot:
    return _client_read_inbox_snapshot(
        socket_path,
        agent_id=agent_id,
        context_limit=context_limit,
        event_limit=event_limit,
        timeout=timeout,
        request_fn=_request,
    )


def read_conflicts(
    socket_path: Path,
    *,
    include_resolved: bool = False,
    timeout: float = 0.5,
) -> tuple[ConflictRecord, ...]:
    return _client_read_conflicts(
        socket_path,
        include_resolved=include_resolved,
        timeout=timeout,
        request_fn=_request,
    )


def resolve_conflict(
    socket_path: Path,
    *,
    conflict_id: str,
    agent_id: str,
    resolution_note: str | None = None,
    timeout: float = 0.5,
) -> ConflictRecord | None:
    return _client_resolve_conflict(
        socket_path,
        conflict_id=conflict_id,
        agent_id=agent_id,
        resolution_note=resolution_note,
        timeout=timeout,
        request_fn=_request,
    )


def start_daemon(project: LoomProject, timeout: float = 2.0) -> DaemonControlResult:
    status = get_daemon_status(project)
    if status.running:
        return DaemonControlResult(
            detail="Daemon already running.",
            pid=status.pid,
            log_path=project.log_path,
    )
    if status.pid is not None and _process_exists(status.pid):
        stop_daemon(project)

    _clear_daemon_artifacts(project)

    command = [sys.executable, "-m", "loom", "daemon", "run"]
    env = os.environ.copy()
    module_root = Path(__file__).resolve().parents[2]
    current_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{module_root}{os.pathsep}{current_pythonpath}"
        if current_pythonpath
        else str(module_root)
    )

    project.loom_dir.mkdir(parents=True, exist_ok=True)
    with project.log_path.open("a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=project.repo_root,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = get_daemon_status(project)
        if status.running:
            return DaemonControlResult(
                detail="Daemon started.",
                pid=status.pid or process.pid,
                log_path=project.log_path,
            )
        if process.poll() is not None:
            break
        time.sleep(0.05)

    if process.poll() is None:
        _terminate_process(process.pid)
    _clear_daemon_artifacts(project)
    raise RuntimeError(f"Failed to start daemon. Check {project.log_path}.")


def stop_daemon(project: LoomProject, timeout: float = 2.0) -> DaemonControlResult:
    status = get_daemon_status(project)
    pid = status.pid
    if pid is None:
        _clear_daemon_artifacts(project)
        return DaemonControlResult(
            detail="Daemon is not running.",
            log_path=project.log_path,
        )

    if _process_exists(pid):
        _terminate_process(pid)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not _process_exists(pid):
                break
            time.sleep(0.05)
        if _process_exists(pid):
            os.kill(pid, signal.SIGKILL)

    _clear_daemon_artifacts(project)
    return DaemonControlResult(
        detail="Daemon stopped.",
        pid=pid,
        log_path=project.log_path,
    )


@contextmanager
def _daemon_signal_handlers(server: "_LoomUnixServer"):
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous_handlers: dict[int, object] = {}

    def _handle_shutdown_signal(signum: int, _frame: object) -> None:
        shutdown_thread = threading.Thread(
            target=server.shutdown,
            name=f"loom-daemon-shutdown-{signum}",
            daemon=True,
        )
        shutdown_thread.start()

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _handle_shutdown_signal)
        yield
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)


def run_daemon(project: LoomProject) -> None:
    server = _LoomUnixServer(project)
    runtime_payload = {
        "pid": os.getpid(),
        "started_at": utc_now(),
        "socket": project.socket_path.name,
        "version": __version__,
        "protocol": LOCAL_PROTOCOL_NAME,
        "protocol_version": LOCAL_PROTOCOL_VERSION,
    }
    try:
        _write_runtime_payload(project.runtime_path, runtime_payload)
        with _daemon_signal_handlers(server):
            server.serve_forever()
    finally:
        server.server_close()
        _clear_daemon_artifacts(project)


class _LoomUnixServer(ThreadingMixIn, UnixStreamServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, project: LoomProject) -> None:
        if project.socket_path.exists():
            project.socket_path.unlink()
        self.project = project
        self.store = CoordinationStore(
            project.db_path,
            repo_root=project.repo_root,
            reuse_connections=True,
        )
        self.store.initialize()
        self.store.close_thread_connection()
        self._subscriber_lock = threading.Lock()
        self._event_subscribers: list[_EventSubscriber] = []
        super().__init__(str(project.socket_path), _LoomRequestHandler)

    def add_event_subscriber(self, event_type: str | None) -> _EventSubscriber:
        subscriber = _EventSubscriber(
            event_type=event_type,
            queue=queue.Queue(),
        )
        with self._subscriber_lock:
            self._event_subscribers.append(subscriber)
        return subscriber

    def remove_event_subscriber(self, subscriber: _EventSubscriber) -> None:
        with self._subscriber_lock:
            try:
                self._event_subscribers.remove(subscriber)
            except ValueError:
                return

    def publish_events(self, events: tuple[EventRecord, ...]) -> None:
        if not events:
            return
        with self._subscriber_lock:
            subscribers = tuple(self._event_subscribers)
        for subscriber in subscribers:
            for event in events:
                if subscriber.event_type and subscriber.event_type != event.type:
                    continue
                subscriber.queue.put(event)


_STREAMING_RESPONSE = object()
_REQUEST_HANDLER_NAMES = {
    "ping": "_handle_ping_request",
    "protocol.describe": "_handle_protocol_describe_request",
    "claim.create": "_handle_claim_create_request",
    "claim.release": "_handle_claim_release_request",
    "claim.renew": "_handle_claim_renew_request",
    "intent.declare": "_handle_intent_declare_request",
    "intent.release": "_handle_intent_release_request",
    "intent.renew": "_handle_intent_renew_request",
    "context.publish": "_handle_context_publish_request",
    "context.read": "_handle_context_read_request",
    "context.get": "_handle_context_get_request",
    "context.ack": "_handle_context_ack_request",
    "status.read": "_handle_status_read_request",
    "agents.read": "_handle_agents_read_request",
    "agent.read": "_handle_agent_read_request",
    "inbox.read": "_handle_inbox_read_request",
    "conflicts.read": "_handle_conflicts_read_request",
    "conflict.resolve": "_handle_conflict_resolve_request",
    "events.follow": "_handle_events_follow_request",
    "events.read": "_handle_events_read_request",
}


class _LoomRequestHandler(StreamRequestHandler):
    def handle(self) -> None:
        try:
            request = read_message(self.rfile)
        except ProtocolError as error:
            self._write_response(error_payload(str(error), error_code=str(error)))
            return

        if request is None:
            return

        try:
            require_compatible_message(request)
        except ProtocolError as error:
            self._write_response(error_payload(str(error), error_code=str(error)))
            return

        try:
            self._dispatch_request(request)
        except (TypeError, ValueError) as error:
            self._write_response(error_payload(str(error), error_code=_error_code(error)))
            return

    def _dispatch_request(self, request: dict[str, object]) -> None:
        request_type = _string_or_none(request.get("type"))
        handler_name = _REQUEST_HANDLER_NAMES.get(request_type or "")
        if handler_name is None:
            self._write_response(error_payload("unsupported_message", error_code="unsupported_message"))
            return

        response = getattr(self, handler_name)(request)
        if response is _STREAMING_RESPONSE:
            return
        self._write_response(success_payload(**response))

    def _handle_ping_request(self, request: dict[str, object]) -> dict[str, object]:
        del request
        return {
            "service": "loomd",
            "version": __version__,
            "protocol": LOCAL_PROTOCOL_NAME,
            "protocol_version": LOCAL_PROTOCOL_VERSION,
            "timestamp": utc_now(),
        }

    def _handle_protocol_describe_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        del request
        return {"protocol": describe_local_protocol()}

    def _handle_claim_create_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            claim, conflicts = store.record_claim(
                agent_id=_required_string(request, "agent_id"),
                description=_required_string(request, "description"),
                scope=_string_list(request.get("scope")),
                source=_string_or_none(request.get("source")) or "daemon",
                lease_minutes=_positive_int_or_none(request.get("lease_minutes")),
                lease_policy=_string_or_none(request.get("lease_policy")),
            )
            return {
                "claim": _claim_to_wire(claim),
                "conflicts": [_conflict_to_wire(item) for item in conflicts],
            }

        return self._run_mutating_request(operation)

    def _handle_claim_release_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            claim = store.release_claim(
                agent_id=_required_string(request, "agent_id"),
            )
            return {"claim": None if claim is None else _claim_to_wire(claim)}

        return self._run_mutating_request(operation)

    def _handle_claim_renew_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            lease_minutes = _positive_int_or_none(request.get("lease_minutes"))
            if lease_minutes is None:
                raise ValueError("lease_minutes must be a positive integer.")
            claim = store.renew_claim(
                agent_id=_required_string(request, "agent_id"),
                lease_minutes=lease_minutes,
                source=_string_or_none(request.get("source")) or "daemon",
            )
            return {"claim": None if claim is None else _claim_to_wire(claim)}

        return self._run_mutating_request(operation)

    def _handle_intent_declare_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            intent, conflicts = store.record_intent(
                agent_id=_required_string(request, "agent_id"),
                description=_required_string(request, "description"),
                reason=_required_string(request, "reason"),
                scope=_string_list(request.get("scope")),
                source=_string_or_none(request.get("source")) or "daemon",
                lease_minutes=_positive_int_or_none(request.get("lease_minutes")),
                lease_policy=_string_or_none(request.get("lease_policy")),
            )
            return {
                "intent": _intent_to_wire(intent),
                "conflicts": [_conflict_to_wire(item) for item in conflicts],
            }

        return self._run_mutating_request(operation)

    def _handle_intent_release_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            intent = store.release_intent(
                agent_id=_required_string(request, "agent_id"),
            )
            return {"intent": None if intent is None else _intent_to_wire(intent)}

        return self._run_mutating_request(operation)

    def _handle_intent_renew_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            lease_minutes = _positive_int_or_none(request.get("lease_minutes"))
            if lease_minutes is None:
                raise ValueError("lease_minutes must be a positive integer.")
            intent = store.renew_intent(
                agent_id=_required_string(request, "agent_id"),
                lease_minutes=lease_minutes,
                source=_string_or_none(request.get("source")) or "daemon",
            )
            return {"intent": None if intent is None else _intent_to_wire(intent)}

        return self._run_mutating_request(operation)

    def _handle_context_publish_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            context, conflicts = store.record_context(
                agent_id=_required_string(request, "agent_id"),
                topic=_required_string(request, "topic"),
                body=_required_string(request, "body"),
                scope=_string_list(request.get("scope")),
                source=_string_or_none(request.get("source")) or "daemon",
            )
            return {
                "context": _context_to_wire(context),
                "conflicts": [_conflict_to_wire(item) for item in conflicts],
            }

        return self._run_mutating_request(operation)

    def _handle_context_read_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        entries = self.server.store.read_context(
            topic=_string_or_none(request.get("topic")),
            agent_id=_string_or_none(request.get("agent_id")),
            scope=_string_list(request.get("scope")),
            limit=int(request.get("limit", 10)),
        )
        return {"context": [_context_to_wire(item) for item in entries]}

    def _handle_context_get_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        context = self.server.store.get_context(
            _required_string(request, "context_id"),
        )
        return {
            "context": None if context is None else _context_to_wire(context),
        }

    def _handle_context_ack_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            ack = store.acknowledge_context(
                context_id=_required_string(request, "context_id"),
                agent_id=_required_string(request, "agent_id"),
                status=_required_string(request, "status"),
                note=_string_or_none(request.get("note")),
            )
            return {"ack": None if ack is None else _context_ack_to_wire(ack)}

        return self._run_mutating_request(operation)

    def _handle_status_read_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        del request
        snapshot = self.server.store.status()
        return _status_snapshot_to_wire(snapshot)

    def _handle_agents_read_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        agents = self.server.store.list_agents(
            limit=int(request.get("limit", 20)),
        )
        return {"agents": [_agent_presence_to_wire(item) for item in agents]}

    def _handle_agent_read_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        snapshot = self.server.store.agent_snapshot(
            agent_id=_required_string(request, "agent_id"),
            context_limit=int(request.get("context_limit", 5)),
            event_limit=int(request.get("event_limit", 10)),
        )
        return {"agent": _agent_snapshot_to_wire(snapshot)}

    def _handle_inbox_read_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        snapshot = self.server.store.inbox_snapshot(
            agent_id=_required_string(request, "agent_id"),
            context_limit=int(request.get("context_limit", 5)),
            event_limit=int(request.get("event_limit", 10)),
        )
        return {"inbox": _inbox_snapshot_to_wire(snapshot)}

    def _handle_conflicts_read_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        conflicts = self.server.store.list_conflicts(
            include_resolved=bool(request.get("include_resolved", False))
        )
        return {"conflicts": [_conflict_to_wire(item) for item in conflicts]}

    def _handle_conflict_resolve_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        def operation(store: CoordinationStore) -> dict[str, object]:
            conflict = store.resolve_conflict(
                conflict_id=_required_string(request, "conflict_id"),
                agent_id=_required_string(request, "agent_id"),
                resolution_note=_string_or_none(request.get("resolution_note")),
            )
            return {
                "conflict": None if conflict is None else _conflict_to_wire(conflict),
            }

        return self._run_mutating_request(operation)

    def _handle_events_follow_request(
        self,
        request: dict[str, object],
    ) -> object:
        self._follow_events(
            store=self.server.store,
            event_type=_string_or_none(request.get("event_type")),
            after_sequence=_int_or_none(request.get("after_sequence")),
        )
        return _STREAMING_RESPONSE

    def _handle_events_read_request(
        self,
        request: dict[str, object],
    ) -> dict[str, object]:
        events = self.server.store.list_events(
            limit=int(request.get("limit", 20)),
            event_type=_string_or_none(request.get("event_type")),
            after_sequence=_int_or_none(request.get("after_sequence")),
            ascending=bool(request.get("ascending", False)),
        )
        return {"events": [_event_to_wire(event) for event in events]}

    def _run_mutating_request(
        self,
        operation,
    ) -> dict[str, object]:
        store = self.server.store
        last_sequence = store.latest_event_sequence()
        response = operation(store)
        self._publish_new_events(store, last_sequence=last_sequence)
        return response

    def _publish_new_events(
        self,
        store: CoordinationStore,
        *,
        last_sequence: int,
    ) -> None:
        self.server.publish_events(
            store.list_events(
                after_sequence=last_sequence,
                ascending=True,
                limit=None,
            )
        )

    def _write_response(self, payload: dict[str, object]) -> None:
        self.wfile.write(encode_message(payload))
        self.wfile.flush()

    def _follow_events(
        self,
        *,
        store: CoordinationStore,
        event_type: str | None,
        after_sequence: int | None,
    ) -> None:
        self._write_response(success_payload(stream="events"))

        subscriber = self.server.add_event_subscriber(event_type)
        last_sequence = after_sequence or 0
        backlog = ()
        try:
            backlog = store.list_events(
                event_type=event_type,
                after_sequence=after_sequence,
                ascending=True,
                limit=None,
            )
            for event in backlog:
                self._write_response(success_payload(event=_event_to_wire(event)))
                last_sequence = event.sequence

            while True:
                try:
                    event = subscriber.queue.get(timeout=FOLLOW_STREAM_HEARTBEAT_SECONDS)
                except queue.Empty:
                    self._write_response(success_payload(heartbeat="events"))
                    continue
                if event.sequence <= last_sequence:
                    continue
                self._write_response(success_payload(event=_event_to_wire(event)))
                last_sequence = event.sequence
        except (BrokenPipeError, ConnectionResetError, OSError):
            return
        finally:
            self.server.remove_event_subscriber(subscriber)

    def finish(self) -> None:
        try:
            super().finish()
        finally:
            self.server.store.close_thread_connection()


def _request(
    socket_path: Path,
    *,
    payload: dict[str, object],
    timeout: float,
) -> dict[str, object]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(socket_path))
        client.sendall(encode_message(payload))
        with client.makefile("rb") as reader:
            response = _read_response_message(reader)
            if response is None:
                raise RuntimeError("daemon_closed_connection")
            return response
    except OSError as error:
        raise RuntimeError("socket_unavailable") from error
    except ProtocolError as error:
        raise RuntimeError(str(error)) from error
    finally:
        client.close()


def _read_response_message(stream: BinaryIO) -> dict[str, object] | None:
    payload = read_message(stream)
    if payload is None:
        return None
    require_compatible_message(payload)
    if not payload.get("ok"):
        error = payload.get("error", "daemon_request_failed")
        error_code = payload.get("error_code")
        detail = payload.get("detail")
        raise ProtocolResponseError(
            str(error),
            code=error_code if isinstance(error_code, str) and error_code else None,
            detail=detail if isinstance(detail, str) and detail else None,
        )
    return payload


def _error_code(error: BaseException) -> str | None:
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        return code
    if isinstance(error, ProtocolError):
        return str(error)
    return None


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    return None


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, tuple):
        return [str(item) for item in value]
    raise ValueError("Expected a list value.")


def _required_string(payload: dict[str, object], key: str) -> str:
    value = _string_or_none(payload.get(key))
    if value is None:
        raise ValueError(f"Missing `{key}`.")
    return value


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _positive_int_or_none(value: object) -> int | None:
    normalized = _int_or_none(value)
    if normalized is None:
        return None
    if normalized <= 0:
        raise ValueError("Lease minutes must be positive.")
    return normalized


def _read_runtime_payload(runtime_path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(runtime_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return {str(key): value for key, value in payload.items()}


def _runtime_pid_or_none(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _terminate_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _clear_daemon_artifacts(project: LoomProject) -> None:
    _safe_unlink(project.runtime_path)
    _safe_unlink(project.socket_path)


def _write_runtime_payload(runtime_path: Path, payload: dict[str, object]) -> None:
    runtime_path.parent.mkdir(exist_ok=True)
    encoded = f"{json.dumps(payload, indent=2)}\n"
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=str(runtime_path.parent),
        prefix=f".{runtime_path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, runtime_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
