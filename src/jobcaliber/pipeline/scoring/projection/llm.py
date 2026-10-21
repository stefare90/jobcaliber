"""Project criteria into a chat-completion prompt pair (deterministic, no LLM)."""
from __future__ import annotations

import json

from jobcaliber.infrastructure.ai.prompts import render
from jobcaliber.core.config import Criterion

SYSTEM = (
    "You are a strict, objective job-match decision model. Score the job against the "
    "candidate's criteria. Reply with a single JSON object and nothing else."
)

POSTING_BLOCK = """Job posting:
Title: {{title}}
Company: {{company}}
Declared location: {{location}}
Declared salary: {{salary}}
Description:
{{description}}"""


def _criterion_line(key: str, criterion: Criterion, values: dict[str, str]) -> str:
    question = criterion.question
    instructions = render(question.instructions, values, strict=True)
    if question.type == "score":
        spec = f"score 0-1 · {instructions}"
    else:
        options = " | ".join(render(opt, values, strict=True) for opt in question.options)
        spec = f"one of: {options} · {instructions}"
    return f"- {key:<14} {spec}"


def build_llm_prompt(criteria: dict[str, Criterion],
                     values: dict[str, str] | None = None) -> tuple[str, str]:
    values = values or {}
    lines = [render(POSTING_BLOCK, {**values, "title": "{{title}}", "company": "{{company}}",
                                    "location": "{{location}}", "salary": "{{salary}}",
                                    "description": "{{description}}"}), "",
             "Criteria (every key must appear in your JSON):"]
    lines += [_criterion_line(key, criterion, values) for key, criterion in criteria.items()]
    lines += [
        "",
        'If the posting does not state what a key needs, do NOT guess: add the key to "missing".',
        "",
        "Return JSON exactly like:",
        _example(criteria),
    ]
    return SYSTEM, "\n".join(lines)


def _example(criteria: dict[str, Criterion]) -> str:
    sample: dict[str, object] = {}
    for key, criterion in criteria.items():
        question = criterion.question
        sample[key] = 0.0 if question.type == "score" else next(iter(question.options))
    sample["missing"] = [key for key, c in criteria.items() if c.question.type == "score"][:1]
    sample["confidence"] = 0.8
    sample["summary_reason"] = ""
    return json.dumps(sample, ensure_ascii=False)
