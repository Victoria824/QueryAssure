# Enterprise governance and tamper-evident evidence

QueryAssure's governance layer sits before agent tool execution. It evaluates an
authenticated subject, tenant, role set, requested action, target resource, data
classification, deployment environment, and approval context. The engine is framework
neutral and denies requests whenever policy context is missing or ambiguous.

```text
Identity provider / API gateway
          │
          ▼
     PolicyRequest ─────► versioned EnterprisePolicy
          │                         │
          ▼                         ▼
     PolicyDecision ─────► allow / deny + reasons + obligations
          │
          ├── deny: return a controlled error and emit decision evidence
          └── allow: execute the tool, retain correlation ID, fulfill obligations
                                      │
                                      ▼
                      redacted report → signed EvidenceEnvelope
```

## Control coverage

| Control | QueryAssure behaviour |
|---|---|
| Default effect | Only `deny` is accepted when loading an enterprise policy |
| Tenant isolation | Resource tenant is mandatory and must equal the authenticated tenant |
| RBAC | A recognized role must grant both the action and resource pattern |
| Data clearance | Role clearance must meet the ordered classification level |
| Side effects | Configured actions require a correctly formatted approval ticket |
| Break glass | Restricted to emergency roles with incident ticket and justification |
| Auditability | Decisions include policy version, fingerprint, reasons, roles, and obligations |
| Evidence integrity | Redacted canonical reports are hashed and signed with HMAC-SHA256 |

These controls supplement authentication and infrastructure authorization. QueryAssure
does not issue identities, OAuth tokens, database credentials, or cloud IAM grants.

## Run the zero-key control demonstration

```bash
queryassure enterprise-demo \
  --output reports/enterprise-evidence.json \
  --html reports/enterprise-governance.html
```

The demo verifies six decisions: same-tenant access, cross-tenant denial, restricted-data
denial, missing approval denial, approved side effect, and audited emergency access. Its
signing key is generated in memory and discarded after the bundle is verified.

## Evaluate a policy in CI or at an agent boundary

The bundled policy pack is suitable for evaluation and examples. Production teams should
copy it into their configuration repository, review it through pull requests, and load it
from an immutable release artifact.

```bash
queryassure policy evaluate \
  --tenant northstar \
  --resource-tenant northstar \
  --subject analyst@example.test \
  --role analyst \
  --action sql.read \
  --resource warehouse:analytics.orders \
  --classification confidential \
  --policy policies/enterprise-policy.yml
```

Exit code `0` means the request is allowed. A denial returns exit code `1` and a complete
decision object. Do not interpret an unavailable policy service as an allow decision.

## Policy pack structure

```yaml
version: "2026-08-17.1"
default_effect: deny
environments: [development, staging, production]
classifications: [public, internal, confidential, restricted]

roles:
  analyst:
    actions: [sql.read, catalog.read]
    resources: ["warehouse:*"]
    clearance: confidential

approval:
  required_for: [agent.notification.send]
  ticket_pattern: "^APR-[0-9]{4,}$"

break_glass:
  roles: [security-admin]
  ticket_pattern: "^INC-[0-9]{4,}$"
```

Action and resource patterns use case-sensitive shell-style matching. Keep patterns narrow;
the policy engine deliberately does not infer permissions from similar names.

## Sign and verify audit evidence

Signing material is read from an environment variable, not a command-line argument. In a
production pipeline, populate that variable from a KMS, HSM, or CI secret manager and use a
key identifier that allows rotation and incident investigation.

```bash
export QUERYASSURE_EVIDENCE_KEY="$(security find-generic-password -w -s qa-evidence)"

queryassure evidence sign reports/latest.json \
  --output reports/latest.evidence.json \
  --key-id kms/queryassure/prod-2026-08

queryassure evidence verify reports/latest.evidence.json \
  --max-age-seconds 86400
```

Before signing, QueryAssure removes result rows, email addresses, and common credential
fields or credential-shaped values. The evidence file is written atomically with owner-only
permissions. Verification checks the canonical
payload digest, constant-time HMAC signature comparison, supported envelope version,
timezone-aware issue date, future clock skew, and optional maximum age.

HMAC proves that a holder of the shared secret created the bundle; it does not provide
public-key non-repudiation. Organizations requiring independent verification should replace
the signer with KMS-backed asymmetric signatures while preserving the envelope contract.

## Production integration checklist

1. Authenticate the subject and tenant before constructing `PolicyRequest`.
2. Derive roles from trusted identity claims, never from model output or user prompts.
3. Bind the resource tenant from server-side metadata.
4. Store policy packs in version control and deploy immutable versions.
5. Execute no tool call until the policy decision is allowed.
6. Fulfill every returned obligation and preserve the decision ID in telemetry.
7. Sign only redacted reports and rotate signing keys through a managed key service.
8. Alert on cross-tenant denials, break-glass decisions, and verification failures.

For OAuth and human-approval controls, see
[enterprise-agent-security.md](enterprise-agent-security.md). For cross-service traces and
failure replay, use the independent
[SpanReplay reference stack](https://github.com/Victoria824/SpanReplay).
