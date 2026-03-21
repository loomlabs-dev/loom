from __future__ import annotations

import pathlib
import subprocess
import sys
import unittest


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEMO_SCRIPT = PROJECT_ROOT / "examples" / "two-agent-demo" / "run_demo.py"


class TwoAgentDemoTest(unittest.TestCase):
    def test_demo_script_runs_end_to_end(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(DEMO_SCRIPT)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )

        output = completed.stdout
        self.assertIn("# Loom Two-Agent Demo", output)
        self.assertIn("$ loom init --no-daemon", output)
        self.assertIn("$ loom conflicts", output)
        self.assertIn("$ loom unclaim --agent agent-a", output)
        self.assertIn("Conflicts detected:", output)
        self.assertIn("Context dependencies surfaced:", output)
        self.assertIn("Open conflicts (2):", output)
        self.assertIn("contextual_dependency", output)
        self.assertIn("Claim released:", output)
        self.assertIn("Recent events", output)
        self.assertIn("Demo complete.", output)


if __name__ == "__main__":
    unittest.main()
