"""Values sitting exactly on a threshold, and one collection that is empty.

Shelf facings landing exactly on capacity must be accepted, a risk score landing
exactly on 60 must move the watch axis, and a waterfall with no eligible
programmes must leave the money where it is.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_BOARD_OFFICER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    validate_paginated,
    validate_success,
)


def _scene_sixteen_facings_on_one_block(api):
    """An overseas commissary holding 16 of its 24 facings on shelf block J9."""
    store = fx.create_store(
        api,
        name="Ansbach Commissary",
        channel="COMMISSARY",
        region="OVERSEAS",
        surcharge_rate_bp=500,
        shelf_block_capacity_facings=24,
    )
    product_a = fx.create_product(
        api,
        sku="SKU-GRO-A01",
        name="Wheat Flour 5lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=300,
    )
    product_b = fx.create_product(
        api,
        sku="SKU-GRO-B01",
        name="Granulated Sugar 4lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=280,
    )
    assortment_a = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product_a["id"],
        shelf_block="J9",
        facings=16,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_15,
        expected_store_version=store["version"],
    )
    return {
        "store": store,
        "store_after_first": fx.read_store(api, store["id"]),
        "product_a": product_a,
        "product_b": product_b,
        "assortment_a": assortment_a,
    }


def test_an_aggregate_exactly_at_shelf_capacity_is_accepted(api):
    """16 held plus 8 incoming equals the capacity of 24, so the create succeeds.

    PRD 3.4: "For the target pairing of `store_id` and `shelf_block`, the system
    adds up `facings` over every `ACTIVE` allocation whose closed window intersects
    the incoming closed window, adds the incoming `facings` to that sum, and
    requires the result to be no greater than the store's
    `shelf_block_capacity_facings`."
    PRD 3.4: "A sum exactly equal to capacity passes; anything above it is rejected
    with `ERR_SHELF_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/shelf_facings_exactly_at_capacity_is_accepted
    """
    scene = _scene_sixteen_facings_on_one_block(api)

    assortment_b = validate_success(
        api.create_assortment(
            factories.assortment_payload(
                store_id=scene["store"]["id"],
                product_id=scene["product_b"]["id"],
                expected_store_version=scene["store_after_first"]["version"],
                shelf_block="J9",
                facings=8,
                supply_mode="WAREHOUSE",
                effective_from=C.AUG_10,
                effective_to=C.AUG_20,
            ),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        201,
    )
    assert assortment_b["status"] == "ACTIVE"
    assert assortment_b["facings"] == 8

    assortment_a = validate_success(
        api.get_assortment(scene["assortment_a"]["id"], HEADERS_ASSORTMENT_PLANNER)
    )
    assert assortment_a["status"] == "ACTIVE"
    assert assortment_a["facings"] == 16


def test_the_accepted_allocation_is_listed_and_advances_the_store_once(api):
    """Both allocations are on the block and the store's version moved by exactly 1.

    PRD 2.7: "A successful allocation itself increments that store's `version` by
    1, so a client creating several allocations against one store must re-read the
    store between writes."
    PRD 2.3: "Filter query parameters, where an endpoint offers them, are additive:
    supplying two filters narrows the result to records matching both."

    Design: Difficulty/boundary_precision_check/shelf_facings_exactly_at_capacity_is_accepted
    """
    scene = _scene_sixteen_facings_on_one_block(api)

    validate_success(
        api.create_assortment(
            factories.assortment_payload(
                store_id=scene["store"]["id"],
                product_id=scene["product_b"]["id"],
                expected_store_version=scene["store_after_first"]["version"],
                shelf_block="J9",
                facings=8,
                supply_mode="WAREHOUSE",
                effective_from=C.AUG_10,
                effective_to=C.AUG_20,
            ),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        201,
    )

    _rows, meta = validate_paginated(
        api.list_assortments(
            {"store_id": scene["store"]["id"], "shelf_block": "J9"}, HEADERS_ASSORTMENT_PLANNER
        )
    )
    assert meta["total_count"] == 2

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["version"] == scene["store_after_first"]["version"] + 1


def _scene_empty_visit_for_restricted_wine(api):
    """A clean patron with an empty open basket and a restricted item on the shelf."""
    store = fx.create_store(
        api,
        name="Schofield Barracks Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-ALC-005",
        name="Table Wine 6pk",
        category="ALCOHOL",
        unit_cost_cents=900,
        resale_restricted=True,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="K1",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SPC J Ruiz", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_09)
    sale = fx.open_sale(api, store["id"], patron["id"])
    return {"store": store, "product": product, "patron": patron, "sale": sale}


def test_a_score_of_exactly_sixty_moves_the_watch_axis_and_leaves_the_card_valid(api):
    """Five restricted units score exactly 60, which is WATCH but not a suspension.

    PRD 3.7: "A score of at least 85 puts the patron at `RESTRICTED`; a score of at
    least 60 but below 85 puts them at `WATCH`; a score below 60 puts them at
    `CLEAR`."
    PRD 3.7: "When `recent_sales_risk_score` reaches 80 and the patron's
    `card_status` is `VALID`, the system suspends the card on the spot:
    `card_status` moves `VALID → SUSPENDED` with `suspension_reason` set to
    `RISK_THRESHOLD`, and the full three-hop cascade described below runs."

    Design: Difficulty/boundary_precision_check/watch_threshold_at_exactly_sixty_moves_patron_to_watch
    """
    scene = _scene_empty_visit_for_restricted_wine(api)

    validate_success(
        api.add_sale_line(
            scene["sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 5),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )

    patron = validate_success(api.get_patron(scene["patron"]["id"], HEADERS_COMPLIANCE_OFFICER))
    assert patron["resale_risk_score"] == 60
    assert patron["resale_watch_status"] == "WATCH"
    assert patron["recent_sales_risk_score"] == 60
    assert patron["card_status"] == "VALID"
    assert patron["suspension_reason"] is None


def test_the_five_restricted_units_are_recorded_on_the_line_and_the_counter(api):
    """The line carries restricted_units 5 and the audit counter agrees.

    PRD 3.5: "`restricted_units` is `quantity` when the product's
    `resale_restricted` is true and 0 otherwise."
    PRD 3.7: "`restricted_units_30d` is the total units of resale-restricted
    product the patron bought inside that set, and `flagged_sale_count_30d` is the
    number of sales in that set whose `compliance_state` is `FLAGGED`."

    Design: Difficulty/boundary_precision_check/watch_threshold_at_exactly_sixty_moves_patron_to_watch
    """
    scene = _scene_empty_visit_for_restricted_wine(api)

    line = validate_success(
        api.add_sale_line(
            scene["sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 5),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )
    assert line["restricted_units"] == 5
    assert line["extended_cents"] == 4500
    assert line["line_surcharge_cents"] == 225

    patron = validate_success(api.get_patron(scene["patron"]["id"], HEADERS_COMPLIANCE_OFFICER))
    assert patron["restricted_units_30d"] == 5
    assert patron["flagged_sale_count_30d"] == 0

    sale = validate_success(api.get_sale(scene["sale"]["id"], HEADERS_STORE_CASHIER))
    assert sale["merchandise_cents"] == 4500
    assert sale["surcharge_total_cents"] == 225


def _scene_dividend_with_only_a_suspended_programme(api):
    """300 cents of dividend money and a single suspended programme to spend it on."""
    store = fx.create_store(
        api,
        name="Lackland Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-DSD-020",
        name="Energy Bar Box",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=1000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="L1",
        facings=4,
        supply_mode="DSD",
        vendor_name="Trailhead Foods",
        promo_allowance_bp=1500,
        promo_window_start=C.AUG_01,
        promo_window_end=C.SEP_01,
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    program = fx.create_mwr_program(
        api,
        store_id=store["id"],
        name="Youth Sports League",
        priority_rank=1,
        funding_ceiling_cents=500000,
        status="SUSPENDED",
    )
    patron = fx.create_patron(api, full_name="A1C K Doyle", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_10)
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 2)
    sale = fx.tender_sale(api, sale["id"])
    return {"store": store, "product": product, "program": program, "patron": patron, "sale": sale}


def test_a_waterfall_with_no_candidates_retains_the_dividend_balance(api):
    """The only programme is suspended, so nothing is transferred and nothing fails.

    PRD 3.9: "The candidates are the store's programmes whose `status` is `ACTIVE`
    and whose `ytd_funded_cents` is strictly below their `funding_ceiling_cents`;
    `SUSPENDED` programmes and programmes already at their ceiling are skipped
    entirely."
    PRD 3.9: "If there are no candidates at all, or if money is still left after
    every candidate has reached its ceiling, the leftover simply stays in the
    dividend fund for the next period."

    Design: Difficulty/boundary_precision_check/dividend_waterfall_with_no_eligible_programs_retains_balance
    """
    scene = _scene_dividend_with_only_a_suspended_programme(api)

    validate_success(api.close_period(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER), 200)

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["dividend_fund_balance_cents"] == 300

    program = validate_success(api.get_mwr_program(scene["program"]["id"], HEADERS_BOARD_OFFICER))
    assert program["ytd_funded_cents"] == 0

    _rows, meta = validate_paginated(
        api.list_fund_ledger(
            scene["store"]["id"], {"entry_type": "DIVIDEND_TRANSFER"}, HEADERS_FUND_CONTROLLER
        )
    )
    assert meta["total_count"] == 0


def test_the_checkpoint_still_advances_and_the_allowance_credit_stands(api):
    """period_close_index reaches 1 and the single ALLOWANCE_CREDIT of 300 remains.

    PRD 3.9: "The store's `period_close_index` is incremented by 1 and the store's
    `version` is incremented by 1."
    PRD 3.6: "The difference between them is recorded: `allowance_variance_cents`
    is `settled_allowance_cents` minus `provisional_allowance_cents`, written at
    tender alongside the settled figure and therefore negative whenever a window
    lapsed mid-basket."

    Design: Difficulty/boundary_precision_check/dividend_waterfall_with_no_eligible_programs_retains_balance
    """
    scene = _scene_dividend_with_only_a_suspended_programme(api)
    assert scene["sale"]["settled_allowance_cents"] == 300
    assert scene["sale"]["allowance_variance_cents"] == 0

    validate_success(api.close_period(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER), 200)

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["period_close_index"] == 1

    rows, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], {"fund": "DIVIDEND"}, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "ALLOWANCE_CREDIT"
    assert rows[0]["amount_cents"] == 300
