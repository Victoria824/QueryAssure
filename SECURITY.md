# Security policy

QueryAssure evaluates systems that may touch sensitive schemas and SQL traces. Please do
not include credentials, personal information, proprietary schemas, production query
results, or private model prompts in public issues.

## Supported versions

| Version | Supported |
|---|---|
| 0.3.x | Yes |
| 0.2.x and earlier | No |

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
