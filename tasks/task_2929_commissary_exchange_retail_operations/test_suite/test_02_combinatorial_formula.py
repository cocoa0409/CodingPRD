"""Formulas whose answer depends on the order in which their parts are applied.

Rounding per line before summing, selecting a contingency tier before the
contingency is added, and clamping a freight subsidy through a nested minimum and
maximum are all arrangements where a plausible reordering changes the cents.
"""
from test_helpers import (
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    make_fund_controller_headers,
    validate_success,
)


def _scene_two_half_cent_lines(api):
    """A commissary visit whose first line already carries a half-cent remainder."""
    store = fx.create_store(
        api,
        name="Camp Lejeune Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-GRO-350",
        name="Long Grain Rice 5lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=350,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="C3",
        facings=8,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="PFC C Ortiz", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_03)
    sale = fx.open_sale(api, store["id"], patron["id"])
    line_a = fx.add_line(api, sale["id"], product["id"], 3)
    return {"store": store, "product": product, "patron": patron, "sale": sale, "line_a": line_a}


def test_surcharge_is_rounded_once_per_line_and_the_rounded_results_added(api):
    """Two lines of 1050 at 500 bp give 53 + 53 = 106, not 105.

    PRD 2.6: "Where a rate applies to several sale lines, the rate is applied and
    rounded once per line, and the rounded line results are then added together."

    Design: Difficulty/combinatorial_formula/surcharge_rounded_per_line_then_summed_not_summed_then_rated
    """
    scene = _scene_two_half_cent_lines(api)

    line_b = validate_success(
        api.add_sale_line(
            scene["sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 3),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )

    assert scene["line_a"]["extended_cents"] == 1050
    assert scene["line_a"]["line_surcharge_cents"] == 53
    assert line_b["extended_cents"] == 1050
    assert line_b["line_surcharge_cents"] == 53

    sale = validate_success(api.get_sale(scene["sale"]["id"], HEADERS_STORE_CASHIER))
    assert sale["surcharge_total_cents"] == 106


def test_visit_rollups_sum_the_rounded_line_figures(api):
    """The visit total is the four components added, with the pinned surcharge sum.

    PRD 3.5: "Finally `total_due_cents` is `merchandise_cents` plus
    `markup_total_cents` plus `surcharge_total_cents` plus `tax_cents`."

    Design: Difficulty/combinatorial_formula/surcharge_rounded_per_line_then_summed_not_summed_then_rated
    """
    scene = _scene_two_half_cent_lines(api)

    validate_success(
        api.add_sale_line(
            scene["sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 3),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )

    sale = validate_success(api.get_sale(scene["sale"]["id"], HEADERS_STORE_CASHIER))
    assert sale["line_count"] == 2
    assert sale["merchandise_cents"] == 2100
    assert sale["markup_total_cents"] == 0
    assert sale["surcharge_total_cents"] == 106
    assert sale["tax_cents"] == 0
    assert sale["total_due_cents"] == 2206


def _store_for_project(api):
    """An overseas exchange with an untouched surcharge fund."""
    return fx.create_store(api, name="Yokota Exchange", channel="EXCHANGE", region="OVERSEAS")


def test_contingency_tier_comes_from_the_request_amount_not_the_obligation(api):
    """495000 selects the 1000 bp tier, so the obligation is 544500.

    PRD 3.9: "Contingency is added by tier, and the evaluation order is pinned:
    **the tier is selected from the contingency-free request amount, never from
    the obligation that already contains the contingency.**"

    Design: Difficulty/combinatorial_formula/contingency_tier_selected_from_request_amount_not_from_obligation
    """
    store = _store_for_project(api)

    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Checkout lane rebuild",
                requested_amount_cents=495000,
            ),
            make_fund_controller_headers("sfc-002"),
        ),
        201,
    )

    assert project["requested_amount_cents"] == 495000
    assert project["contingency_bp"] == 1000
    assert project["contingency_cents"] == 49500
    assert project["obligation_cents"] == 544500


def test_a_drafted_project_reserves_nothing_against_the_surcharge_fund(api):
    """The freshly drafted project is DRAFT with no outlay and no obligation booked.

    PRD 3.9: "A project is born at `state` of `DRAFT` with `revision_count` at 0
    and `submitted_by_user_id`, `decided_by_user_id` and `outlay_cents` all null."

    Design: Difficulty/combinatorial_formula/contingency_tier_selected_from_request_amount_not_from_obligation
    """
    store = _store_for_project(api)

    project = validate_success(
        api.create_capital_project(
            factories.capital_project_payload(
                store_id=store["id"],
                title="Checkout lane rebuild",
                requested_amount_cents=495000,
            ),
            make_fund_controller_headers("sfc-002"),
        ),
        201,
    )

    assert project["state"] == "DRAFT"
    assert project["revision_count"] == 0
    assert project["submitted_by_user_id"] is None
    assert project["decided_by_user_id"] is None
    assert project["outlay_cents"] is None

    read_store = validate_success(api.get_store(store["id"], HEADERS_FUND_CONTROLLER))
    assert read_store["surcharge_obligated_cents"] == 0
    assert read_store["fund_posture"] == "FROZEN"


def _scene_deployed_heavy_order(api):
    """A deployed-site special order heavy enough to hit the subsidy ceiling."""
    store = fx.create_store(
        api, name="Camp Arifjan Exchange", channel="EXCHANGE", region="DEPLOYED"
    )
    product = fx.create_product(
        api,
        sku="SKU-GEN-600",
        name="Field Locker",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=8000,
        unit_weight_grams=6000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="D4",
        facings=2,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SSG D Pike", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_04)
    order = fx.create_special_order(api, store["id"], patron["id"], product["id"], 10)
    return {
        "store": store,
        "store_before_route": fx.read_store(api, store["id"]),
        "product": product,
        "patron": patron,
        "order": order,
    }


def test_shipping_allowance_is_clamped_by_the_outer_ceiling(api):
    """60 kg at 340 cents gives 20400 gross, 5100 share and a 15000 capped subsidy.

    PRD 3.8: "The taxpayer absorbs the rest, subject to a ceiling:
    `shipping_allowance_cents` is the smaller of 15000 cents (150.00 US dollars)
    and the larger of 0 and the difference between `gross_ship_cents` and
    `patron_share_cents` — so the allowance is never negative and never exceeds
    the ceiling, and a shipment whose subsidised portion would have run to 200.00
    US dollars is capped at 150.00."

    Design: Difficulty/combinatorial_formula/shipping_allowance_nested_min_max_clamped_by_cap
    """
    scene = _scene_deployed_heavy_order(api)

    order = validate_success(
        api.route_special_order(
            scene["order"]["id"], factories.route_payload("OVERSEAS_SHIP"), HEADERS_STORE_CASHIER
        ),
        200,
    )

    assert order["billable_weight_kg"] == 60
    assert order["gross_ship_cents"] == 20400
    assert order["patron_share_cents"] == 5100
    assert order["shipping_allowance_cents"] == 15000


def test_the_capped_allowance_is_what_the_store_commits(api):
    """The routed order lands in OVERSEAS_SHIP_PENDING and commits exactly 15000.

    PRD 3.8: "That allowance is then added to the store's
    `shipping_allowance_committed_cents`, and both the store's `version` and the
    order's `version` are incremented by 1."

    Design: Difficulty/combinatorial_formula/shipping_allowance_nested_min_max_clamped_by_cap
    """
    scene = _scene_deployed_heavy_order(api)

    order = validate_success(
        api.route_special_order(
            scene["order"]["id"], factories.route_payload("OVERSEAS_SHIP"), HEADERS_STORE_CASHIER
        ),
        200,
    )
    assert order["state"] == "OVERSEAS_SHIP_PENDING"
    assert order["route"] == "OVERSEAS_SHIP"

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["shipping_allowance_committed_cents"] == 15000
    assert store["version"] == scene["store_before_route"]["version"] + 1
