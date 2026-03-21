from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


class EntrypointTest(unittest.TestCase):
    def test_python_module_entrypoint_supports_version_flag(self) -> None:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else str(SRC_ROOT)
        )

        result = subprocess.run(
            [sys.executable, "-m", "loom", "--version"],
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("0.1.0a0", result.stdout)

    def test_python_module_entrypoint_help_shows_quick_start(self) -> None:
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else str(SRC_ROOT)
        )

        result = subprocess.run(
            [sys.executable, "-m", "loom", "--help"],
            cwd=PROJECT_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Start here:", result.stdout)
        self.assertIn("loom start", result.stdout)
        self.assertIn("loom init --no-daemon", result.stdout)
        self.assertIn("Core loop:", result.stdout)
        self.assertIn("claim    say what you're working on", result.stdout)


if __name__ == "__main__":
    unittest.main()
