"""Broker credit scoring, disputes, and credit-driven cascades."""
from test_helpers import (
    validate_success, validate_error, get_success_data, validate_paginated,
    TEST_USERS, ApiErrorId,
    set_test_clock, create_broker, create_carrier, create_credit_event,
    get_broker, get_credit_event, get_dispute,
    make_broker_admin_headers, make_carrier_admin_headers,
    setup_verified_broker, post_load, get_load,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["compliance_analyst_headers"]


def _broker_and_carrier():
    broker = create_broker()
    carrier = create_carrier()
    return broker, carrier


def test_broker_credit_score_simple_vs_amount_weighted_diverge():
    """PRD §3.7: "Variant selection is by sample size: with 5 or more included
    events the weighted average governs; with fewer than 5 the simple average
    governs — so an identical event list can produce different scores
    depending on whether invoice amounts differ."

    Design: Difficulty/dual_variant_calc/broker_credit_score_simple_vs_amount_weighted_diverge
    """
    set_test_clock()
    broker, carrier = _broker_and_carrier()
    bid, cid = broker["id"], carrier["id"]
    for _ in range(4):
        create_credit_event(bid, cid, invoice_amount_cents=100000, days_to_pay=30)
    create_credit_event(bid, cid, invoice_amount_cents=10000, days_to_pay=60)

    b = get_broker(bid)
    assert b["credit_event_count"] == 5
    assert abs(b["days_to_pay_weighted"] - 30.7317) < 0.0001
    assert abs(b["days_to_pay_simple"] - 36.0) < 0.0001
    assert b["credit_score"] == 84
    assert b["credit_badge"] == "GOLD"
    assert b["credit_score"] != 79


def test_credit_dispute_rebuttal_cycle_returns_to_under_review():
    """PRD §3.7: "The broker may rebut — `UNDER_REVIEW` → `REBUTTED` —
    supplying a `rebuttal_note`, but at most twice per dispute: a third
    attempt is rejected with `ERR_REBUTTAL_LIMIT_EXCEEDED`, and each accepted
    rebuttal increments `rebuttal_count` by 1."

    Design: Difficulty/non_linear_state_machine/credit_dispute_rebuttal_cycle_returns_to_under_review
    """
    set_test_clock()
    broker, carrier = _broker_and_carrier()
    bid, cid = broker["id"], carrier["id"]
    ev = create_credit_event(bid, cid, invoice_amount_cents=50000, days_to_pay=45)
    bh = make_broker_admin_headers(bid)

    disp = validate_success(api_client.file_dispute(
        ev["id"], {"reason": "Invoice was paid on time per ACH trace"}, bh), expected_status=201)
    get_success_data(api_client.start_dispute_review(disp["id"], ANALYST))

    r1 = validate_success(api_client.rebut_dispute(
        disp["id"], {"rebuttal_note": "First rebuttal with bank letter"}, bh))
    assert r1["status"] == "REBUTTED" and r1["rebuttal_count"] == 1
    get_success_data(api_client.start_dispute_review(disp["id"], ANALYST))
    r2 = validate_success(api_client.rebut_dispute(
        disp["id"], {"rebuttal_note": "Second rebuttal with signed POD"}, bh))
    assert r2["status"] == "REBUTTED" and r2["rebuttal_count"] == 2
    get_success_data(api_client.start_dispute_review(disp["id"], ANALYST))

    resp = api_client.rebut_dispute(
        disp["id"], {"rebuttal_note": "Third rebuttal attempt"}, bh)
    validate_error(resp, ApiErrorId.ERR_REBUTTAL_LIMIT_EXCEEDED)
    assert get_dispute(disp["id"])["status"] == "UNDER_REVIEW"


def test_dispute_requires_credit_event_published():
    """PRD §3.7: "Filing requires the event to be `PUBLISHED` — disputing an
    event in any other status is rejected with
    `ERR_CREDIT_EVENT_NOT_PUBLISHED`"

    Design: Difficulty/cross_entity_state_dependency/dispute_requires_credit_event_published
    """
    set_test_clock()
    broker, carrier = _broker_and_carrier()
    bid, cid = broker["id"], carrier["id"]
    ev = create_credit_event(bid, cid, invoice_amount_cents=50000, days_to_pay=45)
    bh = make_broker_admin_headers(bid)
    get_success_data(api_client.file_dispute(ev["id"], {"reason": "first"}, bh))

    resp = api_client.file_dispute(ev["id"], {"reason": "second"}, bh)
    validate_error(resp, ApiErrorId.ERR_CREDIT_EVENT_NOT_PUBLISHED)
    assert get_credit_event(ev["id"])["status"] == "UNDER_DISPUTE"
    rows, _ = validate_paginated(api_client.list_credit_disputes(
        ADMIN, params={"credit_report_event_id": ev["id"]}))
    assert len(rows) == 1


def test_dispute_filed_after_ninety_days_rejected():
    """PRD §3.7: "A broker that disputes a reported event acts within 90 days
    of the event's `reported_at`; filing later is rejected with
    `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422)."

    Design: Corner/validations/dispute_filed_after_ninety_days_rejected
    """
    set_test_clock("2026-01-01T00:00:00Z")
    broker, carrier = _broker_and_carrier()
    bid, cid = broker["id"], carrier["id"]
    ev = create_credit_event(bid, cid, invoice_amount_cents=50000, days_to_pay=45)

    set_test_clock("2026-04-02T00:00:00Z")
    resp = api_client.file_dispute(ev["id"], {"reason": "Too late to dispute"},
                                   make_broker_admin_headers(bid))
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)
    assert get_credit_event(ev["id"])["status"] == "PUBLISHED"


