from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.mcp_prompts import PromptExecutionError, build_prompts  # noqa: E402


class McpPromptsTest(unittest.TestCase):
    def test_build_prompts_exposes_expected_public_prompt_names(self) -> None:
        prompts = build_prompts()

        self.assertEqual(
            tuple(sorted(prompts)),
            (
                "adapt_or_wait",
                "coordinate_before_edit",
                "finish_and_release",
                "handoff_work",
                "resolve_conflict",
                "triage_inbox",
            ),
        )
        self.assertTrue(prompts["resolve_conflict"].describe()["arguments"][0]["required"])

    def test_coordinate_before_edit_prompt_includes_optional_scope_and_agent(self) -> None:
        prompts = build_prompts()

        payload = prompts["coordinate_before_edit"].handler(
            {
                "task": "Refactor auth flow",
                "scope": "src/auth",
                "agent_id": "agent-auth",
            }
        )

        message = payload["messages"][0]["content"]["text"]
        self.assertIn("Do not analyze Loom itself.", message)
        self.assertIn("Minimal loop: start, do the returned next_action, edit, finish.", message)
        self.assertIn("Command meanings:", message)
        self.assertIn("`loom://start` or `loom_start`: read the board and follow Loom's best next move first.", message)
        self.assertIn("`loom_bind`: pin this MCP session", message)
        self.assertIn("`loom_claim`: reserve the work before edits.", message)
        self.assertIn("`loom_finish`: release work cleanly", message)
        self.assertIn("Task: Refactor auth flow", message)
        self.assertIn("Act as Loom agent: agent-auth.", message)
        self.assertIn("Scope hint: src/auth", message)
        self.assertIn("Execute the `next_action`", message)
        self.assertIn("Re-run `loom://start` or `loom_start`", message)
        self.assertIn("call `loom_bind`", message)
        self.assertIn("call `loom_claim`", message)
        self.assertIn("Add `loom_intent` only when you are actually ready to edit", message)
        self.assertIn("Use `loom_finish` when you are done for now.", message)

    def test_coordinate_before_edit_prompt_surfaces_invalid_authority_context(self) -> None:
        prompts = build_prompts()

        payload = prompts["coordinate_before_edit"].handler(
            {"task": "Refactor auth flow"},
            {
                "start": {
                    "authority": {
                        "status": "invalid",
                        "issues": (
                            {"message": "missing file 'PRODUCT.md'"},
                        ),
                    }
                }
            },
        )

        message = payload["messages"][0]["content"]["text"]
        self.assertIn("Declared authority: `loom.yaml` is currently invalid.", message)
        self.assertIn("Authority issue: missing file 'PRODUCT.md'", message)
        self.assertIn(
            "Treat fixing declared repository truth as the first coordination move",
            message,
        )

    def test_coordinate_before_edit_prompt_surfaces_changed_authority_context(self) -> None:
        prompts = build_prompts()

        payload = prompts["coordinate_before_edit"].handler(
            {"task": "Refactor auth flow"},
            {
                "start": {
                    "authority": {
                        "status": "valid",
                        "surfaces": (
                            {"path": "PRODUCT.md", "role": "root_truth"},
                            {"path": "ROADMAP.md", "role": "policy"},
                        ),
                        "declaration_changed": True,
                        "changed_surfaces": (
                            {"path": "PRODUCT.md"},
                        ),
                    }
                }
            },
        )

        message = payload["messages"][0]["content"]["text"]
        self.assertIn("Declared authority surfaces: PRODUCT.md, ROADMAP.md", message)
        self.assertIn(
            "Declared authority changed recently; treat these surfaces as the first repo truth to coordinate: PRODUCT.md",
            message,
        )

    def test_coordinate_before_edit_prompt_surfaces_affected_active_work(self) -> None:
        prompts = build_prompts()

        payload = prompts["coordinate_before_edit"].handler(
            {"task": "Refactor auth flow"},
            {
                "start": {
                    "authority": {
                        "status": "valid",
                        "surfaces": (
                            {"path": "PRODUCT.md", "role": "root_truth"},
                        ),
                        "declaration_changed": False,
                        "changed_surfaces": (
                            {"path": "PRODUCT.md"},
                        ),
                        "affected_active_work": (
                            {
                                "kind": "claim",
                                "agent_id": "agent-a",
                                "overlap_scope": ("src/auth",),
                            },
                        ),
                    }
                }
            },
        )

        message = payload["messages"][0]["content"]["text"]
        self.assertIn(
            "Authority surfaces changed recently; treat these surfaces as the first repo truth to coordinate: PRODUCT.md",
            message,
        )
        self.assertIn(
            "Active work currently touching authority-affected scope: claim by agent-a on src/auth",
            message,
        )

    def test_finish_and_release_prompt_rejects_non_string_summary(self) -> None:
        prompts = build_prompts()

        with self.assertRaises(PromptExecutionError) as context:
            prompts["finish_and_release"].handler({"summary": 42})

        self.assertIn("summary must be a string", str(context.exception))

    def test_resolve_conflict_prompt_requires_non_empty_conflict_id(self) -> None:
        prompts = build_prompts()

        with self.assertRaises(PromptExecutionError) as context:
            prompts["resolve_conflict"].handler({"conflict_id": "   "})

        self.assertIn("conflict_id must be a non-empty string.", str(context.exception))

    def test_handoff_work_prompt_rejects_unexpected_arguments(self) -> None:
        prompts = build_prompts()

        with self.assertRaises(PromptExecutionError) as context:
            prompts["handoff_work"].handler(
                {
                    "task": "Hand off migration",
                    "scope": "src/migrations",
                    "unexpected": "value",
                }
            )

        self.assertIn("Unexpected arguments: unexpected.", str(context.exception))

    def test_handoff_work_prompt_includes_recipient_and_context_steps(self) -> None:
        prompts = build_prompts()

        payload = prompts["handoff_work"].handler(
            {
                "task": "Continue the API migration",
                "scope": "src/api",
                "recipient_agent": "agent-b",
            }
        )

        message = payload["messages"][0]["content"]["text"]
        self.assertIn("Task: Continue the API migration", message)
        self.assertIn("Scope hint: src/api", message)
        self.assertIn("Expected next agent: agent-b", message)
        self.assertIn("Publish a concise handoff note with `loom_context_write`", message)
        self.assertIn("call `loom_unclaim`", message)


if __name__ == "__main__":
    unittest.main()
