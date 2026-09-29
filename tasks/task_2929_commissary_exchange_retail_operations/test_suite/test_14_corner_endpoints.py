"""Endpoint surfaces read on their own terms.

The period-close checkpoint on a store with nothing to do, the two ledger filters, the
waterfall ordering of a store's programmes, and the two special-order surfaces that
belong to the patron rather than to the cashier.
"""
from test_helpers import (
    HEADERS_BOARD_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    constants as C,
    factories,
    fixtures as fx,
    validate_paginated,
    validate_success,
)


def test_the_checkpoint_advances_the_index_even_when_it_finds_no_work(api):
    """A store with no grants, orders, programmes or projects still reaches index 1.

    PRD 3.9: "6. The store's `period_close_index` is incremented by 1 and the store's
    `version` is incremented by 1."
    PRD 3.1: "That last counter is a monotone integer stamped onto every fund ledger
    entry as `period_close_index` at the moment the entry is written, so an auditor can
    tell which accounting period a movement belongs to; it advances only when the store's
    period-close checkpoint runs."

    Design: Corner/endpoints/corner_close_period_on_quiet_store_still_advances_the_index
    """
    store = fx.create_store(
        api,
        name="Fort Wainwright Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )

    closed = validate_success(api.close_period(store["id"], None, HEADERS_FUND_CONTROLLER), 200)
    assert closed["period_close_index"] == 1
    assert closed["version"] == store["version"] + 1

    read_store = fx.read_store(api, store["id"])
    assert read_store["surcharge_fund_balance_cents"] == 0
    assert read_store["dividend_fund_balance_cents"] == 0
    assert read_store["surcharge_obligated_cents"] == 0
    assert read_store["fund_posture"] == "FROZEN"

    _rows, meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0


def test_the_entry_type_filter_narrows_the_ledger_to_one_fund(api):
    """One tender writes two rows into two funds; the filter returns the dividend one.

    PRD 3.6: "A store's ledger can be read in `created_at` ascending order with optional
    `fund` and `entry_type` filters."
    PRD 3.6: "Each entry also records `balance_after_cents`, the running balance of its
    own pairing of `store_id` and `fund` as at that entry, computed by walking that
    pairing's entries in `created_at` ascending order and breaking ties on equal
    `created_at` by `entry_type` in ascending alphabetical order."
    PRD 3.6: "Second, only when `settled_allowance_cents` is greater than 0, an entry
    against the `DIVIDEND` fund with `entry_type` of `ALLOWANCE_CREDIT` and
    `amount_cents` equal to `settled_allowance_cents` as a positive amount, again with
    `source_ref_kind` of `SALE` and `source_ref_id` naming the visit."

    Design: Corner/endpoints/corner_fund_ledger_filtered_by_entry_type_returns_subset
    """
    store = fx.create_store(
        api,
        name="Fort Bragg Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
        exchange_markup_bp=0,
    )
    product = fx.create_product(
        api,
        sku="SKU-LED-1000",
        name="Energy Drink 24pk",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=1000,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AC1",
        facings=6,
        supply_mode="DSD",
        vendor_name="Northline Beverage",
        promo_allowance_bp=2000,
        promo_window_start=C.AUG_01,
        promo_window_end=C.SEP_01,
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT A Lindqvist", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 5)
    fx.tender_sale(api, sale["id"])

    rows, meta = validate_paginated(
        api.list_fund_ledger(
            store["id"], {"entry_type": "ALLOWANCE_CREDIT"}, HEADERS_FUND_CONTROLLER
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["entry_type"] == "ALLOWANCE_CREDIT"
    assert rows[0]["fund"] == "DIVIDEND"
    assert rows[0]["amount_cents"] == 1000
    assert rows[0]["balance_after_cents"] == 1000
    assert rows[0]["source_ref_kind"] == "SALE"
    assert rows[0]["source_ref_id"] == sale["id"]
    assert rows[0]["period_close_index"] == 0

    _all_rows, all_meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert all_meta["total_count"] == 2

    surcharge_rows, surcharge_meta = validate_paginated(
        api.list_fund_ledger(store["id"], {"fund": "SURCHARGE"}, HEADERS_FUND_CONTROLLER)
    )
    assert surcharge_meta["total_count"] == 1
    assert surcharge_rows[0]["amount_cents"] == 250
    assert surcharge_rows[0]["balance_after_cents"] == 250


def test_the_programme_listing_comes_back_in_waterfall_order(api):
    """Rank 1 first, and the two rank-2 programmes in the order they were registered.

    PRD 2.3: "Two endpoints do state a different ordering: the store's fund ledger is
    returned in `created_at` ascending order as an append-only sequence, and the store's
    MWR program list is returned by `priority_rank` ascending with `created_at` ascending
    as the tie-break, because that is the order in which the dividend is actually
    distributed."
    PRD 3.9: "A store's programmes can be listed in waterfall order with an optional
    `status` filter, and any single programme can be read to obtain its
    `ytd_funded_cents`."

    Design: Corner/endpoints/corner_store_mwr_programs_ordered_by_priority_rank_then_created_at
    """
    store = fx.create_store(
        api,
        name="Fort Lewis Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    early_tie = fx.create_mwr_program(
        api, store["id"], name="Youth Sports", priority_rank=2, funding_ceiling_cents=100000
    )
    top = fx.create_mwr_program(
        api, store["id"], name="Family Readiness", priority_rank=1, funding_ceiling_cents=100000
    )
    late_tie = fx.create_mwr_program(
        api, store["id"], name="Outdoor Recreation", priority_rank=2, funding_ceiling_cents=100000
    )

    rows, meta = validate_paginated(
        api.list_store_mwr_programs(store["id"], None, HEADERS_BOARD_OFFICER)
    )
    assert meta["total_count"] == 3
    assert [row["id"] for row in rows] == [top["id"], early_tie["id"], late_tie["id"]]
    assert [row["ytd_funded_cents"] for row in rows] == [0, 0, 0]
    assert [row["status"] for row in rows] == ["ACTIVE", "ACTIVE", "ACTIVE"]

    _suspended, suspended_meta = validate_paginated(
        api.list_store_mwr_programs(store["id"], {"status": "SUSPENDED"}, HEADERS_BOARD_OFFICER)
    )
    assert suspended_meta["total_count"] == 0


def test_an_order_placed_at_a_deployed_site_commits_no_freight_yet(api):
    """The 340-cent deployed rate stays out of the record until the order is routed.

    PRD 3.8: "A newly placed order sits at `state` of `SUBMITTED` with `route` still
    null, and every shipping figure — `billable_weight_kg`, `gross_ship_cents`,
    `patron_share_cents` and `shipping_allowance_cents` — at 0, with `cancelled_reason`
    null."
    PRD 3.2: "The **region** half asks where the card class may travel. `ACTIVE_DUTY`,
    `GUARD_RESERVE` and `DEPENDENT` are authorised in all three regions, `CONUS`,
    `OVERSEAS` and `DEPLOYED`."

    Design: Corner/endpoints/corner_deployed_site_special_order_is_accepted_with_no_money_committed
    """
    store = fx.create_store(
        api,
        name="Camp Arifjan Exchange",
        channel="EXCHANGE",
        region="DEPLOYED",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-DEP-4500",
        name="Field Boots",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=4500,
        unit_weight_grams=900,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AD1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SSG B Cardoza", id_card_class="ACTIVE_DUTY")

    order = validate_success(
        api.create_special_order(
            factories.special_order_payload(store["id"], patron["id"], product["id"], 3),
            HEADERS_STORE_CASHIER,
        ),
        201,
    )
    assert order["state"] == "SUBMITTED"
    assert order["route"] is None
    assert order["cancelled_reason"] is None
    assert order["billable_weight_kg"] == 0
    assert order["gross_ship_cents"] == 0
    assert order["patron_share_cents"] == 0
    assert order["shipping_allowance_cents"] == 0

    assert fx.read_store(api, store["id"])["shipping_allowance_committed_cents"] == 0


def test_a_patron_cancels_their_own_order_from_the_kiosk(api):
    """The caller is the ordering patron themselves, and the order reaches CANCELLED.

    PRD 3.8: "Cancellation is available to the cashier and to the ordering patron, and
    requires `cancelled_reason`, either `PATRON_REQUEST` or `ASSORTMENT_RETIRED`."
    PRD 3.8: "Cancelling from `SUBMITTED → CANCELLED` — or from `LOCAL_FILL_PENDING`,
    which is the same fiscal situation — finds `shipping_allowance_cents` already at 0, so
    the store's committed total is unchanged and only the order's own `version` is
    incremented."

    Design: Corner/endpoints/corner_patron_can_cancel_own_special_order_through_kiosk
    """
    store = fx.create_store(
        api,
        name="Fort Eisenhower Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-KSK-2500",
        name="Bluetooth Speaker",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=2500,
        unit_weight_grams=700,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AE1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SPC C Mwangi", id_card_class="ACTIVE_DUTY")
    order = fx.create_special_order(api, store["id"], patron["id"], product["id"], 1)

    cancelled = validate_success(
        api.cancel_special_order(
            order["id"],
            factories.cancel_payload("PATRON_REQUEST"),
            fx.patron_headers_for(patron),
        ),
        200,
    )
    assert cancelled["state"] == "CANCELLED"
    assert cancelled["cancelled_reason"] == "PATRON_REQUEST"
    assert cancelled["shipping_allowance_cents"] == 0

    assert fx.read_store(api, store["id"])["shipping_allowance_committed_cents"] == 0
