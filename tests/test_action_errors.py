from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.action_errors import (  # noqa: E402
    ConflictNotFoundError,
    ContextNotFoundError,
    LoomActionError,
    NoActiveClaimError,
    NoActiveWorkError,
    ObjectNotFoundError,
    WhoamiSelectionError,
    recoverable_error_code,
)
from loom.project import ProjectNotInitializedError  # noqa: E402


class ActionErrorsTest(unittest.TestCase):
    def test_all_typed_action_errors_inherit_from_stable_base(self) -> None:
        errors = (
            NoActiveClaimError("agent-a"),
            NoActiveWorkError("agent-a"),
            ConflictNotFoundError("conflict_123"),
            ContextNotFoundError("context_123"),
            ObjectNotFoundError("claim_123"),
            WhoamiSelectionError(),
        )

        for error in errors:
            self.assertIsInstance(error, LoomActionError)
            self.assertIsInstance(error, ValueError)

    def test_no_active_claim_error_carries_agent_id_and_message(self) -> None:
        error = NoActiveClaimError("agent-a")

        self.assertEqual(error.agent_id, "agent-a")
        self.assertEqual(str(error), "No active claim for agent-a.")

    def test_no_active_work_error_preserves_optional_detail(self) -> None:
        plain = NoActiveWorkError("agent-a")
        detailed = NoActiveWorkError(
            "agent-b",
            detail="Run `loom claim` or `loom intent` first.",
        )

        self.assertEqual(plain.agent_id, "agent-a")
        self.assertIsNone(plain.detail)
        self.assertEqual(str(plain), "No active claim or intent for agent-a.")
        self.assertEqual(detailed.agent_id, "agent-b")
        self.assertEqual(detailed.detail, "Run `loom claim` or `loom intent` first.")
        self.assertEqual(
            str(detailed),
            "No active claim or intent for agent-b. Run `loom claim` or `loom intent` first.",
        )

    def test_missing_object_errors_preserve_ids_and_messages(self) -> None:
        conflict = ConflictNotFoundError("conflict_123")
        context = ContextNotFoundError("context_123")
        object_error = ObjectNotFoundError("claim_123")

        self.assertEqual(conflict.conflict_id, "conflict_123")
        self.assertEqual(str(conflict), "Conflict not found: conflict_123.")
        self.assertEqual(context.context_id, "context_123")
        self.assertEqual(str(context), "Context not found: context_123.")
        self.assertEqual(object_error.object_id, "claim_123")
        self.assertEqual(str(object_error), "Object not found: claim_123.")

    def test_whoami_selection_error_message_stays_stable(self) -> None:
        self.assertEqual(
            str(WhoamiSelectionError()),
            "Choose only one of --set, --bind, or --unbind.",
        )

    def test_recoverable_error_code_prefers_typed_codes(self) -> None:
        self.assertEqual(
            recoverable_error_code(ProjectNotInitializedError("custom init wording")),
            "project_not_initialized",
        )
        self.assertEqual(
            recoverable_error_code(NoActiveClaimError("agent-a")),
            "no_active_claim",
        )
        self.assertEqual(
            recoverable_error_code(WhoamiSelectionError()),
            "whoami_selection",
        )

    def test_recoverable_error_code_classifies_string_fallbacks(self) -> None:
        self.assertEqual(
            recoverable_error_code("Conflict not found: conflict_123."),
            "conflict_not_found",
        )
        self.assertEqual(
            recoverable_error_code("Unexpected arguments: extra."),
            "invalid_arguments",
        )
        self.assertEqual(
            recoverable_error_code("Run `loom init` first in this repository."),
            "project_not_initialized",
        )
        self.assertIsNone(recoverable_error_code("Completely unrelated failure"))


if __name__ == "__main__":
    unittest.main()
