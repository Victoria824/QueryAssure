# BigQuery assurance mapping

QueryAssure's zero-key execution fixture uses DuckDB, but the validation boundary is dialect-aware.
The checked-in test `test_bigquery_dialect_keeps_schema_and_sensitive_data_gates` parses BigQuery
SQL with SQLGlot and proves that schema grounding, required-table contracts, and restricted-column
policy remain active for qualified warehouse tables.

## What is implemented

- `SqlValidator(..., dialect="bigquery")` for BigQuery parsing.
- Qualified catalog names such as `analytics.orders`.
- BigQuery expressions such as `SAFE_DIVIDE` and `DATE(...)`.
- Required-table, unknown-column, read-only, and sensitive-data checks.
- Database-neutral catalog construction from normalized metadata rows.

## Production adapter boundary

A production BigQuery adapter should use the BigQuery dry-run API before execution and return its
evidence through the existing `CheckResult` contract. Recommended additional policies are:

1. Require a partition predicate for configured large tables.
2. Reject queries whose dry-run `totalBytesProcessed` exceeds the contract budget.
3. Resolve authorized views and policy tags into the catalog.
4. Run jobs with a least-privileged service account and an explicit billing project.
5. Record job ID, location, bytes processed, cache status, and policy version in the report.

The repository does not claim that a live BigQuery job is currently executed. DuckDB keeps CI
deterministic and free; the validator test proves the portable policy boundary without requiring
cloud credentials.

## Interview explanation

> DuckDB is my deterministic execution fixture. The assurance layer is not tied to DuckDB: SQL is
> parsed using the target dialect, metadata is normalized behind a catalog interface, and the
> checks return database-neutral evidence. For BigQuery I would add a dry-run adapter so partition
> and bytes-scanned policies can block an unsafe query before a job starts.
