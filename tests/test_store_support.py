from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.dependency_graph import DependencyLink  # noqa: E402
from loom.local_store.records import ContextAckRecord, ContextRecord  # noqa: E402
from loom.local_store.store_support import (  # noqa: E402
    canonical_conflict_sides,
    claim_from_row,
    context_has_ack,
    dependency_link_scope,
    dump_json,
    event_from_row,
    event_references,
    flatten_reference_pairs,
    load_json,
    merge_context_ack_status,
    merge_scopes,
    normalize_context_ack_status,
    normalize_event_references,
    object_type_for_reference_key,
    reference_pair_placeholders,
    scope_filter_matches,
    semantic_overlap_summary,
    validated_git_branch_table_name,
    validated_lease_policy_table_name,
    validated_lease_table_name,
    validated_row_order,
)


class StoreSupportTest(unittest.TestCase):
    def test_table_validation_helpers_accept_known_tables_and_reject_unknown(self) -> None:
        self.assertEqual(validated_git_branch_table_name("claims"), "claims")
        self.assertEqual(validated_git_branch_table_name("context"), "context")
        self.assertEqual(validated_lease_table_name("intents"), "intents")
        self.assertEqual(validated_lease_policy_table_name("claims"), "claims")

        with self.assertRaisesRegex(ValueError, "Unsupported migration table"):
            validated_git_branch_table_name("claims; DROP TABLE claims")
        with self.assertRaisesRegex(ValueError, "Unsupported lease table"):
            validated_lease_table_name("context")
        with self.assertRaisesRegex(ValueError, "Unsupported lease policy table"):
            validated_lease_policy_table_name("context")

    def test_reference_helpers_shape_pairs_and_order(self) -> None:
        references = (("claim", "claim_1"), ("intent", "intent_2"))

        self.assertEqual(reference_pair_placeholders(2), "(?, ?), (?, ?)")
        self.assertEqual(
            flatten_reference_pairs(references),
            ["claim", "claim_1", "intent", "intent_2"],
        )
        self.assertEqual(validated_row_order(ascending=True), "ASC")
        self.assertEqual(validated_row_order(ascending=False), "DESC")

        with self.assertRaisesRegex(ValueError, "reference_count must be positive"):
            reference_pair_placeholders(0)

    def test_claim_and_event_row_decoders_coerce_payload_values(self) -> None:
        claim = claim_from_row(
            {
                "id": "claim_01",
                "agent_id": "agent-a",
                "description": "Auth migration lane",
                "scope_json": '["src/auth","src/api"]',
                "status": "active",
                "created_at": "2026-03-18T10:00:00Z",
                "git_branch": "main",
                "lease_expires_at": "2026-03-18T10:30:00Z",
                "lease_policy": "yield",
            }
        )
        event = event_from_row(
            {
                "sequence": "7",
                "id": "event_01",
                "type": "claim.recorded",
                "timestamp": "2026-03-18T10:00:00Z",
                "actor_id": "agent-a",
                "payload_json": '{"claim_id":"claim_01","attempt":2,"ok":true}',
            }
        )

        self.assertEqual(claim.scope, ("src/auth", "src/api"))
        self.assertEqual(claim.lease_policy, "yield")
        self.assertEqual(event.sequence, 7)
        self.assertEqual(
            event.payload,
            {"claim_id": "claim_01", "attempt": "2", "ok": "True"},
        )

    def test_conflict_summary_and_scope_helpers_use_dependency_links(self) -> None:
        links = (
            DependencyLink(source="src/a.py", target="src/b.py"),
            DependencyLink(source="src/b.py", target="src/c.py"),
            DependencyLink(source="src/c.py", target="src/d.py"),
        )

        self.assertEqual(
            canonical_conflict_sides(
                left_type="intent",
                left_id="intent_2",
                right_type="claim",
                right_id="claim_1",
            ),
            (("claim", "claim_1"), ("intent", "intent_2")),
        )
        self.assertIn(
            "agent-a claim is semantically entangled with agent-b intent via src/a.py -> src/b.py",
            semantic_overlap_summary(
                agent_id="agent-a",
                object_type="claim",
                other_agent_id="agent-b",
                other_object_type="intent",
                dependency_links=links,
            ),
        )
        self.assertEqual(
            dependency_link_scope(links),
            ("src/a.py", "src/b.py", "src/c.py", "src/d.py"),
        )

    def test_context_ack_helpers_preserve_highest_status_and_detect_presence(self) -> None:
        entry = ContextRecord(
            id="context_01",
            agent_id="agent-a",
            topic="auth-interface-change",
            body="UserSession now requires refresh_token.",
            scope=("src/auth",),
            created_at="2026-03-18T10:00:00Z",
            related_claim_id=None,
            related_intent_id=None,
            acknowledgments=(
                ContextAckRecord(
                    id="ctxack_01",
                    context_id="context_01",
                    agent_id="agent-b",
                    status="adapted",
                    acknowledged_at="2026-03-18T10:01:00Z",
                    note="Shifted work away from auth middleware.",
                ),
            ),
        )

        self.assertEqual(normalize_context_ack_status(" Read "), "read")
        self.assertEqual(merge_context_ack_status("read", "adapted"), "adapted")
        self.assertEqual(merge_context_ack_status("adapted", "read"), "adapted")
        self.assertTrue(context_has_ack(entry, "agent-b"))
        self.assertFalse(context_has_ack(entry, "agent-c"))

        with self.assertRaisesRegex(ValueError, "Context acknowledgment status"):
            normalize_context_ack_status("ignored")

    def test_json_scope_and_filter_helpers_keep_values_stable(self) -> None:
        dumped = dump_json({"topic": "auth", "count": 2})

        self.assertEqual(dumped, '{"topic":"auth","count":2}')
        self.assertEqual(load_json('["src/auth","src/api"]'), ["src/auth", "src/api"])
        self.assertEqual(load_json('{"topic":"auth","count":2}'), ["topic:auth", "count:2"])
        self.assertEqual(load_json('"src/auth"'), ["src/auth"])
        self.assertEqual(
            merge_scopes(("src/auth",), ("src/api", "src/auth"), ("src/web",)),
            ("src/auth", "src/api", "src/web"),
        )
        self.assertTrue(scope_filter_matches(("src/auth",), ("src/auth",)))
        self.assertTrue(scope_filter_matches((), ("src/auth",)))
        self.assertFalse(scope_filter_matches(("src/web",), ("src/auth",)))

    def test_event_reference_helpers_normalize_dedupe_and_map_related_ids(self) -> None:
        payload = {
            "claim_id": "claim_01",
            "related_claim_id": "claim_01",
            "intent_id": "intent_02",
            "agent_id": "agent-b",
            "status": "read",
        }

        self.assertEqual(object_type_for_reference_key("agent_id"), "agent")
        self.assertEqual(object_type_for_reference_key("related_claim_id"), "claim")
        self.assertEqual(object_type_for_reference_key("context_id"), "context")
        self.assertIsNone(object_type_for_reference_key("status"))
        self.assertEqual(
            normalize_event_references(
                [("claim", "claim_01"), ("claim", "claim_01"), ("intent", "intent_02")]
            ),
            (("claim", "claim_01"), ("intent", "intent_02")),
        )
        self.assertEqual(
            event_references(actor_id="agent-a", payload=payload),
            (
                ("actor_id", "agent", "agent-a"),
                ("claim_id", "claim", "claim_01"),
                ("related_claim_id", "claim", "claim_01"),
                ("intent_id", "intent", "intent_02"),
                ("agent_id", "agent", "agent-b"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
