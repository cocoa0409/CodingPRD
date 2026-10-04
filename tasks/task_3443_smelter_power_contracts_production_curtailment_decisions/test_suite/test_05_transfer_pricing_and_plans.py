"""Alumina transfer pricing variants and production-plan publication
(PRD §3.4, §3.9, §2.8).
"""
import pytest
from test_helpers import (
    ApiErrorId,
    assert_production_plan,
    create_alumina_agreement,
    create_alumina_agreement_payload,
    create_production_plan_payload,
    create_smelter,
    get_success_data,
    post_price_observation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTransferPriceVariants:
    def _setup_two_agreements(self):
        smelter = create_smelter()
        post_price_observation("ALUMINA_INDEX", "GLOBAL", "2026-08-15T00:00:00Z", 340.00)
        ag_cp = create_alumina_agreement(smelter["id"], refinery_name="RefineryNorth",
                                         pricing_model="COST_PLUS",
                                         base_cost_per_tonne=300.00, markup_pct=0.15,
                                         monthly_volume_tonnes=8000)
        ag_ml = create_alumina_agreement(smelter["id"], refinery_name="RefinerySouth",
                                         pricing_model="MARKET_LINKED",
                                         market_discount_pct=0.04, monthly_volume_tonnes=4000)
        return smelter, ag_cp, ag_ml

    def test_cost_plus_transfer_price(self, api, controller_headers):
        """PRD §3.4: "Under `COST_PLUS` it is the `base_cost_per_tonne`
        multiplied by one plus the `markup_pct`, ignoring the alumina market
        index entirely."

        Design: Difficulty/dual_variant_calc/alumina_transfer_cost_plus_vs_market_linked
        """
        smelter, ag_cp, _ = self._setup_two_agreements()
        data, _ = validate_paginated(
            api.list_alumina_agreements(smelter["id"], controller_headers)
        )
        cp = next(a for a in data if a["id"] == ag_cp["id"])
        # 300.00 * 1.15
        assert cp["current_transfer_price"] == pytest.approx(345.00, abs=0.01)

    def test_market_linked_transfer_price_diverges(self, api, controller_headers):
        """PRD §3.4: "Under `MARKET_LINKED` it is the latest `GLOBAL`
        `ALUMINA_INDEX` observation multiplied by one minus the
        `market_discount_pct`, reading null when no such observation exists —
        so identical refinery economics produce different transfer prices than
        the cost-plus model whenever the index diverges from cost."

        Design: Difficulty/dual_variant_calc/alumina_transfer_cost_plus_vs_market_linked
        """
        smelter, ag_cp, ag_ml = self._setup_two_agreements()
        data, _ = validate_paginated(
            api.list_alumina_agreements(smelter["id"], controller_headers)
        )
        prices = {a["id"]: a["current_transfer_price"] for a in data}
        # 340.00 * 0.96
        assert prices[ag_ml["id"]] == pytest.approx(326.40, abs=0.01)
        assert prices[ag_cp["id"]] - prices[ag_ml["id"]] == pytest.approx(18.60, abs=0.01)


class TestProductMixCapacityBoundary:
    def _setup_smelter_with_prices(self):
        smelter = create_smelter()  # 1000 tpd -> monthly capacity 30000t
        post_price_observation("ALUMINUM_LME", "GLOBAL", "2026-08-15T00:00:00Z", 2400.00)
        post_price_observation("REGIONAL_PREMIUM", "NA_NORTHWEST", "2026-08-15T00:00:00Z", 380.00)
        return smelter

    def test_plan_sum_exactly_at_capacity_accepted(self, api, controller_headers):
        """PRD §3.9: "The summed tonnage must not exceed the smelter's monthly
        capacity basis; equality with `rated_capacity_tpd` times 30 is
        allowed, and an excess is rejected with
        `ERR_PRODUCT_MIX_OVER_CAPACITY` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/product_mix_sum_exactly_at_capacity
        """
        smelter = self._setup_smelter_with_prices()
        resp = api.create_production_plan(
            create_production_plan_payload(smelter["id"], smelter["version"]),
            controller_headers,
        )
        data = validate_success(resp, 201)
        assert_production_plan(data)
        assert data["total_tonnes"] == pytest.approx(30000)

    def test_plan_sum_over_capacity_rejected(self, api, controller_headers):
        """PRD §3.9: "The summed tonnage must not exceed the smelter's monthly
        capacity basis; equality with `rated_capacity_tpd` times 30 is
        allowed, and an excess is rejected with
        `ERR_PRODUCT_MIX_OVER_CAPACITY` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/product_mix_sum_exactly_at_capacity
        """
        smelter = self._setup_smelter_with_prices()
        resp = api.create_production_plan(
            create_production_plan_payload(
                smelter["id"], smelter["version"], period_month="2026-10",
                allocations=[
                    {"product_form": "BILLET", "tonnes": 12000.01},
                    {"product_form": "SLAB", "tonnes": 9000},
                    {"product_form": "VALUE_ADDED", "tonnes": 9000},
                ],
            ),
            controller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_PRODUCT_MIX_OVER_CAPACITY)


class TestProductMixTierBoundary:
    def test_value_added_share_exactly_25pct_uses_middle_tier(self, api, controller_headers):
        """PRD §3.9: "a share below 10% earns 120 USD per tonne, a share from
        10% through 25% earns 180 (the 25% boundary belongs to this middle
        tier), and a share above 25% earns 240."
        PRD §3.9: "The pinned rounding order rounds each line's per-tonne
        margin half-up to 2 decimals first, then multiplies by that line's
        tonnage, then sums the products into `total_margin_usd`."

        Design: Corner/calculations/product_mix_value_added_tier_boundary_25pct
        """
        smelter = create_smelter()
        post_price_observation("ALUMINUM_LME", "GLOBAL", "2026-08-15T00:00:00Z", 2400.00)
        post_price_observation("REGIONAL_PREMIUM", "NA_NORTHWEST", "2026-08-15T00:00:00Z", 380.00)
        resp = api.create_production_plan(
            create_production_plan_payload(
                smelter["id"], smelter["version"],
                allocations=[
                    {"product_form": "BILLET", "tonnes": 15000},
                    {"product_form": "SLAB", "tonnes": 7500},
                    {"product_form": "VALUE_ADDED", "tonnes": 7500},
                ],
            ),
            controller_headers,
        )
        data = validate_success(resp, 201)
        assert data["total_tonnes"] == pytest.approx(30000)
        # 15000*2600.00 + 7500*2560.00 + 7500*2610.00 (VA share 0.25 -> premium 180)
        assert data["total_margin_usd"] == pytest.approx(77775000.00, abs=0.01)


class TestPlanOptimisticConcurrency:
    def _setup_plan_a(self, api, controller_headers):
        smelter = create_smelter()
        post_price_observation("ALUMINUM_LME", "GLOBAL", "2026-08-15T00:00:00Z", 2400.00)
        post_price_observation("REGIONAL_PREMIUM", "NA_NORTHWEST", "2026-08-15T00:00:00Z", 380.00)
        plan_a = validate_success(
            api.create_production_plan(
                create_production_plan_payload(smelter["id"], smelter["version"],
                                               period_month="2026-11"),
                controller_headers,
            ),
            201,
        )
        return smelter, plan_a

    def test_stale_smelter_version_rejected(self, api, controller_headers):
        """PRD §2.8: "Publishing a production plan likewise requires
        `expected_smelter_version` matching the smelter's current `version`,
        with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_plan_create_stale_smelter_version_rejected
        """
        smelter, plan_a = self._setup_plan_a(api, controller_headers)
        resp = api.create_production_plan(
            create_production_plan_payload(
                smelter["id"], smelter["version"], period_month="2026-11",
                allocations=[
                    {"product_form": "BILLET", "tonnes": 10000},
                    {"product_form": "SLAB", "tonnes": 10000},
                    {"product_form": "VALUE_ADDED", "tonnes": 5000},
                ],
            ),
            controller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        plans, _ = validate_paginated(
            api.list_production_plans(smelter["id"], controller_headers)
        )
        statuses = {p["id"]: p["status"] for p in plans}
        assert statuses[plan_a["id"]] == "PUBLISHED"
        smelter_after = validate_success(api.get_smelter(smelter["id"], controller_headers))
        assert smelter_after["version"] == 2

    def test_fresh_version_create_supersedes_published(self, api, controller_headers):
        """PRD §3.9: "Publication is also the supersession point: creating a
        plan increments the smelter's `version` by 1, and any prior plan still
        `PUBLISHED` for the same smelter and `period_month` flips to terminal
        `SUPERSEDED` with its own `version` bump."

        Design: Corner/cross_cutting_layers/occ_plan_create_supersedes_published
        """
        smelter, plan_a = self._setup_plan_a(api, controller_headers)
        fresh = get_success_data(api.get_smelter(smelter["id"], controller_headers))
        resp = api.create_production_plan(
            create_production_plan_payload(
                smelter["id"], fresh["version"], period_month="2026-11",
                allocations=[
                    {"product_form": "BILLET", "tonnes": 10000},
                    {"product_form": "SLAB", "tonnes": 10000},
                    {"product_form": "VALUE_ADDED", "tonnes": 5000},
                ],
            ),
            controller_headers,
        )
        plan_c = validate_success(resp, 201)
        assert plan_c["status"] == "PUBLISHED"
        assert plan_c["total_tonnes"] == pytest.approx(25000)

        plans, _ = validate_paginated(
            api.list_production_plans(smelter["id"], controller_headers)
        )
        statuses = {p["id"]: p["status"] for p in plans}
        assert statuses[plan_a["id"]] == "SUPERSEDED"
        published = [p for p in plans if p["status"] == "PUBLISHED"
                     and p["period_month"] == "2026-11"]
        assert len(published) == 1
