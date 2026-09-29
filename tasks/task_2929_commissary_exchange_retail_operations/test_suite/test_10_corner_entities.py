"""Entity-level corners: creation, retrieval, listing, defaults and immutability.

One test per corner, each asserting what the PRD pins about a record's shape, its
seeded derived fields and the codes returned when a payload or a path is wrong.
"""
from test_helpers import (
    HEADERS_ASSORTMENT_PLANNER,
    HEADERS_COMPLIANCE_OFFICER,
    HEADERS_FUND_CONTROLLER,
    HEADERS_STORE_CASHIER,
    NON_EXISTENT_UUID,
    assertions as A,
    constants as C,
    factories,
    fixtures as fx,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_store_created_with_every_optional_field_seeds_its_fund_state(api):
    """The three dials are echoed and all five derived fund fields are seeded.

    PRD 3.1: "A freshly registered store is fiscally empty. All four derived money
    figures — `surcharge_fund_balance_cents`, `surcharge_obligated_cents`,
    `dividend_fund_balance_cents` and `shipping_allowance_committed_cents` — begin at
    0, `fund_posture` is consequently derived as `FROZEN`, and `period_close_index`
    begins at 0."
    PRD 2.4: "Most record types additionally carry `updated_at`, an ISO 8601 UTC
    timestamp in the same format that is refreshed on every mutation, and `version`,
    an integer that begins at 1 when the record is created and is incremented by
    exactly 1 on every mutation of that record."

    Design: Corner/entities/corner_store_created_with_all_optional_fields_returns_derived_fund_state
    """
    store = validate_success(
        api.create_store(
            factories.store_payload(
                name="Ramstein Exchange",
                channel="EXCHANGE",
                region="OVERSEAS",
                surcharge_rate_bp=400,
                exchange_markup_bp=750,
                shelf_block_capacity_facings=30,
            ),
            HEADERS_FUND_CONTROLLER,
        ),
        201,
    )

    A.assert_store(
        store,
        name="Ramstein Exchange",
        channel="EXCHANGE",
        region="OVERSEAS",
        surcharge_rate_bp=400,
        exchange_markup_bp=750,
        shelf_block_capacity_facings=30,
        surcharge_fund_balance_cents=0,
        surcharge_obligated_cents=0,
        dividend_fund_balance_cents=0,
        shipping_allowance_committed_cents=0,
        fund_posture="FROZEN",
        period_close_index=0,
        version=1,
    )


def test_reading_an_enrolled_patron_returns_the_clean_enrolment_record(api):
    """The read echoes the enrolment and shows both axes and all counters at rest.

    PRD 3.2: "`card_status` starts at `VALID` with `suspension_reason` null, and
    `resale_watch_status` starts at `CLEAR`."
    PRD 3.2: "The four derived compliance figures — `resale_risk_score`,
    `recent_sales_risk_score`, `restricted_units_30d` and `flagged_sale_count_30d` —
    all start at 0, and so does `manual_strike_count`, the tally of strikes an
    officer has recorded by hand."

    Design: Corner/entities/corner_get_patron_returns_stored_enrollment_record
    """
    created = fx.create_patron(
        api, full_name="MSG (Ret) D Whitlock", id_card_class="RETIREE"
    )

    patron = validate_success(api.get_patron(created["id"], HEADERS_COMPLIANCE_OFFICER))

    A.assert_patron(
        patron,
        full_name="MSG (Ret) D Whitlock",
        id_card_class="RETIREE",
        card_status="VALID",
        suspension_reason=None,
        resale_watch_status="CLEAR",
        resale_risk_score=0,
        recent_sales_risk_score=0,
        restricted_units_30d=0,
        flagged_sale_count_30d=0,
        manual_strike_count=0,
        sponsor_patron_id=None,
        version=created["version"],
    )


def test_the_second_product_page_reports_the_whole_filtered_count(api):
    """total_count counts all three products while the page carries one row.

    PRD 2.3: "List responses carry four pagination fields inside `meta`: `limit`
    (the page size actually applied), `offset` (the page start actually applied),
    `total_count` (the number of records matching the filters before paging) and
    `has_more` (true when records remain beyond the current page)."
    PRD 2.3: "Unless a particular endpoint's description in §4 states a different
    ordering, every list is sorted by `created_at` in ascending order."

    Design: Corner/entities/corner_products_list_second_page_reports_total_count_and_has_more
    """
    fx.create_product(
        api, sku="SKU-PAG-001", name="Canned Corn", category="GROCERY_STAPLE", unit_cost_cents=120
    )
    fx.create_product(
        api, sku="SKU-PAG-002", name="Canned Peas", category="GROCERY_STAPLE", unit_cost_cents=130
    )
    third = fx.create_product(
        api, sku="SKU-PAG-003", name="Canned Beans", category="GROCERY_STAPLE", unit_cost_cents=140
    )

    rows, meta = validate_paginated(
        api.list_products({"limit": 2, "offset": 2}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["has_more"] is False
    assert len(rows) == 1
    assert rows[0]["id"] == third["id"]

    first_page, first_meta = validate_paginated(
        api.list_products({"limit": 2, "offset": 0}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert len(first_page) == 2
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True


def test_an_unknown_special_order_id_returns_the_orders_own_not_found_code(api):
    """A well-formed id matching no order gives 404 ERR_SPECIAL_ORDER_NOT_FOUND.

    PRD 2.8: "**Path existence** — every identifier embedded in the URL path
    resolves, checked from left to right."
    PRD 5: "Every error response carries one of the identifiers below in
    `data.error_id`, together with the HTTP status shown."

    Design: Corner/entities/corner_get_special_order_with_unknown_id_returns_not_found
    """
    error = validate_error(
        api.get_special_order(NON_EXISTENT_UUID, HEADERS_STORE_CASHIER),
        "ERR_SPECIAL_ORDER_NOT_FOUND",
        404,
    )
    assert isinstance(error["message"], str)
    assert error["message"]


def test_an_unknown_sale_line_id_returns_the_child_collections_not_found_code(api):
    """The child collection answers with ERR_SALE_LINE_NOT_FOUND, not the sale's code.

    PRD 2.8: "**Path existence** — every identifier embedded in the URL path
    resolves, checked from left to right."
    PRD 5: "Every error response carries one of the identifiers below in
    `data.error_id`, together with the HTTP status shown."

    Design: Corner/entities/corner_get_sale_line_with_unknown_id_returns_not_found
    """
    error = validate_error(
        api.get_sale_line(NON_EXISTENT_UUID, HEADERS_STORE_CASHIER),
        "ERR_SALE_LINE_NOT_FOUND",
        404,
    )
    assert error["error_id"] != "ERR_SALE_NOT_FOUND"


def test_an_allocation_without_facings_is_a_schema_failure_that_writes_nothing(api):
    """Omitting the mandatory facings count is 422 and leaves the store untouched.

    PRD 3.4: "An assortment allocation names the `store_id` receiving the item and
    the `product_id` being allocated, the `shelf_block` it occupies (a planogram
    block code of between 1 and 8 characters), and the number of `facings` it
    consumes there, which must be at least 1."
    PRD 2.8: "**Request schema** — required body fields present, types correct, enum
    members legal, integers inside their declared ranges, instants parseable
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/corner_create_assortment_missing_facings_returns_invalid_request
    """
    store = fx.create_store(
        api, name="Fort Riley Commissary", channel="COMMISSARY", region="CONUS"
    )
    product = fx.create_product(
        api,
        sku="SKU-REQ-010",
        name="Whole Milk Gallon",
        category="GROCERY_STAPLE",
        unit_cost_cents=380,
    )
    payload = factories.assortment_payload(
        store_id=store["id"],
        product_id=product["id"],
        expected_store_version=store["version"],
        shelf_block="A1",
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
    )
    payload.pop("facings")

    validate_error(
        api.create_assortment(payload, HEADERS_ASSORTMENT_PLANNER), "ERR_INVALID_REQUEST", 422
    )

    _rows, meta = validate_paginated(
        api.list_assortments({"store_id": store["id"]}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert meta["total_count"] == 0

    read_store = validate_success(api.get_store(store["id"], HEADERS_FUND_CONTROLLER))
    assert read_store["version"] == store["version"]


def test_a_store_created_bare_takes_the_three_declared_dial_defaults(api):
    """Omitting all three dials yields 500 basis points, no markup and 24 facings.

    PRD 3.1: "`surcharge_rate_bp` is the cost-plus surcharge applied to every sale
    line, expressed in basis points, defaulting to 500 — five percent — and accepted
    anywhere from 0 up to and including 1000."
    PRD 3.1: "`exchange_markup_bp` is the retail markup, also in basis points,
    defaulting to 0 and accepted from 0 up to and including 5000."
    PRD 3.1: "`shelf_block_capacity_facings` is how many facings a single shelf
    block in this store can hold, defaulting to 24 and required to be at least 1."

    Design: Corner/entities/corner_store_omitting_optional_inputs_applies_declared_defaults
    """
    store = validate_success(
        api.create_store(
            factories.store_payload(
                name="Fort Stewart Commissary", channel="COMMISSARY", region="CONUS"
            ),
            HEADERS_FUND_CONTROLLER,
        ),
        201,
    )

    assert store["surcharge_rate_bp"] == 500
    assert store["exchange_markup_bp"] == 0
    assert store["shelf_block_capacity_facings"] == 24


def test_a_product_created_bare_keeps_its_null_default_as_null(api):
    """The weight default is 500 grams, the flag is false and the limit stays null.

    PRD 3.4: "`unit_weight_grams` is the shipping weight of one unit, defaulting to
    500 and required to be at least 1, and it is the only input to a special order's
    billable weight."
    PRD 3.4: "`quantity_limit_per_visit` caps how many aggregate units of that
    product a single visit may contain; it defaults to null, meaning unlimited, and
    when supplied must be at least 1."
    PRD 3.4: "The `resale_restricted` flag, defaulting to false, marks an item as
    subject to resale-restriction enforcement — tobacco, alcohol, infant formula and
    other controlled goods that have historically been bought on-installation and
    resold outside it."

    Design: Corner/entities/corner_product_omitting_optional_inputs_applies_declared_defaults
    """
    product = validate_success(
        api.create_product(
            factories.product_payload(
                sku="SKU-DEF-050",
                name="Paper Towels 6pk",
                category="GENERAL_MERCHANDISE",
                unit_cost_cents=640,
            ),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        201,
    )

    assert product["unit_weight_grams"] == 500
    assert product["resale_restricted"] is False
    assert product["quantity_limit_per_visit"] is None


def test_an_exchange_line_rounds_its_markup_once_per_unit(api):
    """A cost of 333 at 750 basis points gives a unit price of 358, not 357.5 scaled.

    PRD 3.5: "At an `EXCHANGE` store the line's `unit_price_cents` is
    `unit_cost_cents` plus the markup, where the markup is the product's
    `unit_cost_cents` multiplied by the store's `exchange_markup_bp`, divided by ten
    thousand, and rounded to the nearest whole cent with an exact half rounding up."
    PRD 3.5: "Note carefully that the markup is rounded **per unit**, before quantity
    is involved: the rounded per-unit price is what gets multiplied."
    PRD 3.5: "Finally `total_due_cents` is `merchandise_cents` plus
    `markup_total_cents` plus `surcharge_total_cents` plus `tax_cents`."

    Design: Corner/entities/corner_exchange_sale_line_computes_markup_rounded_per_unit
    """
    store = fx.create_store(
        api,
        name="Fort Campbell Exchange",
        channel="EXCHANGE",
        region="CONUS",
        surcharge_rate_bp=500,
        exchange_markup_bp=750,
    )
    product = fx.create_product(
        api,
        sku="SKU-EXC-333",
        name="Desk Lamp",
        category="GENERAL_MERCHANDISE",
        unit_cost_cents=333,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="B2",
        facings=6,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SGT B Ferro", id_card_class="ACTIVE_DUTY")
    fx.set_clock(api, C.AUG_04)
    sale = fx.open_sale(api, store["id"], patron["id"])

    line = validate_success(
        api.add_sale_line(
            sale["id"], factories.sale_line_payload(product["id"], 4), HEADERS_STORE_CASHIER
        ),
        201,
    )
    assert line["unit_price_cents"] == 358
    assert line["extended_cents"] == 1432
    assert line["line_markup_cents"] == 100
    assert line["line_surcharge_cents"] == 72
    assert line["line_shipping_allowance_cents"] == 0
    assert line["restricted_units"] == 0

    read_sale = validate_success(api.get_sale(sale["id"], HEADERS_STORE_CASHIER))
    assert read_sale["merchandise_cents"] == 1432
    assert read_sale["markup_total_cents"] == 100
    assert read_sale["surcharge_total_cents"] == 72
    assert read_sale["tax_cents"] == 0
    assert read_sale["total_due_cents"] == 1604


def test_a_patrons_identity_and_status_fields_are_minted_by_the_server(api):
    """The payload carries three fields; id, timestamps, version and both axes are minted.

    PRD 2.4: "Every persisted record carries a server-minted `id`, a UUID string with
    no type prefix of any kind."
    PRD 2.4: "Every record also carries `created_at`, an ISO 8601 UTC timestamp with
    three fractional digits, stamped once when the record is written and never
    altered."
    PRD 3.2: "`card_status` starts at `VALID` with `suspension_reason` null, and
    `resale_watch_status` starts at `CLEAR`."

    Design: Corner/entities/corner_patron_system_fields_are_server_generated
    """
    patron = validate_success(
        api.create_patron(
            factories.patron_payload(
                full_name="SPC C Nakamura", id_card_class="GUARD_RESERVE"
            ),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        201,
    )

    assert is_valid_uuid(patron["id"])
    assert is_iso8601_timestamp(patron["created_at"])
    assert is_iso8601_timestamp(patron["updated_at"])
    assert patron["version"] == 1
    assert patron["card_status"] == "VALID"
    assert patron["resale_watch_status"] == "CLEAR"


def test_an_illegal_channel_member_is_refused_and_no_store_is_written(api):
    """The channel enum is closed, so "PX_ANNEX" is a 422 and the collection stays empty.

    PRD 3.1: "The `channel` is either `COMMISSARY`, meaning a grocery operation that
    sells at landed cost plus surcharge, or `EXCHANGE`, meaning a general-merchandise
    operation that sells at cost plus a retail markup."
    PRD 2.8: "**Request schema** — required body fields present, types correct, enum
    members legal, integers inside their declared ranges, instants parseable
    (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/corner_store_with_illegal_channel_enum_returns_invalid_request
    """
    validate_error(
        api.create_store(
            factories.store_payload(name="Bogus Site", channel="PX_ANNEX", region="CONUS"),
            HEADERS_FUND_CONTROLLER,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    _rows, meta = validate_paginated(api.list_stores(None, HEADERS_FUND_CONTROLLER))
    assert meta["total_count"] == 0


def test_a_grant_whose_window_is_empty_is_refused_before_any_aggregate_is_touched(api):
    """valid_to equal to valid_from is a malformed window, and the delegate is untouched.

    PRD 3.3: "`valid_to` must be strictly later than `valid_from`; a window where the
    end is at or before the start is a malformed payload and yields
    `ERR_INVALID_REQUEST` (HTTP 422)."
    PRD 2.7: "A successful grant itself increments the delegate patron's `version` by
    1."

    Design: Corner/entities/corner_delegation_with_valid_to_equal_to_valid_from_returns_invalid_request
    """
    sponsor = fx.create_patron(api, full_name="SFC E Marchetti", id_card_class="ACTIVE_DUTY")
    delegate = fx.create_patron(
        api, full_name="F Marchetti", id_card_class="DEPENDENT", sponsor_patron_id=sponsor["id"]
    )

    validate_error(
        api.create_delegation(
            factories.delegation_payload(
                sponsor_patron_id=sponsor["id"],
                delegate_patron_id=delegate["id"],
                expected_delegate_patron_version=delegate["version"],
                valid_from=C.AUG_05,
                valid_to=C.AUG_05,
                per_sale_spend_cap_cents=25000,
            ),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        "ERR_INVALID_REQUEST",
        422,
    )

    _rows, meta = validate_paginated(
        api.list_delegations(
            {"delegate_patron_id": delegate["id"]}, HEADERS_COMPLIANCE_OFFICER
        )
    )
    assert meta["total_count"] == 0

    read_delegate = validate_success(api.get_patron(delegate["id"], HEADERS_COMPLIANCE_OFFICER))
    assert read_delegate["version"] == delegate["version"]


def test_a_sale_line_representation_carries_neither_updated_at_nor_version(api):
    """The priced line is append-only: id and created_at, and no mutable bookkeeping.

    PRD 2.4: "A **sale line** — the priced record of one item rung onto one visit —
    is written once and never modified; a mistaken sale is voided whole rather than
    having lines edited or deleted."
    PRD 2.4: "Both of these carry only `id` and `created_at`; both `updated_at` and
    `version` are absent from their representations entirely."

    Design: Corner/entities/corner_sale_line_carries_no_version_and_has_no_update_endpoint
    """
    store = fx.create_store(
        api,
        name="Fort Knox Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-IMM-100",
        name="Bread Loaf",
        category="GROCERY_STAPLE",
        unit_cost_cents=200,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="C3",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="CPL G Ibarra", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    created_line = fx.add_line(api, sale["id"], product["id"], 1)

    line = validate_success(api.get_sale_line(created_line["id"], HEADERS_STORE_CASHIER))

    A.assert_append_only(line)
    assert line["sale_id"] == sale["id"]
    assert line["unit_price_cents"] == 200
    assert line["extended_cents"] == 200
    assert line["line_surcharge_cents"] == 10


def test_a_fund_ledger_row_is_append_only_and_stamps_the_period_index(api):
    """The collection row carries no version, and it stamps period_close_index 0.

    PRD 2.4: "A **fund ledger entry** is likewise written once and never touched
    again."
    PRD 3.6: "Each entry stamps the store's `period_close_index` as it stood when the
    entry was written."

    Design: Corner/entities/corner_fund_ledger_entries_are_append_only_with_no_version_field
    """
    store = fx.create_store(
        api,
        name="Fort Sill Commissary",
        channel="COMMISSARY",
        region="CONUS",
        surcharge_rate_bp=500,
    )
    product = fx.create_product(
        api,
        sku="SKU-LED-200",
        name="Rice Cakes",
        category="GROCERY_STAPLE",
        unit_cost_cents=200,
    )
    fx.create_assortment(
        api,
        store_id=store["id"],
        product_id=product["id"],
        shelf_block="D4",
        facings=4,
        supply_mode="WAREHOUSE",
        effective_from=C.AUG_01,
        effective_to=C.AUG_31,
        expected_store_version=store["version"],
    )
    patron = fx.create_patron(api, full_name="SSG H Delacroix", id_card_class="ACTIVE_DUTY")
    sale = fx.open_sale(api, store["id"], patron["id"])
    fx.add_line(api, sale["id"], product["id"], 1)
    fx.tender_sale(api, sale["id"])

    rows, meta = validate_paginated(
        api.list_fund_ledger(store["id"], {"fund": "SURCHARGE"}, HEADERS_FUND_CONTROLLER)
    )
    assert meta["total_count"] == 1
    entry = rows[0]
    A.assert_append_only(entry)
    assert entry["entry_type"] == "SURCHARGE_COLLECTION"
    assert entry["amount_cents"] == 10
    assert entry["balance_after_cents"] == 10
    assert entry["source_ref_kind"] == "SALE"
    assert entry["source_ref_id"] == sale["id"]
    assert entry["period_close_index"] == 0


def test_a_dependent_enrolled_without_a_sponsor_is_refused(api):
    """The self-referential sponsor link is mandatory for a dependent.

    PRD 3.2: "A patron whose `id_card_class` is `DEPENDENT` must therefore supply
    `sponsor_patron_id`, naming another patron record, and a patron of any other
    class must leave `sponsor_patron_id` absent or null."
    PRD 3.2: "Violating either half of that rule — a dependent without a sponsor, or
    a non-dependent with one — is rejected with `ERR_SPONSOR_REQUIRED` (HTTP 422)."

    Design: Corner/entities/corner_dependent_patron_without_sponsor_returns_sponsor_required
    """
    validate_error(
        api.create_patron(
            factories.patron_payload(full_name="K Orlowski", id_card_class="DEPENDENT"),
            HEADERS_COMPLIANCE_OFFICER,
        ),
        "ERR_SPONSOR_REQUIRED",
        422,
    )

    _rows, meta = validate_paginated(api.list_patrons(None, HEADERS_COMPLIANCE_OFFICER))
    assert meta["total_count"] == 0


def test_an_allocation_naming_an_unknown_product_is_refused_before_the_version_check(api):
    """The body reference fails first, so the store's version is never consulted.

    PRD 2.8: "**Body reference existence** — every foreign key supplied in the body
    resolves."
    PRD 2.8: "The system therefore evaluates checks in a fixed doctrinal order and
    returns the first failure it finds; later checks are never reached once an earlier
    one has failed."

    Design: Corner/entities/corner_assortment_referencing_unknown_product_returns_product_not_found
    """
    store = fx.create_store(
        api, name="Fort Carson Commissary", channel="COMMISSARY", region="CONUS"
    )

    validate_error(
        api.create_assortment(
            factories.assortment_payload(
                store_id=store["id"],
                product_id=NON_EXISTENT_UUID,
                expected_store_version=store["version"],
                shelf_block="E5",
                facings=4,
                supply_mode="WAREHOUSE",
                effective_from=C.AUG_01,
                effective_to=C.AUG_31,
            ),
            HEADERS_ASSORTMENT_PLANNER,
        ),
        "ERR_PRODUCT_NOT_FOUND",
        404,
    )

    read_store = validate_success(api.get_store(store["id"], HEADERS_FUND_CONTROLLER))
    assert read_store["version"] == store["version"]

    _rows, meta = validate_paginated(
        api.list_assortments({"store_id": store["id"]}, HEADERS_ASSORTMENT_PLANNER)
    )
    assert meta["total_count"] == 0
