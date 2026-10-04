"""Engagement origination, fee settlement, document intake, and withdrawal.

Covers the solicited/unsolicited initial states, the per-credit-type fee
schedule, version ticking and timestamp refresh on mutation, ownership and
fee-settlement rejections, the document registry rules, and the withdrawal
gates and refund invariant (PRD sections 2.5, 2.10 and 3.1-3.2).
"""

from datetime import datetime, timezone

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    CLOCK_START_ISO,
    DOC_AUDIT_FY,
    FEE_GO_CENTS,
    accept_terms,
    advance_clock,
    create_engagement_solicited,
    create_engagement_unsolicited,
    create_issuer,
    get_engagement,
    get_issuer,
    issuer_headers,
    make_issuer_headers,
    setup_assigned_rating,
    submit_document,
    validate_error,
    validate_success,
)


def _instant(value):
    """Parse an ISO 8601 UTC timestamp for representation-agnostic equality."""
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def test_engagement_solicited_initial_state_requested(api):
    """PRD section 3.1: "A solicited engagement starts in `REQUESTED` with
    `fee_paid` false; an unsolicited one skips negotiation entirely and starts
    in `INFORMATION_GATHERING`."
    PRD section 3.1: "The engagement fee is fixed by credit family: 4500000
    cents for `GENERAL_OBLIGATION`, 5200000 cents for `REVENUE`, and 5800000
    cents for `ENTERPRISE`."

    Design: Corner/state_machines/engagement_solicited_initial_state_requested
    """
    issuer = create_issuer(api)
    data = create_engagement_solicited(api, issuer)
    assert data["status"] == "REQUESTED"
    assert data["fee_paid"] is False
    assert data["fee_cents"] == 4500000
    assert data["received_document_codes"] == []
    # The PRD derives the solicited requirement set from solicitation and
    # credit type without enumerating it, so no exact list is asserted here.
    assert isinstance(data["required_document_codes"], list)


def test_unsolicited_engagement_fee_waived_and_initial_state(api):
    """PRD section 3.1: "An unsolicited engagement carries a `fee_cents` of 0
    and is created with `fee_paid` already true, its fee waived."
    PRD section 3.1: "`required_document_codes` is derived from the
    engagement's `solicitation` and `credit_type` for a solicited engagement,
    and is exactly the single code `PUBLIC_FILING_FY` for an unsolicited one."

    Design: Corner/entities/unsolicited_engagement_fee_waived_and_initial_state
    """
    issuer = create_issuer(api)
    data = create_engagement_unsolicited(api, issuer)
    assert data["status"] == "INFORMATION_GATHERING", (
        "the unsolicited path skips the accept-terms negotiation"
    )
    assert data["fee_cents"] == 0
    assert data["fee_paid"] is True
    assert data["required_document_codes"] == ["PUBLIC_FILING_FY"]


def test_fee_schedule_constants_per_credit_type(api):
    """PRD section 3.1: "The engagement fee is fixed by credit family:
    4500000 cents for `GENERAL_OBLIGATION`, 5200000 cents for `REVENUE`, and
    5800000 cents for `ENTERPRISE`."

    Design: Corner/calculations/fee_schedule_constants_per_credit_type
    """
    issuer_a = create_issuer(api, legal_name="City of Example")
    issuer_b = create_issuer(api, legal_name="Example Water Authority")
    revenue = create_engagement_solicited(
        api, issuer_a, credit_type="REVENUE"
    )
    enterprise = create_engagement_solicited(
        api, issuer_b, credit_type="ENTERPRISE"
    )
    assert revenue["fee_cents"] == 5200000
    assert enterprise["fee_cents"] == 5800000


def test_engagement_version_increments_on_each_mutation(api):
    """PRD section 2.5: "`version` is an integer that increments by one on
    every mutation of the resource, whether the mutation is client-driven or
    system-driven."
    PRD section 2.5: "`created_at` is an ISO 8601 UTC timestamp with three
    fractional digits, fixed at creation. `updated_at` is refreshed on every
    change to the resource."
    PRD section 2.4: "Every timestamp the system records — `assigned_at`,
    `published_at`, `withdrawn_at`, `submitted_at`, `decided_at`,
    `completed_at`, `activated_at`, `due_at`, and the common `created_at` and
    `updated_at` fields — reads this logical clock."

    Design: Corner/cross_cutting_complexity_layers/engagement_version_increments_on_each_mutation
    """
    issuer = create_issuer(api)
    engagement = create_engagement_solicited(api, issuer)
    assert engagement["version"] == 1
    created_at = engagement["created_at"]

    advance_clock(api, "2026-09-01T01:00:00Z")
    engagement = accept_terms(api, engagement, issuer)
    assert engagement["version"] == 2
    assert _instant(engagement["updated_at"]) == _instant("2026-09-01T01:00:00Z")

    advance_clock(api, "2026-09-01T02:00:00Z")
    engagement = submit_document(
        api, engagement["id"], DOC_AUDIT_FY, issuer_headers(issuer)
    )
    assert engagement["version"] == 3
    assert _instant(engagement["updated_at"]) == _instant("2026-09-01T02:00:00Z")
    assert _instant(engagement["created_at"]) == _instant(created_at)
    assert _instant(created_at) == _instant(CLOCK_START_ISO)


