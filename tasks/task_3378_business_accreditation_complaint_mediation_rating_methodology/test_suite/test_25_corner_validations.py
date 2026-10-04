"""Corner queue — validations: fiscal bounds on ledger entries (PRD §3.3),
the accreditation compliance gates (PRD §3.2), the temporal windows
(PRD §3.4/§3.5), single-answer mediation (PRD §3.5) and cross-business
referential integrity on disputes (PRD §3.7)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    answer_mediation,
    business_respond,
    compute_snapshot,
    consumer_reject,
    create_application,
    create_bureau,
    create_business,
    create_consumer,
    decide_application_payload,
    file_and_forward_complaint,
    get_application,
    get_business,
    get_complaint,
    get_invoice,
    ledger_entry_payload,
    make_business_rep_headers,
    offer_mediation,
    party_response_payload,
    run_daily_close,
    set_clock,
    setup_approved_application,
    setup_resolved_complaint,
    setup_unresolved_complaint,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
REVIEWER = TEST_USERS["standards_reviewer_headers"]


def _micro_business_with_approved_invoice():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    business = create_business(legal_name="Pay Test Micro LLC",
                               home_state_code="IA", employee_count=2,
                               founded_on="2020-01-01T00:00:00Z")
    app, invoice = setup_approved_application(business)
    return bureau, business, app, invoice


def _large_world_with_consumer():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    return bureau, consumer, business


def test_payment_exceeding_balance_rejected(api):
    """PRD §3.3: "A `BusinessRep` of the owning business posts an entry with
    `kind` `PAYMENT` and an `amount_cents` of at least 1 (a smaller amount is
    `ERR_INVALID_REQUEST`); a payment larger than the outstanding
    `balance_cents` is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`."
    PRD §3.3: "A payment that exactly covers the balance moves the invoice to
    `PAID` with `balance_cents` at 0 — and this is the moment accreditation
    lands: the linked application advances from `APPROVED_PENDING_DUES` to
    `ACCREDITED`"

    Design: Corner/validations/payment_exceeding_balance_rejected
    """
    _bureau, business, app, invoice = \
        _micro_business_with_approved_invoice()
    assert invoice["balance_cents"] == 40375
    resp = api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("PAYMENT", 40376),
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
    assert get_invoice(business["id"], invoice["id"])["paid_cents"] == 0
    resp = api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("PAYMENT", 40375),
        make_business_rep_headers(business["id"]))
    paid = validate_success(resp, 201)
    assert paid["status"] == "PAID" and paid["balance_cents"] == 0
    assert get_application(business["id"], app["id"])["status"] == \
        "ACCREDITED"


def test_refund_exceeding_paid_rejected(api):
    """PRD §3.3: "Refunds are the bureau's lever. A `BureauAdmin` posts an
    entry with `kind` `REFUND`, again with `amount_cents` of at least 1,
    bounded by the net amount actually collected: a refund larger than
    `paid_cents` minus `refunded_cents` is rejected with
    `ERR_REFUND_EXCEEDS_PAID`."
    PRD §3.3: "From `PAID`, a partial refund moves the invoice back to
    `PARTIALLY_PAID`, and a refund of the entire net paid amount settles it
    as `REFUNDED`."

    Design: Corner/validations/refund_exceeding_paid_rejected
    """
    _bureau, business, _app, invoice = \
        _micro_business_with_approved_invoice()
    validate_success(api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("PAYMENT", 40375),
        make_business_rep_headers(business["id"])), 201)
    resp = api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("REFUND", 40376), ADMIN)
    validate_error(resp, ApiErrorId.ERR_REFUND_EXCEEDS_PAID)
    resp = api.post_ledger_entry(
        invoice["id"], ledger_entry_payload("REFUND", 40375), ADMIN)
    refunded = validate_success(resp, 201)
    assert refunded["status"] == "REFUNDED"
    assert refunded["refunded_cents"] == 40375
    assert refunded["balance_cents"] == 40375


def test_approve_blocked_by_adverse_complaint_history(api):
    """PRD §3.2: "Both `complaints_unanswered_36m` and
    `complaints_unresolved_36m` must be exactly 0, or the decision is rejected
    with `ERR_ADVERSE_COMPLAINT_HISTORY` (HTTP 422)."

    Design: Corner/validations/approve_blocked_by_adverse_complaint_history
    """
    _bureau, consumer, business = _large_world_with_consumer()
    setup_unresolved_complaint(consumer, business)
    assert get_business(business["id"])["complaints_unresolved_36m"] == 1
    app = create_application(business, billing_plan="ANNUAL_PREPAID")
    app = submit_application(app)
    resp = api.decide_application(app["id"], decide_application_payload(),
                                  REVIEWER)
    validate_error(resp, ApiErrorId.ERR_ADVERSE_COMPLAINT_HISTORY)
    current = get_application(business["id"], app["id"])
    assert current["status"] == "SUBMITTED"
    assert current["dues_invoice_id"] is None


def test_approve_blocked_by_void_invoice_outstanding_balance(api):
    """PRD §3.2: "And the business must carry no dues invoice with a positive
    `balance_cents` in `OVERDUE`, nor any `VOID` invoice whose `voided_at`
    falls within the trailing 365 days, or the decision is rejected with
    `ERR_OUTSTANDING_DUES_BALANCE` (HTTP 422)."

    Design: Corner/validations/approve_blocked_by_void_invoice_outstanding_balance
    """
    bureau, business, _app1, _invoice = \
        _micro_business_with_approved_invoice()
    set_clock("2026-10-17T00:00:00Z")  # void the unpaid invoice
    run_daily_close(bureau["id"])
    app2 = create_application(business, billing_plan="ANNUAL_PREPAID",
                              license_number="LIC-L-2")
    app2 = submit_application(app2)
    resp = api.decide_application(app2["id"], decide_application_payload(),
                                  REVIEWER)
    validate_error(resp, ApiErrorId.ERR_OUTSTANDING_DUES_BALANCE)
    rows, meta = validate_paginated(api.list_dues_invoices(
        business["id"], make_business_rep_headers(business["id"])))
    assert len(rows) == 1 and meta["total_count"] == 1
    assert rows[0]["status"] == "VOID" and rows[0]["balance_cents"] == 40375


def test_mediation_create_after_14_day_window_rejected(api):
    """PRD §3.5: "A `BureauAdmin` may offer mediation on an `UNRESOLVED`
    complaint, but only within the mediation window: the offer must arrive no
    later than 14 days after the complaint's `last_unresolved_at`, and a later
    offer is rejected with `ERR_MEDIATION_WINDOW_EXPIRED`."

    Design: Corner/validations/mediation_create_after_14_day_window_rejected
    """
    _bureau, consumer, business = _large_world_with_consumer()
    complaint = setup_unresolved_complaint(consumer, business)
    set_clock("2026-09-16T00:00:00Z")  # 15 days after last_unresolved_at
    resp = api.create_mediation_case(complaint["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_MEDIATION_WINDOW_EXPIRED)
    assert get_business(business["id"])["complaints_open_count"] == 1
    rows, meta = validate_paginated(
        api.list_mediation_cases(complaint["id"], ADMIN))
    assert rows == [] and meta["total_count"] == 0


def test_reopen_after_30_day_window_rejected(api):
    """PRD §3.4: "A `BureauAdmin` may reopen a complaint in `RESOLVED` or
    `UNANSWERED` no later than 30 days after its `closed_at`; a later attempt
    is rejected with `ERR_REOPEN_WINDOW_EXPIRED`, and reopening from any other
    state is `ERR_COMPLAINT_INVALID_STATE`."

    Design: Corner/validations/reopen_after_30_day_window_rejected
    """
    _bureau, consumer, business = _large_world_with_consumer()
    complaint = setup_resolved_complaint(consumer, business)
    assert complaint["status"] == "RESOLVED"
    set_clock("2026-10-02T00:00:00Z")  # 31 days after closed_at
    resp = api.reopen_complaint(complaint["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_REOPEN_WINDOW_EXPIRED)
    current = get_complaint(complaint["id"])
    assert current["status"] == "RESOLVED"
    assert current["reopen_count"] == 0


def test_party_response_twice_by_same_party_rejected(api):
    """PRD §3.5: "A party may answer only once: responding when that side's
    field is no longer `PENDING` is rejected with
    `ERR_MEDIATION_INVALID_STATE`, as is any party response while the case is
    not `OFFERED`."
    PRD §3.5: "When one party has answered and the other is still `PENDING`,
    the case stays `OFFERED`."

    Design: Corner/validations/party_response_twice_by_same_party_rejected
    """
    _bureau, consumer, business = _large_world_with_consumer()
    complaint = setup_unresolved_complaint(consumer, business)
    case = offer_mediation(complaint)
    answered = answer_mediation(case, "BUSINESS", "ACCEPTED", business,
                                consumer)
    assert answered["status"] == "OFFERED"
    assert answered["business_response"] == "ACCEPTED"
    assert answered["consumer_response"] == "PENDING"
    resp = api.mediation_party_response(
        case["id"],
        party_response_payload(party="BUSINESS", response="DECLINED"),
        make_business_rep_headers(business["id"]))
    validate_error(resp, ApiErrorId.ERR_MEDIATION_INVALID_STATE)
    rows, _meta = validate_paginated(
        api.list_mediation_cases(complaint["id"], ADMIN))
    current = [r for r in rows if r["id"] == case["id"]][0]
    assert current["business_response"] == "ACCEPTED"
    assert current["status"] == "OFFERED"


def test_dispute_referencing_other_business_snapshot_rejected(api):
    """PRD §3.7: "The named snapshot must be one of the disputing business's
    own published snapshots and the disputed complaint must belong to that
    business — a `snapshot_id` or `disputed_complaint_id` belonging to another
    business is rejected with `ERR_SNAPSHOT_BUSINESS_MISMATCH` (HTTP 422)"

    Design: Corner/validations/dispute_referencing_other_business_snapshot_rejected
    """
    set_clock(CLOCK_START_ISO)
    create_bureau(name="Heartland Bureau", territory_state_codes=["IA", "NE"],
                  local_dues_fee_cents=0)
    biz_a = create_business(legal_name="Rated A LLC", home_state_code="IA",
                            employee_count=250,
                            founded_on="2018-01-01T00:00:00Z")
    snap_a = compute_snapshot(biz_a, variant="PUBLISHED")
    biz_b = create_business(legal_name="Unrated B LLC", home_state_code="IA",
                            employee_count=250,
                            founded_on="2018-01-01T00:00:00Z")
    # The OCC version is fresh for B, so the referential rule is the one
    # that fails.
    fresh_version_b = get_business(biz_b["id"])["version"]
    resp = api.create_rating_dispute(
        biz_b["id"],
        {"snapshot_id": snap_a["id"], "reason": "wrong snapshot",
         "expected_business_version": fresh_version_b},
        make_business_rep_headers(biz_b["id"]))
    validate_error(resp, ApiErrorId.ERR_SNAPSHOT_BUSINESS_MISMATCH)
    rows, meta = validate_paginated(api.list_rating_disputes(
        biz_b["id"], make_business_rep_headers(biz_b["id"])))
    assert rows == [] and meta["total_count"] == 0
