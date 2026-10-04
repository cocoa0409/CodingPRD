"""Sourcing-effective cost construction and the order price decomposition.

Covers the two dual-variant calculations: the drug-level sourcing-effective
per-unit cost (units-weighted average versus the single-cheapest view) and the
order-level acquisition cost (single-source versus blended fallback).
"""
from test_helpers import (
    create_order_payload,
    list_payload,
    get_success_data,
    validate_success,
    create_manufacturer,
    create_drug,
    create_sourced_price,
    create_price_row,
    setup_order_with_comparison,
    setup_full_stack,
    reset_clock,
    OPS,

)


class TestStockCheckEffectiveCost:

    def test_weighted_average_over_two_row_pool_returns_thirteen(self, api):
        """PRD §3.2: "In its base form it is the available-units-weighted
        average over the pool: each candidate row's unit_cost_cents multiplied
        by its available_units, summed across the pool, divided by the sum of
        available_units across the pool, with the single division rounded half
        up to the nearest cent — no per-row rounding occurs."

        Design: Difficulty/dual_variant_calc/sourcing_weighted_average_vs_cheapest_single_source_on_drug
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        m2 = create_manufacturer("Cardell Labs")
        drug = create_drug()
        p1 = create_sourced_price(drug["id"], m1["id"], unit_cost_cents=12,
                                  available_units=500, reliability_tier="A",
                                  packaging="500-count bottle")
        p2 = create_sourced_price(drug["id"], m2["id"], unit_cost_cents=20,
                                  available_units=100, reliability_tier="B",
                                  packaging="100-count bottle")

        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["effective_unit_cost_cents"] == 13, (
            "expected the units-weighted average ((12*500 + 20*100)/600 = "
            f"13.333 rounded half up to 13), got {data['effective_unit_cost_cents']}"
        )
        assert data["sourcing_status"] == "SOURCED"
        assert sorted(data["eligible_price_ids"]) == sorted([p1["id"], p2["id"]])

    def test_cheapest_single_source_view_differs_from_weighted_average_on_same_pool(self, api):
        """PRD §3.2: "A second, single-cheapest view exists and is the figure a
        patient sees before an order is created: it is simply the lowest
        unit_cost_cents across the pool, and it diverges from the weighted
        average whenever the cheapest holder is not also the largest holder of
        units."

        Design: Difficulty/dual_variant_calc/sourcing_weighted_average_vs_cheapest_single_source_on_drug
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        m2 = create_manufacturer("Cardell Labs")
        drug = create_drug()
        create_sourced_price(drug["id"], m1["id"], unit_cost_cents=12,
                             available_units=500, reliability_tier="A",
                             packaging="500-count bottle")
        create_sourced_price(drug["id"], m2["id"], unit_cost_cents=20,
                             available_units=100, reliability_tier="B",
                             packaging="100-count bottle")

        data = validate_success(api.stock_check(drug["id"], OPS))
        rows = list_payload(api.list_drug_prices_of_drug(drug["id"], OPS))
        cheapest = min(r["unit_cost_cents"] for r in rows)

        assert cheapest == 12, "the cheapest row is offered at 12 cents"
        assert data["effective_unit_cost_cents"] == 13
        assert data["effective_unit_cost_cents"] != cheapest, (
            "the weighted average must differ from the single-cheapest view "
            "when the cheapest holder is not the largest holder of units"
        )

    def test_primary_source_row_supplies_the_packaging_string(self, api):
        """PRD §3.3: "On success the drug's packaging is set from the selected
        primary price row, and effective_unit_cost_cents, ship_interval_days
        and expansion_score are recomputed."

        Design: Difficulty/dual_variant_calc/sourcing_weighted_average_vs_cheapest_single_source_on_drug
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        m2 = create_manufacturer("Cardell Labs")
        drug = create_drug()
        create_sourced_price(drug["id"], m1["id"], unit_cost_cents=12,
                             available_units=500, reliability_tier="A",
                             packaging="500-count bottle")
        create_sourced_price(drug["id"], m2["id"], unit_cost_cents=20,
                             available_units=100, reliability_tier="B",
                             packaging="100-count bottle")
        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["packaging"] == "500-count bottle", (
            "the lowest-unit-cost row supplies the packaging description"
        )


class TestOrderAcquisitionCost:

    def test_unblended_single_source_order_sets_acquisition_cost_to_the_full_line(self, api):
        """PRD §3.6: "When no fallback is attached, or the primary source
        itself holds at least as many available_units as the order's quantity,
        the order is not blended: primary_units is the full quantity,
        fallback_units is 0, is_blended_cost is false, and the blended money
        total is the primary row's unit_cost_cents multiplied by the quantity."

        Design: Difficulty/dual_variant_calc/priced_intake_blended_vs_unblended_acquisition_cost_on_order
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 12, "available_units": 600,
                        "reliability_tier": "A"}],
            formulary=True, quantity=60, packaged_quantity=100,
        )
        order = get_success_data(api.create_order(create_order_payload(
            ctx["prescription"]["id"], ctx["request"]["id"], ctx["pharmacy"]["id"],
            ctx["primary_price"]["id"], quantity=60,
        ), OPS))
        assert order["is_blended_cost"] is False
        assert order["primary_units"] == 60
        assert order["fallback_units"] == 0
        assert order["acquisition_cost_cents"] == 12, (
            "the blended total is 12 cents times 60 units = 720, divided back "
            "down by the order's quantity 60, giving a per-unit 12"
        )

    def test_blended_fallback_order_is_divided_back_to_a_per_unit_cost(self, api):
        """PRD §3.6: "Otherwise the order is blended: primary_units is the
        primary row's available_units, fallback_units is the quantity minus
        those units, is_blended_cost is true, and the blended money total is
        the primary row's unit_cost_cents multiplied by primary_units plus the
        fallback row's unit_cost_cents multiplied by fallback_units."
        PRD §3.6: "In both cases the order's acquisition_cost_cents is the
        blended total divided by the order's quantity and rounded half up to
        the nearest cent."

        Design: Difficulty/dual_variant_calc/priced_intake_blended_vs_unblended_acquisition_cost_on_order
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 16, "available_units": 400,
                        "reliability_tier": "C", "packaging": "400-count bottle"}],
            formulary=True, quantity=60, packaged_quantity=100,
        )
        fallback = ctx["prices"][0]

        # A second row with only 20 units joins the pool after admission, so it
        # cannot cover the order's quantity of 60 and the fallback attaches.
        short_source = create_sourced_price(
            ctx["drug"]["id"], ctx["manufacturer"]["id"],
            unit_cost_cents=12, available_units=20, reliability_tier="C",
            packaging="20-count bottle",
        )

        order = get_success_data(api.create_order(create_order_payload(
            ctx["prescription"]["id"], ctx["request"]["id"], ctx["pharmacy"]["id"],
            short_source["id"], quantity=60, sub_source_price_id=fallback["id"],
        ), OPS))
        assert order["is_blended_cost"] is True
        assert order["primary_units"] == 20
        assert order["fallback_units"] == 40
        assert order["acquisition_cost_cents"] == 15, (
            "the blend (12*20 + 16*40 = 880 cents) is divided back down by the "
            "quantity 60 and rounded half up, giving 15 cents per unit"
        )


class TestPriceRowSourcingEligibility:

    def test_row_leaving_sourced_empties_the_eligible_pool(self, api):
        """PRD §3.2: "When the pool is empty, effective_unit_cost_cents is
        null."
        PRD §2.10: "Rows whose sourcing dimension is UNDER_REVIEW or SUPPRESSED
        are outside the pool."

        Design: Difficulty/dual_variant_calc/sourcing_weighted_average_vs_cheapest_single_source_on_drug
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        drug = create_drug()
        row = create_sourced_price(drug["id"], m1["id"], unit_cost_cents=12,
                                   available_units=500, reliability_tier="A",
                                   packaging="500-count bottle")
        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["eligible_price_ids"] == [row["id"]]
        assert data["effective_unit_cost_cents"] == 12

        get_success_data(api.move_price_sourcing(row["id"], "UNDER_REVIEW", OPS))
        data = validate_success(api.stock_check(drug["id"], OPS))
        assert data["eligible_price_ids"] == []
        assert data["effective_unit_cost_cents"] is None

    def test_proposed_row_contributes_nothing_to_the_eligible_pool(self, api):
        """PRD §3.1: "A new row starts with its two dimensions at their initial
        values: price_status at PROPOSED and sourcing_status at UNDER_REVIEW."
        PRD §2.10: "Rows whose price dimension is PROPOSED or REVOKED are
        outside the pool."

        Design: Difficulty/dual_variant_calc/sourcing_weighted_average_vs_cheapest_single_source_on_drug
        """
        reset_clock()
        m1 = create_manufacturer("Bexley Generics")
        drug = create_drug()
        row = create_price_row(drug["id"], m1["id"], unit_cost_cents=12,
                               available_units=500, reliability_tier="A",
                               packaging="500-count bottle")
        assert row["price_status"] == "PROPOSED"
        assert row["sourcing_status"] == "UNDER_REVIEW"

        data = validate_success(api.stock_check(drug["id"], OPS))
        assert row["id"] not in data["eligible_price_ids"]
        assert data["effective_unit_cost_cents"] is None


