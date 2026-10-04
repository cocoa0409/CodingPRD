"""Pagination with filtering, derived-field reconciliation and same-response consistency."""


from test_helpers import (
    ANALYST_HEADERS,
    E,
    SOM_HEADERS,
    api_client,
    assert_price_integrity_audit,
    factories,
    validate_paginated,
    validate_success,
    fixtures,
)

PAGINATION_QUOTE = (
    "`total_count` is the count of rows matching the filters irrespective of the current page, "
    "and `has_more` indicates whether further rows remain beyond the returned page."
)
FILTER_QUOTE = (
    "Audits may be listed filtered by `store_id`, `price_point_id`, `result` and `status`."
)
VIOLATION_QUOTE = (
    "the result is `VIOLATION` when that rounded ratio is strictly greater than the tolerance of "
    "0.052, and `WITHIN_TOLERANCE` otherwise"
)
COUNT_QUOTE = (
    "A newly filed audit begins `OPEN`, its store's `price_integrity_audit_count` is incremented, "
    "and the store's `open_violation_count` is recomputed."
)
CLOSE_QUOTE = (
    "In both cases the audit moves to `RESOLVED` and the store's `open_violation_count` is "
    "recomputed, so the count always reflects exactly the violations still open."
)
IMMEDIATE_QUOTE = (
    "Every derived cost field is immediate: a single landed-cost write returns the new "
    "`landed_cost_cents`, the new `break_even_units` and the new `net_contribution_cents_per_unit` "
    "in that same response, with no re-read and no eventual convergence window."
)
REVISION_QUOTE = (
    "Each landed-cost application re-derives two numbers that decide whether the item can live at "
    "its fixed retail."
)
BREAK_EVEN_READ_QUOTE = (
    "A break-even read reports the item's `item_id`, its `break_even_units`, its "
    "`unit_retail_cents`, its `landed_cost_cents`, its `variable_store_cost_cents`, its "
    "`net_contribution_cents_per_unit`, and a `regime` string that reads `PRICE_PENDING`, "
    "`CONVERGENCE` or `DIVERGENCE_OR_ZERO_MARGIN` under exactly the conditions above."
)


def test_the_two_states_of_the_projects_listing_can_be_filtered_and_paged(api):
    """Two projects on file page with the declared meta and narrow under a status filter.

    PRD §2.3: "`total_count` is the count of rows matching the filters irrespective of the current
    page, and `has_more` indicates whether further rows remain beyond the returned page."
    PRD §3.8: "A project is started into execution only from `DRAFT` — a start from any other state
    is rejected with `ERR_CONVERSION_NOT_DRAFT`"

    Design: Corner/cross_cutting_complexity_layers/conversion_projects_list_filters_by_status_and_paginates
    """
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    first_store = fixtures.create_store(store_number="1927", shelf_facing_capacity_sqft=400.0)
    second_store = fixtures.create_store(store_number="2031", shelf_facing_capacity_sqft=300.0)

    first_begin = validate_success(
        api.begin_conversion(first_store["id"], target["id"], SOM_HEADERS), 200)
    draft_project = validate_success(fixtures.open_conversion_project(
        first_store["id"], origin["id"], target["id"],
        expected_store_version=first_begin["version"]), 201)
    assert draft_project["status"] == "DRAFT"

    second_begin = validate_success(
        api.begin_conversion(second_store["id"], target["id"], SOM_HEADERS), 200)
    started_project = validate_success(fixtures.open_conversion_project(
        second_store["id"], origin["id"], target["id"],
        expected_store_version=second_begin["version"]), 201)
    started = validate_success(
        api_client.start_conversion_project(started_project["id"], SOM_HEADERS), 200)
    assert started["status"] == "IN_PROGRESS"

    page, meta = validate_paginated(
        api.list_conversion_projects(ANALYST_HEADERS, params={"limit": 1, "offset": 0}))
    assert len(page) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    drafts = validate_success(
        api.list_conversion_projects(ANALYST_HEADERS, params={"status": "DRAFT"}), 200)
    assert len(drafts) == 1
    assert drafts[0]["id"] == draft_project["id"]

    running = validate_success(
        api.list_conversion_projects(ANALYST_HEADERS, params={"status": "IN_PROGRESS"}), 200)
    assert len(running) == 1
    assert running[0]["id"] == started_project["id"]

    by_store = validate_success(
        api.list_conversion_projects(ANALYST_HEADERS, params={"store_id": first_store["id"]}), 200)
    assert len(by_store) == 1

    everything, meta = validate_paginated(api.list_conversion_projects(ANALYST_HEADERS))
    assert len(everything) == 2
    assert meta["limit"] == 10, "the limit parameter falls back to its declared default"


