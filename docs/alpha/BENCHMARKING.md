# Benchmarking

Last updated: March 20, 2026

Loom now has a local benchmark harness for alpha hardening.

The goal is not perfect lab-grade measurement. The goal is to make performance
visible enough that dogfooding and release decisions can rely on real numbers.

## What The Harness Measures

The harness creates fresh synthetic Git repos and benchmarks a representative
coordination loop across multiple surfaces:

- `client_direct`: direct `CoordinationClient` and SQLite path
- `client_daemon`: daemon-backed `CoordinationClient` path
- `cli`: real `python -m loom ... --json` subprocess path
- `mcp`: in-process MCP tool-call path

Representative operations include:

- project/init path
- start/orientation path where relevant
- claim
- intent with semantic dependency overlap
- context write
- status
- inbox
- conflicts
- context acknowledgment
- resolve
- event/log reads
- daemon event-follow latency where available

## Running It

Quick run:

```bash
make bench-quick
```

Larger local run:

```bash
make bench
```

Custom run:

```bash
python3 tools/run_benchmarks.py \
  --label local-check \
  --rounds 5 \
  --python-files 500 \
  --script-files 500 \
  --modes client_direct,client_daemon,cli,mcp
```

## Output

Artifacts are written under:

```text
.loom-reports/benchmarks/
```

Each run emits:

- one JSON report
- one self-contained HTML report

The HTML report is meant to be opened directly in a browser from disk. No build
step or web server is required.

## Reading The Results

Focus on:

- median latency for common reads and writes
- p95 latency for anything user-facing
- daemon follow latency when daemon mode is available
- differences between direct, daemon, CLI, and MCP paths
- failure counts or skipped daemon runs

## Current Baseline

These numbers are from local alpha hardening runs on March 20, 2026.

Quick run (`2` rounds, `100` Python files, `100` script files):

- CLI: roughly `64-120ms`
- `client_direct`: roughly `0.4-19ms`
- `client_daemon`: skipped in this sandboxed run after daemon-start failure
- MCP: roughly `0.03-28ms`

Larger run (`5` rounds, `500` Python files, `500` script files):

- CLI: roughly `64-167ms`
- `client_direct`: roughly `0.4-67ms`
- `client_daemon`: skipped in this sandboxed run after daemon-start failure
- MCP: roughly `0.03-66ms`

Interpretation:

- CLI is dominated by Python process startup, which is expected
- steady-state direct and MCP reads remain comfortably fast for the current
  local coordination loop
- claim creation is the most repo-size-sensitive path and should keep being
  watched as dogfooding expands to larger repos
- daemon mode should still be re-run outside sandboxed environments before any
  public claim about fresh daemon-start or event-follow latency

## macOS Note

The benchmark runner now uses a short temp root plus short daemon filenames for
daemon-mode synthetic repos. This avoids AF_UNIX socket path-length failures on
macOS during benchmark runs without changing Loom's real product defaults.

## Current Intent

The benchmark harness is an alpha hardening tool, not part of the Loom product
surface. It is allowed to evolve quickly as long as:

- the report stays readable
- the measured scenarios stay truthful
- the harness keeps using the real Loom paths instead of synthetic shortcuts
