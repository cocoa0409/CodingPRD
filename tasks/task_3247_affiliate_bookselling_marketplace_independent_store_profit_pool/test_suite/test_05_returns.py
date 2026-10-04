"""Return lifecycle: cascades, windows, quantities, and terminal states."""
from test_helpers import (
    ADMIN,
    FINANCE,
    SERVICE,
    WHOLESALER,
    ApiErrorId,
    create_delivered_order,
    create_placed_order,
    create_return_payload,
    get_success_data,
    make_customer_headers,
    open_return,
    set_clock,
    setup_catalog_and_store,
    setup_delivered_order_scenario,
    settle_return,
    store_ledger,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_return_credit_cascades_line_order_ledger_balance(api):
    """PRD §3.5: "Crediting increments the priced line's `returned_quantity` by
    the returned quantity, adds `refund_cents` to the order's `refunded_cents`,
    and recomputes `retained_cents`; the order's `payment_status` becomes
    `REFUNDED_PARTIAL`, or `REFUNDED_FULL` when the cumulative refund equals the
    full `gross_cents`."
    PRD §3.5: "for a `PRINT` line whose publisher allows returns, it is the
    line's `wholesale_unit_cents` times the returned quantity times the
    publisher's `return_credit_pct`, floored"
    PRD §3.5: "a `RETURN_CLAWBACK` ledger entry is written for the negative of
    the line's final per-line commission multiplied by the fraction of the line
    being returned — returned quantity over line quantity — floored, and the
    affiliate's `accrued_balance_cents` is reconciled."

    Design: Difficulty/transitive_cascade/return_credit_cascades_line_order_ledger_balance
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store, order = setup_delivered_order_scenario(
        customer_id="cust-6",
        quantity=2,
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 30000},
    )
    ret = open_return(
        order["id"], "cust-6", line_index=0, quantity=1, reason_code="DAMAGED"
    )
    get_success_data(api.return_action(ret["id"], {"action": "approve"}, SERVICE))
    get_success_data(api.return_action(ret["id"], {"action": "receive"}, WHOLESALER))
    credited = get_success_data(
        api.return_action(ret["id"], {"action": "credit"}, FINANCE)
    )
    assert credited["wholesale_credit_cents"] == 43200  # floor(54000 * 1 * 0.80)

    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["priced_lines"][0]["returned_quantity"] == 1
    assert order_now["refunded_cents"] == 100000
    assert order_now["retained_cents"] == 100000
    assert order_now["payment_status"] == "REFUNDED_PARTIAL"

    clawbacks = store_ledger(store["id"], kind="RETURN_CLAWBACK")
    assert len(clawbacks) == 1
    assert clawbacks[0]["amount_cents"] == -13800  # floor(27600 * 1/2)

    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    assert store_now["accrued_balance_cents"] == 13800  # 27600 - 13800
    payouts, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_store_id": store["id"]})
    )
    assert payouts == [], "13800 < 30000 threshold: no payout opened"


def test_full_return_credit_flips_payment_to_refunded_full(api):
    """PRD §3.5: "Crediting increments the priced line's `returned_quantity` by
    the returned quantity, adds `refund_cents` to the order's `refunded_cents`,
    and recomputes `retained_cents`; the order's `payment_status` becomes
    `REFUNDED_PARTIAL`, or `REFUNDED_FULL` when the cumulative refund equals the
    full `gross_cents`."
    PRD §3.5: "approval also fixes the customer refund, setting `refund_cents`
    to the line's `unit_price_cents` multiplied by the return `quantity`."

    Design: Difficulty/transitive_cascade/return_credit_cascades_line_order_ledger_balance
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store, order = setup_delivered_order_scenario(
        customer_id="cust-6",
        quantity=1,
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 30000},
    )
    ret = open_return(
        order["id"], "cust-6", line_index=0, quantity=1, reason_code="DAMAGED"
    )
    approved = get_success_data(
        api.return_action(ret["id"], {"action": "approve"}, SERVICE)
    )
    assert approved["refund_cents"] == 100000  # unit_price_cents * quantity
    get_success_data(api.return_action(ret["id"], {"action": "receive"}, WHOLESALER))
    get_success_data(api.return_action(ret["id"], {"action": "credit"}, FINANCE))

    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["refunded_cents"] == 100000
    assert order_now["retained_cents"] == 0
    assert order_now["payment_status"] == "REFUNDED_FULL"
    assert order_now["priced_lines"][0]["returned_quantity"] == 1


