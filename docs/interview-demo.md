# Five-minute interview demo

## 1. State the problem

Text-to-SQL output can be syntactically plausible while hallucinating a column, exposing a
restricted field, changing metric semantics, or exceeding an operational budget.

## 2. Run the deterministic gate

```bash
queryassure demo --output reports/demo --no-open
```

Show `5 golden paths passed`, the injected `customers.lifetime_value` hallucination, and the final
`BLOCKED FROM MERGE` verdict. Open the generated HTML evidence report if time permits.

## 3. Explain the reusable contract

Open `evals/retail.yml` and point to required tables, forbidden columns, gold SQL, latency, and
tool-call budgets. Explain that teams own their cases while a platform team owns the runner,
evidence format, and merge policy.

## 4. Connect to BigQuery

Open `docs/bigquery-assurance.md` and the checked-in BigQuery dialect test. Be explicit that DuckDB
is the deterministic execution fixture; a production BigQuery adapter would use dry-run bytes,
partition, IAM, and job metadata through the same `CheckResult` interface.

## 5. State the boundary

The retail dataset and implementation are independently created and contain no employer code,
schema, or confidential data. The project demonstrates a reusable assurance pattern rather than
claiming access to a production warehouse.
