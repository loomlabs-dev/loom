from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli_follow import _run_follow_loop, emit_inbox_follow_update, handle_context_follow  # noqa: E402
from loom.local_store import ContextRecord, EventRecord, InboxSnapshot  # noqa: E402


def make_event(*, sequence: int, event_id: str, payload: dict[str, str]) -> EventRecord:
    return EventRecord(
        sequence=sequence,
        id=event_id,
        type="context.published",
        timestamp="2026-03-18T12:00:00Z",
        actor_id="agent-a",
        payload=payload,
    )


def make_context(context_id: str, *, topic: str = "migration") -> ContextRecord:
    return ContextRecord(
        id=context_id,
        agent_id="agent-a",
        topic=topic,
        body="Context body",
        scope=("src/api.py",),
        created_at="2026-03-18T12:05:00Z",
        related_claim_id=None,
        related_intent_id=None,
    )


class _DaemonStatus:
    def __init__(self, running: bool) -> None:
        self.running = running


class _FakeClient:
    def __init__(self, *, running: bool) -> None:
        self._running = running
        self.follow_error = False
        self.followed_events: tuple[EventRecord, ...] = ()
        self.poll_events_once: tuple[EventRecord, ...] = ()
        self.read_events_calls = 0
        self.context_entries: dict[str, ContextRecord] = {}
        self.store = type("Store", (), {"latest_event_sequence": lambda self: 0})()

    def daemon_status(self) -> _DaemonStatus:
        return _DaemonStatus(self._running)

    def follow_events(self, *, event_type: str | None, after_sequence: int):
        if self.follow_error:
            raise RuntimeError("daemon follow failed")
        return iter(self.followed_events)

    def read_events(
        self,
        *,
        limit: int | None,
        event_type: str | None,
        after_sequence: int | None,
        ascending: bool,
    ) -> tuple[EventRecord, ...]:
        self.read_events_calls += 1
        if self.read_events_calls == 1:
            return self.poll_events_once
        return ()

    def get_context_entry(self, *, context_id: str) -> ContextRecord | None:
        return self.context_entries.get(context_id)


class CliFollowTest(unittest.TestCase):
    def test_run_follow_loop_uses_daemon_stream_when_available(self) -> None:
        client = _FakeClient(running=True)
        client.followed_events = (
            make_event(sequence=1, event_id="event_1", payload={"context_id": "context_1"}),
            make_event(sequence=2, event_id="event_2", payload={"context_id": "context_2"}),
        )
        seen: list[int] = []

        result = _run_follow_loop(
            client=client,
            after_sequence=0,
            max_follow_items=2,
            poll_interval=0.0,
            follow_event_type="context.published",
            handle_event=lambda event: seen.append(event.sequence) or True,
            read_poll_events=lambda last_sequence: (),
        )

        self.assertEqual(result, 0)
        self.assertEqual(seen, [1, 2])

    def test_run_follow_loop_falls_back_to_polling_after_stream_error(self) -> None:
        client = _FakeClient(running=True)
        client.follow_error = True
        client.poll_events_once = (
            make_event(sequence=3, event_id="event_3", payload={"context_id": "context_3"}),
        )
        seen: list[int] = []

        result = _run_follow_loop(
            client=client,
            after_sequence=0,
            max_follow_items=1,
            poll_interval=0.0,
            follow_event_type=None,
            handle_event=lambda event: seen.append(event.sequence) or True,
            read_poll_events=lambda last_sequence: client.read_events(
                limit=None,
                event_type=None,
                after_sequence=last_sequence,
                ascending=True,
            ),
        )

        self.assertEqual(result, 0)
        self.assertEqual(seen, [3])
        self.assertGreaterEqual(client.read_events_calls, 1)

    def test_emit_inbox_follow_update_json_payload_includes_attention(self) -> None:
        snapshot = InboxSnapshot(
            agent_id="agent-a",
            pending_context=(make_context("context_1"),),
            conflicts=(),
            events=(),
        )
        event = make_event(sequence=4, event_id="event_4", payload={"context_id": "context_1"})
        lines: list[dict[str, object]] = []

        emit_inbox_follow_update(
            snapshot=snapshot,
            event=event,
            json_mode=True,
            identity={"id": "agent-a"},
            write_json_line=lines.append,
            identity_summary_printer=lambda **kwargs: None,
        )

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["stream"], "inbox")
        self.assertEqual(lines[0]["phase"], "update")
        self.assertEqual(lines[0]["attention"], {"pending_context": 1, "active_conflicts": 0})

    def test_handle_context_follow_only_emits_matching_entries(self) -> None:
        client = _FakeClient(running=False)
        client.poll_events_once = (
            make_event(sequence=1, event_id="event_1", payload={"context_id": "context_skip"}),
            make_event(sequence=2, event_id="event_2", payload={"context_id": "context_keep"}),
        )
        client.context_entries = {
            "context_skip": make_context("context_skip", topic="other"),
            "context_keep": make_context("context_keep", topic="migration"),
        }
        payloads: list[dict[str, object]] = []

        result = handle_context_follow(
            client=client,
            topic="migration",
            agent_id=None,
            scope=[],
            poll_interval=0.0,
            max_follow_entries=1,
            json_mode=True,
            context_matches_filters=lambda entry, topic, agent_id, scope: entry.topic == topic,
            write_json_line=payloads.append,
        )

        self.assertEqual(result, 0)
        self.assertEqual(len(payloads), 1)
        self.assertEqual(payloads[0]["stream"], "context")
        self.assertEqual(payloads[0]["phase"], "entry")
        self.assertEqual(payloads[0]["context"].id, "context_keep")


if __name__ == "__main__":
    unittest.main()
