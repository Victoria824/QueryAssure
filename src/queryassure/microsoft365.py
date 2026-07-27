from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .workflows import WorkflowEvent, WorkflowTrace

MAIL_READ = "Mail.Read"
MAIL_WRITE = "Mail.ReadWrite"
MAIL_SEND = "Mail.Send"
TEAMS_SEND = "ChannelMessage.Send"


class PermissionDenied(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OAuthGrant:
    """Non-secret evidence describing a delegated Microsoft Graph grant."""

    tenant_id: str
    subject: str
    scopes: frozenset[str]
    credential_reference: str = "managed-identity://queryassure-demo"

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise PermissionDenied(f"OAuth grant is missing required scope {scope}")


@dataclass(frozen=True, slots=True)
class Approval:
    action: str
    approved: bool
    approved_by: str
    ticket: str


class GraphClientLike(Protocol):
    def list_unread_messages(self) -> list[dict[str, Any]]: ...

    def create_reply_draft(self, message_id: str, body: str) -> dict[str, Any]: ...

    def send_draft(self, draft_id: str) -> dict[str, Any]: ...

    def post_teams_message(self, team_id: str, channel_id: str, body: str) -> dict[str, Any]: ...


@dataclass(slots=True)
class MockMicrosoftGraphClient:
    """Deterministic Microsoft Graph simulator for safe tests and demos."""

    messages: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "id": "msg-001",
                "subject": "Water leak on floor 4",
                "sender": "operations@example.test",
                "priority": "high",
                "unread": True,
            },
            {
                "id": "msg-002",
                "subject": "Monthly inspection complete",
                "sender": "safety@example.test",
                "priority": "normal",
                "unread": True,
            },
        ]
    )
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    sent_drafts: list[str] = field(default_factory=list)
    teams_posts: list[dict[str, str]] = field(default_factory=list)

    def list_unread_messages(self) -> list[dict[str, Any]]:
        return [dict(message) for message in self.messages if message["unread"]]

    def create_reply_draft(self, message_id: str, body: str) -> dict[str, Any]:
        draft_id = f"draft-{len(self.drafts) + 1:03d}"
        draft = {"id": draft_id, "in_reply_to": message_id, "body": body, "status": "draft"}
        self.drafts[draft_id] = draft
        return dict(draft)

    def send_draft(self, draft_id: str) -> dict[str, Any]:
        if draft_id not in self.drafts:
            raise KeyError(f"Unknown draft {draft_id}")
        self.sent_drafts.append(draft_id)
        return {"id": draft_id, "status": "sent"}

    def post_teams_message(
        self,
        team_id: str,
        channel_id: str,
        body: str,
    ) -> dict[str, Any]:
        post = {
            "id": f"teams-{len(self.teams_posts) + 1:03d}",
            "team_id": team_id,
            "channel_id": channel_id,
            "body": body,
        }
        self.teams_posts.append(post)
        return dict(post)


