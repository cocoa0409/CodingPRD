"""Exhibition ticket lifecycle: redemption date gate, refund window, the
sold-plus-remaining quota invariant, and the exhibition-close refund cascade
(PRD §3.2)."""

from test_helpers import (
    ApiErrorId,
    close_exhibition,
    create_exhibition,
    create_federal_fund,
    create_museum,
    create_trust_fund,
    get_fund,
    make_exhibition_manager_headers,
    make_public_headers,
    make_security_screener_headers,
    make_visitor_services_headers,
    purchase_ticket,
    redeem_ticket,
    refund_ticket,
    reset_clock,
    set_clock,
    setup_exhibition_on_sale,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_ticket_redeem_date_gate_and_terminal(api):
    """PRD §3.2: "A `SecurityScreener` redemption happens at the exhibition entrance exactly on the ticket's `visit_date` — any other date fails with `ERR_VISIT_DATE_MISMATCH` — and only while the exhibition is still `ON_SALE`; redemption moves the ticket `PURCHASED` to `REDEEMED`."
    PRD §2.8: "5. **Transition legality** — the target resource stands in a state from which the requested transition exists, else `ERR_INVALID_STATE`."

    Design: Corner/endpoints/ticket_redeem_date_gate_and_terminal
    """
    reset_clock()
    built = setup_exhibition_on_sale(
        fee_cents=1000, daily_ticket_quota=5, advance_clock_to="2026-09-10T00:00:00Z"
    )
    ticket = purchase_ticket(built["exhibition"]["id"], buyer_name="Redeemer", visit_date="2026-09-20")
    # The day before the visit date: the date gate rejects.
    set_clock("2026-09-19T12:00:00Z")
    resp_early = api.redeem_ticket(ticket["id"], headers=make_security_screener_headers())
    validate_error(resp_early, ApiErrorId.ERR_VISIT_DATE_MISMATCH)
    # On the visit date the redemption succeeds.
    set_clock("2026-09-20T12:00:00Z")
    redeemed = redeem_ticket(ticket["id"])
    assert redeemed["status"] == "REDEEMED"
    # REDEEMED is terminal for this path: a second redeem has no transition.
    resp_again = api.redeem_ticket(ticket["id"], headers=make_security_screener_headers())
    validate_error(resp_again, ApiErrorId.ERR_INVALID_STATE)


def test_refund_after_visit_date_rejected(api):
    """PRD §3.2: "A `VisitorServices` refund is permitted only while the current logical date is on or before the ticket's `visit_date`; a later attempt is rejected with `ERR_REFUND_WINDOW_CLOSED`."

    Design: Corner/endpoints/refund_after_visit_date_rejected
    """
    reset_clock()
    built = setup_exhibition_on_sale(
        fee_cents=1000, daily_ticket_quota=5, advance_clock_to="2026-09-10T00:00:00Z"
    )
    ticket = purchase_ticket(built["exhibition"]["id"], buyer_name="Late Refunder", visit_date="2026-09-20")
    # The day after the visit date: the manual-refund window has closed.
    set_clock("2026-09-21T09:00:00Z")
    resp = api.refund_ticket(ticket["id"], headers=make_visitor_services_headers())
    validate_error(resp, ApiErrorId.ERR_REFUND_WINDOW_CLOSED)
    after = validate_success(api.get_ticket(ticket["id"], headers=make_visitor_services_headers()))
    assert after["status"] == "PURCHASED"
    assert get_fund(built["fund"]["id"])["receipts_cents"] == 1000, (
        "a rejected refund must not debit receipts"
    )


def test_ticket_purchase_refund_conserves_quota(api):
    """PRD §3.2: "Each purchase also consumes one unit of the daily quota: counting tickets of the exhibition for the requested `visit_date` in `PURCHASED` or `REDEEMED` status, a purchase is allowed only while that count is strictly below `daily_ticket_quota`; a count equal to the quota means exhaustion and is rejected with `ERR_TICKET_QUOTA_EXHAUSTED`. `REFUNDED` tickets never count. The invariant for every exhibition and date is that the sold count plus the remaining count always equals `daily_ticket_quota`."

    Design: Difficulty/compensating_invariant/ticket_purchase_refund_conserves_quota
    """
    reset_clock()
    built = setup_exhibition_on_sale(
        fee_cents=1000, daily_ticket_quota=3, advance_clock_to="2026-09-10T00:00:00Z"
    )
    exhibition = built["exhibition"]
    t1 = purchase_ticket(exhibition["id"], buyer_name="Buyer One", visit_date="2026-09-20")
    t2 = purchase_ticket(exhibition["id"], buyer_name="Buyer Two", visit_date="2026-09-20")
    refund_ticket(t1["id"])  # frees one unit: sold drops from 2 back to 1
    t3 = purchase_ticket(exhibition["id"], buyer_name="Buyer Three", visit_date="2026-09-20")
    t4 = purchase_ticket(exhibition["id"], buyer_name="Buyer Four", visit_date="2026-09-20")
    # sold == quota == 3: the fifth purchase hits the exhaustion boundary.
    resp = api.purchase_ticket(
        exhibition["id"],
        {"buyer_name": "Buyer Five", "visit_date": "2026-09-20"},
        headers=make_public_headers("visitor-5"),
    )
    validate_error(resp, ApiErrorId.ERR_TICKET_QUOTA_EXHAUSTED)
    rows, _ = validate_paginated(
        api.list_tickets(
            headers=make_exhibition_manager_headers(), params={"exhibition_id": exhibition["id"]}
        )
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[t1["id"]]["status"] == "REFUNDED"
    for live in (t2, t3, t4):
        assert by_id[live["id"]]["status"] == "PURCHASED"
    assert get_fund(built["fund"]["id"])["receipts_cents"] == 3000, (
        "three live tickets at 1000; the refund debited the fourth"
    )


def test_exhibition_close_cascades_refunds_and_receipts(api):
    """PRD §3.2: "Closing the exhibition is the bulk exit: every ticket still `PURCHASED` flips to `REFUNDED`, and each such automatic refund debits the exhibition's revenue fund receipts by that ticket's `price_paid_cents`."

    Design: Difficulty/transitive_cascade/exhibition_close_cascades_refunds_and_receipts
    """
    reset_clock()
    built = setup_exhibition_on_sale(
        fee_cents=1000,
        daily_ticket_quota=5,
        appropriation_cents=100000000,
        advance_clock_to="2026-09-10T00:00:00Z",
    )
    exhibition, fund = built["exhibition"], built["fund"]
    t1 = purchase_ticket(exhibition["id"], buyer_name="Visitor Alpha", visit_date="2026-09-20")
    t2 = purchase_ticket(exhibition["id"], buyer_name="Visitor Beta", visit_date="2026-09-20")
    assert get_fund(fund["id"])["receipts_cents"] == 2000
    closed = close_exhibition(exhibition["id"])
    assert closed["status"] == "CLOSED"
    rows, _ = validate_paginated(
        api.list_tickets(
            headers=make_exhibition_manager_headers(), params={"exhibition_id": exhibition["id"]}
        )
    )
    by_id = {row["id"]: row for row in rows}
    assert by_id[t1["id"]]["status"] == "REFUNDED", "close cascade link 1: ticket flips"
    assert by_id[t2["id"]]["status"] == "REFUNDED", "close cascade link 1: ticket flips"
    fund_after = get_fund(fund["id"])
    assert fund_after["receipts_cents"] == 0, (
        "close cascade link 2: each refund debits receipts by price_paid_cents"
    )
    assert fund_after["settled_available_cents"] == 100000000, (
        "appropriation untouched; receipts netted to zero"
    )


def test_exhibition_close_from_draft_returns_invalid_state(api):
    """PRD §3.2: "The manager then moves it `DRAFT` to `ON_SALE` by opening the sale, and finally `ON_SALE` to `CLOSED` by closing it."
    PRD §2.8: "5. **Transition legality** — the target resource stands in a state from which the requested transition exists, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/exhibition_close_from_draft_returns_invalid_state
    """
    reset_clock()
    fund = create_trust_fund(appropriation_cents=1000000)
    museum = create_museum()
    exhibition = create_exhibition(
        museum["id"], fund["id"], title="Draft Show", fee_cents=500, daily_ticket_quota=10
    )
    resp = api.close_exhibition(exhibition["id"], headers=make_exhibition_manager_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = validate_success(
        api.get_exhibition(exhibition["id"], headers=make_exhibition_manager_headers())
    )
    assert after["status"] == "DRAFT"
    assert get_fund(fund["id"])["receipts_cents"] == 0, "no cascade runs off a rejected close"


def test_federal_revenue_fund_rejected(api):
    """PRD §3.2: "The exhibition's `revenue_fund_id` names the fund that receives ticket receipts and absorbs refund debits, and it must reference a `TRUST` fund — pointing it at a `FEDERAL` fund is rejected with `ERR_NOT_TRUST_FUND`, because ticket revenue is trust money."

    Design: Corner/errors/federal_revenue_fund_rejected
    """
    reset_clock()
    fed = create_federal_fund(appropriation_cents=1000000)
    museum = create_museum()
    resp = api.create_exhibition(
        museum["id"],
        {
            "title": "Federal Revenue Attempt",
            "fee_cents": 1000,
            "daily_ticket_quota": 5,
            "member_presale_opens_at": "2026-09-05T00:00:00Z",
            "public_sale_opens_at": "2026-09-10T00:00:00Z",
            "revenue_fund_id": fed["id"],
        },
        headers=make_exhibition_manager_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_TRUST_FUND)
    _, meta = validate_paginated(
        api.list_exhibitions(
            headers=make_exhibition_manager_headers(), params={"museum_id": museum["id"]}
        )
    )
    assert meta["total_count"] == 0, "no exhibition row may be created"
