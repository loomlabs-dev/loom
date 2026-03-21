from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli import main  # noqa: E402


@contextlib.contextmanager
def working_directory(path: pathlib.Path):
    previous = pathlib.Path.cwd()
    os.chdir(path)
    try:
        yield path
    finally:
        os.chdir(previous)


def _write_authority_file(repo_root: pathlib.Path, contents: str) -> None:
    (repo_root / "loom.yaml").write_text(contents, encoding="utf-8")


def _init_git_repo(repo_root: pathlib.Path) -> None:
    subprocess.run(
        ("git", "-C", str(repo_root), "init", "-q"),
        check=True,
        capture_output=True,
        text=True,
    )


def _commit_all(repo_root: pathlib.Path, message: str) -> None:
    subprocess.run(
        ("git", "-C", str(repo_root), "config", "user.email", "loom-tests@example.com"),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repo_root), "config", "user.name", "Loom Tests"),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repo_root), "add", "."),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "-C", str(repo_root), "commit", "-q", "-m", message),
        check=True,
        capture_output=True,
        text=True,
    )


class CliAuthorityTest(unittest.TestCase):
    def test_start_json_includes_valid_authority_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["authority"]["status"], "valid")
            self.assertEqual(payload["authority"]["surface_count"], 1)
            self.assertEqual(payload["authority"]["surfaces"][0]["path"], "PRODUCT.md")
            self.assertEqual(payload["authority"]["changed_surfaces"][0]["path"], "PRODUCT.md")

    def test_start_human_output_mentions_declared_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start"]), 0)

            output = stdout.getvalue()
            self.assertIn("Authority:", output)
            self.assertIn("1 declared surface(s) in loom.yaml", output)
            self.assertIn("changed authority surface(s): 1", output)
            self.assertIn("PRODUCT.md (root_truth)", output)

    def test_start_json_promotes_declaration_change_to_authority_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["mode"], "attention")
            self.assertIn("Declared authority changed", payload["summary"])
            self.assertTrue(payload["authority"]["declaration_changed"])
            self.assertEqual(payload["next_action"]["command"], 'loom claim "Describe the work you\'re starting" --scope PRODUCT.md')
            self.assertEqual(payload["next_action"]["kind"], "authority")
            self.assertEqual(payload["next_steps"][0], 'loom claim "Describe the work you\'re starting" --scope PRODUCT.md')

    def test_status_json_promotes_declaration_change_to_authority_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["status", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["authority"]["declaration_changed"])
            self.assertEqual(payload["next_action"]["command"], 'loom claim "Describe the work you\'re starting" --scope PRODUCT.md')
            self.assertEqual(payload["next_action"]["kind"], "authority")

    def test_start_json_promotes_changed_authority_surface_to_authority_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

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
            _commit_all(repo_root, "declare authority")
            (repo_root / "PRODUCT.md").write_text("product changed\n", encoding="utf-8")

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["authority"]["declaration_changed"])
            self.assertEqual(payload["mode"], "attention")
            self.assertIn("Authority surfaces changed", payload["summary"])
            self.assertEqual(
                payload["next_action"]["command"],
                'loom claim "Describe the work you\'re starting" --scope src',
            )
            self.assertEqual(payload["next_action"]["kind"], "authority")

    def test_start_json_uses_scope_hints_for_declaration_change_focus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (repo_root / "docs").mkdir()
            (repo_root / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

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

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(
                payload["authority"]["changed_scope_hints"],
                ["src", "docs/guide.md"],
            )
            self.assertEqual(
                payload["next_action"]["command"],
                'loom claim "Describe the work you\'re starting" --scope src --scope docs/guide.md',
            )
            self.assertIn("mapped repo areas", payload["next_action"]["reason"])

    def test_start_human_output_mentions_changed_scope_hints(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

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

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start"]), 0)

            output = stdout.getvalue()
            self.assertIn("changed authority scope hint(s): 1", output)
            self.assertIn("  - src", output)
            self.assertIn('next: loom claim "Describe the work you\'re starting" --scope src', output)

    def test_start_human_output_promotes_declaration_change_to_authority_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: product\n"
                "      path: PRODUCT.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start"]), 0)

            output = stdout.getvalue()
            self.assertIn("Summary: Declared authority changed; coordinate the affected truth surfaces before other work.", output)
            self.assertIn('next: loom claim "Describe the work you\'re starting" --scope PRODUCT.md', output)

    def test_start_json_surfaces_affected_active_work_for_changed_authority_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

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
            _commit_all(repo_root, "declare authority")

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["claim", "Touch app code", "--scope", "src"]), 0)

            (repo_root / "PRODUCT.md").write_text("product changed\n", encoding="utf-8")

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["authority"]["declaration_changed"])
            self.assertEqual(
                tuple(item["path"] for item in payload["authority"]["changed_surfaces"]),
                ("PRODUCT.md",),
            )
            self.assertEqual(payload["authority"]["changed_scope_hints"], ["src"])
            self.assertEqual(len(payload["authority"]["affected_active_work"]), 1)
            self.assertEqual(payload["authority"]["affected_active_work"][0]["kind"], "claim")
            self.assertEqual(payload["authority"]["affected_active_work"][0]["agent_id"], "agent-a")

    def test_status_human_output_mentions_affected_active_work_for_authority_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            (repo_root / "PRODUCT.md").write_text("product\n", encoding="utf-8")
            (repo_root / "src").mkdir()
            (repo_root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            _commit_all(repo_root, "seed product")
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

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
            _commit_all(repo_root, "declare authority")

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["claim", "Touch app code", "--scope", "src"]), 0)

            (repo_root / "PRODUCT.md").write_text("product changed\n", encoding="utf-8")

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["status"]), 0)

            output = stdout.getvalue()
            self.assertIn("changed authority surface(s): 1", output)
            self.assertIn("affected active work: 1", output)
            self.assertIn("claim by agent-a on src", output)

    def test_status_json_includes_invalid_authority_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: missing\n"
                "      path: DOES_NOT_EXIST.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["status", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["authority"]["status"], "invalid")
            self.assertEqual(payload["authority"]["error_code"], "invalid_authority_config")
            self.assertEqual(payload["next_action"]["command"], "fix loom.yaml")
            self.assertEqual(payload["next_action"]["kind"], "authority")
            self.assertEqual(payload["next_steps"][0], "fix loom.yaml")
            self.assertIn(
                "Fix loom.yaml and run `loom start` or `loom status` again.",
                payload["authority"]["next_steps"],
            )

    def test_start_json_with_invalid_authority_promotes_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: missing\n"
                "      path: DOES_NOT_EXIST.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start", "--json"]), 0)

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["mode"], "attention")
            self.assertIn("Declared authority is invalid in loom.yaml", payload["summary"])
            self.assertEqual(payload["next_action"]["command"], "fix loom.yaml")
            self.assertEqual(payload["next_action"]["kind"], "authority")
            self.assertEqual(payload["next_steps"][0], "fix loom.yaml")

    def test_status_human_output_surfaces_invalid_authority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: missing\n"
                "      path: DOES_NOT_EXIST.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["status"]), 0)

            output = stdout.getvalue()
            self.assertIn("Authority:", output)
            self.assertIn("invalid declaration in loom.yaml", output)
            self.assertIn("missing file 'DOES_NOT_EXIST.md'", output)
            self.assertIn("- fix loom.yaml", output)
            self.assertIn("Fix loom.yaml and run `loom start` or `loom status` again.", output)

    def test_start_human_output_with_invalid_authority_suppresses_normal_claim_loop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            _init_git_repo(repo_root)
            stdout = io.StringIO()

            with working_directory(repo_root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["init", "--no-daemon", "--agent", "agent-a"]), 0)

            _write_authority_file(
                repo_root,
                "version: 1\n"
                "authority:\n"
                "  surfaces:\n"
                "    - id: missing\n"
                "      path: DOES_NOT_EXIST.md\n"
                "      role: root_truth\n",
            )

            with working_directory(repo_root), contextlib.redirect_stdout(stdout):
                self.assertEqual(main(["start"]), 0)

            output = stdout.getvalue()
            self.assertIn("Do this first: Fix the declared authority configuration in loom.yaml.", output)
            self.assertNotIn("Quick loop:", output)
            self.assertNotIn("Reserve the work before edits.", output)


if __name__ == "__main__":
    unittest.main()
