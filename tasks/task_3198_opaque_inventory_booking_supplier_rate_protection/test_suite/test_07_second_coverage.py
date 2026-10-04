"""Second-coverage tests for difficulty-design instances.

Each test here is the second translation of an instance whose primary test
lives in an earlier file; the docstring tag maps back to the same instance.
"""
from test_helpers import (
    ADMIN,
    CS,
    FO,
    ApiErrorId,
    accept_bid,
    api_client,
    approve_batch,
    block_customer,
    booking_for_customer,
    create_batch,
    create_customer,
    create_disclosure_zone,
    create_property,
    create_rate_window,
    create_supplier,
    evaluate_bid,
    get_success_data,
    make_customer_headers,
    open_complaint,
    place_bid,
    reset_clock,
    resolve_case,
    setup_accepted_booking,
    setup_booking_with_service_failure,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPriceFloorSecondFacet:
    def test_fixed_acceptance_charges_the_computed_floor(self):
        """PRD §3.3: "Acceptance creates a `Booking` whose `opaque_bid_id`
        ties it back to the winning bid, in `CAPTURED`/`CONFIRMED`, carrying
        the bid's customer, the revealed property and its supplier, the
        consumed rate window via its `rate_window_id`, the copied stay dates,
        and a `charged_price_cents` equal to `bid_price_cents` for a `BID`-mode
        win or `computed_price_cents` for a `FIXED`-mode win."
        PRD §3.2: "The bid-level `computed_price_cents` is the minimum of those
        per-candidate floors, and it is the floor a `BID`-mode offer must meet
        or the exact price a `FIXED`-mode stay charges."

        Design: Difficulty/combinatorial_formula/opaque_price_floor_multi_input_tiered_mode_a
        """
        reset_clock()
        s1 = create_supplier(concealment_discount_min_pct=0.20)
        s2 = create_supplier(concealment_discount_min_pct=0.10)
        create_disclosure_zone(neighborhood_code="NB51", revealed_amenity_codes=["POOL"])
        p1 = create_property(s1["id"], star_rating=5, neighborhood_code="NB51",
                             published_rate_cents=25000)
        p2 = create_property(s2["id"], star_rating=4, neighborhood_code="NB51",
                             published_rate_cents=18000)
        create_rate_window(p1["id"], opaque_rate_cents=13000)
        create_rate_window(p2["id"], opaque_rate_cents=11000)
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB51")
        accepted = accept_bid(bid, customer)
        assert accepted["status"] == "ACCEPTED"
        booking = booking_for_customer(customer)
        # FIXED-mode win charges exactly the computed floor (19800).
        assert booking["charged_price_cents"] == 19800


class TestExhaustionSecondFacet:
    def test_exhausted_window_is_ineligible_for_selector(self):
        """PRD §3.3: "The consumed window's `rooms_sold` increments by 1, and
        if it thereby reaches `rooms_allocated` the window transitions `OPEN →
        EXHAUSTED` and leaves the eligible pool."

        Design: Difficulty/non_linear_state_machine/rate_window_exhausted_to_open_cycle_on_slot_release
        """
        supplier, prop, window, customer, bid, booking, case = (
            setup_booking_with_service_failure(
                "NB52", window_overrides={"rooms_allocated": 1}
            )
        )
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "EXHAUSTED"

        # While EXHAUSTED a fresh bid cannot fill from it.
        c2 = create_customer()
        bid2 = place_bid(c2, neighborhood_code="NB52")
        resp = evaluate_bid(bid2, c2)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"


class TestSuspendCascadeSecondFacet:
    def test_reinstate_does_not_reopen_closed_windows(self):
        """PRD §3.1: "Reinstating the supplier returns it to `ACTIVE` but
        deliberately does not reopen previously closed windows — the supplier
        must open new windows to sell again."

        Design: Difficulty/transitive_cascade/supplier_suspend_cascades_windows_then_bids
        """
        supplier, prop, window = setup_inventory("NB6b")
        get_success_data(api_client.suspend_supplier(supplier["id"], ADMIN))
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "CLOSED"

        reinstated = get_success_data(api_client.reinstate_supplier(supplier["id"], ADMIN))
        assert reinstated["status"] == "ACTIVE"
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "CLOSED"

        # With the only window still closed, a fresh bid rejects even though
        # the supplier is ACTIVE again.
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB6b")
        resp = evaluate_bid(bid, customer)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"


class TestRepeatWinSecondFacet:
    def test_third_win_does_not_raise_repeat_win_flag(self):
        """PRD §3.3: "Finally, acceptance recomputes the customer's
        `opaque_win_count_30d` — the count of that customer's `ACCEPTED` bids
        created within the trailing thirty days ending at the logical clock —
        and if that count exceeds three, the platform auto-creates an open
        `FraudFlag` with `reason_code` `REPEAT_WIN_RATE`, immediately adds
        twenty-five points to the customer's `fraud_score` (the flag's
        `score_delta` is applied at creation for this auto-created path), and
        recomputes `fraud_status` per §3.7; the customer's `version` increments
        as part of the cascade."

        Design: Difficulty/transitive_cascade/bid_acceptance_cascades_window_exhaustion_then_fraud_flag
        """
        reset_clock()
        supplier = create_supplier()
        create_disclosure_zone(neighborhood_code="NB53", revealed_amenity_codes=["POOL"])
        prop = create_property(supplier["id"], neighborhood_code="NB53")
        create_rate_window(prop["id"], rooms_allocated=5)
        customer = create_customer()
        for _ in range(3):
            bid = place_bid(customer, neighborhood_code="NB53")
            accept_bid(bid, customer)

        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        # Three wins do not exceed the threshold: no auto flag, no score change.
        assert cust["opaque_win_count_30d"] == 3
        assert cust["fraud_score"] == 0
        assert cust["fraud_status"] == "CLEAR"
        flags, _ = validate_paginated(
            api_client.list_fraud_flags(ADMIN, params={"customer_id": customer["id"]})
        )
        assert [f for f in flags if f["reason_code"] == "REPEAT_WIN_RATE"] == []


class TestStatePrioritySecondFacet:
    def test_withdrawn_bid_evaluation_rejected_even_when_customer_clear(self):
        """PRD §2.8: "Every request is validated in a fixed priority order, and
        the first failing check determines the error returned:"
        PRD §2.8: "5. State admissibility: the target entity must be in a state
        that permits the operation, else `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.2: "The customer may withdraw a `PENDING` bid at any time before
        evaluation — withdrawal moves it `PENDING → WITHDRAWN`, and only the
        bid's own customer may do so."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_fraud_gate_on_evaluate
        """
        supplier, prop, window = setup_inventory("NB54")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB54")
        get_success_data(api_client.withdraw_opaque_bid(
            bid["id"], make_customer_headers(customer["id"])
        ))
        fresh = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        resp = api_client.evaluate_opaque_bid(
            bid["id"], {"expected_customer_version": fresh["version"]}, ADMIN
        )
        # WITHDRAWN is not an admissible source state for evaluation.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestExhaustionBoundarySecondFacet:
    def test_window_below_allocation_remains_open_and_eligible(self):
        """PRD §3.3: "the window's `rooms_sold` is still below its
        `rooms_allocated`"
        PRD §3.3: "The consumed window's `rooms_sold` increments by 1, and if
        it thereby reaches `rooms_allocated` the window transitions `OPEN →
        EXHAUSTED` and leaves the eligible pool."

        Design: Difficulty/boundary_precision_check/rooms_sold_equal_rooms_allocated_exhausts_window
        """
        supplier, prop, window = setup_inventory(
            "NB55", window_overrides={"rooms_allocated": 2}
        )
        c1 = create_customer()
        bid1 = place_bid(c1, neighborhood_code="NB55")
        accept_bid(bid1, c1)
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        # 1 < 2: still OPEN and eligible.
        assert win["rooms_sold"] == 1
        assert win["status"] == "OPEN"

        c2 = create_customer()
        bid2 = place_bid(c2, neighborhood_code="NB55")
        accepted = accept_bid(bid2, c2)
        assert accepted["status"] == "ACCEPTED"
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["rooms_sold"] == 2
        assert win["status"] == "EXHAUSTED"


class TestEmptyBatchSecondFacet:
    def test_batch_with_booking_approves_and_settles(self):
        """PRD §3.6: "Approval — guarded by the optimistic-concurrency rule of
        §2.7 on the batch's `version` — moves the batch `DRAFT → APPROVED` and
        is permitted only when `booking_ids` is non-empty (an empty selection
        is rejected with `ERR_BATCH_EMPTY`, HTTP 422) and the supplier is not
        `TERMINATED`. Approval is the freezing point: every booking in the
        batch transitions `CONFIRMED → SETTLED`, and the final remittance
        variant replaces the provisional figures."

        Design: Difficulty/boundary_precision_check/empty_booking_ids_blocks_batch_approval
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB56")
        batch = create_batch(supplier["id"])
        assert booking["id"] in batch["booking_ids"]
        approved = approve_batch(batch)
        assert approved["status"] == "APPROVED"
        settled = get_success_data(api_client.get_booking(booking["id"], ADMIN))
        assert settled["fulfillment_status"] == "SETTLED"


class TestSupplierStatusDependencySecondFacet:
    def test_terminated_supplier_also_removes_candidates(self):
        """PRD §3.3: "A candidate is a property paired with one of its rate
        windows, eligible only when every one of the following holds: the
        property's `neighborhood_code` equals the bid's `neighborhood_code`;
        the property's `star_rating` is at least the bid's `min_star_rating`;
        the owning supplier is `ACTIVE`; the window belongs to the property and
        is `OPEN`; the window's `check_in_date` is on or before the bid's
        `check_in_date` and its `check_out_date` is on or after the bid's
        `check_out_date`; the window's `rooms_sold` is still below its
        `rooms_allocated`; and, when the bid carries an amenity filter, every
        requested amenity appears both in the property's `amenity_codes` and in
        the covering disclosure zone's `revealed_amenity_codes`."

        Design: Difficulty/cross_entity_state_dependency/bid_evaluation_depends_on_supplier_status
        """
        supplier, prop, window = setup_inventory("NB57")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB57")
        get_success_data(api_client.terminate_supplier(supplier["id"], ADMIN))
        resp = evaluate_bid(bid, customer)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        rows, _ = validate_paginated(
            api_client.list_bookings(ADMIN, params={"customer_id": customer["id"]})
        )
        assert rows == []


class TestServiceFailureDependencySecondFacet:
    def test_service_failure_succeeds_once_complaint_is_resolved(self):
        """PRD §3.4: "The service-failure path — exercised by a
        `CustomerService` operator marking a service failure on a `CONFIRMED`
        booking — requires a complaint case for that booking in category
        `SERVICE_FAILURE`, already `RESOLVED` with resolution `FULL_REFUND`. It
        refunds the customer the full `charged_price_cents`, moves the booking
        to `REFUNDED`/`SERVICE_FAILED`, zeroes both
        `supplier_remittance_cents` and `platform_commission_cents`, and
        releases the consumed inventory: the rate window's `rooms_sold`
        decrements by 1, and a window that had been `EXHAUSTED` reopens to
        `OPEN`, becoming eligible for the selector again."

        Design: Difficulty/cross_entity_state_dependency/booking_service_failure_depends_on_complaint_resolution
        """
        supplier, prop, window, customer, bid, booking, case = (
            setup_booking_with_service_failure("NB58")
        )
        result = get_success_data(api_client.mark_service_failure(booking["id"], CS))
        assert result["payment_status"] == "REFUNDED"
        assert result["fulfillment_status"] == "SERVICE_FAILED"


class TestOverlapSecondFacet:
    def test_overlapping_window_with_full_containment_qualifies(self):
        """PRD §3.3: "A candidate is a property paired with one of its rate
        windows, eligible only when every one of the following holds: the
        property's `neighborhood_code` equals the bid's `neighborhood_code`;
        the property's `star_rating` is at least the bid's `min_star_rating`;
        the owning supplier is `ACTIVE`; the window belongs to the property and
        is `OPEN`; the window's `check_in_date` is on or before the bid's
        `check_in_date` and its `check_out_date` is on or after the bid's
        `check_out_date`; the window's `rooms_sold` is still below its
        `rooms_allocated`; and, when the bid carries an amenity filter, every
        requested amenity appears both in the property's `amenity_codes` and in
        the covering disclosure zone's `revealed_amenity_codes`."

        Design: Difficulty/resource_temporal_overlap/bid_window_containment_vs_date_overlap_semantics
        """
        # A window larger than the stay fully contains it and qualifies — the
        # mirror image of the partial-overlap rejection.
        supplier, prop, window = setup_inventory(
            "NB59",
            window_overrides={
                "check_in_date": "2026-09-15T00:00:00Z",
                "check_out_date": "2026-11-15T00:00:00Z",
            },
        )
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB59")
        accepted = accept_bid(bid, customer)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["winning_rate_window_id"] == window["id"]


class TestRoomsConservationSecondFacet:
    def test_reopened_window_slot_is_refillable(self):
        """PRD §3.4: "the rate window's `rooms_sold` decrements by 1, and a
        window that had been `EXHAUSTED` reopens to `OPEN`, becoming eligible
        for the selector again."

        Design: Difficulty/compensating_invariant/window_rooms_conserved_across_fill_and_service_failure_refund
        """
        supplier, prop, window, customer, bid, booking, case = (
            setup_booking_with_service_failure(
                "NB60", window_overrides={"rooms_allocated": 1}
            )
        )
        get_success_data(api_client.mark_service_failure(booking["id"], CS))
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "OPEN"
        assert win["rooms_sold"] == 0

        # The released slot is immediately sellable again.
        c2 = create_customer()
        bid2 = place_bid(c2, neighborhood_code="NB60")
        accepted = accept_bid(bid2, c2)
        assert accepted["status"] == "ACCEPTED"
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["rooms_sold"] == 1
