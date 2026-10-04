"""Creation, retrieval, listing and derived-field behaviour of the primary resources."""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    E,
    IMPORT_HEADERS,
    PLANNER_HEADERS,
    SOM_HEADERS,
    api_client,
    factories,
    assert_allocation_line,
    assert_price_integrity_audit,
    assert_price_point,
    validate_error,
    validate_paginated,
    validate_success,
    fixtures,
)

DRAFT_QUOTE = (
    "A newly registered price point begins in `DRAFT` status and its `issued_store_count` is "
    "zero; a price point in `DRAFT` is editable but may not be issued to anything."
)
PRICE_POINT_INPUTS_QUOTE = (
    "It is registered with a `label` — a human-readable name such as `DOLLAR_25_LEGACY` — a "
    "`shelf_price_cents` value that is the single fixed retail charged to the shopper at that "
    "point, and a `target_landed_cost_ratio` expressing the maximum landed cost the buying office "
    "may commit to as a fraction of that shelf price."
)
ITEM_INPUTS_QUOTE = (
    "An item enters the assortment by being denominated. A `MerchandiseBuyer` supplies the "
    "`sku`, which must be unique across all items, a human-readable `description` that will be "
    "reproduced on both the shelf tag and the register file, a `commodity_class` that aisle "
    "changeover planning later reads, an optional `season_code` identifying the season the item "
    "belongs to and left as an empty string when the item is a year-round staple, a "
    "`unit_retail_cents` that is the fixed retail charged per selling unit, a `sqft_per_unit` "
    "expressing the shelf facing one selling unit consumes, a `shelf_package_capacity` giving the "
    "square feet of shelf facing allocated to the item at its home store and therefore the "
    "maximum the shelf can present, a `units_per_case` giving how many selling units a "
    "store-orderable case contains, a `base_landed_cost_cents` that is the vendor's free-on-board "
    "landed cost per unit before any freight pass-through, a `fixed_store_handling_cents` per "
    "case that the item must recover at the fixed retail, a `variable_store_cost_cents` per unit "
    "that is subtracted when net contribution and break-even are derived, and a "
    "`sourcing_vendor_id` naming the vendor the item is bought from."
)
PAGINATION_QUOTE = (
    "`total_count` is the count of rows matching the filters irrespective of the current page, "
    "and `has_more` indicates whether further rows remain beyond the returned page."
)
ORDERING_QUOTE = (
    "Unless a call is otherwise documented, all list endpoints return resources sorted by their "
    "creation timestamp in ascending order, and the ordering is stable across pages."
)
NOT_FOUND_QUOTE = (
    "The rejection carries an HTTP 404 and an error id specific to the resource type that failed"
)
CONTAINER_BOOKING_QUOTE = (
    "A container is then booked against that vendor with a `container_number` that must be "
    "unique, a `port_code` such as `LAX`, a `dc_code` such as `DC-ATL`, and a `total_freight_cents` "
    "for ocean and drayage. It begins `BOOKED` with `customs_cleared` false."
)
RECEIPT_GATE_QUOTE = (
    "The third option is receipt, which requires the container to be in `AT_PORT` — otherwise "
    "`ERR_CONTAINER_NOT_AT_PORT` — and requires `customs_cleared` to be true, otherwise "
    "`ERR_CUSTOMS_NOT_CLEARED` and HTTP 409."
)
HOLD_QUOTE = (
    "A customs hold moves the container to `CUSTOMS_HOLD` and clears `customs_cleared` back to "
    "false; it is refused from any status other than `AT_PORT` with `ERR_CONTAINER_NOT_AT_PORT`."
)
DERIVED_FLAGS_QUOTE = (
    "`broken_case_allowance` is true exactly when one full case cannot fit on the shelf — that "
    "is, when `units_per_case` multiplied by `sqft_per_unit` is greater than "
    "`shelf_package_capacity`."
)
OVERFLOW_FLAG_QUOTE = (
    "`is_shelf_overflow` is true exactly when `on_hand_units` multiplied by `sqft_per_unit` is "
    "greater than `shelf_package_capacity`, meaning the quantity on hand exceeds what the shelf "
    "can present."
)
CLOCK_STATUS_QUOTE = (
    "Season window status is itself clock-derived rather than freely assigned. While the clock is "
    "before the window's `opens_on`, the stored status stands as `DRAFT` or `SCHEDULED`. Once the "
    "clock reaches `opens_on` and remains at or before `closes_on`, the window reads `OPEN`. Once "
    "the clock passes `closes_on`, the window reads `CLOSED`."
)
IMMUTABLE_QUOTE = (
    "A `PriceIntegrityAudit` is an immutable event log and does not carry the common field set: "
    "it exposes `id` and `created_at` only, and neither `updated_at` nor `version` is present on it."
)
FROZEN_QUOTE = (
    "The audit's `mismatch_ratio` and its `result` are computed at creation and are then fixed "
    "for the life of the row."
)
RESOLVE_QUOTE = (
    "A `StoreOperationsManager` may resolve it directly once the shelf and the register have been "
    "reconciled; that call requires the audit to be `OPEN` and is refused with "
    "`ERR_AUDIT_ALREADY_RESOLVED` if it is not."
)
BODY_FK_QUOTE = (
    "Foreign keys supplied in a request body follow the same principle but are validated after "
    "path resolution and before any business rule. Body-supplied references are resolved in the "
    "order the endpoint's input list declares them, and an unresolvable body reference is rejected "
    "with the 404 error id of the missing resource type."
)


