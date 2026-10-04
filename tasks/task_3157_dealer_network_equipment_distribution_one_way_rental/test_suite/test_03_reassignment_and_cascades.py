"""Reassignment selector, dealer suspension sweep, and cross-entity cascades."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_confirmed_reservation,
    create_quoted_reservation,
    make_customer_headers,
    make_dealer_agent_headers,
    setup_active_rate,
    setup_customer,
    setup_dealer,
    setup_two_locations,
    setup_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


def _post_scores(scores):
    resp = api_client.post_performance_reviews(
        {"period": "2026-Q3", "scores": scores}, TEST_USERS["admin"])
    assert resp.status_code == 200, f"Setup failed: performance-reviews -> {resp.text}"


def test_reservation_reassign_cycle_multiple_hops_selector_ranking():
    """PRD §3.6: "Candidates are ranked by `performance_score` descending, then
    `allocated_unit_count` ascending, then `created_at` ascending as the final
    tie-break; entity ids are never used anywhere in the ranking."
    PRD §3.6: "reassigning a `REASSIGNED` reservation again is legal and simply
    appends another event"

    Design: Difficulty/non_linear_state_machine/reservation_reassign_cycle_multiple_hops
    """
    loc_a, loc_b = setup_two_locations()
    dealer_1 = setup_dealer(loc_a, code_prefix="D-61")
    dealer_2 = setup_dealer(loc_a, code_prefix="D-62")
    dealer_3 = setup_dealer(loc_a, code_prefix="D-63")
    setup_unit(dealer_1, code_prefix="U-61")
    unit_2 = setup_unit(dealer_2, code_prefix="U-62")
    unit_3 = setup_unit(dealer_3, code_prefix="U-63")
    _post_scores([
        {"dealer_id": dealer_1["id"], "performance_score": 50},
        {"dealer_id": dealer_2["id"], "performance_score": 80},
        {"dealer_id": dealer_3["id"], "performance_score": 80},
    ])
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_1)
    rsv = create_confirmed_reservation(
        customer, dealer_1, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    # First hop: score 80 tie between D2 and D3, D2 created earlier wins.
    hop1 = validate_success(api_client.reassign_reservation(rsv["id"], TEST_USERS["admin"]))
    assert hop1["status"] == "REASSIGNED"
    assert hop1["origin_dealer_id"] == dealer_2["id"]
    # Second hop: from D2 the remaining candidate is D3 (D1's unit is released
    # but D1's score 50 ranks below D3's 80 — and D1 is the original dealer,
    # eligible again, but lower-ranked).
    hop2 = validate_success(api_client.reassign_reservation(rsv["id"], TEST_USERS["admin"]))
    assert hop2["status"] == "REASSIGNED"
    assert hop2["origin_dealer_id"] == dealer_3["id"]
    # Holds tracked the hops.
    unit_2_after = validate_success(api_client.get_equipment_unit(
        unit_2["id"], TEST_USERS["admin"]))
    unit_3_after = validate_success(api_client.get_equipment_unit(
        unit_3["id"], TEST_USERS["admin"]))
    assert unit_2_after["status"] == "AVAILABLE"
    assert unit_3_after["status"] == "HELD"


def test_reservation_reassign_cycle_appends_events():
    """PRD §3.6: "A successful reassignment is transactional in effect: any unit
    `HELD` for the reservation at the prior dealer is released back to
    `AVAILABLE` there, a unit at the selected new dealer moves
    `AVAILABLE → HELD`, the reservation's `origin_dealer_id` and
    `origin_location_id` are updated, and — when the origin location actually
    changed — the `price_snapshot` is recomputed against the new lane's active
    rate. The reservation's `version` increments, its state becomes
    `REASSIGNED`, and a `ReservationEvent` of type `REASSIGNED` is appended
    recording `from_dealer_id`, `to_dealer_id`, and a free-text `note` giving
    the reason."

    Design: Difficulty/non_linear_state_machine/reservation_reassign_cycle_multiple_hops
    """
    loc_a, loc_b = setup_two_locations()
    dealer_1 = setup_dealer(loc_a, code_prefix="D-71")
    dealer_2 = setup_dealer(loc_a, code_prefix="D-72")
    dealer_3 = setup_dealer(loc_a, code_prefix="D-73")
    unit_1 = setup_unit(dealer_1, code_prefix="U-71")
    setup_unit(dealer_2, code_prefix="U-72")
    setup_unit(dealer_3, code_prefix="U-73")
    _post_scores([
        {"dealer_id": dealer_1["id"], "performance_score": 50},
        {"dealer_id": dealer_2["id"], "performance_score": 80},
        {"dealer_id": dealer_3["id"], "performance_score": 80},
    ])
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_1)
    rsv = create_confirmed_reservation(customer, dealer_1, loc_b)
    validate_success(api_client.reassign_reservation(rsv["id"], TEST_USERS["admin"]))
    validate_success(api_client.reassign_reservation(rsv["id"], TEST_USERS["admin"]))
    # The original hold was released by the first hop.
    unit_1_after = validate_success(api_client.get_equipment_unit(
        unit_1["id"], TEST_USERS["admin"]))
    assert unit_1_after["status"] == "AVAILABLE"
    # Two REASSIGNED events with the from/to dealer ids of each hop.
    events, meta = validate_paginated(api_client.get_reservation_events(
        rsv["id"], TEST_USERS["admin"]))
    reassigned = [e for e in events if e["event_type"] == "REASSIGNED"]
    assert len(reassigned) == 2
    assert (reassigned[0]["from_dealer_id"], reassigned[0]["to_dealer_id"]) == \
        (dealer_1["id"], dealer_2["id"])
    assert (reassigned[1]["from_dealer_id"], reassigned[1]["to_dealer_id"]) == \
        (dealer_2["id"], dealer_3["id"])
    final = validate_success(api_client.get_reservation(rsv["id"], TEST_USERS["admin"]))
    assert final["status"] == "REASSIGNED"


def test_dealer_suspend_mass_reassign_chain():
    """PRD §3.6: "Suspending a dealer — allowed only from `ACTIVE` — flips the
    dealer to `SUSPENDED` and immediately sweeps every reservation whose
    `origin_dealer_id` is that dealer and whose status is `CONFIRMED` or
    `REASSIGNED`: each such reservation auto-reassigns per the selector, and if
    the selector's candidate pool is empty for a given reservation, that
    reservation moves to `EXPIRED` instead, appending the corresponding event."

    Design: Difficulty/transitive_cascade/dealer_suspend_mass_reassign_chain
    """
    loc_a, loc_b = setup_two_locations()
    dealer_1 = setup_dealer(loc_a, code_prefix="D-81")
    dealer_2 = setup_dealer(loc_a, code_prefix="D-82")
    dealer_3 = setup_dealer(loc_a, code_prefix="D-83")
    _post_scores([
        {"dealer_id": dealer_2["id"], "performance_score": 70},
        {"dealer_id": dealer_3["id"], "performance_score": 60},
    ])
    unit_1 = setup_unit(dealer_1, code_prefix="U-81")
    unit_2 = setup_unit(dealer_2, code_prefix="U-82")
    setup_unit(dealer_3, code_prefix="U-83")
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_1)
    rsv = create_confirmed_reservation(
        customer, dealer_1, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    suspended = validate_success(api_client.suspend_dealer(
        dealer_1["id"], TEST_USERS["admin"]))
    assert suspended["status"] == "SUSPENDED"
    # The live reservation auto-reassigned to the highest-scoring candidate.
    rsv_after = validate_success(api_client.get_reservation(rsv["id"], TEST_USERS["admin"]))
    assert rsv_after["status"] == "REASSIGNED"
    assert rsv_after["origin_dealer_id"] == dealer_2["id"]
    # Hold moved: released at the suspended dealer, held at the target dealer.
    unit_1_after = validate_success(api_client.get_equipment_unit(
        unit_1["id"], TEST_USERS["admin"]))
    unit_2_after = validate_success(api_client.get_equipment_unit(
        unit_2["id"], TEST_USERS["admin"]))
    assert unit_1_after["status"] == "AVAILABLE"
    assert unit_2_after["status"] == "HELD"


def test_dealer_suspend_mass_reassign_appends_reassigned_event():
    """PRD §3.6: "Suspending a dealer — allowed only from `ACTIVE` — flips the
    dealer to `SUSPENDED` and immediately sweeps every reservation whose
    `origin_dealer_id` is that dealer and whose status is `CONFIRMED` or
    `REASSIGNED`: each such reservation auto-reassigns per the selector, and if
    the selector's candidate pool is empty for a given reservation, that
    reservation moves to `EXPIRED` instead, appending the corresponding event."

    Design: Difficulty/transitive_cascade/dealer_suspend_mass_reassign_chain
    """
    loc_a, loc_b = setup_two_locations()
    dealer_1 = setup_dealer(loc_a, code_prefix="D-91")
    dealer_2 = setup_dealer(loc_a, code_prefix="D-92")
    _post_scores([{"dealer_id": dealer_2["id"], "performance_score": 70}])
    setup_unit(dealer_1, code_prefix="U-91")
    setup_unit(dealer_2, code_prefix="U-92")
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_1)
    rsv = create_confirmed_reservation(customer, dealer_1, loc_b)
    validate_success(api_client.suspend_dealer(dealer_1["id"], TEST_USERS["admin"]))
    events, meta = validate_paginated(api_client.get_reservation_events(
        rsv["id"], TEST_USERS["admin"]))
    reassigned = [e for e in events if e["event_type"] == "REASSIGNED"]
    assert len(reassigned) == 1
    assert reassigned[0]["from_dealer_id"] == dealer_1["id"]
    assert reassigned[0]["to_dealer_id"] == dealer_2["id"]


def test_no_reassignment_candidate_error():
    """PRD §3.6: "An explicit reassignment with an empty pool is rejected with
    `ERR_NO_REASSIGNMENT_CANDIDATE` (HTTP 409)."

    Design: Corner/validations/no_reassignment_candidate_error
    """
    loc_a, loc_b = setup_two_locations()
    dealer_1 = setup_dealer(loc_a, code_prefix="D-V5A")
    dealer_2 = setup_dealer(loc_a, code_prefix="D-V5B")
    setup_unit(dealer_1, code_prefix="U-V5")
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_1)
    rsv = create_confirmed_reservation(customer, dealer_1, loc_b)
    # The only other same-zone dealer has no AVAILABLE unit of the type.
    resp = api_client.reassign_reservation(rsv["id"], TEST_USERS["admin"])
    validate_error(resp, ApiErrorId.ERR_NO_REASSIGNMENT_CANDIDATE, expected_status=409)
    rsv_after = validate_success(api_client.get_reservation(rsv["id"], TEST_USERS["admin"]))
    assert rsv_after["origin_dealer_id"] == dealer_1["id"]


def test_confirm_blocked_when_origin_dealer_suspended():
    """PRD §3.6: "Reservations still `QUOTED` are deliberately not swept; they
    remain `QUOTED`, and their confirm is subsequently blocked at the
    dealer-posture gate with `ERR_DEALER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_origin_dealer_suspended
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    suspended = validate_success(api_client.suspend_dealer(
        dealer_a["id"], TEST_USERS["admin"]))
    assert suspended["status"] == "SUSPENDED"
    # The QUOTED reservation survived the sweep, but its confirm is gated.
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_DEALER_SUSPENDED, expected_status=409)


def test_confirm_blocked_when_origin_dealer_suspended_reservation_stays_quoted():
    """PRD §3.6: "Reservations still `QUOTED` are deliberately not swept; they
    remain `QUOTED`, and their confirm is subsequently blocked at the
    dealer-posture gate with `ERR_DEALER_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_when_origin_dealer_suspended
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    validate_success(api_client.suspend_dealer(dealer_a["id"], TEST_USERS["admin"]))
    # The reservation itself was untouched by the sweep.
    rsv_after = validate_success(api_client.get_reservation(
        rsv["id"], TEST_USERS["admin"]))
    assert rsv_after["status"] == "QUOTED"
    assert rsv_after["origin_dealer_id"] == dealer_a["id"]
    resp = api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_DEALER_SUSPENDED, expected_status=409)


