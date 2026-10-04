"""Breadth tests: state-machine shapes — initial states, invalid transitions, liveness."""
from test_helpers import (
    ATTRACTION_HOST,
    ApiErrorId,
    DEAL_DESK_CLERK,
    PLATFORM_ADMIN,
    FINANCE_ADMIN,
    RECEIVING_MANAGER,
    SERVICE_TECHNICIAN,
    create_bay_booking,
    create_boat_unit,
    create_member,
    create_open_attraction,
    create_order_fulfillment,
    create_service_order,
    create_store,
    create_waiver,
    get_success_data,
    request_session,
    set_clock,
    setup_delivered_deal,
    validate_error,
    validate_paginated,
)


# --- state_machines/attraction_session_initial_state_is_requested ----------

def test_a_session_request_settles_to_confirmed_within_the_same_call(api):
    """PRD §3.1: "Every session is created in `REQUESTED` and is then resolved
    immediately by the server without a second client call: it confirms, it
    parks, or it fails."
    PRD §3.1: "Committing capacity is a two-sided mutation. Confirming a session
    adds its `party_size` to the venue's `in_use_units`."
    PRD §2.8.1: "The base is the per-guest rate multiplied by that band
    multiplier."

    Design: Corner/state_machines/attraction_session_initial_state_is_requested
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=20, dwell_cost_minutes=30)
    member = create_member(api, store["id"], email="m_is@x.com",
                           full_name="Isla Reed")

    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=2, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    assert session["status"] == "CONFIRMED", (
        f"the REQUESTED state resolves to CONFIRMED, got {session['status']}"
    )
    assert session["dwell_charge_minutes"] > 0, (
        "a confirmed session is charged dwell minutes; got "
        f"{session['dwell_charge_minutes']}"
    )
    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 2, (
        f"the confirmation consumed two units of capacity; got {venue['in_use_units']}"
    )


# --- state_machines/check_in_from_requested_returns_invalid_state ----------

def test_checking_in_a_waitlisted_session_is_refused_as_an_invalid_state(api):
    """PRD §2.11: "a target entity not in any source state the requested transition declares yields"
    PRD §3.1: "When the venue's `in_use_units` plus the party size would exceed
    its `capacity_units` but the store's posture is still `OPEN` rather than
    `FROZEN`, the session enters `WAITLIST_FALLBACK`."

    Design: Corner/state_machines/check_in_from_requested_returns_invalid_state
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=1, dwell_cost_minutes=30)
    first_member = create_member(api, store["id"], email="m_it1@x.com",
                                 full_name="Ivy Tarr")
    second_member = create_member(api, store["id"], email="m_it2@x.com",
                                  full_name="Ian Tarr")

    get_success_data(
        request_session(api, store["id"], attraction["id"], first_member["id"],
                        party_size=1, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    waitlisted = get_success_data(
        request_session(api, store["id"], attraction["id"], second_member["id"],
                        party_size=1, slot_start_utc="2026-11-01T12:00:00Z",
                        slot_end_utc="2026-11-01T13:00:00Z"),
        201,
    )
    assert waitlisted["status"] == "WAITLIST_FALLBACK", (
        f"the state under test is the waitlist branch; got {waitlisted['status']}"
    )

    response = api.check_in_session(waitlisted["id"], ATTRACTION_HOST)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    unchanged = get_success_data(api.get_session(waitlisted["id"], ATTRACTION_HOST), 200)
    assert unchanged["status"] == "WAITLIST_FALLBACK", (
        f"the rejected check-in did not move the row; got {unchanged['status']}"
    )
    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 1, (
        f"the waitlisted party consumes no capacity; got {venue['in_use_units']}"
    )


# --- state_machines/cancelled_session_cannot_be_cancelled_again ------------

def test_a_second_cancel_is_refused_and_releases_no_capacity_twice(api):
    """PRD §2.11: "a target entity already in a terminal state yields
    `ERR_ALREADY_TERMINAL` (HTTP 409)."
    PRD §3.1: "cancelling a `CONFIRMED` session subtracts its `party_size` from
    the venue's `in_use_units`, recomputes the committed and free minute totals,
    and re-evaluates the posture."

    Design: Corner/state_machines/cancelled_session_cannot_be_cancelled_again
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=20, dwell_cost_minutes=30)
    member = create_member(api, store["id"], email="m_tt@x.com",
                           full_name="Tess Toll")
    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=3, slot_start_utc="2026-11-01T10:00:00Z",
                        slot_end_utc="2026-11-01T11:00:00Z"),
        201,
    )
    get_success_data(api.cancel_session(session["id"], ATTRACTION_HOST), 200)

    retry = api.cancel_session(session["id"], ATTRACTION_HOST)
    validate_error(retry, ApiErrorId.ERR_ALREADY_TERMINAL, 409)

    read_back = get_success_data(api.get_session(session["id"], ATTRACTION_HOST), 200)
    assert read_back["status"] == "CANCELLED", (
        f"the retry changed nothing, got {read_back['status']}"
    )
    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 0, (
        f"capacity was released exactly once; got {venue['in_use_units']}"
    )


# --- state_machines/settled_deal_rejects_further_funding -------------------

def test_a_settled_deal_refuses_a_later_refund_as_an_invalid_state(api):
    """PRD §3.4: "A refund is available to a"
    PRD §2.11: "a target entity not in any source state the requested transition declares yields"

    Design: Corner/state_machines/settled_deal_rejects_further_funding
    """
    ctx = setup_delivered_deal(api)
    deal = get_success_data(api.get_deal(ctx["deal"]["id"], DEAL_DESK_CLERK), 200)
    settled = get_success_data(
        api.settle_deal(deal["id"], {"expected_deal_version": deal["version"]},
                        FINANCE_ADMIN),
        200,
    )
    assert settled["deal_stage"] == "SETTLED"
    # A plain read against the deal auto-delivers nothing at SETTLED, but it does
    # re-serve the row; take the fresh version so the refund reaches its state
    # check rather than a stale-version rejection.
    current = get_success_data(api.get_deal(deal["id"], DEAL_DESK_CLERK), 200)

    response = api.refund_deal(
        deal["id"], {"expected_deal_version": current["version"]}, FINANCE_ADMIN
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    unchanged = get_success_data(api.get_deal(deal["id"], DEAL_DESK_CLERK), 200)
    assert unchanged["deal_stage"] == "SETTLED"
    assert unchanged["funding_status"] == "FUNDED", (
        f"a settled deal holds its funding dimension; got {unchanged['funding_status']}"
    )


# --- state_machines/bay_booking_reserved_to_checked_in_to_completed --------

def test_a_bay_booking_reaches_completed_only_through_the_fulfillment_release(api):
    """PRD §3.6: "When the load arrives, the manager checks the booking in,
    moving it from `RESERVED` to `CHECKED_IN`."
    PRD §3.6: "when the service order the fulfilment consumed is now delivered —
    closes the booking from `CHECKED_IN` to `COMPLETED`."

    Design: Corner/state_machines/bay_booking_reserved_to_checked_in_to_completed
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_bv@x.com",
                           full_name="Bay Voss")
    unit = create_boat_unit(api, store["id"], stock_no="BU-BV", model_name="Bay 170",
                            unit_price_cents=4_000_000, unit_condition="NEW",
                            hull_id_no="HINBV0000001", motor_price_cents=0,
                            trailer_price_cents=0)
    order = create_service_order(api, store["id"], unit["id"],
                                 order_kind="OVERSIZE_LOADING", promised_lead_days=3)
    booking = create_bay_booking(api, store["id"], member["id"], order["id"])
    fulfillment = create_order_fulfillment(api, store["id"], member["id"], order["id"],
                                           booking["id"], booking["version"])

    # PRD §3.6: the check-in is what releases the linked OVERSIZE_LOADING order
    # from SCHEDULED to IN_PROGRESS, so it precedes the order's own hops.
    checked = get_success_data(api.check_in_bay_booking(booking["id"],
                                                        RECEIVING_MANAGER), 200)
    get_success_data(api.schedule_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    get_success_data(api.start_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    get_success_data(api.complete_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    get_success_data(api.deliver_service_order(order["id"], SERVICE_TECHNICIAN), 200)
    assert checked["status"] == "CHECKED_IN", (
        f"check-in moves the booking to CHECKED_IN; got {checked['status']}"
    )
    still_pending = get_success_data(
        api.get_order_fulfillment(fulfillment["id"], RECEIVING_MANAGER), 200
    )
    assert still_pending["status"] == "READY_FOR_RELEASE", (
        f"the check-in does not touch the fulfillment; got {still_pending['status']}"
    )

    released = get_success_data(
        api.release_order_fulfillment(
            fulfillment["id"], {"rm_cross_check_code": "rm_7741"}, RECEIVING_MANAGER
        ),
        200,
    )
    assert released["fulfilled_at_utc"] is not None, (
        "a successful release stamps fulfilled_at_utc"
    )
    closed = get_success_data(api.get_bay_booking(booking["id"], RECEIVING_MANAGER), 200)
    assert closed["status"] == "COMPLETED", (
        "the last hop is produced by the fulfillment release, not by a direct "
        f"call; got {closed['status']}"
    )


# --- state_machines/no_show_transition_fires_only_from_the_ops_run ---------

def test_a_finished_slot_is_untouched_until_the_checkpoint_writes_the_strike(api):
    """PRD §3.2: "A `CONFIRMED` session that reaches a checkpoint with its
    `slot_end_utc` already behind the store clock and no check-in on record is
    marked `NO_SHOW`: the party's capacity is released, and the member's
    `no_show_strikes` at that venue increments."
    PRD §3.9: "Internally it advances `permit_remit_epoch` by one, stamps
    `last_ops_run_at`, expires every `SIGNED` waiver whose `expires_on` has
    fallen behind the clock, promotes parked sessions and parked registrations
    where the waiting-order rule allows, marks no-shows for confirmed or
    in-progress occupancy whose slot ended unchecked."

    Design: Corner/state_machines/no_show_transition_fires_only_from_the_ops_run
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=20, dwell_cost_minutes=30)
    member = create_member(api, store["id"], email="m_ns@x.com",
                           full_name="Nita Shor")
    session = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=2, slot_start_utc="2026-08-20T10:00:00Z",
                        slot_end_utc="2026-08-20T11:00:00Z"),
        201,
    )

    before = get_success_data(api.get_session(session["id"], ATTRACTION_HOST), 200)
    assert before["status"] == "CONFIRMED", (
        "the slot ended before the 2026-09-01 clock but nothing has swept it yet; "
        f"got {before['status']}"
    )

    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)

    after = get_success_data(api.get_session(session["id"], ATTRACTION_HOST), 200)
    assert after["status"] == "NO_SHOW", (
        f"the checkpoint is what writes the no-show; got {after['status']}"
    )
    assert after["no_show_strikes"] == 1, (
        f"the member's strike count at that venue increments; got "
        f"{after['no_show_strikes']}"
    )
    venue = get_success_data(api.get_attraction(attraction["id"], ATTRACTION_HOST), 200)
    assert venue["in_use_units"] == 0, (
        f"the no-show released the held capacity; got {venue['in_use_units']}"
    )


# --- state_machines/post_event_happens_before_strike_decay -----------------

def test_completing_a_later_session_resets_the_epoch_and_carries_the_next_request(api):
    """PRD §3.2: "The member is not permanently barred: the epoch moves.
    Completing any session at the attraction resets `strike_epoch_started_at`."
    PRD §2.8.1: "only no-show sessions whose `slot_start_utc` is at or after that
    epoch are counted, so completed sessions are excluded from the count even
    though they do move the epoch."

    Design: Corner/state_machines/post_event_happens_before_strike_decay
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    attraction = create_open_attraction(api, store["id"], attraction_type="AQUARIUM",
                                        capacity_units=20, dwell_cost_minutes=30)
    member = create_member(api, store["id"], email="m_sd@x.com",
                           full_name="Sol Dune")

    missed = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=1, slot_start_utc="2026-08-20T10:00:00Z",
                        slot_end_utc="2026-08-20T11:00:00Z"),
        201,
    )
    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)
    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)

    swept = get_success_data(api.get_session(missed["id"], ATTRACTION_HOST), 200)
    assert swept["status"] == "NO_SHOW"
    assert swept["no_show_strikes"] == 1, (
        "a second checkpoint does not double the strike; got "
        f"{swept['no_show_strikes']}"
    )

    # Move the clock so the next slot has genuinely arrived, then complete it.
    set_clock(api, "2026-09-02T11:00:00Z")
    attended = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=1, slot_start_utc="2026-09-02T10:00:00Z",
                        slot_end_utc="2026-09-02T11:00:00Z"),
        201,
    )
    get_success_data(api.check_in_session(attended["id"], ATTRACTION_HOST), 200)
    completed = get_success_data(
        api.complete_session(attended["id"], ATTRACTION_HOST), 200
    )
    assert completed["status"] == "COMPLETED", (
        f"the completed session is what moves the epoch; got {completed['status']}"
    )

    admitted = get_success_data(
        request_session(api, store["id"], attraction["id"], member["id"],
                        party_size=1, slot_start_utc="2026-12-01T10:00:00Z",
                        slot_end_utc="2026-12-01T11:00:00Z"),
        201,
    )
    assert admitted["status"] == "CONFIRMED", (
        "the completion reset carried the next request, so the effective strike "
        f"count is zero rather than one; got {admitted['status']}"
    )


