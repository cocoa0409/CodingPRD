"""Undo paths that must give back exactly what was taken.

The ledger's signed sum has to return to zero after a void, and a store's committed
shipping allowance has to return to zero after a cancellation.
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


def _scene_tendered_visit_with_two_half_cent_lines(api):
    """A TENDERED visit that collected 53 + 53 = 106 cents of surcharge."""
    store = fx.create_store(
        api,
        name="Camp Lejeune Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-FOR-350",
        name="Infant Formula 12oz",
        category="INFANT_FORMULA",
        unit_cost_cents=350,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="N4",
        facings=8,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="GYSGT P Arriaga", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_12)
    sale = fx.open_sale(api, store["id"], patron["id"])
    line_a = fx.add_line(api, sale["id"], product["id"], 3)
    line_b = fx.add_line(api, sale["id"], product["id"], 3)
    tendered = fx.tender_sale(api, sale["id"])
    return {
        "store": store,
        "product": product,
        "patron": patron,
        "sale": sale,
        "line_a": line_a,
        "line_b": line_b,
        "tendered": tendered,
    }


def test_voiding_a_tendered_visit_returns_the_surcharge_fund_to_zero(api):
    """A reversal of exactly -106 lands beside the collection and the balance is 0.

    PRD 3.6: "Voiding from `TENDERED → VOIDED` reverses the collection. An entry is
    appended against the `SURCHARGE` fund with `entry_type` of `SURCHARGE_REVERSAL`
    and `amount_cents` equal to the negative of the visit's `surcharge_total_cents`,
    with `source_ref_kind` of `SALE` and `source_ref_id` naming the visit."
    PRD 3.6: "The store's `surcharge_fund_balance_cents`,
    `dividend_fund_balance_cents` and `fund_posture` are then recomputed, and because
    the reversal is the exact negation of the collection, the surcharge balance
    returns precisely to its pre-tender value — the compensating pair leaves no
    drift."

    Design: Difficulty/compensating_invariant/void_after_tender_restores_surcharge_fund_balance_exactly
    """
    scene = _scene_tendered_visit_with_two_half_cent_lines(api)
    assert scene["tendered"]["surcharge_total_cents"] == 106

    voided = validate_success(
        api.void_sale(
            scene["sale"]["id"],
            factories.void_payload("OPERATOR_ERROR"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        200,
    )
    assert voided["tender_state"] == "VOIDED"

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["surcharge_fund_balance_cents"] == 0

    entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], {"fund": "SURCHARGE"}, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 2
    assert entries[0]["entry_type"] == "SURCHARGE_COLLECTION"
    assert entries[0]["amount_cents"] == 106
    assert entries[0]["balance_after_cents"] == 106
    assert entries[1]["entry_type"] == "SURCHARGE_REVERSAL"
    assert entries[1]["amount_cents"] == -106
    assert entries[1]["balance_after_cents"] == 0


def test_the_voided_visit_keeps_its_own_audit_figures_untouched(api):
    """The sale and both lines still read 106 / 2100 / 53 / 53 after the reversal.

    PRD 2.6: "Where a rate applies to several sale lines, the rate is applied and
    rounded once per line, and the rounded line results are then added together."
    PRD 2.9: "When the available surcharge is at least 500000 cents (5,000.00 US
    dollars) the posture is `UNRESTRICTED`. When it is at least 100000 cents
    (1,000.00 US dollars) but less than 500000 cents the posture is `CONSTRAINED`.
    When it is below 100000 cents the posture is `FROZEN`."

    Design: Difficulty/compensating_invariant/void_after_tender_restores_surcharge_fund_balance_exactly
    """
    scene = _scene_tendered_visit_with_two_half_cent_lines(api)

    validate_success(
        api.void_sale(
            scene["sale"]["id"],
            factories.void_payload("OPERATOR_ERROR"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        200,
    )

    sale = validate_success(api.get_sale(scene["sale"]["id"], HEADERS_STORE_CASHIER))
    assert sale["surcharge_total_cents"] == 106
    assert sale["merchandise_cents"] == 2100

    line_a = validate_success(api.get_sale_line(scene["line_a"]["id"], HEADERS_STORE_CASHIER))
    line_b = validate_success(api.get_sale_line(scene["line_b"]["id"], HEADERS_STORE_CASHIER))
    assert line_a["line_surcharge_cents"] == 53
    assert line_b["line_surcharge_cents"] == 53

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["fund_posture"] == "FROZEN"


def _scene_routed_overseas_order(api):
    """An order routed OVERSEAS_SHIP that committed exactly 1260 of subsidy."""
    store = fx.create_store(
        api,
        name="Kadena Exchange",
        channel="EXCHANGE",
        region="OVERSEAS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-GEN-900",
        name="Camp Chair",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=900,
        unit_weight_grams=900,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="P5",
        facings=3,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="TSGT L Beaumont", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_13)
    order = fx.create_special_order(api, store["id"], patron["id"], product["id"], 8)
    routed = fx.route_special_order(api, order["id"], "OVERSEAS_SHIP")
    return {"store": store, "product": product, "patron": patron, "order": order, "routed": routed}


def test_cancelling_a_routed_order_releases_exactly_what_routing_committed(api):
    """The 1260 committed at routing is released in full, not the 1680 gross.

    PRD 3.8: "Cancelling from `OVERSEAS_SHIP_PENDING → CANCELLED` subtracts exactly
    that order's `shipping_allowance_cents` from the store's
    `shipping_allowance_committed_cents`, returning the commitment total precisely to
    its pre-routing value, and increments both the store's `version` and the order's
    `version` by 1."
    PRD 3.8: "In every case `cancelled_reason` is recorded from the request."

    Design: Difficulty/compensating_invariant/cancel_after_overseas_route_releases_exact_committed_shipping_allowance
    """
    scene = _scene_routed_overseas_order(api)
    assert scene["routed"]["shipping_allowance_cents"] == 1260

    order = validate_success(
        api.cancel_special_order(
            scene["order"]["id"],
            factories.cancel_payload("PATRON_REQUEST"),
            HEADERS_STORE_CASHIER,
        ),
        200,
    )
    assert order["state"] == "CANCELLED"
    assert order["cancelled_reason"] == "PATRON_REQUEST"

    store = validate_success(api.get_store(scene["store"]["id"], HEADERS_FUND_CONTROLLER))
    assert store["shipping_allowance_committed_cents"] == 0


def test_the_cancelled_order_retains_its_freight_figures_and_posts_no_ledger_entry(api):
    """The record keeps 8 kg / 1680 / 420 / 1260 and no fund movement was written.

    PRD 3.8: "The taxpayer absorbs the rest, subject to a ceiling:
    `shipping_allowance_cents` is the smaller of 15000 cents (150.00 US dollars) and
    the larger of 0 and the difference between `gross_ship_cents` and
    `patron_share_cents` — so the allowance is never negative and never exceeds the
    ceiling, and a shipment whose subsidised portion would have run to 200.00 US
    dollars is capped at 150.00."
    PRD 3.6: "Fund ledger entries are the audit spine of the whole system and they
    are strictly append-only: each carries `store_id` identifying the fund-holding
    store, a `fund` of either `SURCHARGE` — the capital improvement fund — or
    `DIVIDEND` — exchange earnings destined for morale, welfare and recreation — and
    an `entry_type` drawn from `SURCHARGE_COLLECTION`, `SURCHARGE_REVERSAL`,
    `CAPITAL_OUTLAY`, `ALLOWANCE_CREDIT`, `ALLOWANCE_REVERSAL` and
    `DIVIDEND_TRANSFER`."

    Design: Difficulty/compensating_invariant/cancel_after_overseas_route_releases_exact_committed_shipping_allowance
    """
    scene = _scene_routed_overseas_order(api)

    validate_success(
        api.cancel_special_order(
            scene["order"]["id"],
            factories.cancel_payload("PATRON_REQUEST"),
            HEADERS_STORE_CASHIER,
        ),
        200,
    )

    order = validate_success(api.get_special_order(scene["order"]["id"], HEADERS_STORE_CASHIER))
    assert order["billable_weight_kg"] == 8
    assert order["gross_ship_cents"] == 1680
    assert order["patron_share_cents"] == 420
    assert order["shipping_allowance_cents"] == 1260

    _entries, meta = validate_paginated(
        api.list_fund_ledger(scene["store"]["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0
