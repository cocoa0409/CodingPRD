"""Bid placement, evaluation, selector ranking, and lifecycle tests."""
from test_helpers import (
    ADMIN,
    CS,
    FO,
    ApiErrorId,
    accept_bid,
    api_client,
    booking_for_customer,
    block_customer,
    create_customer,
    create_disclosure_zone,
    create_property,
    create_rate_window,
    create_supplier,
    evaluate_bid,
    get_success_data,
    make_customer_headers,
    place_bid,
    reset_clock,
    setup_accepted_booking,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBidCreationModes:
    def test_fixed_mode_ignores_supplied_bid_price_and_computes_floor(self):
        """PRD §3.2: "In `BID` mode the total offered price for the whole stay,
        all nights combined, travels in `bid_price_cents`, and this field is
        required; in `FIXED` mode any supplied `bid_price_cents` is ignored. A
        bid that violates these mode semantics is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "The bid-level `computed_price_cents` is the minimum of those
        per-candidate floors, and it is the floor a `BID`-mode offer must meet
        or the exact price a `FIXED`-mode stay charges."

        Design: Corner/entities/opaque_bid_create_fixed_mode_ignores_bid_price_and_computes_price
        """
        supplier, prop, window = setup_inventory("NB15")
        customer = create_customer()
        resp = api_client.create_opaque_bid(
            {
                "customer_id": customer["id"],
                "neighborhood_code": "NB15",
                "min_star_rating": 4,
                "check_in_date": "2026-10-02T00:00:00Z",
                "check_out_date": "2026-10-04T00:00:00Z",
                "offer_mode": "FIXED",
                "bid_price_cents": 1,
            },
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        # ceil(15000 * 2 nights * (1 - 0.10)) = 27000 regardless of the
        # ignored bid_price_cents.
        assert data["computed_price_cents"] == 27000
        assert data["status"] == "PENDING"

    def test_bid_mode_requires_bid_price(self):
        """PRD §3.2: "In `BID` mode the total offered price for the whole stay,
        all nights combined, travels in `bid_price_cents`, and this field is
        required; in `FIXED` mode any supplied `bid_price_cents` is ignored. A
        bid that violates these mode semantics is rejected with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_bid_create
        """
        supplier, prop, window = setup_inventory("NB41")
        customer = create_customer()
        resp = api_client.create_opaque_bid(
            {
                "customer_id": customer["id"],
                "neighborhood_code": "NB41",
                "min_star_rating": 4,
                "check_in_date": "2026-10-02T00:00:00Z",
                "check_out_date": "2026-10-04T00:00:00Z",
                "offer_mode": "BID",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_bid_create_with_equal_dates_returns_invalid_date_range(self):
        """PRD §3.2: "The temporal gate rejects with `ERR_INVALID_DATE_RANGE`
        (HTTP 400) when `check_out_date` is not strictly after `check_in_date`,
        or when `check_in_date` lies before the current logical date —
        backdated bidding is not permitted."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_bid_create
        """
        reset_clock()
        customer = create_customer()
        create_disclosure_zone(neighborhood_code="NB9")
        resp = api_client.create_opaque_bid(
            {
                "customer_id": customer["id"],
                "neighborhood_code": "NB9",
                "min_star_rating": 4,
                "check_in_date": "2026-10-02T00:00:00Z",
                "check_out_date": "2026-10-02T00:00:00Z",
                "offer_mode": "BID",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)
        rows, _ = validate_paginated(
            api_client.list_opaque_bids(ADMIN, params={"customer_id": customer["id"]})
        )
        assert rows == []

    def test_backdated_check_in_returns_invalid_date_range(self):
        """PRD §3.2: "The temporal gate rejects with `ERR_INVALID_DATE_RANGE`
        (HTTP 400) when `check_out_date` is not strictly after `check_in_date`,
        or when `check_in_date` lies before the current logical date —
        backdated bidding is not permitted."

        Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_constraint_on_bid_create
        """
        reset_clock()
        customer = create_customer()
        create_disclosure_zone(neighborhood_code="NB42")
        resp = api_client.create_opaque_bid(
            {
                "customer_id": customer["id"],
                "neighborhood_code": "NB42",
                "min_star_rating": 4,
                "check_in_date": "2026-08-01T00:00:00Z",
                "check_out_date": "2026-08-03T00:00:00Z",
                "offer_mode": "FIXED",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


class TestDisclosureBoundary:
    def test_system_fields_ignored_and_brand_never_leaks_on_bid(self):
        """PRD §3.2: "A successfully created bid enters `PENDING` status with
        `winning_property_id` and `winning_rate_window_id` unset."
        PRD §2.5: "First, concealment of identity: a property's `brand_name` is
        never disclosed pre-purchase under any circumstance; the shopper's
        pre-purchase view of an opaque offer consists solely of the
        neighborhood, a minimum star rating, and amenity codes."

        Design: Corner/entities/winning_property_id_input_ignored_and_brand_never_leaks_on_bid
        """
        supplier, prop, window = setup_inventory(
            "NB18", property_overrides={"brand_name": "SecretBrand"}
        )
        customer = create_customer()
        resp = api_client.create_opaque_bid(
            {
                "customer_id": customer["id"],
                "neighborhood_code": "NB18",
                "min_star_rating": 4,
                "check_in_date": "2026-10-02T00:00:00Z",
                "check_out_date": "2026-10-04T00:00:00Z",
                "offer_mode": "FIXED",
                "winning_property_id": prop["id"],
            },
            make_customer_headers(customer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["winning_property_id"] is None
        assert "brand_name" not in data
        assert "SecretBrand" not in resp.text

    def test_amenity_outside_zone_rejected_at_disclosure_boundary(self):
        """PRD §2.5: "Third, rejection of boundary-narrowing requests: when a
        customer places a bid, any request content that would narrow disclosure
        below the zone's declared granularity — and thereby risk making the
        discount publicly attributable to a specific brand — is rejected with
        `ERR_DISCLOSURE_BOUNDARY_VIOLATION` (HTTP 422). In particular, an
        amenity filter supplied on a bid is honored only when every requested
        amenity is a member of the zone's `revealed_amenity_codes`; a filter
        value outside that set is rejected with `ERR_INVALID_REQUEST`
        (HTTP 400)."

        Design: Corner/validations/disclosure_boundary_rejects_amenity_outside_zone
        """
        reset_clock()
        create_disclosure_zone(neighborhood_code="NB29", revealed_amenity_codes=["POOL"])
        customer = create_customer()
        resp = api_client.create_opaque_bid(
            {
                "customer_id": customer["id"],
                "neighborhood_code": "NB29",
                "min_star_rating": 4,
                "check_in_date": "2026-10-02T00:00:00Z",
                "check_out_date": "2026-10-04T00:00:00Z",
                "offer_mode": "FIXED",
                "required_amenity_codes": ["SPA"],
            },
            make_customer_headers(customer["id"]),
        )
        # The PRD names both outcomes for an out-of-zone amenity filter (the
        # 422 boundary violation and the 400 filter-membership rejection);
        # accept the one the implementation chose, pinned by HTTP status.
        if resp.status_code == 422:
            validate_error(resp, ApiErrorId.ERR_DISCLOSURE_BOUNDARY_VIOLATION)
        else:
            validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        rows, _ = validate_paginated(
            api_client.list_opaque_bids(ADMIN, params={"customer_id": customer["id"]})
        )
        assert rows == []


class TestSelectorAndFloor:
    def test_floor_is_min_across_candidate_properties(self):
        """PRD §3.2: "At creation the platform computes and stores a snapshot
        `computed_price_cents`: for each property in the bid's neighborhood
        whose `star_rating` is at least the bid's `min_star_rating` and which
        has an `OPEN` rate window fully covering the requested stay with at
        least one room-night slot remaining, the stay length in whole days —
        always at least one night, which the date validation guarantees — is
        multiplied by that window's `opaque_rate_cents` to form a base; the
        lowest total price that supplier will accept is the base multiplied by
        one minus the supplier's `concealment_discount_min_pct`, rounded up to
        a whole cent. The bid-level `computed_price_cents` is the minimum of
        those per-candidate floors, and it is the floor a `BID`-mode offer must
        meet or the exact price a `FIXED`-mode stay charges."

        Design: Difficulty/combinatorial_formula/opaque_price_floor_multi_input_tiered_mode_a
        """
        reset_clock()
        s1 = create_supplier(opaque_commission_pct=0.15, concealment_discount_min_pct=0.20)
        s2 = create_supplier(opaque_commission_pct=0.15, concealment_discount_min_pct=0.10)
        create_disclosure_zone(neighborhood_code="NB2", revealed_amenity_codes=["POOL"])
        p1 = create_property(s1["id"], star_rating=5, neighborhood_code="NB2",
                             published_rate_cents=25000)
        p2 = create_property(s2["id"], star_rating=4, neighborhood_code="NB2",
                             published_rate_cents=18000)
        create_rate_window(p1["id"], opaque_rate_cents=13000)
        create_rate_window(p2["id"], opaque_rate_cents=11000)
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB2")
        # floor P1 = ceil(13000*2*0.80) = 20800; floor P2 = ceil(11000*2*0.90)
        # = 19800; min = 19800.
        assert bid["computed_price_cents"] == 19800

    def test_selector_tie_breaks_by_published_rate_desc(self):
        """PRD §3.3: "Among eligible candidates the selector ranks
        deterministically, with no randomness and no identifier ever
        participating in ranking or tie-breaking: first by the window's
        `opaque_rate_cents` ascending — cheapest fill first — then by the
        property's `published_rate_cents` descending, so that among equally
        priced windows the deeper public discount wins, then by the window's
        `created_at` ascending, and finally by the property's `created_at`
        ascending. The winner supplies the bid's `winning_property_id` and
        `winning_rate_window_id`."

        Design: Corner/calculations/selector_tie_breaks_by_published_rate_then_window_created_at
        """
        reset_clock()
        s1 = create_supplier(concealment_discount_min_pct=0.10)
        s2 = create_supplier(concealment_discount_min_pct=0.10)
        create_disclosure_zone(neighborhood_code="NB25", revealed_amenity_codes=["POOL"])
        p1 = create_property(s1["id"], neighborhood_code="NB25", published_rate_cents=24000)
        p2 = create_property(s2["id"], neighborhood_code="NB25", published_rate_cents=19000)
        # Create P2's window first so created_at cannot be the decider.
        w_p2 = create_rate_window(p2["id"])
        w_p1 = create_rate_window(p1["id"])
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB25")
        accepted = accept_bid(bid, customer)
        # Same opaque rate → deeper public discount (higher published rate) wins.
        assert accepted["winning_property_id"] == p1["id"]
        assert accepted["winning_rate_window_id"] == w_p1["id"]

    def test_concealment_discount_recorded_to_four_decimals(self):
        """PRD §3.3: "The bid records its achieved `concealment_discount_pct`:
        the winning property's `published_rate_cents` multiplied by the number
        of nights gives the published total, and the discount fraction is the
        published total minus the charged price, divided by the published
        total, rounded half-up to 4 decimal places."

        Design: Corner/calculations/concealment_discount_recorded_to_four_decimals
        """
        supplier, prop, window, customer, bid, booking = setup_accepted_booking("NB27")
        assert bid["status"] == "ACCEPTED"
        # published total = 20000 * 2 = 40000; charged 27000 → 0.3250.
        assert bid["concealment_discount_pct"] == 0.3250


class TestBidEvaluationOutcomes:
    def test_bid_below_floor_rejected_and_strict_mode_returns_error(self):
        """PRD §3.3: "Conversely, the bid transitions `PENDING → REJECTED` when
        no eligible candidate exists, or when a `BID`-mode offer fails either
        economic test — offered price below the computed floor, or achieved
        discount below the supplier's minimum. Rejection is a terminal state of
        the bid, not an error response; by default the evaluation call returns
        the rejected bid normally. A caller who prefers rejection to surface as
        an error may request strict evaluation by passing `fail_on_reject` set
        to true, in which case a rejected evaluation is answered with
        `ERR_BID_BELOW_FLOOR` (HTTP 422) instead."

        Design: Corner/calculations/bid_below_floor_rejects_without_fail_flag_and_records_nothing
        """
        supplier, prop, window = setup_inventory("NB26")
        customer = create_customer()
        # Floor for 2 nights = ceil(30000 * 0.9) = 27000; bid 26000 is below.
        bid1 = place_bid(customer, neighborhood_code="NB26",
                         offer_mode="BID", bid_price_cents=26000)
        bid2 = place_bid(customer, neighborhood_code="NB26",
                         offer_mode="BID", bid_price_cents=26000)

        # Strict evaluation: error. (PRD names the 422 ERR_BID_BELOW_FLOOR
        # answer but is silent on whether the strict path skips the terminal
        # transition, so no post-error status is asserted here.)
        resp = evaluate_bid(bid1, customer, fail_on_reject=True)
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_FLOOR)

        # Default evaluation: 200 with the bid terminally REJECTED.
        resp = evaluate_bid(bid2, customer)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"

        rows, _ = validate_paginated(
            api_client.list_bookings(ADMIN, params={"customer_id": customer["id"]})
        )
        assert rows == []

    def test_partial_window_containment_does_not_qualify(self):
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
        reset_clock()
        supplier = create_supplier()
        create_disclosure_zone(neighborhood_code="NB13")
        prop = create_property(supplier["id"], neighborhood_code="NB13")
        # Window starts mid-stay — overlaps but does not fully contain.
        create_rate_window(
            prop["id"],
            check_in_date="2026-10-03T00:00:00Z",
            check_out_date="2026-10-06T00:00:00Z",
        )
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB13")
        resp = evaluate_bid(bid, customer)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"

    def test_blocked_customer_rejected_at_evaluation(self):
        """PRD §3.3: "The fraud gate applies a second time here: a customer
        whose `fraud_status` is `BLOCKED` at evaluation is rejected with
        `ERR_CUSTOMER_BLOCKED` (HTTP 403) even if the bid was created while the
        customer was clear."

        Design: Corner/validations/blocked_customer_cannot_create_bid
        """
        supplier, prop, window = setup_inventory("NB43")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB43")
        block_customer(customer["id"])
        resp = evaluate_bid(bid, customer)
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_BLOCKED)

    def test_blocked_customer_cannot_create_bid(self):
        """PRD §3.7: "A `BLOCKED` customer cannot create bids and cannot have
        pending bids evaluated — both operations reject with
        `ERR_CUSTOMER_BLOCKED` (HTTP 403)."

        Design: Corner/validations/blocked_customer_cannot_create_bid
        """
        reset_clock()
        customer = create_customer()
        block_customer(customer["id"])
        create_disclosure_zone(neighborhood_code="NB30")
        resp = api_client.create_opaque_bid(
            {
                "customer_id": customer["id"],
                "neighborhood_code": "NB30",
                "min_star_rating": 4,
                "check_in_date": "2026-10-02T00:00:00Z",
                "check_out_date": "2026-10-04T00:00:00Z",
                "offer_mode": "FIXED",
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CUSTOMER_BLOCKED)

    def test_withdrawn_bid_evaluation_returns_invalid_state_not_customer_blocked(self):
        """PRD §2.8: "Every request is validated in a fixed priority order, and
        the first failing check determines the error returned:"
        PRD §2.8: "5. State admissibility: the target entity must be in a state
        that permits the operation, else `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_fraud_gate_on_evaluate
        """
        supplier, prop, window = setup_inventory("NB8")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB8")
        get_success_data(api_client.withdraw_opaque_bid(
            bid["id"], make_customer_headers(customer["id"])
        ))
        block_customer(customer["id"])
        fresh = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        resp = api_client.evaluate_opaque_bid(
            bid["id"], {"expected_customer_version": fresh["version"]}, ADMIN
        )
        # State admissibility (priority 5) precedes the business fraud gate
        # (priority 6) in the PRD's fixed order.
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBidLifecycle:
    def test_withdraw_on_terminal_bid_returns_invalid_state(self):
        """PRD §2.8: "5. State admissibility: the target entity must be in a
        state that permits the operation, else `ERR_INVALID_STATE` (HTTP 409)."
        PRD §3.2: "The customer may withdraw a `PENDING` bid at any time before
        evaluation — withdrawal moves it `PENDING → WITHDRAWN`, and only the
        bid's own customer may do so."

        Design: Corner/state_machines/withdraw_on_terminal_bid_returns_invalid_state
        """
        supplier, prop, window = setup_inventory("NB20")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB20")
        withdrawn = get_success_data(api_client.withdraw_opaque_bid(
            bid["id"], make_customer_headers(customer["id"])
        ))
        assert withdrawn["status"] == "WITHDRAWN"

        resp = api_client.withdraw_opaque_bid(bid["id"], make_customer_headers(customer["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        refreshed = get_success_data(api_client.get_opaque_bid(bid["id"], ADMIN))
        assert refreshed["status"] == "WITHDRAWN"

    def test_pending_bid_expires_when_clock_reaches_check_in(self):
        """PRD §2.4: "A `PlatformAdmin`-only test-driving capability advances
        the logical clock to a supplied `current_utc` instant; advancing the
        clock re-evaluates every still-`PENDING` bid whose `check_in_date` has
        been reached and transitions each such bid to `EXPIRED`."

        Design: Corner/state_machines/pending_bid_expires_when_clock_reaches_check_in
        """
        supplier, prop, window = setup_inventory("NB21")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB21")
        assert bid["status"] == "PENDING"

        get_success_data(api_client.set_clock({"current_utc": "2026-10-02T00:00:00Z"}, ADMIN))
        refreshed = get_success_data(api_client.get_opaque_bid(bid["id"], ADMIN))
        assert refreshed["status"] == "EXPIRED"
        rows, _ = validate_paginated(
            api_client.list_bookings(ADMIN, params={"customer_id": customer["id"]})
        )
        assert rows == []


class TestOccAndDerivedVisibility:
    def test_evaluate_with_stale_customer_version_returns_412(self):
        """PRD §2.7: "Evaluating a bid requires the request to carry
        `expected_customer_version`, holding the caller's last observed
        `version` of the bid's customer. If the customer's current `version`
        has advanced since that read — for instance because a fraud flag was
        upheld or another bid was accepted for the same customer — the
        evaluation is rejected with `ERR_STALE_VERSION` (HTTP 412) and must be
        retried against a fresh read."

        Design: Corner/endpoints/evaluate_with_stale_customer_version_returns_412
        """
        supplier, prop, window = setup_inventory(
            "NB32", window_overrides={"rooms_allocated": 5}
        )
        customer = create_customer()
        stale_version = customer["version"]
        b1 = place_bid(customer, neighborhood_code="NB32")
        b2 = place_bid(customer, neighborhood_code="NB32")
        # Accepting b1 advances the customer's version.
        accepted = accept_bid(b1, customer)
        assert accepted["status"] == "ACCEPTED"

        resp = api_client.evaluate_opaque_bid(
            b2["id"], {"expected_customer_version": stale_version}, ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        refreshed = get_success_data(api_client.get_opaque_bid(b2["id"], ADMIN))
        assert refreshed["status"] == "PENDING"

    def test_acceptance_is_immediately_visible_across_entities(self):
        """PRD §3.3: "Acceptance creates a `Booking` whose `opaque_bid_id`
        ties it back to the winning bid, in `CAPTURED`/`CONFIRMED`, carrying
        the bid's customer, the revealed property and its supplier, the
        consumed rate window via its `rate_window_id`, the copied stay dates,
        and a `charged_price_cents` equal to `bid_price_cents` for a `BID`-mode
        win or `computed_price_cents` for a `FIXED`-mode win. The consumed
        window's `rooms_sold` increments by 1, and if it thereby reaches
        `rooms_allocated` the window transitions `OPEN → EXHAUSTED` and leaves
        the eligible pool."

        Design: Corner/consistency_model/acceptance_is_immediately_visible_across_entities
        """
        supplier, prop, window = setup_inventory("NB39")
        customer = create_customer()
        bid = place_bid(customer, neighborhood_code="NB39")
        resp = evaluate_bid(bid, customer)
        data = validate_success(resp)
        assert data["status"] == "ACCEPTED"
        assert data["winning_property_id"] == prop["id"]

        rows, _ = validate_paginated(
            api_client.list_bookings(ADMIN, params={"customer_id": customer["id"]})
        )
        assert len(rows) == 1
        assert rows[0]["payment_status"] == "CAPTURED"
        assert rows[0]["fulfillment_status"] == "CONFIRMED"

        win = get_success_data(api_client.get_rate_window(window["id"], ADMIN))
        assert win["rooms_sold"] == 1

        cust = get_success_data(api_client.get_customer(customer["id"], ADMIN))
        assert cust["opaque_win_count_30d"] == 1
