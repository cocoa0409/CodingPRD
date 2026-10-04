"""Optimistic-concurrency guards and the remaining priority clash.
"""
from test_helpers import (
    ADMIN,
    FLEET,
    agreement_version,
    api_client,
    create_maintenance_event_payload,
    create_purchase_option_payload,
    get_agreement,
    get_success_data,
    get_option,
    get_vehicle,
    get_week,
    open_week,
    settle_week,
    set_clock,
    setup_active_agreement,
    validate_error,
    vehicle_version,
)
from test_helpers.api_errors import ApiErrorId


def test_a_stale_agreement_version_blocks_opening_a_week(api):
    """PRD §3.4: "A FleetOpsAgent opens the next weekly period by naming the
    agreement and supplying expected_agreement_version carrying their last-observed
    version of that agreement - this is the guard described in §2.6, and a stale
    value is rejected with ERR_STALE_AGREEMENT_VERSION (HTTP 412) before anything
    else about the request is considered."

    Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_on_week_open_is_rejected
    """
    ctx = setup_active_agreement(unlimited=True)
    live = agreement_version(ctx.agreement["id"])

    stale = api_client.open_week(
        {"agreement_id": ctx.agreement["id"], "expected_agreement_version": live - 1},
        FLEET,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION, 412)
    assert api_client.list_weeks(FLEET, params={"agreement_id": ctx.agreement["id"]}).json()[
        "meta"
    ]["total_count"] == 0


def test_a_fresh_version_opens_the_period_and_advances_the_row(api):
    """PRD §3.4: "The agreement's version advances by one as part of the
    operation."
    PRD §2.4: "version (integer): a monotonically increasing integer that advances
    by exactly one on every mutation of the row."

    Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_on_week_open_is_rejected
    """
    ctx = setup_active_agreement(unlimited=True)
    live = agreement_version(ctx.agreement["id"])

    opened = get_success_data(api_client.open_week(
        {"agreement_id": ctx.agreement["id"], "expected_agreement_version": live},
        FLEET,
    ), expected_status=201)
    assert opened["week_number"] == 1
    assert agreement_version(ctx.agreement["id"]) == live + 1


def test_a_stale_vehicle_version_blocks_reporting_a_service_event(api):
    """PRD §3.7: "The request must carry expected_vehicle_version holding the
    caller's last-observed version of the unit, and a stale value is rejected with
    ERR_STALE_VEHICLE_VERSION (HTTP 412) - the reason the guard exists is that a
    stale view of a unit would take the wrong unit out of service."

    Design: Corner/cross_cutting_complexity_layers/stale_vehicle_version_on_maintenance_report_is_rejected
    """
    ctx = setup_active_agreement(unlimited=True)
    live = vehicle_version(ctx.vehicle["id"])

    stale = api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=live - 1,
            event_type="SCHEDULED_SERVICE", downtime_hours=4,
        ),
        FLEET,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VEHICLE_VERSION, 412)
    assert api_client.list_maintenance_events(FLEET).json()["meta"]["total_count"] == 0


def test_the_fresh_vehicle_version_takes_the_unit_out_of_service(api):
    """PRD §3.7: "Reporting an event takes the unit out of both ride and delivery
    availability: vehicle_status becomes MAINTENANCE, from ASSIGNED when it was on
    rent or from AVAILABLE when it was sitting in the pool, and assigned_driver_id
    on the unit is cleared."

    Design: Corner/cross_cutting_complexity_layers/stale_vehicle_version_on_maintenance_report_is_rejected
    """
    ctx = setup_active_agreement(unlimited=True)
    live = vehicle_version(ctx.vehicle["id"])

    event = get_success_data(api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=live,
            event_type="SCHEDULED_SERVICE", downtime_hours=4,
        ),
        FLEET,
    ), expected_status=201)

    unit = get_vehicle(ctx.vehicle["id"])
    assert unit["vehicle_status"] == "MAINTENANCE"
    assert unit["assigned_driver_id"] is None
    assert unit["version"] == live + 1
    assert event["event_status"] == "REPORTED"


