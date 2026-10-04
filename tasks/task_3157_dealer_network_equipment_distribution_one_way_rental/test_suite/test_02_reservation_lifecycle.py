"""Reservation lifecycle: initial state, confirmation gates, terminal lockdown,
single-unit occupancy, cancel idempotency, no-show timing, and audit events."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_confirmed_reservation,
    create_quoted_reservation,
    make_customer_headers,
    make_dealer_agent_headers,
    setup_active_rate,
    setup_confirmed_scenario,
    setup_customer,
    setup_dealer,
    setup_two_locations,
    setup_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_reservation_initial_state_is_quoted():
    """PRD §3.3: "The reservation is born `QUOTED` and carries a computed
    `price_snapshot` whose components — `quoted_rate_cents_per_day`,
    `applied_imbalance_factor`, `commission_rate`, and `total_quoted_cents` —
    come from the quoting engine described in §3.5; the snapshot also receives
    a `tow_check_result` that begins as `NOT_REQUIRED` and stays that way unless
    a towed equipment type is confirmed."
    PRD §3.3: "`rental_days` is the number of whole 24-hour days between pickup
    and drop-off rounded up, with a floor of one day."

    Design: Corner/state_machines/reservation_initial_state_is_quoted
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a, verify=False)
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-11T10:00:00Z")
    assert rsv["status"] == "QUOTED"
    assert rsv["tow_check_result"] == "NOT_REQUIRED"
    assert rsv["season"] == "OFF_PEAK"
    assert rsv["rental_days"] == 1


