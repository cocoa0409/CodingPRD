"""The board's end-of-season report: volume tiers, the contingency reserve and
cost per participant."""

from test_helpers import (
    ADMIN,
    BULK_LATEX,
    assert_kg,
    assert_rate,
    read_cost_summary,
    setup_canon,
    validate_success,
)


def test_contingency_is_eight_percent_of_the_pre_contingency_subtotal(api):
    """PRD §3.9: "Seventh, `pre_contingency_cents` is `disposal_subtotal_cents` plus
    `mobilization_fee_cents` plus `staffing_cost_cents`, less `volume_rebate_cents`."
    PRD §3.9: "Eighth — and this is the step most likely to be misread —
    `contingency_cents` is eight percent of `pre_contingency_cents`, rounded half up to
    whole cents. The contingency reserve is described in the county's own budget
    documents as a percentage of total program cost, but the evaluation order pins the
    meaning: it is eight percent of the **pre-contingency** subtotal, never eight
    percent of a total that already includes it."
    PRD §3.9: "Ninth, `total_program_cost_cents` is `pre_contingency_cents` plus
    `contingency_cents`."

    Design: Difficulty/combinatorial_formula/program_cost_rollup_contingency_evaluation_order_mode_c
    """
    ctx = setup_canon(32, manifest={"manifest_tracking_number": "MAN-0003"})

    summary = read_cost_summary(ctx["program_id"])

    assert summary["disposal_subtotal_cents"] == 698
    assert summary["mobilization_fee_cents"] == 250000
    assert summary["volume_rebate_cents"] == 0
    assert summary["staffing_cost_cents"] == 50400
    assert summary["pre_contingency_cents"] == 301098
    assert summary["contingency_cents"] == 24088, "round_half_up(301098 * 0.08)"
    assert summary["total_program_cost_cents"] == 325186


def test_cost_per_participant_divides_the_total_by_the_completed_visits(api):
    """PRD §3.9: "Tenth, `participant_count` is the number of appointments in
    `COMPLETED` status across all of the program's events. Appointments that ended in
    `REFERRED_OUT`, `NO_SHOW`, `CANCELLED` or `EXPIRED` are not participants."
    PRD §3.9: "Working a small season through: one received manifest invoiced at 698
    cents carrying 4.5 kilograms, one event with 12.00 certified staff hours at 4200
    cents an hour, and one completed appointment."
    PRD §3.9: "The total is 325186, and with one participant the cost per participant
    is 325186."

    Design: Difficulty/combinatorial_formula/program_cost_rollup_contingency_evaluation_order_mode_c
    """
    ctx = setup_canon(32, manifest={"manifest_tracking_number": "MAN-0003"})

    response = api.get_cost_summary(ctx["program_id"], ADMIN)
    summary = validate_success(response, 200)

    assert summary["participant_count"] == 1
    assert summary["cost_per_participant_cents"] == 325186
    assert_kg(summary["received_tonnage_kg"], 4.5, "received_tonnage_kg")
    assert_kg(summary["accepted_tonnage_kg"], 4.5, "accepted_tonnage_kg")
    assert summary["event_count"] == 1


def test_two_thousand_kilograms_lands_in_the_second_volume_tier(api):
    """PRD §3.9: "Below two thousand kilograms the mobilisation fee is 250000 cents
    and there is no volume rebate. From two thousand kilograms up to but not including
    eight thousand, the mobilisation fee falls to 180000 cents and a three percent
    rebate applies. At eight thousand kilograms and above, the mobilisation fee falls
    again to 120000 cents and the rebate rises to six percent. The tier boundaries are
    inclusive at their lower edge."
    PRD §3.9: "Fifth, `volume_rebate_cents` is `disposal_subtotal_cents` multiplied by
    the tier's rebate percentage, with the fraction discarded."

    Design: Corner/calculations/mobilization_tier_boundary_at_two_thousand_kg
    """
    ctx = setup_canon(
        32,
        program={"eligible_jurisdiction_codes": ["CO-ARV"]},
        category=BULK_LATEX,
        appointment={"declared_total_kg": 2000.0, "vehicle_count": 2},
        line_weights=(2000.0,),
        container={"container_code": "TOTE-B1", "capacity_kg": 2500.0},
        manifest={"manifest_tracking_number": "MAN-2000"},
    )
    assert ctx["lines"][0]["estimated_disposal_cost_cents"] == 200000
    assert_rate(ctx["manifest"]["blended_rate_cents_per_kg"], 100.0)
    assert ctx["manifest"]["invoiced_disposal_cost_cents"] == 200000

    summary = read_cost_summary(ctx["program_id"])

    assert_kg(summary["received_tonnage_kg"], 2000.0, "received_tonnage_kg")
    assert summary["disposal_subtotal_cents"] == 200000
    assert summary["mobilization_fee_cents"] == 180000, "Tier two applies at exactly 2000 kg"
    assert summary["volume_rebate_cents"] == 6000
    assert summary["staffing_cost_cents"] == 50400
    assert summary["pre_contingency_cents"] == 424400
    assert summary["contingency_cents"] == 33952
    assert summary["total_program_cost_cents"] == 458352
    assert summary["participant_count"] == 1
    assert summary["cost_per_participant_cents"] == 458352
