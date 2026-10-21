import re

import pytest

from jobcaliber.core.config import Criterion, GateAccept, GateMinScore, Question
from jobcaliber.pipeline.scoring.projection import build_llm_prompt, build_systemone_questions

POSTING_PLACEHOLDERS = {"title", "company", "location", "salary", "description"}


def score_q(name: str) -> Question:
    return Question(
        type="score", instructions=f"how good is {name}?", levels=["Not stated", "Low", "Good", "Perfect"], missing=0
    )


def choice_q(missing: str = "missing") -> Question:
    return Question(
        type="choice",
        instructions="is it acceptable?",
        options={"yes": "yes", "no": "no", "missing": "not stated"},
        missing=missing,
    )


def one_criterion() -> dict[str, Criterion]:
    return {"core_skills": Criterion(weight=45, question=score_q("the stack"))}


def eight_criteria() -> dict[str, Criterion]:
    criteria = {
        "core_skills": Criterion(weight=45, question=score_q("the stack")),
        "tools": Criterion(weight=20, question=score_q("the tools")),
        "pay": Criterion(weight=15, question=score_q("the pay")),
        "contract": Criterion(weight=20, question=score_q("the contract")),
        "company_size": Criterion(weight=10, question=score_q("the size")),
        "location": Criterion(
            gate=GateAccept(accept=["primary", "remote"]),
            question=Question(
                type="choice",
                instructions="where?",
                options={"primary": "p", "remote": "r", "unknown": "u"},
                missing="unknown",
            ),
        ),
        "salary_ok": Criterion(gate=True, question=choice_q()),
        "strict": Criterion(gate=GateMinScore(min_score=0.6), question=score_q("strictness")),
    }
    return criteria


@pytest.mark.parametrize("factory", [one_criterion, eight_criteria])
def test_systemone_keys_match_criteria(factory):
    criteria = factory()
    assert set(build_systemone_questions(criteria)) == set(criteria)


@pytest.mark.parametrize("factory", [one_criterion, eight_criteria])
def test_llm_prompt_mentions_every_key_and_instruction(factory):
    criteria = factory()
    system, user = build_llm_prompt(criteria)
    assert "job-match" in system.lower()
    for key, criterion in criteria.items():
        assert key in user
        assert criterion.question.instructions in user


def test_score_projection_carries_only_wire_fields():
    questions = build_systemone_questions(one_criterion())
    assert questions["core_skills"] == {
        "type": "score",
        "instructions": "how good is the stack?",
        "criteria": ["Not stated", "Low", "Good", "Perfect"],
    }


def test_choice_projection_carries_only_wire_fields():
    criteria = {"salary_ok": Criterion(gate=True, question=choice_q())}
    questions = build_systemone_questions(criteria)
    assert questions["salary_ok"] == {
        "type": "choice",
        "instructions": "is it acceptable?",
        "criteria": {"yes": "yes", "no": "no", "missing": "not stated"},
    }


def test_llm_prompt_only_leaves_posting_placeholders():
    _, user = build_llm_prompt(eight_criteria())
    found = set(re.findall(r"\{\{\s*(\w+)\s*\}\}", user))
    assert found == POSTING_PLACEHOLDERS


def test_llm_example_uses_the_real_keys():
    _, user = build_llm_prompt(eight_criteria())
    example = user.strip().splitlines()[-1]
    assert '"core_skills"' in example and '"salary_ok"' in example and '"missing"' in example


def test_llm_choice_keys_are_listed_as_options():
    _, user = build_llm_prompt({"salary_ok": Criterion(gate=True, question=choice_q())})
    assert "one of: yes | no | missing" in user


def test_search_placeholders_are_resolved_in_every_field():
    from jobcaliber.core.config import Search

    values = Search(
        titles=["Software Engineer"],
        on_site_locations=["Sardinia, Italy"],
        remote_locations=["Italy"],
    ).render_values()
    criteria = {
        "role_fit": Criterion(apply_threshold=0.67, question=Question(
            type="score", instructions="aligned with {{search.titles}}?",
            levels=["no", "unknown", "partial", "full"], missing=1)),
        "location": Criterion(gate=GateAccept(accept=["accepted"]), question=Question(
            type="choice", instructions="lives in {{search.on_site_locations}}",
            options={"accepted": "in {{search.on_site_locations}} or remote {{search.remote_locations}}",
                     "rejected": "outside {{search.on_site_locations}}",
                     "unknown": "unknown"}, missing="unknown")),
    }
    questions = build_systemone_questions(criteria, values)
    assert questions["role_fit"]["instructions"] == "aligned with Software Engineer?"
    assert questions["location"]["criteria"]["accepted"] == "in Sardinia, Italy or remote Italy"
    _, user = build_llm_prompt(criteria, values)
    assert "{{search." not in user
    assert set(re.findall(r"\{\{(\w+)\}\}", user)) == POSTING_PLACEHOLDERS


def test_unresolved_search_placeholder_fails_fast():
    from jobcaliber.infrastructure.ai.prompts import PromptError

    criteria = {"role_fit": Criterion(apply_threshold=0.67, question=Question(
        type="score", instructions="aligned with {{search.titles}}?",
        levels=["no", "unknown", "partial", "full"], missing=1))}
    with pytest.raises(PromptError, match=r"unresolved placeholder '\{\{search\.titles\}\}'"):
        build_systemone_questions(criteria, {})


def test_search_render_values_expose_titles_and_locations():
    from jobcaliber.core.config import Search

    values = Search(
        titles=["A", "B"],
        on_site_locations=["Sardinia, Italy"],
        remote_locations=["Italy"],
        exclude=["tirocini"],
    ).render_values()
    assert values == {
        "search.titles": "A, B",
        "search.on_site_locations": "Sardinia, Italy",
        "search.remote_locations": "Italy",
        "search.exclude": "tirocini",
    }
    assert Search(titles=["A"]).render_values()["search.exclude"] == "none"
