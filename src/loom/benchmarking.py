from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from html import escape
from statistics import mean, median

from . import __version__
from .util import json_ready, utc_now


@dataclass(frozen=True)
class BenchmarkMeasurement:
    mode: str
    operation: str
    round_index: int
    duration_ms: float | None
    ok: bool = True
    detail: str | None = None
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class BenchmarkSummary:
    mode: str
    operation: str
    samples: int
    successes: int
    failures: int
    min_ms: float | None
    median_ms: float | None
    mean_ms: float | None
    p95_ms: float | None
    max_ms: float | None


def summarize_measurements(
    measurements: list[BenchmarkMeasurement] | tuple[BenchmarkMeasurement, ...],
) -> tuple[BenchmarkSummary, ...]:
    grouped: dict[tuple[str, str], list[BenchmarkMeasurement]] = {}
    for measurement in measurements:
        grouped.setdefault((measurement.mode, measurement.operation), []).append(measurement)

    summaries: list[BenchmarkSummary] = []
    for mode, operation in sorted(grouped):
        entries = grouped[(mode, operation)]
        successful = sorted(
            measurement.duration_ms
            for measurement in entries
            if measurement.ok and measurement.duration_ms is not None
        )
        failures = sum(1 for measurement in entries if not measurement.ok)
        summaries.append(
            BenchmarkSummary(
                mode=mode,
                operation=operation,
                samples=len(entries),
                successes=len(successful),
                failures=failures,
                min_ms=None if not successful else round(successful[0], 3),
                median_ms=None if not successful else round(float(median(successful)), 3),
                mean_ms=None if not successful else round(float(mean(successful)), 3),
                p95_ms=None if not successful else round(_percentile(successful, 95.0), 3),
                max_ms=None if not successful else round(successful[-1], 3),
            )
        )
    return tuple(summaries)


def build_benchmark_report(
    *,
    label: str,
    scenario: dict[str, object],
    measurements: list[BenchmarkMeasurement] | tuple[BenchmarkMeasurement, ...],
    notes: list[str] | tuple[str, ...] = (),
) -> dict[str, object]:
    measurements_tuple = tuple(measurements)
    summaries = summarize_measurements(measurements_tuple)
    return {
        "generated_at": utc_now(),
        "loom_version": __version__,
        "label": label,
        "scenario": scenario,
        "environment": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "notes": list(notes),
        "measurements": [json_ready(measurement) for measurement in measurements_tuple],
        "summaries": [json_ready(summary) for summary in summaries],
    }


def format_summary_table(report: dict[str, object]) -> str:
    summaries = report.get("summaries", [])
    if not isinstance(summaries, list) or not summaries:
        return "No benchmark summaries recorded."

    rows = [
        (
            str(item["mode"]),
            str(item["operation"]),
            f"{item['successes']}/{item['samples']}",
            _format_ms(item.get("median_ms")),
            _format_ms(item.get("p95_ms")),
            _format_ms(item.get("max_ms")),
        )
        for item in summaries
        if isinstance(item, dict)
    ]
    widths = [
        max(len("mode"), *(len(row[0]) for row in rows)),
        max(len("operation"), *(len(row[1]) for row in rows)),
        max(len("ok"), *(len(row[2]) for row in rows)),
        max(len("median"), *(len(row[3]) for row in rows)),
        max(len("p95"), *(len(row[4]) for row in rows)),
        max(len("max"), *(len(row[5]) for row in rows)),
    ]

    header = _format_row(("mode", "operation", "ok", "median", "p95", "max"), widths)
    divider = _format_row(tuple("-" * width for width in widths), widths)
    lines = [header, divider]
    for row in rows:
        lines.append(_format_row(row, widths))
    return "\n".join(lines)