def test_return_cascade_unit_handoff_imbalance_future_quote():
    """PRD §3.2: "The imbalance factor is 1.0 plus one half of the sum of net
    flow and deficit, divided by the total fleet of type T (units in any status
    other than `RETIRED`), with the divisor floored at 1 so an empty fleet
    cannot divide by zero; the result is rounded half-up to 4 decimal places."
    PRD §3.5: "When the row's forward-looking `imbalance_factor` exceeds 1.0 —
    the threshold that signals destination accumulation — the row's
    `reposition_surcharge_cents` is added to the daily rate; a factor of exactly
    1.0 does not trigger the surcharge."

    Design: Difficulty/transitive_cascade/return_cascade_unit_handoff_imbalance_future_quote
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a, code_prefix="D-A7")
    dealer_b = setup_dealer(loc_b, code_prefix="D-B7")
    unit_1 = setup_unit(dealer_a, code_prefix="U-7001")
    setup_unit(dealer_a, code_prefix="U-7002")
    rate = setup_active_rate(loc_a, loc_b, base_rate_cents=5000,
                             reposition_surcharge_cents=2000)
    customer_a, _ = setup_customer(verify_dealer=dealer_a, email_prefix="c7a")
    # One completed one-way A->B return: net_flow 1 over fleet_total 2.
    rsv_a = create_confirmed_reservation(
        customer_a, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-11T10:00:00Z")
    agreement = validate_success(api_client.create_rental_agreement(
        {"reservation_id": rsv_a["id"], "equipment_unit_id": unit_1["id"],
         "return_location_id": loc_b["id"]},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    validate_success(api_client.return_rental_agreement(
        agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
    # Hop 1: the returned unit landed at the destination with dealer handoff.
    unit_1_after = validate_success(api_client.get_equipment_unit(
        unit_1["id"], TEST_USERS["admin"]))
    assert unit_1_after["current_location_id"] == loc_b["id"]
    assert unit_1_after["current_dealer_id"] == dealer_b["id"]
    # Hop 2: factor = 1 + 0.5 * (1 + 0) / 2 = 1.25 > 1.0.
    rate_after = validate_success(api_client.get_lane_rate(
        rate["id"], TEST_USERS["pricing"]))
    assert rate_after["imbalance_factor"] == pytest.approx(1.25, abs=1e-9)
    # Hop 3: the surcharge flips ON for the next quote on the lane.
    customer_b, _ = setup_customer(verify_dealer=dealer_a, email_prefix="c7b")
    rsv_b = create_quoted_reservation(
        customer_b, dealer_a, loc_b,
        pickup_date="2026-11-20T10:00:00Z", dropoff_date="2026-11-21T10:00:00Z")
    assert rsv_b["price_snapshot"]["quoted_rate_cents_per_day"] == 7000
    assert rsv_b["price_snapshot"]["total_quoted_cents"] == 7000


def test_return_cascade_factor_at_threshold_still_no_surcharge():
    """PRD §3.5: "When the row's forward-looking `imbalance_factor` exceeds 1.0
    — the threshold that signals destination accumulation — the row's
    `reposition_surcharge_cents` is added to the daily rate; a factor of exactly
    1.0 does not trigger the surcharge."

    Design: Difficulty/transitive_cascade/return_cascade_unit_handoff_imbalance_future_quote
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a, code_prefix="D-F7")
    dealer_b = setup_dealer(loc_b, code_prefix="D-F8")
    setup_unit(dealer_a, code_prefix="U-F1")
    rate = setup_active_rate(loc_a, loc_b, base_rate_cents=5000,
                             reposition_surcharge_cents=2000)
    customer_a, _ = setup_customer(verify_dealer=dealer_a, email_prefix="cf1")
    # No completed one-way returns yet: factor sits at exactly 1.0.
    rate_now = validate_success(api_client.get_lane_rate(
        rate["id"], TEST_USERS["pricing"]))
    assert rate_now["imbalance_factor"] == pytest.approx(1.0, abs=1e-9)
    # A factor of exactly 1.0 does not trigger the surcharge.
    rsv = create_quoted_reservation(
        customer_a, dealer_a, loc_b,
        pickup_date="2026-11-20T10:00:00Z", dropoff_date="2026-11-21T10:00:00Z")
    assert rsv["price_snapshot"]["quoted_rate_cents_per_day"] == 5000
    assert rsv["price_snapshot"]["total_quoted_cents"] == 5000
