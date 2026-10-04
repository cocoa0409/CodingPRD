"""Action endpoints whose effect is a coordinated pair of row changes, plus the
immediate-consistency guarantee that a computed read reflects them at once.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    FLEET,
    api_client,
    get_success_data,
    get_vehicle,
    get_week,
    make_driver_headers,
    setup_active_agreement,
    setup_recovered_agreement,
    validate_error,
)
from test_helpers.api_errors import ApiErrorId


def test_swapping_releases_the_old_unit_and_assigns_the_new(api):
    """PRD §3.3: "On success the outgoing unit's vehicle_status is released to
    AVAILABLE, the incoming unit is set to ASSIGNED with assigned_driver_id
    stamped onto it, and the incoming unit's baseline_odometer_miles is
    restamped"

    Design: Corner/endpoints/swap_reassigns_without_double_assignment
    """
    ctx = setup_active_agreement(unlimited=True)
    replacement = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606231", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 61_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)

    swapped = get_success_data(api_client.swap_agreement_vehicle(
        ctx.agreement["id"], {"new_vehicle_id": replacement["id"]}, FLEET
    ))

    assert swapped["vehicle_id"] == replacement["id"]
    released = get_vehicle(ctx.vehicle["id"])
    assert released["vehicle_status"] == "AVAILABLE"
    assert released["assigned_driver_id"] is None

    assigned = get_vehicle(replacement["id"])
    assert assigned["vehicle_status"] == "ASSIGNED"
    assert assigned["assigned_driver_id"] == ctx.driver["id"]
    assert assigned["baseline_odometer_miles"] == 61_000


def test_the_driver_holds_exactly_one_assigned_unit_through_a_swap(api):
    """PRD §2.8: "a unit is either held by a driver, parked in the available pool,
    or parked in the recovery pool, and never two of those at once."

    Design: Corner/endpoints/swap_reassigns_without_double_assignment
    """
    ctx = setup_active_agreement(unlimited=True)
    replacement = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606232", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 61_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)

    api_client.swap_agreement_vehicle(
        ctx.agreement["id"], {"new_vehicle_id": replacement["id"]}, FLEET
    )

    held = api_client.list_vehicles(
        FLEET, params={"assigned_driver_id": ctx.driver["id"]}
    ).json()["data"]
    assert [row["id"] for row in held] == [replacement["id"]]


def test_recovery_returns_the_unit_and_closes_every_delinquent_week(api):
    """PRD §3.8: "Executing the recovery is the final fleet step. It requires
    agreement_status to be RECOVERY_PENDING and vehicle_status to actually be
    RECOVERY, and - because recovery can only be executed once - the agreement's
    recovered-week set must still be open, or the request is rejected with
    ERR_RECOVERY_ALREADY_CLOSED (HTTP 409)."
    PRD §3.8: "every week whose week_status is DELINQUENT is moved to RECOVERED,
    and agreement_status becomes RECOVERED"

    Design: Corner/endpoints/recover_closes_delinquent_weeks_and_returns_unit
    """
    
    ctx = setup_recovered_agreement(unlimited=True)

    assert ctx.agreement["agreement_status"] == "RECOVERED"
    for week in ctx.weeks:
        assert get_week(week["id"])["week_status"] == "RECOVERED"

    unit = get_vehicle(ctx.vehicle["id"])
    assert unit["vehicle_status"] == "AVAILABLE"
    assert unit["assigned_driver_id"] is None


def test_a_replay_of_recovery_is_refused(api):
    """PRD §3.8: "because recovery can only be executed once - the agreement's
    recovered-week set must still be open, or the request is rejected with
    ERR_RECOVERY_ALREADY_CLOSED (HTTP 409)."

    Design: Corner/endpoints/recover_closes_delinquent_weeks_and_returns_unit
    """
    ctx = setup_recovered_agreement(unlimited=True)

    response = api_client.recover_agreement(ctx.agreement["id"], FLEET)
    validate_error(response, ApiErrorId.ERR_RECOVERY_ALREADY_CLOSED, 409)


def test_withdrawal_is_refused_while_an_agreement_still_holds_occupancy(api):
    """PRD §3.1: "A driver leaving the programme, or a ComplianceOfficer
    withdrawing an active or suspended enrolment on the driver's behalf, is
    refused while any agreement of that enrolment still holds occupancy.
    Occupancy-holding agreement states are ACTIVE, RENEWAL_DUE, DELINQUENT,
    RECOVERY_PENDING and PURCHASE_PENDING"

    Design: Corner/endpoints/withdraw_enrollment_blocked_while_agreement_holds_vehicle
    """
    ctx = setup_active_agreement(unlimited=True)

    response = api_client.withdraw_enrollment(
        ctx.enrollment["id"], make_driver_headers(ctx.driver["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)
    assert api_client.get_enrollment(ctx.enrollment["id"], COMPLIANCE).json()[
        "data"
    ]["enrollment_status"] == "ACTIVE"


def test_withdrawal_succeeds_once_the_agreement_has_completed(api):
    """PRD §3.1: "When the withdrawal succeeds enrollment_status reaches
    WITHDRAWN, which is its only terminal state, and if the driver holds no other
    ACTIVE enrolment their posture is forced to INELIGIBLE."

    Design: Corner/endpoints/withdraw_enrollment_blocked_while_agreement_holds_vehicle
    """
    ctx = setup_active_agreement(unlimited=True)
    api_client.complete_agreement(ctx.agreement["id"], FLEET)

    withdrawn = get_success_data(api_client.withdraw_enrollment(
        ctx.enrollment["id"], make_driver_headers(ctx.driver["id"])
    ))
    assert withdrawn["enrollment_status"] == "WITHDRAWN"
    assert api_client.get_driver(ctx.driver["id"], COMPLIANCE).json()["data"][
        "eligibility_status"
    ] == "INELIGIBLE"


def test_waiving_the_only_incurring_week_forfeits_the_equity_credit(api):
    """PRD §3.6: "Because the equity credit is computed from paid amounts net of
    waived amounts, a waiver does not simply remove a bill - it also suppresses
    the equity that week would otherwise have earned, and it triggers both a
    delinquency-count recompute and an equity-credit recompute."
    PRD §3.6: "A waived week moves to WAIVED, which is terminal, and the
    agreement's cumulative waived total rises by that week's amount owed."

    Design: Corner/endpoints/waive_clears_delinquency_and_forfeits_equity
    """
    from test_helpers import agreement_summary, get_week, lapse_grace, setup_with_delinquent_weeks

    ctx = setup_with_delinquent_weeks(count=1, unlimited=True)

    waived = get_success_data(api_client.waive_week(ctx.weeks[0]["id"], ADMIN))
    assert waived["week_status"] == "WAIVED"

    agreement = api_client.get_agreement(ctx.agreement["id"], FLEET).json()["data"]
    assert agreement["total_waived_cents"] == ctx.weeks[0]["amount_due_cents"]
    assert agreement["total_billed_cents"] == 0
    assert agreement["compliance_posture"] == "OPEN"
    assert agreement["agreement_status"] == "ACTIVE"
    assert agreement_summary(ctx.agreement["id"])["equity_credit_cents"] == 0


def test_a_waived_week_leaves_the_posture_reading_at_zero(api):
    """PRD §3.8: "A count of 0 yields OPEN; a count of exactly 1 yields
    RESTRICTED; a count of 2 or more yields FROZEN."

    Design: Corner/endpoints/waive_clears_delinquency_and_forfeits_equity
    """
    from test_helpers import setup_with_delinquent_weeks

    ctx = setup_with_delinquent_weeks(count=1, unlimited=True)
    assert api_client.get_agreement(ctx.agreement["id"], FLEET).json()["data"][
        "compliance_posture"
    ] == "RESTRICTED"

    api_client.waive_week(ctx.weeks[0]["id"], ADMIN)
    summary = get_success_data(api_client.get_agreement_summary(ctx.agreement["id"], FLEET))
    assert summary["outstanding_delinquent_weeks"] == 0
    assert summary["compliance_posture"] == "OPEN"


def test_a_swap_is_visible_in_the_driver_summary_in_the_same_cycle(api):
    """PRD §2.4: "This matters because the version counters are the substrate for
    the concurrency guards described in §2.6."

    Design: Corner/cross_cutting_complexity_layers/post_swaps_reflect_in_driver_summary_immediately
    """
    ctx = setup_active_agreement(unlimited=True)
    replacement = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606233", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": "STANDARD", "odometer_miles": 61_000, "region_code": "CA",
        },
        FLEET,
    ), expected_status=201)

    api_client.swap_agreement_vehicle(
        ctx.agreement["id"], {"new_vehicle_id": replacement["id"]}, FLEET
    )
    summary = get_success_data(api_client.get_driver_summary(ctx.driver["id"], COMPLIANCE))

    assert summary["assigned_vehicle_id"] == replacement["id"]
    held = api_client.list_vehicles(
        FLEET, params={"assigned_driver_id": ctx.driver["id"]}
    ).json()["data"]
    assert len(held) == 1
    assert held[0]["id"] == replacement["id"]
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "AVAILABLE"