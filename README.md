# DataAgentKit

**Test data agents before they test production.**

[![CI](https://github.com/Victoria824/DataAgentKit/actions/workflows/ci.yml/badge.svg)](https://github.com/Victoria824/DataAgentKit/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

[Try the zero-key playground](https://dataagentkit-playground.vicalayy.chatgpt.site) · [View the repository](https://github.com/Victoria824/DataAgentKit) · [Read the data strategy](docs/data-strategy.md)

DataAgentKit is an open-source SQL Agent playground plus a contract-testing and CI quality-gate toolkit for agentic analytics. Ask questions in a polished chat interface, inspect the retrieved metadata, generated SQL, validation decisions, and results—then test the same agent for correctness, security, latency, and regressions.

> Status: early alpha. The deterministic demo, HTTP/Python adapters, data-quality checks,
> and core validation pipeline work today.

## Why this project exists

Text-to-SQL demos are easy. Reliable data agents are not.

A production agent must survive prompt changes, model upgrades, schema drift, ambiguous metrics, sensitive columns, invalid joins, runaway queries, and unexpected tool traces. DataAgentKit treats those behaviours as testable software contracts.

```text
Question → metadata retrieval → SQL generation → policy validation
         → read-only execution → result → trace
                                  ↓
                  DataAgentKit contract tests + CI gate
```

## Two independent tools

### SQL Agent playground

- inspectable chat interface
- schema and business-metric retrieval
- deterministic mode requiring no API key
- optional OpenAI provider
- dialect-aware SQL validation
- read-only DuckDB execution
- visible tool trace and quality gates
- FastAPI endpoint for local integrations

### DataAgentKit

- YAML test cases that live beside your code
- SQL parsing and read-only enforcement
- table and column grounding checks
- sensitive-data policy checks
- execution-result equivalence
- latency and tool-call budgets
- baseline/candidate regression comparison
- JSON reports suitable for CI

## Quickstart

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Generate deterministic retail data
dak seed
dak validate-data

# Run the included agent against the golden suite
dak test --suite evals/retail.yml

# Start the reference agent API
dak serve
```

The API is available at `http://127.0.0.1:8000`, with interactive documentation at `/docs`.

Run the web experience separately:

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.

The [hosted playground](https://dataagentkit-playground.vicalayy.chatgpt.site) is a zero-key interactive walkthrough. For real query execution,
run `dak serve`; the same questions, metadata retrieval, SQL gates, and result traces are
available through `POST /api/chat`.

## A test case is a contract

```yaml
- id: revenue_by_region
  question: Which region generated the most net revenue in 2026?
  expect:
    required_tables: [analytics_orders]
    forbidden_columns: [customers.email, customers.phone]
    gold_sql: |
      select region, round(sum(net_revenue), 2) as net_revenue
      from analytics_orders
      where ordered_at >= date '2026-01-01'
      group by region
      order by net_revenue desc
  budgets:
    max_latency_ms: 5000
    max_tool_calls: 5
```

DataAgentKit compares result sets instead of requiring exact SQL text, because two valid queries can express the same answer.

## Reference dataset: Northstar Retail

The included dataset is deterministic and synthetic. It models an omnichannel Canadian grocery business across:

- customers and behavioural segments
- stores and operating regions
- products, categories, prices, and costs
- orders, line items, promotions, and refunds
- weekly inventory snapshots
- product reviews with realistic missingness
- curated analytics views and business metrics

It intentionally includes seasonality, promotion lift, refund patterns, stock-out scenarios, cancelled orders, sparse fields, PII-classified columns, and tenant boundaries. This provides both clean golden paths and meaningful failure cases without distributing personal or proprietary data.

### Additional data adapters on the roadmap

| Source | Purpose | Distribution approach |
|---|---|---|
| dbt Jaffle Shop | dbt manifest and lineage tests | setup script / attribution |
| DuckDB TPC-H | scalable execution and cost tests | generated locally with `dbgen` |
| Chinook | cross-dialect compatibility | optional download adapter |
| Open Food Facts | messy real-world product metadata | optional adapter; ODbL attribution |
| Spider 2.0 / BIRD | external benchmark compatibility | user-provided benchmark download |

Large third-party datasets are not vendored into this repository. Discover the supported
matrix or generate a local TPC-H database with:

```bash
dak dataset list
dak dataset install tpch --output data/tpch.duckdb --scale 0.1
```

Northstar Retail is the default because it is deterministic, redistributable, fast enough
for CI, and intentionally contains signals that ordinary random-data generators miss. Run
`dak validate-data` to check referential integrity, price/refund bounds, synthetic-only PII,
time/category coverage, a designed stock-out pattern, and a reproducibility fingerprint.

## Architecture

```text
apps/web                         interactive public experience
src/dataagentkit/agent.py        independently usable SQL Agent
src/dataagentkit/api.py          FastAPI adapter
src/dataagentkit/generator.py    deterministic data generator
src/dataagentkit/metadata.py     metadata catalog and retrieval
src/dataagentkit/validators.py   SQL/schema/policy validation
src/dataagentkit/runner.py       test runner and report comparison
src/dataagentkit/adapters.py     Python callable and HTTP agent adapters
src/dataagentkit/datasets.py     dataset catalog and local generators
src/dataagentkit/data_quality.py synthetic-data contracts and fingerprint
evals/                           golden and chaos suites
metadata/                        schema, relationships, policies, metrics
```

The core package has no LangChain or LangGraph dependency. Agent frameworks connect through adapters rather than becoming mandatory runtime dependencies.

To evaluate an existing HTTP agent that accepts `{ "question": "..." }` and returns an
`AgentTrace`-shaped object:

```bash
dak test-http \
  --url http://localhost:8000/api/chat \
  --database data/retail.duckdb \
  --suite evals/retail.yml
```

## Optional live model

Demo mode is intentionally deterministic and free. To exercise a live OpenAI model:

```bash
pip install -e '.[openai]'
export OPENAI_API_KEY=your-key-in-your-shell
dak test --live
```

Never commit model keys. `.env` files are ignored.

## Safety model

- database connections are opened read-only
- write operations are rejected before execution
- restricted columns are enforced from versioned metadata
- returned rows are capped
- tests can block releases on policy regressions
- no production data is required for the included demo

This is an engineering toolkit, not a complete authorization system. Production deployments must also enforce permissions in the warehouse itself.

## One-week roadmap

- **Day 1–2:** working dataset, reference agent, SQL/schema/policy validators
- **Day 3:** golden suite, result equivalence, CLI reports
- **Day 4:** public chat playground and inspectable traces
- **Day 5:** CI workflow, Docker path, documentation
- **Day 6:** schema-drift and metadata-injection mutation runner
- **Day 7:** launch benchmark, public release, and contributor onboarding

The detailed scope, launch checklist, and first-week success measures are in
[docs/launch-plan.md](docs/launch-plan.md).

## Contributing

Small, focused contributions are welcome—especially database adapters, deterministic policy rules, reproducible failure cases, and documentation fixes. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. Third-party datasets retain their original licenses and are only fetched through optional adapters with attribution.
