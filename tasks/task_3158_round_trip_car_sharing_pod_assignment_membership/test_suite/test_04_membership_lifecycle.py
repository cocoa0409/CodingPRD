"""Membership lifecycle: the freeze/revert cycle, gating and residual release."""
from test_helpers import (
    OPERATOR,
    PLATFORM,
    api_client,
    approve_member_with_membership,
    assert_membership,
    create_pod,
    create_reservation,
    create_vehicle,
    freeze_membership_via_split,
    create_sponsored_membership,
    get_success_data,
    make_member_headers,
    post_fuel_transaction,
    scheduled_order_from_incident,
    setup_confirmed_reservation,
    start_trip,
    validate_success,
)
from test_helpers.fixtures import ACCOUNT_ADMIN


def test_split_freezes_the_membership_and_preserves_the_prior_status():
    """PRD §3.4: "When a frozen cascade lands on a member, every membership of that member
    whose status is `ACTIVE` or `SUSPENDED` moves to `FROZEN`. Before the move, the status
    observed immediately beforehand is captured into `status_before_freeze`, which is one of
    `ACTIVE`, `SUSPENDED` or `NONE`, and the membership's `tier` is set to `FROZEN`."

    Design: Difficulty/non_linear_state_machine/membership_freeze_frozen_and_reopen_cycle
    """
    # PRD §3.13: the raw score is T1 + T2 + T3, where T1 is the member's
    # last_accident_fee_block, T2 is 1 when strikes is 0 and 2 otherwise, and T3 is
    # 1 when repair_cost_cents is at least 10000. The high-severity branch fires at
    # 4, so the fixture needs an anchor of 2 together with a repair cost of at
    # least 10000 to take the freeze cascade.
    member, membership = approve_member_with_membership(full_name="Hana Cycle",
                                                        last_accident_fee_block=2)
    # PRD §3.13 gates the split on the incident's member holding a membership in
    # `ACTIVE`, and §3.3 allows more than one non-primary row alongside the single
    # ACTIVE primary. A second, non-primary row keeps that gate satisfied while
    # the primary is driven into SUSPENDED, which is the status the cascade is
    # asserted to preserve.
    create_sponsored_membership(member["id"], tier="STANDARD", primary_flag=False)
    pod = create_pod(name="Campus Cycle", site_type="CAMPUS", capacity=4)
    vehicle = create_vehicle(pod["id"])
    # PRD §3.4: SUSPENDED "blocks new bookings only", so the reservation must be
    # taken while the membership is still ACTIVE and the suspension applied after;
    # a suspension raised first could never reach the reservation the fixture needs.
    reservation = create_reservation(member["id"], pod["id"], vehicle["id"], vehicle["version"])
    validate_success(api_client.suspend_membership(membership["id"], OPERATOR), 200)
    incident = get_success_data(
        api_client.create_incident(
            {
                "reservation_id": reservation["id"],
                "vehicle_id": vehicle["id"],
                "member_id": member["id"],
                "incident_type": "DAMAGE",
                "repair_cost_cents": 12000,
            },
            OPERATOR,
        ),
        201,
    )
    get_success_data(api_client.set_clock("2026-09-05T10:00:00Z", PLATFORM), 200)
    current = validate_success(api_client.get_incident(incident["id"], OPERATOR), 200)

    validate_success(
        api_client.party_split(
            incident["id"], {"expected_incident_version": current["version"]}, OPERATOR
        ),
        200,
    )

    frozen = validate_success(api_client.get_membership(membership["id"], OPERATOR), 200)
    assert_membership(frozen)
    assert frozen["status"] == "FROZEN", (
        f"SUSPENDED is one of the statuses the cascade freezes, got {frozen['status']}"
    )
    assert frozen["status_before_freeze"] == "SUSPENDED", (
        f"The preserved anchor must capture SUSPENDED, got {frozen['status_before_freeze']}"
    )
    assert frozen["tier"] == "FROZEN", (
        f"Freezing sets the tier to FROZEN, got {frozen['tier']}"
    )
    assert frozen["status"] != "ACTIVE", (
        "A frozen membership grants no booking rights, so it must not read ACTIVE"
    )


