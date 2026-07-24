from __future__ import annotations

from pathlib import Path

STARTER_SUITE = """name: My SQL Agent contracts
version: 1
cases:
  - id: revenue_by_region
    question: Which region generated the most net revenue in 2026?
    expect:
      required_tables: [analytics_orders]
      forbidden_columns: [customers.email, customers.phone]
      gold_sql: |
        select region, round(sum(net_revenue), 2) as net_revenue,
               count(distinct order_id) as orders
        from analytics_orders
        where ordered_at >= date '2026-01-01'
        group by region
        order by net_revenue desc
    budgets:
      max_latency_ms: 5000
      max_tool_calls: 5
"""

STARTER_CATALOG = """version: 1
policies:
  forbidden_columns:
    - customers.email
    - customers.phone
tables:
  analytics_orders:
    description: Curated completed orders.
    columns:
      order_id: {type: bigint, description: Unique order key}
      ordered_at: {type: timestamp, description: Order timestamp}
      region: {type: varchar, description: Operating region}
      net_revenue: {type: decimal, description: Revenue after discounts and refunds}
  customers:
    description: Customer profiles with restricted contact fields.
    columns:
      customer_id: {type: integer, description: Unique customer key}
      email: {type: varchar, description: Restricted email, classification: pii}
      phone: {type: varchar, description: Restricted phone, classification: pii}
"""

STARTER_WORKFLOW = """name: SQL Agent quality gate
on: [pull_request]

jobs:
  queryassure:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: Victoria824/QueryAssure@v0.4.0
        with:
          suite: queryassure/evals.yml
          catalog: queryassure/catalog.yml
          report: reports/queryassure.json
          html-report: reports/queryassure.html
"""

STARTER_README = """# QueryAssure contracts

This directory is the versioned quality contract for your SQL Agent.

- `evals.yml` defines expected tables, golden results, policies, and budgets.
- `catalog.yml` grounds table and column references.
- `.github/workflows/queryassure.yml` runs the gate on every pull request.

Start with the zero-key sample, then point the GitHub Action's `agent-url` input at
your running HTTP agent. The endpoint should accept `{"question": "..."}` and return
an AgentTrace-shaped JSON response.

Run the included regression demo locally:

```bash
uvx --from git+https://github.com/Victoria824/QueryAssure queryassure demo
```
"""


def create_starter_project(directory: str | Path, *, force: bool = False) -> list[Path]:
    root = Path(directory)
    files = {
        root / "queryassure" / "evals.yml": STARTER_SUITE,
        root / "queryassure" / "catalog.yml": STARTER_CATALOG,
        root / "queryassure" / "README.md": STARTER_README,
        root / ".github" / "workflows" / "queryassure.yml": STARTER_WORKFLOW,
    }
    conflicts = [path for path in files if path.exists() and not force]
    if conflicts:
        joined = ", ".join(str(path) for path in conflicts)
        raise FileExistsError(f"Refusing to overwrite existing files: {joined}")
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return list(files)
