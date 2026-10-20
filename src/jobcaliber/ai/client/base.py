"""The AIClient interface, its registry, and the shared HTTP transport."""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar

import httpx

from jobcaliber.config import AIEngine


class AIError(RuntimeError):
    pass


@dataclass
class SystemOneRequest:
    state: str
    questions: dict[str, Any]


@dataclass
class LLMRequest:
    user: str
    system: str = ""
    temperature: float = 0.0


@dataclass
class TransportRequest:
    """What a client sends: one wire call's path plus its payload."""

    path: str
    payload: dict = field(default_factory=dict)


class AIClient(ABC):
    """Common interface for every AI transport, plus the wire-api registry.

    The registry is keyed by `engine.api` (the wire protocol), not by product:
    rizzo, Jev and laya all speak `systemone`, while Ollama, OpenRouter and OpenAI
    all speak `openai`. Products differ only by config (base_url, model, key).

    Concrete clients subclass it and self-register:
        @AIClient.register("systemone")
        class SystemOneClient(AIClient): ...
    """

    _registry: ClassVar[dict[str, type["AIClient"]]] = {}
    kind: ClassVar[str] = ""

    def __init__(self, engine: AIEngine, http: httpx.Client | None = None, sleep_fn=None):
        if type(self) is AIClient:
            raise AIError("AIClient is abstract; use AIClient.create() or a concrete subclass")
        if type(self).kind and engine.kind != type(self).kind:
            raise AIError(f"{type(self).__name__} needs a '{type(self).kind}' engine, got '{engine.kind}'")
        self.engine = engine
        self.http = http or httpx.Client(timeout=engine.timeout_s)
        self.sleep_fn = sleep_fn or time.sleep

    @classmethod
    def register(cls, api: str, kind: str):
        def _decorator(subclass: type["AIClient"]) -> type["AIClient"]:
            AIClient._registry[api] = subclass
            subclass.kind = kind
            return subclass
        return _decorator

    @classmethod
    def create(cls, engine: AIEngine, http: httpx.Client | None = None) -> "AIClient":
        """Build the client registered for the engine's wire api."""
        subclass = AIClient._registry.get(engine.api)
        if subclass is None:
            raise AIError(f"no AI client registered for api '{engine.api}'; known: {sorted(AIClient._registry)}")
        return subclass(engine, http)

    @abstractmethod
    def build_request(self, request: Any) -> TransportRequest:
        """Translate a domain request into the wire path and payload."""

    @abstractmethod
    def extract(self, data: dict) -> Any:
        """Pull the domain value out of the provider's JSON response."""

    def headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        api_key = self.engine.resolve_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.update(self.engine.headers)
        return headers

    def _retry_delay(self, resp: httpx.Response, attempt: int) -> float:
        policy = self.engine.retry
        retry_after = resp.headers.get("Retry-After", "").strip()
        if retry_after.isdigit():
            return min(float(retry_after), policy.max_delay_s)
        delay = min(policy.base_delay_s * 2 ** (attempt - 1), policy.max_delay_s)
        return delay * (1 + random.uniform(0, 0.2))

    def _post(self, request: Any) -> Any:
        transport = self.build_request(request)
        url = f"{self.engine.base_url}{transport.path}"
        attempts = max(1, self.engine.retry.max_attempts)
        for attempt in range(1, attempts + 1):
            if self.engine.throttle_s > 0:
                self.sleep_fn(self.engine.throttle_s)
            resp = self.http.post(url, json=transport.payload, headers=self.headers())
            retryable = resp.status_code == 429 or resp.status_code >= 500
            if retryable and attempt < attempts:
                self.sleep_fn(self._retry_delay(resp, attempt))
                continue
            resp.raise_for_status()
            return self.extract(resp.json())
        raise AIError(f"no response from {url} after {attempts} attempts")