def render_benchmark_report_html(report: dict[str, object]) -> str:
    summaries = [
        item for item in report.get("summaries", []) if isinstance(item, dict)
    ]
    max_median = max(
        (
            float(item["median_ms"])
            for item in summaries
            if item.get("median_ms") is not None
        ),
        default=0.0,
    )
    summary_rows = "\n".join(
        _render_summary_row(item, max_median=max_median)
        for item in summaries
    )
    notes = report.get("notes", [])
    notes_html = "".join(
        f"<li>{escape(str(note))}</li>"
        for note in notes
    )
    notes_block = (
        f"<section><h2>Notes</h2><ul>{notes_html}</ul></section>"
        if notes_html
        else ""
    )
    raw_json = escape(
        json.dumps(json_ready(report), indent=2, sort_keys=True),
        quote=False,
    )
    scenario = report.get("scenario", {})
    environment = report.get("environment", {})
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Loom Benchmark Report</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      color-scheme: light;
      --ink: #10221a;
      --muted: #5f6f67;
      --paper: #f7f5ef;
      --panel: #ffffff;
      --line: #d9d4c7;
      --accent: #1f7a5a;
      --accent-soft: #d9efe5;
      --warn: #b45309;
    }}
    body {{
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top right, #e9f4ef 0, transparent 24rem),
        linear-gradient(180deg, #fbfaf6 0%, var(--paper) 100%);
    }}
    main {{
      max-width: 72rem;
      margin: 0 auto;
      padding: 2rem 1.25rem 4rem;
    }}
    h1, h2 {{
      margin: 0 0 0.75rem;
      font-family: "Avenir Next Condensed", "Gill Sans", sans-serif;
      letter-spacing: 0.02em;
    }}
    p, li {{
      line-height: 1.45;
    }}
    .meta {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
      gap: 0.75rem;
      margin: 1.25rem 0 2rem;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 0.85rem;
      padding: 0.9rem 1rem;
      box-shadow: 0 0.25rem 1rem rgba(16, 34, 26, 0.05);
    }}
    .label {{
      display: block;
      color: var(--muted);
      font-size: 0.8rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 0.25rem;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 0.85rem;
      overflow: hidden;
      box-shadow: 0 0.25rem 1rem rgba(16, 34, 26, 0.05);
    }}
    th, td {{
      text-align: left;
      padding: 0.8rem 0.9rem;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{
      font-family: "Avenir Next Condensed", "Gill Sans", sans-serif;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-size: 0.82rem;
      color: var(--muted);
      background: #fbfaf7;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    .bar-shell {{
      height: 0.65rem;
      min-width: 8rem;
      background: #eef2ef;
      border-radius: 999px;
      overflow: hidden;
      margin-top: 0.3rem;
    }}
    .bar {{
      height: 100%;
      background: linear-gradient(90deg, var(--accent-soft), var(--accent));
    }}
    .warn {{
      color: var(--warn);
      font-weight: 600;
    }}
    pre {{
      overflow: auto;
      background: #1b2622;
      color: #e6f1ed;
      padding: 1rem;
      border-radius: 0.85rem;
      border: 1px solid #24342e;
    }}
    details {{
      margin-top: 1.5rem;
    }}
  </style>
</head>
<body>
  <main>
    <h1>Loom Benchmark Report</h1>
    <p>{escape(str(report.get("label", "benchmark")))} · generated {escape(str(report.get("generated_at", "")))}</p>
    <section class="meta">
      <div class="card"><span class="label">Loom</span>{escape(str(report.get("loom_version", "")))}</div>
      <div class="card"><span class="label">Rounds</span>{escape(str(scenario.get("rounds", "")))}</div>
      <div class="card"><span class="label">Python Files</span>{escape(str(scenario.get("python_files", "")))}</div>
      <div class="card"><span class="label">Script Files</span>{escape(str(scenario.get("script_files", "")))}</div>
      <div class="card"><span class="label">Modes</span>{escape(", ".join(scenario.get("modes", [])))}</div>
      <div class="card"><span class="label">Python</span>{escape(str(environment.get("python_version", "")))}</div>
    </section>
    <section>
      <h2>Summary</h2>
      <table>
        <thead>
          <tr>
            <th>Mode</th>
            <th>Operation</th>
            <th>OK</th>
            <th>Median</th>
            <th>P95</th>
            <th>Max</th>
          </tr>
        </thead>
        <tbody>
          {summary_rows}
        </tbody>
      </table>
    </section>
    {notes_block}
    <details>
      <summary>Raw JSON</summary>
      <pre>{raw_json}</pre>
    </details>
  </main>
</body>
</html>
"""


def _percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        raise ValueError("Percentile requires at least one value.")
    if len(values) == 1:
        return float(values[0])
    rank = (len(values) - 1) * (percentile_value / 100.0)
    lower = int(rank)
    upper = min(lower + 1, len(values) - 1)
    fraction = rank - lower
    return float(values[lower] + (values[upper] - values[lower]) * fraction)


def _format_ms(value: object) -> str:
    if value is None:
        return "-"
    return f"{float(value):.3f} ms"


def _format_row(values: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(value.ljust(width) for value, width in zip(values, widths, strict=True))


def _render_summary_row(item: dict[str, object], *, max_median: float) -> str:
    median_ms = item.get("median_ms")
    width = 0.0
    if median_ms is not None and max_median > 0:
        width = max(3.0, (float(median_ms) / max_median) * 100.0)
    failures = int(item.get("failures", 0))
    ok_text = f"{item.get('successes', 0)}/{item.get('samples', 0)}"
    if failures:
        ok_text += f" ({failures} failed)"
    warn_class = " class=\"warn\"" if failures else ""
    bar_html = (
        ""
        if median_ms is None
        else (
            "<div class=\"bar-shell\">"
            f"<div class=\"bar\" style=\"width: {width:.1f}%\"></div>"
            "</div>"
        )
    )
    return (
        "<tr>"
        f"<td>{escape(str(item.get('mode', '')))}</td>"
        f"<td>{escape(str(item.get('operation', '')))}</td>"
        f"<td{warn_class}>{escape(ok_text)}</td>"
        f"<td>{escape(_format_ms(median_ms))}{bar_html}</td>"
        f"<td>{escape(_format_ms(item.get('p95_ms')))}</td>"
        f"<td>{escape(_format_ms(item.get('max_ms')))}</td>"
        "</tr>"
    )
