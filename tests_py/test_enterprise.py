import json
import stat
from datetime import datetime, timedelta, timezone

import pytest
from typer.testing import CliRunner

from queryassure.cli import app as cli_app
from queryassure.enterprise import run_enterprise_demo
from queryassure.evidence import (
    EvidenceVerificationError,
    read_evidence_bundle,
    sign_evidence,
    verify_evidence,
    write_evidence_bundle,
)
from queryassure.governance import (
    EnterprisePolicy,
    PolicyConfigurationError,
    PolicyEngine,
    PolicyRequest,
)


@pytest.fixture()
def policy() -> EnterprisePolicy:
    return EnterprisePolicy.from_yaml("src/queryassure/resources/enterprise-policy.yml")


def _request(**overrides) -> PolicyRequest:
    values = {
        "tenant_id": "northstar",
        "resource_tenant_id": "northstar",
        "subject": "analyst@example.test",
        "roles": frozenset({"analyst"}),
        "action": "sql.read",
        "resource": "warehouse:analytics.orders",
        "classification": "confidential",
    }
    values.update(overrides)
    return PolicyRequest(**values)


def test_policy_allows_grounded_same_tenant_read(policy):
    decision = PolicyEngine(policy).evaluate(_request())
    assert decision.allowed
    assert decision.matched_roles == ("analyst",)
    assert decision.policy_version == "2026-08-17.1"
    assert "emit_policy_decision" in decision.obligations
    assert len(decision.request_fingerprint) == 24


def test_policy_blocks_cross_tenant_and_excessive_classification(policy):
    missing_binding = PolicyEngine(policy).evaluate(_request(resource_tenant_id=None))
    assert not missing_binding.allowed
    assert "resource tenant" in missing_binding.reasons[0]

    cross_tenant = PolicyEngine(policy).evaluate(
        _request(resource_tenant_id="contoso")
    )
    assert not cross_tenant.allowed
    assert "Cross-tenant" in cross_tenant.reasons[0]

    restricted = PolicyEngine(policy).evaluate(_request(classification="restricted"))
    assert not restricted.allowed
    assert "exceeds role clearance" in restricted.reasons[0]


def test_policy_requires_verifiable_approval_for_side_effects(policy):
    engine = PolicyEngine(policy)
    request = _request(
        subject="operator@example.test",
        roles=frozenset({"operator"}),
        action="agent.notification.send",
        resource="m365:teams.facilities",
        classification="internal",
    )
    denied = engine.evaluate(request)
    assert not denied.allowed
    assert "approval ticket" in denied.reasons[0]

    approved = engine.evaluate(
        _request(
            subject="operator@example.test",
            roles=frozenset({"operator"}),
            action="agent.notification.send",
            resource="m365:teams.facilities",
            classification="internal",
            approval_ticket="APR-0042",
        )
    )
    assert approved.allowed
    assert "attach_approval_evidence" in approved.obligations


def test_break_glass_is_restricted_and_auditable(policy):
    engine = PolicyEngine(policy)
    denied = engine.evaluate(
        _request(
            roles=frozenset({"security-admin"}),
            classification="restricted",
            break_glass=True,
        )
    )
    assert not denied.allowed

    allowed = engine.evaluate(
        _request(
            subject="security@example.test",
            roles=frozenset({"security-admin"}),
            classification="restricted",
            break_glass=True,
            approval_ticket="INC-0199",
            justification="Investigate active tenant-isolation alert",
        )
    )
    assert allowed.allowed
    assert set(allowed.obligations) >= {
        "page_security_on_call",
        "expire_break_glass_session",
        "post_incident_review",
    }


def test_policy_configuration_fails_closed(tmp_path):
    unsafe = tmp_path / "policy.yml"
    unsafe.write_text(
        """
version: one
default_effect: allow
environments: [production]
classifications: [internal]
roles:
  admin:
    actions: ['*']
    resources: ['*']
    clearance: internal
"""
    )
    with pytest.raises(PolicyConfigurationError, match="deny default"):
        EnterprisePolicy.from_yaml(unsafe)

    malformed = tmp_path / "malformed.yml"
    malformed.write_text("- not\n- a\n- mapping\n")
    with pytest.raises(PolicyConfigurationError, match="root must be a mapping"):
        EnterprisePolicy.from_yaml(malformed)


