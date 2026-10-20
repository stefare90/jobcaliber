import pytest
from pydantic import ValidationError

from jobcaliber.config import (
    Criterion,
    GateAccept,
    GateMinScore,
    Question,
    Search,
    SearchLocation,
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


def weighted(weight=45, **kw):
    return Criterion(weight=weight, question=kw.get("question") or score_q())


# --- search -----------------------------------------------------------------

def test_search_needs_a_title():
    with pytest.raises(ValueError, match="at least one non-empty title"):
        validate_search(Search(titles=["  "], locations=[SearchLocation(query="Turin, Italy")]))


def test_search_needs_a_location_query():
    with pytest.raises(ValueError, match="at least one non-empty location query"):
        validate_search(Search(titles=["Dev"], locations=[SearchLocation(query=" ")]))


def test_search_accepts_a_remote_location():
    search = Search(
        titles=["Dev"],
        locations=[SearchLocation(query="Turin, Italy"), SearchLocation(query="Italy", remote=True)],
    )
    validate_search(search)
    assert [loc.remote for loc in search.locations] == [False, True]


# --- criteria shape ---------------------------------------------------------

def test_weight_and_gate_are_mutually_exclusive():
    with pytest.raises(ValueError, match="not both"):
        validate_criteria({"x": Criterion(weight=10, gate=True, question=bool_q())})


def test_criterion_needs_weight_or_gate():
    with pytest.raises(ValueError, match="set either weight > 0 or a gate"):
        validate_criteria({"x": Criterion(question=score_q())})


def test_gate_false_is_treated_as_no_gate():
    with pytest.raises(ValueError, match="set either weight > 0 or a gate"):
        validate_criteria({"x": Criterion(gate=False, question=score_q())})


def test_a_weighted_criterion_must_be_a_score_question():
    with pytest.raises(ValueError, match="weighted criterion needs a 'score' question"):
        validate_criteria({"x": Criterion(weight=10, question=choice_q())})


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
    validate_criteria({"location": Criterion(gate=GateAccept(accept=["primary", "remote"]), question=choice_q())})


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
        validate_criteria({"x": weighted(question=score_q(levels=("only one",)))})


def test_score_missing_must_be_a_valid_level_index():
    with pytest.raises(ValueError, match="level index must be within"):
        validate_criteria({"x": weighted(question=score_q(missing=9))})


def test_score_missing_must_be_an_index_not_a_key():
    with pytest.raises(ValueError, match="'missing' must be a level index"):
        validate_criteria({"x": weighted(question=Question(type="score", instructions="?", levels=["a", "b"], missing="na"))})


def test_choice_question_needs_options():
    with pytest.raises(ValueError, match="needs at least one option"):
        validate_criteria({"x": Criterion(gate=True, question=Question(type="choice", instructions="?", missing="missing"))})


def test_choice_missing_must_be_an_option_key():
    with pytest.raises(ValueError, match="'missing' must be one of the options"):
        validate_criteria({"x": Criterion(gate=GateAccept(accept=["primary"]), question=choice_q(missing="nope"))})


# --- penalties --------------------------------------------------------------

def test_penalties_must_reference_known_criteria():
    with pytest.raises(ValueError, match="penalty for unknown criterion 'ghost'"):
        validate_criteria({"core": weighted()}, penalties={"ghost": 0.8})


def test_penalty_must_be_a_factor():
    with pytest.raises(ValueError, match=r"penalty must be within \(0, 1\]"):
        validate_criteria({"core": weighted()}, penalties={"core": 0.0})


def test_empty_criteria_are_rejected():
    with pytest.raises(ValueError, match="at least one criterion"):
        validate_criteria({})


def test_full_happy_path_with_mixed_criteria():
    criteria = {
        "core_skills": weighted(45),
        "tools": weighted(20),
        "location": Criterion(gate=GateAccept(accept=["primary", "remote", "hybrid"]), question=choice_q()),
        "salary_ok": Criterion(gate=True, question=bool_q()),
        "strict_match": Criterion(gate=GateMinScore(min_score=0.7), question=score_q()),
    }
    validate_criteria(criteria, penalties={"core_skills": 0.85})
    assert set(criteria) == {"core_skills", "tools", "location", "salary_ok", "strict_match"}


def test_question_rejects_unknown_type():
    with pytest.raises(ValidationError):
        Question(type="noul", instructions="?", missing=0)