def test_the_store_open_violation_count_reconciles_as_audits_are_resolved(api):
    """The denormalized count tracks only open violations and survives visit removal.

    PRD §3.11: "A newly filed audit begins `OPEN`, its store's `price_integrity_audit_count` is
    incremented, and the store's `open_violation_count` is recomputed."
    PRD §3.11: "In both cases the audit moves to `RESOLVED` and the store's `open_violation_count`
    is recomputed, so the count always reflects exactly the violations still open."
    PRD §3.11: "the result is `VIOLATION` when that rounded ratio is strictly greater than the
    tolerance of 0.052, and `WITHIN_TOLERANCE` otherwise"

    Design: Corner/cross_cutting_complexity_layers/store_open_violation_count_reconciles_with_manual_resolution
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()

    first = validate_success(api.create_audit(
        factories.create_audit_payload(
            store["id"], price_point["id"], observed_item_count=80, mismatched_item_count=5,
            audited_at="2026-09-03T00:00:00Z"),
        SOM_HEADERS), 201)
    second = validate_success(api.create_audit(
        factories.create_audit_payload(
            store["id"], price_point["id"], observed_item_count=100, mismatched_item_count=6,
            audited_at="2026-09-04T00:00:00Z"),
        SOM_HEADERS), 201)
    clean = validate_success(api.create_audit(
        factories.create_audit_payload(
            store["id"], price_point["id"], observed_item_count=100, mismatched_item_count=3,
            audited_at="2026-09-05T00:00:00Z"),
        SOM_HEADERS), 201)
    assert_price_integrity_audit(clean)

    before = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert before["open_violation_count"] == 2, "the clean visit never counts as a violation"
    assert before["price_integrity_audit_count"] == 3
    assert clean["result"] == "WITHIN_TOLERANCE"
    assert clean["mismatch_ratio"] == 0.030

    validate_success(api.resolve_audit(first["id"], SOM_HEADERS), 200)
    middle = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert middle["open_violation_count"] == 1

    validate_success(api.resolve_audit(second["id"], SOM_HEADERS), 200)
    after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert after["open_violation_count"] == 0
    assert after["price_integrity_audit_count"] == 3, (
        "closing a violation does not remove the visit that recorded it"
    )


def test_a_cost_write_reports_its_recomputed_fields_in_the_same_response(api):
    """The item's derived cost fields are visible immediately, with no re-read needed.

    PRD §3.3: "Every landed-cost application re-derives two numbers that decide whether the item
    can live at its fixed retail."
    PRD §2.5: "Because a derived field is still a mutation, a recomputation of a computed field
    updates `updated_at` and increments `version` exactly as a client-supplied edit would."
    PRD §3.3: "A break-even read reports the item's `item_id`, its `break_even_units`, its
    `unit_retail_cents`, its `landed_cost_cents`, its `variable_store_cost_cents`, its
    `net_contribution_cents_per_unit`, and a `regime` string that reads `PRICE_PENDING`,
    `CONVERGENCE` or `DIVERGENCE_OR_ZERO_MARGIN` under exactly the conditions above."

    Design: Corner/consistency_model/item_cost_fields_are_visible_in_the_same_response_that_writes_them
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="1001", base_landed_cost_cents=105)

    write = validate_success(
        fixtures.apply_landed_cost(item["id"], applied_amount_cents=100), 201)
    assert write["applied_amount_cents"] == 100
    assert write["effective_sequence"] == 1

    # ceil((100 * 4 + 6) / (125 - 4)) == ceil(406 / 121) == 4.
    projection = validate_success(api.get_break_even(item["id"], ANALYST_HEADERS), 200)
    assert projection["landed_cost_cents"] == 100
    assert projection["break_even_units"] == 4
    assert projection["net_contribution_cents_per_unit"] == 21
    assert projection["regime"] == "CONVERGENCE"

    read = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert read["status"] == "COST_PENDING", (
        "no eventual window separates the cost write from the lifecycle move"
    )
    assert read["landed_cost_cents"] == 100
    assert read["break_even_units"] == 4
    assert read["net_contribution_cents_per_unit"] == 21