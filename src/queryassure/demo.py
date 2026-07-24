from __future__ import annotations

from pathlib import Path
from typing import Any

from .agent import SqlAgent
from .generator import generate_retail_database
from .metadata import Catalog
from .models import AgentTrace
from .reporting import render_html_report
from .runner import EvaluationRunner

DEMO_CASES: list[dict[str, Any]] = [
    {
        "id": "revenue_by_region",
        "question": "Which region generated the most net revenue in 2026?",
        "expect": {
            "required_tables": ["analytics_orders"],
            "gold_sql": """
                select region, round(sum(net_revenue), 2) as net_revenue,
                       count(distinct order_id) as orders
                from analytics_orders
                where ordered_at >= date '2026-01-01'
                group by region order by net_revenue desc
            """,
        },
        "budgets": {"max_latency_ms": 5000, "max_tool_calls": 5},
    },
    {
        "id": "average_basket_by_channel",
        "question": "Compare average basket value by channel for 2026.",
        "expect": {
            "required_tables": ["analytics_orders"],
            "gold_sql": """
                select channel, round(avg(net_revenue), 2) as average_order_value,
                       count(*) as orders
                from analytics_orders
                where ordered_at >= date '2026-01-01'
                group by channel order by average_order_value desc
            """,
        },
        "budgets": {"max_latency_ms": 5000, "max_tool_calls": 5},
    },
    {
        "id": "refunds_by_category",
        "question": "Which product category has the highest refund amount?",
        "expect": {
            "required_tables": ["refunds", "order_items", "products"],
            "gold_sql": """
                select p.category, round(sum(r.refund_amount), 2) as refund_amount,
                       count(*) as refunded_items
                from refunds r
                join order_items oi using(order_item_id)
                join products p using(product_id)
                group by p.category order by refund_amount desc
            """,
        },
        "budgets": {"max_latency_ms": 5000, "max_tool_calls": 5},
    },
    {
        "id": "frozen_stockouts",
        "question": "Show the weekly frozen category stock risk by region since April 2026.",
        "expect": {
            "required_tables": ["inventory_snapshots", "stores", "products"],
            "gold_sql": """
                select s.region, i.snapshot_date,
                       round(avg(i.units_on_hand), 1) as avg_units_on_hand,
                       sum(case when i.units_on_hand <= i.reorder_point then 1 else 0 end)
                         as low_stock_skus
                from inventory_snapshots i
                join stores s using(store_id)
                join products p using(product_id)
                where p.category = 'Frozen' and i.snapshot_date >= date '2026-04-01'
                group by s.region, i.snapshot_date order by i.snapshot_date, s.region
            """,
        },
        "budgets": {"max_latency_ms": 5000, "max_tool_calls": 5},
    },
    {
        "id": "segment_performance",
        "question": "Compare customer segment revenue and average order value in 2026.",
        "expect": {
            "required_tables": ["analytics_orders"],
            "gold_sql": """
                select segment, count(distinct customer_id) as customers,
                       round(sum(net_revenue), 2) as net_revenue,
                       round(avg(net_revenue), 2) as avg_order_value
                from analytics_orders
                where ordered_at >= date '2026-01-01'
                group by segment order by net_revenue desc
            """,
        },
        "budgets": {"max_latency_ms": 5000, "max_tool_calls": 5},
    },
]


class _HallucinatingAgent:
    """A controlled mutation used to prove that the quality gate blocks regressions."""

    def ask(self, question: str) -> AgentTrace:
        return AgentTrace(
            question=question,
            sql=(
                "select customer_id, lifetime_value "
                "from customers order by lifetime_value desc limit 20"
            ),
            answer="The highest-lifetime-value customers are listed below.",
            retrieved_context=[
                {
                    "kind": "table",
                    "name": "customers",
                    "columns": ["customer_id", "segment", "region"],
                }
            ],
            tool_calls=[
                {"tool": "metadata.retrieve", "status": "ok", "items": 1},
                {"tool": "sql.generate", "status": "ok", "mode": "injected-regression"},
            ],
            latency_ms=42.8,
        )


def run_demo(output_directory: str | Path) -> tuple[dict[str, Any], Path, Path]:
    """Run five golden contracts plus one intentionally unsafe SQL mutation."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    database = generate_retail_database(output / "northstar.duckdb", orders=1_000)
    catalog = Catalog.from_duckdb(database)
    catalog.policies = {"forbidden_columns": ["customers.email", "customers.phone"]}

    golden_runner = EvaluationRunner(SqlAgent(database, catalog), database, catalog)
    results = [golden_runner.run_case(case) for case in DEMO_CASES]
    mutation_runner = EvaluationRunner(_HallucinatingAgent(), database, catalog)
    results.append(
        mutation_runner.run_case(
            {
                "id": "schema_hallucination_regression",
                "question": "Rank customers by lifetime value.",
                "expect": {"required_tables": ["customers"]},
            }
        )
    )
    passed = sum(result.passed for result in results)
    report = {
        "suite": "QueryAssure 30-second regression demo",
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "pass_rate": passed / len(results),
        },
        "demo": {
            "expected_regressions": 1,
            "regressions_caught": len(results) - passed,
            "mutation": "hallucinated customers.lifetime_value column",
        },
        "results": [result.to_dict() for result in results],
    }
    json_path = EvaluationRunner.save_report(report, output / "queryassure-demo.json")
    html_path = render_html_report(report, output / "queryassure-demo.html")
    return report, json_path, html_path
