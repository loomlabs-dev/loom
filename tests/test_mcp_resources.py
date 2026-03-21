from __future__ import annotations

import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.mcp_resources import (  # noqa: E402
    activity_feed_target,
    build_resource_templates,
    build_resource_uris,
    build_resources,
    dynamic_resource_target,
    project_resource_uris,
)


def _reader(name: str):
    def _read() -> dict[str, str]:
        return {"name": name}

    return _read


class McpResourcesTest(unittest.TestCase):
    def test_build_resources_without_project_exposes_only_global_resources(self) -> None:
        resources = build_resources(
            project_available=False,
            read_protocol=_reader("protocol"),
            read_start=_reader("start"),
            read_identity=_reader("identity"),
            read_mcp=_reader("mcp"),
            read_activity=_reader("activity"),
            read_log=_reader("log"),
            read_context_feed=_reader("context"),
            read_status=_reader("status"),
            read_agents=_reader("agents"),
            read_conflicts=_reader("conflicts"),
            read_conflict_history=_reader("history"),
            read_agent=_reader("agent"),
            read_inbox=_reader("inbox"),
        )

        self.assertEqual(
            build_resource_uris(resources),
            (
                "loom://protocol",
                "loom://start",
                "loom://identity",
                "loom://mcp",
            ),
        )

    def test_build_resources_with_project_exposes_repo_resources(self) -> None:
        resources = build_resources(
            project_available=True,
            read_protocol=_reader("protocol"),
            read_start=_reader("start"),
            read_identity=_reader("identity"),
            read_mcp=_reader("mcp"),
            read_activity=_reader("activity"),
            read_log=_reader("log"),
            read_context_feed=_reader("context"),
            read_status=_reader("status"),
            read_agents=_reader("agents"),
            read_conflicts=_reader("conflicts"),
            read_conflict_history=_reader("history"),
            read_agent=_reader("agent"),
            read_inbox=_reader("inbox"),
        )

        self.assertEqual(
            project_resource_uris(
                resource_map={resource.uri: resource for resource in resources},
                include_identity=True,
            ),
            (
                "loom://identity",
                "loom://start",
                "loom://mcp",
                "loom://activity",
                "loom://log",
                "loom://context",
                "loom://status",
                "loom://agents",
                "loom://conflicts",
                "loom://conflicts/history",
                "loom://agent",
                "loom://inbox",
            ),
        )

    def test_dynamic_resource_target_prefers_alias_and_rejects_inline_timeline_suffix(self) -> None:
        self.assertEqual(
            dynamic_resource_target(
                "loom://claim/claim_123/timeline",
                timeline_object_id_for_alias_uri=lambda uri: "claim_123" if uri.endswith("/timeline") else None,
            ),
            ("timeline", "claim_123"),
        )
        self.assertIsNone(
            dynamic_resource_target(
                "loom://claim/claim_123/timeline",
                timeline_object_id_for_alias_uri=lambda uri: None,
            )
        )
        self.assertEqual(
            dynamic_resource_target(
                "loom://event/42",
                timeline_object_id_for_alias_uri=lambda uri: None,
            ),
            ("event", "42"),
        )

    def test_activity_feed_target_and_templates_cover_public_feed_surface(self) -> None:
        templates = build_resource_templates()
        template_uris = {template.uri_template for template in templates}

        self.assertIn("loom://activity/{agent_id}/after/{sequence}", template_uris)
        self.assertIn("loom://events/after/{sequence}", template_uris)
        self.assertEqual(
            activity_feed_target(
                "loom://activity/agent-a/after/17",
                after_sequence=int,
            ),
            ("agent-a", 17),
        )
        self.assertIsNone(
            activity_feed_target(
                "loom://activity/agent-a",
                after_sequence=int,
            )
        )


if __name__ == "__main__":
    unittest.main()
