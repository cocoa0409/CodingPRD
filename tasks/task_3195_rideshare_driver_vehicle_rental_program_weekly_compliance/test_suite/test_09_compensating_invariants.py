"""Compensating pairs: operations whose forward and reverse halves cancel a
programme-wide count.
"""
from test_helpers import (
    ADMIN,
    FLEET,
    SUPPORT,
    agreement_version,
    api_client,
    count_assigned_vehicles,
    count_non_retired_vehicles,
    count_retired_vehicles,
    create_maintenance_event_payload,
    create_purchase_option_payload,
    get_agreement,
    get_option,
    get_success_data,
    get_vehicle,
    open_week,
    settle_week,
    vehicle_version,
)
from test_helpers import setup_active_agreement


def _region_owned_vehicles(region="CA"):
    from test_helpers import vehicles_in_region
    return vehicles_in_region(region)


def test_issuing_a_loaner_conserves_the_assigned_unit_count(api):
    """PRD §2.8: "issuing a loaner flips the loaner from AVAILABLE to ASSIGNED and
    stamps the agreement's driver onto it, so the number of assigned units across
    the fleet is conserved even though the driver now nominally controls two
    units."

    Design: Difficulty/compensating_invariant/maintenance_loaner_conserves_assigned_fleet_units
    """
    ctx = setup_active_agreement(unlimited=True)
    spare = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606231", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": ctx.vehicle["vehicle_class"],
            "odometer_miles": 61_000, "region_code": ctx.vehicle["region_code"],
        },
        FLEET,
    ), expected_status=201)

    before = count_assigned_vehicles(ctx.vehicle["region_code"])
    assert before == 1

    event = get_success_data(api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            downtime_hours=30,
        ),
        FLEET,
    ), expected_status=201)
    api_client.start_maintenance_event(event["id"], FLEET)
    issued = get_success_data(api_client.issue_loaner(event["id"], FLEET))

    assert issued["loaner_vehicle_id"] == spare["id"], (
        "the only AVAILABLE unit of the right class and region is selected"
    )
    assert get_vehicle(ctx.vehicle["id"])["vehicle_status"] == "MAINTENANCE"
    assert get_vehicle(spare["id"])["vehicle_status"] == "ASSIGNED"
    assert count_assigned_vehicles(ctx.vehicle["region_code"]) == before, (
        "the loaner substitutes for the unit under repair"
    )


def test_completing_the_event_restores_both_units_and_the_count(api):
    """PRD §2.8: "Completing the service event performs the compensating action -
    the loaner is released back to AVAILABLE with its driver reference cleared,
    and the original unit, restamped to ASSIGNED, resumes the assignment."
    PRD §3.7: "This assignment of the loaner is the forward half of the invariant"

    Design: Difficulty/compensating_invariant/maintenance_loaner_conserves_assigned_fleet_units
    """
    ctx = setup_active_agreement(unlimited=True)
    spare = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606232", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": ctx.vehicle["vehicle_class"],
            "odometer_miles": 61_000, "region_code": ctx.vehicle["region_code"],
        },
        FLEET,
    ), expected_status=201)

    event = get_success_data(api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            downtime_hours=30,
        ),
        FLEET,
    ), expected_status=201)
    api_client.start_maintenance_event(event["id"], FLEET)
    api_client.issue_loaner(event["id"], FLEET)
    api_client.complete_maintenance_event(event["id"], FLEET)

    original = get_vehicle(ctx.vehicle["id"])
    assert original["vehicle_status"] == "ASSIGNED"
    assert original["assigned_driver_id"] == ctx.driver["id"]

    released = get_vehicle(spare["id"])
    assert released["vehicle_status"] == "AVAILABLE"
    assert released["assigned_driver_id"] is None
    assert count_assigned_vehicles(ctx.vehicle["region_code"]) == 1


def test_the_two_vehicle_ids_carrying_assigned_differ_before_and_after(api):
    """PRD §2.8: "a unit is either held by a driver, parked in the available pool,
    or parked in the recovery pool, and never two of those at once."
    PRD §3.7: "the loaner's vehicle_status is flipped from AVAILABLE to ASSIGNED
    with assigned_driver_id stamped onto it"

    Design: Difficulty/compensating_invariant/maintenance_loaner_conserves_assigned_fleet_units
    """
    ctx = setup_active_agreement(unlimited=True)
    spare = get_success_data(api_client.admit_vehicle(
        {
            "vin": "2HGES16575H606233", "model_name": "Civic", "model_year": 2022,
            "vehicle_class": ctx.vehicle["vehicle_class"],
            "odometer_miles": 61_000, "region_code": ctx.vehicle["region_code"],
        },
        FLEET,
    ), expected_status=201)

    event = get_success_data(api_client.report_maintenance_event(
        create_maintenance_event_payload(
            ctx.agreement["id"], ctx.vehicle["id"],
            expected_vehicle_version=vehicle_version(ctx.vehicle["id"]),
            downtime_hours=30,
        ),
        FLEET,
    ), expected_status=201)
    api_client.start_maintenance_event(event["id"], FLEET)
    api_client.issue_loaner(event["id"], FLEET)
    during = [v["id"] for v in _region_owned_vehicles(ctx.vehicle["region_code"])
              if v["vehicle_status"] == "ASSIGNED"]
    assert during == [spare["id"]], "the loaner carries the assignment during the repair"

    api_client.complete_maintenance_event(event["id"], FLEET)
    after = [v["id"] for v in _region_owned_vehicles(ctx.vehicle["region_code"])
             if v["vehicle_status"] == "ASSIGNED"]
    assert after == [ctx.vehicle["id"]], "the original unit resumes the assignment"
    assert during != after, "the count is conserved but the ids are not"