def test_accept_terms_by_non_owner_rejected(api):
    """PRD section 2.10: "Fifth, ownership: the caller's `X-User-ID` must match
    the owning identity — the engagement's issuer for term acceptance,
    document submission, withdrawal, appeals, and disclosure submission; the
    session's `chair_id` for open, close, and alternate appointment; the
    underwriter on underwriter-originated engagements; and the issuer on bond
    sales — failing as `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/validations/accept_terms_by_non_owner_rejected
    """
    issuer_a = create_issuer(api, legal_name="City of Example")
    issuer_b = create_issuer(api, legal_name="County of Example")
    engagement = create_engagement_solicited(api, issuer_a)
    resp = api.accept_terms(
        engagement["id"],
        {"fee_payment_cents": engagement["fee_cents"], "apply_credit_cents": 0},
        headers=make_issuer_headers(issuer_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    engagement = get_engagement(api, engagement["id"])
    assert engagement["status"] == "REQUESTED"
    assert engagement["fee_paid"] is False


def test_fee_underpayment_rejected(api):
    """PRD section 3.1: "The cash and the applied credit together must equal
    `fee_cents` exactly, or the attempt fails with
    `ERR_FEE_PAYMENT_MISMATCH`; the applied credit may not exceed the issuer's
    `credit_balance_cents`, or it fails with `ERR_INSUFFICIENT_ISSUER_CREDIT`."

    Design: Corner/validations/fee_underpayment_rejected
    """
    issuer = create_issuer(api)
    engagement = create_engagement_solicited(api, issuer)
    resp = api.accept_terms(
        engagement["id"],
        {"fee_payment_cents": engagement["fee_cents"] - 1, "apply_credit_cents": 0},
        headers=issuer_headers(issuer),
    )
    validate_error(resp, ApiErrorId.ERR_FEE_PAYMENT_MISMATCH)
    engagement = get_engagement(api, engagement["id"])
    assert engagement["status"] == "REQUESTED"
    assert engagement["fee_paid"] is False


def test_documents_before_accept_terms_rejected(api):
    """PRD section 3.2: "Documents are accepted only while the engagement is
    `ENGAGED` or `INFORMATION_GATHERING`; in any other state the submission
    fails with `ERR_ENGAGEMENT_STATE_INVALID`."

    Design: Corner/state_machines/documents_before_accept_terms_rejected
    """
    issuer = create_issuer(api)
    engagement = create_engagement_solicited(api, issuer)
    resp = api.submit_document(
        engagement["id"],
        {"document_code": DOC_AUDIT_FY},
        headers=issuer_headers(issuer),
    )
    validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_STATE_INVALID)
    engagement = get_engagement(api, engagement["id"])
    assert engagement["status"] == "REQUESTED"
    assert engagement["received_document_codes"] == []


def test_unknown_document_code_rejected(api):
    """PRD section 3.2: "A code outside this registry is rejected with
    `ERR_DOCUMENT_CODE_UNKNOWN`, and resubmitting a code already present in
    the engagement's `received_document_codes` is rejected with
    `ERR_DUPLICATE_DOCUMENT`."

    Design: Corner/validations/unknown_document_code_rejected
    """
    issuer = create_issuer(api)
    engagement = create_engagement_solicited(api, issuer)
    engagement = accept_terms(api, engagement, issuer)
    resp = api.submit_document(
        engagement["id"],
        {"document_code": "SHADOW_REPORT"},
        headers=issuer_headers(issuer),
    )
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_CODE_UNKNOWN)
    engagement = get_engagement(api, engagement["id"])
    assert engagement["status"] == "ENGAGED"
    assert engagement["received_document_codes"] == []


