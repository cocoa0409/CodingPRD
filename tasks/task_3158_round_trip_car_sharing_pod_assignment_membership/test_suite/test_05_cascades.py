"""Multi-hop cascades: the damage chain and the reservation close chain."""
from test_helpers import (
    PLATFORM,
    OPERATOR,
    accumulate_closed_reservations,
    api_client,
    assert_incident,
    assert_membership,
    create_reservation,
    freeze_membership_via_split,
    get_success_data,
    return_vehicle,
    make_member_headers,
    post_fuel_transaction,
    scheduled_order_from_incident,
    setup_confirmed_reservation,
    start_trip,
    validate_success,
)
from test_helpers.fixtures import FLEET




def test_high_severity_split_freezes_the_membership_on_the_same_response():
    """PRD §3.13: "With a `last_accident_fee_block` of 2, a `strikes` of 0 and a
    `repair_cost_cents` of 12000, the raw score is 4, the branch fires, and the excess fee is
    1500 multiplied by 4 plus 1500 multiplied by the difference of 2, giving 9000 cents."
    PRD §3.13: "The branch then cascades: every membership of the incident's member whose
    status is `ACTIVE` or `SUSPENDED` is moved to `FROZEN`, with `status_before_freeze`
    capturing the status observed immediately beforehand and `tier` set to `FROZEN`."

    Design: Difficulty/transitive_cascade/damage_split_three_hop_cascade
    """
    setup = freeze_membership_via_split(
        repair_cost_cents=12000, pod_name="Campus Cascade", clock="2026-09-05T10:00:00Z",
        member_kwargs={"full_name": "Campus Cascade Member"},
    )

    incident = setup["split"]
    assert_incident(incident)
    assert incident["severity_score"] == 4, (
        f"last_accident_fee_block 2 plus a non-zero strike term plus a large repair cost "
        f"gives 4, got {incident['severity_score']}"
    )
    assert incident["status"] == "FEE_CHARGED", (
        f"A raw score of 4 takes the high-severity branch, got {incident['status']}"
    )
    assert incident["insurance_layer"] == "STANDARD", (
        f"The fee of record must select the membership's tier, got {incident['insurance_layer']}"
    )
    # PRD §3.13: "A `STANDARD` membership — and any membership falling back to the
    # base tier — carries a zero deductible and a member liability fraction of
    # 1.00", so the fee of record against this fixture's 12000-cent repair is the
    # whole repair cost.
    assert incident["member_damage_fee_cents"] == 12000, (
        f"STANDARD liability of 1.00 against a 12000-cent repair with no deductible, got "
        f"{incident['member_damage_fee_cents']}"
    )

    frozen = setup["membership_after"]
    assert_membership(frozen)
    assert frozen["status"] == "FROZEN", (
        f"The freeze hop must have fired on the same call, got {frozen['status']}"
    )
    assert frozen["status_before_freeze"] == "ACTIVE", (
        f"The preserved anchor captures the status observed immediately beforehand, got "
        f"{frozen['status_before_freeze']}"
    )
    assert frozen["tier"] == "FROZEN", (
        f"Freezing sets the tier to FROZEN rather than leaving it as it was, got {frozen['tier']}"
    )


def test_high_severity_freeze_cancels_the_members_live_reservations():
    """PRD §3.4: "Freezing a membership is not cosmetic: every reservation belonging to that
    member whose status is `HELD` or `CONFIRMED` is cancelled, and the vehicle of each
    cancelled reservation is returned to `use_status` of `AVAILABLE`, after which the
    utilization and bay accounting of the affected pods is recomputed."

    Design: Difficulty/transitive_cascade/damage_split_three_hop_cascade
    """
    setup = freeze_membership_via_split(
        repair_cost_cents=12000, pod_name="Cancel Cascade", clock="2026-09-05T10:00:00Z"
    )

    reservation = validate_success(
        api_client.get_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    assert reservation["status"] == "CANCELLED", (
        f"Every CONFIRMED reservation of the frozen member is cancelled, got "
        f"{reservation['status']}"
    )
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], FLEET), 200)
    assert vehicle["use_status"] == "AVAILABLE", (
        f"The vehicle of a cancelled reservation returns to AVAILABLE, got {vehicle['use_status']}"
    )