def test_completing_a_purchase_retires_the_unit_and_closes_the_agreement(api):
    """PRD §3.9: "On success option_status reaches COMPLETED, vehicle_status is
    moved from ASSIGNED to RETIRED and the unit leaves the rental fleet
    permanently with assigned_driver_id cleared, and agreement_status becomes
    PURCHASED, its final terminal value."

    Design: Difficulty/compensating_invariant/purchase_exit_conserves_non_retired_vehicle_total
    """
    ctx = setup_active_agreement(unlimited=True)
    week1 = open_week(ctx.agreement["id"])
    settle_week(week1["id"])
    get_success_data(api_client.tender_payment(
        week1["id"],
        {"amount_cents": get_success_data(api_client.get_week(week1["id"], SUPPORT))["amount_due_cents"],
         "payment_outcome": "SUCCEEDED"},
        SUPPORT,
    ), expected_status=201)

    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(
            ctx.agreement["id"], ctx.driver["id"],
            purchase_price_cents=1_200_000, escrow_weeks_required=1,
        ),
        ADMIN,
    ), expected_status=201)
    api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    api_client.fund_escrow(option["id"], ctx.driver_headers)
    completed = get_success_data(api_client.complete_purchase_option(option["id"], ADMIN))

    assert completed["option_status"] == "COMPLETED"
    assert get_agreement(ctx.agreement["id"])["agreement_status"] == "PURCHASED"

    vehicle = get_vehicle(ctx.vehicle["id"])
    assert vehicle["vehicle_status"] == "RETIRED"
    assert vehicle["assigned_driver_id"] is None


def test_the_fleet_total_is_conserved_across_the_purchase_exit(api):
    """PRD §3.10: "available_fleet_count is then every unit whose vehicle_status
    is AVAILABLE or RECOVERY - a unit sitting in the recovery pool is still
    programme fleet and still counts toward supply, even though it is not
    currently lettable."
    PRD §3.9: "the unit leaves the rental fleet permanently"

    Design: Difficulty/compensating_invariant/purchase_exit_conserves_non_retired_vehicle_total
    """
    ctx = setup_active_agreement(unlimited=True)
    week1 = open_week(ctx.agreement["id"])
    settle_week(week1["id"])
    get_success_data(api_client.tender_payment(
        week1["id"],
        {"amount_cents": get_success_data(api_client.get_week(week1["id"], SUPPORT))["amount_due_cents"],
         "payment_outcome": "SUCCEEDED"},
        SUPPORT,
    ), expected_status=201)

    region = ctx.vehicle["region_code"]
    pooled_before = count_non_retired_vehicles(region)
    retired_before = count_retired_vehicles(region)

    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(
            ctx.agreement["id"], ctx.driver["id"],
            purchase_price_cents=1_200_000, escrow_weeks_required=1,
        ),
        ADMIN,
    ), expected_status=201)
    api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    api_client.fund_escrow(option["id"], ctx.driver_headers)
    api_client.complete_purchase_option(option["id"], ADMIN)

    assert count_non_retired_vehicles(region) == pooled_before - 1
    assert count_retired_vehicles(region) == retired_before + 1
    assert (
        count_non_retired_vehicles(region) + count_retired_vehicles(region)
        == pooled_before + retired_before
    ), "the ASSIGNED removal and the RETIRED addition cancel"


def test_the_purchase_does_not_disturb_the_billed_total(api):
    """PRD §3.9: "Completion requires escrow_weeks_funded to have reached
    escrow_weeks_required - otherwise the request is rejected with
    ERR_ESCROW_INCOMPLETE (HTTP 422) - and requires escrow_balance_cents plus
    equity_credit_cents to cover purchase_price_cents."

    Design: Difficulty/compensating_invariant/purchase_exit_conserves_non_retired_vehicle_total
    """
    ctx = setup_active_agreement(unlimited=True)
    week1 = open_week(ctx.agreement["id"])
    settle_week(week1["id"])
    signed = get_success_data(api_client.tender_payment(
        week1["id"],
        {"amount_cents": get_success_data(api_client.get_week(week1["id"], SUPPORT))["amount_due_cents"],
         "payment_outcome": "SUCCEEDED"},
        SUPPORT,
    ), expected_status=201)

    billed_before = get_agreement(ctx.agreement["id"])["total_billed_cents"]

    option = get_success_data(api_client.offer_purchase_option(
        create_purchase_option_payload(
            ctx.agreement["id"], ctx.driver["id"],
            purchase_price_cents=1_200_000, escrow_weeks_required=1,
        ),
        ADMIN,
    ), expected_status=201)
    api_client.elect_purchase_option(
        option["id"],
        {"expected_agreement_version": agreement_version(ctx.agreement["id"])},
        ctx.driver_headers,
    )
    api_client.fund_escrow(option["id"], ctx.driver_headers)
    funded = get_option(option["id"])
    api_client.complete_purchase_option(option["id"], ADMIN)

    assert funded["escrow_balance_cents"] + funded["equity_credit_cents"] >= 1_200_000
    assert get_agreement(ctx.agreement["id"])["total_billed_cents"] == billed_before
    assert billed_before == signed["amount_due_cents"]