def test_duplicate_document_code_rejected(api):
    """PRD section 3.2: "A code outside this registry is rejected with
    `ERR_DOCUMENT_CODE_UNKNOWN`, and resubmitting a code already present in
    the engagement's `received_document_codes` is rejected with
    `ERR_DUPLICATE_DOCUMENT`."

    Design: Corner/validations/duplicate_document_code_rejected
    """
    issuer = create_issuer(api)
    engagement = create_engagement_solicited(api, issuer)
    engagement = accept_terms(api, engagement, issuer)
    submit_document(api, engagement["id"], DOC_AUDIT_FY, issuer_headers(issuer))
    resp = api.submit_document(
        engagement["id"],
        {"document_code": DOC_AUDIT_FY},
        headers=issuer_headers(issuer),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_DOCUMENT)
    engagement = get_engagement(api, engagement["id"])
    assert engagement["received_document_codes"].count(DOC_AUDIT_FY) == 1


def test_withdraw_unsolicited_rejected(api):
    """PRD section 3.1: "Withdrawal is never available on an unsolicited
    engagement, nor on any engagement once it reaches `RATING_ASSIGNED`; both
    attempts are rejected with `ERR_WITHDRAWAL_NOT_PERMITTED`, because from
    assignment onward the appeal process is the only pre-publication remedy."

    Design: Corner/state_machines/withdraw_unsolicited_rejected
    """
    issuer = create_issuer(api)
    engagement = create_engagement_unsolicited(api, issuer)
    resp = api.withdraw_engagement(
        engagement["id"], headers=issuer_headers(issuer)
    )
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_NOT_PERMITTED)
    engagement = get_engagement(api, engagement["id"])
    assert engagement["status"] == "INFORMATION_GATHERING"


def test_withdraw_after_rating_assigned_rejected(api):
    """PRD section 3.1: "Withdrawal is never available on an unsolicited
    engagement, nor on any engagement once it reaches `RATING_ASSIGNED`; both
    attempts are rejected with `ERR_WITHDRAWAL_NOT_PERMITTED`, because from
    assignment onward the appeal process is the only pre-publication remedy."

    Design: Corner/state_machines/withdraw_after_rating_assigned_rejected
    """
    ctx = setup_assigned_rating(api)
    resp = api.withdraw_engagement(
        ctx["engagement"]["id"], headers=issuer_headers(ctx["issuer"])
    )
    validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_NOT_PERMITTED)
    engagement = get_engagement(api, ctx["engagement"]["id"])
    assert engagement["status"] == "RATING_ASSIGNED"
    assert get_issuer(api, ctx["issuer"]["id"])["credit_balance_cents"] == 0, (
        "no refund fires on a rejected withdrawal"
    )


def test_withdraw_reengage_fee_credit_conservation(api):
    """PRD section 3.1: "From `ENGAGED`, `INFORMATION_GATHERING`, `ANALYSIS`,
    or `COMMITTEE_READY`, withdrawal refunds half the paid fee: `refund_cents`
    is `fee_cents` multiplied by the withdrawal refund ratio of 0.5, rounded
    half-up to whole cents, and the refund is credited to the issuer's
    `credit_balance_cents` for use against future engagement fees."
    PRD section 3.1: "The cash and the applied credit together must equal
    `fee_cents` exactly, or the attempt fails with `ERR_FEE_PAYMENT_MISMATCH`;
    the applied credit may not exceed the issuer's `credit_balance_cents`, or
    it fails with `ERR_INSUFFICIENT_ISSUER_CREDIT`."

    Design: Difficulty/compensating_invariant/withdraw_reengage_fee_credit_conservation
    """
    issuer = create_issuer(api)
    eng1 = create_engagement_solicited(api, issuer)
    accept_terms(api, eng1, issuer)  # full 4500000 cash, no credit

    resp = api.withdraw_engagement(eng1["id"], headers=issuer_headers(issuer))
    withdrawn = validate_success(resp, 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["refund_cents"] == 2250000, (
        "round_half_up(4500000 * 0.5) == 2250000"
    )
    midpoint = get_issuer(api, issuer["id"])
    assert midpoint["credit_balance_cents"] == 2250000, (
        "the refund moved retained fees into issuer credit"
    )

    eng2 = create_engagement_solicited(api, issuer)
    eng2 = accept_terms(
        api, eng2, issuer, fee_payment_cents=2250000, apply_credit_cents=2250000
    )
    assert eng2["status"] == "ENGAGED"
    assert eng2["fee_paid"] is True
    final = get_issuer(api, issuer["id"])
    assert final["credit_balance_cents"] == 0, (
        "the withdraw-then-reengage pair conserves the credit balance exactly"
    )
