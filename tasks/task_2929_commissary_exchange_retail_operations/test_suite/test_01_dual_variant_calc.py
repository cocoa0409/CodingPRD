"""Two computations that exist in two variants over the very same records.

The vendor promotional allowance is evaluated once against the visit's
``business_date`` and once against the tender instant; the resale risk score is
evaluated once over an age-filtered set of sales and once over a rank-filtered
one. Both pairs are asserted here on scenes where the two variants must disagree.
"""
from test_helpers import (
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    validate_paginated,
    validate_success,
)


def _scene_lapsed_promo_window(api):
    """An exchange basket rung inside a vendor promo window, tendered after it."""
    store = fx.create_store(
        api,
        name="Fort Bliss Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-DSD-001",
        name="Sports Drink 12pk",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=1000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="A1",
        facings=4,
        supply_mode="DSD",
        vendor_name="Sideline Beverage Co",
        promo_allowance_bp=1500,
        promo_window_start=C.AUG_01,
        promo_window_end=C.AUG_05,
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT A Reyes", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_02)
    sale = fx.open_sale(api, store["id"], patron["id"])
    line = fx.add_line(api, sale["id"], product["id"], 3)
    fx.set_clock(api, C.AUG_07)
    return {"store": store, "product": product, "patron": patron, "sale": sale, "line": line}


def test_settled_allowance_is_zero_when_the_clock_passed_the_promo_window(api):
    """Tendering after `promo_window_end` settles 0 against a positive provisional.

    PRD 3.6: "When the clock has advanced past a `promo_window_end` between the
    line add and the tender, the settled figure is 0 for that line while the
    provisional figure was positive."

    Design: Difficulty/dual_variant_calc/allowance_provisional_vs_settled_diverge_when_clock_passes_promo_window
    """
    scene = _scene_lapsed_promo_window(api)

    response = api.tender_sale(scene["sale"]["id"], factories.tender_payload(), HEADERS_STORE_CASHIER)
    sale = validate_success(response, 200)

    assert sale["provisional_allowance_cents"] == 450
    assert sale["settled_allowance_cents"] == 0
    assert sale["allowance_variance_cents"] == -450
    assert sale["merchandise_cents"] == 3000
    assert sale["surcharge_total_cents"] == 150
    assert sale["total_due_cents"] == 3150
    assert sale["tender_state"] == "TENDERED"


def test_only_the_settled_allowance_figure_reaches_the_dividend_fund(api):
    """A lapsed window writes a surcharge collection and no allowance credit.

    PRD 3.6: "Only `settled_allowance_cents` ever reaches the dividend fund; the
    provisional figure is a planning number and posts nowhere."

    Design: Difficulty/dual_variant_calc/allowance_provisional_vs_settled_diverge_when_clock_passes_promo_window
    """
    scene = _scene_lapsed_promo_window(api)

    validate_success(
        api.tender_sale(scene["sale"]["id"], factories.tender_payload(), HEADERS_STORE_CASHIER),
        200,
    )

    entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 1
    assert entries[0]["entry_type"] == "SURCHARGE_COLLECTION"
    assert entries[0]["amount_cents"] == 150
    assert [entry["entry_type"] for entry in entries] == ["SURCHARGE_COLLECTION"]

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["dividend_fund_balance_cents"] == 0
    assert store["surcharge_fund_balance_cents"] == 150


def _scene_aged_restricted_sale(api):
    """A tendered restricted-item basket 48 days old plus a fresh open visit."""
    store = fx.create_store(
        api,
        name="Fort Hood Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-TOB-010",
        name="Cigarette Carton",
        category="TOBACCO",
        unit_cost_cents=500,
        resale_restricted=True,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="B2",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.JUN_01,
        effective_to=C.DEC_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="CPL B Nunez", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.JUN_15)
    old_sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, old_sale["id"], product["id"], 4)
    fx.tender_sale(api, old_sale["id"])
    fx.set_clock(api, C.AUG_02)
    new_sale = fx.open_sale(api, store["id"], patron["id"])
    return {
        "store": store,
        "product": product,
        "patron": patron,
        "old_sale": old_sale,
        "new_sale": new_sale,
    }


def test_rolling_thirty_day_score_drops_the_aged_restricted_sale(api):
    """The age-filtered variant counts only the one unit inside the window.

    PRD 3.7: "Its input set is filtered by *age*: qualifying sales whose
    `business_date` is at or after the logical clock's current instant minus
    thirty days, and at or before the logical clock's current instant."

    Design: Difficulty/dual_variant_calc/patron_risk_rolling30d_and_last5_diverge_on_aged_restricted_sale
    """
    scene = _scene_aged_restricted_sale(api)

    validate_success(
        api.add_sale_line(
            scene["new_sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 1),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )

    patron = validate_success(api.get_patron(scene["patron"]["id"], HEADERS_COMPLIANCE_OFFICER))
    assert patron["resale_risk_score"] == 12
    assert patron["restricted_units_30d"] == 1
    assert patron["flagged_sale_count_30d"] == 0
    assert patron["resale_watch_status"] == "CLEAR"


def test_last_five_sales_score_keeps_the_aged_restricted_sale(api):
    """The rank-filtered variant still counts the 48-day-old basket.

    PRD 3.7: "A sale older than thirty days still counts if it is among the five
    most recent, and a sixth sale inside the thirty-day window does not count at
    all."

    Design: Difficulty/dual_variant_calc/patron_risk_rolling30d_and_last5_diverge_on_aged_restricted_sale
    """
    scene = _scene_aged_restricted_sale(api)

    validate_success(
        api.add_sale_line(
            scene["new_sale"]["id"],
            factories.sale_line_payload(scene["product"]["id"], 1),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )

    patron = validate_success(api.get_patron(scene["patron"]["id"], HEADERS_COMPLIANCE_OFFICER))
    assert patron["recent_sales_risk_score"] == 60
    assert patron["card_status"] == "VALID"
    assert patron["suspension_reason"] is None
