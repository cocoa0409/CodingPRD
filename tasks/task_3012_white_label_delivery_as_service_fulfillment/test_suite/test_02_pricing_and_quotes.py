"""Pricing policy windows, serviceability, and the dual-variant delivery fee
(PRD sections 3.2-3.4)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_override,
    add_policy,
    admin_headers,
    base_chain,
    batch_orders,
    check_serviceability,
    create_quote_payload,
    delivered_order,
    dispatch_batch,
    drive_to_in_transit,
    m_headers,
    make_order,
    make_order_accepted,
    make_order_ready_fresh,
    merchant_version,
    new_quote,
    ready_order_in_batch,
    set_clock,
    set_surge,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFourInputFeeAssembly:
    def test_fee_components_band_b_peak_and_surge(self, api):
        """PRD section 3.4: "The quoted fee is assembled from four components,
        each an integer number of cents and each rounded half up before
        summing."
        PRD section 3.4: "The `peak_uplift_cents` apply when `pickup_ready_at`,
        converted into the store's timezone, falls inside any of the policy's
        half-open peak windows: the uplift is the sum of band fee and value
        surcharge multiplied by `peak_uplift_pct`, rounded half up, and zero
        off-peak. The sum of these three is the base total. The
        `surge_component_cents` are the base total multiplied by the amount by
        which the current platform surge multiplier exceeds one, rounded half
        up; with the multiplier at its default of 1.0 the surge component is
        zero. The `quoted_fee_cents` are the base total plus the surge
        component."

        Design: Difficulty/combinatorial_formula/delivery_fee_four_input_nonlinear_assembly
        """
        env = base_chain(surge=1.5, with_courier=False)
        m_id = env["merchant"]["id"]
        quote = validate_success(
            api.create_quote(
                create_quote_payload(
                    env["store"]["id"],
                    dropoff_lat=0.05,
                    dropoff_lng=0.0,
                    order_value_cents=12000,
                    pickup_ready_at="2026-09-01T12:30:00Z",
                ),
                m_headers(m_id),
            ),
            201,
        )
        assert quote["distance_m"] == 5566
        assert quote["band_fee_cents"] == 1150
        assert quote["value_surcharge_cents"] == 200
        assert quote["peak_uplift_cents"] == 338
        assert quote["surge_component_cents"] == 844
        assert quote["quoted_fee_cents"] == 2532

    def test_fee_components_interact_nonlinearly_against_flatter_assemblies(self, api):
        """PRD section 3.4: "The `peak_uplift_cents` apply when
        `pickup_ready_at`, converted into the store's timezone, falls inside
        any of the policy's half-open peak windows: the uplift is the sum of
        band fee and value surcharge multiplied by `peak_uplift_pct`, rounded
        half up, and zero off-peak. The sum of these three is the base total."
        PRD section 2.7: "within the delivery-fee calculation, every component
        (the peak uplift, the surge component, the pass-through delta) is
        individually rounded half up to whole cents *before* the components
        are summed — the component-then-sum order is pinned and must not be
        reversed"

        Design: Difficulty/combinatorial_formula/delivery_fee_four_input_nonlinear_assembly
        """
        env = base_chain(surge=1.5, with_courier=False)
        m_id = env["merchant"]["id"]

        peak = validate_success(
            api.create_quote(
                create_quote_payload(
                    env["store"]["id"],
                    dropoff_lat=0.05,
                    order_value_cents=12000,
                    pickup_ready_at="2026-09-01T12:30:00Z",
                ),
                m_headers(m_id),
            ),
            201,
        )
        # Surge multiplies the base INCLUDING the peak uplift:
        # 1350 + 338 = 1688; 844 = round_half_up(1688 * 0.5); total 2532.
        assert peak["peak_uplift_cents"] == 338
        assert peak["surge_component_cents"] == 844
        assert peak["quoted_fee_cents"] == (
            peak["band_fee_cents"]
            + peak["value_surcharge_cents"]
            + peak["peak_uplift_cents"]
            + peak["surge_component_cents"]
        )

        off_peak = validate_success(
            api.create_quote(
                create_quote_payload(
                    env["store"]["id"],
                    dropoff_lat=0.05,
                    order_value_cents=12000,
                    pickup_ready_at="2026-09-01T09:00:00Z",
                ),
                m_headers(m_id),
            ),
            201,
        )
        # Off-peak same distance/value: base 1350, uplift 0, surge 675.
        assert off_peak["peak_uplift_cents"] == 0
        assert off_peak["surge_component_cents"] == 675
        assert off_peak["quoted_fee_cents"] == 2025


class TestPeakWindowBoundary:
    def test_peak_window_half_open_boundary(self, api):
        """PRD section 3.3: "`peak_windows`, an array of half-open local-time
        windows each defined by `start_local_hhmm` and `end_local_hhmm` in the
        store's timezone"
        PRD section 3.4: "The `peak_uplift_cents` apply when `pickup_ready_at`,
        converted into the store's timezone, falls inside any of the policy's
        half-open peak windows: the uplift is the sum of band fee and value
        surcharge multiplied by `peak_uplift_pct`, rounded half up, and zero
        off-peak."

        Design: Corner/calculations/peak_window_half_open_boundary
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        off = validate_success(
            api.create_quote(
                create_quote_payload(
                    env["store"]["id"], pickup_ready_at="2026-09-01T10:59:59Z"
                ),
                m_headers(m_id),
            ),
            201,
        )
        assert off["peak_uplift_cents"] == 0
        assert off["quoted_fee_cents"] == 500

        peak = validate_success(
            api.create_quote(
                create_quote_payload(
                    env["store"]["id"], pickup_ready_at="2026-09-01T11:00:00Z"
                ),
                m_headers(m_id),
            ),
            201,
        )
        assert peak["peak_uplift_cents"] == 125
        assert peak["quoted_fee_cents"] == 625


