"""Corner queue: errors — exact error_id boundary behavior for payments,
county eligibility, filing deadlines, modification caps, and settlement void."""
from test_helpers import (
    CANONICAL_COUNTY_BOTH,
    CANONICAL_COUNTY_EIDL_ONLY,
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    create_draft,
    create_modification,
    modification_decision_payload,
    payment_payload,
    read_loan,
    report_settlement,
    set_clock,
    setup_active_loan,
    setup_draft_application,
    setup_loan_with_t1_released,
    validate_error,
    validate_success,
)


def test_payment_exact_payoff_allowed_one_cent_over_rejected(api):
    """PRD §3.9: "The `amount_cents` must be positive and no greater than the sum of `late_fee_balance_cents`, the interest due at posting, and `outstanding_balance_cents`; an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE` (HTTP 422), while an amount exactly equal to that sum is an allowed exact payoff."
    PRD §3.9: "If the principal portion drives `outstanding_balance_cents` to exactly zero, the loan's `lifecycle_status` becomes `PAID_IN_FULL`, which is terminal."
    PRD §3.9: "The borrower services the loan with payments against an `ACTIVE` loan (a payment against any other lifecycle status — including `CHARGED_OFF` — is rejected with `ERR_LOAN_NOT_ACTIVE`)."

    Design: Corner/errors/payment_exact_payoff_allowed_one_cent_over_rejected
    """
    ctx = setup_loan_with_t1_released()  # T1 2500000 released 2026-11-01
    loan_id = ctx["loan"]["id"]
    # At 2026-12-01 the interest due is round_half_up(2500000 * 0.03125 * 30
    # / 365) = 6421; fees 0; outstanding 2500000 -> chargeable total 2506421.
    set_clock("2026-12-01T00:00:00Z", ctx["admin_headers"])

    resp = api.create_payment(
        loan_id, payment_payload(2506422), ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)
    rows = validate_success(
        api.list_payments(loan_id, ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["list_payments"])
    assert rows == []

    # Exact payoff: 6421 interest + 2500000 principal.
    resp = api.create_payment(
        loan_id, payment_payload(2506421), ctx["applicant_headers"])
    payment = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_payment"])
    assert payment["fee_portion_cents"] == 0
    assert payment["interest_portion_cents"] == 6421
    assert payment["principal_portion_cents"] == 2500000

    loan = read_loan(ctx)
    assert loan["lifecycle_status"] == "PAID_IN_FULL"
    assert loan["outstanding_balance_cents"] == 0

    # Terminal: no further payments.
    resp = api.create_payment(
        loan_id, payment_payload(100), ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_ACTIVE)


def test_physical_submit_to_eidl_only_county_rejected(api):
    """PRD §3.2: "Only after the deadline checks does county eligibility run: the application's `county_fips` must appear in the declaration's `counties` with the application's `loan_purpose` among that county's `eligible_purposes`, else the submission is rejected with `ERR_COUNTY_NOT_ELIGIBLE` (HTTP 422)."

    Design: Corner/errors/physical_submit_to_eidl_only_county_rejected
    """
    # County 06059 is declared ECONOMIC_INJURY-only; clock 2026-10-02 leaves
    # both filing deadlines open, so eligibility is the only failing gate.
    ctx = setup_draft_application(
        county_fips=CANONICAL_COUNTY_EIDL_ONLY,
        loan_purpose="PHYSICAL_DAMAGE",
        requested_amount_cents=2500000)
    app_physical_id = ctx["application"]["id"]
    app_eidl = create_draft(
        ctx, county_fips=CANONICAL_COUNTY_EIDL_ONLY,
        loan_purpose="ECONOMIC_INJURY", requested_amount_cents=2500000)

    resp = api.submit_application(app_physical_id, ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_COUNTY_NOT_ELIGIBLE)
    application = validate_success(
        api.get_application(app_physical_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DRAFT"

    resp = api.submit_application(app_eidl["id"], ctx["applicant_headers"])
    submitted = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["submit_application"])
    assert submitted["status"] == "SUBMITTED"


def test_submit_after_fully_closed_declaration_rejected(api):
    """PRD §3.2: "Then the purpose-specific deadline applies: a `PHYSICAL_DAMAGE` submission with the current instant strictly after the declaration's `physical_filing_deadline` is rejected with `ERR_PHYSICAL_FILING_CLOSED` (HTTP 422), and an `ECONOMIC_INJURY` submission strictly after the `economic_injury_filing_deadline` is rejected with `ERR_EIDL_FILING_CLOSED` (HTTP 422) — both deadlines inclusive of their exact instant."
    PRD §2.4: "`FULLY_CLOSED` once the current instant is strictly after `economic_injury_filing_deadline`."

    Design: Corner/errors/submit_after_fully_closed_declaration_rejected
    """
    ctx = setup_draft_application(
        county_fips=CANONICAL_COUNTY_BOTH,
        loan_purpose="PHYSICAL_DAMAGE",
        requested_amount_cents=2500000)
    app_physical_id = ctx["application"]["id"]
    app_eidl = create_draft(
        ctx, county_fips=CANONICAL_COUNTY_EIDL_ONLY,
        loan_purpose="ECONOMIC_INJURY", requested_amount_cents=2500000)

    # Past the EIDL deadline 2027-06-28 (and the physical one 2026-12-30).
    set_clock("2027-06-29T00:00:00Z", ctx["admin_headers"])

    resp = api.submit_application(app_eidl["id"], ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_EIDL_FILING_CLOSED)
    # Each purpose reports its own deadline error.
    resp = api.submit_application(app_physical_id, ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_PHYSICAL_FILING_CLOSED)


def test_modification_over_applicant_cap_rejected(api):
    """PRD §3.8: "A decision of `APPROVED` first checks the new total against the same statutory cap used at origination — 50000000, 10000000, or 200000000 cents by applicant type for physical loans, 200000000 cents for economic injury — and rejects an over-cap request with `ERR_MODIFICATION_EXCEEDS_CAP` (HTTP 422)."
    PRD §3.6: "Step one takes the statutory cap for the applicant type crossed with purpose: 50000000 cents ($500,000) for a `HOMEOWNER` physical loan, 10000000 cents ($100,000) for a `RENTER` physical loan, 200000000 cents ($2,000,000) for a `BUSINESS` physical loan, and 200000000 cents for any `ECONOMIC_INJURY` loan regardless of applicant type."

    Design: Corner/errors/modification_over_applicant_cap_rejected
    """
    ctx = setup_active_loan()  # HOMEOWNER physical, approved 20000000
    loan_id = ctx["loan"]["id"]
    # Create checks only freshness and shape; 60000000 differs from 20000000.
    modification = create_modification(ctx, 60000000)
    assert modification["status"] == "SUBMITTED"

    resp = api.decide_modification_request(
        modification["id"], modification_decision_payload("APPROVED"),
        ctx["approver_headers"])
    validate_error(resp, ApiErrorId.ERR_MODIFICATION_EXCEEDS_CAP)

    rows = validate_success(
        api.list_modification_requests(loan_id, ctx["approver_headers"]),
        EXPECTED_SUCCESS_STATUS["list_modification_requests"])
    assert rows[0]["id"] == modification["id"]
    assert rows[0]["status"] == "SUBMITTED"
    assert read_loan(ctx)["approved_amount_cents"] == 20000000


def test_settlement_void_on_reported_rejected(api):
    """PRD §3.8: "An apply can be undone: a `ServicingAgent` voids a settlement that is `APPLIED` (else `ERR_SETTLEMENT_NOT_APPLIED`)."
    PRD §3.8: "The borrower reports a settlement on an `ACTIVE` loan (else `ERR_LOAN_NOT_ACTIVE`) with a `settlement_amount_cents` strictly greater than zero and the `received_date`; the report sits in `REPORTED`."

    Design: Corner/errors/settlement_void_on_reported_rejected
    """
    ctx = setup_active_loan()
    loan_id = ctx["loan"]["id"]
    settlement = report_settlement(
        ctx, 1000000, received_date="2026-11-10T00:00:00Z")
    assert settlement["status"] == "REPORTED"

    # Void without a forward apply: rejected, commitment untouched.
    resp = api.void_insurance_settlement(
        settlement["id"], ctx["servicing_headers"])
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_APPLIED)

    rows = validate_success(
        api.list_insurance_settlements(loan_id, ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["list_insurance_settlements"])
    assert rows[0]["status"] == "REPORTED"
    assert read_loan(ctx)["commitment_amount_cents"] == 20000000
