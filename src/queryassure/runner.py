from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import yaml

from .metadata import Catalog
from .models import AgentTrace, CaseResult, CheckResult
from .validators import SqlValidator, canonical_rows, execute_read_only


class AgentLike(Protocol):
    def ask(self, question: str) -> AgentTrace: ...


class EvaluationRunner:
    def __init__(self, agent: AgentLike, database: str | Path, catalog: Catalog) -> None:
        self.agent = agent
        self.database = Path(database)
        self.validator = SqlValidator(catalog)

    def run_case(self, case: dict[str, Any]) -> CaseResult:
        trace = self.agent.ask(case["question"])
        expectations = case.get("expect", {})
        checks = self.validator.validate(trace.sql, expectations) if trace.sql else []
        checks.append(
            CheckResult(
                "agent_execution",
                trace.error is None,
                "Agent completed successfully" if trace.error is None else trace.error,
            )
        )

        if trace.error is None and expectations.get("gold_sql"):
            _, expected_rows = execute_read_only(self.database, expectations["gold_sql"])
            equivalent = canonical_rows(trace.rows) == canonical_rows(expected_rows)
            checks.append(
                CheckResult(
                    "result_equivalence",
                    equivalent,
                    "Result set matches the golden query"
                    if equivalent
                    else "Result set differs from the golden query",
                    details={"actual_rows": len(trace.rows), "expected_rows": len(expected_rows)},
                )
            )

        budgets = case.get("budgets", {})
        if "max_latency_ms" in budgets:
            passed = trace.latency_ms <= float(budgets["max_latency_ms"])
            checks.append(
                CheckResult(
                    "latency_budget",
                    passed,
                    f"Latency {trace.latency_ms:.1f} ms / budget {budgets['max_latency_ms']} ms",
                    severity="warning",
                )
            )
        if "max_tool_calls" in budgets:
            passed = len(trace.tool_calls) <= int(budgets["max_tool_calls"])
            checks.append(
                CheckResult(
                    "tool_call_budget",
                    passed,
                    f"Tool calls {len(trace.tool_calls)} / budget {budgets['max_tool_calls']}",
                    severity="warning",
                )
            )
        passed = all(check.passed for check in checks if check.severity == "error")
        return CaseResult(case["id"], case["question"], passed, checks, trace)

    def run_file(self, path: str | Path) -> dict[str, Any]:
        payload = yaml.safe_load(Path(path).read_text()) or {}
        results = [self.run_case(case) for case in payload.get("cases", [])]
        passed = sum(result.passed for result in results)
        return {
            "suite": payload.get("name", Path(path).stem),
            "summary": {
                "total": len(results),
                "passed": passed,
                "failed": len(results) - passed,
                "pass_rate": passed / len(results) if results else 0.0,
            },
            "results": [result.to_dict() for result in results],
        }

    @staticmethod
    def save_report(report: dict[str, Any], path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, default=str))
        return target


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    before = baseline["summary"]
    after = candidate["summary"]
    return {
        "baseline_pass_rate": before["pass_rate"],
        "candidate_pass_rate": after["pass_rate"],
        "delta": after["pass_rate"] - before["pass_rate"],
        "regression": after["pass_rate"] < before["pass_rate"],
        "baseline_failed": before["failed"],
        "candidate_failed": after["failed"],
    }
