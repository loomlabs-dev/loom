from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import ClaimRecord, ConflictRecord  # noqa: E402
from loom.mcp_graph import extract_agent_ids, extract_object_ids, resolve_agent_ids_from_object_ids  # noqa: E402


class _FakeStore:
    def __init__(
        self,
        *,
        claims: dict[str, ClaimRecord] | None = None,
        conflicts: dict[str, ConflictRecord] | None = None,
    ) -> None:
        self._claims = claims or {}
        self._conflicts = conflicts or {}

    def get_claim(self, object_id: str) -> ClaimRecord | None:
        return self._claims.get(object_id)

    def get_intent(self, object_id: str):
        return None

    def get_context(self, object_id: str):
        return None

    def get_conflict(self, object_id: str) -> ConflictRecord | None:
        return self._conflicts.get(object_id)


class McpGraphTest(unittest.TestCase):
    def test_extract_object_ids_handles_deep_nested_payload(self) -> None:
        value: object = "claim_deep_01"
        for _ in range(sys.getrecursionlimit() + 50):
            value = [value]

        self.assertEqual(extract_object_ids(value), {"claim_deep_01"})

    def test_extract_agent_ids_handles_self_referential_payload(self) -> None:
        payload: dict[str, object] = {"actor_id": "agent-loop"}
        payload["self"] = payload
        payload["nested"] = [{"agent_id": "agent-nested"}, payload]

        self.assertEqual(
            extract_agent_ids(payload),
            {"agent-loop", "agent-nested"},
        )

    def test_resolve_agent_ids_from_object_ids_handles_long_conflict_chain(self) -> None:
        chain_length = sys.getrecursionlimit() + 50
        claims: dict[str, ClaimRecord] = {}
        conflicts: dict[str, ConflictRecord] = {}
        expected_agent_ids: set[str] = set()

        for index in range(chain_length + 1):
            claim_id = f"claim_chain_{index:04d}"
            agent_id = f"agent-chain-{index:04d}"
            expected_agent_ids.add(agent_id)
            claims[claim_id] = ClaimRecord(
                id=claim_id,
                agent_id=agent_id,
                description="claim",
                scope=(f"src/feature_{index}.py",),
                status="active",
                created_at="2026-03-18T12:00:00Z",
            )

        for index in range(chain_length):
            conflict_id = f"conflict_chain_{index:04d}"
            next_object_id = (
                f"conflict_chain_{index + 1:04d}"
                if index + 1 < chain_length
                else f"claim_chain_{chain_length:04d}"
            )
            conflicts[conflict_id] = ConflictRecord(
                id=conflict_id,
                kind="scope_overlap",
                severity="warning",
                summary="conflict",
                object_type_a="conflict" if next_object_id.startswith("conflict_") else "claim",
                object_id_a=next_object_id,
                object_type_b="claim",
                object_id_b=f"claim_chain_{index:04d}",
                scope=(f"src/feature_{index}.py",),
                created_at="2026-03-18T12:00:00Z",
            )

        store = _FakeStore(claims=claims, conflicts=conflicts)

        self.assertEqual(
            resolve_agent_ids_from_object_ids(
                store,
                object_ids={"conflict_chain_0000"},
                visited=set(),
            ),
            expected_agent_ids,
        )


if __name__ == "__main__":
    unittest.main()
