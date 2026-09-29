"""Dual-variant arithmetic: scoring variants on an attempt, and the two
credit-hour translations that disagree on identical mastery data.
"""
from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import dimension_score, rubric_dimension

TWO_EQUAL_DIMENSIONS = [
    rubric_dimension("D1", 0.5000, 100, False),
    rubric_dimension("D2", 0.5000, 100, False),
]


def test_first_of_two_readers_yields_a_provisional_figure_that_awards_nothing():
    """A single arrived reader on a two-reader rubric publishes a provisional
    figure and moves no unit total.

    PRD: "When the blueprint requires two readers and only the first has
    arrived, the variant is `PROVISIONAL_SINGLE_READER`. The attempt stays in
    `UNDER_REVIEW`, `final_score_pct` is written as reader one's figure,
    `is_provisional_score` is set to true, and `scores_received_count` becomes 1
    — but no mastery outcome is recorded, no units are awarded, and no cascade
    fires."

    Design: Difficulty/dual_variant_calc/attempt_score_provisional_vs_final_two_readers
    """
    ctx = fx.two_reader_scenario(blueprint_dimensions=TWO_EQUAL_DIMENSIONS)

    first = fx.record_score(
        ctx["attempt"]["id"],
        ctx["evaluator_one"]["id"],
        [dimension_score("D1", 82), dimension_score("D2", 82)],
    )
    A.assert_number_equals(first["weighted_score_pct"], 82.00, "weighted_score_pct")

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    A.assert_number_equals(attempt["final_score_pct"], 82.00, "final_score_pct")
    assert attempt["is_provisional_score"] is True
    assert attempt["score_variant"] == "PROVISIONAL_SINGLE_READER"
    assert attempt["status"] == "UNDER_REVIEW"
    assert attempt["scores_received_count"] == 1

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 0
    assert student["mastered_competency_count"] == 0


def test_second_reader_replaces_the_provisional_figure_with_the_mean_and_awards_units():
    """Agreement between two readers overwrites the provisional figure with
    their mean and is the only variant that awards the competency's units.

    PRD: "A difference less than or equal to the tolerance is agreement, and the
    variant is `TWO_READER_MEAN`: add the two figures, divide by two, and round
    half up to two decimals."

    Design: Difficulty/dual_variant_calc/attempt_score_provisional_vs_final_two_readers
    """
    ctx = fx.two_reader_scenario(blueprint_dimensions=TWO_EQUAL_DIMENSIONS)

    fx.record_score(
        ctx["attempt"]["id"],
        ctx["evaluator_one"]["id"],
        [dimension_score("D1", 82), dimension_score("D2", 82)],
    )
    second = fx.record_score(
        ctx["attempt"]["id"],
        ctx["evaluator_two"]["id"],
        [dimension_score("D1", 84), dimension_score("D2", 84)],
    )
    A.assert_number_equals(second["weighted_score_pct"], 84.00, "weighted_score_pct")

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    A.assert_number_equals(attempt["final_score_pct"], 83.00, "final_score_pct")
    assert attempt["is_provisional_score"] is False
    assert attempt["score_variant"] == "TWO_READER_MEAN"
    assert attempt["status"] == "SCORED_MASTERED"
    A.assert_instant_equals(attempt["mastered_at_utc"], BASE_CLOCK_UTC, "mastered_at_utc")

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 4
    assert student["mastered_competency_count"] == 1
    A.assert_number_equals(
        student["cumulative_credit_equivalency"], 1.3, "cumulative_credit_equivalency"
    )


def _ten_units_in_one_term():
    """Ten mastered units inside a single active term: a four-unit competency and
    a six-unit competency, both resolved by one reader at 85.00."""
    fx.set_clock(BASE_CLOCK_UTC)
    program = fx.create_program(units_per_credit_hour=3.0)
    first = fx.create_competency(program["id"], code="IT-101", unit_value=4,
                                level="FOUNDATION")
    fx.create_blueprint(first, dimensions=TWO_EQUAL_DIMENSIONS,
                        required_evaluator_count=1)
    second = fx.create_competency(program["id"], code="IT-102",
                                  title="Systems Analysis", unit_value=6, level="CORE")
    fx.create_blueprint(second, dimensions=TWO_EQUAL_DIMENSIONS,
                        required_evaluator_count=1)
    program = fx.publish_program(program["id"])
    student = fx.activate_student(fx.create_student(program["id"])["id"])
    term = fx.activate_term(fx.create_term(student["id"])["id"])
    evaluator = fx.create_evaluator()
    for competency in (first, second):
        attempt = fx.open_attempt(student["id"], competency["id"])
        fx.submit_attempt(attempt["id"], student["id"],
                          artifact_hash="sha256:" + competency["code"])
        fx.record_score(attempt["id"], evaluator["id"],
                        [dimension_score("D1", 85), dimension_score("D2", 85)])
    return {"program": program, "student": student, "term": term,
            "first": first, "second": second}


def test_term_aid_equivalency_floors_the_ten_units_to_three_whole_credit_hours():
    """The aid variant divides the term's own units by the program's ratio and
    discards the remainder, so ten units at 3.0 units per credit hour certify
    three whole credit hours and not three and a third.

    PRD: "The **aid variant** governs `credit_equivalency_earned` on a
    subscription term. It divides that term's `units_mastered_in_term` by the
    program's `units_per_credit_hour` and takes the floor — discarding any
    fractional remainder — and it is evaluated strictly per term, never across
    terms."

    Design: Difficulty/dual_variant_calc/credit_equivalency_aid_floor_vs_transcript_round
    """
    ctx = _ten_units_in_one_term()

    term = fx.refresh_term(ctx["term"]["id"])
    assert term["units_mastered_in_term"] == 10
    assert term["credit_equivalency_earned"] == 3


def test_transcript_translation_rounds_the_same_ten_units_half_up_to_three_point_three():
    """The transcript variant rounds the summed units half up to one decimal, and
    publishes the gap against the summed per-line figures rather than hiding it.

    PRD: "The headline figure, `translated_credit_hours`, is computed from
    `total_mastered_units` divided by `units_per_credit_hour`, rounded half up to
    **one** decimal place."

    Design: Difficulty/dual_variant_calc/credit_equivalency_aid_floor_vs_transcript_round
    """
    ctx = _ten_units_in_one_term()

    record = fx.create_transcript(ctx["student"]["id"], purpose="TRANSFER")
    assert record["total_mastered_units"] == 10
    assert record["competency_line_count"] == 2
    A.assert_number_equals(record["translated_credit_hours"], 3.3,
                           "translated_credit_hours")
    A.assert_number_equals(record["line_credit_hour_sum"], 3.33, "line_credit_hour_sum")
    A.assert_number_equals(record["rounding_residual_credit_hours"], 0.03,
                           "rounding_residual_credit_hours")

    student = fx.refresh_student(ctx["student"]["id"])
    A.assert_number_equals(student["cumulative_credit_equivalency"], 3.3,
                           "cumulative_credit_equivalency")