# --- state_machines/waiver_supersede_and_expiry_are_system_driven ----------

def test_a_newer_signing_supersedes_the_older_waiver_and_only_the_clock_expires_one(api):
    """PRD §3.2: "A new waiver for a member and scope is not additive: the moment
    a fresh `SIGNED` waiver is written for a member and scope that already has
    one, the older row moves from `SIGNED` to `SUPERSEDED`, so exactly one live
    waiver per member per scope is ever valid."
    PRD §3.2: "during an ops-run sweep, any `SIGNED` waiver whose `expires_on`
    has fallen before the store clock's current instant moves to `EXPIRED`."
    PRD §3.2: "At creation the server computes `expires_on` as the signature
    instant plus the term in whole days."

    Design: Corner/state_machines/waiver_supersede_and_expiry_are_system_driven
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    store = create_store(api)
    member = create_member(api, store["id"], email="m_wv@x.com",
                           full_name="Wade Vale")
    older = create_waiver(api, store["id"], member["id"], activity_scope="SIMULATOR",
                          signed_at_utc="2026-01-01T00:00:00Z", waiver_term_days=365)
    newer = create_waiver(api, store["id"], member["id"], activity_scope="SIMULATOR",
                          signed_at_utc="2026-09-02T00:00:00Z", waiver_term_days=365)

    assert newer["status"] == "SIGNED", f"the fresh waiver is live; got {newer['status']}"
    assert newer["expires_on"].startswith("2027-09-02"), (
        "expires_on is the signature instant plus the term in whole days; got "
        f"{newer['expires_on']}"
    )
    superseded = get_success_data(api.get_waiver(older["id"], ATTRACTION_HOST), 200)
    assert superseded["status"] == "SUPERSEDED", (
        f"the newer signing superseded the older row; got {superseded['status']}"
    )

    get_success_data(api.ops_run(store["id"], PLATFORM_ADMIN), 200)
    still_signed = get_success_data(api.get_waiver(newer["id"], ATTRACTION_HOST), 200)
    assert still_signed["status"] == "SIGNED", (
        "the newer waiver expires a year after the clock, so the sweep leaves it "
        f"alone; got {still_signed['status']}"
    )

    rows, meta = validate_paginated(
        api.list_waivers(ATTRACTION_HOST,
                         params={"member_id": member["id"],
                                 "activity_scope": "SIMULATOR"})
    )
    assert meta["total_count"] == 2, (
        "both terminal and non-terminal waivers remain queryable; got "
        f"{meta['total_count']}"
    )
    assert len(rows) == 2
