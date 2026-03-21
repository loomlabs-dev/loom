from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.authority import (  # noqa: E402
    LoomAuthorityError,
    load_authority_config,
    read_authority_summary,
)
from loom.local_store.records import ClaimRecord, IntentRecord  # noqa: E402


def _write_authority_file(repo_root: pathlib.Path, contents: str) -> None:
    (repo_root / "loom.yaml").write_text(contents, encoding="utf-8")


class AuthorityTest(unittest.TestCase):
    def test_committed_repository_authority_file_loads_cleanly(self) -> None:
        config = load_authority_config(PROJECT_ROOT)

        self.assertEqual(config.version, 1)
        self.assertEqual(len(config.surfaces), 3)
        self.assertEqual(config.surfaces[0].id, "readme")
        self.assertEqual(config.surfaces[0].path, "README.md")
        self.assertEqual(config.surfaces[0].role, "root_truth")
        self.assertEqual(config.surfaces[-1].id, "roadmap")
        self.assertEqual(config.surfaces[-1].path, "ROADMAP.md")

    def test_committed_repository_authority_summary_cascades_declared_surfaces(self) -> None:
        summary = read_authority_summary(
            PROJECT_ROOT,
            changed_paths=("loom.yaml",),
        )

        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["status"], "valid")
        self.assertTrue(summary["declaration_changed"])
        self.assertEqual(summary["surface_count"], 3)
        self.assertEqual(
            tuple(item["path"] for item in summary["changed_surfaces"]),
            (
                "README.md",
                "docs/alpha/ALPHA_0_1_CONTRACT.md",
                "ROADMAP.md",
            ),
        )

    def test_measrd_example_authority_file_loads_cleanly_when_stubbed(self) -> None:
        example_authority = (
            PROJECT_ROOT / "examples" / "authority" / "measrd" / "loom.yaml"
        ).read_text(encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            for line in example_authority.splitlines():
                stripped = line.strip()
                if not stripped.startswith("path: "):
                    continue
                relative_path = stripped.split(":", 1)[1].strip()
                target = repo_root / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f"{relative_path}\n", encoding="utf-8")
            _write_authority_file(repo_root, example_authority)

            config = load_authority_config(repo_root)

            self.assertEqual(config.version, 1)
            self.assertEqual(len(config.surfaces), 5)
            self.assertEqual(config.surfaces[0].id, "measrd-sot")
            self.assertEqual(
                tuple(surface.path for surface in config.surfaces),
                (
                    "MEASRD_SOT.md",
                    "FOUNDATION_STATUS.md",
                    "foundation/delivery/DECISION_CHECKPOINT_STATUS.yaml",
                    "foundation/delivery/FIRST_VERTICAL_SLICE_AUTHORIZATION.md",
                    "foundation/operations/LOOM_OPERATING_CONTRACT.md",
                ),
            )

    def test_load_authority_config_reads_valid_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "ROADMAP.md").write_text("roadmap\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      kind: document\n"
                "      description: Core truth.\n"
                "      topics:\n"
                "        - product\n"
                "        - strategy\n"
                "      scope_hints:\n"
                "        - src\n"
                "        - ROADMAP.md\n"
                "    - id: roadmap\n"
                "      path: ROADMAP.md\n"
                "      role: boundary\n",
            )

            config = load_authority_config(repo_root)

            self.assertEqual(config.version, 1)
            self.assertEqual(len(config.surfaces), 2)
            self.assertEqual(config.surfaces[0].id, "product")
            self.assertEqual(config.surfaces[0].path, "PRODUCT.md")
            self.assertEqual(config.surfaces[0].role, "root_truth")
            self.assertEqual(config.surfaces[0].topics, ("product", "strategy"))
            self.assertEqual(config.surfaces[0].scope_hints, ("src", "ROADMAP.md"))

    def test_load_authority_config_rejects_duplicate_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "A.md").write_text("a\n", encoding="utf-8")
            (repo_root / "B.md").write_text("b\n", encoding="utf-8")
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: duplicate\n"
                "      path: A.md\n"
                "      role: root_truth\n"
                "    - id: duplicate\n"
                "      path: B.md\n"
                "      role: policy\n",
            )

            with self.assertRaisesRegex(LoomAuthorityError, "duplicate surface id 'duplicate'"):
                load_authority_config(repo_root)

    def test_load_authority_config_rejects_outside_repo_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: outside\n"
                "      path: ../outside.md\n"
                "      role: root_truth\n",
            )

            with self.assertRaisesRegex(LoomAuthorityError, "must stay inside the repo"):
                load_authority_config(repo_root)

    def test_load_authority_config_rejects_missing_scope_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      scope_hints:\n"
                "        - src\n",
            )

            with self.assertRaisesRegex(LoomAuthorityError, "scope hint 'src' is missing"):
                load_authority_config(repo_root)

    def test_read_authority_summary_marks_changed_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "ROADMAP.md").write_text("roadmap\n", encoding="utf-8")
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "    - id: roadmap\n"
                "      path: ROADMAP.md\n"
                "      role: boundary\n",
            )

            summary = read_authority_summary(
                repo_root,
                changed_paths=("PRODUCT.md", "notes.md"),
            )

            self.assertTrue(summary["enabled"])
            self.assertEqual(summary["status"], "valid")
            self.assertEqual(summary["surface_count"], 2)
            self.assertEqual(
                tuple(item["path"] for item in summary["changed_surfaces"]),
                ("PRODUCT.md",),
            )
            self.assertEqual(tuple(summary["changed_scope_hints"]), ())

    def test_read_authority_summary_surfaces_changed_scope_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (repo_root / "docs").mkdir()
            (repo_root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      scope_hints:\n"
                "        - src\n"
                "        - docs/guide.md\n",
            )

            summary = read_authority_summary(
                repo_root,
                changed_paths=("PRODUCT.md",),
            )

            self.assertEqual(
                tuple(summary["changed_scope_hints"]),
                ("src", "docs/guide.md"),
            )

    def test_read_authority_summary_cascades_when_declaration_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "ROADMAP.md").write_text("roadmap\n", encoding="utf-8")
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "    - id: roadmap\n"
                "      path: ROADMAP.md\n"
                "      role: boundary\n",
            )

            summary = read_authority_summary(
                repo_root,
                changed_paths=("loom.yaml",),
            )

            self.assertTrue(summary["declaration_changed"])
            self.assertEqual(
                tuple(item["path"] for item in summary["changed_surfaces"]),
                ("PRODUCT.md", "ROADMAP.md"),
            )

    def test_read_authority_summary_surfaces_affected_active_work_for_changed_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n"
                "      scope_hints:\n"
                "        - src\n",
            )

            summary = read_authority_summary(
                repo_root,
                changed_paths=("PRODUCT.md",),
                claims=(
                    ClaimRecord(
                        id="claim_1",
                        agent_id="agent-a",
                        description="Touch app code",
                        scope=("src",),
                        status="active",
                        created_at="2026-03-20T00:00:00Z",
                    ),
                ),
                intents=(
                    IntentRecord(
                        id="intent_1",
                        agent_id="agent-b",
                        description="Touch app runtime",
                        reason="Need runtime follow-up",
                        scope=("src/app.py",),
                        status="active",
                        created_at="2026-03-20T00:00:00Z",
                        related_claim_id=None,
                    ),
                ),
            )

            self.assertEqual(summary["changed_scope_hints"], ("src",))
            self.assertEqual(len(summary["affected_active_work"]), 2)
            self.assertEqual(summary["affected_active_work"][0]["kind"], "claim")
            self.assertEqual(summary["affected_active_work"][0]["agent_id"], "agent-a")
            self.assertEqual(summary["affected_active_work"][1]["kind"], "intent")
            self.assertEqual(summary["affected_active_work"][1]["agent_id"], "agent-b")

    def test_read_authority_summary_surfaces_invalid_config_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: broken\n"
                "      path: MISSING.md\n"
                "      role: root_truth\n",
            )

            summary = read_authority_summary(repo_root)

            self.assertTrue(summary["enabled"])
            self.assertEqual(summary["status"], "invalid")
            self.assertEqual(summary["error_code"], "invalid_authority_config")
            self.assertEqual(summary["surface_count"], 0)
            self.assertIn("missing file 'MISSING.md'", summary["issues"][0]["message"])


if __name__ == "__main__":
    unittest.main()
