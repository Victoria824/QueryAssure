from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

CATEGORIES = {
    "Fresh": ["Organic Bananas", "Honeycrisp Apples", "Baby Spinach", "Avocados"],
    "Pantry": ["Basmati Rice", "Penne Pasta", "Tomato Sauce", "Olive Oil"],
    "Dairy": ["Greek Yogurt", "Oat Milk", "Cheddar Cheese", "Free Range Eggs"],
    "Frozen": ["Berry Blend", "Vegetable Pizza", "Mango Chunks", "Veggie Burgers"],
    "Snacks": ["Sea Salt Chips", "Granola Bars", "Dark Chocolate", "Trail Mix"],
    "Beverages": ["Sparkling Water", "Cold Brew", "Orange Juice", "Green Tea"],
}
REGIONS = ["Toronto", "West", "Prairies", "Quebec", "Atlantic"]
SEGMENTS = ["New", "Occasional", "Loyal", "High Value"]


def _weighted_choice(rng: random.Random, items: list[str], weights: list[float]) -> str:
    return rng.choices(items, weights=weights, k=1)[0]


def generate_retail_database(
    path: str | Path,
    *,
    seed: int = 20260722,
    orders: int = 8_000,
) -> Path:
    """Generate deterministic retail data with seasonality and known failure cases."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    rng = random.Random(seed)
    connection = duckdb.connect(str(target))
    connection.execute(
        """
        create table stores(
          store_id integer primary key, store_name varchar, region varchar,
          opened_at date, format varchar, tenant_id integer
        );
        create table customers(
          customer_id integer primary key, customer_name varchar, email varchar,
          phone varchar, segment varchar, region varchar, joined_at date, tenant_id integer
        );
        create table products(
          product_id integer primary key, product_name varchar, category varchar,
          brand varchar, unit_price decimal(10,2), unit_cost decimal(10,2),
          is_perishable boolean, tenant_id integer
        );
        create table promotions(
          promotion_id integer primary key, promotion_name varchar, category varchar,
          discount_pct decimal(5,2), starts_at date, ends_at date, tenant_id integer
        );
        create table orders(
          order_id bigint primary key, customer_id integer, store_id integer,
          ordered_at timestamp, channel varchar, status varchar, tenant_id integer
        );
        create table order_items(
          order_item_id bigint primary key, order_id bigint, product_id integer,
          promotion_id integer, quantity integer, unit_price decimal(10,2),
          discount_amount decimal(10,2), tenant_id integer
        );
        create table refunds(
          refund_id bigint primary key, order_item_id bigint, refunded_at timestamp,
          refund_amount decimal(10,2), reason varchar, tenant_id integer
        );
        create table inventory_snapshots(
          snapshot_date date, store_id integer, product_id integer,
          units_on_hand integer, reorder_point integer, tenant_id integer
        );
        create table product_reviews(
          review_id bigint primary key, customer_id integer, product_id integer,
          rating integer, review_text varchar, created_at timestamp, tenant_id integer
        );
        """
    )

    stores = []
    for store_id in range(1, 16):
        region = REGIONS[(store_id - 1) % len(REGIONS)]
        stores.append(
            (
                store_id,
                f"{region} Market {1 + (store_id - 1) // len(REGIONS)}",
                region,
                date(2018, 1, 1) + timedelta(days=rng.randint(0, 1600)),
                "Urban" if store_id % 3 else "Suburban",
                1 if store_id <= 12 else 2,
            )
        )
    connection.executemany("insert into stores values (?, ?, ?, ?, ?, ?)", stores)

    products = []
    product_id = 1
    for category, names in CATEGORIES.items():
        for variation in range(4):
            for name in names:
                price = round(rng.uniform(2.5, 18.0) * (1 + variation * 0.08), 2)
                products.append(
                    (
                        product_id,
                        f"{name} {['Classic', 'Family', 'Select', 'Value'][variation]}",
                        category,
                        f"Northstar {1 + product_id % 9}",
                        price,
                        round(price * rng.uniform(0.45, 0.72), 2),
                        category in {"Fresh", "Dairy", "Frozen"},
                        1,
                    )
                )
                product_id += 1
    connection.executemany("insert into products values (?, ?, ?, ?, ?, ?, ?, ?)", products)

    customers = []
    for customer_id in range(1, 1_501):
        region = _weighted_choice(rng, REGIONS, [0.34, 0.2, 0.16, 0.2, 0.1])
        segment = _weighted_choice(rng, SEGMENTS, [0.18, 0.36, 0.33, 0.13])
        joined = date(2021, 1, 1) + timedelta(days=rng.randint(0, 1600))
        customers.append(
            (
                customer_id,
                f"Customer {customer_id:04d}",
                f"customer{customer_id:04d}@example.test",
                f"+1-555-{customer_id % 1000:03d}-{(customer_id * 37) % 10000:04d}",
                segment,
                region,
                joined,
                1,
            )
        )
    connection.executemany("insert into customers values (?, ?, ?, ?, ?, ?, ?, ?)", customers)

    promotions = [
        (1, "Summer Fresh", "Fresh", 15.0, date(2025, 6, 1), date(2025, 8, 31), 1),
        (2, "Back to School", "Snacks", 20.0, date(2025, 8, 15), date(2025, 9, 30), 1),
        (3, "Holiday Pantry", "Pantry", 12.0, date(2025, 11, 15), date(2025, 12, 31), 1),
        (4, "New Year Wellness", "Beverages", 18.0, date(2026, 1, 1), date(2026, 2, 15), 1),
    ]
    connection.executemany("insert into promotions values (?, ?, ?, ?, ?, ?, ?)", promotions)

    start = datetime(2024, 1, 1)
    end = datetime(2026, 6, 30, 23, 59)
    seconds = int((end - start).total_seconds())
    order_rows = []
    item_rows = []
    refund_rows = []
    review_rows = []
    item_id = refund_id = review_id = 1
    product_lookup = {row[0]: row for row in products}
    customer_segments = {row[0]: row[4] for row in customers}
    for order_id in range(1, orders + 1):
        customer_id = rng.randint(1, len(customers))
        segment = customer_segments[customer_id]
        timestamp = start + timedelta(seconds=rng.randint(0, seconds))
        seasonal = 1.0 + 0.2 * math.sin((timestamp.timetuple().tm_yday / 365) * math.tau)
        channel = _weighted_choice(rng, ["delivery", "pickup", "in_store"], [0.44, 0.2, 0.36])
        status = _weighted_choice(rng, ["completed", "cancelled"], [0.975, 0.025])
        store_id = rng.randint(1, 12)
        order_rows.append((order_id, customer_id, store_id, timestamp, channel, status, 1))
        item_count = rng.randint(1, 4) + (1 if segment in {"Loyal", "High Value"} else 0)
        for _ in range(item_count):
            pid = rng.randint(1, len(products))
            product = product_lookup[pid]
            quantity = max(1, int(rng.expovariate(0.9)))
            price = float(product[4]) * seasonal
            unit_price = round(price, 2)
            promotion_id = None
            discount = 0.0
            for promo in promotions:
                if product[2] == promo[2] and promo[4] <= timestamp.date() <= promo[5]:
                    promotion_id = promo[0]
                    discount = round(price * quantity * float(promo[3]) / 100, 2)
                    break
            item_rows.append(
                (item_id, order_id, pid, promotion_id, quantity, unit_price, discount, 1)
            )
            if status == "completed" and rng.random() < (0.075 if product[6] else 0.035):
                amount = round(unit_price * quantity - discount, 2)
                refund_rows.append(
                    (
                        refund_id,
                        item_id,
                        timestamp + timedelta(days=rng.randint(1, 21)),
                        amount,
                        _weighted_choice(
                            rng,
                            ["damaged", "quality", "late_delivery", "changed_mind"],
                            [0.25, 0.34, 0.16, 0.25],
                        ),
                        1,
                    )
                )
                refund_id += 1
            if status == "completed" and rng.random() < 0.055:
                rating = _weighted_choice(rng, [1, 2, 3, 4, 5], [0.04, 0.07, 0.16, 0.36, 0.37])
                review_rows.append(
                    (
                        review_id,
                        customer_id,
                        pid,
                        int(rating),
                        None if rng.random() < 0.1 else f"Synthetic review: rating {rating}",
                        timestamp + timedelta(days=rng.randint(1, 14)),
                        1,
                    )
                )
                review_id += 1
            item_id += 1
    connection.executemany("insert into orders values (?, ?, ?, ?, ?, ?, ?)", order_rows)
    connection.executemany("insert into order_items values (?, ?, ?, ?, ?, ?, ?, ?)", item_rows)
    connection.executemany("insert into refunds values (?, ?, ?, ?, ?, ?)", refund_rows)
    connection.executemany("insert into product_reviews values (?, ?, ?, ?, ?, ?, ?)", review_rows)

    # Generate the dense fact table inside DuckDB. A stable hash keeps the data reproducible
    # while avoiding tens of thousands of Python-to-database round trips.
    connection.execute(
        f"""
        insert into inventory_snapshots
        select
          date '2026-01-05' + cast(week * 7 as integer) as snapshot_date,
          store_id,
          product_id,
          case
            when category = 'Frozen' and store_id in (2, 7, 12) and week > 15
              then cast(hash({seed}, week, store_id, product_id) % 6 as integer)
            else 8 + cast(hash({seed}, week, store_id, product_id) % 83 as integer)
          end as units_on_hand,
          8 as reorder_point,
          1 as tenant_id
        from range(0, 26) as w(week)
        cross join range(1, 13) as s(store_id)
        cross join products
        """
    )

    connection.execute(
        """
        create view analytics_orders as
        select o.order_id, o.ordered_at, o.channel, o.customer_id, o.store_id,
               s.region, c.segment,
               sum(oi.quantity * oi.unit_price) as gross_revenue,
               sum(oi.discount_amount) as discount_amount,
               sum(oi.quantity * oi.unit_price - oi.discount_amount)
                 - coalesce(sum(r.refund_amount), 0) as net_revenue,
               coalesce(sum(r.refund_amount), 0) as refund_amount
        from orders o
        join order_items oi using(order_id)
        join customers c using(customer_id)
        join stores s using(store_id)
        left join refunds r using(order_item_id)
        where o.status = 'completed' and o.tenant_id = 1
        group by all;

        create view weekly_category_performance as
        select date_trunc('week', o.ordered_at) as week, p.category,
               sum(oi.quantity * oi.unit_price - oi.discount_amount) as revenue,
               sum(oi.quantity) as units,
               count(distinct o.order_id) as orders
        from orders o
        join order_items oi using(order_id)
        join products p using(product_id)
        where o.status = 'completed' and o.tenant_id = 1
        group by all;
        """
    )
    connection.execute("analyze")
    connection.close()
    return target
