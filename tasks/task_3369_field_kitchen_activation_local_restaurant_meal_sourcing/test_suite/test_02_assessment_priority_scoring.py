"""Rapid needs assessments and the feeding-priority score."""
from test_helpers import (
    create_assessment,
    create_incident,
    TEST_USERS,
)

COORD = TEST_USERS["field_coordinator_headers"]


def test_rapid_posture_scores_identical_field_data_at_eighty_three(api):
    """PRD §3.1: "Under `RAPID`, the default posture for the first 72 hours of
    an activation, the infrastructure raw penalty is used at full weight and
    the partner raw penalty is used at single weight."
    PRD §3.1: "The need component measures how many meals each affected person
    requires: it is 0 when `population_affected` is 0, and otherwise it is the
    estimated daily meal need multiplied by 100 and divided by the affected
    population, rounded half up, capped at 100."

    Design: Difficulty/dual_variant_calc/assessment_priority_rapid_vs_durable_on_identical_field_data
    """
    incident = create_incident()
    rapid = create_assessment(
        incident["id"],
        population_affected=40000,
        estimated_daily_meal_need=9000,
        access_constraint="LIMITED",
        water_available=False,
        power_available=True,
        partner_kitchens_identified=2,
        assessment_mode="RAPID",
    )
    # need 9000*100/40000 = 22.5 -> 23; access LIMITED 25; infra 20; partner 15
    assert rapid["feeding_priority_score"] == 83
    assert rapid["assessment_mode"] == "RAPID"


def test_durable_posture_scores_the_same_field_data_at_eighty_eight(api):
    """PRD §3.1: "Under `DURABLE`, the posture adopted once the response shifts
    toward local capacity, the infrastructure penalty is halved with half-up
    rounding and the partner penalty is doubled and then capped at 40."
    PRD §3.1: "The two postures therefore diverge whenever the raw
    infrastructure penalty differs from twice the raw partner penalty."

    Design: Difficulty/dual_variant_calc/assessment_priority_rapid_vs_durable_on_identical_field_data
    """
    incident = create_incident()
    durable = create_assessment(
        incident["id"],
        population_affected=40000,
        estimated_daily_meal_need=9000,
        access_constraint="LIMITED",
        water_available=False,
        power_available=True,
        partner_kitchens_identified=2,
        assessment_mode="DURABLE",
    )
    # need 23; access 25; infra 20/2 = 10; partner min(40, 2*15) = 30
    assert durable["feeding_priority_score"] == 88

    rapid = create_assessment(
        incident["id"],
        population_affected=40000,
        estimated_daily_meal_need=9000,
        access_constraint="LIMITED",
        water_available=False,
        power_available=True,
        partner_kitchens_identified=2,
        assessment_mode="RAPID",
    )
    assert rapid["feeding_priority_score"] != durable["feeding_priority_score"]
    assert rapid["feeding_priority_score"] == 83
