"""Nested-rounding scoring: the satisfaction composite and the cohort point award.

Both formulas pin an evaluation order that changes the stored value when it is
read the other way round (PRD §3.2, §3.6).
"""
from test_helpers import (
    LND_STATEMENT_SEQUENCE,
    assert_satisfaction_record,
    create_and_pay_lnd_statement,
    create_cohort,
    create_enrolled_student,
    make_partner_headers,
    read_cohort,
    read_partner,
    read_student,
    satisfaction_payload,
    setup_active_placement,
    setup_student_at_phase,
    staff_headers,
    validate_success,
)


def test_satisfaction_composite_rounds_each_weighted_term_before_summing(api):
    """PRD §3.6: "The `composite_score` is built in a fixed order that rounds each
    weighted term before summing."
    PRD §3.6: "The supervisor term is `supervisor_rating` multiplied by 0.50, rounded
    half up to 2 decimal places."
    PRD §3.6: "Rounding each term before summing is mandatory — summing the unrounded
    terms first produces different values."

    Ratings of 4.25 / 3.15 / 2.05 round to 2.13 + 0.95 + 0.41 = 3.49 and store a
    composite of 3.36; summing the unrounded terms first would store 3.35.

    Design: Difficulty/combinatorial_formula/satisfaction_composite_per_term_rounding
    """
    scenario = setup_active_placement()

    data = validate_success(
        api.submit_satisfaction_record(
            satisfaction_payload(scenario.placement["id"]),
            make_partner_headers(scenario.partner["id"]),
        ),
        201,
    )

    assert float(data["composite_score"]) == 3.36, data["composite_score"]
    assert_satisfaction_record(data)


def test_satisfaction_composite_is_mirrored_onto_placement_and_partner(api):
    """PRD §3.6: "The resulting composite is mirrored in two places: the placement's
    `satisfaction_score` is set to it, and the partner's `placement_quality_score` is
    set to it"
    PRD §3.6: "The composite is then that weighted total multiplied by 5, divided by
    4, minus 1, rounded half up to 2 decimal places, and finally clamped into the
    range 0.00 to 5.00."

    Design: Difficulty/combinatorial_formula/satisfaction_composite_per_term_rounding
    """
    scenario = setup_active_placement()

    validate_success(
        api.submit_satisfaction_record(
            satisfaction_payload(scenario.placement["id"]),
            make_partner_headers(scenario.partner["id"]),
        ),
        201,
    )

    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    partner = read_partner(scenario.partner["id"])
    assert float(placement["satisfaction_score"]) == 3.36, placement["satisfaction_score"]
    assert float(partner["placement_quality_score"]) == 3.36, partner["placement_quality_score"]


def test_cohort_award_reads_the_level_from_the_raw_paid_point_total(api):
    """PRD §3.2: "The cohort's level is read from that raw total: level 3 when
    `total_points` is at least 20, otherwise level 2 when `total_points` is at least
    10, otherwise level 1."
    PRD §3.2: "The final `awarded_points` is that base award plus the level multiplied
    by 100 bonus points."

    Thirteen paid points read level 2, so the award is round(13/3) + 2*100 = 204.

    Design: Difficulty/combinatorial_formula/cohort_contract_points_circular_evaluation_order
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    setup_student_at_phase(student, cohort["id"], statements=2)

    third = LND_STATEMENT_SEQUENCE[2]
    create_and_pay_lnd_statement(
        student["id"],
        period_start=third[0], period_end=third[1],
        hours_attended=third[2], hours_expected=third[3],
        behavior_incidents=third[4],
    )

    assert read_cohort(cohort["id"])["awarded_points"] == 204, read_cohort(cohort["id"])
    assert read_student(student["id"])["lifetime_contract_points"] == 13


def test_cohort_award_stood_at_level_one_before_the_tier_was_crossed(api):
    """PRD §3.2: "The base award is `total_points` divided by 3, rounded half up to a
    whole number of points."
    PRD §3.2: "The recomputation sums `contract_points_earned` over the stipend
    statements at status `PAID` whose `phase` is `L_AND_D` and whose student is
    enrolled in this cohort, producing a raw `total_points`."

    Eight paid points read level 1, so the award stands at round(8/3) + 100 = 103
    and the ten-point tier boundary is what the third payment crosses.

    Design: Difficulty/combinatorial_formula/cohort_contract_points_circular_evaluation_order
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    setup_student_at_phase(student, cohort["id"], statements=2)

    assert read_cohort(cohort["id"])["awarded_points"] == 103, (
        read_cohort(cohort["id"])["awarded_points"]
    )
    assert read_student(student["id"])["lifetime_contract_points"] == 8
