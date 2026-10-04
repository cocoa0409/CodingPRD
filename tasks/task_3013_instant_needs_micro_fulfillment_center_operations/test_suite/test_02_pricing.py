"""Pricing calculations: pinned per-line tax rounding, tiered delivery fee,
and the membership fee-waiver boundary."""
from test_helpers import (
    ApiErrorId,
    create_balance,
    create_customer,
    create_membership,
    create_product,
    create_site,
    make_customer_headers,
    place_order,
    seed_on_hand,
    set_clock,
    validate_error,
    validate_success,
)


class TestOrderTaxRounding:
    def test_tax_per_line_components_pinned(self, api):
        """PRD §3.5: "Third, tax: only AGE_RESTRICTED lines are taxed, at a rate
        of 7 percent. The pinned rounding order is per-line-then-sum: each taxed
        line's amount — quantity multiplied by unit price multiplied by the 7
        percent rate — is rounded half-up to integer cents individually, and the
        rounded line amounts are summed into tax_cents."

        Design: Difficulty/dual_variant_calc/tax_rounding_per_line_then_sum_vs_sum_then_round
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        beer_a = create_product(sku="SKU-BEER-A", name="Lager 6-pack", price_cents=99,
                                product_class="AGE_RESTRICTED")
        beer_b = create_product(sku="SKU-BEER-B", name="IPA 4-pack", price_cents=199,
                                product_class="AGE_RESTRICTED")
        customer = create_customer()
        order = place_order(
            customer["id"], site["id"],
            [{"product_id": beer_a["id"], "qty": 1}, {"product_id": beer_b["id"], "qty": 1}],
        )
        # per-line: round_half_up(6.93) = 7 plus round_half_up(13.93) = 14
        assert order["tax_cents"] == 21, order
        assert order["subtotal_cents"] == 298, order
        assert order["delivery_fee_cents"] == 199, f"off-peak, within included miles: {order}"

    def test_tax_sum_then_round_alternative_rejected(self, api):
        """PRD §3.5: "Summing raw line amounts and rounding once at the end is
        a rejected alternative; it can diverge from the pinned rule by a cent
        or more."
        PRD §2.7: "order tax rounds each taxed line to cents before summing,
        and summing raw amounts before a single rounding is a rejected
        alternative that can differ from the pinned rule."

        Three 25-cent AGE_RESTRICTED lines: per-line round_half_up(1.75) = 2
        three times (6), where sum-then-round would give round(5.25) = 5.

        Design: Difficulty/dual_variant_calc/tax_rounding_divergence_on_half_cent_lines
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        mini = create_product(sku="SKU-MINI", name="Mini shooter", price_cents=25,
                              product_class="AGE_RESTRICTED")
        customer = create_customer()
        order = place_order(
            customer["id"], site["id"],
            [{"product_id": mini["id"], "qty": 1}] * 3,
        )
        assert order["tax_cents"] == 6, f"per-line rounding pins 6, got {order['tax_cents']}"
        assert order["tax_cents"] != 5, "the sum-then-round alternative is rejected"
        assert order["subtotal_cents"] == 75, order