def test_price_point_create_returns_draft_with_zero_issued_stores(api):
    """A price point registered with its three inputs comes back DRAFT with no stores issued.

    PRD §2.4: "A newly registered price point begins in `DRAFT` status and its
    `issued_store_count` is zero; a price point in `DRAFT` is editable but may not be issued to
    anything."
    PRD §2.4: "It is registered with a `label` — a human-readable name such as
    `DOLLAR_25_LEGACY` — a `shelf_price_cents` value that is the single fixed retail charged to
    the shopper at that point, and a `target_landed_cost_ratio` expressing the maximum landed cost
    the buying office may commit to as a fraction of that shelf price."

    Design: Corner/entities/price_point_create_returns_draft_with_zero_issued_stores
    """
    fixtures.set_clock()
    created = validate_success(
        api.create_price_point(
            {"label": "DOLLAR_25", "shelf_price_cents": 125, "target_landed_cost_ratio": 0.90},
            BUYER_HEADERS),
        201,
    )
    assert_price_point(created)
    assert created["label"] == "DOLLAR_25"
    assert created["shelf_price_cents"] == 125
    assert created["target_landed_cost_ratio"] == pytest.approx(0.90)
    assert created["status"] == "DRAFT"
    assert created["issued_store_count"] == 0


def test_item_get_round_trips_every_declared_cost_input(api):
    """Every cost and geometry input written at denomination reads back unchanged.

    PRD §3.1: "An item enters the assortment by being denominated. A `MerchandiseBuyer` supplies
    the `sku`, which must be unique across all items, a human-readable `description` that will be
    reproduced on both the shelf tag and the register file, a `commodity_class` that aisle
    changeover planning later reads, an optional `season_code` identifying the season the item
    belongs to and left as an empty string when the item is a year-round staple, a
    `unit_retail_cents` that is the fixed retail charged per selling unit, a `sqft_per_unit`
    expressing the shelf facing one selling unit consumes, a `shelf_package_capacity` giving the
    square feet of shelf facing allocated to the item at its home store and therefore the maximum
    the shelf can present, a `units_per_case` giving how many selling units a store-orderable case
    contains, a `base_landed_cost_cents` that is the vendor's free-on-board landed cost per unit
    before any freight pass-through, a `fixed_store_handling_cents` per case that the item must
    recover at the fixed retail, a `variable_store_cost_cents` per unit that is subtracted when
    net contribution and break-even are derived, and a `sourcing_vendor_id` naming the vendor the
    item is bought from."

    Design: Corner/entities/item_get_round_trips_every_declared_cost_input
    """
    fixtures.set_clock()
    vendor = fixtures.create_vendor()
    item = fixtures.create_item(
        vendor["id"], sku="1001", description="Bath Bar 4ct", commodity_class="BATH",
        season_code="HARVEST_2026", unit_retail_cents=125, sqft_per_unit=0.1,
        shelf_package_capacity=4.0, units_per_case=4, base_landed_cost_cents=105,
        fixed_store_handling_cents=6, variable_store_cost_cents=4)

    read = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert read["sku"] == "1001"
    assert read["description"] == "Bath Bar 4ct"
    assert read["commodity_class"] == "BATH"
    assert read["season_code"] == "HARVEST_2026"
    assert read["unit_retail_cents"] == 125
    assert read["base_landed_cost_cents"] == 105
    assert read["sqft_per_unit"] == pytest.approx(0.1)
    assert read["shelf_package_capacity"] == pytest.approx(4.0)
    assert read["units_per_case"] == 4
    assert read["fixed_store_handling_cents"] == 6
    assert read["variable_store_cost_cents"] == 4
    assert read["sourcing_vendor_id"] == vendor["id"]


