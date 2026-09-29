"""Inclusive boundaries pinned at two-decimal precision, and the zero / empty
edge of the transcript translation.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.api_client import api_client
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import (
    create_transcript_record_payload,
    dimension_score,
    rubric_dimension,
)

TEN_THOUSAND_POINT_RUBRIC = [
    rubric_dimension("D1", 0.5000, 10000, False),
    rubric_dimension("D2", 0.5000, 10000, False),
]


def _two_boundary_attempts():
    """Two competencies with an explicit 80.00 threshold and ten-thousand-point
    dimensions, so a single hundredth of a percentage point is reachable."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program(units_per_credit_hour=3.0)
    at_threshold = fx.create_competency(program["id"], code="B-1",
                                        title="Boundary One", unit_value=4,
                                        level="CORE", mastery_threshold_pct=80.00)
    fx.create_blueprint(at_threshold, dimensions=TEN_THOUSAND_POINT_RUBRIC,
                        required_evaluator_count=1)
    below = fx.create_competency(program["id"], code="B-2", title="Boundary Two",
                                 unit_value=4, level="CORE",
                                 mastery_threshold_pct=80.00)
    fx.create_blueprint(below, dimensions=TEN_THOUSAND_POINT_RUBRIC,
                        required_evaluator_count=1)
    program = fx.publish_program(program["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    evaluator = fx.create_evaluator()

    exact = fx.open_attempt(student["id"], at_threshold["id"])
    fx.submit_attempt(exact["id"], student["id"], artifact_hash="sha256:b1-a")
    short = fx.open_attempt(student["id"], below["id"])
    fx.submit_attempt(short["id"], student["id"], artifact_hash="sha256:b2-a")
    return {"program": program, "student": student, "term": term,
            "at_threshold": at_threshold, "below": below, "evaluator": evaluator,
            "exact_attempt": exact, "short_attempt": short}


def test_a_score_landing_exactly_on_the_threshold_masters_the_competency():
    """8000 and 8000 out of 10000 weight to exactly 80.00, and the comparison is
    inclusive, so the attempt masters and the units land.

    PRD: "The attempt is mastered when `final_score_pct` is greater than or equal
    to the competency's effective mastery threshold — the boundary is inclusive, so
    a score exactly at the threshold is mastery — and, when the blueprint's
    `passing_rule` is `WEIGHTED_PLUS_ALL_CRITICAL`, additionally when no counted
    score has `critical_fail` true."

    Design: Difficulty/boundary_precision_check/mastery_threshold_inclusive_boundary
    """
    ctx = _two_boundary_attempts()
    A.assert_number_equals(
        fx.refresh_competency(ctx["at_threshold"]["id"])
          ["effective_mastery_threshold_pct"],
        80.00, "effective_mastery_threshold_pct",
    )

    score = fx.record_score(
        ctx["exact_attempt"]["id"], ctx["evaluator"]["id"],
        [dimension_score("D1", 8000), dimension_score("D2", 8000)],
    )
    A.assert_number_equals(score["weighted_score_pct"], 80.00, "weighted_score_pct")

    attempt = fx.refresh_attempt(ctx["exact_attempt"]["id"])
    assert attempt["status"] == "SCORED_MASTERED"

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 4
    assert student["mastered_competency_count"] == 1
    A.assert_number_equals(student["cumulative_credit_equivalency"], 1.3,
                           "cumulative_credit_equivalency")


def test_one_hundredth_below_the_threshold_does_not_master():
    """8000 and 7998 out of 10000 weight to 79.99 — a single hundredth short — and
    that resolves as not mastered with a cool-off published.

    PRD: "Third, multiply the accumulated total by one hundred and round the result
    half up to two decimal places; that single figure is `weighted_score_pct`."

    Design: Difficulty/boundary_precision_check/mastery_threshold_inclusive_boundary
    """
    ctx = _two_boundary_attempts()

    score = fx.record_score(
        ctx["short_attempt"]["id"], ctx["evaluator"]["id"],
        [dimension_score("D1", 8000), dimension_score("D2", 7998)],
    )
    A.assert_number_equals(score["weighted_score_pct"], 79.99, "weighted_score_pct")

    attempt = fx.refresh_attempt(ctx["short_attempt"]["id"])
    assert attempt["status"] == "SCORED_NOT_MASTERED"
    A.assert_instant_equals(attempt["cooloff_until_utc"],
                            "2026-09-03T00:00:00.000Z", "cooloff_until_utc")

    assert fx.refresh_student(ctx["student"]["id"])["mastered_unit_total"] == 0


def test_a_transcript_for_a_student_with_nothing_mastered_carries_an_empty_line_array():
    """The empty case is legal rather than an error: the record is created in DRAFT
    with an empty array and every count at zero.

    PRD: "A transcript for a student with no mastered competencies is perfectly
    legal: `lines` is the empty array, `competency_line_count` is 0, and every
    total is zero."

    Design: Difficulty/boundary_precision_check/empty_transcript_zero_lines
    """
    ctx = fx.base_chain(program_overrides={"units_per_credit_hour": 3.0})

    response = api_client.create_transcript_record(
        create_transcript_record_payload(ctx["student"]["id"], purpose="TRANSFER"),
        fx.REGISTRAR,
    )
    record = validate_success(response, 201)
    assert record["lines"] == []
    assert record["competency_line_count"] == 0
    assert record["total_mastered_units"] == 0
    assert record["status"] == "DRAFT"

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 0


def test_the_empty_transcript_still_publishes_every_credit_hour_figure_as_zero():
    """The division by the program's ratio is not skipped for an empty record: the
    headline figure, the line sum and the reconciliation residual are all present
    and all zero.

    PRD: "The gap between the two approaches is not swept under the rug but
    published as `rounding_residual_credit_hours`, which is `line_credit_hour_sum`
    minus `translated_credit_hours`, rounded half up to two decimals — the artifact
    the receiving institution must reconcile, stated explicitly rather than left for
    them to discover."

    Design: Difficulty/boundary_precision_check/empty_transcript_zero_lines
    """
    ctx = fx.base_chain(program_overrides={"units_per_credit_hour": 3.0})

    record = fx.create_transcript(ctx["student"]["id"], purpose="TRANSFER")
    A.assert_number_equals(record["translated_credit_hours"], 0.0,
                           "translated_credit_hours")
    A.assert_number_equals(record["line_credit_hour_sum"], 0.00,
                           "line_credit_hour_sum")
    A.assert_number_equals(record["rounding_residual_credit_hours"], 0.00,
                           "rounding_residual_credit_hours")

    student = fx.refresh_student(ctx["student"]["id"])
    A.assert_number_equals(student["cumulative_credit_equivalency"], 0.0,
                           "cumulative_credit_equivalency")
