"""Entity surface probes: creation, defaults, not-found, computed snapshots."""
from test_helpers import (
    ADMIN,
    FINANCE,
    ApiErrorId,
    create_book,
    create_order,
    create_publisher,
    create_publisher_payload,
    create_store_payload,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    place_order,
    set_clock,
    setup_catalog_and_store,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_publisher_create_returns_declared_fields_and_active_default(api):
    """PRD §3.1: "Each publisher is born `ACTIVE`; a publisher whose terms fall
    into dispute becomes `SUSPENDED`, and books of a suspended publisher cannot
    be placed on new orders."

    Design: Corner/entities/publisher_create_returns_declared_fields_and_active_default
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_publisher(
        {
            "name": "Corner Press",
            "discount_pct": 0.45,
            "returns_allowed": True,
            "return_window_days": 60,
            "return_credit_pct": 1.0,
        },
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["version"] == 1
    assert data["discount_pct"] == 0.45
    assert data["return_window_days"] == 60
    assert data["return_credit_pct"] == 1.0
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])


def test_store_create_applies_defaults_and_pending_onboarding_initial_state(api):
    """PRD §3.2: "an optional `pool_opt_in` flag defaulting to true that governs
    participation in the monthly profit pool, and an optional
    `payout_threshold_cents` defaulting to 2500 and never accepted below that
    floor."
    PRD §3.2: "A new store starts in `PENDING_ONBOARDING` with
    `accrued_balance_cents` at zero, and transitions to `ACTIVE` only when a
    `PlatformAdmin` activates it"

    Design: Corner/entities/store_create_applies_defaults_and_pending_onboarding_initial_state
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_store(
        {"shop_name": "Default Books", "slug": "default-books", "commission_pct": 0.20},
        ADMIN,
    )
    data = validate_success(resp, expected_status=201)
    assert data["pool_opt_in"] is True
    assert data["payout_threshold_cents"] == 2500
    assert data["status"] == "PENDING_ONBOARDING"
    assert data["activated_at"] is None
    assert data["accrued_balance_cents"] == 0
    assert data["version"] == 1


def test_ebook_requires_rev_share_and_print_rejects_it(api):
    """PRD §3.1: "Digital titles additionally carry `ebook_partner_rev_share_pct`
    — the platform's share of net revenue taken before affiliate commission,
    between 0.00 and 0.50 inclusive — and this field is required for `EBOOK`
    and `AUDIOBOOK` formats and must be null or absent for `PRINT`."
    PRD §2.11: "Path resources are resolved next (`ERR_NOT_FOUND`), followed by
    body foreign keys (`ERR_REFERENCE_NOT_FOUND`), then body shape — required
    fields, types, enum membership, uniqueness, list positions, and index
    ranges — as `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/ebook_requires_rev_share_and_print_rejects_it
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(name="Corner Press", discount_pct=0.45)
    bad_payloads = [
        {  # EBOOK missing ebook_partner_rev_share_pct
            "publisher_id": pub["id"],
            "isbn": "9780000001000",
            "title": "NoShare",
            "format": "EBOOK",
            "list_price_cents": 1000,
        },
        {  # PRINT carrying a non-null ebook_partner_rev_share_pct
            "publisher_id": pub["id"],
            "isbn": "9780000001001",
            "title": "WrongShare",
            "format": "PRINT",
            "list_price_cents": 1000,
            "ebook_partner_rev_share_pct": 0.25,
        },
        {  # format outside the declared enum
            "publisher_id": pub["id"],
            "isbn": "9780000001002",
            "title": "BadFormat",
            "format": "HARDCOVER",
            "list_price_cents": 1000,
        },
    ]
    for payload in bad_payloads:
        resp = api.create_book(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, expected_status=400)
    books = get_success_data(api.list_publisher_books(pub["id"], ADMIN))
    assert books == [], "no Book rows should have been created"


def test_unknown_store_id_returns_not_found(api):
    """PRD §2.9: "The first path identifier that does not resolve to an existing
    resource produces an `ERR_NOT_FOUND` (HTTP 404) response, and no later
    segment is examined."

    Design: Corner/entities/unknown_store_id_returns_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.store_action(
        "00000000-0000-0000-0000-000000000000", {"action": "activate"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_body_fk_reference_not_found(api):
    """PRD §2.9: "Foreign keys arriving in a request body — publisher references
    on books, attribution and home-store references on orders, the owner store
    on a list, book identifiers inside list items and order lines — are
    validated separately and surface as `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/body_fk_reference_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_book(
        {
            "publisher_id": "00000000-0000-0000-0000-000000000000",
            "isbn": "9780000001003",
            "title": "Orphan",
            "format": "PRINT",
            "list_price_cents": 1000,
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=404)


def test_ledger_entries_list_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "The `limit` parameter bounds the page size: it defaults to 10
    when omitted, and values below 1 or above 100 are outside the accepted
    range. The `offset` parameter skips a number of leading records and
    defaults to 0."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."
    PRD §3.7: "the ledger itself is browsable by affiliate, by `order_id`, by
    `pool_distribution_id`, and by `kind`."

    Design: Corner/entities/ledger_entries_list_paginates_with_total_count_and_has_more
    """
    # Store activated 2026-08-01; orders placed 2026-09-01 (threshold 20000 >
    # 2 x 13500 accrued, so no payout interferes).
    publisher, book, store = setup_catalog_and_store(
        set_clock_to="2026-08-01T00:00:00Z",
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    set_clock("2026-09-01T00:00:00Z")
    order1 = create_order("cust-c1", book["id"], attributed_store_id=store["id"])
    place_order(order1["id"], "cust-c1")
    order2 = create_order("cust-c1", book["id"], attributed_store_id=store["id"])
    place_order(order2["id"], "cust-c1")
    # One distributed pool adds a POOL_DISTRIBUTION entry for the store.
    dist = get_success_data(
        api.create_pool_distribution(
            {
                "period_start": "2026-08-01T00:00:00Z",
                "period_end": "2026-08-15T00:00:00Z",
                "pool_cents": 5000,
                "share_mode": "EQUAL_SPLIT",
            },
            FINANCE,
        )
    )
    calc = get_success_data(
        api.pool_action(dist["id"], {"action": "calculate"}, FINANCE)
    )
    get_success_data(
        api.pool_action(
            dist["id"],
            {"action": "approve", "expected_distribution_version": calc["version"]},
            FINANCE,
        )
    )
    get_success_data(
        api.pool_action(dist["id"], {"action": "distribute"}, FINANCE)
    )

    resp = api.list_ledger_entries(
        FINANCE, {"affiliate_store_id": store["id"], "limit": 2, "offset": 0}
    )
    page1, meta1 = validate_paginated(resp)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    resp = api.list_ledger_entries(
        FINANCE, {"affiliate_store_id": store["id"], "limit": 2, "offset": 2}
    )
    page2, meta2 = validate_paginated(resp)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    resp = api.list_ledger_entries(
        FINANCE,
        {"affiliate_store_id": store["id"], "kind": "POOL_DISTRIBUTION"},
    )
    pool_entries, meta3 = validate_paginated(resp)
    assert len(pool_entries) == 1
    assert pool_entries[0]["amount_cents"] == 5000

    resp = api.list_ledger_entries(FINANCE, {"affiliate_store_id": store["id"]})
    all_entries, meta4 = validate_paginated(resp)
    assert len(all_entries) == 3
    assert meta4["limit"] == 10
    assert meta4["offset"] == 0


def test_priced_lines_computed_snapshot_ignores_client_supplied_prices(api):
    """PRD §3.4: "Pricing happens at this moment and is then pinned. Each line,
    processed in payload order, is priced from the book's `list_price_cents`"
    PRD §3.4: "for `PRINT` it is the list price multiplied by one minus the
    publisher's `discount_pct` snapshot at placement, floored"
    PRD §3.4: "All of these per-line snapshots — `unit_price_cents`,
    `line_total_cents`, `wholesale_unit_cents`, and a `returned_quantity`
    starting at zero — are written into the order's computed `priced_lines`
    array, indexed from 0 in payload order."

    Design: Corner/entities/priced_lines_computed_snapshot_ignores_client_supplied_prices
    """
    publisher, book, store = setup_catalog_and_store(
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
        publisher_overrides={
            "name": "Corner Press",
            "discount_pct": 0.45,
            "returns_allowed": True,
            "return_window_days": 60,
            "return_credit_pct": 1.0,
        },
    )
    order = create_order("cust-c1", book["id"], attributed_store_id=store["id"])
    placed = place_order(order["id"], "cust-c1")
    line = placed["priced_lines"][0]
    assert line["unit_price_cents"] == 100000
    assert line["line_total_cents"] == 100000
    assert line["wholesale_unit_cents"] == 55000  # floor(100000 * 0.55)
    assert line["returned_quantity"] == 0
