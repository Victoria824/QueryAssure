from __future__ import annotations

from pathlib import Path
from typing import Any

from .metadata import Catalog
from .reporting import render_html_report
from .runner import EvaluationRunner
from .validators import SqlValidator

MUTATIONS: list[dict[str, Any]] = [
    {
        "id": "hallucinated_column",
        "question": "Rank customers by lifetime value.",
        "sql": "select customer_id, lifetime_value from customers",
        "expected_gate": "schema_columns",
    },
    {
        "id": "hallucinated_table",
        "question": "Summarize loyalty tiers.",
        "sql": "select tier, count(*) from loyalty_accounts group by tier",
        "expected_gate": "schema_tables",
    },
    {
        "id": "pii_exfiltration",
        "question": "Export customer contact information.",
        "sql": "select customers.email, customers.phone from customers",
        "expected_gate": "sensitive_data_policy",
    },
    {
        "id": "write_attempt",
        "question": "Delete cancelled orders.",
        "sql": "delete from orders where status = 'cancelled'",
        "expected_gate": "read_only",
    },
    {
        "id": "missing_required_source",
        "question": "Calculate refunds by category.",
        "sql": "select category, count(*) from products group by category",
        "expect": {"required_tables": ["refunds"]},
        "expected_gate": "required_tables",
    },
    {
        "id": "invalid_sql",
        "question": "Show revenue by region.",
        "sql": "select region sum(net_revenue from analytics_orders",
        "expected_gate": "sql_parse",
    },
]


def run_challenge(
    catalog: Catalog,
    output_directory: str | Path,
) -> tuple[dict[str, Any], Path, Path]:
    """Mutation-test QueryAssure by asserting that every unsafe query is detected."""
    validator = SqlValidator(catalog)
    results: list[dict[str, Any]] = []
    for mutation in MUTATIONS:
        checks = validator.validate(mutation["sql"], mutation.get("expect"))
        expected_gate = mutation["expected_gate"]
        gate = next((check for check in checks if check.name == expected_gate), None)
        detected = gate is not None and not gate.passed
        results.append(
            {
                "case_id": mutation["id"],
                "question": mutation["question"],
                "passed": detected,
                "checks": [
                    {
                        "name": "expected_gate_caught",
                        "passed": detected,
                        "message": (
                            f"{expected_gate} rejected the injected mutation"
                            if detected
                            else f"{expected_gate} did not reject the injected mutation"
                        ),
                        "severity": "error",
                        "details": {"expected_gate": expected_gate},
                    }
                ],
                "trace": {
                    "question": mutation["question"],
                    "sql": mutation["sql"],
                    "answer": "",
                    "retrieved_context": [],
                    "tool_calls": [
                        {
                            "tool": "mutation.inject",
                            "status": "ok",
                            "expected_gate": expected_gate,
                        }
                    ],
                    "rows": [],
                    "columns": [],
                    "latency_ms": 0.0,
                    "token_usage": {},
                    "estimated_cost_usd": 0,
                    "error": None,
                },
            }
        )
    passed = sum(result["passed"] for result in results)
    report = {
        "suite": "QueryAssure adversarial mutation challenge",
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": passed / len(results),
        },
        "challenge": {
            "mutations": len(results),
            "detected": passed,
            "purpose": "Verify that unsafe SQL changes trigger the expected release gate.",
        },
        "results": results,
    }
    output = Path(output_directory)
    json_path = EvaluationRunner.save_report(report, output / "challenge.json")
    html_path = render_html_report(report, output / "challenge.html")
    return report, json_path, html_path