class TestValueTierHighestMatch:
    def test_value_tier_highest_match_applies(self, api):
        """PRD section 3.4: "The `value_surcharge_cents` are the
        `surcharge_cents` of the highest value tier whose
        `min_order_value_cents` is at most the `order_value_cents`, and zero
        when no tier qualifies."

        Design: Corner/calculations/value_tier_highest_match_applies
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        quote = validate_success(
            api.create_quote(
                create_quote_payload(env["store"]["id"], order_value_cents=50000),
                m_headers(m_id),
            ),
            201,
        )
        assert quote["value_surcharge_cents"] == 500
        assert quote["quoted_fee_cents"] == 1000


class TestNoActivePricingPolicy:
    def test_quote_rejected_when_no_active_policy(self, api):
        """PRD section 3.4: "requires an `ACTIVE` pricing policy of the
        merchant whose effective window contains the current clock; with none,
        the request fails with `ERR_NO_ACTIVE_PRICING_POLICY`."

        Design: Corner/calculations/quote_rejected_when_no_active_policy
        """
        env = base_chain(with_courier=False, with_policy_activated=False)
        m_id = env["merchant"]["id"]
        resp = api.create_quote(
            create_quote_payload(env["store"]["id"]), m_headers(m_id)
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRICING_POLICY)
        listed, _ = validate_paginated(api.list_quotes(m_headers(m_id)))
        assert listed == []


class TestPolicyWindowAdjacency:
    def test_adjacent_half_open_windows_allowed_and_overlap_rejected(self, api):
        """PRD section 3.3: "The candidate policy's half-open effective window
        must not overlap the effective window of any other `ACTIVE` policy of
        the same merchant; an overlap is rejected with
        `ERR_POLICY_WINDOW_OVERLAP`."
        PRD section 3.3: "Activation — performed by the merchant with an
        `expected_merchant_version` as described in §2.8 — moves the policy to
        `ACTIVE`, automatically archives whatever policy of the same merchant
        was previously `ACTIVE` (the `ACTIVE` to `ARCHIVED` transition is
        system-driven and needs no request), and increments the merchant's
        `version`."

        Design: Difficulty/resource_temporal_overlap/pricing_policy_window_half_open_adjacency_allowed
        """
        simple_bands = [{"max_m": 3000, "base_cents": 500, "per_100m_cents": 0}]
        env = base_chain(
            with_courier=False,
            with_store=False,
            policy_overrides={
                "distance_bands": simple_bands,
                "value_tiers": [],
                "peak_windows": [],
                "peak_uplift_pct": 0.0,
            },
        )
        m_id = env["merchant"]["id"]
        p1 = env["policy"]
        assert p1["effective_from"].startswith("2026-01-01T00:00:00")
        assert p1["effective_until"].startswith("2027-01-01T00:00:00")

        p2 = add_policy(
            m_id,
            distance_bands=[{"max_m": 3000, "base_cents": 600, "per_100m_cents": 0}],
            value_tiers=[], peak_windows=[], peak_uplift_pct=0.0,
            effective_from="2027-01-01T00:00:00Z",
            effective_until="2028-01-01T00:00:00Z",
        )
        p3 = add_policy(
            m_id,
            distance_bands=[{"max_m": 3000, "base_cents": 700, "per_100m_cents": 0}],
            value_tiers=[], peak_windows=[], peak_uplift_pct=0.0,
            effective_from="2026-06-01T00:00:00Z",
            effective_until="2026-07-01T00:00:00Z",
        )

        # p3's window start lies inside p1's half-open window: overlap.
        overlap = api.activate_pricing_policy(
            m_id, p3["id"], {"expected_merchant_version": merchant_version(m_id)},
            m_headers(m_id),
        )
        validate_error(overlap, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP)

        # p2 starts exactly where p1 ends: adjacency is allowed.
        ok = api.activate_pricing_policy(
            m_id, p2["id"], {"expected_merchant_version": merchant_version(m_id)},
            m_headers(m_id),
        )
        activated = validate_success(ok, 200)
        assert activated["status"] == "ACTIVE"

        p1_after = validate_success(api.get_pricing_policy(p1["id"], m_headers(m_id)))
        assert p1_after["status"] == "ARCHIVED"
        p2_after = validate_success(api.get_pricing_policy(p2["id"], m_headers(m_id)))
        assert p2_after["status"] == "ACTIVE"

    def test_overlap_rejection_leaves_both_policies_unchanged(self, api):
        """PRD section 3.3: "The candidate policy's half-open effective window
        must not overlap the effective window of any other `ACTIVE` policy of
        the same merchant; an overlap is rejected with
        `ERR_POLICY_WINDOW_OVERLAP`."
        PRD section 3.3: "At most one policy per merchant may be `ACTIVE` at
        any time, and activation is rejected with `ERR_INVALID_STATE` unless
        the policy is `DRAFT`."

        Design: Difficulty/resource_temporal_overlap/pricing_policy_window_half_open_adjacency_allowed
        """
        env = base_chain(
            with_courier=False,
            with_store=False,
            policy_overrides={
                "distance_bands": [{"max_m": 3000, "base_cents": 500, "per_100m_cents": 0}],
                "value_tiers": [], "peak_windows": [], "peak_uplift_pct": 0.0,
            },
        )
        m_id = env["merchant"]["id"]
        p1 = env["policy"]
        p3 = add_policy(
            m_id,
            distance_bands=[{"max_m": 3000, "base_cents": 700, "per_100m_cents": 0}],
            value_tiers=[], peak_windows=[], peak_uplift_pct=0.0,
            effective_from="2026-06-01T00:00:00Z",
            effective_until="2026-07-01T00:00:00Z",
        )
        version_before = merchant_version(m_id)

        overlap = api.activate_pricing_policy(
            m_id, p3["id"], {"expected_merchant_version": version_before}, m_headers(m_id)
        )
        validate_error(overlap, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP)

        p1_after = validate_success(api.get_pricing_policy(p1["id"], m_headers(m_id)))
        p3_after = validate_success(api.get_pricing_policy(p3["id"], m_headers(m_id)))
        assert p1_after["status"] == "ACTIVE", "rejected activation must not archive p1"
        assert p3_after["status"] == "DRAFT"


class TestServiceabilityRadiusBoundary:
    def test_radius_boundary_exact_vs_one_meter_over(self, api):
        """PRD section 3.2: "With no matching override, the radius test alone
        decides: the address is serviceable when the computed distance is no
        greater than `delivery_radius_m` — the boundary is inclusive, so a
        dropoff exactly on the radius is serviceable. An address that fails
        this verdict is rejected with `ERR_ADDRESS_NOT_SERVICEABLE`."

        Design: Difficulty/boundary_precision_check/serviceability_radius_boundary_exact_vs_one_meter_over
        """
        env = base_chain(
            with_courier=False, store_overrides={"delivery_radius_m": 1113}
        )
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]

        verdict = validate_success(
            api.check_serviceability(
                s_id,
                {"dropoff_lat": 0.01, "dropoff_lng": 0.0, "address_text": "10 Dest Rd"},
                m_headers(m_id),
            )
        )
        assert verdict["distance_m"] == 1113
        assert verdict["serviceable"] is True

        updated = validate_success(
            api.update_store(s_id, {"delivery_radius_m": 1112}, m_headers(m_id))
        )
        assert updated["delivery_radius_m"] == 1112

        verdict2 = validate_success(
            api.check_serviceability(
                s_id,
                {"dropoff_lat": 0.01, "dropoff_lng": 0.0, "address_text": "10 Dest Rd"},
                m_headers(m_id),
            )
        )
        assert verdict2["serviceable"] is False

        quote_resp = api.create_quote(
            create_quote_payload(s_id, dropoff_lat=0.01), m_headers(m_id)
        )
        validate_error(quote_resp, ApiErrorId.ERR_ADDRESS_NOT_SERVICEABLE)

    def test_radius_inclusive_boundary_quote_succeeds_at_exact_distance(self, api):
        """PRD section 3.2: "the boundary is inclusive, so a dropoff exactly
        on the radius is serviceable."

        Design: Difficulty/boundary_precision_check/serviceability_radius_boundary_exact_vs_one_meter_over
        """
        env = base_chain(
            with_courier=False, store_overrides={"delivery_radius_m": 1113}
        )
        m_id = env["merchant"]["id"]
        quote = validate_success(
            api.create_quote(
                create_quote_payload(env["store"]["id"], dropoff_lat=0.01),
                m_headers(m_id),
            ),
            201,
        )
        assert quote["distance_m"] == 1113
        assert quote["status"] == "ACTIVE"


class TestServiceabilityOverrides:
    def test_deny_override_longest_pattern_wins_over_radius(self, api):
        """PRD section 3.2: "If at least one override matches, the winner is
        the matching override with the longest `address_pattern`, with ties
        broken by earliest `created_at`; a winning `DENY` makes the address
        not serviceable regardless of distance, while a winning `ALLOW` falls
        through to the radius test."
        PRD section 3.2: "An address that fails this verdict is rejected with
        `ERR_ADDRESS_NOT_SERVICEABLE`."

        Design: Corner/calculations/deny_override_longest_pattern_wins_over_radius
        """
        env = base_chain(with_courier=False)
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]

        add_override(m_id, s_id, address_pattern="Dest Rd", effect="DENY")
        denied = api.create_quote(create_quote_payload(s_id), m_headers(m_id))
        validate_error(denied, ApiErrorId.ERR_ADDRESS_NOT_SERVICEABLE)

        # A longer ALLOW pattern wins the longest-match rule and re-enables it.
        add_override(m_id, s_id, address_pattern="10 Dest Rd", effect="ALLOW")
        quote = validate_success(
            api.create_quote(create_quote_payload(s_id), m_headers(m_id)), 201
        )
        assert quote["quoted_fee_cents"] == 500


class TestQuotedVsFinalSurgeDivergence:
    def test_quoted_and_invoice_diverge_when_surge_moves(self, api):
        """PRD section 3.4: "What the merchant actually pays, the
        `merchant_invoice_cents`, is the base total plus the *quoted* surge
        component plus the pass-through of the surge delta: the difference
        between the final surge component and the quoted surge component,
        multiplied by the policy's `surge_passthrough_pct`, rounded half up."
        PRD section 3.4: "Identical inputs can therefore legitimately produce
        an invoice different from the quoted fee whenever surge moved between
        quote and dispatch."

        Design: Difficulty/dual_variant_calc/delivery_fee_quoted_vs_final_surge_divergence
        """
        env = base_chain(surge=1.5)
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]

        order = make_order_ready_fresh(
            m_id, s_id, "dv-1", promised_at="2026-09-01T13:00:00Z",
            quote_overrides={
                "dropoff_lat": 0.05,
                "order_value_cents": 12000,
                "pickup_ready_at": "2026-09-01T12:30:00Z",
            },
        )
        batch = batch_orders(s_id, c_id, [order["id"]],
                             window_start="2026-09-01T12:00:00Z",
                             window_end="2026-09-01T13:00:00Z")
        set_surge(2.0)
        validate_success(api.dispatch_batch(batch["id"], env["courier_headers"]), 200)

        order_after = validate_success(api.get_order(order["id"], m_headers(m_id)))
        assert order_after["quoted_fee_cents"] == 2532
        assert order_after["final_fee_cents"] == 3376
        assert order_after["merchant_invoice_cents"] == 2954
        assert order_after["merchant_invoice_cents"] != order_after["quoted_fee_cents"]
        assert order_after["batch_fee_share_cents"] == 550

    def test_invoice_uses_passthrough_fraction_not_full_surge_delta(self, api):
        """PRD section 3.4: "The final variant recomputes the surge component
        using the platform surge multiplier in force at dispatch time rather
        than at quote time, yielding the order's `final_fee_cents`. What the
        merchant actually pays, the `merchant_invoice_cents`, is the base total
        plus the *quoted* surge component plus the pass-through of the surge
        delta: the difference between the final surge component and the quoted
        surge component, multiplied by the policy's `surge_passthrough_pct`,
        rounded half up."

        Design: Difficulty/dual_variant_calc/delivery_fee_quoted_vs_final_surge_divergence
        """
        # With surge 1.5 -> 2.0 and passthrough 0.5, the invoice must absorb
        # only HALF the surge delta: 844 of the 1688-cent gap, not all of it.
        env = base_chain(surge=1.5)
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(
            m_id, s_id, "dv-2", promised_at="2026-09-01T13:00:00Z",
            quote_overrides={
                "dropoff_lat": 0.05,
                "order_value_cents": 12000,
                "pickup_ready_at": "2026-09-01T12:30:00Z",
            },
        )
        batch = batch_orders(s_id, c_id, [order["id"]],
                             window_start="2026-09-01T12:00:00Z",
                             window_end="2026-09-01T13:00:00Z")
        set_surge(2.0)
        validate_success(api.dispatch_batch(batch["id"], env["courier_headers"]), 200)

        order_after = validate_success(api.get_order(order["id"], m_headers(m_id)))
        full_pass_through_would_be = 1688 + 844 + 844  # 3376 == final_fee_cents
        assert order_after["merchant_invoice_cents"] == 2954
        assert order_after["merchant_invoice_cents"] < full_pass_through_would_be


class TestInvoiceFloor:
    def test_invoice_floor_when_surge_drops_between_quote_and_dispatch(self, api):
        """PRD section 3.4: "The invoice is floored at the base total, so a
        negative surge delta can reduce the invoice down to the base total but
        never below it."

        Design: Corner/calculations/invoice_floor_when_surge_drops_between_quote_and_dispatch
        """
        env = base_chain(surge=2.0)
        m_id = env["merchant"]["id"]
        s_id = env["store"]["id"]
        c_id = env["courier"]["id"]
        order = make_order_ready_fresh(m_id, s_id, "fl-1",
                                       promised_at="2026-09-01T02:00:00Z")
        assert order["quoted_fee_cents"] == 1000  # base 500 + surge 500

        batch = batch_orders(s_id, c_id, [order["id"]])
        set_surge(1.0)
        validate_success(api.dispatch_batch(batch["id"], env["courier_headers"]), 200)

        order_after = validate_success(api.get_order(order["id"], m_headers(m_id)))
        assert order_after["quoted_fee_cents"] == 1000
        assert order_after["final_fee_cents"] == 500
        # PRD 3.4: invoice = base_total + *quoted* surge component +
        # passthrough of (final - quoted) surge delta. Here that is
        # 500 + 500 + round_half_up(0.5 * (0 - 500)) = 750. The invoice floor
        # at the base total (500) does not bind: the floor can only pin the
        # invoice when the pass-through share alone exceeds the quoted surge
        # component (i.e. surge_passthrough_pct > 1).
        assert order_after["merchant_invoice_cents"] == 750
