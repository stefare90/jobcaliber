"""Concrete AI transports. Importing them registers each with AIClient."""
from __future__ import annotations

from jobcaliber.infrastructure.ai.client.base import (
    AIClient,
    AIError,
    LLMRequest,
    SystemOneRequest,
    TransportRequest,
)
from jobcaliber.infrastructure.ai.client.llm import LLMClient
from jobcaliber.infrastructure.ai.client.system_one import SystemOneClient

__all__ = [
    "AIClient",
    "AIError",
    "LLMClient",
    "LLMRequest",
    "SystemOneClient",
    "SystemOneRequest",
    "TransportRequest",
]
