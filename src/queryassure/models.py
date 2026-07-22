from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentTrace:
    question: str
    sql: str
    answer: str = ""
    retrieved_context: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    estimated_cost_usd: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    message: str
    severity: str = "error"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaseResult:
    case_id: str
    question: str
    passed: bool
    checks: list[CheckResult]
    trace: AgentTrace

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
            "trace": self.trace.to_dict(),
        }