class HttpMicrosoftGraphClient:
    """Fail-closed Microsoft Graph client for explicitly enabled live integrations."""

    def __init__(
        self,
        grant: OAuthGrant,
        token_provider: Callable[[], str],
        *,
        client: httpx.Client | None = None,
        enabled: bool | None = None,
    ) -> None:
        live_enabled = (
            os.getenv("QUERYASSURE_GRAPH_LIVE_ENABLED", "").lower() in {"1", "true", "yes"}
            if enabled is None
            else enabled
        )
        if not live_enabled:
            raise RuntimeError("Live Microsoft Graph access is disabled")
        self.grant = grant
        self.token_provider = token_provider
        self.client = client or httpx.Client(
            base_url="https://graph.microsoft.com/v1.0",
            timeout=10.0,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        scope: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.grant.require(scope)
        token = self.token_provider()
        if not token:
            raise RuntimeError("Microsoft Graph token provider returned no credential")
        response = self.client.request(
            method,
            path,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        response.raise_for_status()
        return response.json() if response.content else {}

    def list_unread_messages(self) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/me/messages?$filter=isRead%20eq%20false&$select=id,subject,from,importance",
            scope=MAIL_READ,
        )
        return list(payload.get("value", []))

    def create_reply_draft(self, message_id: str, body: str) -> dict[str, Any]:
        encoded_message_id = quote(message_id, safe="")
        return self._request(
            "POST",
            f"/me/messages/{encoded_message_id}/createReply",
            scope=MAIL_WRITE,
            payload={"message": {"body": {"contentType": "text", "content": body}}},
        )

    def send_draft(self, draft_id: str) -> dict[str, Any]:
        encoded_draft_id = quote(draft_id, safe="")
        return self._request("POST", f"/me/messages/{encoded_draft_id}/send", scope=MAIL_SEND)

    def post_teams_message(
        self,
        team_id: str,
        channel_id: str,
        body: str,
    ) -> dict[str, Any]:
        encoded_team_id = quote(team_id, safe="")
        encoded_channel_id = quote(channel_id, safe="")
        return self._request(
            "POST",
            f"/teams/{encoded_team_id}/channels/{encoded_channel_id}/messages",
            scope=TEAMS_SEND,
            payload={"body": {"contentType": "text", "content": body}},
        )


class Microsoft365Agent:
    """Reference Outlook/Teams agent with least privilege and approval gates."""

    def __init__(self, client: GraphClientLike, grant: OAuthGrant) -> None:
        self.client = client
        self.grant = grant

    def run(self, request: str, context: dict[str, Any] | None = None) -> WorkflowTrace:
        started = time.perf_counter()
        context = context or {}
        approvals = {
            item["action"]: Approval(**item)
            for item in context.get("approvals", [])
        }
        events: list[WorkflowEvent] = []

        def record(
            kind: str,
            name: str,
            status: str,
            summary: str,
            **kwargs: Any,
        ) -> None:
            events.append(
                WorkflowEvent(
                    sequence=len(events) + 1,
                    kind=kind,
                    name=name,
                    status=status,
                    summary=summary,
                    **kwargs,
                )
            )

        normalized = request.lower()
        try:
            self.grant.require(MAIL_READ)
            messages = self.client.list_unread_messages()
            record(
                "tool",
                "graph.outlook.list_unread",
                "ok",
                f"Retrieved {len(messages)} unread messages",
                required_scopes=[MAIL_READ],
                metadata={"message_ids": [message["id"] for message in messages]},
            )
            high_priority = [
                message
                for message in messages
                if message.get("priority", message.get("importance")) == "high"
            ]
            record(
                "decision",
                "mail.triage",
                "ok",
                f"Classified {len(high_priority)} high-priority facilities messages",
                metadata={"high_priority_ids": [message["id"] for message in high_priority]},
            )

            if "draft" in normalized or "reply" in normalized or "send" in normalized:
                self.grant.require(MAIL_WRITE)
                if not messages:
                    raise RuntimeError("No unread messages are available for a reply draft")
                source = high_priority[0] if high_priority else messages[0]
                draft = self.client.create_reply_draft(
                    source["id"],
                    "Facilities Operations has received the incident and initiated triage.",
                )
                record(
                    "tool",
                    "graph.outlook.create_reply_draft",
                    "ok",
                    f"Created draft {draft['id']} without sending",
                    required_scopes=[MAIL_WRITE],
                    metadata={"draft_id": draft["id"], "message_id": source["id"]},
                )

                if "send" in normalized:
                    approval = approvals.get("graph.outlook.send_draft")
                    if not approval or not approval.approved:
                        record(
                            "approval",
                            "graph.outlook.send_draft",
                            "waiting",
                            "Draft retained; a human must approve outbound email",
                            required_scopes=[MAIL_SEND],
                            side_effect=True,
                            approval_required=True,
                            approved=False,
                        )
                        return WorkflowTrace(
                            request=request,
                            status="awaiting_approval",
                            outcome=f"Draft {draft['id']} is ready for review.",
                            events=events,
                            granted_scopes=sorted(self.grant.scopes),
                            latency_ms=round((time.perf_counter() - started) * 1000, 2),
                        )
                    self.grant.require(MAIL_SEND)
                    self.client.send_draft(draft["id"])
                    record(
                        "tool",
                        "graph.outlook.send_draft",
                        "ok",
                        f"Sent approved draft {draft['id']}",
                        required_scopes=[MAIL_SEND],
                        side_effect=True,
                        approval_required=True,
                        approved=True,
                        metadata={
                            "approval_ticket": approval.ticket,
                            "approved_by": approval.approved_by,
                        },
                    )

            if "teams" in normalized or "notify" in normalized:
                approval = approvals.get("graph.teams.post_message")
                if not approval or not approval.approved:
                    record(
                        "approval",
                        "graph.teams.post_message",
                        "waiting",
                        "Teams notification withheld pending human approval",
                        required_scopes=[TEAMS_SEND],
                        side_effect=True,
                        approval_required=True,
                        approved=False,
                    )
                    return WorkflowTrace(
                        request=request,
                        status="awaiting_approval",
                        outcome="Incident summary is ready for Teams approval.",
                        events=events,
                        granted_scopes=sorted(self.grant.scopes),
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    )
                self.grant.require(TEAMS_SEND)
                post = self.client.post_teams_message(
                    "facilities-team",
                    "incident-response",
                    f"{len(high_priority)} high-priority facilities incident(s) require attention.",
                )
                record(
                    "tool",
                    "graph.teams.post_message",
                    "ok",
                    f"Posted approved Teams notification {post['id']}",
                    required_scopes=[TEAMS_SEND],
                    side_effect=True,
                    approval_required=True,
                    approved=True,
                    metadata={
                        "approval_ticket": approval.ticket,
                        "approved_by": approval.approved_by,
                        "channel_id": "incident-response",
                    },
                )

            return WorkflowTrace(
                request=request,
                status="completed",
                outcome=(
                    f"Triaged {len(messages)} unread messages and identified "
                    f"{len(high_priority)} high-priority facilities incident(s)."
                ),
                events=events,
                retrieved_context=[
                    {"name": "facilities escalation policy", "classification": "internal"},
                    {"name": "incident response routing", "classification": "internal"},
                ],
                granted_scopes=sorted(self.grant.scopes),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        except (PermissionDenied, KeyError, RuntimeError, httpx.HTTPError) as exc:
            record("policy", "workflow.fail_closed", "blocked", str(exc))
            return WorkflowTrace(
                request=request,
                status="blocked",
                outcome="The workflow was stopped before an unauthorized action occurred.",
                events=events,
                granted_scopes=sorted(self.grant.scopes),
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
            )


def build_demo_agent(
    scopes: set[str] | frozenset[str] | None = None,
) -> Microsoft365Agent:
    grant = OAuthGrant(
        tenant_id="northstar-facilities",
        subject="facility.agent@example.test",
        scopes=frozenset(scopes or {MAIL_READ, MAIL_WRITE, MAIL_SEND, TEAMS_SEND}),
    )
    return Microsoft365Agent(MockMicrosoftGraphClient(), grant)


class Microsoft365DemoHarness:
    """Select a least-privilege demo grant from each evaluation case."""

    def run(self, request: str, context: dict[str, Any] | None = None) -> WorkflowTrace:
        context = context or {}
        scopes = set(context.get("scopes", [MAIL_READ]))
        return build_demo_agent(scopes).run(request, context=context)
