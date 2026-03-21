from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli_scope import _infer_claim_scope, resolve_intent_scope  # noqa: E402


def init_repo_root(temp_dir: str) -> pathlib.Path:
    repo_root = pathlib.Path(temp_dir)
    (repo_root / ".git").mkdir()
    return repo_root


def write_file(repo_root: pathlib.Path, relative_path: str, contents: str = "pass\n") -> None:
    target = repo_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")


class CliScopeTest(unittest.TestCase):
    def test_infer_claim_scope_returns_low_confidence_unscoped_for_weak_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            write_file(repo_root, "api.py")

            scopes, inference = _infer_claim_scope(
                project_root=repo_root,
                description="api",
            )

        self.assertEqual(scopes, ())
        self.assertEqual(inference["mode"], "unscoped")
        self.assertEqual(inference["confidence"], "low")
        self.assertEqual(inference["matched_tokens"], ("api",))

    def test_infer_claim_scope_returns_ambiguous_for_disjoint_equal_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            write_file(repo_root, "src/auth/api.py")
            write_file(repo_root, "src/billing/api.py")

            scopes, inference = _infer_claim_scope(
                project_root=repo_root,
                description="api",
            )

        self.assertEqual(scopes, ())
        self.assertEqual(inference["mode"], "unscoped")
        self.assertEqual(inference["confidence"], "ambiguous")
        self.assertEqual(
            inference["candidate_scopes"],
            ("src/auth/api", "src/billing/api"),
        )

    def test_infer_claim_scope_returns_high_confidence_for_specific_multi_token_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            write_file(repo_root, "src/auth/session.py")
            write_file(repo_root, "src/auth/helpers.py")

            scopes, inference = _infer_claim_scope(
                project_root=repo_root,
                description="Refactor auth session flow",
            )

        self.assertEqual(scopes, ("src/auth/session",))
        self.assertEqual(inference["mode"], "inferred")
        self.assertTrue(inference["used"])
        self.assertEqual(inference["confidence"], "high")
        self.assertEqual(inference["matched_tokens"], ("auth", "session"))

    def test_resolve_intent_scope_wraps_unscoped_reason_with_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = init_repo_root(temp_dir)
            write_file(repo_root, "api.py")

            scopes, inference = resolve_intent_scope(
                project_root=repo_root,
                description="api",
                explicit_scope=[],
            )

        self.assertEqual(scopes, ())
        self.assertEqual(inference["mode"], "unscoped")
        self.assertIn("Provide --scope", inference["reason"])
        self.assertIn("weak repo path match", inference["reason"])


if __name__ == "__main__":
    unittest.main()
