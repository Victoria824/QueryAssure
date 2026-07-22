from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb

QUALITY_CHECKS: list[tuple[str, str, str]] = [
    (
        "order_customer_integrity",
        "select count(*) from orders o left join customers c using(customer_id) "
        "where c.customer_id is null",
        "zero",
    ),
    (
        "item_order_integrity",
        "select count(*) from order_items i left join orders o using(order_id) "
        "where o.order_id is null",
        "zero",
    ),
    (
        "product_price_bounds",
        "select count(*) from products where unit_price <= 0 or unit_cost <= 0 "
        "or unit_cost >= unit_price",
        "zero",
    ),
    (
        "discount_bounds",
        "select count(*) from order_items where discount_amount < 0 "
        "or discount_amount > quantity * unit_price",
        "zero",
    ),
    (
        "refund_bounds",
        "select count(*) from refunds r join order_items i using(order_item_id) "
        "where r.refund_amount < 0 "
        "or r.refund_amount > i.quantity * i.unit_price - i.discount_amount",
        "zero",
    ),
    (
        "synthetic_pii",
        "select count(*) from customers where not email like '%@example.test'",
        "zero",
    ),
    (
        "category_coverage",
        "select count(distinct category) from products",
        "at_least_6",
    ),
    (
        "time_coverage",
        "select count(distinct date_trunc('month', ordered_at)) from orders",
        "at_least_24",
    ),
    (
        "designed_stockout_signal",
        "select count(*) from inventory_snapshots i join stores s using(store_id) "
        "join products p using(product_id) where s.region = 'West' and p.category = 'Frozen' "
        "and snapshot_date >= date '2026-04-20' and units_on_hand <= reorder_point",
        "positive",
    ),
]


def validate_retail_data(database: str | Path) -> dict[str, Any]:
    connection = duckdb.connect(str(database), read_only=True)
    results: list[dict[str, Any]] = []
    for name, query, rule in QUALITY_CHECKS:
        value = int(connection.execute(query).fetchone()[0])
        passed = (
            value == 0
            if rule == "zero"
            else value >= 6
            if rule == "at_least_6"
            else value >= 24
            if rule == "at_least_24"
            else value > 0
        )
        results.append({"name": name, "passed": passed, "value": value, "rule": rule})

    signature_payload = connection.execute(
        """
        select
          (select count(*) from orders) as orders,
          (select count(*) from order_items) as items,
          (select round(sum(net_revenue), 2) from analytics_orders) as net_revenue,
          (select count(*) from refunds) as refunds,
          (select count(*) from inventory_snapshots) as snapshots
        """
    ).fetchone()
    connection.close()
    signature_json = json.dumps(signature_payload, default=str).encode()
    fingerprint = hashlib.sha256(signature_json).hexdigest()[:16]
    passed = sum(item["passed"] for item in results)
    return {
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "fingerprint": fingerprint,
        },
        "checks": results,
    }
