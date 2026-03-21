from __future__ import annotations

import argparse
import contextlib
import io
import os
import shutil
import sys
import tempfile
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = WORKSPACE_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from loom.cli import main as loom_main  # noqa: E402


DEMO_COMMANDS = (
    ["init", "--no-daemon"],
    ["claim", "Refactor auth flow", "--agent", "agent-a", "--scope", "src/auth"],
    [
        "intent",
        "Touch auth middleware",
        "--agent",
        "agent-b",
        "--scope",
        "src/auth/middleware",
        "--reason",
        "Need rate limiting hook",
    ],
    [
        "context",
        "write",
        "auth-interface-change",
        "UserSession now requires refresh_token.",
        "--agent",
        "agent-a",
        "--scope",
        "src/auth",
        "--scope",
        "src/api",
    ],
    ["context", "read", "--scope", "src/api"],
    ["conflicts"],
    ["unclaim", "--agent", "agent-a"],
    ["status"],
    ["log", "--limit", "10"],
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_demo.py",
        description="Run Loom's canonical two-agent local-first proof.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        help="Existing directory to use as the demo repo. It will be initialized if needed.",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the generated temp repo instead of deleting it afterward.",
    )
    args = parser.parse_args(argv)

    if args.repo:
        repo_root = args.repo.resolve()
        repo_root.mkdir(parents=True, exist_ok=True)
        result = _run_demo(repo_root)
        print(f"Demo repo: {repo_root}")
        return result

    if args.keep:
        repo_root = Path(tempfile.mkdtemp(prefix="loom-two-agent-demo-"))
        result = _run_demo(repo_root)
        print(f"Demo repo: {repo_root}")
        return result

    temp_dir = tempfile.mkdtemp(prefix="loom-two-agent-demo-")
    repo_root = Path(temp_dir)
    try:
        return _run_demo(repo_root)
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


def _run_demo(repo_root: Path) -> int:
    _seed_demo_repo(repo_root)
    print(f"# Loom Two-Agent Demo\n")
    print(f"Repo: {repo_root}\n")

    for command in DEMO_COMMANDS:
        exit_code, stdout, stderr = _run_loom_command(repo_root, command)
        print(f"$ loom {' '.join(command)}")
        if stdout:
            print(stdout)
        if stderr:
            print("STDERR:")
            print(stderr)
        print()
        if exit_code != 0:
            return exit_code

    print("Demo complete.")
    return 0


def _seed_demo_repo(repo_root: Path) -> None:
    (repo_root / ".git").mkdir(exist_ok=True)

    files = {
        repo_root / "src" / "auth" / "session.py": "class UserSession:\n    refresh_token: str | None = None\n",
        repo_root / "src" / "auth" / "middleware.py": "def auth_middleware() -> None:\n    pass\n",
        repo_root / "src" / "api" / "handlers.py": "def handle_request() -> None:\n    pass\n",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _run_loom_command(repo_root: Path, argv: list[str]) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        _working_directory(repo_root),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        exit_code = loom_main(argv)
    return exit_code, stdout.getvalue().strip(), stderr.getvalue().strip()


@contextlib.contextmanager
def _working_directory(path: Path):
    previous = Path.cwd()
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chdir(path)
        yield
    finally:
        os.chdir(previous)


if __name__ == "__main__":
    raise SystemExit(main())
