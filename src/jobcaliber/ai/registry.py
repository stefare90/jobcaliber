"""AIClients: build engine transports from `AIConfig` and resolve pipeline roles."""
from __future__ import annotations

from pathlib import Path
from typing import Union

import httpx

from jobcaliber.ai.client import AIClient, AIError, LLMClient, SystemOneClient
from jobcaliber.ai.prompts import PromptStore
from jobcaliber.config import AIConfig, Criterion, validate_criteria

Client = Union[SystemOneClient, LLMClient]


class AIClients:
    def __init__(self, ai_config: AIConfig, prompts: PromptStore, http: httpx.Client | None = None):
        self.config = ai_config
        self.prompts = prompts
        self._clients: dict[str, Client] = {
            name: AIClient.create(engine, http) for name, engine in ai_config.engines.items()
        }
        self._roles = ai_config.roles

    @classmethod
    def from_config(cls, ai_config: AIConfig, root: Path, http: httpx.Client | None = None) -> "AIClients":
        prompts = PromptStore(root / ai_config.prompts_dir, ai_config.custom_prompts)
        clients = cls(ai_config, prompts, http)
        clients._validate_scorer_prompts()
        return clients

    def _validate_scorer_prompts(self) -> None:
        """Kept for symmetry: projections are validated when a scorer is built."""
        name = self._roles.get("scorer")
        if not name:
            return
        if self.config.engines[name].kind not in ("decision", "llm"):
            raise AIError(f"scorer engine '{name}' has an unsupported kind")

    def client(self, role: str) -> Client:
        name = self._roles.get(role)
        if not name:
            raise AIError(f"role '{role}' is not configured under ai.roles")
        return self._clients[name]

    def by_name(self, engine_name: str) -> Client:
        if engine_name not in self._clients:
            raise AIError(f"unknown engine '{engine_name}'; known: {sorted(self._clients)}")
        return self._clients[engine_name]

    def system_one(self, role: str = "scorer") -> SystemOneClient:
        client = self.client(role)
        if not isinstance(client, SystemOneClient):
            raise AIError(f"role '{role}' is not a decision engine")
        return client

    def llm(self, role: str) -> LLMClient:
        client = self.client(role)
        if not isinstance(client, LLMClient):
            raise AIError(f"role '{role}' is not an llm engine")
        return client

    # Domain services, built from the role-resolved engine (lazy imports avoid a
    # package cycle: scoring/delivery/ingestion import jobcaliber.ai submodules).
    def scorer(self, criteria: dict[str, Criterion], values: dict[str, str] | None = None):
        """Scorer for the configured 'scorer' role (implementation hidden)."""
        return self.scorer_for(self._role_engine("scorer"), criteria, values)

    def scorer_for(self, engine_name: str, criteria: dict[str, Criterion],
                   values: dict[str, str] | None = None):
        """Scorer for a named engine (used by benchmarks)."""
        from jobcaliber.scoring import Scorer
        validate_criteria(criteria)
        return Scorer.create(self.by_name(engine_name), criteria, self.prompts, values)

    def _role_engine(self, role: str) -> str:
        name = self._roles.get(role)
        if not name:
            raise AIError(f"role '{role}' is not configured under ai.roles")
        return name

    def query_expander(self):
        from jobcaliber.ingestion.query_expander import QueryExpander
        return QueryExpander(self.llm("query_expander"), self.prompts)
