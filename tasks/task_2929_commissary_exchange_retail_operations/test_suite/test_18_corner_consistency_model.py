"""Nothing lags behind the request that caused it.

The tender response itself already carries every derived money figure, and the reads that
follow it agree exactly.
"""
from test_helpers import (
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    validate_paginated,
    validate_success,
)


def test_the_tender_response_already_carries_every_derived_figure(api):
    """Markup 200, surcharge 110, total 2510 and a settled allowance of 330, in one reply.

    PRD 3.5: "Note carefully that the markup is rounded **per unit**, before quantity is
    involved: the rounded per-unit price is what gets multiplied."
    PRD 3.5: "Finally `total_due_cents` is `merchandise_cents` plus `markup_total_cents`
    plus `surcharge_total_cents` plus `tax_cents`."
    PRD 3.6: "The **settled** figure, held in `settled_allowance_cents` and written exactly
    once at tender, tests each governing allocation's window against the logical clock's
    instant **at tender**."

    Design: Corner/consistency_model/corner_tender_response_shows_all_derived_money_in_the_same_request
    """
    store = fx.create_store(
        api,
        name="Fort Story Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
        exchange_markup_bp=1000,
    )
    product = fx.create_product(
        api,
        sku="SKU-IMM-500",
        name="Camp Chair",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=500,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AM1",
        facings=6,
        supply_mode="DSD",
        vendor_name="Harborline Goods",
        promo_allowance_bp=1500,
        promo_window_start=C.AUG_01,
        promo_window_end=C.SEP_01,
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT S Kaminski", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    line = fx.add_line(api, sale["id"], product["id"], 4)

    tendered = validate_success(
        api.tender_sale(sale["id"], factories.tender_payload(), HEADERS_STORE_CASHIER), 200
    )
    assert tendered["tender_state"] == "TENDERED"
    assert tendered["merchandise_cents"] == 2200
    assert tendered["markup_total_cents"] == 200
    assert tendered["surcharge_total_cents"] == 110
    assert tendered["tax_cents"] == 0
    assert tendered["total_due_cents"] == 2510
    assert tendered["provisional_allowance_cents"] == 330
    assert tendered["settled_allowance_cents"] == 330
    assert tendered["allowance_variance_cents"] == 0

    read_line = validate_success(api.get_sale_line(line["id"], HEADERS_STORE_CASHIER))
    assert read_line["unit_price_cents"] == 550
    assert read_line["line_markup_cents"] == 200
    assert read_line["extended_cents"] == 2200

    read_sale = fx.read_sale(api, sale["id"])
    for field in (
        "merchandise_cents",
        "markup_total_cents",
        "surcharge_total_cents",
        "tax_cents",
        "total_due_cents",
        "provisional_allowance_cents",
        "settled_allowance_cents",
        "allowance_variance_cents",
    ):
        assert read_sale[field] == tendered[field]

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_fund_balance_cents"] == 110
    assert read_store["dividend_fund_balance_cents"] == 330

    _rows, meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 2
