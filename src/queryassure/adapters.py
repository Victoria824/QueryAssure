from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from .models import AgentTrace


class CallableAgentAdapter:
    """Wrap any Python callable so it can be evaluated by QueryAssure."""

    def __init__(self, function: Callable[[str], AgentTrace | dict[str, Any]]) -> None:
        self.function = function

    def ask(self, question: str) -> AgentTrace:
        result = self.function(question)
        if isinstance(result, AgentTrace):
            return result
        return AgentTrace(**result)


class HttpAgentAdapter:
    """Evaluate an existing agent through a small, configurable HTTP contract."""

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.headers = headers or {}

    def ask(self, question: str) -> AgentTrace:
        response = httpx.post(
            self.url,
            json={"question": question},
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        # The reference API nests a trace; simple third-party adapters can return it directly.
        trace = payload.get("trace", payload)
        return AgentTrace(**trace)
