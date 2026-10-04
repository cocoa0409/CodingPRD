"""Dual-variant calculations: stale-credit pricing and settlement variants."""
import pytest

from test_helpers import (
    api_client,
    create_assignment,
    create_order,
    create_product,
    create_rep,
    create_route,
    create_route_day,
    create_store,
    create_stale_credit,
    get_credit,
    list_lots,
    load_route_day,
    make_admin_headers,
    make_rep_headers,
    make_supervisor_headers,
    order_line,
    deliver_line,
    lot_entry,
    set_clock,
    start_route_day,
    submit_order,
    deliver_order,
    validate_success,
)


class TestStaleCreditPricingVariantDivergence:
    def test_pricing_variant_snapshots_store_policy_and_amounts(self, api):
        """PRD §3.7: "Under FULL_RETAIL, credit_cents is the qty_cases multiplied
        by the product's case_price_cents — the full list value. Under
        SALVAGE_RATE, credit_cents is the same product multiplied by 0.40 and
        rounded half up to whole cents — forty percent of list — so the two
        variants diverge for identical quantities and prices."

        Design: Difficulty/dual_variant_calc/stale_credit_pricing_variant_divergence
        """
        set_clock()
        rep = create_rep()
        store_a = create_store(store_code="SA", credit_policy="FULL_RETAIL")
        store_b = create_store(store_code="SB", credit_policy="SALVAGE_RATE")
        product = create_product(case_price_cents=250)
        route = create_route(rep["id"])
        create_assignment(route["id"], store_a["id"])
        create_assignment(route["id"], store_b["id"], stop_sequence=2)
        day = create_route_day(route["id"])
        load_route_day(
            day["id"],
            [lot_entry(product["id"], "L-ST", "2026-09-06", 40)],
            rep,
        )
        start_route_day(day["id"], rep)

        credit_a = create_stale_credit(
            day["id"], store_a["id"], product["id"], 10, make_rep_headers(rep["id"])
        )
        credit_b = create_stale_credit(
            day["id"], store_b["id"], product["id"], 10, make_rep_headers(rep["id"])
        )

        assert credit_a["pricing_variant"] == "FULL_RETAIL"
        assert credit_a["credit_cents"] == 2500
        assert credit_b["pricing_variant"] == "SALVAGE_RATE"
        assert credit_b["credit_cents"] == 1000
        assert credit_a["credit_cents"] - credit_b["credit_cents"] == 1500

    def test_variant_selected_by_store_policy_not_payload(self, api):
        """PRD §3.7: "Pricing snapshots the store's policy at creation onto the
        credit's pricing_variant."

        Design: Difficulty/dual_variant_calc/stale_credit_pricing_variant_divergence
        """
        set_clock()
        rep = create_rep()
        store_a = create_store(store_code="SA", credit_policy="FULL_RETAIL")
        store_b = create_store(store_code="SB", credit_policy="SALVAGE_RATE")
        product = create_product(case_price_cents=250)
        route = create_route(rep["id"])
        create_assignment(route["id"], store_a["id"])
        create_assignment(route["id"], store_b["id"], stop_sequence=2)
        day = create_route_day(route["id"])
        load_route_day(
            day["id"],
            [lot_entry(product["id"], "L-ST", "2026-09-06", 40)],
            rep,
        )
        start_route_day(day["id"], rep)

        credit_a = create_stale_credit(
            day["id"], store_a["id"], product["id"], 4, make_rep_headers(rep["id"])
        )
        credit_b = create_stale_credit(
            day["id"], store_b["id"], product["id"], 4, make_rep_headers(rep["id"])
        )

        # Same qty and price: only the store policy differs.
        assert credit_a["pricing_variant"] == "FULL_RETAIL"
        assert credit_b["pricing_variant"] == "SALVAGE_RATE"
        assert credit_a["credit_cents"] == 4 * 250
        assert credit_b["credit_cents"] == 400  # round_half_up(4 * 250 * 0.40)
        # Both credits begin PENDING_APPROVAL with created_by recorded.
        assert credit_a["status"] == "PENDING_APPROVAL"
        assert credit_b["status"] == "PENDING_APPROVAL"


