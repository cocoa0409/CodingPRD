"""Construction uplift on a readiness review, and the interval-rollover shortfall
computation for a usage-based commitment."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_account,
    create_configuration,
    create_review,
    create_training_record,
    draft_agreement,
    drive_account_to_readiness,
    get_agreement,
    month_close,
    set_clock,
    submit_agreement,
    validate_success,
)


def _uplift_scenario():
    """Account plus a DA_V2 catalog entry whose minimums are 780 x 700 x 320 x 280."""
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(account_name="Alder Point Surgical", idn_group_code="IDN-ALDER",
                             region_code="EAST", placement_cap=4,
                             maximum_procedure_commitment=20)
    config = create_configuration(model_code="DA_V2", base_placement_fee_cents=6000000,
                                  max_instrument_lives=12, integration_tier=2,
                                  min_operating_room_length_cm=780,
                                  min_operating_room_width_cm=700,
                                  min_table_throw_radius_cm=320,
                                  min_ceiling_clearance_cm=280)
    return account, config


def test_construction_uplift_escalates_the_second_unit_beyond_the_first(api):
    """PRD §3.1.1: "If there are no uplift units, the `construction_uplift_fee_cents` is
    zero. Otherwise the fee is 304800 cents for each uplift unit, plus a further 76200 cents
    for each unit beyond the first, so the second unit and every unit after it costs more
    than the first: two units cost 685800 cents rather than 609600."

    Design: Difficulty/combinatorial_formula/construction_uplift_nested_max_rounding_order
    """
    account, config = _uplift_scenario()

    # The clear OR length (776) and width (698) each fall below their configuration
    # minimum, so both count as uplift units: 2 x 304800 + 1 x 76200 = 685800.
    review = create_review(account["id"], config["id"],
                           operating_room_length_cm=776, operating_room_width_cm=698,
                           table_throw_radius_cm=400, ceiling_clearance_cm=300)

    assert review["construction_uplift_fee_cents"] == 685800, (
        "two uplift units escalate the second unit: 685800, not the flat 609600"
    )


def test_construction_uplift_of_one_unit_quotes_the_base_amount(api):
    """PRD §3.1.1: "One uplift unit therefore quotes 304800 cents".

    Design: Difficulty/combinatorial_formula/construction_uplift_nested_max_rounding_order
    """
    account, config = _uplift_scenario()

    # Only the clear OR length misses its minimum; the other three clear it.
    review = create_review(account["id"], config["id"],
                           operating_room_length_cm=770, operating_room_width_cm=700,
                           table_throw_radius_cm=320, ceiling_clearance_cm=280)

    assert review["construction_uplift_fee_cents"] == 304800


def _usage_based_rollover_scenario():
    """A usage-based agreement committing to 12 procedures per interval, nothing delivered."""
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(account_name="Odak Regional", idn_group_code="IDN-ODAK",
                             region_code="MIDWEST", placement_cap=6,
                             maximum_procedure_commitment=30)
    config = create_configuration(model_code="DA_V1", base_placement_fee_cents=4800000,
                                  max_instrument_lives=10, integration_tier=1)
    review = create_review(account["id"], config["id"], verdict="PASSED")
    create_training_record(account["id"])
    account = drive_account_to_readiness(account)
    agreement = draft_agreement(
        account["id"], config["id"], review["id"],
        arrangement_type="USAGE_BASED", base_monthly_fee_cents=0,
        minimum_procedures_per_cycle=12, interval_months=1,
        placement_fee_cents=1500000, usage_rate_basis_points=400)
    agreement = submit_agreement(agreement)
    accepted = validate_success(api_client.accept_agreement(
        agreement["id"],
        {"expected_agreement_version": agreement["version"],
         "expected_hospital_account_version": account["version"]},
        TEST_USERS["hospital_procurement_officer_headers"]), 200)
    return account, accepted


def _round_half_up(numerator: int, denominator: int) -> int:
    return (numerator + denominator // 2) // denominator


def test_rollover_charges_the_shortfall_beyond_the_two_procedure_grace(api):
    """PRD §2.12: "First the shortfall is the committed minimum minus the delivered count,
    floored at 0. If the agreement's shortfall has been waived for the interval, the fee is
    0. Otherwise, if the shortfall is 0 the fee is 0. Otherwise, if the shortfall is 2 or
    fewer procedures the fee is 0 as well — the grace band is inclusive. Only beyond that
    does a fee accrue: the fee is the shortfall beyond the grace of 2, multiplied by the
    agreement's `placement_fee_cents`, multiplied by a shortfall rate of 200 basis points,
    and the product is divided by 10000 and rounded half-up to a whole number of cents."

    PRD §2.12: "The shortfall itself is recorded as `shortfall_procedures`, the fee as
    `last_shortfall_fee_cents`."

    Design: Difficulty/combinatorial_formula/shortfall_compliance_tier_escalation_remainder_ladder
    """
    account, agreement = _usage_based_rollover_scenario()

    month_close("2026-10-01T00:00:00Z")
    closed = get_agreement(agreement["id"])

    assert closed["shortfall_procedures"] == 12, (
        "no procedures were delivered against a commitment of 12"
    )
    chargeable = closed["shortfall_procedures"] - 2
    expected_fee = _round_half_up(
        chargeable * closed["placement_fee_cents"] * 200, 10000)
    assert closed["last_shortfall_fee_cents"] == expected_fee, (
        "the fee is the shortfall beyond the inclusive 2-procedure grace, at 2 percent of "
        "the agreement's placement fee"
    )


def test_rollover_never_reports_meets_commitment_while_a_shortfall_stands(api):
    """PRD §2.12: "`MEETS_COMMITMENT` applies when the current interval's shortfall is 0 or
    has been waived."

    Design: Difficulty/combinatorial_formula/shortfall_compliance_tier_escalation_remainder_ladder
    """
    account, agreement = _usage_based_rollover_scenario()

    month_close("2026-10-01T00:00:00Z")
    closed = get_agreement(agreement["id"])

    assert closed["shortfall_procedures"] > 0
    assert closed["compliance_status"] != "MEETS_COMMITMENT", (
        "an interval with an unwaived shortfall cannot report MEETS_COMMITMENT"
    )
    assert closed["compliance_status"] in [
        "SHORTFALL_WARNING", "SHORTFALL_CHARGEABLE", "NON_COMPLIANT", "REMEDIATION_REQUIRED",
    ]