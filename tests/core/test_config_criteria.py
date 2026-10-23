import pytest
from pydantic import ValidationError

from jobcaliber.core.config import (
    Criterion,
    GateAccept,
    GateMinScore,
    Question,
    Search,
    validate_criteria,
    validate_search,
)


def score_q(levels=("Not stated", "No match", "Good", "Perfect"), missing=0):
    return Question(type="score", instructions="how good?", levels=list(levels), missing=missing)


def choice_q(options=("primary", "remote", "hybrid", "elsewhere", "unknown"), missing="unknown"):
    return Question(
        type="choice",
        instructions="which arrangement?",
        options={o: o.title() for o in options},
        missing=missing,
    )


def bool_q():
    return Question(
        type="choice",
        instructions="at least 38k?",
        options={"yes": "yes", "no": "no", "missing": "not stated"},
        missing="missing",
    )


def scored(min_threshold=0.5, apply_threshold=None, **kw):
    return Criterion(min_threshold=min_threshold, apply_threshold=apply_threshold,
                     question=kw.get("question") or score_q())


# --- search -----------------------------------------------------------------

def test_search_needs_a_title():
    with pytest.raises(ValueError, match="at least one non-empty title"):
        validate_search(Search(titles=["  "], on_site_locations=["Turin, Italy"]))


def test_search_needs_a_location():
    with pytest.raises(ValueError, match="at least one on_site_locations or remote_locations"):
        validate_search(Search(titles=["Dev"], on_site_locations=[" "], remote_locations=[]))


def test_search_accepts_remote_locations_only():
    search = Search(titles=["Dev"], remote_locations=["Italy"])
    validate_search(search)
    assert search.on_site_locations == [] and search.remote_locations == ["Italy"]


# --- criteria shape ---------------------------------------------------------

def test_thresholds_and_gate_are_mutually_exclusive():
    with pytest.raises(ValueError, match="a gate cannot also carry thresholds"):
        validate_criteria({"x": Criterion(min_threshold=0.5, gate=True, question=bool_q())})


def test_criterion_needs_a_gate_or_a_threshold():
    with pytest.raises(ValueError, match="set a gate or at least one threshold"):
        validate_criteria({"x": Criterion(question=score_q())})


def test_gate_false_is_treated_as_no_gate():
    with pytest.raises(ValueError, match="set a gate or at least one threshold"):
        validate_criteria({"x": Criterion(gate=False, question=score_q())})


def test_a_scored_criterion_must_be_a_score_question():
    with pytest.raises(ValueError, match="scored criterion needs a 'score' question"):
        validate_criteria({"x": Criterion(min_threshold=0.5, question=choice_q())})


def test_min_threshold_above_apply_threshold_is_rejected():
    with pytest.raises(ValueError, match="min_threshold 0.9 is above apply_threshold 0.5"):
        validate_criteria({"x": scored(min_threshold=0.9, apply_threshold=0.5)})


def test_thresholds_must_be_within_range():
    with pytest.raises(ValueError, match=r"min_threshold must be within \[0, 1\]"):
        validate_criteria({"x": scored(min_threshold=1.5)})


def test_at_least_one_scored_criterion_is_required():
    with pytest.raises(ValueError, match="at least one scored criterion is required"):
        validate_criteria({"loc": Criterion(gate=GateAccept(accept=["primary"]), question=choice_q())})


# --- boolean gates ----------------------------------------------------------

def test_boolean_gate_needs_yes_no_missing():
    bad = Question(type="choice", instructions="?", options={"yes": "y", "no": "n"}, missing="no")
    with pytest.raises(ValueError, match="exactly the options yes/no/missing"):
        validate_criteria({"x": Criterion(gate=True, question=bad)})


def test_boolean_gate_on_a_score_question_is_rejected():
    with pytest.raises(ValueError, match="a boolean gate needs a 'choice' question"):
        validate_criteria({"x": Criterion(gate=True, question=score_q())})


# --- accept gates -----------------------------------------------------------

def test_accept_gate_needs_a_choice_question():
    with pytest.raises(ValueError, match="gate.accept needs a 'choice' question"):
        validate_criteria({"x": Criterion(gate=GateAccept(accept=["good"]), question=score_q())})


def test_accept_must_be_a_subset_of_the_options():
    with pytest.raises(ValueError, match=r"names \['onsite'\] which are not options"):
        validate_criteria({"x": Criterion(gate=GateAccept(accept=["onsite"]), question=choice_q())})


def test_accept_must_not_accept_the_missing_option():
    with pytest.raises(ValueError, match="cannot be accepted"):
        validate_criteria({"x": Criterion(gate=GateAccept(accept=["primary", "unknown"]), question=choice_q())})


def test_accept_gate_happy_path():
    validate_criteria({
        "core": scored(),
        "location": Criterion(gate=GateAccept(accept=["primary", "remote"]), question=choice_q()),
    })


# --- min_score gates --------------------------------------------------------

def test_min_score_gate_needs_a_score_question():
    with pytest.raises(ValueError, match="gate.min_score needs a 'score' question"):
        validate_criteria({"x": Criterion(gate=GateMinScore(min_score=0.5), question=choice_q())})


def test_min_score_must_be_within_range():
    with pytest.raises(ValueError, match=r"within \[0, 1\]"):
        validate_criteria({"x": Criterion(gate=GateMinScore(min_score=1.5), question=score_q())})


# --- question validity ------------------------------------------------------

def test_score_question_needs_two_levels():
    with pytest.raises(ValueError, match="at least 2 levels"):
        validate_criteria({"x": scored(question=score_q(levels=("only one",)))})


def test_score_missing_must_be_a_valid_level_index():
    with pytest.raises(ValueError, match="level index must be within"):
        validate_criteria({"x": scored(question=score_q(missing=9))})


def test_score_missing_must_be_an_index_not_a_key():
    with pytest.raises(ValueError, match="'missing' must be a level index"):
        validate_criteria({"x": scored(question=Question(type="score", instructions="?", levels=["a", "b"], missing="na"))})


def test_choice_question_needs_options():
    with pytest.raises(ValueError, match="needs at least one option"):
        validate_criteria({"x": Criterion(gate=True, question=Question(type="choice", instructions="?", missing="missing"))})


def test_choice_missing_must_be_an_option_key():
    with pytest.raises(ValueError, match="'missing' must be one of the options"):
        validate_criteria({"x": Criterion(gate=GateAccept(accept=["primary"]), question=choice_q(missing="nope"))})


def test_empty_criteria_are_rejected():
    with pytest.raises(ValueError, match="at least one criterion"):
        validate_criteria({})


def test_full_happy_path_with_mixed_criteria():
    criteria = {
        "core_skills": scored(min_threshold=0.5, apply_threshold=1.0),
        "tools": scored(min_threshold=0.5, apply_threshold=1.0),
        "role_fit": scored(apply_threshold=1.0),
        "pay": scored(apply_threshold=0.75),
        "location": Criterion(gate=GateAccept(accept=["primary", "remote", "hybrid"]), question=choice_q()),
        "contract_ok": Criterion(gate=True, question=bool_q()),
    }
    validate_criteria(criteria)
    assert set(criteria) == {"core_skills", "tools", "role_fit", "pay", "location", "contract_ok"}


def test_question_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Question(type="noul", instructions="?", missing=0)
