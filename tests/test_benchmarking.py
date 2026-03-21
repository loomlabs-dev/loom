from __future__ import annotations

import json
import pathlib
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.benchmarking import (  # noqa: E402
    BenchmarkMeasurement,
    build_benchmark_report,
    format_summary_table,
    render_benchmark_report_html,
    summarize_measurements,
)


class BenchmarkingTest(unittest.TestCase):
    def test_summarize_measurements_groups_modes_and_handles_failures(self) -> None:
        summaries = summarize_measurements(
            (
                BenchmarkMeasurement(
                    mode="cli",
                    operation="claim",
                    round_index=0,
                    duration_ms=12.0,
                ),
                BenchmarkMeasurement(
                    mode="cli",
                    operation="claim",
                    round_index=1,
                    duration_ms=18.0,
                ),
                BenchmarkMeasurement(
                    mode="cli",
                    operation="claim",
                    round_index=2,
                    duration_ms=None,
                    ok=False,
                    detail="failed",
                ),
                BenchmarkMeasurement(
                    mode="mcp",
                    operation="status",
                    round_index=0,
                    duration_ms=5.0,
                ),
            )
        )

        self.assertEqual(len(summaries), 2)
        cli_summary = summaries[0]
        self.assertEqual(cli_summary.mode, "cli")
        self.assertEqual(cli_summary.operation, "claim")
        self.assertEqual(cli_summary.samples, 3)
        self.assertEqual(cli_summary.successes, 2)
        self.assertEqual(cli_summary.failures, 1)
        self.assertEqual(cli_summary.min_ms, 12.0)
        self.assertEqual(cli_summary.median_ms, 15.0)
        self.assertEqual(cli_summary.max_ms, 18.0)

    def test_report_rendering_includes_summary_and_raw_json(self) -> None:
        report = build_benchmark_report(
            label="quick",
            scenario={
                "rounds": 2,
                "python_files": 50,
                "script_files": 50,
                "modes": ["client_direct", "cli"],
            },
            measurements=[
                BenchmarkMeasurement(
                    mode="client_direct",
                    operation="status",
                    round_index=0,
                    duration_ms=7.25,
                ),
                BenchmarkMeasurement(
                    mode="client_direct",
                    operation="status",
                    round_index=1,
                    duration_ms=8.0,
                ),
            ],
            notes=["daemon mode skipped in this run"],
        )

        table = format_summary_table(report)
        html = render_benchmark_report_html(report)

        self.assertIn("client_direct", table)
        self.assertIn("status", table)
        self.assertIn("Loom Benchmark Report", html)
        self.assertIn("daemon mode skipped in this run", html)
        self.assertIn("\"label\": \"quick\"", html)
        self.assertIn("client_direct", html)
        self.assertIn("status", html)
        self.assertTrue(json.loads(json.dumps(report)))


if __name__ == "__main__":
    unittest.main()
