"""Battery-health ingestion: telematics precondition, unknown-vehicle
existence, the strict 70.0 SOH boundary with stickiness, and the two
end-of-life valuation variants diverging on identical inputs."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    battery_health_payload,
    provision_and_activate_telematics,
    read_vehicle,
    report_battery_health,
    set_logical_clock,
    setup_base_fleet,
    validate_error,
)

_TELEMATICS = TEST_USERS["telematics_ingestion_headers"]


def test_battery_report_requires_active_telematics(api):
    """PRD section 3.9: "the `TelematicsIngestion` pipeline streams
    battery-health reports carrying `measured_soh_pct` and `measured_at`;
    reports are accepted only for vehicles with telematics `ACTIVE`
    (`ERR_TELEMATICS_NOT_ACTIVE`)."

    Design: Corner/calculations/battery_report_requires_active_telematics
    """
    fleet = setup_base_fleet(quantity=1)
    veh_id = fleet["vehicles"][0]["id"]  # telematics still OFFLINE
    resp = api.report_battery_health(
        veh_id, battery_health_payload(95.0, "2026-09-02T00:00:00Z"), _TELEMATICS
    )
    validate_error(resp, ApiErrorId.ERR_TELEMATICS_NOT_ACTIVE)
    vehicle = read_vehicle(veh_id)
    assert vehicle["current_soh_pct"] == 100.0, "a rejected report moves nothing"
    assert vehicle["last_battery_report_at"] is None


def test_battery_health_unknown_vehicle_returns_not_found(api):
    """PRD section 2.8 rule 3: "Path-template ids exist, validated left to
    right along the URL ... (`ERR_NOT_FOUND`, 404)."

    Design: Corner/endpoints/battery_health_unknown_vehicle_returns_not_found
    """
    set_logical_clock()
    resp = api.report_battery_health(
        NON_EXISTENT_UUID,
        battery_health_payload(90.0, "2026-09-02T00:00:00Z"),
        _TELEMATICS,
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def _setup_active_vehicle():
    """One registered vehicle (quantity-1 order) with telematics ACTIVE."""
    fleet = setup_base_fleet(quantity=1, delivery_method="CUSTOMER_PICKUP")
    veh_id = fleet["vehicles"][0]["id"]
    provision_and_activate_telematics(veh_id)
    return veh_id


def test_eol_valuation_variants_computed_on_threshold_crossing(api):
    """PRD section 3.9: "When a report's `measured_soh_pct` falls strictly
    below 70.0, the vehicle's `battery_eol_status` moves from `NONE` to
    `EOL_REVIEW` ... and both end-of-life valuations are computed and stored
    on the vehicle at that moment" — "A vehicle reporting 68.4 with a 77 kWh
    pack records 630000 cents under refurbishment and 632016 cents under
    recovery — the two views genuinely diverge, and both are the contract."

    Design: Difficulty/dual_variant_calc/battery_eol_valuation_refurbish_vs_recovery_divergence
    """
    veh_id = _setup_active_vehicle()
    data = report_battery_health(veh_id, 68.4, "2026-09-02T00:00:00Z")
    assert data["current_soh_pct"] == 68.4
    assert data["battery_eol_status"] == "EOL_REVIEW", "68.4 < 70.0 crosses the strict threshold"
    assert data["eol_valuation_refurbish_cents"] == 630000, (
        "1800000 x 0.35 (the below-70 band multiplier)"
    )
    assert data["eol_valuation_recovery_cents"] == 632016, "77 x 12000 x 0.684"


def test_eol_valuation_variants_diverge_and_report_stamp_recorded(api):
    """PRD section 3.9: "Each accepted report sets `current_soh_pct` to the
    measured value and `last_battery_report_at` to `measured_at`."; the
    refurbishment view "is insensitive to pack size" while the
    materials-recovery view "scales with pack size and moves continuously
    with health" — "the two views genuinely diverge".

    Design: Difficulty/dual_variant_calc/battery_eol_valuation_refurbish_vs_recovery_divergence
    """
    veh_id = _setup_active_vehicle()
    data = report_battery_health(veh_id, 68.4, "2026-09-02T00:00:00Z")
    assert data["eol_valuation_refurbish_cents"] != data["eol_valuation_recovery_cents"], (
        "identical inputs, divergent variants: 630000 != 632016"
    )
    vehicle = read_vehicle(veh_id)
    assert vehicle["last_battery_report_at"] is not None
    assert vehicle["last_battery_report_at"].startswith("2026-09-02T00:00:00"), (
        "last_battery_report_at carries the report's measured_at instant"
    )
    assert vehicle["current_soh_pct"] == 68.4


def test_soh_exactly_70_stays_out_of_eol(api):
    """PRD section 3.9: "When a report's `measured_soh_pct` falls strictly
    below 70.0, the vehicle's `battery_eol_status` moves from `NONE` to
    `EOL_REVIEW`" — exactly 70.0 is not strictly below and stays out; 69.9
    crosses.

    Design: Difficulty/boundary_precision_check/soh_exactly_70_stays_out_of_eol
    """
    veh_id = _setup_active_vehicle()
    at_70 = report_battery_health(veh_id, 70.0, "2026-09-02T00:00:00Z")
    assert at_70["battery_eol_status"] == "NONE", "70.0 is not strictly below 70.0"
    assert at_70["eol_valuation_refurbish_cents"] is None
    assert at_70["eol_valuation_recovery_cents"] is None
    at_699 = report_battery_health(veh_id, 69.9, "2026-09-03T00:00:00Z")
    assert at_699["battery_eol_status"] == "EOL_REVIEW", "69.9 < 70.0 crosses"
    assert at_699["current_soh_pct"] == 69.9


def test_eol_status_is_sticky_after_crossing(api):
    """PRD section 3.9: the vehicle's `battery_eol_status` "moves from `NONE`
    to `EOL_REVIEW` and stays there — the flag is sticky".

    Design: Difficulty/boundary_precision_check/soh_exactly_70_stays_out_of_eol
    """
    veh_id = _setup_active_vehicle()
    report_battery_health(veh_id, 69.9, "2026-09-03T00:00:00Z")
    recovered = report_battery_health(veh_id, 72.0, "2026-09-04T00:00:00Z")
    assert recovered["battery_eol_status"] == "EOL_REVIEW", (
        "a report back above 70.0 does not clear the sticky flag"
    )
    assert recovered["current_soh_pct"] == 72.0, "current_soh_pct still tracks every report"
