from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class PolicyConfigurationError(ValueError):
    """Raised when a policy pack is incomplete or unsafe."""


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    """Framework-neutral authorization input for an agent action."""

    tenant_id: str
    subject: str
    roles: frozenset[str]
    action: str
    resource: str
    resource_tenant_id: str | None = None
    environment: str = "production"
    classification: str = "internal"
    approval_ticket: str | None = None
    break_glass: bool = False
    justification: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        payload = asdict(self)
        payload.pop("approval_ticket", None)
        payload.pop("justification", None)
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()[:24]


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Auditable result returned by the fail-closed policy engine."""

    decision_id: str
    allowed: bool
    policy_version: str
    request_fingerprint: str
    reasons: tuple[str, ...]
    matched_roles: tuple[str, ...] = ()
    obligations: tuple[str, ...] = ()
    evaluated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class RolePolicy:
    actions: tuple[str, ...]
    resources: tuple[str, ...]
    clearance: str


@dataclass(frozen=True, slots=True)
class EnterprisePolicy:
    version: str
    environments: tuple[str, ...]
    classifications: tuple[str, ...]
    roles: dict[str, RolePolicy]
    approval_actions: tuple[str, ...]
    approval_ticket_pattern: str
    break_glass_roles: tuple[str, ...]
    break_glass_ticket_pattern: str
    default_effect: str = "deny"

    @classmethod
    def from_yaml(cls, path: str | Path) -> EnterprisePolicy:
        payload = yaml.safe_load(Path(path).read_text()) or {}
        if not isinstance(payload, dict):
            raise PolicyConfigurationError("Policy root must be a mapping")
        version = str(payload.get("version", "")).strip()
        default_effect = str(payload.get("default_effect", "deny")).lower()
        environments = tuple(str(item) for item in payload.get("environments", []))
        classifications = tuple(str(item) for item in payload.get("classifications", []))
        raw_roles = payload.get("roles", {})
        if not version:
            raise PolicyConfigurationError("Policy version is required")
        if default_effect != "deny":
            raise PolicyConfigurationError("Enterprise policies must use a deny default")
        if not environments:
            raise PolicyConfigurationError("At least one environment is required")
        if not classifications:
            raise PolicyConfigurationError("A classification hierarchy is required")
        if len(set(classifications)) != len(classifications):
            raise PolicyConfigurationError("Data classifications must be unique")
        if not isinstance(raw_roles, dict) or not raw_roles:
            raise PolicyConfigurationError("At least one role policy is required")

        roles: dict[str, RolePolicy] = {}
        for name, value in raw_roles.items():
            value = value or {}
            if not isinstance(value, dict):
                raise PolicyConfigurationError(f"Role {name!r} must be a mapping")
            clearance = str(value.get("clearance", ""))
            if clearance not in classifications:
                raise PolicyConfigurationError(
                    f"Role {name!r} has unknown clearance {clearance!r}"
                )
            actions = tuple(str(item) for item in value.get("actions", []))
            resources = tuple(str(item) for item in value.get("resources", []))
            if not actions or not resources:
                raise PolicyConfigurationError(
                    f"Role {name!r} must define actions and resources"
                )
            roles[str(name)] = RolePolicy(actions, resources, clearance)

        approval = payload.get("approval", {}) or {}
        break_glass = payload.get("break_glass", {}) or {}
        approval_pattern = str(approval.get("ticket_pattern", r"^APR-[0-9]+$"))
        break_glass_pattern = str(break_glass.get("ticket_pattern", r"^INC-[0-9]+$"))
        try:
            re.compile(approval_pattern)
            re.compile(break_glass_pattern)
        except re.error as exc:
            raise PolicyConfigurationError(f"Invalid ticket pattern: {exc}") from exc

        return cls(
            version=version,
            default_effect=default_effect,
            environments=environments,
            classifications=classifications,
            roles=roles,
            approval_actions=tuple(str(item) for item in approval.get("required_for", [])),
            approval_ticket_pattern=approval_pattern,
            break_glass_roles=tuple(str(item) for item in break_glass.get("roles", [])),
            break_glass_ticket_pattern=break_glass_pattern,
        )


class PolicyEngine:
    """Evaluate tenant, role, classification, and approval controls as code."""

    def __init__(self, policy: EnterprisePolicy) -> None:
        self.policy = policy

    @staticmethod
    def _matches(value: str, patterns: tuple[str, ...]) -> bool:
        return any(fnmatch.fnmatchcase(value, pattern) for pattern in patterns)

    def _decision(
        self,
        request: PolicyRequest,
        *,
        allowed: bool,
        reasons: list[str],
        matched_roles: list[str] | None = None,
        obligations: list[str] | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            decision_id=f"pdp_{uuid.uuid4().hex}",
            allowed=allowed,
            policy_version=self.policy.version,
            request_fingerprint=request.fingerprint(),
            reasons=tuple(reasons),
            matched_roles=tuple(sorted(matched_roles or [])),
            obligations=tuple(obligations or []),
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )

    def evaluate(self, request: PolicyRequest) -> PolicyDecision:
        reasons: list[str] = []
        obligations: list[str] = ["emit_policy_decision", "preserve_correlation_id"]

        if not request.tenant_id or not request.subject:
            return self._decision(
                request,
                allowed=False,
                reasons=["A tenant and authenticated subject are required"],
                obligations=obligations,
            )
        if not request.action or not request.resource:
            return self._decision(
                request,
                allowed=False,
                reasons=["A non-empty action and resource are required"],
                obligations=obligations,
            )
        if not request.resource_tenant_id:
            return self._decision(
                request,
                allowed=False,
                reasons=["A server-bound resource tenant is required"],
                obligations=obligations,
            )
        if request.resource_tenant_id != request.tenant_id:
            return self._decision(
                request,
                allowed=False,
                reasons=["Cross-tenant resource access is prohibited"],
                obligations=obligations,
            )
        if request.environment not in self.policy.environments:
            return self._decision(
                request,
                allowed=False,
                reasons=[f"Environment {request.environment!r} is not governed"],
                obligations=obligations,
            )

        known_roles = sorted(request.roles.intersection(self.policy.roles))
        if not known_roles:
            return self._decision(
                request,
                allowed=False,
                reasons=["No recognized role was provided"],
                obligations=obligations,
            )

        if request.break_glass:
            emergency_roles = sorted(
                request.roles.intersection(self.policy.break_glass_roles)
            )
            ticket_valid = bool(
                request.approval_ticket
                and re.fullmatch(
                    self.policy.break_glass_ticket_pattern,
                    request.approval_ticket,
                )
            )
            if (
                not emergency_roles
                or not request.justification
                or not request.justification.strip()
                or not ticket_valid
            ):
                return self._decision(
                    request,
                    allowed=False,
                    reasons=[
                        "Break-glass access requires an authorized role, incident ticket, "
                        "and justification"
                    ],
                    matched_roles=emergency_roles,
                    obligations=obligations,
                )
            obligations.extend(
                ["page_security_on_call", "expire_break_glass_session", "post_incident_review"]
            )
            return self._decision(
                request,
                allowed=True,
                reasons=["Authorized break-glass exception"],
                matched_roles=emergency_roles,
                obligations=obligations,
            )

        matched_roles = [
            role
            for role in known_roles
            if self._matches(request.action, self.policy.roles[role].actions)
            and self._matches(request.resource, self.policy.roles[role].resources)
        ]
        if not matched_roles:
            return self._decision(
                request,
                allowed=False,
                reasons=["No role grants this action on the requested resource"],
                obligations=obligations,
            )

        if request.classification not in self.policy.classifications:
            return self._decision(
                request,
                allowed=False,
                reasons=[f"Unknown data classification {request.classification!r}"],
                matched_roles=matched_roles,
                obligations=obligations,
            )
        required_clearance = self.policy.classifications.index(request.classification)
        highest_clearance = max(
            self.policy.classifications.index(self.policy.roles[role].clearance)
            for role in matched_roles
        )
        if required_clearance > highest_clearance:
            return self._decision(
                request,
                allowed=False,
                reasons=[
                    f"Classification {request.classification!r} exceeds role clearance"
                ],
                matched_roles=matched_roles,
                obligations=obligations,
            )

        if self._matches(request.action, self.policy.approval_actions):
            ticket_valid = bool(
                request.approval_ticket
                and re.fullmatch(
                    self.policy.approval_ticket_pattern,
                    request.approval_ticket,
                )
            )
            if not ticket_valid:
                return self._decision(
                    request,
                    allowed=False,
                    reasons=["A valid approval ticket is required for this action"],
                    matched_roles=matched_roles,
                    obligations=obligations,
                )
            obligations.append("attach_approval_evidence")

        reasons.append("Tenant, role, resource, classification, and approval checks passed")
        return self._decision(
            request,
            allowed=True,
            reasons=reasons,
            matched_roles=matched_roles,
            obligations=obligations,
        )