def test_split_from_active_preserves_active_and_reaches_assessed():
    """PRD §3.13: "The high-severity branch fires when the severity score is greater than or
    equal to 4, and it runs from `ASSESSED` to `FEE_CHARGED`."
    PRD §3.4: "If a membership was `ACTIVE` before it was frozen, a successful thaw returns
    it to `ACTIVE`"

    Design: Difficulty/non_linear_state_machine/membership_freeze_frozen_and_reopen_cycle
    """
    setup = freeze_membership_via_split(repair_cost_cents=12000, pod_name="Active Freeze Pod")

    frozen = setup["membership_after"]
    assert frozen["status"] == "FROZEN", (
        f"An ACTIVE membership must freeze on the cascade, got {frozen['status']}"
    )
    assert frozen["status_before_freeze"] == "ACTIVE", (
        f"The preserved anchor must capture ACTIVE, got {frozen['status_before_freeze']}"
    )
    assert setup["split"]["status"] in ("ASSESSED", "FEE_CHARGED"), (
        f"Assessment advances the incident off OPEN, got {setup['split']['status']}"
    )
    assert frozen["status"] != "ACTIVE", (
        "A membership that has been frozen must no longer read ACTIVE"
    )


def _sweep_into_overdue(setup, clock="2026-09-10T12:00:00Z"):
    """Take a live reservation whose window elapsed into the OVERDUE dimension.

    PRD §3.10 declares the sweep's own entry edges and the `status_before_overdue`
    capture, so the elapsed window is reached by the sweep itself rather than by a
    physical return (which PRD §3.8 makes the member's own gesture).
    """
    get_success_data(api_client.set_clock(clock, PLATFORM), 200)
    return validate_success(
        api_client.reopen_overdue(setup["reservation"]["id"], OPERATOR), 200
    )


def test_overdue_resolution_never_lands_on_the_preserved_returned_status():
    """PRD §3.10: "The resolution moves the reservation to `CLOSED`, never to `RETURNED`,
    regardless of what the preserved status was"
    PRD §3.10: "Before either edge fires, the status observed immediately beforehand is
    captured into `status_before_overdue` — one of `CONFIRMED`, `IN_USE`, `RETURNED` or
    `NONE` — and that capture is the preservation anchor."

    Design: Difficulty/non_linear_state_machine/reservation_overdue_revert_cyclic_dimension
    """
    setup = setup_confirmed_reservation(pod_name="Overdue Revert Pod")
    reopened = _sweep_into_overdue(setup)
    resolved = validate_success(
        api_client.resolve_overdue(setup["reservation"]["id"], OPERATOR), 200
    )

    assert reopened["status"] == "OVERDUE", (
        f"The sweep carries the reservation into the lateness dimension, got {reopened['status']}"
    )
    assert resolved["status"] == "CLOSED", (
        f"Resolution closes the reservation, got {resolved['status']}"
    )
    assert resolved["status"] != "RETURNED", (
        "Resolution never lands in RETURNED regardless of the preserved status"
    )
    assert resolved["status_before_overdue"] == "CONFIRMED", (
        f"The preserved anchor must survive to resolution, got {resolved['status_before_overdue']}"
    )
    assert resolved["charge_total_cents"] == 9944, (
        f"Both the reopen and the resolution edge recompute the charge, which equals 9944 "
        f"at the sample instant: got {resolved['charge_total_cents']}"
    )