def test_close_hop_posts_the_referral_credit_on_top_of_the_hold_release():
    """PRD §3.11: "It then credits the member's `wallet_credit_cents` by the member's
    `wallet_hold_cents` and sets `wallet_hold_cents` to 0, so the amount reserved at booking
    is released back to the spendable balance exactly once per reservation."
    PRD §3.11: "when the reservation's `charge_total_cents` is greater than 5000 cents and the
    member already has at least 2 `CLOSED` reservations within the last 180 days, the
    member's `wallet_credit_cents` is credited by 500 cents and the member's
    `referral_invites` is incremented by 10."

    Design: Difficulty/transitive_cascade/reservation_close_two_hop_cascade
    """
    setup = setup_confirmed_reservation(pod_name="Campus Close", site_type="AIRPORT",
                                        fuel_floor_pct=35)
    # A trip holds the vehicle down while it is live (PRD §3.6), so the placeholder
    # booking is cancelled to free the vehicle for the earlier cycles below.
    validate_success(
        api_client.cancel_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    # PRD §3.11 keys the referral credit on the member having "at least 2 `CLOSED`
    # reservations within the last 180 days", so the fixture walks two earlier
    # cycles to CLOSED before the hop under test.
    accumulate_closed_reservations(
        2, setup["pod"]["id"], setup["vehicle"]["id"], setup["member"]["id"],
        first_start="2026-09-01T00:00:00Z",
    )
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], OPERATOR), 200)
    setup["reservation"] = create_reservation(
        setup["member"]["id"], setup["pod"]["id"], setup["vehicle"]["id"], vehicle["version"],
        start_at="2026-09-06T09:00:00Z", end_at="2026-09-06T13:00:00Z",
    )
    start_trip(setup["member"]["id"], setup["reservation"]["id"], method="APP")
    get_success_data(api_client.set_clock("2026-09-06T13:10:00Z", PLATFORM), 200)
    returned = return_vehicle(
        setup["member"]["id"], setup["reservation"]["id"], setup["pod"]["id"],
        odometer_miles=42000, fuel_level_pct=20,
    )
    assert returned["status"] == "RETURNED", (
        f"A return inside the grace band bills no block and stays RETURNED, got "
        f"{returned['status']}"
    )
    assert returned["charge_total_cents"] > 5000, (
        f"The referral band needs a charge above 5000 cents, got "
        f"{returned['charge_total_cents']}"
    )
    post_fuel_transaction(setup["member"]["id"], setup["reservation"]["id"], setup["vehicle"]["id"])
    held = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)

    closed = validate_success(
        api_client.close_reservation(
            setup["reservation"]["id"], make_member_headers(setup["member"]["id"])
        ),
        200,
    )

    assert closed["status"] == "CLOSED", (
        f"The close hop lands on CLOSED, got {closed['status']}"
    )
    member = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)
    assert member["wallet_hold_cents"] == 0, (
        f"The hold is released exactly once per reservation: got {member['wallet_hold_cents']}"
    )
    assert member["referral_invites"] == 10, (
        f"A qualifying close increments referral_invites by 10, got {member['referral_invites']}"
    )
    assert member["wallet_credit_cents"] == held["wallet_credit_cents"] + held["wallet_hold_cents"] + 500, (
        f"The close hop re-credits the hold it reserved and adds the 500-cent referral credit "
        f"on top: {held['wallet_credit_cents']} + {held['wallet_hold_cents']} + 500, got "
        f"{member['wallet_credit_cents']}"
    )


def test_eight_closed_reservations_schedule_a_utilization_service_order():
    """PRD §3.11: "when the vehicle has at least 8 `CLOSED` reservations whose `closed_at`
    falls inside the last 30 days, a maintenance order is created with `blocking` true,
    `status` of `SCHEDULED` and `reason` of `UTILIZATION_SERVICE`"

    Design: Difficulty/transitive_cascade/reservation_close_two_hop_cascade
    """
    setup = setup_confirmed_reservation(pod_name="Utilization Pod")
    # A live trip holds the vehicle down while it is live (PRD §3.6), and the fact
# under test is the count of the vehicle's CLOSED reservations, so the placeholder
# trip is cancelled; the eight counted cycles follow.
    validate_success(
        api_client.cancel_reservation(setup["reservation"]["id"], OPERATOR), 200
    )
    accumulate_closed_reservations(
        8, setup["pod"]["id"], setup["vehicle"]["id"], setup["member"]["id"],
    )

    orders = validate_success(
        api_client.list_vehicle_maintenance_orders(setup["vehicle"]["id"], OPERATOR,
                                                   {"limit": 100}), 200
    )
    utilization = [o for o in orders if o["reason"] == "UTILIZATION_SERVICE"]
    assert utilization, (
        f"Eight closes inside the trailing window must schedule a service order; got "
        f"{[o['reason'] for o in orders]}"
    )
    assert utilization[0]["blocking"] is True, (
        "The utilization-service order is raised blocking"
    )
    assert utilization[0]["status"] == "SCHEDULED", (
        f"The order is born SCHEDULED, got {utilization[0]['status']}"
    )

def test_maintenance_order_raised_from_the_incident_holds_the_vehicle_in_maintenance():
    """PRD §3.12: "A blocking order moves straight into `BLOCKED` and takes the vehicle with
    it: ... on success the vehicle's `use_status` is set to `MAINTENANCE`"
    PRD §3.12: "An order is created either directly against a vehicle by a `PodOperator`,
    supplying the `vehicle_id`, a `reason`, a `blocking` flag, a `scheduled_start` and a
    `scheduled_end`, or from an incident, where a `pod_id` is supplied instead of a
    `vehicle_id`."

    Design: Difficulty/transitive_cascade/damage_split_three_hop_cascade
    """
    setup = freeze_membership_via_split(
        repair_cost_cents=12000, pod_name="Order Cascade", clock="2026-09-05T10:00:00Z"
    )
    order = scheduled_order_from_incident(
        setup["pod"]["id"], setup["incident"]["id"], reason="COLLISION_REPAIR", blocking=True,
        scheduled_start="2026-09-20T09:00:00Z", scheduled_end="2026-09-20T11:00:00Z",
    )

    assert order["status"] == "BLOCKED", (
        f"A blocking order moves straight into BLOCKED, got {order['status']}"
    )
    assert order["incident_id"] == setup["incident"]["id"], (
        f"The order records the incident it was raised from, got {order['incident_id']}"
    )
    vehicle = validate_success(api_client.get_vehicle(setup["vehicle"]["id"], FLEET), 200)
    assert vehicle["use_status"] == "MAINTENANCE", (
        f"The blocking order takes the vehicle with it, got {vehicle['use_status']}"
    )
