"""Concrete AI transports. Importing them registers each with AIClient."""
from __future__ import annotations

from jobcaliber.ai.client.base import (
    AIClient,
    AIError,
    LLMRequest,
    SystemOneRequest,
    TransportRequest,
)
from jobcaliber.ai.client.llm import LLMClient
from jobcaliber.ai.client.system_one import SystemOneClient

__all__ = [
    "AIClient",
    "AIError",
    "LLMClient",
    "LLMRequest",
    "SystemOneClient",
    "SystemOneRequest",
    "TransportRequest",
]