class TestOrderComparisonSnapshot:

    def test_order_comparison_starts_fresh_unsubstantiated_with_a_30_day_deadline(self, api):
        """PRD §3.9: "A comparison record starts at state FRESH with
        substantiated false, substantiation_digest empty, status
        UNSUBSTANTIATED, and stale_deadline_at set to 30 days after its
        creation."

        Design: Difficulty/dual_variant_calc/priced_intake_blended_vs_unblended_acquisition_cost_on_order
        """
        reset_clock()
        ctx, comparison = setup_order_with_comparison(quantity=60)
        assert comparison["order_id"] == ctx["order"]["id"]
        assert comparison["state"] == "FRESH"
        assert comparison["status"] == "UNSUBSTANTIATED"
        assert comparison["substantiated"] is False
        assert comparison["substantiation_digest"] is None

    def test_order_snapshots_the_drug_reference_prices_at_creation(self, api):
        """PRD §3.6: "Its retail_reference_price_cents and
        insured_reference_price_cents are snapshotted from the drug at this
        moment, so later changes to the drug's reference prices do not move the
        order's recorded comparison basis."

        Design: Difficulty/dual_variant_calc/priced_intake_blended_vs_unblended_acquisition_cost_on_order
        """
        reset_clock()
        ctx, comparison = setup_order_with_comparison(
            quantity=60,
            drug_rows=[{"unit_cost_cents": 12, "available_units": 600}],
        )
        order = get_success_data(api.get_order(ctx["order"]["id"], OPS))
        assert order["retail_reference_price_cents"] == 4200
        assert order["insured_reference_price_cents"] == 3600
        assert comparison["typical_retail_price_cents"] == 4200
        assert comparison["benefit_covered_price_cents"] == 3600