"""Payout lifecycle: retry cycle, threshold boundary, dedupe, role and state gates."""
from test_helpers import (
    ADMIN,
    FINANCE,
    SERVICE,
    ApiErrorId,
    create_active_partner,
    create_active_store,
    create_book,
    create_order,
    create_publisher,
    get_success_data,
    make_customer_headers,
    place_order,
    set_clock,
    store_ledger,
    validate_error,
    validate_paginated,
    validate_success,
)


def _place_payout_order(store_id, book_id, customer_id):
    order = create_order(customer_id, book_id, attributed_store_id=store_id)
    return place_order(order["id"], customer_id)


def _single_payout(api, store_id):
    payouts, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_store_id": store_id})
    )
    assert len(payouts) == 1
    return payouts[0]


def test_payout_failed_to_pending_retry_cycle(api):
    """PRD §3.7: "A payout begins `PENDING`; its lifecycle runs `PENDING` →
    `PROCESSING` → `PAID`, with a `PROCESSING` → `FAILED` → `PENDING` retry
    cycle, and `PAID` as the only terminal state."
    PRD §3.7: "Marking the payout paid is terminal and debits the affiliate: the
    payout's `amount_cents` is subtracted from the affiliate's
    `accrued_balance_cents` as the ledger-derived balance is reconciled. A
    processing payout may instead fail, recording a `failure_reason`; failure is
    not terminal — a retry returns the payout to `PENDING` and clears the
    `failure_reason`, ready to begin the cycle again."

    Design: Difficulty/non_linear_state_machine/payout_failed_to_pending_retry_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book = create_book(pub["id"], isbn="9780000000021", title="Payout Book")
    store = create_active_store(
        shop_name="Retry Books", slug="retry-books", commission_pct=0.30
    )
    _place_payout_order(store["id"], book["id"], "cust-5")

    payout = _single_payout(api, store["id"])
    assert payout["amount_cents"] == 13800

    get_success_data(api.payout_action(payout["id"], {"action": "process"}, FINANCE))
    failed = get_success_data(
        api.payout_action(
            payout["id"], {"action": "fail", "failure_reason": "bank_reject"}, FINANCE
        )
    )
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == "bank_reject"

    retried = get_success_data(
        api.payout_action(payout["id"], {"action": "retry"}, FINANCE)
    )
    assert retried["status"] == "PENDING"
    assert retried["failure_reason"] is None
    assert retried["amount_cents"] == 13800  # frozen across the cycle

    get_success_data(api.payout_action(payout["id"], {"action": "process"}, FINANCE))
    paid = get_success_data(
        api.payout_action(payout["id"], {"action": "mark-paid"}, FINANCE)
    )
    assert paid["status"] == "PAID"

    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    assert store_now["accrued_balance_cents"] == 0


def test_payout_amount_frozen_snapshot_at_release(api):
    """PRD §3.7: "Payouts are never created by hand; they exist only because the
    release sweep of §2.7 opened one, carrying an `amount_cents` frozen as the
    affiliate's accrued balance at that instant."
    PRD §2.7: "a new payout is opened for exactly the current balance as a
    frozen snapshot."

    Design: Difficulty/non_linear_state_machine/payout_failed_to_pending_retry_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book = create_book(pub["id"], isbn="9780000000021", title="Payout Book")
    store = create_active_store(
        shop_name="Retry Books", slug="retry-books", commission_pct=0.30
    )
    _place_payout_order(store["id"], book["id"], "cust-5")

    payout = _single_payout(api, store["id"])
    assert payout["status"] == "PENDING"
    # Frozen at the balance observed when the sweep fired.
    assert payout["amount_cents"] == 13800
    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    assert store_now["accrued_balance_cents"] == 13800


