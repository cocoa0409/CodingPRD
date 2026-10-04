"""Pricing and commission calculations: line floors, digital mechanics."""
from test_helpers import (
    ADMIN,
    FINANCE,
    ApiErrorId,
    create_active_store,
    create_book,
    create_delivered_order,
    create_order,
    create_pool,
    create_publisher,
    deliver_order,
    dispatch_order,
    get_success_data,
    list_store_payouts,
    make_customer_headers,
    place_order,
    set_clock,
    setup_catalog_and_store,
    ship_order,
    store_ledger,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_line_pricing_per_line_floor_then_sum_with_promotion(api):
    """PRD §2.6: "Every calculation that divides or applies a percentage rounds
    per line (or per store, in the case of pool shares) using a floor toward
    zero before any summation: round each component down to a whole cent first,
    then sum the rounded components."
    PRD §3.4: "if a promotion matches the book's ISBN, is `ACTIVE`, and the
    placement instant falls inside its closed window, the unit price is the list
    price minus the list price multiplied by the promotion's `discount_pct`
    floored to a whole cent; otherwise the unit price is the list price."
    PRD §3.4: "The order's `gross_cents` is the sum of the per-line totals —
    summed strictly after each line's own rounding, in pinned payload order"

    Design: Difficulty/combinatorial_formula/line_pricing_per_line_floor_then_sum_with_promotion
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Penny Press",
        discount_pct=0.40,
        returns_allowed=False,
        return_window_days=0,
        return_credit_pct=0.0,
    )
    book = create_book(
        pub["id"], isbn="9780000000010", title="Odd Price", list_price_cents=9999
    )
    promo_resp = api.create_promotion(
        {
            "book_isbn": "9780000000010",
            "discount_pct": 0.15,
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-10T00:00:00Z",
        },
        ADMIN,
    )
    promo = validate_success(promo_resp, expected_status=201)
    assert promo["status"] == "ACTIVE", "clock is inside the closed window"

    store = create_active_store(
        shop_name="Round Books",
        slug="round-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    order = create_order(
        "cust-3",
        lines=[
            {"book_id": book["id"], "quantity": 1},
            {"book_id": book["id"], "quantity": 1},
        ],
        attributed_store_id=store["id"],
    )
    placed = place_order(order["id"], "cust-3")
    assert placed["priced_lines"][0]["unit_price_cents"] == 8500
    assert placed["priced_lines"][1]["unit_price_cents"] == 8500
    # Sum AFTER per-line rounding: 2 * 8500 == 17000, not 19998 - 2999 == 16999.
    assert placed["gross_cents"] == 17000
    assert placed["priced_lines"][0]["wholesale_unit_cents"] == 5999
    # per-line net = 8500 - 5999 = 2501; commission = 2 * floor(2501 * 0.30).
    assert placed["commission_cents"] == 1500


def test_line_pricing_wholesale_leg_floors_per_line_for_print(api):
    """PRD §3.4: "The wholesale unit cost depends on format: for `PRINT` it is
    the list price multiplied by one minus the publisher's `discount_pct`
    snapshot at placement, floored; for `EBOOK` and `AUDIOBOOK` it is the list
    price multiplied by a flat digital cost basis of 30%, floored."
    PRD §2.6: "Every calculation that divides or applies a percentage rounds
    per line (or per store, in the case of pool shares) using a floor toward
    zero before any summation: round each component down to a whole cent first,
    then sum the rounded components."
    PRD §3.4: "`wholesale_cost_cents` is the sum of each line's floored
    wholesale unit cost multiplied by its quantity"

    Design: Difficulty/combinatorial_formula/line_pricing_per_line_floor_then_sum_with_promotion
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Penny Press",
        discount_pct=0.40,
        returns_allowed=False,
        return_window_days=0,
        return_credit_pct=0.0,
    )
    book = create_book(
        pub["id"], isbn="9780000000010", title="Odd Price", list_price_cents=9999
    )
    store = create_active_store(
        shop_name="Floor Books",
        slug="floor-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    order = create_order(
        "cust-3",
        lines=[{"book_id": book["id"], "quantity": 3}],
        attributed_store_id=store["id"],
    )
    placed = place_order(order["id"], "cust-3")
    line = placed["priced_lines"][0]
    # Per-line floor: floor(9999 * 0.60) = 5999 (not 5999.4 carried up).
    assert line["wholesale_unit_cents"] == 5999
    assert placed["wholesale_cost_cents"] == 5999 * 3
    assert line["unit_price_cents"] == 9999  # no promotion applies
    assert placed["gross_cents"] == 9999 * 3
    # commission floor((29997 - 17997) * 0.30) = floor(3600.0) = 3600
    assert placed["commission_cents"] == 3600


