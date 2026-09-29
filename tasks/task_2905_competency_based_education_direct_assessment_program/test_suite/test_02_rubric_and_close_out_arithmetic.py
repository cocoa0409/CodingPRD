"""Multi-input formulas whose evaluation order is pinned: the weighted rubric
score, and the term close-out refund / aid-return chain.
"""
from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.constants import BASE_CLOCK_UTC
from test_helpers.factories import dimension_score, rubric_dimension

SEVENTHS_RUBRIC = [
    rubric_dimension("D1", 0.3400, 7, True),
    rubric_dimension("D2", 0.3300, 7, False),
    rubric_dimension("D3", 0.3300, 7, False),
]

CLOSE_CLOCK_UTC = "2026-10-01T00:00:00.000Z"


def _three_sevenths_attempt():
    """A submitted attempt bound to a three-dimension rubric whose weights and
    seven-point ceilings make sum-then-round and round-then-sum disagree."""
    return fx.attempt_under_review(
        competency_overrides={"code": "IT-201", "title": "Secure Coding Review",
                              "unit_value": 4, "level": "CORE"},
        blueprint_dimensions=SEVENTHS_RUBRIC,
        blueprint_overrides={"passing_rule": "WEIGHTED_PLUS_ALL_CRITICAL",
                             "required_evaluator_count": 1},
    )


def test_weighted_score_accumulates_at_full_precision_and_rounds_exactly_once():
    """Scores of 5, 5 and 6 out of 7 weight to 76.14 when the products are
    accumulated unrounded, and to 76.15 when each contribution is rounded first.
    Only the single final rounding is the contract.

    PRD: "Summing first and rounding once at the end is the normative rule.
    Rounding each dimension's contribution to two decimals before adding them is
    the wrong rule: it drifts by up to one hundredth of a percentage point per
    dimension and will disagree with the expected result."

    Design: Difficulty/combinatorial_formula/rubric_sum_then_round_dimension_order
    """
    ctx = _three_sevenths_attempt()

    score = fx.record_score(
        ctx["attempt"]["id"],
        ctx["evaluator"]["id"],
        [dimension_score("D1", 5), dimension_score("D2", 5), dimension_score("D3", 6)],
    )
    A.assert_number_equals(score["weighted_score_pct"], 76.14, "weighted_score_pct")
    assert float(score["weighted_score_pct"]) != 76.15
    assert score["reader_ordinal"] == 1
    assert score["critical_fail"] is False


def test_the_seventy_six_point_one_four_resolution_falls_short_and_publishes_a_cooloff():
    """76.14 is below the default 80.00 threshold, so the attempt resolves as not
    mastered, publishes a cool-off two days out and moves no unit total.

    PRD: "A non-mastering resolution sets `status` to `SCORED_NOT_MASTERED` with
    `scored_at_utc` at the logical clock, leaves `mastered_at_utc` null, publishes
    `cooloff_until_utc` as the logical clock advanced by `attempt_cooloff_hours`,
    and leaves every unit total untouched."

    Design: Difficulty/combinatorial_formula/rubric_sum_then_round_dimension_order
    """
    ctx = _three_sevenths_attempt()

    fx.record_score(
        ctx["attempt"]["id"],
        ctx["evaluator"]["id"],
        [dimension_score("D1", 5), dimension_score("D2", 5), dimension_score("D3", 6)],
    )

    attempt = fx.refresh_attempt(ctx["attempt"]["id"])
    A.assert_number_equals(attempt["final_score_pct"], 76.14, "final_score_pct")
    assert attempt["score_variant"] == "SINGLE_READER_FINAL"
    assert attempt["status"] == "SCORED_NOT_MASTERED"
    assert attempt["mastered_at_utc"] is None
    A.assert_instant_equals(attempt["cooloff_until_utc"],
                            "2026-09-03T00:00:00.000Z", "cooloff_until_utc")

    student = fx.refresh_student(ctx["student"]["id"])
    assert student["mastered_unit_total"] == 0


def _lapsed_term_with_released_aid():
    """A 91-day term with 375000 cents of tuition and 200000 cents of released
    aid, closed LAPSED after 30 attended days."""
    ctx = fx.mastery_then_aid_scenario(score=90)
    ctx["award"] = fx.disburse_aid(ctx["award"]["id"])
    fx.set_clock(CLOSE_CLOCK_UTC)
    ctx["closed_term"] = fx.close_term(ctx["term"]["id"], "LAPSED", CLOSE_CLOCK_UTC)
    return ctx


def test_close_out_computes_the_refund_from_gross_tuition_and_the_net_charge_after_it():
    """Thirty of ninety-one days earns 0.3297, and the refund is taken from the
    gross tuition figure while the net charge is what is left of it.

    PRD: "Step five computes `institutional_refund_cents` as `tuition_cents`
    multiplied by one minus `earned_pct`, rounded half up to the nearest whole
    cent — **computed from the gross tuition figure**."

    Design: Difficulty/combinatorial_formula/term_close_refund_evaluation_order
    """
    ctx = _lapsed_term_with_released_aid()

    term = ctx["closed_term"]
    assert term["status"] == "LAPSED"
    assert term["term_days"] == 91
    assert term["attended_days"] == 30
    A.assert_number_equals(term["earned_pct"], 0.3297, "earned_pct")
    A.assert_cents(term["institutional_refund_cents"], 251363,
                   "institutional_refund_cents")
    A.assert_cents(term["net_institutional_charge_cents"], 123637,
                   "net_institutional_charge_cents")


def test_unearned_aid_comes_from_gross_disbursed_money_and_the_split_is_exact():
    """The unearned figure is 200000 x 0.6703 = 134060, taken from the money that
    actually left rather than from the 123637 net charge, and the school's share
    is the smaller of that figure and the net charge scaled by the same factor.

    PRD: "Step eight computes `school_return_share_cents` as the **smaller** of
    `unearned_aid_cents` and the net institutional charge multiplied by one minus
    `earned_pct` rounded half up to the nearest cent, and then computes
    `student_return_share_cents` as `unearned_aid_cents` minus
    `school_return_share_cents`."

    Design: Difficulty/combinatorial_formula/term_close_refund_evaluation_order
    """
    ctx = _lapsed_term_with_released_aid()

    award = fx.return_aid(ctx["award"]["id"])
    assert award["status"] == "RETURNED"
    A.assert_cents(award["unearned_aid_cents"], 134060, "unearned_aid_cents")
    A.assert_cents(award["school_return_share_cents"], 82874,
                   "school_return_share_cents")
    A.assert_cents(award["student_return_share_cents"], 51186,
                   "student_return_share_cents")
    A.assert_cents(award["returned_amount_cents"], 82874, "returned_amount_cents")
    A.assert_cents(award["retained_amount_cents"], 117126, "retained_amount_cents")
    A.assert_return_split_is_exact(award)

    student = fx.refresh_student(ctx["student"]["id"])
    A.assert_cents(student["aid_retained_total_cents"], 117126,
                   "aid_retained_total_cents")
    A.assert_cents(student["aid_returned_total_cents"], 82874,
                   "aid_returned_total_cents")