def test_terminal_state_lockdown_cancelled_reservation_rejects_confirm():
    """PRD §2.9: "A `Reservation` is `QUOTED`, `CONFIRMED`, `REASSIGNED`,
    `FULFILLED`, `CANCELLED`, `EXPIRED`, or `NO_SHOW` (the last four terminal)."
    PRD §2.8: "(6) State admissibility: the target entity's current state must
    permit the requested transition, else `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/terminal_state_lockdown_cancelled_reservation_rejects_confirm
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(customer, dealer_a, loc_b)
    validate_success(api_client.cancel_reservation(
        rsv["id"], make_customer_headers(customer["id"])))
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api_client.get_reservation(rsv["id"], TEST_USERS["admin"]))
    assert after["status"] == "CANCELLED"


def test_double_cancel_is_idempotency_violation():
    """PRD §2.8: "(6) State admissibility: the target entity's current state must
    permit the requested transition, else `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.9: "A `Reservation` is `QUOTED`, `CONFIRMED`, `REASSIGNED`,
    `FULFILLED`, `CANCELLED`, `EXPIRED`, or `NO_SHOW` (the last four terminal)."

    Design: Corner/state_machines/double_cancel_is_idempotency_violation
    """
    scenario = setup_confirmed_scenario()
    customer = scenario["customer"]
    rsv = scenario["reservation"]
    unit = scenario["unit"]
    validate_success(api_client.cancel_reservation(
        rsv["id"], make_customer_headers(customer["id"])))
    resp = api_client.cancel_reservation(
        rsv["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    # The single cancel released the hold exactly once.
    unit_after = validate_success(api_client.get_equipment_unit(
        unit["id"], TEST_USERS["admin"]))
    assert unit_after["status"] == "AVAILABLE"


def test_license_gate_blocks_confirm():
    """PRD §3.3: "License: the customer's `driver_license_verified` must be
    true, else `ERR_LICENSE_NOT_VERIFIED`."

    Design: Corner/validations/license_gate_blocks_confirm
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a, verify=False)
    rsv = create_quoted_reservation(customer, dealer_a, loc_b)
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_VERIFIED, expected_status=422)
    after = validate_success(api_client.get_reservation(rsv["id"], TEST_USERS["admin"]))
    assert after["status"] == "QUOTED"


def test_no_active_rate_blocks_reservation_create():
    """PRD §3.3: "Quoting requires an `ACTIVE` lane rate for the origin,
    destination, equipment type, and pickup season; without one the creation
    fails with `ERR_NO_ACTIVE_RATE`."

    Design: Corner/validations/no_active_rate_blocks_reservation_create
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    # Lane rate exists only as DRAFT (never activated).
    from test_helpers import create_lane_rate_payload
    draft = validate_success(api_client.create_lane_rate(
        create_lane_rate_payload(
            origin_location_id=loc_a["id"], dest_location_id=loc_b["id"]),
        TEST_USERS["pricing"]), expected_status=201)
    assert draft["status"] == "DRAFT"
    customer, _ = setup_customer(verify_dealer=dealer_a, verify=False)
    resp = api_client.create_reservation(
        {
            "customer_id": customer["id"],
            "origin_dealer_id": dealer_a["id"],
            "dest_location_id": loc_b["id"],
            "equipment_type": "TRUCK_10FT",
            "rental_kind": "ONE_WAY",
            "pickup_date": "2026-11-10T10:00:00Z",
            "dropoff_date": "2026-11-11T10:00:00Z",
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RATE, expected_status=422)


def test_invalid_date_range_rejected():
    """PRD §3.3: "The drop-off must fall strictly after the pickup, and the
    pickup must not lie in the past relative to the logical clock — a violation
    is `ERR_INVALID_DATE_RANGE` (HTTP 400)."

    Design: Corner/validations/invalid_date_range_rejected
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a, verify=False)
    resp = api_client.create_reservation(
        {
            "customer_id": customer["id"],
            "origin_dealer_id": dealer_a["id"],
            "dest_location_id": loc_b["id"],
            "equipment_type": "TRUCK_10FT",
            "rental_kind": "ONE_WAY",
            "pickup_date": "2026-11-12T10:00:00Z",
            "dropoff_date": "2026-11-10T10:00:00Z",
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=400)


def test_no_show_only_after_pickup_date():
    """PRD §2.5: "A logical clock governs every time-dependent rule: the minimum
    `pickup_date` at reservation creation, the no-show deadline, the
    `checkout_at` and `returned_at` stamps on a rental agreement, the
    `scheduled_after` instant on a reposition task, the idle-penalty measurement
    on a repositioning unit, and the projected-days computation behind a
    settlement preview."
    PRD §2.8: "date-range coherence (`ERR_INVALID_DATE_RANGE`, HTTP 400)"

    Design: Corner/endpoints/no_show_only_after_pickup_date
    """
    validate_success(api_client.set_clock("2026-11-10T09:00:00Z", TEST_USERS["admin"]))
    scenario = setup_confirmed_scenario(
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-11T10:00:00Z")
    rsv = scenario["reservation"]
    unit = scenario["unit"]
    # Before pickup_date: rejected.
    resp = api_client.mark_no_show(rsv["id"], TEST_USERS["admin"])
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=400)
    # After pickup_date passes: succeeds and releases the hold.
    validate_success(api_client.set_clock("2026-11-10T10:00:01Z", TEST_USERS["admin"]))
    after = validate_success(api_client.mark_no_show(rsv["id"], TEST_USERS["admin"]))
    assert after["status"] == "NO_SHOW"
    unit_after = validate_success(api_client.get_equipment_unit(
        unit["id"], TEST_USERS["admin"]))
    assert unit_after["status"] == "AVAILABLE"


def test_occ_stale_version_on_confirm_after_patch():
    """PRD §2.7: "Confirming a reservation requires the request to carry
    `expected_reservation_version`, the client's last observed `version` of that
    reservation; if the reservation's current `version` has advanced since the
    client last read it — for example because another writer reassigned the
    reservation to a different dealer and recomputed its price snapshot — the
    confirm is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
    client from acting on a quoted price and dealer it has not observed."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_confirm_after_patch
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(customer, dealer_a, loc_b)
    patched = validate_success(api_client.patch_reservation(
        rsv["id"], {"dropoff_date": "2026-11-12T10:00:00Z"},
        make_customer_headers(customer["id"])))
    # Confirm with the pre-patch version is stale.
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    # Confirm with the fresh version succeeds against the PATCHed window.
    confirmed = validate_success(api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": patched["version"]},
        make_customer_headers(customer["id"])))
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["rental_days"] == 2


def test_immediate_consistency_of_cascade_in_same_response():
    """PRD §3.3: "When all checks pass, confirmation freezes the quote: the
    pricing engine runs again against whatever lane rate is `ACTIVE` at the
    confirm instant, and the result — potentially different from the originally
    quoted total if the rate row changed between quote and confirm, which is
    intended — becomes the frozen `price_snapshot`, and the frozen value wins.
    The selected unit moves `AVAILABLE → HELD`, which pins it to this
    reservation without changing its holding dealer or the dealer's
    `allocated_unit_count`."

    Design: Corner/consistency_model/immediate_consistency_of_cascade_in_same_response
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    unit = setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(customer, dealer_a, loc_b)
    confirmed = validate_success(api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"])))
    # The confirm response itself shows the frozen state.
    assert confirmed["status"] == "CONFIRMED"
    assert isinstance(confirmed["price_snapshot"]["total_quoted_cents"], int)
    # Immediate follow-up read shows the held unit — no consistency lag.
    unit_after = validate_success(api_client.get_equipment_unit(
        unit["id"], TEST_USERS["admin"]))
    assert unit_after["status"] == "HELD"


def test_reservation_event_immutable_no_version_field():
    """PRD §2.4: "The exception is `ReservationEvent`, the append-only audit
    row: it carries `id` and `created_at` only; `updated_at` and `version` are
    absent because events are never modified after being appended."
    PRD §3.3: "A `ReservationEvent` of type `CREATED` is appended at birth."

    Design: Corner/entities/reservation_event_immutable_no_version_field
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a, verify=False)
    rsv = create_quoted_reservation(customer, dealer_a, loc_b)
    events, meta = validate_paginated(api_client.get_reservation_events(
        rsv["id"], make_customer_headers(customer["id"])))
    assert len(events) == 1
    event = events[0]
    assert event["event_type"] == "CREATED"
    assert "id" in event and "created_at" in event
    assert "version" not in event
    assert "updated_at" not in event


def test_unit_interval_occupation_blocks_second_confirm():
    """PRD §3.3: "Availability: an `AVAILABLE` unit of the requested type must
    exist at the origin dealer, free for the entire pickup-to-drop-off interval,
    else `ERR_NO_UNIT_AVAILABLE` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/unit_interval_occupation_blocks_second_confirm
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    unit = setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer_a, _ = setup_customer(verify_dealer=dealer_a, email_prefix="c15a")
    customer_b, _ = setup_customer(verify_dealer=dealer_a, email_prefix="c15b")
    r1 = create_confirmed_reservation(
        customer_a, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    r2 = create_quoted_reservation(
        customer_b, dealer_a, loc_b,
        pickup_date="2026-11-12T10:00:00Z", dropoff_date="2026-11-13T10:00:00Z")
    # The single unit is HELD for R1; R2's confirm finds nothing available.
    resp = api_client.confirm_reservation(
        r2["id"], {"expected_reservation_version": r2["version"]},
        make_customer_headers(customer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_UNIT_AVAILABLE, expected_status=409)
    # Cancelling R1 releases the hold; R2's confirm then succeeds.
    validate_success(api_client.cancel_reservation(
        r1["id"], make_customer_headers(customer_a["id"])))
    unit_mid = validate_success(api_client.get_equipment_unit(
        unit["id"], TEST_USERS["admin"]))
    assert unit_mid["status"] == "AVAILABLE"
    confirmed = validate_success(api_client.confirm_reservation(
        r2["id"], {"expected_reservation_version": r2["version"]},
        make_customer_headers(customer_b["id"])))
    assert confirmed["status"] == "CONFIRMED"
    unit_end = validate_success(api_client.get_equipment_unit(
        unit["id"], TEST_USERS["admin"]))
    assert unit_end["status"] == "HELD"


def test_unit_interval_occupation_hold_is_whole_interval_not_half_open():
    """PRD §3.3: "Availability: an `AVAILABLE` unit of the requested type must
    exist at the origin dealer, free for the entire pickup-to-drop-off interval,
    else `ERR_NO_UNIT_AVAILABLE` (HTTP 409)."
    PRD §3.3: "The selected unit moves `AVAILABLE → HELD`, which pins it to this
    reservation without changing its holding dealer or the dealer's
    `allocated_unit_count`."

    Design: Difficulty/resource_temporal_overlap/unit_interval_occupation_blocks_second_confirm
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    unit = setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer_a, _ = setup_customer(verify_dealer=dealer_a, email_prefix="c15c")
    customer_b, _ = setup_customer(verify_dealer=dealer_a, email_prefix="c15d")
    r1 = create_confirmed_reservation(customer_a, dealer_a, loc_b)
    # Adjacent (touching) window still fails: the HELD unit is invisible.
    r2 = create_quoted_reservation(
        customer_b, dealer_a, loc_b,
        pickup_date="2026-11-11T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    resp = api_client.confirm_reservation(
        r2["id"], {"expected_reservation_version": r2["version"]},
        make_customer_headers(customer_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NO_UNIT_AVAILABLE, expected_status=409)
    # The hold did not change the unit's dealer or the dealer's count.
    unit_after = validate_success(api_client.get_equipment_unit(
        unit["id"], TEST_USERS["admin"]))
    assert unit_after["status"] == "HELD"
    assert unit_after["current_dealer_id"] == dealer_a["id"]
    dealer_after = validate_success(api_client.get_dealer(
        dealer_a["id"], TEST_USERS["admin"]))
    assert dealer_after["allocated_unit_count"] == 1


def test_confirm_cancel_hold_release_conserves_fleet_availability():
    """PRD §3.3: "The selected unit moves `AVAILABLE → HELD`, which pins it to
    this reservation without changing its holding dealer or the dealer's
    `allocated_unit_count`."
    PRD §3.6: "any unit `HELD` for the reservation at the prior dealer is
    released back to `AVAILABLE` there"

    Design: Difficulty/compensating_invariant/confirm_cancel_hold_release_conserves_fleet_availability
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a, code_prefix="U-A")
    setup_unit(dealer_a, code_prefix="U-B")
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)

    def available_count():
        data, meta = validate_paginated(api_client.list_equipment_units(
            TEST_USERS["admin"],
            params={"current_dealer_id": dealer_a["id"], "status": "AVAILABLE"}))
        return meta["total_count"]

    assert available_count() == 2
    r1 = create_quoted_reservation(customer, dealer_a, loc_b)
    validate_success(api_client.confirm_reservation(
        r1["id"], {"expected_reservation_version": r1["version"]},
        make_customer_headers(customer["id"])))
    assert available_count() == 1
    validate_success(api_client.cancel_reservation(
        r1["id"], make_customer_headers(customer["id"])))
    # Invariant restored after the compensating cancel — no drift.
    assert available_count() == 2


def test_confirm_cancel_cycle_repeats_without_drift():
    """PRD §3.3: "The selected unit moves `AVAILABLE → HELD`, which pins it to
    this reservation without changing its holding dealer or the dealer's
    `allocated_unit_count`."
    PRD §3.6: "any unit `HELD` for the reservation at the prior dealer is
    released back to `AVAILABLE` there"

    Design: Difficulty/compensating_invariant/confirm_cancel_hold_release_conserves_fleet_availability
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a, code_prefix="U-C")
    setup_unit(dealer_a, code_prefix="U-D")
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)

    def available_count():
        data, meta = validate_paginated(api_client.list_equipment_units(
            TEST_USERS["admin"],
            params={"current_dealer_id": dealer_a["id"], "status": "AVAILABLE"}))
        return meta["total_count"]

    # A second confirm->cancel cycle must end at exactly the same count.
    for pickup, dropoff in (
        ("2026-11-10T10:00:00Z", "2026-11-11T10:00:00Z"),
        ("2026-11-12T10:00:00Z", "2026-11-13T10:00:00Z"),
    ):
        rsv = create_quoted_reservation(
            customer, dealer_a, loc_b, pickup_date=pickup, dropoff_date=dropoff)
        validate_success(api_client.confirm_reservation(
            rsv["id"], {"expected_reservation_version": rsv["version"]},
            make_customer_headers(customer["id"])))
        assert available_count() == 1
        validate_success(api_client.cancel_reservation(
            rsv["id"], make_customer_headers(customer["id"])))
        assert available_count() == 2
    dealer_after = validate_success(api_client.get_dealer(
        dealer_a["id"], TEST_USERS["admin"]))
    assert dealer_after["allocated_unit_count"] == 2