class TestDeliveryFeeTiers:
    def test_delivery_fee_peak_and_cap_nonlinear_interaction(self, api):
        """PRD §3.5: "The fee starts at the schedule's base_cents; the billable
        distance is the order's delivery_distance_miles minus the schedule's
        included_miles, floored at zero, and the billable miles multiplied by
        per_mile_cents — rounded half-up to integer cents — is added. If the
        placement instant falls inside any of the site's peak_windows, the
        peak_surcharge_cents is added. The result is then clamped: raised to at
        least min_fee_cents and capped at max_fee_cents."

        Design: Difficulty/combinatorial_formula/delivery_fee_tiered_peak_cap_nonlinear
        """
        set_clock("2026-09-12T02:00:00Z")  # Saturday 02:00 UTC, inside the peak windows
        site = create_site(
            code="SITE-P",
            name="Peakville MFC",
            delivery_radius_miles=10.0,
            peak_windows=[
                {"day_of_week": "FRI", "start": "22:00", "end": "24:00"},
                {"day_of_week": "SAT", "start": "00:00", "end": "04:00"},
            ],
        )
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer(email="peak@example.com", full_name="Pete Peak")

        short = place_order(customer["id"], site["id"],
                            [{"product_id": chips["id"], "qty": 1}], delivery_distance_miles=2.0)
        # 199 + round_half_up(1.0 * 99) = 298 + peak 150
        assert short["delivery_fee_cents"] == 448, short
        assert short["tax_cents"] == 0, f"STANDARD product untaxed: {short}"

        long_ = place_order(customer["id"], site["id"],
                            [{"product_id": chips["id"], "qty": 1}], delivery_distance_miles=7.0)
        # 199 + round_half_up(6.0 * 99) = 594 + 150 = 943 — under the cap, surcharge survives
        assert long_["delivery_fee_cents"] == 943, long_

    def test_delivery_fee_capped_at_max_fee(self, api):
        """PRD §3.5: "The result is then clamped: raised to at least
        min_fee_cents and capped at max_fee_cents."

        Design: Difficulty/combinatorial_formula/delivery_fee_tiered_peak_cap_nonlinear
        """
        set_clock("2026-09-12T02:00:00Z")
        site = create_site(
            code="SITE-P",
            delivery_radius_miles=10.0,
            peak_windows=[
                {"day_of_week": "FRI", "start": "22:00", "end": "24:00"},
                {"day_of_week": "SAT", "start": "00:00", "end": "04:00"},
            ],
        )
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer()
        order = place_order(customer["id"], site["id"],
                            [{"product_id": chips["id"], "qty": 1}], delivery_distance_miles=9.5)
        # 199 + round_half_up(8.0 * 99) = 792 + 150 = 1141 -> capped at 999
        assert order["delivery_fee_cents"] == 999, order


class TestFeeWaiverThreshold:
    def test_fee_waiver_threshold_exact_vs_one_cent_below(self, api):
        """PRD §3.5: "Finally, the waiver applies: if the customer holds an
        ACTIVE membership and the order's subtotal_cents is at least the site's
        fee_waiver_threshold_cents — meeting the threshold exactly waives the
        fee — the fee becomes 0."

        Design: Difficulty/boundary_precision_check/fee_waiver_threshold_exact_vs_one_cent_below
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        soda = create_product(sku="SKU-SODA", name="Soda", price_cents=499)
        bal_chips = create_balance(site["id"], chips["id"])
        bal_soda = create_balance(site["id"], soda["id"])
        seed_on_hand(bal_chips["id"], 50)
        seed_on_hand(bal_soda["id"], 50)
        customer = create_customer()
        create_membership(customer["id"], monthly_fee_cents=1000)

        at_threshold = place_order(customer["id"], site["id"],
                                   [{"product_id": chips["id"], "qty": 6}])
        assert at_threshold["subtotal_cents"] == 3000, at_threshold
        assert at_threshold["delivery_fee_cents"] == 0, "exact threshold waives (>=)"

        below = place_order(customer["id"], site["id"],
                            [{"product_id": chips["id"], "qty": 5},
                             {"product_id": soda["id"], "qty": 1}])
        assert below["subtotal_cents"] == 2999, below
        assert below["delivery_fee_cents"] == 199, "one cent below does not waive"
        assert below["total_cents"] == 3198, below

    def test_fee_waiver_requires_active_membership(self, api):
        """PRD §3.5: "Finally, the waiver applies: if the customer holds an
        ACTIVE membership and the order's subtotal_cents is at least the site's
        fee_waiver_threshold_cents — meeting the threshold exactly waives the
        fee — the fee becomes 0."

        Design: Difficulty/boundary_precision_check/fee_waiver_threshold_exact_vs_one_cent_below
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer()  # no membership at all
        order = place_order(customer["id"], site["id"],
                            [{"product_id": chips["id"], "qty": 6}])
        assert order["subtotal_cents"] == 3000, order
        assert order["delivery_fee_cents"] == 199, "no ACTIVE membership, no waiver"


