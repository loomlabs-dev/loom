from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import importlib.util


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
RUNNER = PROJECT_ROOT / "tools" / "run_benchmarks.py"
sys.path.insert(0, str(SRC_ROOT))

from loom.project import initialize_project, load_project  # noqa: E402

spec = importlib.util.spec_from_file_location("loom_run_benchmarks", RUNNER)
assert spec is not None and spec.loader is not None
run_benchmarks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_benchmarks)


class BenchmarkRunnerTest(unittest.TestCase):
    def test_runner_compacts_daemon_paths_for_benchmark_repos(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=run_benchmarks._benchmark_temp_root(),
            prefix=run_benchmarks.BENCHMARK_TEMP_PREFIXES["client_daemon"],
        ) as temp_dir:
            repo_root = pathlib.Path(temp_dir)
            (repo_root / ".git").mkdir()
            initialize_project(repo_root)

            run_benchmarks._configure_short_daemon_paths(repo_root)
            project = load_project(repo_root)

            self.assertEqual(project.socket_path.name, "d.sock")
            self.assertEqual(project.runtime_path.name, "d.json")
            self.assertEqual(project.log_path.name, "d.log")
            self.assertLess(len(str(project.socket_path)), 104)

    def test_runner_emits_json_report_for_mcp_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = pathlib.Path(temp_dir)
            env = os.environ.copy()
            existing_pythonpath = env.get("PYTHONPATH")
            env["PYTHONPATH"] = (
                f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
                if existing_pythonpath
                else str(SRC_ROOT)
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "--label",
                    "test",
                    "--rounds",
                    "1",
                    "--python-files",
                    "6",
                    "--script-files",
                    "6",
                    "--modes",
                    "mcp",
                    "--output-dir",
                    str(output_dir),
                ],
                cwd=PROJECT_ROOT,
                env=env,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, msg=result.stderr)
            json_reports = sorted(output_dir.glob("test-*.json"))
            self.assertEqual(len(json_reports), 1)
            report = json.loads(json_reports[0].read_text(encoding="utf-8"))
            operations = [
                measurement["operation"]
                for measurement in report["measurements"]
                if measurement["mode"] == "mcp"
            ]
            self.assertIn("mcp_initialize", operations)
            self.assertIn("init", operations)
            self.assertIn("start", operations)
            self.assertIn("claim", operations)


if __name__ == "__main__":
    unittest.main()
