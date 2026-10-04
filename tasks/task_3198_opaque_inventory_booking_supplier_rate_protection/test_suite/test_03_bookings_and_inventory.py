"""Booking state dimensions and rate-window inventory conservation tests."""
from test_helpers import (
    ADMIN,
    CS,
    FO,
    ApiErrorId,
    accept_bid,
    api_client,
    booking_for_customer,
    create_batch,
    create_customer,
    evaluate_bid,
    get_success_data,
    make_customer_headers,
    open_complaint,
    place_bid,
    reset_clock,
    resolve_case,
    setup_accepted_booking,
    setup_booking_with_goodwill,
    setup_booking_with_service_failure,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
    approve_batch,
)


class TestBookingParallelDimensions:
    def test_partial_refund_moves_only_payment_dimension(self):
        """PRD §3.4: "The booking carries two independent status dimensions
        precisely so that money and fulfillment can diverge: `payment_status`
        evolves `CAPTURED → REFUNDED` or `CAPTURED → PARTIALLY_REFUNDED`, while
        `fulfillment_status` evolves `CONFIRMED → SERVICE_FAILED` or `CONFIRMED
        → SETTLED`."
        PRD §3.4: "Granting goodwill refunds exactly `goodwill_credit_cents` to
        the customer and moves `payment_status` to `PARTIALLY_REFUNDED` while
        fulfillment stays `CONFIRMED`."

        Design: Difficulty/non_linear_state_machine/booking_parallel_payment_and_fulfillment_dimensions
        """
        supplier, prop, window, customer, bid, booking, case = setup_booking_with_goodwill(
            "NB4", 2000
        )
        assert booking["payment_status"] == "PARTIALLY_REFUNDED"
        assert booking["fulfillment_status"] == "CONFIRMED"

    def test_partially_refunded_booking_remains_settleable(self):
        """PRD §3.6: "the batch gathers every booking whose `supplier_id`
        matches the batch's supplier, whose `fulfillment_status` is
        `CONFIRMED`, and whose `check_out_date` falls on or after the period
        start and strictly before the period end"

        Design: Difficulty/non_linear_state_machine/booking_parallel_payment_and_fulfillment_dimensions
        """
        supplier, prop, window, customer, bid, booking, case = setup_booking_with_goodwill(
            "NB44", 2000
        )
        assert booking["fulfillment_status"] == "CONFIRMED"
        batch = create_batch(supplier["id"])
        assert booking["id"] in batch["booking_ids"]


