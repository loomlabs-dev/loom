from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.local_store import ClaimRecord  # noqa: E402
from loom.util import (  # noqa: E402
    current_git_branch,
    current_worktree_paths,
    infer_object_type,
    is_past_utc_timestamp,
    is_stale_utc_timestamp,
    json_ready,
    normalize_lease_policy,
    normalize_scope,
    normalize_scopes,
    overlapping_scopes,
    parse_utc_timestamp,
    utc_after_minutes,
)


@dataclasses.dataclass(frozen=True)
class DemoPayload:
    root: pathlib.Path
    claim: ClaimRecord
    tags: tuple[str, ...]


class UtilTest(unittest.TestCase):
    def test_utc_after_minutes_uses_reference_timestamp(self) -> None:
        self.assertEqual(
            utc_after_minutes(15, from_timestamp="2026-03-18T12:00:00Z"),
            "2026-03-18T12:15:00Z",
        )

    def test_utc_after_minutes_rejects_non_positive_values(self) -> None:
        with self.assertRaises(ValueError):
            utc_after_minutes(0)

    def test_parse_and_age_helpers_normalize_timestamp_inputs(self) -> None:
        reference = datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc)

        self.assertEqual(
            parse_utc_timestamp("2026-03-18T12:00:00"),
            reference,
        )
        self.assertTrue(
            is_stale_utc_timestamp(
                "2026-03-18T03:00:00Z",
                now=reference,
            )
        )
        self.assertTrue(
            is_past_utc_timestamp(
                "2026-03-18T12:00:00Z",
                now=reference,
            )
        )

    def test_normalize_lease_policy_trims_and_validates_values(self) -> None:
        self.assertEqual(normalize_lease_policy(" Yield "), "yield")
        self.assertIsNone(normalize_lease_policy(None, allow_none=True))
        with self.assertRaises(ValueError):
            normalize_lease_policy("pause")

    def test_normalize_scope_and_scopes_dedupe_and_strip_globs(self) -> None:
        self.assertEqual(normalize_scope("src\\api/**"), "src/api")
        self.assertEqual(
            normalize_scopes(
                ("src/api", "./src/api/*", "tests", "tests")
            ),
            ("src/api", "tests"),
        )

    def test_current_git_branch_reads_plain_git_dir_and_gitdir_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            git_dir = repo_root / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text(
                "ref: refs/heads/main\n",
                encoding="utf-8",
            )
            self.assertEqual(current_git_branch(repo_root), "main")

        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            actual_git_dir = repo_root / ".cache" / "git-dir"
            actual_git_dir.mkdir(parents=True)
            (repo_root / ".git").write_text(
                "gitdir: .cache/git-dir\n",
                encoding="utf-8",
            )
            (actual_git_dir / "HEAD").write_text(
                "ref: refs/heads/feature/refactor\n",
                encoding="utf-8",
            )
            self.assertEqual(current_git_branch(repo_root), "feature/refactor")

    def test_current_worktree_paths_dedupes_and_normalizes_git_output(self) -> None:
        repo_root = PROJECT_ROOT
        modified = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="src/api.py\nsrc\\auth\\session.py\n\n",
        )
        cached = subprocess.CompletedProcess(
            args=(),
            returncode=0,
            stdout="src/auth/session.py\nREADME.md\n",
        )

        with patch(
            "loom.util.subprocess.run",
            side_effect=(modified, cached),
        ) as run_mock:
            paths = current_worktree_paths(repo_root)

        self.assertEqual(
            paths,
            ("src/api.py", "src/auth/session.py", "README.md"),
        )
        self.assertEqual(run_mock.call_count, 2)

    def test_current_worktree_paths_returns_empty_on_git_failure(self) -> None:
        repo_root = PROJECT_ROOT
        with patch(
            "loom.util.subprocess.run",
            return_value=subprocess.CompletedProcess(args=(), returncode=1, stdout=""),
        ):
            self.assertEqual(current_worktree_paths(repo_root), ())

    def test_json_ready_serializes_dataclasses_paths_and_tuples(self) -> None:
        payload = DemoPayload(
            root=PROJECT_ROOT,
            claim=ClaimRecord(
                id="claim_123",
                agent_id="agent-a",
                description="Claimed work",
                scope=("src/api",),
                status="active",
                created_at="2026-03-18T12:00:00Z",
                git_branch="main",
                lease_expires_at=None,
                lease_policy=None,
            ),
            tags=("alpha", "beta"),
        )

        self.assertEqual(
            json_ready(payload),
            {
                "root": str(PROJECT_ROOT),
                "claim": {
                    "id": "claim_123",
                    "agent_id": "agent-a",
                    "description": "Claimed work",
                    "scope": ["src/api"],
                    "status": "active",
                    "created_at": "2026-03-18T12:00:00Z",
                    "git_branch": "main",
                    "lease_expires_at": None,
                    "lease_policy": None,
                },
                "tags": ["alpha", "beta"],
            },
        )

    def test_infer_object_type_and_overlapping_scopes_cover_common_cases(self) -> None:
        self.assertEqual(infer_object_type("claim_abc"), "claim")
        self.assertEqual(
            overlapping_scopes(
                ("src/api", "tests"),
                ("src/api/handlers.py", "docs"),
            ),
            ("src/api/handlers.py",),
        )
        self.assertEqual(
            overlapping_scopes(
                (".",),
                ("src/api",),
            ),
            (".",),
        )
        with self.assertRaises(ValueError):
            infer_object_type("event_123")


if __name__ == "__main__":
    unittest.main()
