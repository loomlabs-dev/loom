from __future__ import annotations

import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

import loom.project as project_module  # noqa: E402
from loom.project import (  # noqa: E402
    LoomProjectError,
    initialize_project,
    load_project,
    set_default_agent,
    set_terminal_agent,
)


class ProjectTest(unittest.TestCase):
    def test_load_project_rejects_malformed_json_config_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            project, _ = initialize_project(repo_root)
            project.config_path.write_text("{not-json", encoding="utf-8")

            with self.assertRaisesRegex(LoomProjectError, "Invalid Loom config"):
                load_project(project.repo_root)

    def test_load_project_rejects_non_object_config_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            project, _ = initialize_project(repo_root)
            project.config_path.write_text('["not", "an", "object"]\n', encoding="utf-8")

            with self.assertRaisesRegex(LoomProjectError, "Invalid Loom config"):
                load_project(project.repo_root)

    def test_load_project_rejects_invalid_typed_config_values_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            project, _ = initialize_project(repo_root)
            project.config_path.write_text(
                '{\n'
                '  "schema_version": "oops",\n'
                '  "database": 123\n'
                '}\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(LoomProjectError, "Invalid Loom config"):
                load_project(project.repo_root)

    def test_update_config_rejects_corrupted_config_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            project, _ = initialize_project(repo_root)
            project.config_path.write_text("{broken", encoding="utf-8")

            with self.assertRaisesRegex(LoomProjectError, "Invalid Loom config"):
                project_module._update_config(
                    project.config_path,
                    lambda config: config.__setitem__("default_agent", "agent-a"),
                )

    def test_concurrent_config_updates_preserve_both_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            project, _ = initialize_project(repo_root)
            entered_write = threading.Event()
            release_write = threading.Event()
            original_write = project_module._write_config_unlocked
            delay_once = True
            errors: list[BaseException] = []

            def delayed_write(config_path: pathlib.Path, config: dict[str, object]) -> None:
                nonlocal delay_once
                aliases = dict(config.get("terminal_aliases", {}))
                if delay_once and config.get("default_agent") == "agent-a" and "tty-b" not in aliases:
                    delay_once = False
                    entered_write.set()
                    self.assertTrue(release_write.wait(timeout=1))
                original_write(config_path, config)

            def set_default() -> None:
                try:
                    set_default_agent("agent-a", project.repo_root)
                except BaseException as error:  # pragma: no cover - failure path assertion
                    errors.append(error)

            def set_terminal() -> None:
                try:
                    set_terminal_agent(
                        "agent-b",
                        terminal_identity="tty-b",
                        start=project.repo_root,
                    )
                except BaseException as error:  # pragma: no cover - failure path assertion
                    errors.append(error)

            with patch("loom.project._write_config_unlocked", side_effect=delayed_write):
                first = threading.Thread(target=set_default, name="set-default")
                second = threading.Thread(target=set_terminal, name="set-terminal")
                first.start()
                self.assertTrue(entered_write.wait(timeout=1))
                second.start()
                time.sleep(0.05)
                self.assertTrue(second.is_alive())
                release_write.set()
                first.join(timeout=1)
                second.join(timeout=1)

            self.assertEqual(errors, [])
            updated_project = load_project(project.repo_root)
            self.assertEqual(updated_project.default_agent, "agent-a")
            self.assertEqual(updated_project.terminal_aliases, {"tty-b": "agent-b"})

    def test_write_config_preserves_existing_file_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            project, _ = initialize_project(repo_root)
            original_text = project.config_path.read_text(encoding="utf-8")
            updated_config = dict(project_module._read_config(project.config_path))
            updated_config["default_agent"] = "agent-a"

            with patch("loom.project.os.replace", side_effect=OSError("replace_failed")):
                with self.assertRaises(OSError):
                    project_module._write_config(project.config_path, updated_config)

            self.assertEqual(project.config_path.read_text(encoding="utf-8"), original_text)
            self.assertEqual(
                sorted(path.name for path in project.config_path.parent.glob(f".{project.config_path.name}.*.tmp")),
                [],
            )


if __name__ == "__main__":
    unittest.main()