class TestSettlementForwardVsChronologicalDivergence:
    def _setup_two_deliveries_and_credit(self):
        """Lot A 90 fresh cases + lot B 10 stale cases; order1 30 cases full
        price, order2 20 cases at 10% discount; 5-case credit approved."""
        set_clock()
        rep = create_rep()
        store = create_store()
        product = create_product()
        route = create_route(rep["id"], base_capacity_cases=120)
        create_assignment(route["id"], store["id"])
        day = create_route_day(route["id"])
        load_route_day(
            day["id"],
            [
                lot_entry(product["id"], "L-A", "2026-09-20", 90),
                lot_entry(product["id"], "L-B", "2026-09-06", 10),
            ],
            rep,
        )
        start_route_day(day["id"], rep)

        order1 = create_order(
            day["id"], store["id"], [order_line(product["id"], 30)], rep
        )
        submit_order(order1["id"], rep)
        deliver_order(order1["id"], [deliver_line(product["id"], 30)], rep)

        order2 = create_order(
            day["id"],
            store["id"],
            [order_line(product["id"], 20, line_discount_pct=0.10)],
            rep,
        )
        submit_order(order2["id"], rep)
        deliver_order(order2["id"], [deliver_line(product["id"], 20)], rep)

        credit = create_stale_credit(
            day["id"], store["id"], product["id"], 5, make_rep_headers(rep["id"])
        )
        resp = api_client.approve_stale_credit(credit["id"], make_supervisor_headers())
        validate_success(resp)

        return day

    def test_dual_variants_diverge_by_discount_drift(self, api):
        """PRD §3.9: "because the forward variant values sold cases at list
        while the chronological variant uses per-line discounted prices, the
        two diverge on identical data whenever any line carries a positive
        discount."

        Design: Difficulty/dual_variant_calc/settlement_forward_vs_chronological_divergence
        """
        day = self._setup_two_deliveries_and_credit()

        resp = api.create_settlement(
            {"route_day_id": day["id"]}, make_supervisor_headers()
        )
        settlement = validate_success(resp, expected_status=201)

        assert settlement["gross_delivered_cents"] == 24000  # 15000 + 9000
        assert settlement["credits_cents"] == 2500  # 5 * 500 FULL_RETAIL
        assert settlement["chronological_expected_cents"] == 21500
        # Forward: (90 - 0 - 40) * 500 (lot A) + (10 - 5 - 5) * 500 (lot B) - 2500
        assert settlement["forward_expected_cents"] == 22500
        assert settlement["recon_delta_cents"] == 1000

    def test_chronological_equals_gross_minus_credits(self, api):
        """PRD §3.9: "gross_delivered_cents is the sum of line_total_cents over
        the day's DELIVERED orders (per-line priced, discounts included);
        credits_cents is the sum of credit_cents over the day's APPROVED stale
        credits; and chronological_expected_cents is the gross minus the
        credits."

        Design: Difficulty/dual_variant_calc/settlement_forward_vs_chronological_divergence
        """
        day = self._setup_two_deliveries_and_credit()

        resp = api.create_settlement(
            {"route_day_id": day["id"]}, make_supervisor_headers()
        )
        settlement = validate_success(resp, expected_status=201)

        assert (
            settlement["chronological_expected_cents"]
            == settlement["gross_delivered_cents"] - settlement["credits_cents"]
        )
        assert (
            settlement["recon_delta_cents"]
            == settlement["forward_expected_cents"]
            - settlement["chronological_expected_cents"]
        )
        # The discount drift is exactly the 10% off the 20-case line.
        assert settlement["recon_delta_cents"] == 1000
