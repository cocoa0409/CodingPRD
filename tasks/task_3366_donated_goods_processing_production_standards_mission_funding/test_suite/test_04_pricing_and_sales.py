"""Price-point assignment, clamping, costing fallback, and retail sales."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_priced_item,
    create_sorted_items,
    get_org,
    sell_item,
    setup_org_with_standard,
    sort_item_descriptor,
    validate_error,
    validate_success,
)

ASSOCIATE = TEST_USERS["store_associate_headers"]


def _get_item(item_id) -> dict:
    return validate_success(api_client.get_donated_item(item_id, ASSOCIATE))


class TestPricingAndSales:
    def test_sell_unpriced_item_returns_invalid_state(self, api):
        """PRD 3.5: "An item not currently `ON_FLOOR` cannot be sold
        (`ERR_INVALID_STATE`), and all of this requires an `ACTIVE`
        organization."

        Design: Corner/state_machines/sell_unpriced_item_returns_invalid_state
        """
        org, site, _std = setup_org_with_standard("Org UP")
        _donation, items = create_sorted_items(
            site["id"], [sort_item_descriptor(category="TEXTILES",
                                              condition_grade="A")])
        resp = api_client.sell_item(items[0]["id"], ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert _get_item(items[0]["id"])["status"] == "SORTED"
        assert get_org(org["id"])["retail_margin_pool_cents"] == 0

    def test_sell_sold_item_twice_returns_invalid_state(self, api):
        """PRD 3.5: "The sale moves the item to `SOLD`, stamps `sold_at` with
        the logical clock, and books the margin: the difference between
        `current_selling_price_cents` and the locked `unit_cost_cents` is added
        to the organization's `retail_margin_pool_cents`, which in turn
        recomputes `margin_health` per §2.8."
        PRD 3.5: "An item not currently `ON_FLOOR` cannot be sold
        (`ERR_INVALID_STATE`), and all of this requires an `ACTIVE`
        organization."

        Design: Corner/state_machines/sell_sold_item_twice_returns_invalid_state
        """
        org, site, _std = setup_org_with_standard("Org Tw")
        item = create_priced_item(org["id"], site["id"])
        sold = sell_item(item["id"])
        assert sold["status"] == "SOLD"
        assert sold.get("sold_at")
        resp = api_client.sell_item(item["id"], ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_org(org["id"])["retail_margin_pool_cents"] == 970, (
            "margin (1000 - 30) must be credited exactly once")

    def test_pricing_without_active_standard_rejected(self, api):
        """PRD 3.3: "A `StoreAssociate` performs it; the item must currently be
        `SORTED` (anything else draws `ERR_INVALID_STATE`), its organization
        must be `ACTIVE`, and an `ACTIVE` production standard must exist for
        the organization's pairing with the item's `category` — otherwise the
        request fails with `ERR_NO_ELIGIBLE_STANDARD`."

        Design: Corner/validations/pricing_without_active_standard_rejected
        """
        # Standard covers TEXTILES only; the item is HOUSEWARES.
        org, site, _std = setup_org_with_standard("Org NS")
        _donation, items = create_sorted_items(
            site["id"], [sort_item_descriptor(category="HOUSEWARES",
                                              condition_grade="A",
                                              estimated_value_cents=100,
                                              weight_lbs=2)])
        resp = api_client.price_item(items[0]["id"], ASSOCIATE)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_STANDARD)
        item = _get_item(items[0]["id"])
        assert item["status"] == "SORTED"
        assert item.get("price_cents") is None

    def test_price_point_assignment_clamps_to_floor_and_ceiling(self, api):
        """PRD 3.3: "The assigned `price_cents` is the value the standard's
        `grade_price_map` gives the item's `condition_grade`, first capped at
        the standard's `price_ceiling_cents` and then raised to at least its
        `price_floor_cents`."
        PRD 3.3: "Finally, pricing stamps the item's floor identity:
        `floor_week` receives the current week index, `color_tag` receives the
        rotation color for that week per §2.4, `markdown_step` starts at 0, and
        `current_selling_price_cents` starts equal to `price_cents`."

        Design: Corner/calculations/price_point_assignment_clamps_to_floor_and_ceiling
        """
        org, site, _std = setup_org_with_standard(
            "Org Clamp", grade_price_map={"A": 9999, "B": 700, "C": 50})
        item_a = create_priced_item(org["id"], site["id"], grade="A",
                                    donor_name="DCLA")
        item_c = create_priced_item(org["id"], site["id"], grade="C",
                                    estimated_value_cents=40, donor_name="DCLC")
        assert item_a["price_cents"] == 5000, "grade-A map 9999 clamps to ceiling"
        assert item_a["current_selling_price_cents"] == 5000
        assert item_a["markdown_step"] == 0
        assert item_a["status"] == "ON_FLOOR"
        assert item_c["price_cents"] == 100, "grade-C map 50 clamps to floor"
        assert item_c["current_selling_price_cents"] == 100

    def test_actual_costing_falls_back_to_standard_without_closed_runs(self, api):
        """PRD 3.3: "Under the `ACTUAL` variant, it is the sum of
        `labor_cost_cents` across all of the organization's `CLOSED` processing
        runs in the item's category divided by the sum of
        `item_count_processed` across those same runs, rounded half-up to whole
        cents; if the organization has no closed runs in that category at all,
        the computation falls back to the `STANDARD` variant."
        PRD 3.3: "Under the `STANDARD` variant, the unit cost is the standard's
        `hourly_cost_cents` divided by its `target_items_per_hour`, rounded
        half-up to whole cents."

        Design: Corner/calculations/actual_costing_falls_back_to_standard_without_closed_runs
        """
        org, site, _std = setup_org_with_standard("Org AF",
                                                  costing_method="ACTUAL")
        item = create_priced_item(org["id"], site["id"], grade="A")
        assert item["unit_cost_cents"] == 30, (
            "no CLOSED runs -> STANDARD fallback: round_half_up(1800/60) = 30")