def test_items_list_pages_in_creation_order(api):
    """A list endpoint pages deterministically in creation order with the declared meta fields.

    PRD §2.3: "`total_count` is the count of rows matching the filters irrespective of the
    current page, and `has_more` indicates whether further rows remain beyond the returned page."
    PRD §2.3: "Unless a call is otherwise documented, all list endpoints return resources sorted
    by their creation timestamp in ascending order, and the ordering is stable across pages."

    Design: Corner/entities/items_list_paginates_and_filters_by_price_point
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    created = [
        fixtures.create_price_assigned_item(price_point["id"], vendor["id"], sku="1001"),
        fixtures.create_price_assigned_item(price_point["id"], vendor["id"], sku="1002"),
        fixtures.create_item(vendor["id"], sku="1003"),
    ]

    first_page, meta = validate_paginated(api.list_items(ANALYST_HEADERS, params={"limit": 2, "offset": 0}))
    assert len(first_page) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [row["id"] for row in first_page] == [created[0]["id"], created[1]["id"]], (
        "pages follow creation order, which makes them stable"
    )

    second_page, meta = validate_paginated(api.list_items(ANALYST_HEADERS, params={"limit": 2, "offset": 2}))
    assert len(second_page) == 1
    assert second_page[0]["id"] == created[2]["id"]
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    defaulted, meta = validate_paginated(api.list_items(ANALYST_HEADERS))
    assert len(defaulted) == 3
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_container_get_with_unknown_id_returns_container_not_found(api):
    """An unallocated container id produces the entity-specific 404.

    PRD §2.8: "The rejection carries an HTTP 404 and an error id specific to the resource type
    that failed"

    Design: Corner/entities/container_get_with_unknown_id_returns_container_not_found
    """
    fixtures.set_clock()
    response = api.get_container("00000000-0000-4000-8000-000000000000", IMPORT_HEADERS)
    validate_error(response, E.ERR_CONTAINER_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"
    assert set(response.json()["data"]) >= {"error_id", "message"}


def test_container_create_defaults_customs_cleared_false(api):
    """A booked container is not customs cleared, so receipt waits for a release.

    PRD §3.6: "A container is then booked against that vendor with a `container_number` that
    must be unique, a `port_code` such as `LAX`, a `dc_code` such as `DC-ATL`, and a
    `total_freight_cents` for ocean and drayage. It begins `BOOKED` with `customs_cleared` false."
    PRD §3.6: "A customs hold moves the container to `CUSTOMS_HOLD` and clears `customs_cleared`
    back to false; it is refused from any status other than `AT_PORT` with `ERR_CONTAINER_NOT_AT_PORT`."
    PRD §3.6: "The third option is receipt, which requires the container to be in `AT_PORT` —
    otherwise `ERR_CONTAINER_NOT_AT_PORT` — and requires `customs_cleared` to be true, otherwise
    `ERR_CUSTOMS_NOT_CLEARED` and HTTP 409."

    Design: Corner/entities/container_create_defaults_customs_cleared_false
    """
    fixtures.set_clock()
    vendor = fixtures.create_vendor()
    container = fixtures.create_booked_container(vendor["id"], total_freight_cents=200)
    assert container["status"] == "BOOKED"
    assert container["customs_cleared"] is False

    on_hold = fixtures.create_container_at_port(vendor["id"], total_freight_cents=200, on_hold=True)
    assert on_hold["status"] == "CUSTOMS_HOLD"
    assert on_hold["customs_cleared"] is False, "the hold clears the declared default back to false"

    validate_error(
        api_client.container_receive(on_hold["id"], IMPORT_HEADERS),
        E.ERR_CONTAINER_NOT_AT_PORT.value,
    )

    released = fixtures.container_customs_release(on_hold["id"])
    assert released["status"] == "AT_PORT"
    assert released["customs_cleared"] is True, "the release is what satisfies the receipt gate"

    received = fixtures.container_receive(on_hold["id"])
    assert received["status"] == "RECEIVED"


def test_item_computed_flags_follow_the_geometry_and_the_live_stock(api):
    """The broken-case flag is geometry and the overflow flag is stock; neither is client-set.

    PRD §3.1: "`broken_case_allowance` is true exactly when one full case cannot fit on the shelf
    — that is, when `units_per_case` multiplied by `sqft_per_unit` is greater than
    `shelf_package_capacity`."
    PRD §3.1: "`is_shelf_overflow` is true exactly when `on_hand_units` multiplied by
    `sqft_per_unit` is greater than `shelf_package_capacity`, meaning the quantity on hand
    exceeds what the shelf can present."
    PRD §3.7: "In the worked shape of that rule, a shelf that holds 40 units belonging to an item
    whose case is 100 units accepts 140 units, not 40."

    Design: Corner/entities/item_computed_flags_ignored_input_returns_computed_values
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="2001", sqft_per_unit=0.1,
        shelf_package_capacity=4.0, units_per_case=100, base_landed_cost_cents=105)

    before = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    # 100 * 0.1 == 10.0 exceeds the 4.0 shelf, so the geometry arms the base-deck allowance.
    assert before["broken_case_allowance"] is True
    assert before["on_hand_units"] == 0
    assert before["is_shelf_overflow"] is False
    assert before["status"] == "PRICE_ASSIGNED"

    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=140)
    assert_allocation_line(line)
    assert line["allocated_units"] == 140, "the base deck adds one full 100-unit case"
    assert line["overflow_units"] == 0

    fixtures.release_line(line["id"], 140)

    after = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert after["on_hand_units"] == 140
    # 140 * 0.1 == 14.0 exceeds the same 4.0 shelf, so the live stock now overflows it.
    assert after["is_shelf_overflow"] is True
    assert after["status"] == "PRICE_ASSIGNED", "the flags never move the lifecycle"