def test_sweep_preserves_the_pre_lateness_status_and_recomputes_the_charge():
    """PRD §3.10: "Before either edge fires, the status observed immediately beforehand is
    captured into `status_before_overdue` — one of `CONFIRMED`, `IN_USE`, `RETURNED` or
    `NONE` — and that capture is the preservation anchor."
    PRD §3.10: "The sweep then sets the reservation's status to `OVERDUE`, recomputes
    `charge_total_cents` by the return charge calculation of §3.9, and increments the
    reservation's `version`."

    Design: Difficulty/non_linear_state_machine/reservation_overdue_revert_cyclic_dimension
    """
    setup = setup_confirmed_reservation(pod_name="Overdue Dimension Pod")
    before = setup["reservation"]
    reopened = _sweep_into_overdue(setup)

    assert reopened["status"] == "OVERDUE", (
        f"The sweep moves the reservation into the lateness dimension, got {reopened['status']}"
    )
    assert reopened["status_before_overdue"] == "CONFIRMED", (
        f"The capture records the status observed immediately beforehand, got "
        f"{reopened['status_before_overdue']}"
    )
    assert reopened["version"] > before["version"], (
        f"The sweep increments the reservation's version: {before['version']} → "
        f"{reopened['version']}"
    )
    assert reopened["charge_total_cents"] == 9944, (
        f"The sweep recomputes the charge against the elapsed window, giving the worked "
        f"sample figure 9944; got {reopened['charge_total_cents']}"
    )


def test_membership_close_succeeds_once_no_non_terminal_reservation_remains():
    """PRD §3.4: "A `UniversityAccountAdmin` closes a membership. Closing requires the
    membership to be in `ACTIVE` or `SUSPENDED`; requires the member to hold no reservation
    whose status is `HELD`, `CONFIRMED`, `IN_USE` or `OVERDUE`"
    PRD §3.4: "A close that would violate the primary-membership invariant is refused with
    `ERR_DUPLICATE_PRIMARY_MEMBERSHIP`."

    Design: Difficulty/cross_entity_state_dependency/membership_closure_gated_by_open_reservations
    """
    setup = setup_confirmed_reservation(
        pod_name="Campus Lock Clear", start_at="2026-09-05T00:00:00Z", end_at="2026-09-05T04:00:00Z"
    )
    start_trip(setup["member"]["id"], setup["reservation"]["id"], method="APP")
    get_success_data(
        api_client.return_reservation(
            setup["reservation"]["id"],
            {
                "returned_pod_id": setup["pod"]["id"],
                "returned_odometer_miles": 41000,
                "returned_fuel_level_pct": 80,
                "contamination_level": 0,
            },
            make_member_headers(setup["member"]["id"]),
        ),
        200,
    )
    # PRD §3.11: the close requires "a valid `FuelCardTransaction` whose `status` is
    # `POSTED` already posted against it — a reservation returned but not yet
    # refuelled cannot be closed."
    post_fuel_transaction(
        setup["member"]["id"], setup["reservation"]["id"], setup["vehicle"]["id"]
    )
    closed_reservation = validate_success(
        api_client.close_reservation(
            setup["reservation"]["id"], make_member_headers(setup["member"]["id"])
        ),
        200,
    )
    assert closed_reservation["status"] == "CLOSED", (
        f"The reservation must reach a terminal posture before the close, got "
        f"{closed_reservation['status']}"
    )

    closed = validate_success(
        api_client.close_membership(setup["membership"]["id"], ACCOUNT_ADMIN), 200
    )

    assert closed["status"] == "CLOSED", (
        f"With no live reservation the close proceeds, got {closed['status']}"
    )
    assert closed["residual_released_cents"] == 6840, (
        f"floor(8550 * 80 / 100) is 6840, got {closed['residual_released_cents']}"
    )


