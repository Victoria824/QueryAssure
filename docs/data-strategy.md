# Evaluation data strategy

DataAgentKit separates three kinds of data.

## 1. Deterministic synthetic business data

Northstar Retail is the default because every row can be regenerated from a versioned seed. The generator embeds known patterns—seasonality, promotion windows, stock-outs, refunds, segmentation, nulls, and access-sensitive fields—so tests have explanations rather than arbitrary expected outputs.

Every golden case contains both an expected contract and an executable reference query. This lets the runner compare result sets instead of SQL strings.

## 2. Open ecosystem examples

Optional setup scripts can fetch projects such as dbt Jaffle Shop or Chinook. These sources are never silently bundled: the user sees the source, license, version, checksum, and attribution.

| Source | Best use here | Integration policy |
|---|---|---|
| [dbt Jaffle Shop](https://github.com/dbt-labs/jaffle-shop) | manifests, lineage, tests, business definitions | user installs the Apache-2.0 project |
| [DuckDB TPC-H](https://duckdb.org/docs/current/core_extensions/tpch) | scale, latency, execution budgets, canonical answers | generated locally with `dak dataset install tpch` |
| [Chinook](https://github.com/lerocha/chinook-database) | small cross-dialect tutorials | optional MIT-licensed download |
| [Open Food Facts](https://openfoodfacts.github.io/openfoodfacts-server/api/tutorials/license-be-on-the-legal-side/) | multilingual and messy product grounding | optional ODbL source; attribution and share-alike apply |
| [NYC TLC](https://www.nyc.gov/site/tlc/about/raw-data.page) | high-volume public event data | user-provided public files, not vendored |

## 3. External research benchmarks

Spider 2.0 and BIRD compatibility should be implemented as adapters. Their data remains outside the package and is downloaded under each benchmark's own terms.

- [Spider 2.0](https://spider2-sql.github.io/) stresses enterprise-scale workflows and
  multiple SQL dialects.
- [BIRD](https://bird-bench.github.io/) provides realistic text-to-SQL tasks and external
  knowledge challenges.

## Quality dimensions

- semantic richness: joins, metrics, date logic, slowly changing behaviour
- deterministic regeneration: fixed seeds and stable IDs
- known causal patterns: promotional lift and purposeful stock-outs
- realistic dirtiness: null text, cancelled orders, sparse reviews
- governance: PII tags, tenant boundaries, restricted fields
- mutation readiness: schema rename, deletion, new look-alike columns
- scalability: adjustable row counts and optional TPC-H generation

Synthetic data is not meant to imitate a real company's records. It is a controlled environment for testing system behaviour.

## How Northstar earns trust

Generation and validation are separate. `dak seed` creates the database from a fixed seed;
`dak validate-data` independently verifies referential integrity, numeric bounds, synthetic
PII, category/time coverage, and the deliberately planted Western frozen-stock signal. It
also emits an aggregate fingerprint so contributors can identify unintended data drift.

Golden tests use executable reference queries and compare result sets, not literal SQL.
Chaos scenarios separately describe security, schema-drift, and metadata-injection failures.
This combination makes the data useful for correctness, reliability, governance, and
regression testing—not merely for making a chat demo look populated.