class TestPlacementValidationOrder:
    def test_radius_vs_insufficient_stock_priority(self, api):
        """PRD §2.6: "Only after existence does the server evaluate
        state-transition legality (ERR_INVALID_STATE), business-safety rules,
        capacity and fiscal constraints, optimistic-concurrency checks,
        uniqueness (ERR_DUPLICATE_RESOURCE), and finally payload
        well-formedness (ERR_INVALID_REQUEST). This ordering is normative: when
        several violations coexist, the earliest category in this sequence
        determines the response."
        PRD §3.5: "the distance may not exceed the site's
        delivery_radius_miles (otherwise ERR_DELIVERY_RADIUS_EXCEEDED)"

        Design: Difficulty/priority_pair_validation_conflict/radius_vs_insufficient_stock_priority
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        create_balance(site["id"], chips["id"])  # on_hand 0 — no stock
        customer = create_customer()
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "site_id": site["id"],
                "lines": [{"product_id": chips["id"], "qty": 1}],
                "delivery_distance_miles": 9.0,
            },
            make_customer_headers(customer["id"]),
        )
        err = validate_error(resp, ApiErrorId.ERR_DELIVERY_RADIUS_EXCEEDED)
        assert err["error_id"] != "ERR_INSUFFICIENT_STOCK"
        assert err["error_id"] != "ERR_PRODUCT_UNSELLABLE"

    def test_out_of_radius_placement_persists_no_order(self, api, site_ops_headers):
        """PRD §3.5: "the distance may not exceed the site's
        delivery_radius_miles (otherwise ERR_DELIVERY_RADIUS_EXCEEDED)"

        Design: Difficulty/priority_pair_validation_conflict/radius_vs_insufficient_stock_priority
        """
        from test_helpers import validate_paginated

        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        chips = create_product(sku="SKU-CHIPS", price_cents=500)
        balance = create_balance(site["id"], chips["id"])
        seed_on_hand(balance["id"], 50)
        customer = create_customer()
        resp = api.create_order(
            {
                "customer_id": customer["id"],
                "site_id": site["id"],
                "lines": [{"product_id": chips["id"], "qty": 1}],
                "delivery_distance_miles": 9.0,
            },
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_RADIUS_EXCEEDED)
        rows, meta = validate_paginated(
            api.list_orders(site_ops_headers, params={"customer_id": customer["id"]})
        )
        assert rows == [] and meta["total_count"] == 0, "a rejected placement persists nothing"


class TestTaxRoundingQtyWithinLine:
    def test_tax_per_line_applies_to_qty_within_one_line(self, api):
        """PRD §3.5: "each taxed line's amount — quantity multiplied by unit
        price multiplied by the 7 percent rate — is rounded half-up to integer
        cents individually, and the rounded line amounts are summed into
        tax_cents."

        Two units of a 99-cent item on ONE line: the line amount 2 x 99 x 0.07
        = 13.86 rounds once to 14, not twice to 7 + 7.

        Design: Difficulty/dual_variant_calc/tax_rounding_per_line_then_sum_vs_sum_then_round
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        beer = create_product(sku="SKU-BEER-Q", name="Lager", price_cents=99,
                              product_class="AGE_RESTRICTED")
        customer = create_customer()
        order = place_order(customer["id"], site["id"], [{"product_id": beer["id"], "qty": 2}])
        assert order["tax_cents"] == 14, order
        assert order["subtotal_cents"] == 198, order

    def test_tax_divergence_also_with_qty_in_line(self, api):
        """PRD §2.7: "order tax rounds each taxed line to cents before
        summing, and summing raw amounts before a single rounding is a
        rejected alternative that can differ from the pinned rule."

        A single line of qty 3 at 25 cents: the pinned rule computes the line
        amount 3 x 25 x 0.07 = 5.25 and rounds it once to 5; only splitting
        into three qty-1 lines would yield 6. Both shapes are the same basket
        priced differently by where the line boundary falls.

        Design: Difficulty/dual_variant_calc/tax_rounding_divergence_on_half_cent_lines
        """
        set_clock("2026-09-10T14:00:00Z")
        site = create_site()
        mini = create_product(sku="SKU-MINI-Q", name="Mini shooter", price_cents=25,
                              product_class="AGE_RESTRICTED")
        customer = create_customer()
        one_line = place_order(customer["id"], site["id"], [{"product_id": mini["id"], "qty": 3}])
        assert one_line["tax_cents"] == 5, f"one line of qty 3 rounds once: {one_line['tax_cents']}"
        assert one_line["subtotal_cents"] == 75, one_line
