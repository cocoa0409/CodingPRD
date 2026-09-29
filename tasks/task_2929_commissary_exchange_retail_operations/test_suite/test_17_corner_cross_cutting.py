"""Layers that only bite when they are stacked.

Two stale-view tokens on two different parents, the store version counter read across a
whole day of traffic, and a retirement whose consequences reach two hops out.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    constants as C,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_free_shelf_block_does_not_save_a_stale_store_token(api):
    """The guard is the store's own version, not the block the allocation lands on.

    PRD 2.7: "**Creating an assortment allocation** requires `expected_store_version`,
    carrying the client's last observed `version` of the store named by `store_id` in the
    body."
    PRD 2.7: "A mismatch is rejected with `ERR_STALE_STORE_VERSION` (HTTP 412)."
    PRD 2.7: "A successful allocation itself increments that store's `version` by 1, so a
    client creating several allocations against one store must re-read the store between
    writes."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_store_version_on_assortment_create_returns_conflict
    """
    store = fx.create_store(
        api,
        name="Fort Buchanan Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
        shelf_block_capacity_facings=24,
    )
    product = fx.create_product(
        api,
        sku="SKU-OCC-800",
        name="Beach Chair",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=800,
    )
    first = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AI1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    version_after_first = fx.store_version(api, store["id"])
    assert version_after_first == store["version"] + 1

    stale_body = factories.assortment_payload(
        store_id=store["id"],
        product_id=product["id"],
        expected_store_version=store["version"],
        shelf_block="AI2",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
    )
    validate_error(
        api.create_assortment(stale_body, HEADERS_ASSORTMENT_PLANNER),
        "ERR_STALE_STORE_VERSION",
        412,
    )

    assert fx.store_version(api, store["id"]) == version_after_first

    rows, meta = validate_paginated(
        api.list_assortments({"store_id": store["id"]}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]

    fresh_body = dict(stale_body, expected_store_version=version_after_first)
    validate_success(api.create_assortment(fresh_body, HEADERS_ASSORTMENT_PLANNER), 201)


def test_the_stale_delegate_token_is_checked_before_any_supersession(api):
    """The rejected grant leaves the incumbent ACTIVE and unpointed; the retry supersedes.

    PRD 2.7: "**Creating a shopper delegation** requires
    `expected_delegate_patron_version`, carrying the client's last observed `version` of
    the patron named by `delegate_patron_id` in the body."
    PRD 2.7: "A mismatch is rejected with `ERR_STALE_PATRON_VERSION` (HTTP 412). A
    successful grant itself increments the delegate patron's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_stale_delegate_patron_version_on_delegation_create_returns_conflict
    """
    sponsor_one = fx.create_patron(api, full_name="SGM (Ret) M Oyelaran", id_card_class="RETIREE")
    sponsor_two = fx.create_patron(
        api, full_name="COL (Ret) N Steinhauer", id_card_class="RETIREE"
    )
    delegate = fx.create_patron(api, full_name="SPC O Bhattacharya", id_card_class="ACTIVE_DUTY")
    first = fx.create_delegation(
        api,
        sponsor_patron_id=sponsor_one["id"],
        delegate_patron_id=delegate["id"],
        valid_from=C.AUG_01,
        valid_to=C.SEP_01,
        per_sale_spend_cap_cents=50000,
        expected_delegate_patron_version=delegate["version"],
    )
    delegate_version = fx.patron_version(api, delegate["id"])
    assert delegate_version == delegate["version"] + 1

    stale_body = factories.delegation_payload(
        sponsor_patron_id=sponsor_two["id"],
        delegate_patron_id=delegate["id"],
        expected_delegate_patron_version=delegate["version"],
        valid_from=C.AUG_10,
        valid_to=C.AUG_20,
        per_sale_spend_cap_cents=50000,
    )
    validate_error(
        api.create_delegation(stale_body, HEADERS_COMPLIANCE_OFFICER),
        "ERR_STALE_PATRON_VERSION",
        412,
    )

    assert fx.patron_version(api, delegate["id"]) == delegate_version
    incumbent = fx.read_delegation(api, first["id"])
    assert incumbent["status"] == "ACTIVE"
    assert incumbent["superseded_by_delegation_id"] is None

    _rows, meta = validate_paginated(
        api.list_delegations({"delegate_patron_id": delegate["id"]}, HEADERS_COMPLIANCE_OFFICER)
    )
    assert meta["total_count"] == 1

    fresh_body = dict(stale_body, expected_delegate_patron_version=delegate_version)
    second = validate_success(
        api.create_delegation(fresh_body, HEADERS_COMPLIANCE_OFFICER), 201
    )
    displaced = fx.read_delegation(api, first["id"])
    assert displaced["status"] == "SUPERSEDED"
    assert displaced["superseded_by_delegation_id"] == second["id"]


def test_the_store_token_advances_once_per_write_that_touches_the_store(api):
    """1 at birth, 2 after the allocation, still 2 after a line, 3 at tender, 4 at close.

    PRD 2.4: "Most record types additionally carry `updated_at`, an ISO 8601 UTC timestamp
    in the same format that is refreshed on every mutation, and `version`, an integer that
    begins at 1 when the record is created and is incremented by exactly 1 on every
    mutation of that record."
    PRD 3.6: "Finally the store's `version` and the visit's `version` are each incremented
    by 1, and the visit's `tender_state` moves `OPEN → TENDERED`."
    PRD 3.9: "6. The store's `period_close_index` is incremented by 1 and the store's
    `version` is incremented by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_store_version_increments_on_every_write
    """
    store = fx.create_store(
        api,
        name="Fort Greely Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    assert store["version"] == 1

    product = fx.create_product(
        api,
        sku="SKU-VER-500",
        name="Pasta 5lb",
        category="GROCERY_STAPLE",
        unit_cost_cents=500,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AJ1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    assert fx.store_version(api, store["id"]) == 2

    patron = fx.create_patron(api, full_name="SGT P Larsson", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 2)
    assert fx.store_version(api, store["id"]) == 2

    fx.tender_sale(api, sale["id"])
    assert fx.store_version(api, store["id"]) == 3

    closed = validate_success(api.close_period(store["id"], None, HEADERS_FUND_CONTROLLER), 200)
    assert closed["version"] == 4
    assert closed["surcharge_fund_balance_cents"] == 50
    assert closed["period_close_index"] == 1


def test_retiring_the_allocation_cancels_the_pending_shipment_it_fed(api):
    """The order is cancelled as ASSORTMENT_RETIRED and 472 of commitment is released.

    PRD 3.4: "First, every special order of the same `store_id` and `product_id` whose
    `state` is `OVERSEAS_SHIP_PENDING` is moved to `CANCELLED` with its `cancelled_reason`
    set to `ASSORTMENT_RETIRED`, because there is no longer a live allocation to fill it
    from."
    PRD 3.4: "Second, and caused by the first, the store's
    `shipping_allowance_committed_cents` is recomputed, which releases each cancelled
    order's `shipping_allowance_cents` from the commitment total."
    PRD 3.8: "Whichever branch is taken, billable weight is computed the same way: the
    product's `unit_weight_grams` multiplied by the order's `quantity`, divided by one
    thousand, and **rounded up** to the next whole kilogram whenever there is any
    remainder."

    Design: Corner/cross_cutting_complexity_layers/corner_assortment_retire_cascade_cancels_overseas_pending_order
    """
    store = fx.create_store(
        api,
        name="Torii Station Exchange",
        channel="EXCHANGE",
        region="OVERSEAS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-CAS-3000",
        name="Rice Cooker",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=3000,
        unit_weight_grams=900,
    )
    assortment = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AK1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        overseas_shipping_allowance_cents=100,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SSG Q Delacruz", id_card_class="ACTIVE_DUTY")
    order = fx.create_special_order(api, store["id"], patron["id"], product["id"], 3)
    fx.route_special_order(api, order["id"], "OVERSEAS_SHIP")
    assert fx.read_store(api, store["id"])["shipping_allowance_committed_cents"] == 472

    retired = fx.retire_assortment(api, assortment["id"], reason="VENDOR_DISCONTINUED")
    assert retired["status"] == "RETIRED"

    read_order = fx.read_special_order(api, order["id"])
    assert read_order["state"] == "CANCELLED"
    assert read_order["cancelled_reason"] == "ASSORTMENT_RETIRED"
    assert read_order["billable_weight_kg"] == 3
    assert read_order["gross_ship_cents"] == 630
    assert read_order["patron_share_cents"] == 158
    assert read_order["shipping_allowance_cents"] == 472

    assert fx.read_store(api, store["id"])["shipping_allowance_committed_cents"] == 0
