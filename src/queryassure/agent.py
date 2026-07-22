from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Protocol

from .metadata import Catalog
from .models import AgentTrace
from .validators import SqlValidator, execute_read_only


class ModelProvider(Protocol):
    def generate_sql(self, question: str, schema: str) -> tuple[str, dict[str, int]]: ...


DEMO_QUERIES: list[tuple[tuple[str, ...], str]] = [
    (
        ("weekly", "category", "revenue"),
        """select week, category, round(revenue, 2) as revenue
from weekly_category_performance
where week >= date '2026-01-01'
order by week, revenue desc""",
    ),
    (
        ("region", "revenue"),
        """select region, round(sum(net_revenue), 2) as net_revenue,
       count(distinct order_id) as orders
from analytics_orders
where ordered_at >= date '2026-01-01'
group by region
order by net_revenue desc""",
    ),
    (
        ("basket", "channel"),
        """select channel, round(avg(net_revenue), 2) as average_order_value,
       count(*) as orders
from analytics_orders
where ordered_at >= date '2026-01-01'
group by channel
order by average_order_value desc""",
    ),
    (
        ("refund", "category"),
        """select p.category, round(sum(r.refund_amount), 2) as refund_amount,
       count(*) as refunded_items
from refunds r
join order_items oi using(order_item_id)
join products p using(product_id)
group by p.category
order by refund_amount desc""",
    ),
    (
        ("stock", "risk", "frozen"),
        """select s.region, i.snapshot_date,
       round(avg(i.units_on_hand), 1) as avg_units_on_hand,
       sum(case when i.units_on_hand <= i.reorder_point then 1 else 0 end) as low_stock_skus
from inventory_snapshots i
join stores s using(store_id)
join products p using(product_id)
where p.category = 'Frozen' and i.snapshot_date >= date '2026-04-01'
group by s.region, i.snapshot_date
order by i.snapshot_date, s.region""",
    ),
    (
        ("customer", "segment"),
        """select segment, count(distinct customer_id) as customers,
       round(sum(net_revenue), 2) as net_revenue,
       round(avg(net_revenue), 2) as avg_order_value
from analytics_orders
where ordered_at >= date '2026-01-01'
group by segment
order by net_revenue desc""",
    ),
]


class OpenAIProvider:
    def __init__(self, model: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Install queryassure[openai] to use OpenAI") from exc
        self.client = OpenAI()
        self.model = model or os.getenv("QUERYASSURE_MODEL", "gpt-4.1-mini")

    def generate_sql(self, question: str, schema: str) -> tuple[str, dict[str, int]]:
        response = self.client.responses.create(
            model=self.model,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You generate one read-only DuckDB SELECT query. "
                        "Use only the supplied schema. Return JSON with a single sql field."
                    ),
                },
                {"role": "user", "content": f"Schema:\n{schema}\n\nQuestion:\n{question}"},
            ],
        )
        text = response.output_text.strip()
        match = re.search(r"\{.*\}", text, re.DOTALL)
        sql = json.loads(match.group(0) if match else text)["sql"]
        usage = getattr(response, "usage", None)
        return sql, {
            "input": getattr(usage, "input_tokens", 0) if usage else 0,
            "output": getattr(usage, "output_tokens", 0) if usage else 0,
        }


class SqlAgent:
    """A small reference SQL Agent that is intentionally easy to test."""

    def __init__(
        self,
        database: str | Path,
        catalog: Catalog,
        provider: ModelProvider | None = None,
    ) -> None:
        self.database = Path(database)
        self.catalog = catalog
        self.provider = provider
        self.validator = SqlValidator(catalog)

    def _demo_sql(self, question: str) -> str:
        normalized = question.lower()
        scored = [
            (sum(keyword in normalized for keyword in keywords), sql)
            for keywords, sql in DEMO_QUERIES
        ]
        score, sql = max(scored, key=lambda item: item[0])
        if score == 0:
            return """select region, round(sum(net_revenue), 2) as net_revenue
from analytics_orders
group by region
order by net_revenue desc"""
        return sql

    def ask(self, question: str) -> AgentTrace:
        started = time.perf_counter()
        context = self.catalog.retrieve(question)
        tool_calls: list[dict[str, Any]] = [
            {"tool": "metadata.retrieve", "status": "ok", "items": len(context)}
        ]
        tokens: dict[str, int] = {}
        if self.provider:
            sql, tokens = self.provider.generate_sql(question, self.catalog.schema_prompt(context))
            mode = "llm"
        else:
            sql = self._demo_sql(question)
            mode = "deterministic-demo"
        tool_calls.append({"tool": "sql.generate", "status": "ok", "mode": mode})
        checks = self.validator.validate(sql)
        failed = [check for check in checks if not check.passed]
        tool_calls.append(
            {
                "tool": "sql.validate",
                "status": "failed" if failed else "ok",
                "checks": len(checks),
            }
        )
        if failed:
            return AgentTrace(
                question=question,
                sql=sql,
                retrieved_context=context,
                tool_calls=tool_calls,
                token_usage=tokens,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error="; ".join(check.message for check in failed),
            )
        try:
            columns, rows = execute_read_only(self.database, sql)
            tool_calls.append({"tool": "duckdb.execute", "status": "ok", "rows": len(rows)})
        except Exception as exc:  # pragma: no cover - exercised by integration tests
            return AgentTrace(
                question=question,
                sql=sql,
                retrieved_context=context,
                tool_calls=tool_calls,
                token_usage=tokens,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
            )
        answer = (
            f"I generated and validated a read-only query, then returned {len(rows)} rows. "
            "Open the SQL and trace panels to inspect how the answer was grounded."
        )
        return AgentTrace(
            question=question,
            sql=sql,
            answer=answer,
            retrieved_context=context,
            tool_calls=tool_calls,
            rows=rows,
            columns=columns,
            token_usage=tokens,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
