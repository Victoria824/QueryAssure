# Enterprise agent security reference

QueryAssure's Microsoft 365 example models the controls needed when an agent reads,
drafts, notifies, or acts inside an employee's existing workflow. The default simulator
is deterministic and never contacts Microsoft. The live client is disabled unless
`QUERYASSURE_GRAPH_LIVE_ENABLED=true` is set explicitly.

## Trust boundaries

```text
Department request
  → agent routing
  → delegated OAuth scope check
  → Microsoft Graph adapter
  → reversible draft or read
  → human approval for outbound side effect
  → Outlook / Teams action
  → redacted audit evidence
```

The model never receives an OAuth access token. A token provider supplies credentials to
the Graph transport only when a request is sent. Tokens, authorization headers, message
bodies, and raw result rows are excluded from the evaluation report.

## Reference permission model

| Action | Graph scope | Default policy |
|---|---|---|
| Read unread Outlook messages | `Mail.Read` | allowed |
| Create a reply draft | `Mail.ReadWrite` | allowed, retained as draft |
| Send an Outlook draft | `Mail.Send` | explicit human approval required |
| Post to a Teams channel | `ChannelMessage.Send` | explicit human approval required |

Evaluation cases declare both required and allowed scopes. A run fails when the grant
contains scopes outside the contract, providing an automated least-privilege check.

## Evidence generated for review

Every workflow emits a monotonically ordered event sequence containing:

- decision or tool name
- success, blocked, or waiting status
- required Graph scopes
- whether the action creates an external side effect
- whether approval was required and supplied
- non-secret approval ticket and reviewer identity

QueryAssure then checks required and forbidden tools, OAuth scopes, unapproved side
effects, approval evidence, audit completeness, tool-call budgets, latency, and credential
hygiene. The resulting JSON and self-contained HTML reports can be retained as deployment
evidence for an organization's security review.

## Live Graph integration

The reference `HttpMicrosoftGraphClient` uses a fixed
`https://graph.microsoft.com/v1.0` base URL, a short request timeout, delegated scope
checks before each call, and a callback-based token provider. Production deployments
should obtain tokens through a managed identity or a confidential credential store,
enforce tenant restrictions, and place the API behind authenticated service boundaries.

QueryAssure demonstrates control patterns; it does not replace Microsoft Entra Conditional
Access, Microsoft Purview, tenant-level DLP, or an organization's formal SOC 2 / ISO 27001
control assessment.
