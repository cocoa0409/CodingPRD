"""Per-entity creation defaults, retrieval round-trips and list paging."""

from test_helpers import (
    api_client,
    create_account,
    create_part,
    get_success_data,
    reload_account,
    set_clock,
    stock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_fresh_account_starts_bronze_open_with_zero_counters(api,
                                                               sales_rep_headers,
                                                               parts_manager_headers):
    """PRD §3.1: "Creation establishes the account's derived furniture in one shot:
    `tier` starts at `BRONZE`, `petty_cash_cents` starts at 0, `order_sequence`
    starts at 0, and `is_archived` starts false."
    PRD §3.1: "a fresh account with no orders, no loans and a zero receivable
    derives to `OPEN`."

    Design: Corner/entities/account_create_starts_bronze_open_with_zero_counters
    """
    set_clock("2026-09-01T00:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Corner Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))

    response = api_client.create_account(
        {"shop_name": "Corner Garage", "tax_id": "TX-C001",
         "billing_address": "1 Corner St", "home_store_id": store["id"],
         "credit_limit_cents": 250000, "credit_terms_days": 30,
         "delivery_service_level": "SHOP_DELIVERY"}, sales_rep_headers)
    account = validate_success(response, 201)

    assert account["tier"] == "BRONZE"
    assert account["account_posture"] == "OPEN"
    assert account["petty_cash_cents"] == 0
    assert account["order_sequence"] == 0
    assert account["credit_exposure_cents"] == 0
    assert account["receivable_balance_cents"] == 0
    assert account["deposit_liability_cents"] == 0
    assert account["is_archived"] is False
    assert account["shipping_address"] is None, (
        "an omitted shipping_address is stored as null"
    )


def test_a_store_round_trips_its_posted_configuration(api, parts_manager_headers):
    """PRD §3.1: "Its delivery characteristics are `delivery_radius_miles`,
    `cutoff_hour_local` (defaulting to 15), `cutoff_buffer_minutes` (defaulting
    to 30), `promise_time_minutes`, and `daily_capacity_units`."
    PRD §3.1: "Its place in the replenishment chain is `hub_store_id`, the hub or
    mega-hub it is replenished from, which is null for a hub, a mega-hub or a
    DC."

    Design: Corner/entities/store_get_round_trips_the_posted_configuration
    """
    set_clock("2026-09-01T00:00:00.000Z")
    mega = get_success_data(api_client.create_store(
        {"store_code": "S900", "name": "Corner Mega", "store_type": "MEGA_HUB",
         "delivery_radius_miles": 60.0, "cutoff_hour_local": 17,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 120,
         "daily_capacity_units": 900, "hub_store_id": None}, parts_manager_headers))

    fetched = get_success_data(api_client.get_store(mega["id"], parts_manager_headers))

    assert fetched["store_type"] == "MEGA_HUB"
    assert fetched["store_code"] == "S900"
    assert fetched["daily_capacity_units"] == 900
    assert fetched["cutoff_buffer_minutes"] == 30
    assert fetched["hub_store_id"] is None
    assert fetched["committed_units_today"] == 0, (
        "on creation committed_units_today is 0"
    )
    assert fetched["is_archived"] is False


def test_the_parts_list_pages_with_total_count_and_has_more(api,
                                                            parts_manager_headers):
    """PRD §2.3: "`limit` caps how many items a single page returns; when omitted
    it defaults to 10, and any value supplied must be at least 1 and at most 100.
    `offset` states how many leading items to skip and defaults to 0."
    PRD §2.3: "Paged and non-paged list responses both carry `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/parts_list_paginates_with_total_count_and_has_more
    """
    set_clock("2026-09-01T00:00:00.000Z")
    for sku, line_code, price in (("P-1", "IGN", 1000), ("P-2", "IGN", 2000),
                                  ("P-3", "BRK", 3000)):
        get_success_data(api_client.create_part(
            {"sku": sku, "description": f"Part {sku}", "line_code": line_code,
             "list_price_cents": price, "core_charge_cents": 0},
            parts_manager_headers))

    page_one, meta_one = validate_paginated(
        api_client.list_parts(parts_manager_headers, params={"limit": 2, "offset": 0}))
    assert len(page_one) == 2
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True

    page_two, meta_two = validate_paginated(
        api_client.list_parts(parts_manager_headers, params={"limit": 2, "offset": 2}))
    assert len(page_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    filtered, meta_filtered = validate_paginated(
        api_client.list_parts(parts_manager_headers, params={"line_code": "IGN"}))
    assert len(filtered) == 2
    assert meta_filtered["total_count"] == 2

    unpaged, meta_unpaged = validate_paginated(
        api_client.list_parts(parts_manager_headers))
    assert len(unpaged) == 3
    assert meta_unpaged["limit"] == 10
    assert meta_unpaged["offset"] == 0


def test_an_unknown_account_id_returns_the_account_specific_not_found(
        api, sales_rep_headers):
    """PRD §2.10: "That failure is a 404 carrying the not-found identifier for the
    kind of resource the failing segment names:
    `ERR_COMMERCIAL_ACCOUNT_NOT_FOUND`"

    Design: Corner/entities/account_get_with_an_unknown_id_returns_account_not_found
    """
    set_clock("2026-09-01T00:00:00.000Z")
    response = api_client.get_account("11111111-2222-3333-4444-555555555555",
                                      sales_rep_headers)
    validate_error(response, "ERR_COMMERCIAL_ACCOUNT_NOT_FOUND", expected_status=404)


def test_a_posted_order_defaults_to_draft_with_server_derived_fields(
        api, sales_rep_headers, parts_manager_headers):
    """PRD §3.3: "At creation the order receives its identity and its provisional
    economics. The account's `order_sequence` counter is read and incremented, and
    the order's `member_sequence` is set to the value the counter held before the
    increment — so the account's very first order carries `member_sequence` 1"

    Design: Corner/entities/order_create_defaults_status_and_ignores_system_fields
    """
    set_clock("2026-09-01T00:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Def Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    part = get_success_data(api_client.create_part(
        {"sku": "P-A", "description": "Part A", "line_code": "IGN",
         "list_price_cents": 1673, "core_charge_cents": 0}, parts_manager_headers))
    stock(store["id"], part["id"], 5)
    account = create_account(store["id"], tax_id="TX-C002", shop_name="Def Garage")
    version = reload_account(account["id"])["version"]

    order = get_success_data(api_client.create_order(
        {"account_id": account["id"],
         "line_items": [{"part_id": part["id"], "quantity": 1}],
         "expected_account_version": version}, sales_rep_headers))

    assert order["status"] == "DRAFT", "no status was supplied"
    assert order["member_sequence"] == 1
    assert order["pricing_band"] == "BRONZE"
    assert order["reserved_unit_count"] == 0, (
        "reservation only happens at confirmation, so a fresh order holds no units"
    )
    assert reload_account(account["id"])["credit_exposure_cents"] == order["parts_subtotal_cents"]


def test_amending_the_terms_re_derives_the_posture_from_the_new_window(
        api, credit_analyst_headers, parts_manager_headers, sales_rep_headers,
        driver_headers):
    """PRD §3.1: "After the amendment the account's `account_posture` is
    re-derived."
    PRD §2.6: "`account_posture` — that is computed by the server and can never be
    set directly by a client."

    Design: Corner/entities/account_put_recomputes_posture_from_the_new_terms
    """
    from test_helpers import advance_order_to_delivered

    set_clock("2026-09-01T08:00:00.000Z")
    store = get_success_data(api_client.create_store(
        {"store_code": "S100", "name": "Post Satellite", "store_type": "SATELLITE",
         "delivery_radius_miles": 5.0, "cutoff_hour_local": 15,
         "cutoff_buffer_minutes": 30, "promise_time_minutes": 240,
         "daily_capacity_units": 500}, parts_manager_headers))
    part = create_part(sku="P-B", list_price_cents=4000)
    stock(store["id"], part["id"], 5)
    account = create_account(store["id"], tax_id="TX-C003", shop_name="Post Garage",
                            credit_terms_days=90)
    delivered = advance_order_to_delivered(
        account["id"], [{"part_id": part["id"], "quantity": 1}],
        driver_id="drv-post", route_code="R-POST")

    # PRD 2.6: the account suspends once the clock is strictly past the oldest
    # due instant plus the terms plus the 30-day grace.  The order was delivered
    # under 90-day terms, so 120 days past its own due instant is inside the
    # span; a full year past is past it.
    set_clock("2027-12-15T08:00:00.000Z")
    amended = get_success_data(api_client.update_account(
        account["id"],
        {"credit_terms_days": 30,
         "account_posture": "OPEN",
         "expected_account_version": reload_account(account["id"])["version"]},
        credit_analyst_headers))

    assert amended["account_posture"] == "CREDIT_SUSPENDED", (
        "the posture was re-derived from the aging test, not taken from the body"
    )
    assert amended["receivable_balance_cents"] == 4000
    assert amended["credit_exposure_cents"] == 0, (
        "the suspension came from the aging test, not the exposure test"
    )

    posture = get_success_data(api_client.get_account_posture(account["id"],
                                                              credit_analyst_headers))
    assert posture["oldest_due_at"] == delivered["order"]["delivered_payment_due_at"], (
        "the due instant driving the aging test is the delivered order's own due instant"
    )