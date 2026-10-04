"""Combinatorial formulas: teaming surcharge and pinned per-line rounding."""
from test_helpers import (
    TEST_USERS,
    create_approved_teaming,
    setup_active_chain,
    validate_success,
)

INT = TEST_USERS["integrator_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestTeamingSurchargeModeA:
    def test_surcharge_raw_branch_dominates(self, api):
        """PRD §3.6: "take the raw uplift equal to the order total multiplied
        by the revenue share multiplied by 0.30; take a floor amount equal to
        the order total multiplied by 0.015; select the larger of the raw
        uplift and the floor amount; cap the result at 500000 cents (five
        thousand dollars per order); and round half-up to integer cents."

        Design: Difficulty/combinatorial_formula/teaming_surcharge_mode_a_min_max_floor_cap
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        teaming = create_approved_teaming(
            agreement["id"], vehicle["id"],
            integrator_name="Integ Co", small_business=False,
            revenue_share_pct=0.10,
        )
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "price_list_id": price_list["id"],
             "teaming_id": teaming["id"], "buyer_tier": "FEDERAL",
             "lines": [{"sku": "SW-1", "qty": 10}]},
            INT,
        )
        order = validate_success(resp, expected_status=201)
        # total = 10000*10 = 100000; raw = 100000*0.10*0.30 = 3000;
        # floor = 100000*0.015 = 1500; min(500000, max(3000,1500)) = 3000.
        assert order["order_total_cents"] == 100000
        assert order["teaming_surcharge_cents"] == 3000

    def test_surcharge_excluded_from_order_total(self, api):
        """PRD §3.6: "The order's teaming_surcharge_cents is computed at the
        same time (see below) but is not added into order_total_cents; the
        surcharge is layered in at invoice time instead."

        Design: Difficulty/combinatorial_formula/teaming_surcharge_mode_a_min_max_floor_cap
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        teaming = create_approved_teaming(
            agreement["id"], vehicle["id"],
            integrator_name="Integ Co", small_business=False,
            revenue_share_pct=0.10,
        )
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "price_list_id": price_list["id"],
             "teaming_id": teaming["id"], "buyer_tier": "FEDERAL",
             "lines": [{"sku": "SW-1", "qty": 10}]},
            INT,
        )
        order = validate_success(resp, expected_status=201)
        assert order["order_total_cents"] == 100000
        assert order["teaming_surcharge_cents"] == 3000
        assert order["order_total_cents"] == 10000 * 10  # surcharge not folded in

    def test_surcharge_floor_branch_dominates_at_low_share(self, api):
        """PRD §3.6: "select the larger of the raw uplift and the floor
        amount; cap the result at 500000 cents (five thousand dollars per
        order); and round half-up to integer cents."

        Design: Difficulty/combinatorial_formula/teaming_surcharge_mode_a_min_max_floor_cap
        """
        _, agreement, vehicle, price_list = setup_active_chain()
        teaming = create_approved_teaming(
            agreement["id"], vehicle["id"],
            integrator_name="Integ Co", small_business=False,
            revenue_share_pct=0.01,
        )
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "price_list_id": price_list["id"],
             "teaming_id": teaming["id"], "buyer_tier": "FEDERAL",
             "lines": [{"sku": "SW-1", "qty": 10}]},
            INT,
        )
        order = validate_success(resp, expected_status=201)
        # raw = 100000*0.01*0.30 = 300; floor = 100000*0.015 = 1500 -> floor dominates.
        assert order["order_total_cents"] == 100000
        assert order["teaming_surcharge_cents"] == 1500


class TestOrderPricingPerLineRounding:
    def test_two_line_order_total_is_per_line_sum(self, api):
        """PRD §3.6: "The order's order_total_cents is the integer sum of
        these per-line subtotals — the per-line rounding order is pinned and
        sum-then-round is not permitted."

        Design: Difficulty/combinatorial_formula/order_pricing_mode_b_per_line_rounding
        """
        lines = [
            {"sku": "SW-A", "basis_price_cents": 20000,
             "offered_price_cents": 10001, "origin_country": "US"},
            {"sku": "SW-B", "basis_price_cents": 20000,
             "offered_price_cents": 10001, "origin_country": "US"},
        ]
        _, _, vehicle, price_list = setup_active_chain(lines=lines)
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "price_list_id": price_list["id"],
             "buyer_tier": "FEDERAL",
             "lines": [{"sku": "SW-A", "qty": 3}, {"sku": "SW-B", "qty": 7}]},
            OPS,
        )
        order = validate_success(resp, expected_status=201)
        # round_half_up(10001*3)=30003 + round_half_up(10001*7)=70007 -> 100010.
        assert order["order_total_cents"] == 100010
        assert order["teaming_surcharge_cents"] == 0

    def test_direct_order_has_zero_surcharge(self, api):
        """PRD §3.6: "When the arrangement's small_business flag is true, the
        surcharge is zero." — and a direct agency order carries no teaming
        arrangement at all, so no uplift applies.
        PRD §2.7: "The order-pricing rule has a stricter, pinned rounding
        order: each order line is rounded half-up individually first, and the
        line subtotals are then summed as integers — sum-then-round is not
        permitted."

        Design: Difficulty/combinatorial_formula/order_pricing_mode_b_per_line_rounding
        """
        _, _, vehicle, price_list = setup_active_chain()
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "price_list_id": price_list["id"],
             "buyer_tier": "FEDERAL", "lines": [{"sku": "SW-1", "qty": 5}]},
            OPS,
        )
        order = validate_success(resp, expected_status=201)
        assert order["order_total_cents"] == 50000
        assert order["teaming_surcharge_cents"] == 0
