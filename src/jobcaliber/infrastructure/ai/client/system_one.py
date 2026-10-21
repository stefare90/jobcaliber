"""System One transport: `POST {base_url}/v1/systemone` (rizzo-flow, Jev, laya)."""
from __future__ import annotations

from typing import Any

from jobcaliber.infrastructure.ai.client.base import AIClient, SystemOneRequest, TransportRequest


@AIClient.register("systemone", "decision")
class SystemOneClient(AIClient):
    def system_one(self, state: str, questions: dict[str, Any]) -> dict:
        return self._post(SystemOneRequest(state=state, questions=questions))

    def build_request(self, request: SystemOneRequest) -> TransportRequest:
        return TransportRequest(
            path="/v1/systemone",
            payload={"state": request.state, "model": self.engine.model, "questions": request.questions},
        )

    def extract(self, data: dict) -> dict:
        return data
