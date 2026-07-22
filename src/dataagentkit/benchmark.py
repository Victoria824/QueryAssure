from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def summarize_report(label: str, report: dict[str, Any]) -> dict[str, Any]:
    results = report.get("results", [])
    latencies = [float(item.get("trace", {}).get("latency_ms", 0.0)) for item in results]
    costs = [float(item.get("trace", {}).get("estimated_cost_usd", 0.0)) for item in results]
    tool_calls = [len(item.get("trace", {}).get("tool_calls", [])) for item in results]
    hallucinations = 0
    policy_violations = 0
    for result in results:
        for check in result.get("checks", []):
            if check.get("name") in {"schema_tables", "schema_columns"} and not check.get("passed"):
                hallucinations += 1
            if check.get("name") == "sensitive_data_policy" and not check.get("passed"):
                policy_violations += 1
    summary = report.get("summary", {})
    return {
        "label": label,
        "suite": report.get("suite", "unknown"),
        "cases": int(summary.get("total", len(results))),
        "pass_rate": round(float(summary.get("pass_rate", 0.0)), 4),
        "failed": int(summary.get("failed", 0)),
        "p50_latency_ms": round(_percentile(latencies, 0.50), 2),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 2),
        "average_tool_calls": round(sum(tool_calls) / len(tool_calls), 2) if tool_calls else 0.0,
        "estimated_cost_usd": round(sum(costs), 6),
        "schema_hallucinations": hallucinations,
        "policy_violations": policy_violations,
    }


def build_leaderboard(reports: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    entries = [summarize_report(label, report) for label, report in reports]
    entries.sort(
        key=lambda item: (
            -item["pass_rate"],
            item["schema_hallucinations"],
            item["policy_violations"],
            item["p95_latency_ms"],
        )
    )
    for rank, entry in enumerate(entries, start=1):
        entry["rank"] = rank
    return {
        "schema_version": 1,
        "ranking": "pass rate, safety failures, then p95 latency",
        "entries": entries,
    }


def render_markdown(leaderboard: dict[str, Any]) -> str:
    lines = [
        "# DataAgentKit benchmark",
        "",
        "Reproducible comparison generated from DataAgentKit JSON reports.",
        "",
        "| Rank | Agent | Pass rate | Schema hallucinations | "
        "Policy violations | p95 latency | Cost |",
        "|---:|---|---:|---:|---:|---:|---:|",
    ]
    for item in leaderboard["entries"]:
        lines.append(
            f"| {item['rank']} | {item['label']} | {item['pass_rate']:.0%} | "
            f"{item['schema_hallucinations']} | {item['policy_violations']} | "
            f"{item['p95_latency_ms']:.1f} ms | ${item['estimated_cost_usd']:.4f} |"
        )
    lines.extend(
        [
            "",
            "> Rankings prioritize correctness and safety over speed. Re-run the source reports",
            "> on your own infrastructure before drawing model-level conclusions.",
            "",
        ]
    )
    return "\n".join(lines)


def save_leaderboard(
    leaderboard: dict[str, Any],
    *,
    json_path: str | Path,
    markdown_path: str | Path,
) -> tuple[Path, Path]:
    json_target = Path(json_path)
    markdown_target = Path(markdown_path)
    json_target.parent.mkdir(parents=True, exist_ok=True)
    markdown_target.parent.mkdir(parents=True, exist_ok=True)
    json_target.write_text(json.dumps(leaderboard, indent=2))
    markdown_target.write_text(render_markdown(leaderboard))
    return json_target, markdown_target
