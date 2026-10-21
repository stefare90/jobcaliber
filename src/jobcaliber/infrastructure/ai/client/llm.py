"""LLM transport: any OpenAI-compatible `/v1/chat/completions` endpoint.

Ollama, OpenRouter and OpenAI all speak this wire; they differ only by config
(`base_url`, `model`, `api_key_env`).
"""
from __future__ import annotations

from jobcaliber.infrastructure.ai.client.base import AIClient, LLMRequest, TransportRequest


@AIClient.register("openai", "llm")
class LLMClient(AIClient):
    def complete(self, user: str, system: str = "", temperature: float = 0.0) -> str:
        return self._post(LLMRequest(user=user, system=system, temperature=temperature))

    def build_request(self, request: LLMRequest) -> TransportRequest:
        messages = ([{"role": "system", "content": request.system}] if request.system else []) + [
            {"role": "user", "content": request.user}
        ]
        return TransportRequest(
            path="/chat/completions",
            payload={
                **self.engine.options,
                "model": self.engine.model,
                "messages": messages,
                "temperature": request.temperature,
            },
        )

    def extract(self, data: dict) -> str:
        return data["choices"][0]["message"]["content"]
