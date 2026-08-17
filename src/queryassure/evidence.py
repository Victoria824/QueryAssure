from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .reporting import redact_report


class EvidenceVerificationError(ValueError):
    """Raised when an evidence bundle is malformed, stale, or tampered with."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode()


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    version: int
    algorithm: str
    key_id: str
    issued_at: str
    payload_sha256: str
    payload: dict[str, Any]
    signature: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> EvidenceEnvelope:
        required = {
            "version",
            "algorithm",
            "key_id",
            "issued_at",
            "payload_sha256",
            "payload",
            "signature",
        }
        missing = sorted(required.difference(value))
        if missing:
            raise EvidenceVerificationError(
                f"Evidence envelope is missing: {', '.join(missing)}"
            )
        if not isinstance(value["payload"], dict):
            raise EvidenceVerificationError("Evidence payload must be an object")
        try:
            return cls(
                version=int(value["version"]),
                algorithm=str(value["algorithm"]),
                key_id=str(value["key_id"]),
                issued_at=str(value["issued_at"]),
                payload_sha256=str(value["payload_sha256"]),
                payload=value["payload"],
                signature=str(value["signature"]),
            )
        except (TypeError, ValueError) as exc:
            raise EvidenceVerificationError("Evidence envelope contains invalid types") from exc


def _signature_material(envelope: EvidenceEnvelope) -> bytes:
    return _canonical_json(
        {
            "version": envelope.version,
            "algorithm": envelope.algorithm,
            "key_id": envelope.key_id,
            "issued_at": envelope.issued_at,
            "payload_sha256": envelope.payload_sha256,
        }
    )


def sign_evidence(
    report: dict[str, Any],
    secret: bytes,
    *,
    key_id: str,
    issued_at: datetime | None = None,
) -> EvidenceEnvelope:
    """Redact and sign an evaluation report with an operator-managed HMAC key."""
    if len(secret) < 32:
        raise ValueError("Evidence signing keys must contain at least 32 bytes")
    if not key_id.strip():
        raise ValueError("A non-empty key_id is required")
    timestamp = (issued_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = redact_report(report)
    payload_sha256 = hashlib.sha256(_canonical_json(payload)).hexdigest()
    unsigned = EvidenceEnvelope(
        version=1,
        algorithm="HMAC-SHA256",
        key_id=key_id,
        issued_at=timestamp.isoformat(),
        payload_sha256=payload_sha256,
        payload=payload,
        signature="",
    )
    signature = hmac.new(secret, _signature_material(unsigned), hashlib.sha256).hexdigest()
    return EvidenceEnvelope(**{**unsigned.to_dict(), "signature": signature})


def verify_evidence(
    envelope: EvidenceEnvelope | dict[str, Any],
    secret: bytes,
    *,
    max_age_seconds: float | None = None,
    now: datetime | None = None,
) -> bool:
    """Verify the payload digest, signature, and optional evidence age."""
    if max_age_seconds is not None and max_age_seconds < 0:
        raise EvidenceVerificationError("Evidence maximum age cannot be negative")
    value = (
        envelope
        if isinstance(envelope, EvidenceEnvelope)
        else EvidenceEnvelope.from_dict(envelope)
    )
    if value.version != 1 or value.algorithm != "HMAC-SHA256":
        raise EvidenceVerificationError("Unsupported evidence format or algorithm")
    actual_digest = hashlib.sha256(_canonical_json(value.payload)).hexdigest()
    if not hmac.compare_digest(actual_digest, value.payload_sha256):
        raise EvidenceVerificationError("Evidence payload digest does not match")
    expected = hmac.new(secret, _signature_material(value), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, value.signature):
        raise EvidenceVerificationError("Evidence signature does not match")
    try:
        issued_at = datetime.fromisoformat(value.issued_at)
    except ValueError as exc:
        raise EvidenceVerificationError("Evidence issued_at is invalid") from exc
    if issued_at.tzinfo is None:
        raise EvidenceVerificationError("Evidence issued_at must include a timezone")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (current - issued_at.astimezone(timezone.utc)).total_seconds()
    if age < -300:
        raise EvidenceVerificationError("Evidence timestamp is in the future")
    if max_age_seconds is not None and age > max_age_seconds:
        raise EvidenceVerificationError("Evidence bundle has expired")
    return True


def write_evidence_bundle(envelope: EvidenceEnvelope, path: str | Path) -> Path:
    """Atomically persist an owner-readable evidence bundle."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(envelope.to_dict(), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, target)
        target.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def read_evidence_bundle(path: str | Path) -> EvidenceEnvelope:
    try:
        payload = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceVerificationError("Evidence bundle cannot be read as JSON") from exc
    if not isinstance(payload, dict):
        raise EvidenceVerificationError("Evidence envelope must be an object")
    return EvidenceEnvelope.from_dict(payload)