def test_season_window_status_ladder_is_clock_derived_with_an_inclusive_close(api):
    """The same stored window reads SCHEDULED, then OPEN, then OPEN at its last instant, then CLOSED.

    PRD §2.9: "Season window status is itself clock-derived rather than freely assigned. While
    the clock is before the window's `opens_on`, the stored status stands as `DRAFT` or
    `SCHEDULED`. Once the clock reaches `opens_on` and remains at or before `closes_on`, the
    window reads `OPEN`. Once the clock passes `closes_on`, the window reads `CLOSED`."
    PRD §2.9: "The upper bound is inclusive: the instant of `closes_on` itself is still `OPEN`,
    and only the instant after it is `CLOSED`."

    Design: Corner/entities/season_window_status_is_clock_derived_and_never_written
    """
    fixtures.set_clock()
    window = fixtures.create_draft_season_window(
        opens_on="2026-10-01T00:00:00Z", closes_on="2026-11-30T00:00:00Z")
    published = validate_success(api.schedule_season_window(window["id"], PLANNER_HEADERS), 200)

    early = validate_success(api.get_season_window(window["id"], ANALYST_HEADERS), 200)
    assert early["status"] == "SCHEDULED", "the clock is still before opens_on"
    assert early["opens_on"].startswith("2026-10-01T00:00:00")
    assert early["closes_on"].startswith("2026-11-30T00:00:00")

    fixtures.set_clock("2026-10-01T00:00:00Z")
    at_open = validate_success(api.get_season_window(window["id"], ANALYST_HEADERS), 200)
    assert at_open["status"] == "OPEN", "opens_on itself is inside the window"

    fixtures.set_clock("2026-11-30T00:00:00Z")
    last_instant = validate_success(api.get_season_window(window["id"], ANALYST_HEADERS), 200)
    assert last_instant["status"] == "OPEN", "closes_on itself is still an open instant"

    fixtures.set_clock("2026-12-01T00:00:00Z")
    after = validate_success(api.get_season_window(window["id"], ANALYST_HEADERS), 200)
    assert after["status"] == "CLOSED", "only the instant after closes_on closes the window"
    assert after["opens_on"] == published["opens_on"], "the clock never rewrites the bounds"


