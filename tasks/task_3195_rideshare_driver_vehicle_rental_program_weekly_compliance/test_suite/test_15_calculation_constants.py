"""Calculation constants applied: the damage cap, the unlimited-mile provision,
the tier multiplier and the fleet-sizing balance point.
"""
from test_helpers import (
    ADMIN,
    FLEET,
    api_client,
    create_fleet_fact_payload,
    create_maintenance_event_payload,
    get_success_data,
    get_week,
    settle_week,
    setup_active_agreement,
    setup_agreement_with_open_week,
    vehicle_version,
)


def _report_and_complete(ctx, vehicle_id, damage_liability_cents, downtime_hours=0,
                         event_type="DAMAGE_REPAIR"):
    event = get_success_data(api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], vehicle_id,
            expected_vehicle_version=vehicle_version(vehicle_id),
            event_type=event_type,
            downtime_hours=downtime_hours,
            damage_liability_cents=damage_liability_cents,
        ),
        FLEET,
    ), expected_status=201)
    if downtime_hours > 0:
        api_client.start_maintenance_event(event["id"], FLEET)
    return get_success_data(api_client.complete_maintenance_event(event["id"], FLEET))


def test_damage_liability_binds_on_the_driver_cap(api):
    """PRD §3.7: "Whatever remains is then charged to the driver, but only up to
    the driver-damage cap of 50,000 cents, and the charged amount is added to
    damage_charge_cents on the open week."

    Design: Corner/calculations/damage_charge_capped_at_fifty_thousand
    """
    ctx = setup_agreement_with_open_week(
        unlimited=True, maintenance_allowance_miles=0
    )
    _report_and_complete(ctx, ctx.vehicle["id"], 60_000)

    week = get_week(ctx.week["id"])
    assert week["damage_charge_cents"] == 50_000, (
        "with a zero allowance the remaining liability is capped at 50,000 cents"
    )


def test_a_liability_exactly_at_the_cap_is_charged_in_full(api):
    """PRD §3.7: "the charged amount is added to damage_charge_cents on the open
    week."
    PRD §3.7: "the identical 30,000 cents reported against an agreement with no
    allowance miles leaves the driver charged the full 30,000 cents."

    Design: Corner/calculations/damage_charge_capped_at_fifty_thousand
    """
    ctx = setup_agreement_with_open_week(
        unlimited=True, maintenance_allowance_miles=0
    )
    _report_and_complete(ctx, ctx.vehicle["id"], 50_000)

    week = get_week(ctx.week["id"])
    assert week["damage_charge_cents"] == 50_000, (
        "the cap is inclusive, so a liability of exactly 50,000 cents is charged in full"
    )
    assert week["miles_driven"] == 0
    assert week["amount_due_cents"] == (
        week["base_charge_cents"]
        + week["insurance_charge_cents"]
        + week["mileage_overage_cents"]
        + week["damage_charge_cents"]
        - week["platform_credit_cents"]
    )


def test_an_unlimited_provision_suppresses_the_mile_bucket(api):
    """PRD §3.5: "mileage_overage_cents is zero when unlimited_mileage is true"
    PRD §3.3: "If unlimited_mileage is true that cap is not applicable and the
    weekly rate already covers all mileage"

    Design: Corner/calculations/unlimited_mileage_yields_no_overage
    """
    ctx = setup_agreement_with_open_week(unlimited=True)
    api_client.record_mileage(ctx.week["id"], {"miles_driven": 5000}, FLEET)
    settled = settle_week(ctx.week["id"])

    assert settled["miles_driven"] == 5_000
    assert settled["mileage_overage_cents"] == 0, (
        "the unlimited-mile provision suppresses the mile bucket entirely"
    )


def test_the_unlimited_week_still_owes_the_rate_and_premium_less_the_credit(api):
    """PRD §3.5: "amount_due_cents is the base plus the insurance plus the mile
    overage plus the damage, minus the platform credit."

    Design: Corner/calculations/unlimited_mileage_yields_no_overage
    """
    ctx = setup_agreement_with_open_week(unlimited=True)
    api_client.record_mileage(ctx.week["id"], {"miles_driven": 5000}, FLEET)
    settled = settle_week(ctx.week["id"])

    assert settled["amount_due_cents"] == 38_435, (
        "35,000 base plus 4,000 insurance minus 565 credit at activity score 95"
    )
    assert settled["platform_credit_cents"] == 565