def test_promotion_closed_interval_plus_buffer_conflict(api):
    """PRD §3.3: "Concretely, a new window conflicts with an existing
    non-`ENDED` promotion on the same ISBN unless the new start falls strictly
    more than one day after the existing window's end, or the new end falls
    strictly more than one day before the existing window's start; violations
    are rejected with `ERR_PROMOTION_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/promotion_closed_interval_plus_buffer_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Promo Press",
        discount_pct=0.40,
        returns_allowed=False,
        return_window_days=0,
        return_credit_pct=0.0,
    )
    create_book(pub["id"], isbn="9780000000070", title="Promo Book", list_price_cents=5000)
    get_success_data(
        api.create_promotion(
            {
                "book_isbn": "9780000000070",
                "discount_pct": 0.10,
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-09-10T00:00:00Z",
            },
            ADMIN,
        )
    )
    # Sep 11 start: only one day after the inclusive Sep 10 end -> conflict.
    resp = api.create_promotion(
        {
            "book_isbn": "9780000000070",
            "discount_pct": 0.10,
            "window_start": "2026-09-11T00:00:00Z",
            "window_end": "2026-09-15T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PROMOTION_WINDOW_CONFLICT, expected_status=409)
    # Sep 12 start: strictly more than one day after Sep 10 -> accepted.
    resp = api.create_promotion(
        {
            "book_isbn": "9780000000070",
            "discount_pct": 0.10,
            "window_start": "2026-09-12T00:00:00Z",
            "window_end": "2026-09-15T00:00:00Z",
        },
        ADMIN,
    )
    validate_success(resp, expected_status=201)


def test_promotion_overlapping_window_rejected_and_after_ended_frees_isbn(api):
    """PRD §3.3: "Concretely, a new window conflicts with an existing
    non-`ENDED` promotion on the same ISBN unless the new start falls strictly
    more than one day after the existing window's end, or the new end falls
    strictly more than one day before the existing window's start; violations
    are rejected with `ERR_PROMOTION_WINDOW_CONFLICT` (HTTP 409). Promotions
    that have already `ENDED` no longer block anything."

    Design: Difficulty/resource_temporal_overlap/promotion_closed_interval_plus_buffer_conflict
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Promo Press",
        discount_pct=0.40,
        returns_allowed=False,
        return_window_days=0,
        return_credit_pct=0.0,
    )
    create_book(pub["id"], isbn="9780000000070", title="Promo Book", list_price_cents=5000)
    get_success_data(
        api.create_promotion(
            {
                "book_isbn": "9780000000070",
                "discount_pct": 0.10,
                "window_start": "2026-09-01T00:00:00Z",
                "window_end": "2026-09-10T00:00:00Z",
            },
            ADMIN,
        )
    )
    # Overlapping the closed interval itself: Sep 10 start -> conflict.
    resp = api.create_promotion(
        {
            "book_isbn": "9780000000070",
            "discount_pct": 0.10,
            "window_start": "2026-09-10T00:00:00Z",
            "window_end": "2026-09-15T00:00:00Z",
        },
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PROMOTION_WINDOW_CONFLICT, expected_status=409)

    # Once the existing promotion has ENDED, the same window no longer blocks.
    set_clock("2026-09-20T00:00:00Z")
    resp = api.create_promotion(
        {
            "book_isbn": "9780000000070",
            "discount_pct": 0.10,
            "window_start": "2026-09-05T00:00:00Z",
            "window_end": "2026-09-09T00:00:00Z",
        },
        ADMIN,
    )
    validate_success(resp, expected_status=201)