class TestServiceFailurePath:
    def test_service_failure_full_refund_zeroes_economics(self):
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

        Design: Difficulty/compensating_invariant/window_rooms_conserved_across_fill_and_service_failure_refund
        """
        supplier, prop, window, customer, bid, booking, case = (
            setup_booking_with_service_failure(
                "NB14", window_overrides={"rooms_allocated": 2}
            )
        )
        assert booking["supplier_remittance_cents"] > 0

        result = get_success_data(api_client.mark_service_failure(booking["id"], CS))
        assert result["payment_status"] == "REFUNDED"
        assert result["fulfillment_status"] == "SERVICE_FAILED"
        assert result["supplier_remittance_cents"] == 0
        assert result["platform_commission_cents"] == 0

        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        # rooms_sold was 1 after acceptance; the compensate returns it to 0.
        assert win["rooms_sold"] == 0

    def test_exhausted_window_reopens_on_service_failure(self):
        """PRD §3.4: "the rate window's `rooms_sold` decrements by 1, and a
        window that had been `EXHAUSTED` reopens to `OPEN`, becoming eligible
        for the selector again."

        Design: Difficulty/non_linear_state_machine/rate_window_exhausted_to_open_cycle_on_slot_release
        """
        supplier, prop, window, customer, bid, booking, case = (
            setup_booking_with_service_failure(
                "NB5", window_overrides={"rooms_allocated": 1}
            )
        )
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "EXHAUSTED"
        assert win["rooms_sold"] == 1

        get_success_data(api_client.mark_service_failure(booking["id"], CS))
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "OPEN"
        assert win["rooms_sold"] == 0

    def test_service_failure_blocked_until_complaint_resolved(self):
        """PRD §3.4: "The service-failure path — exercised by a
        `CustomerService` operator marking a service failure on a `CONFIRMED`
        booking — requires a complaint case for that booking in category
        `SERVICE_FAILURE`, already `RESOLVED` with resolution `FULL_REFUND`."
        PRD §2.8: "5. State admissibility: the target entity must be in a state
        that permits the operation, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/booking_service_failure_depends_on_complaint_resolution
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB12")
        case = open_complaint(customer, booking, category="SERVICE_FAILURE",
                              description="walked to another hotel")
        get_success_data(api_client.start_review_complaint_case(case["id"], CS))
        # Case is UNDER_REVIEW, not RESOLVED → the booking action is not permitted.
        resp = api_client.mark_service_failure(booking["id"], CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        refreshed = get_success_data(api_client.get_booking(booking["id"], ADMIN))
        assert refreshed["payment_status"] == "CAPTURED"
        assert refreshed["fulfillment_status"] == "CONFIRMED"


class TestSettledBookingLockdown:
    def test_settled_booking_is_locked_against_service_failure(self):
        """PRD §3.4: "Once a booking's `fulfillment_status` reaches `SETTLED`
        through batch approval, it is locked: neither the service-failure path
        nor the goodwill path may touch it again, and attempts are rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/settled_booking_is_locked_against_service_failure
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB23")
        batch = create_batch(supplier["id"])
        approve_batch(batch)
        settled = get_success_data(api_client.get_booking(booking["id"], ADMIN))
        assert settled["fulfillment_status"] == "SETTLED"

        # A FULL_REFUND complaint may still resolve, but the booking is locked.
        case = open_complaint(customer, booking, category="SERVICE_FAILURE",
                              description="walked")
        resolve_case(case["id"], "FULL_REFUND")
        resp = api_client.mark_service_failure(booking["id"], CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        refreshed = get_success_data(api_client.get_booking(booking["id"], ADMIN))
        assert refreshed["fulfillment_status"] == "SETTLED"
        assert refreshed["payment_status"] == "CAPTURED"


class TestWindowExhaustionBoundary:
    def test_rooms_sold_equal_rooms_allocated_exhausts_window(self):
        """PRD §3.3: "The consumed window's `rooms_sold` increments by 1, and
        if it thereby reaches `rooms_allocated` the window transitions `OPEN →
        EXHAUSTED` and leaves the eligible pool."
        PRD §3.3: "the window's `rooms_sold` is still below its
        `rooms_allocated`"

        Design: Difficulty/boundary_precision_check/rooms_sold_equal_rooms_allocated_exhausts_window
        """
        supplier, prop, window = setup_inventory(
            "NB10", window_overrides={"rooms_allocated": 1}
        )
        c1 = create_customer()
        bid1 = place_bid(c1, neighborhood_code="NB10")
        accepted = accept_bid(bid1, c1)
        assert accepted["status"] == "ACCEPTED"
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["rooms_sold"] == 1
        assert win["status"] == "EXHAUSTED"

        # At equality the window is no longer eligible: a second bid rejects.
        c2 = create_customer()
        bid2 = place_bid(c2, neighborhood_code="NB10")
        resp = evaluate_bid(bid2, c2)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"

    def test_version_increments_on_every_mutation(self):
        """PRD §2.8: "Every resource carries a server-minted `id` formatted as
        a bare UUID with no type prefix, a `created_at` timestamp in ISO 8601
        UTC with three fractional digits, an `updated_at` timestamp of the same
        format refreshed on every mutation, and an integer `version` that
        starts at its initial value and increments by exactly 1 on every
        mutation of that resource — including automatic mutations caused by
        cascades (such as a supplier suspension closing rate windows) and by
        lifecycle events (such as a bid acceptance incrementing the customer's
        `version`)."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        supplier, prop, window = setup_inventory("NB38")
        assert window["version"] == 1
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB38")
        accept_bid(bid, customer)

        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["version"] == 2

        closed = get_success_data(api_client.close_rate_window(
            window["id"], {"expected_rate_window_version": win["version"]}, ADMIN
        ))
        assert closed["version"] == 3
        assert closed["status"] == "CLOSED"

    def test_derived_fields_reconcile_after_each_acceptance(self):
        """PRD §3.3: "Finally, acceptance recomputes the customer's
        `opaque_win_count_30d` — the count of that customer's `ACCEPTED` bids
        created within the trailing thirty days ending at the logical clock —
        and if that count exceeds three, the platform auto-creates an open
        `FraudFlag` with `reason_code` `REPEAT_WIN_RATE`, immediately adds
        twenty-five points to the customer's `fraud_score` (the flag's
        `score_delta` is applied at creation for this auto-created path), and
        recomputes `fraud_status` per §3.7; the customer's `version` increments
        as part of the cascade."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_after_each_mutation
        """
        supplier, prop, window = setup_inventory(
            "NB37", window_overrides={"rooms_allocated": 5}
        )
        customer = create_customer()
        b1 = place_bid(customer, neighborhood_code="NB37")
        accept_bid(b1, customer)
        b2 = place_bid(customer, neighborhood_code="NB37")
        accept_bid(b2, customer)

        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["rooms_sold"] == 2
        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        assert cust["opaque_win_count_30d"] == 2
        assert cust["fraud_status"] == "CLEAR"


class TestOccOnWindowClose:
    def test_rate_window_close_with_stale_version_returns_412(self):
        """PRD §2.7: "Closing a rate window requires
        `expected_rate_window_version`, holding the caller's last observed
        `version` of that window; a mismatch with the window's current
        `version` is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/rate_window_close_with_stale_version_returns_412
        """
        supplier, prop, window = setup_inventory("NB33")
        stale_version = window["version"]
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB33")
        # The fill mutates the window (rooms_sold) and advances its version.
        accept_bid(bid, customer)

        resp = api_client.close_rate_window(
            window["id"], {"expected_rate_window_version": stale_version}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "OPEN"
