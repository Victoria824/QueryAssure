# Security policy

QueryAssure evaluates systems that may touch sensitive schemas and SQL traces. Please do
not include credentials, personal information, proprietary schemas, production query
results, or private model prompts in public issues.

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x | Yes |
| 0.3.x and earlier | No |

## Reporting a vulnerability

Use GitHub's private vulnerability reporting flow:

<https://github.com/Victoria824/QueryAssure/security/advisories/new>

Include the affected version, impact, minimal sanitized reproduction, and any suggested
mitigation. Please allow a reasonable remediation window before public disclosure.

## Scope

Reports about write-query bypasses, sensitive-column policy bypasses, unsafe credential
handling, dependency compromise, or unintentional data transmission are in scope. Model
quality disagreements without a security or privacy impact belong in the public issue
tracker.

## Security defaults

- SQL is parsed as exactly one query before execution.
- DuckDB is opened read-only with external access and extension loading disabled.
- Query execution is bounded by time, row, memory, temporary-storage, and thread limits.
- Evidence reports remove result rows and redact common credential-shaped fields.
- Live model API access is off unless `QUERYASSURE_LIVE_ENABLED=true`.
- Set `QUERYASSURE_API_TOKEN` whenever the API is reachable by another user or host.
- Docker Compose publishes only on loopback and runs both images as non-root.

QueryAssure is not a sandbox for hostile tenants. Warehouse permissions remain the final
authorization boundary. For public or multi-user deployments, run execution in an
ephemeral isolated worker, add an authenticated gateway with per-user rate limits, and
avoid returning raw schemas or query results unless the caller is authorized.