def test_digital_commission_uses_rev_share_not_wholesale_discount(api):
    """PRD §3.4: "for `EBOOK` and `AUDIOBOOK` it is the list price multiplied by
    a flat digital cost basis of 30%, floored."
    PRD §3.4: "For digital formats, the platform first keeps its partner share —
    the `line_total_cents` multiplied by the book's
    `ebook_partner_rev_share_pct`, floored — and the line commission is what
    remains after that platform keep, multiplied by the affiliate's
    `commission_pct`, floored."
    PRD §3.4: "its `platform_margin_cents` is, for print lines, each line's
    total minus its wholesale cost minus its commission, and for digital lines,
    each line's total minus the platform keep minus its commission, all summed."

    Design: Corner/calculations/digital_commission_uses_rev_share_not_wholesale_discount
    """
    publisher, book, store = setup_catalog_and_store(
        publisher_overrides={
            "name": "Half Press",
            "discount_pct": 0.50,  # would halve a PRINT price; must NOT apply here
            "returns_allowed": False,
            "return_window_days": 0,
            "return_credit_pct": 0.0,
        },
        book_overrides={
            "isbn": "9780000001020",
            "title": "Gate Ebook",
            "format": "EBOOK",
            "list_price_cents": 20000,
            "ebook_partner_rev_share_pct": 0.25,
        },
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    order = create_order("cust-c1", book["id"], attributed_store_id=store["id"])
    placed = place_order(order["id"], "cust-c1")
    line = placed["priced_lines"][0]
    assert line["wholesale_unit_cents"] == 6000  # floor(20000 * 0.30), not 10000
    # platform keeps floor(20000 * 0.25) = 5000; commission floor(15000 * 0.30).
    assert placed["commission_cents"] == 4500
    assert placed["platform_margin_cents"] == 20000 - 5000 - 4500


def test_promotion_clock_transitions_observed_through_pricing(api):
    """PRD §3.3: "A promotion begins `SCHEDULED`; when the logical clock reaches
    a moment inside its closed window it becomes `ACTIVE` and starts
    participating in line pricing; when the clock passes `window_end` it becomes
    `ENDED`."
    PRD §3.4: "if a promotion matches the book's ISBN, is `ACTIVE`, and the
    placement instant falls inside its closed window, the unit price is the list
    price minus the list price multiplied by the promotion's `discount_pct`
    floored to a whole cent; otherwise the unit price is the list price."

    Design: Corner/state_machines/promotion_clock_transitions_observed_through_pricing
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Corner Press",
        discount_pct=0.45,
        returns_allowed=True,
        return_window_days=60,
        return_credit_pct=1.0,
    )
    book = create_book(
        pub["id"], isbn="9780000001030", title="PB1", list_price_cents=10000
    )
    promo = get_success_data(
        api.create_promotion(
            {
                "book_isbn": "9780000001030",
                "discount_pct": 0.10,
                "window_start": "2026-09-05T00:00:00Z",
                "window_end": "2026-09-10T00:00:00Z",
            },
            ADMIN,
        )
    )
    assert promo["status"] == "SCHEDULED", "clock Sep 1 is before window_start"

    store = create_active_store(
        shop_name="State Books",
        slug="state-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )

    def _place_one():
        order = create_order("cust-c1", book["id"], attributed_store_id=store["id"])
        return place_order(order["id"], "cust-c1")

    order1 = _place_one()  # clock Sep 1: promo SCHEDULED
    assert order1["priced_lines"][0]["unit_price_cents"] == 10000

    set_clock("2026-09-05T00:00:00Z")
    order2 = _place_one()  # clock inside window: promo ACTIVE
    assert order2["priced_lines"][0]["unit_price_cents"] == 9000

    set_clock("2026-09-11T00:00:00Z")
    order3 = _place_one()  # clock past window_end: promo ENDED
    assert order3["priced_lines"][0]["unit_price_cents"] == 10000


def test_clock_default_is_fixed_startup_time(api):
    """PRD §2.4: "At server startup the logical clock is exactly
    `2026-09-01T00:00:00Z`; the server must never fall back to wall-clock time
    at any point."
    PRD §3.3: "A promotion begins `SCHEDULED`; when the logical clock reaches a
    moment inside its closed window it becomes `ACTIVE` and starts participating
    in line pricing; when the clock passes `window_end` it becomes `ENDED`."

    Design: Corner/endpoints/clock_default_is_fixed_startup_time
    """
    # No clock call is ever made: the startup default must already be
    # 2026-09-01T00:00:00Z, inside this promotion's window.
    pub = create_publisher(
        name="Corner Press",
        discount_pct=0.45,
        returns_allowed=True,
        return_window_days=60,
        return_credit_pct=1.0,
    )
    create_book(pub["id"], isbn="9780000001050", title="Clock Book", list_price_cents=5000)
    resp = api.create_promotion(
        {
            "book_isbn": "9780000001050",
            "discount_pct": 0.10,
            "window_start": "2026-09-01T00:00:00Z",
            "window_end": "2026-09-30T00:00:00Z",
        },
        ADMIN,
    )
    promo = validate_success(resp, expected_status=201)
    assert promo["status"] == "ACTIVE"
