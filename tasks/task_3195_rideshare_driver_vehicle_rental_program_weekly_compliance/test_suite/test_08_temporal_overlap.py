"""Temporal overlap rules: half-open occupancy intervals and the recovery quiet
period's 24-hour buffer.
"""
from test_helpers import (
    COMPLIANCE,
    FLEET,
    api_client,
    create_maintenance_event_payload,
    create_unlimited_agreement_payload,
    get_agreement,
    get_success_data,
    get_vehicle,
    register_driver,
    set_clock,
    setup_with_delinquent_weeks,
    validate_error,
    vehicle_version,
)
from test_helpers.api_errors import ApiErrorId


def _driver_with_verified_enrollment(vin="1HGCM82633A004352"):
    driver = register_driver()
    enrollment = get_success_data(api_client.enroll_driver(
        {"driver_id": driver["id"], "program_tier": "TIER_1"}, COMPLIANCE
    ), expected_status=201)
    api_client.verify_enrollment(enrollment["id"], COMPLIANCE)
    vehicle = get_success_data(api_client.admit_vehicle(
        {
            "vin": vin, "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 40_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)
    return driver, enrollment, vehicle


def test_an_interval_beginning_one_second_before_the_boundary_collides(api):
    """PRD §3.4: "Occupancy intervals are half-open on both bounds: a new interval
    that begins exactly at another interval's period_end does not collide with it,
    while one that begins strictly before that instant does."
    PRD §3.3: "the requested interval must not collide with an existing occupancy
    interval on that unit, or the request is rejected with
    ERR_VEHICLE_INTERVAL_OVERLAP (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/vehicle_occupancy_half_open_interval_adjacency
    """
    driver, enrollment, vehicle = _driver_with_verified_enrollment()
    first = get_success_data(api_client.create_agreement(
        create_unlimited_agreement_payload(
            enrollment["id"], driver["id"], vehicle["id"],
            period_start="2026-09-01T00:00:00Z", period_end="2026-09-08T00:00:00Z",
        ),
        FLEET,
    ), expected_status=201)

    overlapping = api_client.create_agreement(
        create_unlimited_agreement_payload(
            enrollment["id"], driver["id"], vehicle["id"],
            period_start="2026-09-07T23:59:59Z", period_end="2026-09-15T00:00:00Z",
        ),
        FLEET,
    )
    validate_error(overlapping, ApiErrorId.ERR_VEHICLE_INTERVAL_OVERLAP, 409)
    assert get_agreement(first["id"])["period_end"] == "2026-09-08T00:00:00Z"


def test_an_interval_beginning_exactly_at_the_boundary_is_accepted(api):
    """PRD §3.4: "This is what allows the same unit to be re-let back-to-back
    without an artificial gap, and it is also the rule behind the
    ERR_VEHICLE_INTERVAL_OVERLAP rejection that guards agreement creation and
    swaps."

    Design: Difficulty/resource_temporal_overlap/vehicle_occupancy_half_open_interval_adjacency
    """
    driver, enrollment, vehicle = _driver_with_verified_enrollment("1HGCM82633A004399")
    first = get_success_data(api_client.create_agreement(
        create_unlimited_agreement_payload(
            enrollment["id"], driver["id"], vehicle["id"],
            period_start="2026-09-01T00:00:00Z", period_end="2026-09-08T00:00:00Z",
        ),
        FLEET,
    ), expected_status=201)

    adjacent = get_success_data(api_client.create_agreement(
        create_unlimited_agreement_payload(
            enrollment["id"], driver["id"], vehicle["id"],
            period_start="2026-09-08T00:00:00Z", period_end="2026-09-15T00:00:00Z",
        ),
        FLEET,
    ), expected_status=201)

    assert adjacent["period_start"] == "2026-09-08T00:00:00Z"
    assert get_agreement(first["id"])["period_end"] == "2026-09-08T00:00:00Z"


def test_a_single_second_of_trespass_is_the_whole_difference(api):
    """PRD §2.7: "Intervals are half-open: a new interval that starts exactly at
    an existing interval's period_end does not collide."
    PRD §3.4: "the same unit to be re-let back-to-back without an artificial gap"

    Design: Difficulty/resource_temporal_overlap/vehicle_occupancy_half_open_interval_adjacency
    """
    driver, enrollment, vehicle = _driver_with_verified_enrollment("1HGCM82633A004411")
    api_client.create_agreement(
        create_unlimited_agreement_payload(
            enrollment["id"], driver["id"], vehicle["id"],
            period_start="2026-09-01T00:00:00Z", period_end="2026-09-08T00:00:00Z",
        ),
        FLEET,
    )

    one_second_early = api_client.create_agreement(
        create_unlimited_agreement_payload(
            enrollment["id"], driver["id"], vehicle["id"],
            period_start="2026-09-07T23:59:59Z", period_end="2026-09-15T00:00:00Z",
        ),
        FLEET,
    )
    assert one_second_early.status_code == 409

    exact = api_client.create_agreement(
        create_unlimited_agreement_payload(
            enrollment["id"], driver["id"], vehicle["id"],
            period_start="2026-09-08T00:00:00Z", period_end="2026-09-15T00:00:00Z",
        ),
        FLEET,
    )
    assert exact.status_code == 201


def test_maintenance_reporting_is_refused_inside_the_recovery_quiet_period(api):
    """PRD §3.8: "The unit then enters a quiet period: its recovery interval stays
    open for 24 hours past this instant, and no maintenance event may be reported
    against it during that window."
    PRD §3.7: "a maintenance event may not be reported against a unit whose
    recovery interval is open, where that interval runs from the instant the unit
    entered RECOVERY through 24 hours after it last returned to AVAILABLE.
    Reporting against a unit still inside that window is rejected with
    ERR_MAINTENANCE_WINDOW_CONFLICT (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/recovery_interval_blocks_maintenance_reporting
    """
    ctx = setup_with_delinquent_weeks(count=2, unlimited=True)
    set_clock("2026-09-11T00:00:00Z")
    get_success_data(api_client.escalate_recovery(ctx.agreement["id"], FLEET))
    get_success_data(api_client.recover_agreement(ctx.agreement["id"], FLEET))
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "AVAILABLE"

    response = api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            event_type="UNSCHEDULED_REPAIR", odometer_at_service=40_100,
            downtime_hours=8,
        ),
        FLEET,
    )
    validate_error(response, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT, 409)


def test_the_quiet_period_is_a_buffer_not_a_half_open_occupancy_interval(api):
    """PRD §3.7: "that interval runs from the instant the unit entered RECOVERY
    through 24 hours after it last returned to AVAILABLE"
    PRD §3.8: "its recovery interval stays open for 24 hours past this instant"

    Design: Difficulty/resource_temporal_overlap/recovery_interval_blocks_maintenance_reporting
    """
    ctx = setup_with_delinquent_weeks(count=2, unlimited=True)
    set_clock("2026-09-11T00:00:00Z")
    api_client.escalate_recovery(ctx.agreement["id"], FLEET)
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "RECOVERY"

    one_hour_in = api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            odometer_at_service=40_100, downtime_hours=8,
        ),
        FLEET,
    )
    assert one_hour_in.status_code == 409
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "RECOVERY", (
        "the refusal leaves the unit in the recovery pool"
    )


def test_the_buffer_runs_from_the_return_to_the_pool_not_from_the_freeze(api):
    """PRD §3.7: "The agreement behind the event must not be FROZEN in posture, or
    the request is rejected with ERR_AGREEMENT_FROZEN (HTTP 409)."
    PRD §3.7: "a unit that has just come back from recovery has not yet been
    cleared for service."

    Design: Difficulty/resource_temporal_overlap/recovery_interval_blocks_maintenance_reporting
    """
    ctx = setup_with_delinquent_weeks(count=2, unlimited=True)
    set_clock("2026-09-11T00:00:00Z")
    api_client.escalate_recovery(ctx.agreement["id"], FLEET)
    api_client.recover_agreement(ctx.agreement["id"], FLEET)

    vehicle = get_vehicle(ctx.vehicle["id"])
    assert vehicle["vehicle_status"] == "AVAILABLE"
    assert vehicle["assigned_driver_id"] is None
    assert get_agreement(ctx.agreement["id"])["agreement_status"] == "RECOVERED"