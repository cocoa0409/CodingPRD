"""Requests that violate two rules at once, where only the precedence ordering
decides which refusal the caller sees.
"""
from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    create_attempt_payload,
    dimension_score,
    record_score_payload,
    rubric_dimension,
)
from test_helpers.test_users import make_evaluator_headers, make_student_headers

INSIDE_COOLOFF_UTC = "2026-09-02T00:00:00.000Z"

TWO_EQUAL_DIMENSIONS = [
    rubric_dimension("D1", 0.5000, 100, False),
    rubric_dimension("D2", 0.5000, 100, False),
]


def _inside_the_cooloff_window():
    """A failed attempt whose cool-off runs to 2026-09-03, observed from
    2026-09-02 while the term is still active."""
    ctx = fx.scored_attempt(score=40)
    assert ctx["attempt"]["status"] == "SCORED_NOT_MASTERED"
    fx.set_clock(INSIDE_COOLOFF_UTC)
    return ctx


def test_the_cooloff_gate_is_live_one_day_into_the_two_day_window():
    """The control: with the term still active, a retry inside the cool-off window
    is refused for the cool-off alone.

    PRD: "The attempt cool-off window has elapsed — otherwise
    `ERR_ATTEMPT_COOLOFF_ACTIVE`. Applies to attempt creation."

    Design: Difficulty/priority_pair_validation_conflict/term_state_beats_attempt_cooloff
    """
    ctx = _inside_the_cooloff_window()

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_ATTEMPT_COOLOFF_ACTIVE.value, 422)


def test_a_closed_term_outranks_the_still_live_cooloff():
    """Once the term has lapsed both rules are violated by the same request, and
    the lifecycle-state refusal is the one reported.

    PRD: "The rejection a caller sees is always the violation with the lowest
    precedence number in the ordering below, and evaluation stops there."

    Design: Difficulty/priority_pair_validation_conflict/term_state_beats_attempt_cooloff
    """
    ctx = _inside_the_cooloff_window()

    closed = fx.close_term(ctx["term"]["id"], "LAPSED", INSIDE_COOLOFF_UTC)
    assert closed["status"] == "LAPSED"

    response = api_client.create_attempt(
        create_attempt_payload(ctx["student"]["id"], ctx["competency"]["id"]),
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TERM_NOT_ACTIVE.value, 409)

    listed = api_client.list_attempts(fx.REGISTRAR,
                                      params={"student_id": ctx["student"]["id"]})
    A.assert_page(listed, 1)


def _conflicted_and_clean_readers():
    """An attempt under review with two candidate readers: one linked to the
    student's own mentor, one with no mentor appointment at all."""
    ctx = fx.mentored_scenario(
        mentor_overrides={"full_name": "Mentor Mira", "email": "mira@example.edu",
                          "max_caseload": 5, "cadence_days": 7},
        with_blueprint=True,
        blueprint_dimensions=TWO_EQUAL_DIMENSIONS,
    )
    assert ctx["assignment"]["status"] == "ACTIVE"
    ctx["conflicted_reader"] = fx.create_evaluator(
        full_name="Conflicted Reader", email="coi@example.edu",
        certification_level="SENIOR", mentor_id=ctx["mentor"]["id"],
    )
    ctx["clean_reader"] = fx.create_evaluator(
        full_name="Clean Reader", email="clean@example.edu",
        certification_level="SENIOR",
    )
    ctx["attempt"] = fx.open_attempt(ctx["student"]["id"], ctx["competency"]["id"])
    ctx["attempt"] = fx.submit_attempt(ctx["attempt"]["id"], ctx["student"]["id"])
    return ctx


def test_an_unknown_rubric_dimension_alone_is_a_dimension_mismatch():
    """The control: a conflict-free reader submitting a code the rubric never
    declared is refused for the rubric alone.

    PRD: "The submitted `dimension_scores` key set equals the bound blueprint's
    rubric dimension code set exactly, with no missing and no unknown dimension —
    otherwise `ERR_RUBRIC_DIMENSION_MISMATCH`. Applies to rubric scoring."

    Design: Difficulty/priority_pair_validation_conflict/integrity_coi_beats_rubric_mismatch
    """
    ctx = _conflicted_and_clean_readers()

    response = api_client.record_score(
        ctx["attempt"]["id"],
        record_score_payload(ctx["clean_reader"]["id"], [dimension_score("D9", 50)]),
        make_evaluator_headers(ctx["clean_reader"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_RUBRIC_DIMENSION_MISMATCH.value, 422)


def test_segregation_of_duties_outranks_the_rubric_mismatch_at_the_same_status():
    """The candidate's own coach submitting the same bogus payload is refused for
    the conflict instead. Both refusals are 422, so nothing but the precedence
    order distinguishes them.

    PRD: "Segregation of duties. At scoring time the reader must not be linked to
    the mentor of the student's active mentor assignment, and no existing
    non-voided score on the attempt may have come from a reader sharing that same
    mentor link — otherwise `ERR_EVALUATOR_CONFLICT_OF_INTEREST`."

    Design: Difficulty/priority_pair_validation_conflict/integrity_coi_beats_rubric_mismatch
    """
    ctx = _conflicted_and_clean_readers()

    response = api_client.record_score(
        ctx["attempt"]["id"],
        record_score_payload(ctx["conflicted_reader"]["id"],
                             [dimension_score("D9", 50)]),
        make_evaluator_headers(ctx["conflicted_reader"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_EVALUATOR_CONFLICT_OF_INTEREST.value, 422)

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    assert attempt["status"] == "UNDER_REVIEW"
    assert attempt["scores_received_count"] == 0
    A.assert_page(
        api_client.list_evaluator_scores(fx.REGISTRAR,
                                         params={"attempt_id": ctx["attempt"]["id"]}),
        0,
    )
