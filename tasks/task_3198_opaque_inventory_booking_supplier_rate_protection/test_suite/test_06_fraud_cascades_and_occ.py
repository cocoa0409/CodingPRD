"""Fraud scoring, flag disposition, and supplier cascade tests."""
from test_helpers import (
    ADMIN,
    CS,
    FO,
    ApiErrorId,
    accept_bid,
    api_client,
    approve_batch,
    block_customer,
    create_batch,
    create_customer,
    create_manual_flag,
    create_property,
    create_rate_window,
    create_supplier,
    evaluate_bid,
    get_success_data,
    make_customer_headers,
    place_bid,
    reset_clock,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFraudScoreDualDirection:
    def test_uphold_applies_delta_and_status_thresholds(self):
        """PRD §3.7: "Status derives from score by fixed thresholds: a score of
        fifty or more yields `BLOCKED`; a score of twenty or more but below
        fifty yields `WATCH`; anything lower is `CLEAR`."
        PRD §3.7: "Upholding adds the flag's `score_delta` to the customer's
        `fraud_score` if that delta was not already applied — which is exactly
        the case for manual flags — and marks it applied; upholding an
        already-applied auto-created flag changes no score."

        Design: Difficulty/dual_variant_calc/fraud_score_decay_uphold_vs_dismiss_on_customer_domain
        """
        reset_clock()
        customer = create_customer()
        assert customer["fraud_score"] == 0

        f1 = create_manual_flag(customer["id"], score_delta=30)
        get_success_data(api_client.uphold_fraud_flag(f1["id"], ADMIN))
        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        assert cust["fraud_score"] == 30
        assert cust["fraud_status"] == "WATCH"

        f2 = create_manual_flag(customer["id"], score_delta=30)
        get_success_data(api_client.uphold_fraud_flag(f2["id"], ADMIN))
        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        assert cust["fraud_score"] == 60
        assert cust["fraud_status"] == "BLOCKED"

    def test_dismiss_of_upheld_flag_returns_invalid_state(self):
        """PRD §3.7: "Flags are adjudicated by `PlatformAdmin` from `OPEN` to
        either `UPHELD` or `DISMISSED`."
        PRD §2.8: "5. State admissibility: the target entity must be in a state
        that permits the operation, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/dual_variant_calc/fraud_score_decay_uphold_vs_dismiss_on_customer_domain
        """
        reset_clock()
        customer = create_customer()
        f1 = create_manual_flag(customer["id"], score_delta=30)
        get_success_data(api_client.uphold_fraud_flag(f1["id"], ADMIN))

        # UPHELD is a terminal disposition: a later dismiss is inadmissible.
        resp = api_client.dismiss_fraud_flag(f1["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        assert cust["fraud_score"] == 30


class TestFraudScoreConservation:
    def test_dismiss_of_unapplied_manual_flag_leaves_score_unchanged(self):
        """PRD §3.7: "Dismissing subtracts the delta (floored at zero) if and
        only if it had been applied, so dismissing an unapplied manual flag
        leaves the score untouched."

        Design: Difficulty/compensating_invariant/fraud_score_conserved_across_flag_uphold_and_dismiss
        """
        reset_clock()
        customer = create_customer()
        fa = create_manual_flag(customer["id"], score_delta=30)
        get_success_data(api_client.uphold_fraud_flag(fa["id"], ADMIN))
        fb = create_manual_flag(customer["id"], score_delta=30,
                                reason_code="ARBITRAGE_PATTERN")

        # fb was never applied, so its dismissal subtracts nothing.
        get_success_data(api_client.dismiss_fraud_flag(fb["id"], ADMIN))
        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        assert cust["fraud_score"] == 30
        assert cust["fraud_status"] == "WATCH"

    def test_second_dismiss_of_dismissed_flag_returns_invalid_state(self):
        """PRD §3.7: "Flags are adjudicated by `PlatformAdmin` from `OPEN` to
        either `UPHELD` or `DISMISSED`."
        PRD §2.8: "5. State admissibility: the target entity must be in a state
        that permits the operation, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/compensating_invariant/fraud_score_conserved_across_flag_uphold_and_dismiss
        """
        reset_clock()
        customer = create_customer()
        fb = create_manual_flag(customer["id"], score_delta=30)
        get_success_data(api_client.dismiss_fraud_flag(fb["id"], ADMIN))
        resp = api_client.dismiss_fraud_flag(fb["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestRepeatWinCascade:
    def test_fourth_win_auto_creates_repeat_win_flag_and_exhausts_window(self):
        """PRD §3.3: "Finally, acceptance recomputes the customer's
        `opaque_win_count_30d` — the count of that customer's `ACCEPTED` bids
        created within the trailing thirty days ending at the logical clock —
        and if that count exceeds three, the platform auto-creates an open
        `FraudFlag` with `reason_code` `REPEAT_WIN_RATE`, immediately adds
        twenty-five points to the customer's `fraud_score` (the flag's
        `score_delta` is applied at creation for this auto-created path), and
        recomputes `fraud_status` per §3.7; the customer's `version` increments
        as part of the cascade."
        PRD §3.3: "The consumed window's `rooms_sold` increments by 1, and if
        it thereby reaches `rooms_allocated` the window transitions `OPEN →
        EXHAUSTED` and leaves the eligible pool."

        Design: Difficulty/transitive_cascade/bid_acceptance_cascades_window_exhaustion_then_fraud_flag
        """
        reset_clock()
        supplier = create_supplier()
        get_success_data(api_client.create_disclosure_zone(
            {"neighborhood_code": "NB7", "min_star_rating": 3,
             "revealed_amenity_codes": ["POOL"]}, ADMIN
        ))
        prop = create_property(supplier["id"], neighborhood_code="NB7")
        windows = [
            create_rate_window(prop["id"], rooms_allocated=1) for _ in range(4)
        ]
        customer = create_customer()
        for _ in range(3):
            bid = place_bid(customer, neighborhood_code="NB7")
            accept_bid(bid, customer)

        b4 = place_bid(customer, neighborhood_code="NB7")
        accepted4 = accept_bid(b4, customer)
        assert accepted4["status"] == "ACCEPTED"

        # Every single-room window is now EXHAUSTED with rooms_sold == 1.
        for w in windows:
            win = get_success_data(api_client.get_rate_window(w["id"], ADMIN))
            assert win["rooms_sold"] == 1
            assert win["status"] == "EXHAUSTED"

        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        assert cust["opaque_win_count_30d"] == 4
        assert cust["fraud_score"] == 25
        assert cust["fraud_status"] == "WATCH"

        flags, _ = validate_paginated(
            api_client.list_fraud_flags(ADMIN, params={"customer_id": customer["id"]})
        )
        auto = [f for f in flags if f["reason_code"] == "REPEAT_WIN_RATE"]
        assert len(auto) == 1
        assert auto[0]["score_delta"] == 25
        assert auto[0]["status"] == "OPEN"


class TestSupplierCascade:
    def test_supplier_suspend_cascades_windows_then_bids(self):
        """PRD §3.1: "When a supplier is suspended, every `OPEN` rate window
        across every property that supplier owns transitions to `CLOSED` as a
        cascade, and each such window mutation refreshes its `updated_at` and
        increments its `version`; the supplier's own `version` likewise
        increments. Any still-`PENDING` bid whose candidate set would have
        drawn on that supplier's properties becomes unfillable and is rejected
        at its next evaluation."

        Design: Difficulty/transitive_cascade/supplier_suspend_cascades_windows_then_bids
        """
        supplier, prop, window = setup_inventory("NB6")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB6")
        assert bid["status"] == "PENDING"

        suspended = get_success_data(api_client.suspend_supplier(supplier["id"], ADMIN))
        assert suspended["status"] == "SUSPENDED"
        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["status"] == "CLOSED"

        resp = evaluate_bid(bid, customer)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"

    def test_bid_evaluation_depends_on_supplier_status(self):
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
        supplier, prop, window = setup_inventory("NB11")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB11")
        get_success_data(api_client.suspend_supplier(supplier["id"], ADMIN))

        resp = evaluate_bid(bid, customer)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        rows, _ = validate_paginated(
            api_client.list_bookings(ADMIN, params={"customer_id": customer["id"]})
        )
        assert rows == []


class TestSettlementOcc:
    def test_settlement_approve_with_stale_batch_version_returns_412(self):
        """PRD §2.7: "Approving a settlement batch requires
        `expected_settlement_batch_version`, holding the approver's last
        observed `version` of the batch; a mismatch — for instance because a
        re-selection re-derived the batch contents after the approver's read —
        is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/endpoints/settlement_approve_with_stale_batch_version_returns_412
        """
        reset_clock()
        supplier = create_supplier()
        batch = create_batch(supplier["id"])
        stale_version = batch["version"]
        # Reselection recomputes the batch and advances its version.
        get_success_data(api_client.reselect_settlement_batch(batch["id"], FO))

        resp = api_client.approve_settlement_batch(
            batch["id"], {"expected_settlement_batch_version": stale_version}, FO
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        refreshed = get_success_data(api_client.get_settlement_batch(batch["id"], FO))
        assert refreshed["status"] == "DRAFT"
