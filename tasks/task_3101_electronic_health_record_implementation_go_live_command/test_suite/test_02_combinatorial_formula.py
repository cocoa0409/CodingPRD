"""Combinatorial formulas: several inputs combining under a pinned order.

Covers the tiered customization-risk score, the round-each-line-then-sum charge
capture order, and the multiplicative command-center SLA.
"""

import pytest

from test_helpers import (
    api_client,
    validate_success,
    assert_cost_precision,
    create_build_item_payload,
    create_patient_order_payload,
    create_staffing_shift_payload,
    get_success_data,
    setup_program_and_facility,
    setup_program_facility_department,
    setup_credentialed_staff,
    BUILD_ANALYST,
    CONVERSION,
    ANALYST,
    COMMAND_CENTER,
    THRESHOLDS,
)


# ===========================================================================
# r2_customization_risk_tiered_marginal_allocation_at_unit_cap
# ===========================================================================

def test_completing_build_scores_twelve_custom_fields_at_ninety_two(api, build_analyst_headers):
    """PRD §3.3: "each of the first 4 units is worth 2 points, each of units 5
    through 8 is worth 3 points, and each of units 9 through 12 is worth 5
    points. For example, 3 units earn 6 points, 8 units earn 20 points (4 at 2
    plus 4 at 3), and 12 units earn 40 points (4 at 2, 4 at 3, 4 at 5)."
    PRD §3.3: "That tier total is then multiplied by a classification weight
    taken from the build classification: 1.0 for `FOUNDATION_ADOPTED`, 1.5 for
    `FOUNDATION_ADAPTED` and 2.0 for `LOCAL_CUSTOM`. The weighted result is then
    multiplied by a depth multiplier of 1 plus 0.15 for each unit of
    `customization_depth` beyond the first".

    Twelve distinct fields under LOCAL_CUSTOM at depth 2 is
    40 * 2.0 * 1.15 = 92.00, rounded once at the very end.

    Design: Difficulty/combinatorial_formula/r2_customization_risk_tiered_marginal_allocation_at_unit_cap
    """
    prog, fac, dept = setup_program_facility_department()
    item = get_success_data(api_client.create_build_item(
        dept["id"],
        create_build_item_payload(
            application_code="LAB", build_classification="FOUNDATION_ADAPTED",
            customization_depth=2,
            local_custom_fields=[f"CF{n:02d}" for n in range(1, 13)],
        ),
        build_analyst_headers,
    ))
    get_success_data(api_client.start_build_item(item["id"], build_analyst_headers))

    completed = validate_success(api.complete_build_item(item["id"], build_analyst_headers), 200)
    assert completed["status"] == "BUILD_COMPLETE"
    assert completed["customization_risk_points"] == pytest.approx(69.00, abs=0.01), (
        f"12 units in marginal tiers (40) x FOUNDATION_ADAPTED weight (1.5) x "
        f"depth-2 multiplier (1.15) = 69.00; got {completed['customization_risk_points']}"
    )
    assert_cost_precision(completed["customization_risk_points"])


def test_customization_risk_applies_marginal_tiers_not_a_flat_top_rate(api, build_analyst_headers):
    """PRD §3.3: "The starting quantity is the number of *distinct* field names
    in `local_custom_fields` — a list naming the same field twice counts once.
    That count is then capped at 12 billable units; units beyond the twelfth are
    not counted at all."
    PRD §3.3: "The product is rounded half-up to two decimal places exactly
    once, at the very end; no intermediate tier, weight or multiplier is rounded
    on its way through."

    Charging every unit the top rate would give 12 * 5 * 2.0 * 1.15 = 138.00;
    the marginal ladder gives 40 * 2.0 * 1.15 = 92.00, so the tier sum recovered
    from the published score is exactly 40.

    Design: Difficulty/combinatorial_formula/r2_customization_risk_tiered_marginal_allocation_at_unit_cap
    """
    prog, fac, dept = setup_program_facility_department()
    item = get_success_data(api_client.create_build_item(
        dept["id"],
        create_build_item_payload(
            application_code="LAB", build_classification="FOUNDATION_ADAPTED",
            customization_depth=2,
            local_custom_fields=[f"CF{n:02d}" for n in range(1, 13)],
        ),
        build_analyst_headers,
    ))
    get_success_data(api_client.start_build_item(item["id"], build_analyst_headers))
    completed = validate_success(api.complete_build_item(item["id"], build_analyst_headers), 200)

    risk = completed["customization_risk_points"]
    assert risk != pytest.approx(103.50, abs=0.01), "a flat top-rate reading is wrong"
    # Recover the pre-weight, pre-depth tier sum and pin it to the marginal ladder.
    tier_sum = risk / (1.5 * 1.15)
    assert tier_sum == pytest.approx(40.00, abs=0.01), (
        f"the marginal tier ladder for 12 units is 4*2 + 4*3 + 4*5 = 40; got {tier_sum}"
    )


# ===========================================================================
# r2_charge_capture_per_line_rounding_order
# ===========================================================================

