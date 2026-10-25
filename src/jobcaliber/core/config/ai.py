"""AI engines and roles: transports are chosen by config, never by code."""
from __future__ import annotations

import ipaddress
import os
import re
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

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


MAC_ADDRESS = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


class WakeOnLan(BaseModel):
    """How to power on the machine that serves this engine, from S5 or S3."""

    mac: str
    broadcast: str
    wait_s: int = 150

    @field_validator("mac")
    @classmethod
    def _mac(cls, value: str) -> str:
        if not MAC_ADDRESS.match(value):
            raise ValueError(f"mac {value!r} is not a MAC address; expected aa:bb:cc:dd:ee:ff")
        return value.lower()

    @field_validator("broadcast")
    @classmethod
    def _broadcast(cls, value: str) -> str:
        try:
            ipaddress.IPv4Address(value)
        except ValueError:
            raise ValueError(f"broadcast {value!r} is not an IPv4 address") from None
        return value

    @field_validator("wait_s")
    @classmethod
    def _wait(cls, value: int) -> int:
        if not 5 <= value <= 900:
            raise ValueError(f"wait_s must be within [5, 900], got {value}")
        return value


class ModelHost(BaseModel):
    """The machine that serves this engine: how to bring it up and down.

    The controller owns the policy (leave the host as you found it); the host only receives the
    three elementary commands. Empty commands are allowed: a host that stays on needs none.
    """

    # The machine itself: needed to know whether it is up before deciding what to do.
    address: str | None = None
    ssh_port: int = 22
    wake_on_lan: WakeOnLan | None = None
    start_command: str | None = None
    stop_command: str | None = None
    poweroff_command: str | None = None

    @model_validator(mode="after")
    def _something_to_do(self) -> "ModelHost":
        if not (self.wake_on_lan or self.start_command or self.stop_command or self.poweroff_command):
            raise ValueError("model_host needs at least one of wake_on_lan, start_command, stop_command, poweroff_command")
        if not self.address and (self.wake_on_lan or self.poweroff_command):
            raise ValueError(
                "model_host.address is required to wake or power off the host: without it the "
                "controller cannot tell whether the machine was already on"
            )
        return self


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
    model_host: ModelHost | None = None

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
