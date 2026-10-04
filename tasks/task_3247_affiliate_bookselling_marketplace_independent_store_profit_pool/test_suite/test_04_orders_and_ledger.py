"""Order lifecycle, ledger entries, and attribution gates."""
from test_helpers import (
    ADMIN,
    FINANCE,
    SERVICE,
    WHOLESALER,
    ApiErrorId,
    create_active_partner,
    create_active_store,
    create_book,
    create_delivered_order,
    create_order,
    create_partner,
    create_publisher,
    deliver_order,
    dispatch_order,
    get_success_data,
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


def _riverbend_book(isbn, title, list_price_cents=100000, **overrides):
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    return create_book(
        pub["id"], isbn=isbn, title=title, list_price_cents=list_price_cents, **overrides
    )


def test_order_commission_provisional_vs_final_diverge_after_return(api):
    """PRD §3.4: "Delivery also finalizes the commission: the provisional
    `ORDER_ACCRUAL` entry is marked `reversed` true, a fresh final
    `ORDER_ACCRUAL` entry recomputed by the same per-line formula supersedes it,
    the affiliate's balance is reconciled again, and the payout sweep runs once
    more."
    PRD §3.5: "The affiliate's commission is clawed back proportionally: a
    `RETURN_CLAWBACK` ledger entry is written for the negative of the line's
    final per-line commission multiplied by the fraction of the line being
    returned — returned quantity over line quantity — floored, and the
    affiliate's `accrued_balance_cents` is reconciled."
    PRD §3.5: "for a `PRINT` line whose publisher allows returns, it is the
    line's `wholesale_unit_cents` times the returned quantity times the
    publisher's `return_credit_pct`, floored"

    Design: Difficulty/dual_variant_calc/order_commission_provisional_vs_final_diverge_after_return
    """
    set_clock("2026-09-01T00:00:00Z")
    book = _riverbend_book("9780000000001", "Hardcover One")
    store = create_active_store(
        shop_name="Maple Books",
        slug="maple-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    order = create_delivered_order("cust-1", book["id"], attributed_store_id=store["id"])

    cust = make_customer_headers("cust-1")
    ret = get_success_data(
        api.create_return(
            order["id"],
            {"line_index": 0, "quantity": 1, "reason_code": "UNWANTED"},
            cust,
        )
    )
    get_success_data(
        api.return_action(ret["id"], {"action": "approve"}, SERVICE)
    )
    get_success_data(
        api.return_action(ret["id"], {"action": "receive"}, WHOLESALER)
    )
    credited = get_success_data(
        api.return_action(ret["id"], {"action": "credit"}, FINANCE)
    )
    assert credited["wholesale_credit_cents"] == 43200  # floor(54000 * 1 * 0.80)

    entries = store_ledger(store["id"])
    accruals = [e for e in entries if e["kind"] == "ORDER_ACCRUAL"]
    assert len(accruals) == 2
    reversed_accruals = [e for e in accruals if e["reversed"] is True]
    final_accruals = [e for e in accruals if e["reversed"] is False]
    assert len(reversed_accruals) == 1 and reversed_accruals[0]["amount_cents"] == 13800
    assert len(final_accruals) == 1 and final_accruals[0]["amount_cents"] == 13800

    clawbacks = [e for e in entries if e["kind"] == "RETURN_CLAWBACK"]
    assert len(clawbacks) == 1
    assert clawbacks[0]["amount_cents"] == -13800
    assert clawbacks[0]["reversed"] is False

    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    assert store_now["accrued_balance_cents"] == 0  # 13800 final - 13800 clawback


def test_delivery_supersedes_provisional_accrual_without_any_return(api):
    """PRD §3.4: "Delivery also finalizes the commission: the provisional
    `ORDER_ACCRUAL` entry is marked `reversed` true, a fresh final
    `ORDER_ACCRUAL` entry recomputed by the same per-line formula supersedes it,
    the affiliate's balance is reconciled again, and the payout sweep runs once
    more."
    PRD §2.7: "Once an entry has been superseded — by final settlement or by an
    explicit reversal — its `reversed` flag becomes true and it drops out of the
    balance computation permanently."

    Design: Difficulty/dual_variant_calc/order_commission_provisional_vs_final_diverge_after_return
    """
    set_clock("2026-09-01T00:00:00Z")
    book = _riverbend_book("9780000000001", "Hardcover One")
    store = create_active_store(
        shop_name="Maple Books",
        slug="maple-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    order = create_delivered_order("cust-1", book["id"], attributed_store_id=store["id"])
    assert order["fulfillment_status"] == "DELIVERED"

    entries = store_ledger(store["id"])
    accruals = [e for e in entries if e["kind"] == "ORDER_ACCRUAL"]
    assert len(accruals) == 2, "provisional plus final ORDER_ACCRUAL entries"
    reversed_accruals = [e for e in accruals if e["reversed"] is True]
    final_accruals = [e for e in accruals if e["reversed"] is False]
    assert len(reversed_accruals) == 1 and reversed_accruals[0]["amount_cents"] == 13800
    assert len(final_accruals) == 1 and final_accruals[0]["amount_cents"] == 13800

    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    # Only the non-reversed final entry counts: 13800, still under threshold.
    assert store_now["accrued_balance_cents"] == 13800


def test_cancel_placed_order_conserves_zero_net_ledger(api):
    """PRD §3.4: "Cancelling a `PLACED` order — available to the owning customer
    or to `CustomerService` acting on their behalf — requires the order paid,
    and unwinds the money: `payment_status` becomes `REFUNDED_FULL`,
    `refunded_cents` is set to the full `gross_cents` and `retained_cents` to
    zero, the provisional accrual entry is marked reversed, and a
    `COMMISSION_REVERSAL` ledger entry for the negative amount is written
    against the affiliate, whose balance is then reconciled."
    PRD §3.4: "Throughout the order's life, `retained_cents` always equals
    `gross_cents` minus `refunded_cents` and is recomputed on every return
    credit."

    Design: Difficulty/compensating_invariant/cancel_placed_order_conserves_zero_net_ledger
    """
    set_clock("2026-09-01T00:00:00Z")
    book = _riverbend_book("9780000000080", "Cancel Book")
    store = create_active_store(
        shop_name="Cancel Books",
        slug="cancel-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,  # 13800 accrual stays below: no payout
    )
    order = create_order("cust-12", book["id"], attributed_store_id=store["id"])
    place_order(order["id"], "cust-12")

    resp = api.order_action(
        order["id"], {"action": "cancel"}, make_customer_headers("cust-12")
    )
    cancelled = validate_success(resp, expected_status=200)
    assert cancelled["payment_status"] == "REFUNDED_FULL"
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert cancelled["refunded_cents"] == 100000
    assert cancelled["retained_cents"] == 0

    entries = store_ledger(store["id"])
    accruals = [e for e in entries if e["kind"] == "ORDER_ACCRUAL"]
    assert len(accruals) == 1
    assert accruals[0]["amount_cents"] == 13800
    assert accruals[0]["reversed"] is True
    reversals = [e for e in entries if e["kind"] == "COMMISSION_REVERSAL"]
    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == -13800

    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    assert store_now["accrued_balance_cents"] == 0
    payouts, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_store_id": store["id"]})
    )
    assert payouts == []


def test_cancel_draft_order_writes_no_ledger_entries(api):
    """PRD §3.4: "Cancelling while the order is still in `DRAFT` is a quiet act
    — no commission entry was ever written, so nothing needs clawing back."
    PRD §3.4: "An order's fulfillment lifecycle runs `DRAFT` → `PLACED` →
    `SENT_TO_WHOLESALER` → `SHIPPED` → `DELIVERED`, with `CANCELLED` as the
    terminal alternative reachable from `DRAFT` or `PLACED`"

    Design: Difficulty/compensating_invariant/cancel_placed_order_conserves_zero_net_ledger
    """
    set_clock("2026-09-01T00:00:00Z")
    book = _riverbend_book("9780000000080", "Cancel Book")
    store = create_active_store(
        shop_name="Cancel Books",
        slug="cancel-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    order = create_order("cust-12", book["id"], attributed_store_id=store["id"])
    cancelled = validate_success(
        api.order_action(
            order["id"], {"action": "cancel"}, make_customer_headers("cust-12")
        ),
        expected_status=200,
    )
    assert cancelled["fulfillment_status"] == "CANCELLED"
    assert store_ledger(store["id"]) == []


def test_order_place_blocked_by_suspended_partner(api):
    """PRD §3.4: "the attributed affiliate — store or partner — must be
    `ACTIVE`, or the placement is rejected with `ERR_AFFILIATE_NOT_ACTIVE`
    (HTTP 422)"
    PRD §3.2: "Suspending an `ACTIVE` partner blocks new order attribution and
    additionally freezes the partner's money in place: pending payouts for the
    partner cannot move into processing until reactivation."
    PRD §3.4: "A successful placement moves the order to `PLACED` and, in the
    same request, flips `payment_status` from `PENDING` to `PAID` — payment
    capture is atomic with placement."

    Design: Difficulty/cross_entity_state_dependency/order_place_blocked_by_suspended_partner
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Digital Press",
        discount_pct=0.0,
        returns_allowed=False,
        return_window_days=0,
        return_credit_pct=0.0,
    )
    book = create_book(
        pub["id"],
        isbn="9780000000060",
        title="Gate Book",
        format="EBOOK",
        list_price_cents=20000,
        ebook_partner_rev_share_pct=0.25,
    )
    partner = create_active_partner(
        display_name="Gate Author", partner_kind="AUTHOR", commission_pct=0.10
    )
    order = create_order(
        "cust-10", book["id"], attributed_partner_id=partner["id"]
    )
    get_success_data(api.partner_action(partner["id"], {"action": "suspend"}, ADMIN))

    cust = make_customer_headers("cust-10")
    resp = api.order_action(order["id"], {"action": "place"}, cust)
    validate_error(resp, ApiErrorId.ERR_AFFILIATE_NOT_ACTIVE, expected_status=422)
    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["fulfillment_status"] == "DRAFT"
    assert order_now["payment_status"] == "PENDING"

    get_success_data(api.partner_action(partner["id"], {"action": "activate"}, ADMIN))
    placed = validate_success(
        api.order_action(order["id"], {"action": "place"}, cust), expected_status=200
    )
    assert placed["fulfillment_status"] == "PLACED"
    assert placed["payment_status"] == "PAID"
    # platform keeps floor(20000 * 0.25) = 5000; commission floor(15000 * 0.10).
    assert placed["commission_cents"] == 1500


def test_order_place_blocked_by_suspended_store(api):
    """PRD §3.4: "the attributed affiliate — store or partner — must be
    `ACTIVE`, or the placement is rejected with `ERR_AFFILIATE_NOT_ACTIVE`
    (HTTP 422)"
    PRD §3.2: "Suspending an `ACTIVE` store stamps `suspended_at`, advances
    `version`, and — critically — blocks new order attribution to the store from
    that moment (enforced at placement)."

    Design: Difficulty/cross_entity_state_dependency/order_place_blocked_by_suspended_partner
    """
    set_clock("2026-09-01T00:00:00Z")
    book = _riverbend_book("9780000000001", "Hardcover One")
    store = create_active_store(
        shop_name="Maple Books",
        slug="maple-books",
        commission_pct=0.30,
        payout_threshold_cents=20000,
    )
    order = create_order("cust-10", book["id"], attributed_store_id=store["id"])
    get_success_data(api.store_action(store["id"], {"action": "suspend"}, ADMIN))

    cust = make_customer_headers("cust-10")
    resp = api.order_action(order["id"], {"action": "place"}, cust)
    validate_error(resp, ApiErrorId.ERR_AFFILIATE_NOT_ACTIVE, expected_status=422)
    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["fulfillment_status"] == "DRAFT"

    get_success_data(api.store_action(store["id"], {"action": "reactivate"}, ADMIN))
    placed = validate_success(
        api.order_action(order["id"], {"action": "place"}, cust), expected_status=200
    )
    assert placed["fulfillment_status"] == "PLACED"
    assert placed["payment_status"] == "PAID"


def test_approved_partner_cannot_be_attributed_until_active(api):
    """PRD §3.2: "A `PlatformAdmin` may approve an application, moving the
    partner to `APPROVED` — a state in which the partner exists but may not yet
    be attributed on orders — and only a subsequent activation moves the partner
    to `ACTIVE`, where order attribution becomes possible."
    PRD §3.4: "the attributed affiliate — store or partner — must be `ACTIVE`,
    or the placement is rejected with `ERR_AFFILIATE_NOT_ACTIVE` (HTTP 422)"

    Design: Corner/state_machines/approved_partner_cannot_be_attributed_until_active
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
        pub["id"],
        isbn="9780000001020",
        title="Gate Ebook",
        format="EBOOK",
        list_price_cents=20000,
        ebook_partner_rev_share_pct=0.25,
    )
    partner = create_partner(
        display_name="Terminal Author", partner_kind="AUTHOR", commission_pct=0.10
    )
    get_success_data(api.partner_action(partner["id"], {"action": "approve"}, ADMIN))
    order = create_order("cust-c2", book["id"], attributed_partner_id=partner["id"])

    cust = make_customer_headers("cust-c2")
    resp = api.order_action(order["id"], {"action": "place"}, cust)
    validate_error(resp, ApiErrorId.ERR_AFFILIATE_NOT_ACTIVE, expected_status=422)
    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["fulfillment_status"] == "DRAFT"
    assert order_now["payment_status"] == "PENDING"


def test_order_dispatch_requires_placed_and_ship_requires_dispatch(api):
    """PRD §3.4: "An order's fulfillment lifecycle runs `DRAFT` → `PLACED` →
    `SENT_TO_WHOLESALER` → `SHIPPED` → `DELIVERED`, with `CANCELLED` as the
    terminal alternative reachable from `DRAFT` or `PLACED`"
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Corner/state_machines/order_dispatch_requires_placed_and_ship_requires_dispatch
    """
    _publisher, book, store = setup_catalog_and_store(
        store_overrides={"commission_pct": 0.30, "payout_threshold_cents": 20000}
    )
    order = create_order("cust-c1", book["id"], attributed_store_id=store["id"])
    for action in ("dispatch", "ship", "deliver"):
        resp = api.order_action(order["id"], {"action": action}, WHOLESALER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    order_now = get_success_data(api.get_order(order["id"], FINANCE))
    assert order_now["fulfillment_status"] == "DRAFT"
    assert order_now["payment_status"] == "PENDING"