def test_a_stale_agreement_version_blocks_electing_the_option(api):
    """PRD §3.9: "A Driver elects the option, and the request must carry
    expected_agreement_version holding their last-observed version of the agreement
    behind the option - a stale value is rejected with ERR_STALE_AGREEMENT_VERSION
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_on_week_open_is_rejected
    """
    ctx = setup_active_agreement(unlimited=True)
    offered = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(ctx.agreement["id"], ctx.driver["id"]),
        ADMIN,
    ), expected_status=201)
    assert offered["option_status"] == "OFFERED"

    stale = api_client.elect_purchase_option(
        offered["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"]) - 1},
        ctx.driver_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_AGREEMENT_VERSION, 412)
    assert get_option(offered["id"])["option_status"] == "OFFERED", (
        "the stale election is refused rather than applied"
    )


def test_a_fresh_agreement_version_completes_the_election(api):
    """PRD §3.9: "On success option_status moves from OFFERED to ELECTED with
    elected_at stamped, agreement_status moves from ACTIVE to PURCHASE_PENDING"

    Design: Corner/cross_cutting_complexity_layers/stale_agreement_version_on_week_open_is_rejected
    """
    ctx = setup_active_agreement(unlimited=True)
    offered = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(ctx.agreement["id"], ctx.driver["id"]),
        ADMIN,
    ), expected_status=201)

    elected = get_success_data(api_client.elect_purchase_option(
        offered["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    ))
    assert elected["option_status"] == "ELECTED"
    assert get_agreement(ctx.agreement["id"])["agreement_status"] == "PURCHASE_PENDING"


def test_advancing_the_clock_crosses_every_deadline_it_passes(api):
    """PRD §2.9: "Advancing the clock is not a passive bookkeeping operation:
    every time-gated transition whose deadline the new instant reaches is applied
    as part of that call."

    Design: Corner/cross_cutting_complexity_layers/clock_advance_lapses_grace_without_a_manual_call
    """
    ctx = setup_active_agreement(unlimited=True)
    week = open_week(ctx.agreement["id"])
    settled = settle_week(week["id"])
    assert settled["week_status"] == "DUE"
    assert settled["payment_deadline"] == "2026-09-08T00:00:00Z"

    set_clock("2026-09-08T00:00:00Z")
    assert get_week(week["id"])["week_status"] == "GRACE", (
        "the clock call alone applied the time-gated transition"
    )


def test_the_week_stays_in_grace_until_delinquency_is_declared(api):
    """PRD §3.8: "When a week's payment deadline has passed without settlement,
    the clock advance described in §2.9 moves the week from DUE to GRACE; this
    happens as a consequence of advancing the clock, not as a separate call. Grace
    buys 72 hours. Declaring the week delinquent is a deliberate step taken by a
    ComplianceOfficer after that grace has lapsed"

    Design: Corner/cross_cutting_complexity_layers/clock_advance_lapses_grace_without_a_manual_call
    """
    ctx = setup_active_agreement(unlimited=True)
    week = open_week(ctx.agreement["id"])
    settle_week(week["id"])

    set_clock("2026-09-11T00:00:00Z")
    assert get_week(week["id"])["week_status"] == "GRACE", (
        "delinquency still requires the explicit grace-lapse call"
    )
    assert get_agreement(ctx.agreement["id"])["compliance_posture"] == "OPEN"


def test_counterpart_test_advancing_the_clock_twice_reaches_grace_once(api):
    """PRD §2.9: "any other deadline that falls between the old and new instants
    is crossed in the same way."
    PRD §3.4: "a period can be GRACE in status while UNPAID in payment"

    Design: Corner/cross_cutting_complexity_layers/clock_advance_lapses_grace_without_a_manual_call
    """
    ctx = setup_active_agreement(unlimited=True)
    week = open_week(ctx.agreement["id"])
    settle_week(week["id"])

    set_clock("2026-09-05T00:00:00Z")
    assert get_week(week["id"])["week_status"] == "DUE", "the deadline has not been reached"

    set_clock("2026-09-09T00:00:00Z")
    row = get_week(week["id"])
    assert row["week_status"] == "GRACE"
    assert row["payment_status"] == "UNPAID", (
        "the payment dimension has not moved with the week dimension"
    )