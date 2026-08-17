from __future__ import annotations

import secrets
from importlib import resources
from pathlib import Path
from typing import Any

from .evidence import sign_evidence, verify_evidence, write_evidence_bundle
from .governance import EnterprisePolicy, PolicyEngine, PolicyRequest
from .models import CheckResult


def _demo_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "analyst_reads_own_tenant",
            "expect_allowed": True,
            "request": PolicyRequest(
                tenant_id="northstar",
                resource_tenant_id="northstar",
                subject="analyst@example.test",
                roles=frozenset({"analyst"}),
                action="sql.read",
                resource="warehouse:analytics.orders",
                classification="confidential",
            ),
        },
        {
            "id": "cross_tenant_access_blocked",
            "expect_allowed": False,
            "request": PolicyRequest(
                tenant_id="northstar",
                resource_tenant_id="contoso",
                subject="analyst@example.test",
                roles=frozenset({"analyst"}),
                action="sql.read",
                resource="warehouse:analytics.orders",
                classification="internal",
            ),
        },
        {
            "id": "restricted_data_blocked",
            "expect_allowed": False,
            "request": PolicyRequest(
                tenant_id="northstar",
                resource_tenant_id="northstar",
                subject="analyst@example.test",
                roles=frozenset({"analyst"}),
                action="sql.read",
                resource="warehouse:security.audit",
                classification="restricted",
            ),
        },
        {
            "id": "side_effect_requires_approval",
            "expect_allowed": False,
            "request": PolicyRequest(
                tenant_id="northstar",
                resource_tenant_id="northstar",
                subject="operator@example.test",
                roles=frozenset({"operator"}),
                action="agent.notification.send",
                resource="m365:teams.facilities",
                classification="internal",
            ),
        },
        {
            "id": "approved_side_effect_allowed",
            "expect_allowed": True,
            "required_obligation": "attach_approval_evidence",
            "request": PolicyRequest(
                tenant_id="northstar",
                resource_tenant_id="northstar",
                subject="operator@example.test",
                roles=frozenset({"operator"}),
                action="agent.notification.send",
                resource="m365:teams.facilities",
                classification="internal",
                approval_ticket="APR-0042",
            ),
        },
        {
            "id": "audited_break_glass_allowed",
            "expect_allowed": True,
            "required_obligation": "post_incident_review",
            "request": PolicyRequest(
                tenant_id="northstar",
                resource_tenant_id="northstar",
                subject="security@example.test",
                roles=frozenset({"security-admin"}),
                action="sql.read",
                resource="warehouse:security.audit",
                classification="restricted",
                approval_ticket="INC-0199",
                break_glass=True,
                justification="Investigate active cross-tenant access alert",
            ),
        },
    ]


def run_enterprise_demo(
    output: str | Path,
    *,
    secret: bytes | None = None,
) -> tuple[dict[str, Any], Path, bool]:
    """Exercise enterprise authorization controls and create signed evidence."""
    bundled = resources.files("queryassure").joinpath("resources/enterprise-policy.yml")
    with resources.as_file(bundled) as policy_path:
        policy = EnterprisePolicy.from_yaml(policy_path)
    engine = PolicyEngine(policy)
    results: list[dict[str, Any]] = []
    for case in _demo_cases():
        request: PolicyRequest = case["request"]
        decision = engine.evaluate(request)
        checks = [
            CheckResult(
                "expected_policy_decision",
                decision.allowed is case["expect_allowed"],
                f"Decision allowed={decision.allowed}; expected {case['expect_allowed']}",
            )
        ]
        required_obligation = case.get("required_obligation")
        if required_obligation:
            checks.append(
                CheckResult(
                    "required_policy_obligation",
                    required_obligation in decision.obligations,
                    f"Required obligation {required_obligation!r} is present",
                )
            )
        passed = all(check.passed for check in checks)
        results.append(
            {
                "case_id": case["id"],
                "question": (
                    f"{request.subject} requests {request.action} on {request.resource}"
                ),
                "passed": passed,
                "checks": [check.to_dict() for check in checks],
                "trace": {
                    "latency_ms": 0.0,
                    "events": [
                        {
                            "sequence": 1,
                            "kind": "policy",
                            "name": "enterprise_policy.evaluate",
                            "status": "allowed" if decision.allowed else "denied",
                            "summary": "; ".join(decision.reasons),
                            "metadata": decision.to_dict(),
                        }
                    ],
                },
            }
        )
    passed_count = sum(result["passed"] for result in results)
    report = {
        "suite": "enterprise-governance",
        "summary": {
            "total": len(results),
            "passed": passed_count,
            "failed": len(results) - passed_count,
            "pass_rate": passed_count / len(results),
        },
        "governance": {
            "policy_version": policy.version,
            "default_effect": policy.default_effect,
            "controls": [
                "tenant_isolation",
                "rbac_resource_authorization",
                "classification_clearance",
                "approval_obligations",
                "break_glass_governance",
            ],
        },
        "results": results,
    }
    signing_key = secret or secrets.token_bytes(32)
    envelope = sign_evidence(report, signing_key, key_id="enterprise-demo-ephemeral")
    target = write_evidence_bundle(envelope, output)
    return report, target, verify_evidence(envelope, signing_key)