def test_payout_mark_paid_conserves_ledger_minus_paid_identity(api):
    """PRD §2.7: "An affiliate's `accrued_balance_cents` is a derived figure,
    never written directly: it is the sum of the `amount_cents` of that
    affiliate's ledger entries whose `reversed` flag is false, minus the
    `amount_cents` of the affiliate's payouts that have reached `PAID`."
    PRD §3.7: "Marking the payout paid is terminal and debits the affiliate: the
    payout's `amount_cents` is subtracted from the affiliate's
    `accrued_balance_cents` as the ledger-derived balance is reconciled."

    Design: Difficulty/compensating_invariant/payout_mark_paid_conserves_ledger_minus_paid_identity
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book = create_book(pub["id"], isbn="9780000000081", title="Identity Book")
    store = create_active_store(
        shop_name="Identity Books", slug="identity-books", commission_pct=0.30
    )
    _place_payout_order(store["id"], book["id"], "cust-13")

    payout = _single_payout(api, store["id"])
    get_success_data(api.payout_action(payout["id"], {"action": "process"}, FINANCE))
    get_success_data(
        api.payout_action(
            payout["id"], {"action": "fail", "failure_reason": "bank_reject"}, FINANCE
        )
    )
    get_success_data(api.payout_action(payout["id"], {"action": "retry"}, FINANCE))
    get_success_data(api.payout_action(payout["id"], {"action": "process"}, FINANCE))

    before = get_success_data(api.get_store(store["id"], FINANCE))
    assert before["accrued_balance_cents"] == 13800  # 13800 - 0 PAID

    paid = get_success_data(
        api.payout_action(payout["id"], {"action": "mark-paid"}, FINANCE)
    )
    assert paid["status"] == "PAID"
    assert paid["amount_cents"] == 13800

    after = get_success_data(api.get_store(store["id"], FINANCE))
    assert after["accrued_balance_cents"] == 0  # 13800 - 13800

    entries = store_ledger(store["id"])
    assert len(entries) == 1, "payout lifecycle never writes ledger entries"
    assert entries[0]["kind"] == "ORDER_ACCRUAL"
    assert entries[0]["amount_cents"] == 13800


def test_mark_paid_requires_processing_and_is_terminal(api):
    """PRD §3.7: "A payout begins `PENDING`; its lifecycle runs `PENDING` →
    `PROCESSING` → `PAID`, with a `PROCESSING` → `FAILED` → `PENDING` retry
    cycle, and `PAID` as the only terminal state."
    PRD §2.11: "Only then are state-machine preconditions checked
    (`ERR_INVALID_STATE`, HTTP 409)"

    Design: Difficulty/compensating_invariant/payout_mark_paid_conserves_ledger_minus_paid_identity
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Riverbend Press",
        discount_pct=0.46,
        returns_allowed=True,
        return_window_days=30,
        return_credit_pct=0.80,
    )
    book = create_book(pub["id"], isbn="9780000000081", title="Identity Book")
    store = create_active_store(
        shop_name="Identity Books", slug="identity-books", commission_pct=0.30
    )
    _place_payout_order(store["id"], book["id"], "cust-13")
    payout = _single_payout(api, store["id"])

    # PENDING -> mark-paid skips PROCESSING: rejected.
    resp = api.payout_action(payout["id"], {"action": "mark-paid"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    before = get_success_data(api.get_store(store["id"], FINANCE))
    assert before["accrued_balance_cents"] == 13800  # untouched

    get_success_data(api.payout_action(payout["id"], {"action": "process"}, FINANCE))
    get_success_data(api.payout_action(payout["id"], {"action": "mark-paid"}, FINANCE))

    # PAID is terminal: a second mark-paid is rejected.
    resp = api.payout_action(payout["id"], {"action": "mark-paid"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = get_success_data(api.get_store(store["id"], FINANCE))
    assert after["accrued_balance_cents"] == 0


def test_payout_threshold_exact_equality_releases(api):
    """PRD §2.7: "A balance exactly equal to the threshold does release.
    Balances below the threshold simply accrue until a later event lifts them
    across."
    PRD §2.7: "if the balance is greater than or equal to the affiliate's
    `payout_threshold_cents`, and no payout for that affiliate currently sits in
    `PENDING` or `PROCESSING`, and the affiliate's own status is `ACTIVE`, a new
    payout is opened for exactly the current balance as a frozen snapshot."

    Design: Difficulty/boundary_precision_check/payout_threshold_exact_equality_releases
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Digital Press",
        discount_pct=0.0,
        returns_allowed=False,
        return_window_days=0,
        return_credit_pct=0.0,
    )
    cheap = create_book(
        pub["id"],
        isbn="9780000000050",
        title="Cheap Ebook",
        format="EBOOK",
        list_price_cents=10000,
        ebook_partner_rev_share_pct=0.25,
    )
    exact = create_book(
        pub["id"],
        isbn="9780000000051",
        title="Exact Ebook",
        format="EBOOK",
        list_price_cents=13333,
        ebook_partner_rev_share_pct=0.25,
    )
    low = create_active_partner(
        display_name="Below Threshold",
        partner_kind="AUTHOR",
        commission_pct=0.10,
        payout_threshold_cents=1000,
    )
    eq = create_active_partner(
        display_name="Exact Threshold",
        partner_kind="INFLUENCER",
        commission_pct=0.10,
        payout_threshold_cents=1000,
    )

    order_low = create_order("cust-9", cheap["id"], attributed_partner_id=low["id"])
    place_order(order_low["id"], "cust-9")
    order_eq = create_order("cust-9", exact["id"], attributed_partner_id=eq["id"])
    place_order(order_eq["id"], "cust-9")

    low_now = get_success_data(api.get_partner(low["id"], FINANCE))
    assert low_now["accrued_balance_cents"] == 750  # floor((10000-2500) * 0.10)
    payouts_low, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_partner_id": low["id"]})
    )
    assert payouts_low == [], "750 < 1000: no payout"

    eq_now = get_success_data(api.get_partner(eq["id"], FINANCE))
    assert eq_now["accrued_balance_cents"] == 1000  # floor((13333-3333) * 0.10)
    payouts_eq, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_partner_id": eq["id"]})
    )
    assert len(payouts_eq) == 1, "balance exactly equal to the threshold releases"
    assert payouts_eq[0]["amount_cents"] == 1000


def test_partner_balance_below_threshold_opens_no_payout(api):
    """PRD §2.7: "Balances below the threshold simply accrue until a later event
    lifts them across."
    PRD §2.7: "if the balance is greater than or equal to the affiliate's
    `payout_threshold_cents`, and no payout for that affiliate currently sits in
    `PENDING` or `PROCESSING`, and the affiliate's own status is `ACTIVE`, a new
    payout is opened for exactly the current balance as a frozen snapshot."

    Design: Difficulty/boundary_precision_check/payout_threshold_exact_equality_releases
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Digital Press",
        discount_pct=0.0,
        returns_allowed=False,
        return_window_days=0,
        return_credit_pct=0.0,
    )
    cheap = create_book(
        pub["id"],
        isbn="9780000000050",
        title="Cheap Ebook",
        format="EBOOK",
        list_price_cents=10000,
        ebook_partner_rev_share_pct=0.25,
    )
    low = create_active_partner(
        display_name="Below Threshold",
        partner_kind="AUTHOR",
        commission_pct=0.10,
        payout_threshold_cents=1000,
    )
    order = create_order("cust-9", cheap["id"], attributed_partner_id=low["id"])
    place_order(order["id"], "cust-9")

    low_now = get_success_data(api.get_partner(low["id"], FINANCE))
    assert low_now["accrued_balance_cents"] == 750
    payouts, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_partner_id": low["id"]})
    )
    assert payouts == [], "750 < 1000: the balance simply accrues"


def test_payout_no_duplicate_open_per_affiliate(api):
    """PRD §2.7: "if the balance is greater than or equal to the affiliate's
    `payout_threshold_cents`, and no payout for that affiliate currently sits in
    `PENDING` or `PROCESSING`, and the affiliate's own status is `ACTIVE`, a new
    payout is opened for exactly the current balance as a frozen snapshot."

    Design: Corner/cross_cutting/payout_no_duplicate_open_per_affiliate
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Corner Press",
        discount_pct=0.45,
        returns_allowed=True,
        return_window_days=60,
        return_credit_pct=1.0,
    )
    book = create_book(pub["id"], isbn="9780000001021", title="Pipe Book")
    store = create_active_store(
        shop_name="Dup Books", slug="dup-books", commission_pct=0.30
    )
    _place_payout_order(store["id"], book["id"], "cust-c1")
    _place_payout_order(store["id"], book["id"], "cust-c1")

    payouts, _ = validate_paginated(
        api.list_payouts(FINANCE, {"affiliate_store_id": store["id"]})
    )
    assert len(payouts) == 1, "a PENDING payout blocks a second release"
    assert payouts[0]["amount_cents"] == 13500  # frozen at the first accrual

    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    assert store_now["accrued_balance_cents"] == 27000


def test_err_affiliate_not_active_on_payout_process(api):
    """PRD §3.7: "`FinanceOps` moves it to `PROCESSING` — but only while the
    beneficiary affiliate, store or partner, is itself `ACTIVE`; processing
    against a suspended affiliate is rejected with `ERR_AFFILIATE_NOT_ACTIVE`."
    PRD §3.2: "Suspending an `ACTIVE` partner blocks new order attribution and
    additionally freezes the partner's money in place: pending payouts for the
    partner cannot move into processing until reactivation."

    Design: Corner/errors/err_affiliate_not_active_on_payout_process
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Corner Press",
        discount_pct=0.45,
        returns_allowed=True,
        return_window_days=60,
        return_credit_pct=1.0,
    )
    book = create_book(pub["id"], isbn="9780000001021", title="Pipe Book")
    store = create_active_store(
        shop_name="Suspend Books", slug="suspend-books", commission_pct=0.30
    )
    _place_payout_order(store["id"], book["id"], "cust-c1")
    payout = _single_payout(api, store["id"])

    get_success_data(api.store_action(store["id"], {"action": "suspend"}, ADMIN))
    resp = api.payout_action(payout["id"], {"action": "process"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_AFFILIATE_NOT_ACTIVE, expected_status=422)
    payout_now = get_success_data(api.get_payout(payout["id"], FINANCE))
    assert payout_now["status"] == "PENDING"

    get_success_data(api.store_action(store["id"], {"action": "reactivate"}, ADMIN))
    processed = validate_success(
        api.payout_action(payout["id"], {"action": "process"}, FINANCE),
        expected_status=200,
    )
    assert processed["status"] == "PROCESSING"


def test_store_deactivate_blocked_by_outstanding_balance(api):
    """PRD §3.2: "Deactivation is the terminal act, permitted from either
    `ACTIVE` or `SUSPENDED`, but only when the store's `accrued_balance_cents`
    is exactly zero and no payout for the store sits in `PENDING` or
    `PROCESSING`; otherwise the request fails with
    `ERR_STORE_SETTLEMENT_OUTSTANDING` (HTTP 422)."

    Design: Corner/validations/store_deactivate_blocked_by_outstanding_balance
    """
    set_clock("2026-09-01T00:00:00Z")
    pub = create_publisher(
        name="Corner Press",
        discount_pct=0.45,
        returns_allowed=True,
        return_window_days=60,
        return_credit_pct=1.0,
    )
    book = create_book(pub["id"], isbn="9780000001021", title="Pipe Book")
    store = create_active_store(
        shop_name="Settle Books", slug="settle-books", commission_pct=0.30
    )
    _place_payout_order(store["id"], book["id"], "cust-c1")
    payout = _single_payout(api, store["id"])

    resp = api.store_action(store["id"], {"action": "deactivate"}, ADMIN)
    validate_error(
        resp, ApiErrorId.ERR_STORE_SETTLEMENT_OUTSTANDING, expected_status=422
    )

    get_success_data(api.payout_action(payout["id"], {"action": "process"}, FINANCE))
    get_success_data(api.payout_action(payout["id"], {"action": "mark-paid"}, FINANCE))
    store_now = get_success_data(api.get_store(store["id"], FINANCE))
    assert store_now["accrued_balance_cents"] == 0

    resp = api.store_action(store["id"], {"action": "deactivate"}, ADMIN)
    deactivated = validate_success(resp, expected_status=200)
    assert deactivated["status"] == "DEACTIVATED"