def test_membership_close_blocked_by_a_non_terminal_reservation():
    """PRD §3.4: "Closing requires the membership to be in `ACTIVE` or `SUSPENDED`; requires
    the member to hold no reservation whose status is `HELD`, `CONFIRMED`, `IN_USE` or
    `OVERDUE`"
    PRD §3.4: "A membership that is already in the terminal posture for this operation is
    refused with `ERR_ALREADY_TERMINAL` (HTTP 409), and a thaw attempted against a membership
    with a status other than `FROZEN` is refused with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/membership_closure_gated_by_open_reservations
    """
    setup = setup_confirmed_reservation(pod_name="Campus Lock")

    refused = api_client.close_membership(setup["membership"]["id"], ACCOUNT_ADMIN)

    assert refused.status_code == 409, (
        f"Expected HTTP 409 while a reservation is still live, got {refused.status_code}"
    )
    assert refused.json()["data"]["error_id"] == "ERR_INVALID_STATE", (
        f"An undeclared from-state returns the invalid-state error, got "
        f"{refused.json()['data']['error_id']}"
    )
    membership = validate_success(api_client.get_membership(setup["membership"]["id"], OPERATOR), 200)
    assert membership["status"] == "ACTIVE", (
        f"The refused close must leave the membership untouched, got {membership['status']}"
    )
    assert membership["residual_released_cents"] == 0, (
        f"A refused close releases nothing, got {membership['residual_released_cents']}"
    )
    reservation = validate_success(api_client.get_reservation(setup["reservation"]["id"], OPERATOR), 200)
    assert reservation["status"] == "CONFIRMED", (
        f"The live reservation is untouched by the refusal, got {reservation['status']}"
    )


def test_membership_close_releases_the_residual_exactly_once():
    """PRD §3.4: "The released amount is the floor of `membership_billing_cents` multiplied by
    80 percent. With the default billing of 8550 cents, the released residual is 6840 cents."
    PRD §3.4: "A second close of the same membership releases zero and is refused with
    `ERR_ALREADY_RELEASED` (HTTP 409)"

    Design: Corner/cross_cutting_layers/occupant_release_credits_wallet_once_on_thaw
    """
    setup = freeze_membership_via_split(repair_cost_cents=12000, pod_name="Residual Lot")
    # Thaw back to ACTIVE so the close's declared from-state is reached: PRD §3.4
    # says the FEE_CHARGED branch joins CLOSED through the completion of the order
    # raised from the incident, which is what returns the membership to its
    # preserved status. The incident's own trip is a CONFIRMED reservation, which
    # is not one of the postures the membership close counts as open, so the join
    # hop is what the close is evaluated against.
    order = scheduled_order_from_incident(
        setup["pod"]["id"], setup["incident"]["id"], reason="COLLISION_REPAIR", blocking=True,
        scheduled_start="2026-09-20T09:00:00Z", scheduled_end="2026-09-20T11:00:00Z",
    )
    get_success_data(api_client.start_maintenance_order(order["id"], OPERATOR), 200)
    get_success_data(api_client.complete_maintenance_order(order["id"], OPERATOR), 200)
    thawed = get_success_data(api_client.get_membership(setup["membership"]["id"], OPERATOR), 200)
    assert thawed["status"] in ("ACTIVE", "SUSPENDED"), (
        f"The join hop restores the preserved status before a close can be attempted, got "
        f"{thawed['status']}"
    )
    # PRD §3.13 credits the frozen member's wallet with the damage fee of record
    # and the branch amount, so the release under test is observed as a delta.
    before = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)

    closed = validate_success(api_client.close_membership(setup["membership"]["id"], ACCOUNT_ADMIN), 200)
    assert closed["residual_released_cents"] == 6840, (
        f"floor(8550 * 80 / 100) is 6840, got {closed['residual_released_cents']}"
    )

    second = api_client.close_membership(setup["membership"]["id"], ACCOUNT_ADMIN)
    assert second.status_code == 409, (
        f"Expected HTTP 409 on the repeat close, got {second.status_code}"
    )
    assert second.json()["data"]["error_id"] == "ERR_ALREADY_RELEASED", (
        f"The release guard is evaluated before the state preconditions, so a repeat close "
        f"surfaces as a release conflict rather than an invalid transition; got "
        f"{second.json()['data']['error_id']}"
    )
    member = validate_success(api_client.get_member(setup["member"]["id"], OPERATOR), 200)
    assert member["wallet_credit_cents"] == before["wallet_credit_cents"] + 6840, (
        f"The released residual is credited to the wallet exactly once on top of the "
        f"balance the freeze left behind: {before['wallet_credit_cents']} + 6840, got "
        f"{member['wallet_credit_cents']}"
    )