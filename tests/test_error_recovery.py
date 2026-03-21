from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.action_errors import (  # noqa: E402
    ContextNotFoundError,
    NoActiveWorkError,
)
from loom.cli_actions import error_next_steps  # noqa: E402
from loom.mcp_steps import tool_error_next_steps  # noqa: E402
from loom.project import ProjectNotInitializedError  # noqa: E402


class ErrorRecoveryTest(unittest.TestCase):
    def test_cli_error_next_steps_prefers_project_not_initialized_type(self) -> None:
        error = ProjectNotInitializedError("Completely custom init wording.")

        self.assertEqual(error_next_steps(error), ("loom init --no-daemon",))

    def test_cli_error_next_steps_prefers_no_active_work_type(self) -> None:
        error = NoActiveWorkError(
            "agent-a",
            detail="Use --note to publish a handoff without active work.",
        )

        self.assertEqual(
            error_next_steps(error),
            (
                "loom status",
                'loom finish --note "What changed and what matters next."',
            ),
        )

    def test_mcp_error_next_steps_prefers_context_not_found_type(self) -> None:
        error = ContextNotFoundError("context_missing")

        self.assertEqual(
            tool_error_next_steps(error),
            (
                "Call loom_context_read to re-read recent shared context.",
                "Call loom_inbox for the affected agent.",
            ),
        )

    def test_cli_error_next_steps_uses_shared_string_fallback_classifier(self) -> None:
        self.assertEqual(
            error_next_steps("Conflict not found: conflict_123."),
            (
                "loom conflicts",
                "loom status",
            ),
        )

    def test_mcp_error_next_steps_uses_shared_invalid_argument_classifier(self) -> None:
        self.assertEqual(
            tool_error_next_steps("Unexpected arguments: extra."),
            ("Call loom_protocol to inspect the supported tool schemas.",),
        )


if __name__ == "__main__":
    unittest.main()
