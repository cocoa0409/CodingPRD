"""Dual-variant calculations: letter-of-intent thresholds and certificate money.

Both families compute two variants of the same quantity from identical stored
rows and let one of them govern.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_letter_of_intent,
    validate_error,
    validate_success,
)
from test_helpers.factories import letter_of_intent_payload
from test_helpers.fixtures import (
    ADMIN,
    seed_applicant,
    seed_health_service_area,
    seed_state_plan_formula,
    set_clock,
)
from test_helpers.test_users import make_applicant_headers

SECOND_CYCLE_CALENDAR = {
    "loi_deadline_at": "2026-10-01T00:00:00Z",
    "application_deadline_at": "2026-10-05T00:00:00Z",
    "comment_period_closes_at": "2026-10-10T00:00:00Z",
    "intervention_deadline_at": "2026-10-15T00:00:00Z",
    "completeness_deadline_at": "2026-10-20T00:00:00Z",
    "decision_deadline_at": "2026-11-30T00:00:00Z",
}

FIRST_CYCLE_CALENDAR = {
    "loi_deadline_at": "2026-08-10T00:00:00Z",
    "application_deadline_at": "2026-08-20T00:00:00Z",
    "comment_period_closes_at": "2026-08-25T00:00:00Z",
    "intervention_deadline_at": "2026-08-28T00:00:00Z",
    "completeness_deadline_at": "2026-09-05T00:00:00Z",
    "decision_deadline_at": "2026-09-30T00:00:00Z",
}


def _open_cycle(hsa_id, formula_id, calendar):
    payload = {
        "hsa_id": hsa_id,
        "formula_id": formula_id,
        "service_type": "ACUTE_CARE_BEDS",
    }
    payload.update(calendar)
    return validate_success(api_client.create_batching_cycle(payload, ADMIN), 201)


def _phase_one_world():
    """One planning area, one formula, one applicant, one open cycle."""
    set_clock("2026-08-01T00:00:00Z")
    hsa = seed_health_service_area()
    formula = seed_state_plan_formula()
    applicant = seed_applicant()
    cycle = _open_cycle(hsa["id"], formula["id"], FIRST_CYCLE_CALENDAR)
    return {"hsa": hsa, "formula": formula, "applicant": applicant, "cycle": cycle}


def _file_phase_one_letter(world):
    return validate_success(
        api_client.create_letter_of_intent(
            letter_of_intent_payload(
                world["applicant"]["id"],
                world["hsa"]["id"],
                world["cycle"]["id"],
                project_description="3-bed acute care addition, phase one",
                capital_cost_cents=300000000,
                bed_delta=3,
            ),
            make_applicant_headers(world["applicant"]["id"]),
        ),
        201,
    )


class TestLetterOfIntentThresholdVariants:
    def test_first_letter_below_both_thresholds_is_non_reviewable(self):
        """A first letter of 300000000 cents / 3 beds is judged on itself alone.

        PRD §3.3: "`project_basis_reviewable` is true when at least one of
        three tests passes: the letter's own `capital_cost_cents` is at least
        500000000 cents (five million dollars); or its own `bed_delta` is at
        least 10 beds; or its `service_type` is one of the three categories the
        state always reviews regardless of size — `OPEN_HEART_SURGERY`,
        `MRI_UNIT` or `NURSING_HOME_BEDS`."
        PRD §3.3: "`governing_review_basis` is `AGGREGATED_24_MONTH` when
        `prior_window_loi_count` is 1 or more, and `PROJECT_BASED` when it is
        0."
        PRD §3.3: "`review_determination` is then `REVIEWABLE` when the
        governing variant's flag is true, and `NON_REVIEWABLE` when it is
        false."

        Design: Difficulty/dual_variant_calc/loi_threshold_project_basis_vs_aggregated_same_row_data
        """
        world = _phase_one_world()

        loi_1 = _file_phase_one_letter(world)

        assert_letter_of_intent(loi_1)
        assert loi_1["prior_window_loi_count"] == 0
        assert loi_1["project_basis_reviewable"] is False
        assert loi_1["governing_review_basis"] == "PROJECT_BASED"
        assert loi_1["review_determination"] == "NON_REVIEWABLE"

    def test_second_letter_with_identical_row_data_becomes_reviewable(self):
        """The same-size project turns reviewable once a prior letter aggregates.

        PRD §3.3: "`prior_window_loi_count` is how many such letters there are.
        `aggregate_capital_cost_cents` is this letter's own `capital_cost_cents`
        plus the sum of the qualifying priors' `capital_cost_cents`, and
        `aggregate_bed_delta` is this letter's own `bed_delta` plus the sum of
        the priors' `bed_delta`."
        PRD §3.3: "Then `aggregated_basis_reviewable` is true when at least one
        of the same three tests passes against the aggregates:
        `aggregate_capital_cost_cents` is at least 500000000 cents, or
        `aggregate_bed_delta` is at least 10 beds, or the `service_type` is one
        of the three always-reviewable categories."
        PRD §3.3: "`governing_review_basis` is `AGGREGATED_24_MONTH` when
        `prior_window_loi_count` is 1 or more, and `PROJECT_BASED` when it is
        0."

        Design: Difficulty/dual_variant_calc/loi_threshold_project_basis_vs_aggregated_same_row_data
        """
        world = _phase_one_world()
        _file_phase_one_letter(world)
        second_cycle = _open_cycle(
            world["hsa"]["id"], world["formula"]["id"], SECOND_CYCLE_CALENDAR
        )
        set_clock("2026-09-15T00:00:00Z")

        loi_2 = validate_success(
            api_client.create_letter_of_intent(
                letter_of_intent_payload(
                    world["applicant"]["id"],
                    world["hsa"]["id"],
                    second_cycle["id"],
                    project_description="3-bed acute care addition, phase two",
                    capital_cost_cents=250000000,
                    bed_delta=3,
                ),
                make_applicant_headers(world["applicant"]["id"]),
            ),
            201,
        )

        assert loi_2["project_basis_reviewable"] is False
        assert loi_2["aggregated_basis_reviewable"] is True
        assert loi_2["prior_window_loi_count"] == 1
        assert loi_2["aggregate_capital_cost_cents"] == 550000000
        assert loi_2["aggregate_bed_delta"] == 6
        assert loi_2["governing_review_basis"] == "AGGREGATED_24_MONTH"
        assert loi_2["review_determination"] == "REVIEWABLE"

    def test_non_reviewable_letter_cannot_be_converted(self):
        """The project-basis verdict is load-bearing: conversion is refused.

        PRD §3.4: "A letter whose `review_determination` is `NON_REVIEWABLE`
        cannot become an application — the project does not need a certificate
        — and the attempt yields `ERR_LOI_NOT_REVIEWABLE`."

        Design: Difficulty/dual_variant_calc/loi_threshold_project_basis_vs_aggregated_same_row_data
        """
        world = _phase_one_world()
        loi_1 = _file_phase_one_letter(world)
        assert loi_1["review_determination"] == "NON_REVIEWABLE"

        response = api_client.create_application(
            {
                "loi_id": loi_1["id"],
                "requested_bed_count": 3,
                "projected_capital_cost_cents": 300000000,
                "narrative": "phase one narrative",
            },
            make_applicant_headers(world["applicant"]["id"]),
        )

        validate_error(response, ApiErrorId.ERR_LOI_NOT_REVIEWABLE)
