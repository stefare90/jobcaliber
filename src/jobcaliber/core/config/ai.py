"""AI engines and roles: transports are chosen by config, never by code."""
from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, Field, model_validator

KIND_APIS = {"decision": {"systemone"}, "llm": {"openai"}}
# Allowed engine kinds per role (a role may have several implementations).
ROLE_KINDS: dict[str, set[str]] = {
    "scorer": {"decision", "llm"},
}


class RetryPolicy(BaseModel):
    """Retry only transient transport failures (429 / 5xx), never a rejecting answer."""

    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 20.0


class AIEngine(BaseModel):
    kind: str
    api: str
    base_url: str
    model: str
    api_key_env: str | None = None
    timeout_s: float = 120.0
    headers: dict[str, str] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    throttle_s: float = 0.0

    @model_validator(mode="after")
    def _validate_kind_api(self) -> "AIEngine":
        if self.kind not in KIND_APIS:
            raise ValueError(f"unknown engine kind '{self.kind}'; expected one of {sorted(KIND_APIS)}")
        if self.api not in KIND_APIS[self.kind]:
            raise ValueError(f"api '{self.api}' is not valid for kind '{self.kind}'; expected {sorted(KIND_APIS[self.kind])}")
        if self.options and self.kind != "llm":
            raise ValueError(
                f"engine '{self.model}': 'options' is only valid for kind 'llm'; "
                f"the systemone wire takes a fixed payload (state/model/questions)"
            )
        return self

    def resolve_api_key(self) -> str:
        return os.environ.get(self.api_key_env, "") if self.api_key_env else ""


class AIConfig(BaseModel):
    prompts_dir: str = "prompts"
    engines: dict[str, AIEngine] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)
    custom_prompts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_roles(self) -> "AIConfig":
        for role, engine_name in self.roles.items():
            if role not in ROLE_KINDS:
                raise ValueError(f"unknown role '{role}'; expected one of {sorted(ROLE_KINDS)}")
            if engine_name not in self.engines:
                raise ValueError(f"role '{role}' references unknown engine '{engine_name}'")
            kind = self.engines[engine_name].kind
            if kind not in ROLE_KINDS[role]:
                raise ValueError(f"role '{role}' accepts {sorted(ROLE_KINDS[role])} engines, but '{engine_name}' is '{kind}'")
        return self