def test_price_integrity_audit_is_append_only_and_its_verdict_is_frozen(api):
    """The audit carries no modification fields, and resolving it does not launder the verdict.

    PRD §2.5: "A `PriceIntegrityAudit` is an immutable event log and does not carry the common
    field set: it exposes `id` and `created_at` only, and neither `updated_at` nor `version` is
    present on it."
    PRD §3.11: "The audit's `mismatch_ratio` and its `result` are computed at creation and are
    then fixed for the life of the row."
    PRD §3.11: "A `StoreOperationsManager` may resolve it directly once the shelf and the
    register have been reconciled; that call requires the audit to be `OPEN` and is refused with
    `ERR_AUDIT_ALREADY_RESOLVED` if it is not."

    Design: Corner/entities/price_integrity_audit_has_no_update_or_delete_surface
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()
    audit = validate_success(
        api.create_audit(factories.create_audit_payload(
            store["id"], price_point["id"], observed_item_count=80, mismatched_item_count=5),
            SOM_HEADERS),
        201,
    )
    assert_price_integrity_audit(audit)
    assert audit["mismatch_ratio"] == 0.063
    assert audit["result"] == "VIOLATION"

    resolved = validate_success(api.resolve_audit(audit["id"], SOM_HEADERS), 200)
    assert resolved["status"] == "RESOLVED"

    read = validate_success(api.get_audit(audit["id"], ANALYST_HEADERS), 200)
    assert read["observed_item_count"] == 80
    assert read["mismatched_item_count"] == 5, "the visit counts cannot be edited after the fact"
    assert read["result"] == "VIOLATION", "resolution does not soften the recorded verdict"
    assert read["mismatch_ratio"] == 0.063
    assert_price_integrity_audit(read)

    store_after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert store_after["open_violation_count"] == 0


def test_aisle_reset_creation_resolves_its_body_references_in_declared_order(api):
    """With several unresolvable references, the first declared one is the one reported.

    PRD §2.8: "Foreign keys supplied in a request body follow the same principle but are validated
    after path resolution and before any business rule. Body-supplied references are resolved in
    the order the endpoint's input list declares them, and an unresolvable body reference is
    rejected with the 404 error id of the missing resource type."
    PRD §2.8: "This ordering means that a request carrying both a missing reference and a violated
    business constraint reports the missing reference."

    Design: Corner/entities/aisle_reset_creation_requires_resolvable_store_price_point_and_window
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()

    all_unknown = api.create_aisle_reset({
        "store_id": "00000000-0000-4000-8000-000000000001",
        "price_point_id": "00000000-0000-4000-8000-000000000002",
        "season_window_id": "00000000-0000-4000-8000-000000000003",
        "aisle_code": "A11",
        "starts_at": "2026-09-05T00:00:00Z",
        "ends_at": "2026-09-10T00:00:00Z",
        "allocated_shelf_sqft": 50.0,
        "seasonal_changeover": True,
    }, PLANNER_HEADERS)
    validate_error(all_unknown, E.ERR_STORE_NOT_FOUND.value)

    window_unknown = fixtures.plan_reset(
        store["id"], price_point["id"], "00000000-0000-4000-8000-000000000003",
        aisle_code="A11", starts_at="2026-09-05T00:00:00Z", ends_at="2026-09-10T00:00:00Z")
    validate_error(window_unknown, E.ERR_SEASON_WINDOW_NOT_FOUND.value)

    resets = validate_success(api.list_aisle_resets(PLANNER_HEADERS), 200)
    assert resets == [], "neither rejected request persisted a reset"
    store_after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert store_after["status"] == "SINGLE_PRICE"

def test_season_window_create_rejects_a_missing_bound_and_a_reversed_pair(api):
    """A missing close bound is a shape error; a present but early one is a malformed window.

    PRD §3.10: "A season window is defined with a `season_code` such as `HARVEST_2026`, an
    `opens_on` that is the first instant the window is open and is inclusive, and a `closes_on`
    that is the last instant the window is open and is also inclusive. `closes_on` must be
    strictly after `opens_on`; a window satisfying neither is rejected as malformed with
    `ERR_INVALID_SEASON_WINDOW` and HTTP 400."
    PRD §2.8: "declared request-shape constraints such as a count below its floor, an upper bound
    not strictly after its lower bound, a `to_price_point_id` equal to its `from_price_point_id`, a
    `decision` outside `RETAIN` and `DELETE`, or a `method` outside `FREIGHT_PASS_THROUGH` and
    `VENDOR_PRICE_CHANGE`, all reported as `ERR_INVALID_REQUEST` at HTTP 400"

    Design: Corner/entities/season_window_create_without_closes_on_returns_invalid_request
    """
    fixtures.set_clock()

    missing = api.create_season_window(
        {"season_code": "HARVEST_2026", "opens_on": "2026-09-01T00:00:00Z"}, PLANNER_HEADERS)
    validate_error(missing, E.ERR_INVALID_REQUEST.value)

    reversed_pair = api.create_season_window(
        {"season_code": "HARVEST_2026", "opens_on": "2026-11-30T00:00:00Z",
         "closes_on": "2026-09-01T00:00:00Z"},
        PLANNER_HEADERS)
    validate_error(reversed_pair, E.ERR_INVALID_SEASON_WINDOW.value)

    windows = validate_success(api.list_season_windows(PLANNER_HEADERS), 200)
    assert windows == [], "neither request persisted a window"