def test_the_tier_multiplier_is_applied_once_after_the_band_sum(api):
    """PRD §3.2: "A driver on TIER_3 receives a further benefit: once the band sum
    is complete, the whole of it is multiplied by five quarters and floored,
    applied exactly once and applied after - never before - the band sum is
    finished."
    PRD §3.2: "a score of exactly 75 therefore adds one point's worth of the
    escalated band for 15 cents, bringing the running total to 265 cents"

    Design: Corner/calculations/tier_three_multiplier_applied_after_band_sum
    """
    ctx = setup_agreement_with_open_week(
        unlimited=True, activity_score=75, program_tier="TIER_3"
    )
    settled = settle_week(ctx.week["id"])

    assert settled["platform_credit_cents"] == 331, (
        "the 265-cent band sum is raised by five quarters, not each point"
    )
    assert settled["amount_due_cents"] == 38_669


def test_the_same_score_on_a_base_tier_yields_the_unmultiplied_band(api):
    """PRD §3.2: "the band credits a point sitting exactly at 50, and a score of
    60 yields 110 cents"

    Design: Corner/calculations/tier_three_multiplier_applied_after_band_sum
    """
    ctx = setup_agreement_with_open_week(unlimited=True, activity_score=75,
                                         program_tier="TIER_1")
    settled = settle_week(ctx.week["id"])

    assert settled["platform_credit_cents"] == 265, (
        "a TIER_1 enrolment receives no escalation of the band sum"
    )
    assert settled["amount_due_cents"] == 35_000 + 4_000 - 265


def test_the_region_balances_when_demand_meets_the_unit_count(api):
    """PRD §3.10: "A recomputation leaving sizing_deficit_units positive puts
    fleet_fact_status at UNDER_SUPPLIED; one leaving it negative puts it at
    OVER_SUPPLIED; and one leaving it at exactly zero returns it to BALANCED."
    PRD §3.10: "available_fleet_count is then every unit whose vehicle_status is
    AVAILABLE or RECOVERY"

    Design: Corner/calculations/fleet_sizing_deficit_sign_at_balance
    """
    setup_active_agreement(unlimited=True)
    for vin, miles in (("2HGES16575H606231", 61_000), ("5TFAX5GN2GX123456", 22_000)):
        api_client.admit_vehicle(
            {
                "vin": vin, "model_name": "Civic", "model_year": 2022,
                "vehicle_class": "STANDARD", "odometer_miles": miles, "region_code": "CA",
            },
            FLEET,
        )

    fact = get_success_data(api_client.declare_fleet_fact(
        create_fleet_fact_payload(region_code="CA", demand_units=3), ADMIN
    ), expected_status=201)
    recomputed = get_success_data(api_client.recompute_fleet_fact(fact["id"], FLEET))

    assert recomputed["active_agreements_count"] == 1
    assert recomputed["available_fleet_count"] == 2
    assert recomputed["utilization_bps"] == 3333
    assert recomputed["sizing_deficit_units"] == 0
    assert recomputed["fleet_fact_status"] == "BALANCED"


def test_demand_above_the_unit_count_leaves_the_region_under_supplied(api):
    """PRD §3.10: "sizing_deficit_units is the region's demand_units minus that
    same denominator, and it is a signed figure: a positive value means the region
    is short of cars against demand"

    Design: Corner/calculations/fleet_sizing_deficit_sign_at_balance
    """
    setup_active_agreement(unlimited=True)
    for vin, miles in (("2HGES16575H606232", 61_000), ("5TFAX5GN2GX123457", 22_000)):
        api_client.admit_vehicle(
            {
                "vin": vin, "model_name": "Civic", "model_year": 2022,
                "vehicle_class": "STANDARD", "odometer_miles": miles, "region_code": "CA",
            },
            FLEET,
        )

    fact = get_success_data(api_client.declare_fleet_fact(
        create_fleet_fact_payload(region_code="CA", demand_units=5), ADMIN
    ), expected_status=201)
    recomputed = get_success_data(api_client.recompute_fleet_fact(fact["id"], FLEET))

    assert recomputed["utilization_bps"] == 3333, "raising demand does not move utilization"
    assert recomputed["sizing_deficit_units"] == 2
    assert recomputed["fleet_fact_status"] == "UNDER_SUPPLIED"