def test_signed_evidence_is_redacted_atomic_and_verifiable(tmp_path):
    key = b"operator-managed-test-key-32-bytes-minimum"
    report = {
        "suite": "private",
        "summary": {"total": 1, "passed": 1, "failed": 0, "pass_rate": 1.0},
        "results": [
            {
                "trace": {
                    "rows": [{"email": "private@example.test"}],
                    "actor": "private@example.test",
                    "authorization": "Bearer private-token",
                    "note": "upstream returned Bearer abcdefghijklmnop",
                }
            }
        ],
    }
    envelope = sign_evidence(report, key, key_id="kms/queryassure/test")
    assert verify_evidence(envelope, key)
    encoded = json.dumps(envelope.to_dict())
    assert "private@example.test" not in encoded
    assert "private-token" not in encoded
    assert "abcdefghijklmnop" not in encoded

    output = write_evidence_bundle(envelope, tmp_path / "evidence.json")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert verify_evidence(read_evidence_bundle(output), key)


def test_evidence_verification_detects_tampering_wrong_key_and_expiry():
    key = b"operator-managed-test-key-32-bytes-minimum"
    issued_at = datetime(2026, 8, 17, tzinfo=timezone.utc)
    envelope = sign_evidence(
        {"summary": {"failed": 0}},
        key,
        key_id="kms/queryassure/prod",
        issued_at=issued_at,
    )
    tampered = envelope.to_dict()
    tampered["payload"]["summary"]["failed"] = 1
    with pytest.raises(EvidenceVerificationError, match="digest"):
        verify_evidence(tampered, key)
    with pytest.raises(EvidenceVerificationError, match="signature"):
        verify_evidence(envelope, b"different-operator-managed-key-32-bytes")
    with pytest.raises(EvidenceVerificationError, match="expired"):
        verify_evidence(
            envelope,
            key,
            max_age_seconds=60,
            now=issued_at + timedelta(minutes=2),
        )


def test_evidence_reader_fails_closed_on_malformed_inputs(tmp_path):
    invalid_json = tmp_path / "invalid.json"
    invalid_json.write_text("not-json")
    with pytest.raises(EvidenceVerificationError, match="cannot be read"):
        read_evidence_bundle(invalid_json)

    wrong_shape = tmp_path / "array.json"
    wrong_shape.write_text("[]")
    with pytest.raises(EvidenceVerificationError, match="must be an object"):
        read_evidence_bundle(wrong_shape)

    with pytest.raises(EvidenceVerificationError, match="cannot be negative"):
        verify_evidence({}, b"operator-managed-test-key-32-bytes-minimum", max_age_seconds=-1)


def test_enterprise_demo_produces_six_verified_controls(tmp_path):
    report, evidence_path, verified = run_enterprise_demo(
        tmp_path / "enterprise-evidence.json",
        secret=b"operator-managed-test-key-32-bytes-minimum",
    )
    assert verified
    assert report["summary"] == {
        "total": 6,
        "passed": 6,
        "failed": 0,
        "pass_rate": 1.0,
    }
    assert evidence_path.exists()
    assert report["governance"]["default_effect"] == "deny"


def test_enterprise_cli_and_policy_cli(tmp_path):
    runner = CliRunner()
    demo = runner.invoke(
        cli_app,
        [
            "enterprise-demo",
            "--output",
            str(tmp_path / "enterprise.json"),
            "--html",
            str(tmp_path / "enterprise.html"),
        ],
    )
    assert demo.exit_code == 0
    assert "6/6 passed" in demo.stdout
    assert "Verified" in demo.stdout

    allowed = runner.invoke(
        cli_app,
        [
            "policy",
            "evaluate",
            "--tenant",
            "northstar",
            "--resource-tenant",
            "northstar",
            "--subject",
            "analyst@example.test",
            "--role",
            "analyst",
            "--action",
            "sql.read",
            "--resource",
            "warehouse:analytics.orders",
            "--classification",
            "confidential",
        ],
    )
    assert allowed.exit_code == 0
    assert '"allowed": true' in allowed.stdout


def test_evidence_cli_reads_key_from_environment(tmp_path, monkeypatch):
    key = "operator-managed-test-key-32-bytes-minimum"
    monkeypatch.setenv("QUERYASSURE_EVIDENCE_KEY", key)
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps({"summary": {"failed": 0}}))
    evidence_path = tmp_path / "evidence.json"
    runner = CliRunner()
    signed = runner.invoke(
        cli_app,
        [
            "evidence",
            "sign",
            str(report_path),
            "--output",
            str(evidence_path),
            "--key-id",
            "kms/queryassure/prod",
        ],
    )
    assert signed.exit_code == 0
    verified = runner.invoke(cli_app, ["evidence", "verify", str(evidence_path)])
    assert verified.exit_code == 0
    assert "VERIFIED" in verified.stdout
