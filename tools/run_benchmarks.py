#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from loom.benchmarking import (  # noqa: E402
    BenchmarkMeasurement,
    build_benchmark_report,
    format_summary_table,
    render_benchmark_report_html,
)
from loom.client import CoordinationClient  # noqa: E402
from loom.daemon import start_daemon, stop_daemon  # noqa: E402
from loom.mcp import MCP_PROTOCOL_VERSION, LoomMcpServer  # noqa: E402
from loom.project import initialize_project, load_project  # noqa: E402
from loom.util import json_ready  # noqa: E402


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".loom-reports" / "benchmarks"
DEFAULT_MODES = ("client_direct", "client_daemon", "cli", "mcp")
BENCHMARK_DAEMON_SOCKET_FILENAME = "d.sock"
BENCHMARK_DAEMON_RUNTIME_FILENAME = "d.json"
BENCHMARK_DAEMON_LOG_FILENAME = "d.log"
BENCHMARK_TEMP_ROOT = Path("/tmp") / "loom-bench"
BENCHMARK_TEMP_PREFIXES = {
    "client_direct": "lb-direct-",
    "client_daemon": "lb-daemon-",
    "cli": "lb-cli-",
    "mcp": "lb-mcp-",
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    modes = _parse_modes(args.modes)
    measurements: list[BenchmarkMeasurement] = []
    notes: list[str] = []
    scenario = {
        "rounds": args.rounds,
        "python_files": args.python_files,
        "script_files": args.script_files,
        "modes": list(modes),
    }

    for round_index in range(args.rounds):
        for mode in modes:
            with tempfile.TemporaryDirectory(
                prefix=BENCHMARK_TEMP_PREFIXES.get(mode, "lb-"),
                dir=str(_benchmark_temp_root()),
            ) as temp_dir:
                repo_root = Path(temp_dir)
                _create_synthetic_repo(
                    repo_root,
                    python_files=args.python_files,
                    script_files=args.script_files,
                )
                if mode == "client_direct":
                    _run_client_round(
                        repo_root=repo_root,
                        measurements=measurements,
                        round_index=round_index,
                        daemon=False,
                        notes=notes,
                    )
                elif mode == "client_daemon":
                    _run_client_round(
                        repo_root=repo_root,
                        measurements=measurements,
                        round_index=round_index,
                        daemon=True,
                        notes=notes,
                    )
                elif mode == "cli":
                    _run_cli_round(
                        repo_root=repo_root,
                        measurements=measurements,
                        round_index=round_index,
                    )
                elif mode == "mcp":
                    _run_mcp_round(
                        repo_root=repo_root,
                        measurements=measurements,
                        round_index=round_index,
                    )
                else:
                    raise ValueError(f"Unsupported benchmark mode: {mode}")

    report = build_benchmark_report(
        label=args.label,
        scenario=scenario,
        measurements=measurements,
        notes=sorted(set(notes)),
    )

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base_name = f"{_slug(args.label)}-{timestamp}"
    json_path = output_dir / f"{base_name}.json"
    html_path = output_dir / f"{base_name}.html"
    report["artifacts"] = {
        "json": str(json_path),
        "html": str(html_path),
    }

    json_path.write_text(
        f"{json.dumps(json_ready(report), indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    html_path.write_text(render_benchmark_report_html(report), encoding="utf-8")

    print(format_summary_table(report))
    print()
    print(f"JSON report: {json_path}")
    print(f"HTML report: {html_path}")
    if report["notes"]:
        print()
        print("Notes:")
        for note in report["notes"]:
            print(f"- {note}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_benchmarks.py",
        description="Run local Loom benchmarks and emit JSON + HTML reports.",
    )
    parser.add_argument("--label", default="manual", help="Short label for this benchmark run.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where JSON and HTML reports should be written.",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=3,
        help="How many fresh-repo rounds to run per benchmark mode.",
    )
    parser.add_argument(
        "--python-files",
        type=int,
        default=200,
        help="Approximate number of Python source files to synthesize per repo.",
    )
    parser.add_argument(
        "--script-files",
        type=int,
        default=200,
        help="Approximate number of JS/TS source files to synthesize per repo.",
    )
    parser.add_argument(
        "--modes",
        default=",".join(DEFAULT_MODES),
        help="Comma-separated modes: client_direct,client_daemon,cli,mcp",
    )
    return parser


def _parse_modes(value: str) -> tuple[str, ...]:
    modes = tuple(part.strip() for part in value.split(",") if part.strip())
    if not modes:
        raise ValueError("At least one benchmark mode is required.")
    unknown = sorted(set(modes) - set(DEFAULT_MODES))
    if unknown:
        raise ValueError(f"Unsupported benchmark mode(s): {', '.join(unknown)}")
    return modes


def _create_synthetic_repo(
    repo_root: Path,
    *,
    python_files: int,
    script_files: int,
) -> None:
    (repo_root / ".git").mkdir()
    (repo_root / "src" / "auth").mkdir(parents=True)
    (repo_root / "src" / "api").mkdir(parents=True)
    (repo_root / "src" / "generated_py").mkdir(parents=True)
    (repo_root / "src" / "generated_ts").mkdir(parents=True)

    _write_text(
        repo_root / "src" / "auth" / "session.py",
        "class UserSession:\n    pass\n",
    )
    _write_text(
        repo_root / "src" / "api" / "handlers.py",
        "from auth.session import UserSession\n\n"
        "def handle_request() -> UserSession:\n"
        "    return UserSession()\n",
    )
    _write_text(
        repo_root / "src" / "auth" / "session.ts",
        "export function createSession(): string {\n"
        "    return 'session';\n"
        "}\n",
    )
    _write_text(
        repo_root / "src" / "api" / "handlers.ts",
        'import { createSession } from "../auth/session.js";\n\n'
        "export function handleRequest(): string {\n"
        "    return createSession();\n"
        "}\n",
    )

    for index in range(max(0, python_files - 2)):
        path = repo_root / "src" / "generated_py" / f"module_{index:04d}.py"
        if index == 0:
            content = "value_0000 = 0\n"
        else:
            previous = index - 1
            content = (
                f"from generated_py.module_{previous:04d} import value_{previous:04d}\n\n"
                f"value_{index:04d} = value_{previous:04d} + 1\n"
            )
        _write_text(path, content)

    for index in range(max(0, script_files - 2)):
        path = repo_root / "src" / "generated_ts" / f"module_{index:04d}.ts"
        if index == 0:
            content = "export const value0000 = 0;\n"
        else:
            previous = index - 1
            content = (
                f'import {{ value{previous:04d} }} from "./module_{previous:04d}.js";\n\n'
                f"export const value{index:04d} = value{previous:04d} + 1;\n"
            )
        _write_text(path, content)


def _benchmark_temp_root() -> Path:
    if BENCHMARK_TEMP_ROOT.is_dir() or not BENCHMARK_TEMP_ROOT.exists():
        BENCHMARK_TEMP_ROOT.mkdir(parents=True, exist_ok=True)
        return BENCHMARK_TEMP_ROOT
    return Path(tempfile.gettempdir())


def _configure_short_daemon_paths(repo_root: Path) -> None:
    config_path = repo_root / ".loom" / "config.json"
    if not config_path.is_file():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        return
    config["daemon_socket"] = BENCHMARK_DAEMON_SOCKET_FILENAME
    config["daemon_runtime"] = BENCHMARK_DAEMON_RUNTIME_FILENAME
    config["daemon_log"] = BENCHMARK_DAEMON_LOG_FILENAME
    config_path.write_text(f"{json.dumps(config, indent=2)}\n", encoding="utf-8")


def _run_client_round(
    *,
    repo_root: Path,
    measurements: list[BenchmarkMeasurement],
    round_index: int,
    daemon: bool,
    notes: list[str],
) -> None:
    mode = "client_daemon" if daemon else "client_direct"
    project = _measure(
        measurements,
        mode=mode,
        operation="project_init",
        round_index=round_index,
        func=lambda: initialize_project(repo_root)[0],
    )
    if project is None:
        return

    if daemon:
        _configure_short_daemon_paths(repo_root)
        project = load_project(repo_root)
        daemon_result = _measure(
            measurements,
            mode=mode,
            operation="daemon_start",
            round_index=round_index,
            func=lambda: start_daemon(project),
        )
        if daemon_result is None:
            notes.append(
                "client_daemon mode skipped after daemon start failure. This is expected in some sandboxed environments."
            )
            return

    try:
        project = load_project(repo_root)
        client = CoordinationClient(project)

        claim_result = _measure(
            measurements,
            mode=mode,
            operation="claim",
            round_index=round_index,
            func=lambda: client.create_claim(
                agent_id="agent-a",
                description="Refactor auth flow",
                scope=("src/auth/session.py",),
                source="benchmark",
            ),
        )
        if claim_result is None:
            return

        intent_result = _measure(
            measurements,
            mode=mode,
            operation="intent",
            round_index=round_index,
            func=lambda: client.declare_intent(
                agent_id="agent-b",
                description="Touch auth middleware",
                reason="Need rate limiting hook",
                scope=("src/api/handlers.py",),
                source="benchmark",
            ),
        )
        if intent_result is None:
            return
        _, conflicts = intent_result
        conflict_id = conflicts[0].id if conflicts else None

        context_result = _measure(
            measurements,
            mode=mode,
            operation="context_write",
            round_index=round_index,
            func=lambda: client.publish_context(
                agent_id="agent-a",
                topic="auth-interface",
                body="Refresh token required.",
                scope=("src/auth/session.py",),
                source="benchmark",
            ),
        )
        if context_result is None:
            return
        context_record, _ = context_result

        _measure(
            measurements,
            mode=mode,
            operation="status",
            round_index=round_index,
            func=client.read_status,
        )
        _measure(
            measurements,
            mode=mode,
            operation="inbox",
            round_index=round_index,
            func=lambda: client.read_inbox_snapshot(agent_id="agent-b"),
        )
        _measure(
            measurements,
            mode=mode,
            operation="conflicts",
            round_index=round_index,
            func=client.read_conflicts,
        )
        _measure(
            measurements,
            mode=mode,
            operation="events",
            round_index=round_index,
            func=lambda: client.read_events(limit=20),
        )
        _measure(
            measurements,
            mode=mode,
            operation="context_ack",
            round_index=round_index,
            func=lambda: client.acknowledge_context(
                context_id=context_record.id,
                agent_id="agent-b",
                status="adapted",
                note="Shifted plan during benchmark.",
            ),
        )
        if conflict_id is not None:
            _measure(
                measurements,
                mode=mode,
                operation="resolve",
                round_index=round_index,
                func=lambda: client.resolve_conflict(
                    conflict_id=conflict_id,
                    agent_id="agent-a",
                    resolution_note="Bench resolution.",
                ),
            )
        if daemon:
            _measure_event_follow_latency(
                measurements,
                round_index=round_index,
                client=client,
            )
    finally:
        if daemon:
            try:
                stop_daemon(project)
            except RuntimeError as error:
                notes.append(f"daemon stop warning: {error}")


def _run_cli_round(
    *,
    repo_root: Path,
    measurements: list[BenchmarkMeasurement],
    round_index: int,
) -> None:
    mode = "cli"
    init_result = _measure(
        measurements,
        mode=mode,
        operation="init",
        round_index=round_index,
        func=lambda: _run_cli_command(repo_root, "init", "--no-daemon", "--agent", "agent-a", "--json"),
    )
    if init_result is None:
        return
    _measure(
        measurements,
        mode=mode,
        operation="start",
        round_index=round_index,
        func=lambda: _run_cli_command(repo_root, "start", "--json"),
    )
    claim_result = _measure(
        measurements,
        mode=mode,
        operation="claim",
        round_index=round_index,
        func=lambda: _run_cli_command(
            repo_root,
            "claim",
            "Refactor auth flow",
            "--scope",
            "src/auth/session.py",
            "--agent",
            "agent-a",
            "--json",
        ),
    )
    if claim_result is None:
        return
    intent_result = _measure(
        measurements,
        mode=mode,
        operation="intent",
        round_index=round_index,
        func=lambda: _run_cli_command(
            repo_root,
            "intent",
            "Touch auth middleware",
            "--scope",
            "src/api/handlers.py",
            "--agent",
            "agent-b",
            "--json",
        ),
    )
    if intent_result is None:
        return
    conflict_id = intent_result.get("conflicts", [{}])[0].get("id")
    context_result = _measure(
        measurements,
        mode=mode,
        operation="context_write",
        round_index=round_index,
        func=lambda: _run_cli_command(
            repo_root,
            "context",
            "write",
            "auth-interface",
            "Refresh token required.",
            "--scope",
            "src/auth/session.py",
            "--agent",
            "agent-a",
            "--json",
        ),
    )
    if context_result is None:
        return
    context_id = context_result.get("context", {}).get("id")

    _measure(
        measurements,
        mode=mode,
        operation="status",
        round_index=round_index,
        func=lambda: _run_cli_command(repo_root, "status", "--json"),
    )
    _measure(
        measurements,
        mode=mode,
        operation="inbox",
        round_index=round_index,
        func=lambda: _run_cli_command(repo_root, "inbox", "--agent", "agent-b", "--json"),
    )
    _measure(
        measurements,
        mode=mode,
        operation="conflicts",
        round_index=round_index,
        func=lambda: _run_cli_command(repo_root, "conflicts", "--json"),
    )
    if context_id:
        _measure(
            measurements,
            mode=mode,
            operation="context_ack",
            round_index=round_index,
            func=lambda: _run_cli_command(
                repo_root,
                "context",
                "ack",
                context_id,
                "--agent",
                "agent-b",
                "--status",
                "adapted",
                "--note",
                "Shifted plan during benchmark.",
                "--json",
            ),
        )
    if conflict_id:
        _measure(
            measurements,
            mode=mode,
            operation="resolve",
            round_index=round_index,
            func=lambda: _run_cli_command(
                repo_root,
                "resolve",
                conflict_id,
                "--agent",
                "agent-a",
                "--note",
                "Bench resolution.",
                "--json",
            ),
        )
    _measure(
        measurements,
        mode=mode,
        operation="log",
        round_index=round_index,
        func=lambda: _run_cli_command(repo_root, "log", "--limit", "20", "--json"),
    )


def _run_mcp_round(
    *,
    repo_root: Path,
    measurements: list[BenchmarkMeasurement],
    round_index: int,
) -> None:
    mode = "mcp"
    server = LoomMcpServer(cwd=repo_root)

    initialize_result = _measure(
        measurements,
        mode=mode,
        operation="mcp_initialize",
        round_index=round_index,
        func=lambda: _mcp_initialize(server),
    )
    if initialize_result is None:
        return

    init_result = _measure(
        measurements,
        mode=mode,
        operation="init",
        round_index=round_index,
        func=lambda: _mcp_call(server, "loom_init", {"default_agent": "agent-a"}),
    )
    if init_result is None:
        return
    _measure(
        measurements,
        mode=mode,
        operation="start",
        round_index=round_index,
        func=lambda: _mcp_call(server, "loom_start", {}),
    )
    claim_result = _measure(
        measurements,
        mode=mode,
        operation="claim",
        round_index=round_index,
        func=lambda: _mcp_call(
            server,
            "loom_claim",
            {
                "agent_id": "agent-a",
                "description": "Refactor auth flow",
                "scope": ["src/auth/session.py"],
            },
        ),
    )
    if claim_result is None:
        return
    intent_result = _measure(
        measurements,
        mode=mode,
        operation="intent",
        round_index=round_index,
        func=lambda: _mcp_call(
            server,
            "loom_intent",
            {
                "agent_id": "agent-b",
                "description": "Touch auth middleware",
                "scope": ["src/api/handlers.py"],
            },
        ),
    )
    if intent_result is None:
        return
    conflict_id = intent_result.get("conflicts", [{}])[0].get("id")
    context_result = _measure(
        measurements,
        mode=mode,
        operation="context_write",
        round_index=round_index,
        func=lambda: _mcp_call(
            server,
            "loom_context_write",
            {
                "agent_id": "agent-a",
                "topic": "auth-interface",
                "body": "Refresh token required.",
                "scope": ["src/auth/session.py"],
            },
        ),
    )
    if context_result is None:
        return
    context_id = context_result.get("context", {}).get("id")

    _measure(
        measurements,
        mode=mode,
        operation="status",
        round_index=round_index,
        func=lambda: _mcp_call(server, "loom_status", {}),
    )
    _measure(
        measurements,
        mode=mode,
        operation="inbox",
        round_index=round_index,
        func=lambda: _mcp_call(server, "loom_inbox", {"agent_id": "agent-b"}),
    )
    _measure(
        measurements,
        mode=mode,
        operation="conflicts",
        round_index=round_index,
        func=lambda: _mcp_call(server, "loom_conflicts", {}),
    )
    if context_id:
        _measure(
            measurements,
            mode=mode,
            operation="context_ack",
            round_index=round_index,
            func=lambda: _mcp_call(
                server,
                "loom_context_ack",
                {
                    "context_id": context_id,
                    "agent_id": "agent-b",
                    "status": "adapted",
                    "note": "Shifted plan during benchmark.",
                },
            ),
        )
    if conflict_id:
        _measure(
            measurements,
            mode=mode,
            operation="resolve",
            round_index=round_index,
            func=lambda: _mcp_call(
                server,
                "loom_resolve",
                {
                    "conflict_id": conflict_id,
                    "agent_id": "agent-a",
                    "resolution_note": "Bench resolution.",
                },
            ),
        )
    _measure(
        measurements,
        mode=mode,
        operation="log",
        round_index=round_index,
        func=lambda: _mcp_call(server, "loom_log", {"limit": 20}),
    )


def _measure_event_follow_latency(
    measurements: list[BenchmarkMeasurement],
    *,
    round_index: int,
    client: CoordinationClient,
) -> None:
    mode = "client_daemon"
    after_sequence = client.store.latest_event_sequence()
    arrivals: queue.Queue[object] = queue.Queue(maxsize=1)
    ready = threading.Event()

    def _watch() -> None:
        try:
            ready.set()
            for event in client.follow_events(after_sequence=after_sequence):
                arrivals.put((time.perf_counter_ns(), event.type))
                return
            arrivals.put(RuntimeError("event stream closed before a new event arrived"))
        except Exception as error:  # pragma: no cover - best-effort benchmark path
            arrivals.put(error)

    watcher = threading.Thread(target=_watch, name="loom-bench-watch", daemon=True)
    watcher.start()
    ready.wait(timeout=1.0)
    time.sleep(0.05)
    start_ns = time.perf_counter_ns()
    try:
        client.publish_context(
            agent_id="agent-c",
            topic="daemon-follow",
            body="event latency sample",
            scope=("src/auth/session.ts",),
            source="benchmark",
        )
        result = arrivals.get(timeout=2.0)
        if isinstance(result, Exception):
            raise result
        arrival_ns, event_type = result
    except Exception as error:
        measurements.append(
            BenchmarkMeasurement(
                mode=mode,
                operation="event_follow_latency",
                round_index=round_index,
                duration_ms=None,
                ok=False,
                detail=str(error),
            )
        )
        return

    measurements.append(
        BenchmarkMeasurement(
            mode=mode,
            operation="event_follow_latency",
            round_index=round_index,
            duration_ms=(arrival_ns - start_ns) / 1_000_000.0,
            metadata={"event_type": event_type},
        )
    )


def _measure(
    measurements: list[BenchmarkMeasurement],
    *,
    mode: str,
    operation: str,
    round_index: int,
    func,
):
    started_at = time.perf_counter_ns()
    try:
        result = func()
    except Exception as error:
        measurements.append(
            BenchmarkMeasurement(
                mode=mode,
                operation=operation,
                round_index=round_index,
                duration_ms=None,
                ok=False,
                detail=str(error),
            )
        )
        return None

    measurements.append(
        BenchmarkMeasurement(
            mode=mode,
            operation=operation,
            round_index=round_index,
            duration_ms=(time.perf_counter_ns() - started_at) / 1_000_000.0,
        )
    )
    return result


def _run_cli_command(repo_root: Path, *args: str) -> dict[str, object]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        f"{SRC_ROOT}{os.pathsep}{existing_pythonpath}"
        if existing_pythonpath
        else str(SRC_ROOT)
    )
    result = subprocess.run(
        [sys.executable, "-m", "loom", *args],
        cwd=repo_root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "CLI command failed")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("CLI benchmark expected JSON output.") from error
    if not isinstance(payload, dict):
        raise RuntimeError("CLI benchmark received non-object JSON.")
    return {str(key): value for key, value in payload.items()}


def _mcp_initialize(server: LoomMcpServer) -> None:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": "initialize",
            "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION},
        }
    )
    if response is None:
        raise RuntimeError("MCP initialize returned no response.")
    server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return True


def _mcp_call(server: LoomMcpServer, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": f"bench-{tool_name}",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
    )
    if response is None:
        raise RuntimeError(f"MCP tool returned no response: {tool_name}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError(f"MCP tool returned invalid result: {tool_name}")
    if result.get("isError"):
        content = result.get("structuredContent", {})
        raise RuntimeError(str(content.get("error") or f"MCP tool failed: {tool_name}"))
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        raise RuntimeError(f"MCP tool returned invalid structured content: {tool_name}")
    return {str(key): value for key, value in structured.items()}


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _slug(value: str) -> str:
    normalized = "".join(character.lower() if character.isalnum() else "-" for character in value)
    collapsed = "-".join(part for part in normalized.split("-") if part)
    return collapsed or "benchmark"


if __name__ == "__main__":
    raise SystemExit(main())
