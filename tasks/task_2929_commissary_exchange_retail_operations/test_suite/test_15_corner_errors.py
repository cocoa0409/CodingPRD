"""Refusal codes that have to be their own, not a shared approximation.

Anonymous access, patron self-service scope, the two terminal-state codes that are
distinct from their generic neighbours, and the six per-entity not-found codes.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_BOARD_OFFICER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_NO_AUTH,
    HEADERS_STORE_CASHIER,
    NON_EXISTENT_UUID,
    constants as C,
    factories,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_anonymous_caller_cannot_enumerate_stores(api):
    """Both headers omitted, so the listing never runs and 401 comes back instead.

    PRD 2.1: "A request that omits either header, supplies an empty string for either, or
    names a role outside the seven is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD 2.8: "1. **Authentication** — headers present and the role recognised
    (`ERR_UNAUTHENTICATED`)."

    Design: Corner/errors/corner_missing_auth_headers_returns_unauthenticated
    """
    store = fx.create_store(
        api,
        name="Fort Irwin Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )

    error = validate_error(api.list_stores(None, HEADERS_NO_AUTH), "ERR_UNAUTHENTICATED", 401)
    assert isinstance(error["message"], str)
    assert error["message"].strip() != ""
    assert "rows" not in error

    assert fx.read_store(api, store["id"])["name"] == "Fort Irwin Commissary"


def test_a_patron_may_read_their_own_visit_but_not_a_neighbours(api):
    """The role check passes and the ownership check is what refuses the read.

    PRD 2.1: "Concretely, a caller acting as `Patron` may read a patron record only when
    the addressed record is their own, may read a sale only when the sale's `patron_id`
    equals `X-User-ID`, may read or cancel a special order only when the order's
    `patron_id` equals `X-User-ID`, and may place a special order only when the
    `patron_id` in the request body equals `X-User-ID`."
    PRD 2.1: "Any of these addressed with a different patron is rejected with
    `ERR_PATRON_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/errors/corner_patron_reading_another_patrons_sale_returns_scope_violation
    """
    store = fx.create_store(
        api,
        name="Fort Riley Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    self_patron = fx.create_patron(api, full_name="SGT D Ivanenko", id_card_class="ACTIVE_DUTY")
    other_patron = fx.create_patron(api, full_name="SGT E Barbosa", id_card_class="ACTIVE_DUTY")
    other_sale = fx.open_sale(api, store["id"], other_patron["id"])

    validate_error(
        api.get_sale(other_sale["id"], fx.patron_headers_for(self_patron)),
        "ERR_PATRON_SCOPE_VIOLATION",
        403,
    )

    owner_view = validate_success(
        api.get_sale(other_sale["id"], fx.patron_headers_for(other_patron)), 200
    )
    assert owner_view["patron_id"] == other_patron["id"]
    assert owner_view["tender_state"] == "OPEN"


def test_a_second_void_of_the_same_visit_keeps_the_first_reason(api):
    """VOIDED is terminal and says so in its own code, without rewriting the reason.

    PRD 3.6: "A visit may be voided from `tender_state` of either `OPEN` or `TENDERED`; a
    visit already at `VOIDED` cannot be voided again and yields `ERR_SALE_ALREADY_VOIDED`
    (HTTP 409)."
    PRD 3.6: "Voiding from `OPEN → VOIDED` writes **no ledger entry at all**, because
    nothing was ever collected on an open basket."

    Design: Corner/errors/corner_second_void_returns_sale_already_voided
    """
    store = fx.create_store(
        api,
        name="Fort Benning Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    patron = fx.create_patron(api, full_name="PFC F Nowakowski", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.void_sale(api, sale["id"], "OPERATOR_ERROR")

    validate_error(
        api.void_sale(
            sale["id"], factories.void_payload("COMPLIANCE_HOLD"), HEADERS_COMPLIANCE_OFFICER
        ),
        "ERR_SALE_ALREADY_VOIDED",
        409,
    )

    read_sale = fx.read_sale(api, sale["id"])
    assert read_sale["tender_state"] == "VOIDED"
    assert read_sale["voided_reason"] == "OPERATOR_ERROR"

    _rows, meta = validate_paginated(
        api.list_fund_ledger(store["id"], None, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 0


def test_retiring_an_already_retired_allocation_bumps_nothing(api):
    """The refused second retirement leaves the shelf aggregate's version alone.

    PRD 3.4: "Retiring one is the planner's way of pulling an item off a shelf: it is
    legal only from `status` of `ACTIVE`, and retiring an allocation that is already
    `RETIRED` yields `ERR_ASSORTMENT_NOT_ACTIVE` (HTTP 409)."
    PRD 2.7: "A successful allocation itself increments that store's `version` by 1, so a
    client creating several allocations against one store must re-read the store between
    writes."

    Design: Corner/errors/corner_retire_of_retired_assortment_returns_assortment_not_active
    """
    store = fx.create_store(
        api,
        name="Ramstein Exchange",
        channel="EXCHANGE",
        region="OVERSEAS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-RTR-1500",
        name="Travel Mug",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=1500,
    )
    assortment = fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AF1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    fx.retire_assortment(api, assortment["id"], reason="VENDOR_DISCONTINUED")
    version_after_retire = fx.store_version(api, store["id"])

    validate_error(
        api.retire_assortment(
            assortment["id"],
            factories.assortment_retire_payload("PLANOGRAM_RESET"),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        "ERR_ASSORTMENT_NOT_ACTIVE",
        409,
    )

    read_assortment = validate_success(
        api.get_assortment(assortment["id"], HEADERS_ASSORTMENT_PLANNER)
    )
    assert read_assortment["status"] == "RETIRED"
    assert fx.store_version(api, store["id"]) == version_after_retire


def test_an_order_already_routed_cannot_be_routed_again(api):
    """LOCAL_FILL_PENDING is not routable and not terminal, so the codes differ.

    PRD 3.8: "A cashier supplies a `route` of either `LOCAL_FILL` or `OVERSEAS_SHIP`, and
    the order may only be routed while its `state` is `SUBMITTED`; routing anything else
    yields `ERR_SPECIAL_ORDER_NOT_ROUTABLE` (HTTP 409)."
    PRD 3.8: "The order will be filled from local stock, so no freight is incurred at
    all: `gross_ship_cents`, `patron_share_cents` and `shipping_allowance_cents` are all
    set to 0."

    Design: Corner/errors/corner_route_of_already_routed_order_returns_not_routable
    """
    store = fx.create_store(
        api,
        name="Fort Campbell Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-RRT-2000",
        name="Duffel Bag",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=2000,
        unit_weight_grams=700,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="AG1",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT G Yamashiro", id_card_class="ACTIVE_DUTY")
    order = fx.create_special_order(api, store["id"], patron["id"], product["id"], 2)
    fx.route_special_order(api, order["id"], "LOCAL_FILL")

    error = validate_error(
        api.route_special_order(
            order["id"], factories.route_payload("LOCAL_FILL"), HEADERS_STORE_CASHIER
        ),
        "ERR_SPECIAL_ORDER_NOT_ROUTABLE",
        409,
    )
    assert error["error_id"] != "ERR_SPECIAL_ORDER_TERMINAL"

    read_order = fx.read_special_order(api, order["id"])
    assert read_order["state"] == "LOCAL_FILL_PENDING"
    assert read_order["route"] == "LOCAL_FILL"
    assert read_order["shipping_allowance_cents"] == 0
    assert fx.read_store(api, store["id"])["shipping_allowance_committed_cents"] == 0


def test_each_addressed_collection_answers_with_its_own_not_found_code(api):
    """Six unknown identifiers, six different codes, all at 404.

    PRD 2.10: "Each addressable collection has its own dedicated not-found code — stores,
    patrons, products, assortment allocations, sales, sale lines, delegations, capital
    projects, special orders and MWR programs each have one — and the code returned always
    names the resource whose identifier failed, never the resource the caller was
    ultimately after."
    PRD 2.8: "3. **Path existence** — every identifier embedded in the URL path resolves,
    checked from left to right."

    Design: Corner/errors/corner_unknown_ids_return_entity_specific_not_found_codes
    """
    store = fx.create_store(
        api,
        name="Fort Detrick Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    patron = fx.create_patron(api, full_name="SPC H Petrosyan", id_card_class="ACTIVE_DUTY")

    validate_error(
        api.get_store(NON_EXISTENT_UUID, HEADERS_FUND_CONTROLLER), "ERR_STORE_NOT_FOUND", 404
    )
    validate_error(
        api.get_patron(NON_EXISTENT_UUID, HEADERS_COMPLIANCE_OFFICER), "ERR_PATRON_NOT_FOUND", 404
    )
    validate_error(
        api.get_assortment(NON_EXISTENT_UUID, HEADERS_ASSORTMENT_PLANNER),
        "ERR_ASSORTMENT_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_delegation(NON_EXISTENT_UUID, HEADERS_COMPLIANCE_OFFICER),
        "ERR_DELEGATION_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_capital_project(NON_EXISTENT_UUID, HEADERS_FUND_CONTROLLER),
        "ERR_PROJECT_NOT_FOUND",
        404,
    )
    validate_error(
        api.get_mwr_program(NON_EXISTENT_UUID, HEADERS_BOARD_OFFICER),
        "ERR_MWR_PROGRAM_NOT_FOUND",
        404,
    )

    assert fx.read_store(api, store["id"])["id"] == store["id"]
    assert fx.read_patron(api, patron["id"])["id"] == patron["id"]
