"""Numeric rule precision: the incident resolution grace band, the instrument-lives floor
and reset, and the inclusive shortfall grace."""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_case,
    create_incident_payload,
    get_agreement,
    get_success_data,
    month_close,
    set_clock,
    setup_commissioned_system,
    setup_system_at_instrument_lives,
    setup_usage_based_system,
    validate_success,
)


def test_incident_filed_against_a_comprehensive_system_is_minor_with_a_six_hour_due(api):
    """PRD §2.9: "`MINOR` otherwise. The `response_due_at_utc` is the incident start instant
    advanced by the `response_time_commitment_hours` of the active service contract."
    PRD §2.8: "The resulting commitment is 24 hours for `COMPREHENSIVE`, 12 for `STANDARD`,
    18 for `LIMITED` and 24 for `PARTS_ONLY` once the tier index is applied directly."

    Design: Corner/calculations/incident_resolution_penalty_grace_band_is_inclusive_at_due
    """
    ctx = setup_commissioned_system()
    assert ctx.contract["coverage_tier"] == "COMPREHENSIVE"
    assert ctx.contract["response_time_commitment_hours"] == 24

    incident = validate_success(api_client.create_incident(
        create_incident_payload(ctx.system["id"],
                                incident_started_at="2026-09-05T00:00:00Z"),
        TEST_USERS["service_engineer_headers"]), 201)

    assert incident["incident_severity"] == "MINOR", (
        "the system is in service and the account posture is ungated"
    )
    assert incident["response_due_at_utc"] == "2026-09-06T00:00:00.000Z"
    assert incident["request_status"] == "OPEN"
    assert incident["resolved_at_utc"] is None


def test_resolving_at_the_due_instant_scores_no_penalty(api):
    """PRD §2.9: "A resolution at or before `response_due_at_utc` scores zero."

    Design: Corner/calculations/incident_resolution_penalty_grace_band_is_inclusive_at_due
    """
    ctx = setup_commissioned_system()
    incident = create_incident_on(ctx, "2026-09-05T00:00:00Z")
    set_clock(incident["response_due_at_utc"])

    resolved = validate_success(api_client.resolve_incident(
        incident["id"],
        {"resolution_notes": "Resolved exactly at the commitment instant.",
         "expected_incident_version": incident["version"]},
        TEST_USERS["service_engineer_headers"]), 200)

    assert resolved["request_status"] == "RESOLVED"
    account = get_success_data(api_client.get_account(
        ctx.account["id"], TEST_USERS["platform_admin_headers"]))
    assert account.get("penalty_balance_points", 0) == 0, (
        "the grace boundary is closed on the left, so the due instant itself is free"
    )


def test_instrument_lives_floor_at_zero_and_reset_restores_the_full_count(api):
    """PRD §2.10: "The accumulator is floored at 0 and never goes negative. Cancelling a case
    releases its load back to the accumulator. The only action that raises the count is
    provisioning a replacement accessory set, which resets the remaining lives to the
    configuration's `max_instrument_lives`."

    Design: Corner/calculations/instrument_lives_accumulator_never_goes_negative_under_load
    """
    ctx = setup_system_at_instrument_lives(max_instrument_lives=2, consumed=2)
    assert ctx.system["instrument_lives_remaining"] == 0

    after = get_success_data(api_client.decrement_instrument_lives(
        ctx.system["id"], {"approved_load": 5}, TEST_USERS["service_engineer_headers"]), 200)
    assert after["instrument_lives_remaining"] == 0, "the accumulator never goes negative"

    reset = validate_success(api_client.reset_instrument_lives(
        ctx.system["id"], {"expected_robot_system_version": after["version"]},
        TEST_USERS["service_engineer_headers"]), 200)
    assert reset["instrument_lives_remaining"] == 2, (
        "a provisioning reset restores the configuration's full life count"
    )


def test_a_shortfall_of_exactly_two_charges_nothing(api):
    """PRD §2.12: "Otherwise, if the shortfall is 2 or fewer procedures the fee is 0 as well —
    the grace band is inclusive. Only beyond that does a fee accrue".
    PRD §2.12: "A commitment of 10 with a shortfall of exactly 2 therefore yields no fee,
    while a shortfall of 3 yields one procedure's worth of the placement fee at 2 percent."

    Design: Corner/calculations/shortfall_fee_grace_two_is_inclusive_and_three_charges
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=6,
                                   placement_fee_cents=1000000,
                                   usage_rate_basis_points=400)
    for i in range(4):
        create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                    case_started_at=f"2026-09-{5 + i:02d}T08:00:00Z")

    month_close("2026-10-01T00:00:00Z")
    closed = get_agreement(ctx.agreement["id"])

    assert closed["shortfall_procedures"] == 2, (
        "four scheduled cases count against a commitment of 6"
    )
    assert closed["last_shortfall_fee_cents"] == 0, (
        "a shortfall of exactly the 2-procedure grace is free"
    )


def test_a_shortfall_beyond_the_grace_charges_one_procedures_worth(api):
    """PRD §2.12: "Only beyond that does a fee accrue: the fee is the shortfall beyond the
    grace of 2, multiplied by the agreement's `placement_fee_cents`, multiplied by a
    shortfall rate of 200 basis points, and the product is divided by 10000 and rounded
    half-up to a whole number of cents."

    Design: Corner/calculations/shortfall_fee_grace_two_is_inclusive_and_three_charges
    """
    ctx = setup_usage_based_system(minimum_procedures_per_cycle=6,
                                   placement_fee_cents=1000000,
                                   usage_rate_basis_points=400)
    for i in range(3):
        create_case(ctx.system["id"], ctx.account["id"], ctx.surgeon["id"],
                    case_started_at=f"2026-09-{5 + i:02d}T08:00:00Z")

    month_close("2026-10-01T00:00:00Z")
    closed = get_agreement(ctx.agreement["id"])

    assert closed["shortfall_procedures"] == 3
    # Submit recomputes `placement_fee_cents` from the referenced configuration
    # (base 4800000 + integration tier 1 x 250000 = 5050000), so the shortfall
    # fee is one chargeable procedure at 2 percent of 5050000.
    assert closed["placement_fee_cents"] == 5050000
    assert closed["last_shortfall_fee_cents"] == 101000, (
        "one chargeable procedure at 2 percent of the agreement's placement fee"
    )


# ─── local helper ────────────────────────────────────────────────────────────

def create_incident_on(ctx, started_at: str):
    return get_success_data(api_client.create_incident(
        create_incident_payload(ctx.system["id"], incident_started_at=started_at),
        TEST_USERS["service_engineer_headers"]), 201)