def test_dispute_then_sustain_resolution_restores_credit_totals():
    """PRD §3.7: "A `SUSTAIN` outcome lands the dispute in `RESOLVED_SUSTAIN`
    and returns the event to `PUBLISHED`, recomputing the broker's credit
    fields with the event included again." and "The broker record also tracks
    `credit_event_count` (events in `PUBLISHED` or `UNDER_DISPUTE` status),
    and three ledger sums: `included_amount_cents` over `PUBLISHED` events,
    `under_dispute_amount_cents` over `UNDER_DISPUTE` events, and
    `removed_amount_cents` over `REMOVED` events."

    Design: Difficulty/compensating_invariant/dispute_then_sustain_resolution_restores_credit_totals
    """
    set_test_clock()
    broker, carrier = _broker_and_carrier()
    bid, cid = broker["id"], carrier["id"]
    create_credit_event(bid, cid, invoice_amount_cents=50000, days_to_pay=30)
    ev_b = create_credit_event(bid, cid, invoice_amount_cents=70000, days_to_pay=40)

    pre = get_broker(bid)
    assert pre["credit_score"] == 74
    assert pre["included_amount_cents"] == 120000
    assert pre["under_dispute_amount_cents"] == 0
    assert pre["removed_amount_cents"] == 0

    bh = make_broker_admin_headers(bid)
    disp = validate_success(api_client.file_dispute(
        ev_b["id"], {"reason": "Payment was within terms"}, bh), expected_status=201)

    mid = get_broker(bid)
    assert mid["included_amount_cents"] == 50000
    assert mid["under_dispute_amount_cents"] == 70000
    assert mid["removed_amount_cents"] == 0
    assert mid["credit_score"] == 73
    assert (mid["included_amount_cents"] + mid["under_dispute_amount_cents"]
            + mid["removed_amount_cents"]) == 120000

    r = validate_success(api_client.resolve_dispute(disp["id"], {"outcome": "SUSTAIN"}, ANALYST))
    assert r["status"] == "RESOLVED_SUSTAIN"
    assert get_credit_event(ev_b["id"])["status"] == "PUBLISHED"

    post = get_broker(bid)
    assert post["included_amount_cents"] == 120000
    assert post["under_dispute_amount_cents"] == 0
    assert post["removed_amount_cents"] == 0
    assert post["credit_score"] == 74
    assert abs(post["days_to_pay_simple"] - 35.0) < 0.0001


def test_dispute_remove_cascades_event_score_org_suspension():
    """PRD §3.7: "A `REMOVE` outcome lands the dispute in `RESOLVED_REMOVE`
    and moves the event permanently to `REMOVED`, recomputing the broker's
    fields with the event excluded for good — and this is the moment the floor
    falls out: if the recomputed `credit_score` is below 40, the broker org is
    suspended and the full suspension cascade of §3.8 fires." and §3.7:
    "creation alone never suspends a broker, no matter how bad the numbers
    look."

    Design: Difficulty/transitive_cascade/dispute_remove_cascades_event_score_org_suspension
    """
    set_test_clock()
    bctx = setup_verified_broker()
    carrier = create_carrier()
    bid, cid = bctx["broker"]["id"], carrier["id"]
    load = post_load(bctx, rate_offer_cents=120000)

    for _ in range(5):
        create_credit_event(bid, cid, invoice_amount_cents=100000, days_to_pay=80)
    good = create_credit_event(bid, cid, invoice_amount_cents=100000, days_to_pay=30)

    # Creation never suspends even though score is bad.
    pre = get_broker(bid)
    assert pre["status"] == "ACTIVE"
    assert pre["credit_badge"] == "CRITICAL"

    bh = make_broker_admin_headers(bid)
    disp = validate_success(api_client.file_dispute(
        good["id"], {"reason": "Broker contests the only clean record"}, bh),
        expected_status=201)

    r = validate_success(api_client.resolve_dispute(disp["id"], {"outcome": "REMOVE"}, ANALYST))
    assert r["status"] == "RESOLVED_REMOVE"
    assert get_credit_event(good["id"])["status"] == "REMOVED"

    b = get_broker(bid)
    assert b["credit_event_count"] == 5
    assert b["included_amount_cents"] == 500000
    assert b["removed_amount_cents"] == 100000
    assert b["credit_score"] == 35
    assert b["credit_badge"] == "CRITICAL"
    assert b["status"] == "SUSPENDED"

    l = get_load(load["id"])
    assert l["status"] == "WITHDRAWN"
    assert l["visibility"] == "DELISTED"