def test_return_creation_blocked_until_order_delivered(api):
    """PRD §3.5: "Opening a return against an order that has not reached
    `DELIVERED` fails with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.5: "Returns are opened against a delivered order's priced lines."

    Design: Difficulty/cross_entity_state_dependency/return_creation_blocked_until_order_delivered
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store = setup_catalog_and_store(
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000}
    )
    order = create_placed_order("cust-11", book["id"], attributed_store_id=store["id"])
    dispatch = get_success_data(
        api.order_action(order["id"], {"action": "dispatch"}, WHOLESALER)
    )
    get_success_data(api.order_action(order["id"], {"action": "ship"}, WHOLESALER))

    cust = make_customer_headers("cust-11")
    resp = api.create_return(
        order["id"],
        {"line_index": 0, "quantity": 1, "reason_code": "DAMAGED"},
        cust,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    get_success_data(api.order_action(order["id"], {"action": "deliver"}, WHOLESALER))
    resp = api.create_return(
        order["id"],
        {"line_index": 0, "quantity": 1, "reason_code": "DAMAGED"},
        cust,
    )
    ret = validate_success(resp, expected_status=201)
    assert ret["status"] == "REQUESTED"


def test_business_temporal_vs_business_referential_on_return_creation(api):
    """PRD §3.5: "for `PRINT` lines, the publisher's `returns_allowed` must hold
    and the logical clock must be no later than `delivered_at` plus the
    publisher's `return_window_days`; for `EBOOK` and `AUDIOBOOK` lines, the
    `UNWANTED` reason is rejected outright — digital goods are never returnable
    simply because the customer changed their mind. Either violation surfaces as
    `ERR_RETURN_WINDOW_CLOSED` (HTTP 422)."
    PRD §2.11: "then temporal windows (`ERR_RETURN_WINDOW_CLOSED`,
    `ERR_WINDOW_NOT_SATISFIED`), then fiscal rules
    (`ERR_COMMERCIAL_TERMS_INVALID`, `ERR_POOL_SUM_MISMATCH`), and finally
    referential guards (`ERR_STORE_SETTLEMENT_OUTSTANDING`,
    `ERR_LIST_NOT_PUBLISHABLE`, `ERR_RETURN_QUANTITY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_return_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store, order = setup_delivered_order_scenario(
        customer_id="cust-8",
        publisher_overrides={
            "name": "Narrow Window Press",
            "return_window_days": 10,
        },
        book_overrides={
            "isbn": "9780000000041",
            "title": "Late Return",
            "list_price_cents": 20000,
        },
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    set_clock("2026-09-12T00:00:01Z")  # 11 days after delivery: window closed
    cust = make_customer_headers("cust-8")
    # Quantity 5 exceeds the line's unreturned balance AND the window is closed;
    # the temporal check must fire first.
    resp = api.create_return(
        order["id"],
        {"line_index": 0, "quantity": 5, "reason_code": "UNWANTED"},
        cust,
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED, expected_status=422)

    resp = api.list_order_returns(order["id"], FINANCE)
    returns, _ = validate_paginated(resp)
    assert returns == [], "no ReturnRequest row should have been created"


def test_return_quantity_exceeds_unreturned_balance(api):
    """PRD §3.5: "The quantity must be at least one and must not exceed the
    line's quantity minus the units already returned on that line; excess is
    rejected with `ERR_RETURN_QUANTITY_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/return_quantity_exceeds_unreturned_balance
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store, order = setup_delivered_order_scenario(
        customer_id="cust-c5",
        quantity=2,
        publisher_overrides={"return_window_days": 60},
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    ret1 = open_return(
        order["id"], "cust-c5", line_index=0, quantity=1, reason_code="DAMAGED"
    )
    settle_return(ret1["id"])

    cust = make_customer_headers("cust-c5")
    resp = api.create_return(
        order["id"], {"line_index": 0, "quantity": 2, "reason_code": "DAMAGED"}, cust
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDED, expected_status=422)

    resp = api.create_return(
        order["id"], {"line_index": 0, "quantity": 1, "reason_code": "DAMAGED"}, cust
    )
    ret2 = validate_success(resp, expected_status=201)
    assert ret2["status"] == "REQUESTED"


def test_digital_unwanted_return_rejected_outright(api):
    """PRD §3.5: "for `EBOOK` and `AUDIOBOOK` lines, the `UNWANTED` reason is
    rejected outright — digital goods are never returnable simply because the
    customer changed their mind. Either violation surfaces as
    `ERR_RETURN_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/digital_unwanted_return_rejected_outright
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store, order = setup_delivered_order_scenario(
        customer_id="cust-c6",
        quantity=2,
        publisher_overrides={
            "discount_pct": 0.45,
            "returns_allowed": True,
            "return_window_days": 60,
            "return_credit_pct": 1.0,
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
    set_clock("2026-09-01T00:01:00Z")  # one minute after delivery
    cust = make_customer_headers("cust-c6")
    resp = api.create_return(
        order["id"], {"line_index": 0, "quantity": 1, "reason_code": "UNWANTED"}, cust
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED, expected_status=422)

    resp = api.create_return(
        order["id"], {"line_index": 0, "quantity": 1, "reason_code": "DAMAGED"}, cust
    )
    ret = validate_success(resp, expected_status=201)
    assert ret["status"] == "REQUESTED"


def test_return_reject_terminal_then_receive_or_credit_fails(api):
    """PRD §3.5: "A return's lifecycle runs `REQUESTED` → `APPROVED` →
    `RECEIVED` → `CREDITED`, with `REJECTED` as the terminal alternative out of
    `REQUESTED`."
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/return_reject_terminal_then_receive_or_credit_fails
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store, order = setup_delivered_order_scenario(
        customer_id="cust-c1",
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    ret = open_return(
        order["id"], "cust-c1", line_index=0, quantity=1, reason_code="UNWANTED"
    )
    get_success_data(api.return_action(ret["id"], {"action": "reject"}, SERVICE))

    resp = api.return_action(ret["id"], {"action": "receive"}, WHOLESALER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    resp = api.return_action(ret["id"], {"action": "credit"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["refunded_cents"] == 0
    assert order_now["retained_cents"] == 100000


def test_return_creation_blocked_on_draft_order(api):
    """PRD §3.5: "Opening a return against an order that has not reached
    `DELIVERED` fails with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.5: "Returns are opened against a delivered order's priced lines. A
    return request names the order (from the path), a `line_index` — the 0-based
    position into the order's `priced_lines` — a `quantity`, and a `reason_code`
    of `DAMAGED`, `WRONG_ITEM`, or `UNWANTED`."

    Design: Difficulty/cross_entity_state_dependency/return_creation_blocked_until_order_delivered
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store = setup_catalog_and_store(
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000}
    )
    order = create_placed_order("cust-11", book["id"], attributed_store_id=store["id"])
    cust = make_customer_headers("cust-11")
    # PLACED but never dispatched: still not DELIVERED.
    resp = api.create_return(
        order["id"], {"line_index": 0, "quantity": 1, "reason_code": "DAMAGED"}, cust
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    resp = api.list_order_returns(order["id"], FINANCE)
    returns, _ = validate_paginated(resp)
    assert returns == []


def test_print_return_rejected_after_publisher_window_alone(api):
    """PRD §3.5: "for `PRINT` lines, the publisher's `returns_allowed` must hold
    and the logical clock must be no later than `delivered_at` plus the
    publisher's `return_window_days`; for `EBOOK` and `AUDIOBOOK` lines, the
    `UNWANTED` reason is rejected outright — digital goods are never returnable
    simply because the customer changed their mind. Either violation surfaces as
    `ERR_RETURN_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_return_creation
    """
    set_clock("2026-09-01T00:00:00Z")
    publisher, book, store, order = setup_delivered_order_scenario(
        customer_id="cust-8",
        publisher_overrides={"name": "Narrow Window Press", "return_window_days": 10},
        book_overrides={
            "isbn": "9780000000041",
            "title": "Late Return",
            "list_price_cents": 20000,
        },
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000},
    )
    set_clock("2026-09-12T00:00:01Z")  # window closed; quantity itself is legal
    cust = make_customer_headers("cust-8")
    resp = api.create_return(
        order["id"], {"line_index": 0, "quantity": 1, "reason_code": "UNWANTED"}, cust
    )
    validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_CLOSED, expected_status=422)

    resp = api.list_order_returns(order["id"], FINANCE)
    returns, _ = validate_paginated(resp)
    assert returns == []
