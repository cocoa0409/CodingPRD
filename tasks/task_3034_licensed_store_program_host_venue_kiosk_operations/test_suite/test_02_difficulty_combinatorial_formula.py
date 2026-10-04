"""Difficulty rule: combinatorial_formula."""
from test_helpers import (
    ADMIN,
    api_client,
    create_member,
    create_product,
    generate_statement,
    make_inspector_headers,
    make_licensee_manager_headers,
    set_clock,
    setup_operating_store,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    add_assortment_item,
    create_approved_distributor,
    create_campaign,
    create_sales_report,
    create_supply_order,
    finalize_sales_report,
)
from test_helpers.test_users import make_loyalty_member_headers


class TestRoyaltyTieredMarginalStraddle:
    def _setup(self, net_cents):
        set_clock()
        bundle = setup_operating_store(
            agreement_overrides={
                "royalty_tiers": [
                    {"threshold_cents": 0, "rate_bps": 300},
                    {"threshold_cents": 50000000, "rate_bps": 350},
                ],
            }
        )
        report = create_sales_report(
            bundle["store"]["id"], bundle["licensee_id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30",
            gross_sales_cents=net_cents, returns_cents=0, loyalty_redemption_cents=0,
        )
        finalize_sales_report(report["id"], bundle["licensee_id"])
        return bundle

    def test_tier_straddle_applies_marginal_rates(self):
        """PRD §3.7: "The statement's `royalty_amount_cents` applies the tier
        table marginally to the recognized figure: for each tier, take the
        portion of recognized sales falling between that tier's `threshold_cents`
        and the next tier's threshold (unbounded for the last tier) — never
        less than zero — multiply by the tier's `rate_bps` over the 10000
        denominator, sum all tier products unrounded, and apply a single
        round-half-up to the total for integer cents."

        Design: Difficulty/combinatorial_formula/royalty_tiered_marginal_straddle
        """
        bundle = self._setup(60000000)
        stmt = generate_statement(
            bundle["agreement"]["id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30")
        assert stmt["recognized_sales_cents"] == 60000000
        # tier1 50000000*300/10000 = 1500000; tier2 10000000*350/10000 = 350000
        assert stmt["royalty_amount_cents"] == 1850000

    def test_tier_straddle_amounts_fixed_at_generation_after_issue(self):
        """PRD §3.7: "Issuing moves `DRAFT → ISSUED` without recomputing
        anything — the amounts were fixed at generation."

        Design: Difficulty/combinatorial_formula/royalty_tiered_marginal_straddle
        """
        bundle = self._setup(60000000)
        stmt = generate_statement(
            bundle["agreement"]["id"],
            period_start_date="2026-09-01", period_end_date="2026-09-30")
        issued = validate_success(api_client.issue_royalty_statement(stmt["id"], ADMIN))
        assert issued["status"] == "ISSUED"
        assert issued["recognized_sales_cents"] == 60000000
        assert issued["royalty_amount_cents"] == 1850000


class TestSupplyOrderLineRoundingOrder:
    def _setup_three_product_order(self):
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        products = [
            create_product(unit_cost_cents=333, case_pack_units=1) for _ in range(3)
        ]
        for product in products:
            add_assortment_item(store_id, lic_id, product["id"], par_level=100)
        distributor = create_approved_distributor()
        order = create_supply_order(
            store_id, lic_id, distributor["id"],
            lines=[{"product_item_id": p["id"], "quantity": 150} for p in products],
        )
        return order

    def test_per_line_rounding_then_sum(self):
        """PRD §2.9: "Per-line-then-sum is a deliberate, pinned ordering for
        supply-order pricing: rounding happens on each line before lines are
        summed, and the alternative order (sum first, round once) is explicitly
        forbidden because it yields different cents."

        Design: Difficulty/combinatorial_formula/supply_order_line_rounding_order
        """
        order = self._setup_three_product_order()
        # per line: round_half_up(150*333*9500/10000) = round_half_up(47452.5) = 47453
        assert order["total_cost_cents"] == 3 * 47453
        assert order["total_cost_cents"] == 142359
        assert order["total_cost_cents"] != 142358
        lines, _meta = validate_paginated(
            api_client.list_supply_order_lines(ADMIN, params={"supply_order_id": order["id"]}))
        assert len(lines) == 3
        for line in lines:
            assert line["discount_bps"] == 500
            assert line["line_cost_cents"] == 47453

    def test_volume_discount_boundary_below_100(self):
        """PRD §3.5: "Each **SupplyOrderLine** snapshots the product's
        `unit_cost_cents` at order creation, earns a `discount_bps` of 500 when
        its `quantity_ordered` reaches 100 units or more (otherwise 0), and
        computes its `line_cost_cents` as the quantity times the unit cost
        times the complement of the discount over the basis-point denominator
        of 10000, rounded half-up to integer cents."

        Design: Difficulty/combinatorial_formula/supply_order_line_rounding_order
        """
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        product = create_product(unit_cost_cents=333, case_pack_units=1)
        add_assortment_item(store_id, lic_id, product["id"], par_level=100)
        distributor = create_approved_distributor()
        order = create_supply_order(
            store_id, lic_id, distributor["id"],
            lines=[{"product_item_id": product["id"], "quantity": 99}],
        )
        lines, _meta = validate_paginated(
            api_client.list_supply_order_lines(ADMIN, params={"supply_order_id": order["id"]}))
        assert lines[0]["discount_bps"] == 0
        assert lines[0]["line_cost_cents"] == 99 * 333
        assert order["total_cost_cents"] == 99 * 333


class TestPromotionPricePreviewPinnedOrder:
    def _setup(self):
        set_clock()
        bundle = setup_operating_store()
        lic_id = bundle["licensee_id"]
        store_id = bundle["store"]["id"]
        member = create_member()
        earn = validate_success(api_client.create_loyalty_event(
            member["id"],
            {"event_type": "EARN", "store_format": "LICENSED",
             "store_id": store_id, "purchase_cents": 2000},
            make_licensee_manager_headers(lic_id)), expected_status=201)
        assert earn["points"] == 10  # floor(2000/200) * 1
        campaign = create_campaign(
            store_id, start_date="2026-10-01", end_date="2026-10-10",
            discount_pct=30, floor_price_cents=800)
        return bundle, member, campaign

    def test_pinned_discount_floor_redemption_order(self):
        """PRD §3.9: "The preview pins its evaluation order because the floor
        and the redemption cap would otherwise chase each other: first the
        discounted price is computed as the base times the complement of
        `discount_pct` over 100, rounded half-up; then that price is clamped
        upward to at least `floor_price_cents`; then the member's redemption is
        the smaller of their full `points_balance` value (at 100 cents per
        point) and half of the clamped price, floored to whole cents — the
        preview always applies the licensed-store 50 percent cap; finally the
        effective price is the clamped price minus the redemption."

        Design: Difficulty/combinatorial_formula/promotion_price_preview_pinned_order
        """
        _bundle, member, campaign = self._setup()
        preview = validate_success(api_client.preview_promotion_price(
            campaign["id"], {"base_price_cents": 1000, "member_id": member["id"]}, ADMIN))
        # raw = round_half_up(1000*70/100) = 700; clamped up to floor 800
        assert preview["clamped_price_cents"] == 800
        # redemption = min(10*100, floor(800*50/100)) = min(1000, 400) = 400
        assert preview["redemption_cents"] == 400
        assert preview["effective_price_cents"] == 400

    def test_preview_returns_exactly_three_figures(self):
        """PRD §3.9: "The preview returns exactly three figures:
        `clamped_price_cents`, `redemption_cents`, and
        `effective_price_cents`."

        Design: Difficulty/combinatorial_formula/promotion_price_preview_pinned_order
        """
        _bundle, member, campaign = self._setup()
        preview = validate_success(api_client.preview_promotion_price(
            campaign["id"], {"base_price_cents": 1000, "member_id": member["id"]}, ADMIN))
        assert set(preview.keys()) == {
            "clamped_price_cents", "redemption_cents", "effective_price_cents"}
        assert preview["effective_price_cents"] == (
            preview["clamped_price_cents"] - preview["redemption_cents"])