def test_imaging_order_charge_is_summed_from_individually_rounded_lines(api, conversion_headers):
    """PRD §3.7: "an imaging order carries a technology line of 12.5 percent and
    a contrast line of 7.5 percent".
    PRD §3.7: "Each line is rounded half-up to two decimal places *first*, and
    the rounded lines are then summed; that order is pinned and must not be
    inverted. The sum is published as the provisional charge to two decimals."

    For 12345 cents the three rounded lines are 12345.00, 1543.13 and 925.88, so
    the published provisional charge is 14814.01.

    Design: Difficulty/combinatorial_formula/r2_charge_capture_per_line_rounding_order
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-4002", order_type="IMAGING",
            encounter_utc="2026-08-28T00:00:00Z", legacy_charge_cents=12345,
        ),
        conversion_headers,
    ))

    assert order["provisional_charge_cents"] == pytest.approx(14814.01, abs=0.01), (
        f"12345.00 + 1543.13 + 925.88 = 14814.01; got {order['provisional_charge_cents']}"
    )
    assert_cost_precision(order["provisional_charge_cents"])


def test_imaging_order_charge_is_neither_the_unrounded_sum_nor_a_truncation(api, conversion_headers):
    """PRD §3.7: "Each line is rounded half-up to two decimal places *first*, and
    the rounded lines are then summed; that order is pinned and must not be
    inverted."
    PRD §3.7: "Every order carries a base line equal to the full
    `legacy_charge_cents`."

    Rounding the pre-rounded sum instead yields 14814.00 and truncating each line
    yields 14813.00; the pinned order yields neither.

    Design: Difficulty/combinatorial_formula/r2_charge_capture_per_line_rounding_order
    """
    prog, fac = setup_program_and_facility()
    order = get_success_data(api_client.create_patient_order(
        fac["id"],
        create_patient_order_payload(
            patient_mrn="MRN-4002", order_type="IMAGING",
            encounter_utc="2026-08-28T00:00:00Z", legacy_charge_cents=12345,
        ),
        conversion_headers,
    ))

    provisional = order["provisional_charge_cents"]
    assert provisional != pytest.approx(14814.00, abs=0.01), (
        "summing first and rounding once is the inverted order"
    )
    assert provisional != pytest.approx(14813.00, abs=0.01), (
        "truncating each line is not half-up rounding"
    )
    # The base line is the full legacy charge, echoed back untouched.
    assert order["legacy_charge_cents"] == 12345
    base_and_tech_and_contrast = 12345.00 + 1543.13 + 925.88
    assert provisional == pytest.approx(base_and_tech_and_contrast, abs=0.01)


# ===========================================================================
# r2_command_center_sla_three_input_nonlinear_interaction
# ===========================================================================

def test_uncovered_ticket_pays_the_coverage_penalty_multiplicatively(api, command_center_headers):
    """PRD §3.10: "A severity weight scales the base 60-minute target: 0.25 for
    `SEV1`, 0.50 for `SEV2`, 1.00 for `SEV3` and 2.00 for `SEV4`".
    PRD §3.10: "A coverage modifier halves the target to 0.50 when there is no
    at-the-elbow cover available — that is, when the ticket's facility has no
    shift in `SCHEDULED` or `ACTIVE` status with `support_role` `AT_THE_ELBOW`
    whose `end_utc` is still ahead of the clock — and is otherwise 1.00."
    PRD §3.10: "The four factors multiply the 60-minute base, and the product is
    published as `resolution_sla_minutes` rounded half-up to a whole number of
    minutes."

    60 * 1.00 (SEV3) * 1.10 (radiology) * 0.50 (uncovered) = 33.

    Design: Difficulty/combinatorial_formula/r2_command_center_sla_three_input_nonlinear_interaction
    """
    prog, fac = setup_program_and_facility()
    ticket = validate_success(api.create_ticket(
        {"facility_id": fac["id"], "target_ref": fac["id"], "severity": "SEV3",
         "at_the_elbow_zone": "RADIOLOGY"},
        command_center_headers,
    ), 201)

    assert ticket["resolution_sla_minutes"] == 33, (
        f"60 * 1.00 * 1.10 * 0.50 = 33; got {ticket['resolution_sla_minutes']}"
    )
    assert ticket["severity"] == "SEV3"
    assert ticket["triage_state"] == "REPORTED"


def test_covering_shift_removes_the_halving_and_the_target_doubles(api, command_center_headers):
    """PRD §3.10: "A coverage modifier halves the target to 0.50 when there is no
    at-the-elbow cover available — that is, when the ticket's facility has no
    shift in `SCHEDULED` or `ACTIVE` status with `support_role` `AT_THE_ELBOW`
    whose `end_utc` is still ahead of the clock — and is otherwise 1.00."
    PRD §3.10: "A shift may not overlap another shift of the same staff member,
    and two `AT_THE_ELBOW` shifts at the same facility may not overlap either".

    With an at-the-elbow shift on file whose window is still ahead of the clock,
    the same SEV3/radiology input reads 60 * 1.00 * 1.10 * 1.00 = 66.

    Design: Difficulty/combinatorial_formula/r2_command_center_sla_three_input_nonlinear_interaction
    """
    ctx = setup_credentialed_staff()
    get_success_data(api_client.create_shift(
        create_staffing_shift_payload(
            ctx["staff"]["id"], ctx["fac"]["id"], support_role="AT_THE_ELBOW",
            start_utc="2026-09-02T06:00:00Z", end_utc="2026-09-02T14:00:00Z",
        ),
        command_center_headers,
    ))

    ticket = validate_success(api.create_ticket(
        {"facility_id": ctx["fac"]["id"], "target_ref": ctx["fac"]["id"],
         "severity": "SEV3", "at_the_elbow_zone": "RADIOLOGY"},
        command_center_headers,
    ), 201)

    assert ticket["resolution_sla_minutes"] == 66, (
        f"with at-the-elbow cover the coverage factor is 1.00, so 60 * 1.00 * 1.10 "
        f"= 66; got {ticket['resolution_sla_minutes']}"
    )