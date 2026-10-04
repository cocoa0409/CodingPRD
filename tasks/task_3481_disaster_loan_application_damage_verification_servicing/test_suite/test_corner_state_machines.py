"""Corner queue: state_machines — invalid transitions, terminal/branch
behavior, and side-effect execution on the application, verification, loan,
receivable, modification, and servicing-action machines."""
from test_helpers import (
    CANONICAL_COUNTY_EIDL_ONLY,
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    complete_verification,
    create_modification,
    create_verification_payload,
    decide_application,
    decide_modification,
    dispute_verification,
    file_credit_review,
    list_receivable_data,
    list_tranche_data,
    loan_version,
    modification_request_payload,
    read_loan,
    receivable_payment_payload,
    request_servicing_action,
    servicing_action_decision_payload,
    set_clock,
    setup_active_loan,
    setup_application_in_decision_pending,
    setup_loan_with_applied_settlement,
    setup_loan_with_t1_released,
    setup_submitted_application,
    validate_error,
    validate_success,
)


def test_resubmit_returns_application_not_draft(api):
    """PRD §3.2: "The application must still be in `DRAFT`, else `ERR_APPLICATION_NOT_DRAFT` (HTTP 409)."
    PRD §3.2: "A successful submission stamps `submitted_at` with the current logical instant and moves the application to `SUBMITTED`."

    Design: Corner/state_machines/resubmit_returns_application_not_draft
    """
    ctx = setup_submitted_application(requested_amount_cents=2500000)
    app_id = ctx["application"]["id"]

    resp = api.submit_application(app_id, ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_DRAFT)

    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "SUBMITTED"
    assert application["reconsideration_count"] == 0


def test_eidl_application_skips_verification_entirely(api):
    """PRD §3.3: "A `PASS` on an `ECONOMIC_INJURY` application moves it directly to `DECISION_PENDING` — economic-injury files skip damage verification entirely."
    PRD §3.4: "Opening one against an application in any other status is rejected with `ERR_APPLICATION_NOT_IN_VERIFICATION`, and opening one against an `ECONOMIC_INJURY` application is rejected with `ERR_VERIFICATION_NOT_APPLICABLE` (HTTP 409) — economic-injury files have no physical verification step."
    PRD §2.8: "Every `ECONOMIC_INJURY` loan, regardless of applicant type, pays an annual rate of 0.04 over 360 months."
    PRD §3.6: "At or below the threshold, `collateral_required` is false and the collateral fields are absent."

    Design: Corner/state_machines/eidl_application_skips_verification_entirely
    """
    ctx = setup_submitted_application(
        applicant_type="BUSINESS",
        annual_income_cents=6000000,
        monthly_debt_cents=100000,
        county_fips=CANONICAL_COUNTY_EIDL_ONLY,
        loan_purpose="ECONOMIC_INJURY",
        requested_amount_cents=5000000)
    app_id = ctx["application"]["id"]

    review = file_credit_review(
        ctx, credit_score=700, verified_monthly_debt_cents=100000)
    # STANDARD amortized payment on 5000000 at (0.04/12) over 360 months,
    # rounded half-up at the final step -> 23871.
    assert review["verdict"] == "PASS"
    assert review["proposed_payment_cents"] == 23871
    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DECISION_PENDING"

    # No verification may be opened on an economic-injury file.
    resp = api.create_damage_verification(
        app_id, create_verification_payload(), ctx["verifier_headers"])
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_NOT_APPLICABLE)

    # 5000000 is not strictly greater than the 5000000 EIDL collateral
    # threshold, so the approval needs no collateral fields.
    decide_application(ctx, decision="APPROVED", with_collateral=False)
    loan = read_loan(ctx, loan_id=ctx["application"]["loan_id"])
    assert loan["approved_amount_cents"] == 5000000
    assert loan["interest_rate"] == 0.04
    assert loan["term_months"] == 360
    assert loan["collateral_required"] is False
    # T1 = min(2500000, 5000000) = 2500000; remainder 2500000 splits into
    # floor(2500000/2) = 1250000 and the rest 1250000.
    tranches = list_tranche_data(ctx)
    assert [t["amount_cents"] for t in tranches] == [2500000, 1250000, 1250000]


def test_dispute_recomplete_cycle_recomputes_loss(api):
    """PRD §3.4: "The `net_verified_loss_cents` is then the verified loss minus `insurance_proceeds_cents`, floored at zero; this is the duplication-of-benefits deduction."
    PRD §3.4: "A completion that resolves a `DISPUTED` verification re-records and recomputes the figures and refreshes `completed_at`, but the linked application is already in `DECISION_PENDING` and stays there with its version unchanged."

    Design: Corner/state_machines/dispute_recomplete_cycle_recomputes_loss
    """
    ctx = setup_application_in_decision_pending(
        requested_amount_cents=12000000,
        assessed_loss_cents=10000000,
        insurance_proceeds_cents=2000000,
        complete_clock="2026-11-20T00:00:00Z")
    # First completion: net = 10000000 - 2000000 = 8000000.
    assert ctx["verification"]["net_verified_loss_cents"] == 8000000
    app_id = ctx["application"]["id"]
    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DECISION_PENDING"

    disputed = dispute_verification(ctx)
    assert disputed["status"] == "DISPUTED"

    recompleted = complete_verification(
        ctx, assessed_loss_cents=12000000, insurance_proceeds_cents=2000000)
    # Recomputed from the new figures: net = 12000000 - 2000000 = 10000000.
    assert recompleted["verified_loss_cents"] == 12000000
    assert recompleted["net_verified_loss_cents"] == 10000000

    # The re-completion does not re-fire the advance transition.
    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DECISION_PENDING"


def test_dispute_window_inclusive_boundary(api):
    """PRD §3.4: "Dispute requires ownership (else `ERR_FORBIDDEN_OWNER`), a verification currently `COMPLETED` (else `ERR_VERIFICATION_NOT_DISPUTABLE`), a filing no later than 30 days after `completed_at` — the thirtieth day itself is admissible, and anything later is rejected with `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 422) — and a linked application that has not yet been `APPROVED`; once the application is approved the verification is frozen, dispute is rejected with `ERR_VERIFICATION_NOT_DISPUTABLE`, and post-approval loss changes flow through modification requests and insurance settlements instead."
    PRD §3.4: "The borrower may contest the figures: the owning `Applicant` disputes a verification, moving it from `COMPLETED` to `DISPUTED`."

    Design: Corner/state_machines/dispute_window_inclusive_boundary
    """
    ctx = setup_application_in_decision_pending(
        requested_amount_cents=2500000,
        assessed_loss_cents=2500000,
        insurance_proceeds_cents=0,
        complete_clock="2026-11-20T00:00:00Z")
    v1_id = ctx["verification"]["id"]
    h1_headers = ctx["applicant_headers"]
    ctx = setup_application_in_decision_pending(
        _ctx=ctx,
        requested_amount_cents=2500000,
        assessed_loss_cents=2500000,
        insurance_proceeds_cents=0,
        complete_clock="2026-11-20T00:00:00Z")
    v2_id = ctx["verification"]["id"]
    app2_id = ctx["application"]["id"]

    # Both verifications completed 2026-11-20; the 30th day (2026-12-20) is
    # admissible, one second later is not.
    set_clock("2026-12-20T00:00:00Z", ctx["admin_headers"])
    resp = api.dispute_damage_verification(v1_id, h1_headers)
    disputed = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["dispute_damage_verification"])
    assert disputed["status"] == "DISPUTED"

    set_clock("2026-12-20T00:00:01Z", ctx["admin_headers"])
    resp = api.dispute_damage_verification(v2_id, ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED)
    rows = validate_success(
        api.list_damage_verifications(app2_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["list_damage_verifications"])
    v2 = [row for row in rows if row["id"] == v2_id][0]
    assert v2["status"] == "COMPLETED"


def test_accept_twice_returns_loan_not_pending_acceptance(api):
    """PRD §3.7: "An approved loan is not yet live. The owning `Applicant` accepts it, moving `lifecycle_status` from `PENDING_ACCEPTANCE` to `ACTIVE` — an accept against a loan in any other lifecycle status is rejected with `ERR_LOAN_NOT_PENDING_ACCEPTANCE`, and ownership is enforced as `ERR_FORBIDDEN_OWNER`."
    PRD §3.7: "Acceptance cascades: tranche stage 1 flips from `SCHEDULED` to `ELIGIBLE`, though its money still moves only through an explicit release."

    Design: Corner/state_machines/accept_twice_returns_loan_not_pending_acceptance
    """
    ctx = setup_active_loan()  # accepted at 2026-11-01; stage 1 ELIGIBLE

    resp = api.accept_loan(ctx["loan"]["id"], ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_LOAN_NOT_PENDING_ACCEPTANCE)

    # The first accept's cascade is not re-fired: stage 1 still ELIGIBLE,
    # later stages untouched.
    tranches = list_tranche_data(ctx)
    assert tranches[0]["status"] == "ELIGIBLE"
    assert [t["status"] for t in tranches[1:]] == ["SCHEDULED", "SCHEDULED"]


def test_receivable_escalates_when_loan_defaults(api):
    """PRD §3.9: "Status boundaries are inclusive at every rung: at 30 or more days past due a `CURRENT` loan becomes `DELINQUENT`; at 120 or more a `DELINQUENT` loan becomes `DEFAULT`; at 180 or more a loan in `DEFAULT` is charged off, moving `lifecycle_status` to `CHARGED_OFF`, which is terminal and accepts no further payments (`ERR_LOAN_NOT_ACTIVE`)."
    PRD §3.9: "the `DEFAULT` transition carries two cascades of its own: any `OPEN` or `PARTIALLY_PAID` excess-funds receivable on the loan becomes `ESCALATED`, and every `REQUESTED` servicing action on the loan becomes `DENIED`."
    PRD §3.8: "an overpayment is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`, and a payment against a receivable in `PAID` or `ESCALATED` is rejected with `ERR_RECEIVABLE_NOT_OPEN` (both HTTP 422 and 409 respectively)."

    Design: Corner/state_machines/receivable_escalates_when_loan_defaults
    """
    ctx = setup_loan_with_applied_settlement(settlement_amount_cents=24000000)
    # Clawback: total insurance 5000000 (verification) + 24000000 = 29000000;
    # new net = max(0, 25000000 - 29000000) = 0; commitment = min(20000000, 0)
    # = 0; excess = disbursed 2500000 - 0 = 2500000.
    receivable = ctx["receivables"][0]
    assert receivable["amount_due_cents"] == 2500000
    assert receivable["status"] == "OPEN"

    # next_due 2027-12-01 (released 2026-11-01 + 13 months); the sweep to
    # 2028-03-30 lands exactly 120 days past due -> DEFAULT (inclusive).
    set_clock("2028-03-30T00:00:00Z", ctx["admin_headers"])
    loan = read_loan(ctx)
    assert loan["days_past_due"] == 120
    assert loan["servicing_status"] == "DEFAULT"

    escalated = list_receivable_data(ctx)[0]
    assert escalated["status"] == "ESCALATED"

    resp = api.pay_excess_funds_receivable(
        receivable["id"], receivable_payment_payload(100),
        ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_RECEIVABLE_NOT_OPEN)


def test_modification_increase_appends_delta_stage(api):
    """PRD §3.8: "On approval the loan's `approved_amount_cents` becomes the requested amount and the delta drives the schedule. When the new amount is larger, `commitment_amount_cents` grows by the delta, a new tranche carrying exactly the delta is appended at the next `stage_number` in `SCHEDULED` status, and `monthly_payment_cents` is recomputed with the deferred-capitalized variant on the new approved amount."
    PRD §3.6: "Hop two spawns the disbursement schedule: tranche stage 1 is the smaller of 2500000 cents and the approved amount, and any remainder is split into stage 2 taking the floor of half the remainder and stage 3 taking the rest; a tranche whose computed amount would be zero is not created."

    Design: Corner/state_machines/modification_increase_appends_delta_stage
    """
    ctx = setup_active_loan()  # approved 20000000, ACTIVE, nothing released
    modification = create_modification(ctx, 26000000)
    assert modification["status"] == "SUBMITTED"

    decided = decide_modification(ctx, modification["id"], "APPROVED")
    assert decided["status"] == "APPROVED"

    loan = ctx["loan"]  # refreshed by decide_modification
    assert loan["approved_amount_cents"] == 26000000
    assert loan["commitment_amount_cents"] == 26000000  # delta +6000000
    # DEFERRED_CAPITALIZED on the new amount: 26000000 * (1 + 0.03125) =
    # 26812500, amortized at (0.03125/12) over 360 -> 114858.
    assert loan["monthly_payment_cents"] == 114858

    tranches = ctx["tranches"]
    assert [t["stage_number"] for t in tranches] == [1, 2, 3, 4]
    assert [t["amount_cents"] for t in tranches] == [
        2500000, 8750000, 8750000, 6000000]
    assert tranches[0]["status"] == "ELIGIBLE"  # flipped at acceptance only
    assert tranches[3]["status"] == "SCHEDULED"


def test_modification_supersede_auto_denies_predecessor(api):
    """PRD §3.8: "Creating it bumps the loan's `version` by 1, and if a predecessor request on the same loan is still `SUBMITTED` the newer create supersedes it: the predecessor is moved to `DENIED` automatically, with no deciding officer recorded."
    PRD §4: "List modification requests on a loan; ordered by `created_at` ascending."

    Design: Corner/state_machines/modification_supersede_auto_denies_predecessor
    """
    ctx = setup_active_loan()
    v1 = loan_version(ctx)
    resp = api.create_modification_request(
        ctx["loan"]["id"],
        modification_request_payload(26000000, v1, reason="first"),
        ctx["applicant_headers"])
    m1 = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_modification_request"])

    # The first create bumped loan.version, so the second create must carry
    # the freshly read version.
    v2 = loan_version(ctx)
    assert v2 == v1 + 1
    resp = api.create_modification_request(
        ctx["loan"]["id"],
        modification_request_payload(28000000, v2, reason="second"),
        ctx["applicant_headers"])
    m2 = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_modification_request"])

    rows = validate_success(
        api.list_modification_requests(ctx["loan"]["id"],
                                       ctx["approver_headers"]),
        EXPECTED_SUCCESS_STATUS["list_modification_requests"])
    assert len(rows) == 2
    by_id = {row["id"]: row for row in rows}
    assert by_id[m1["id"]]["status"] == "DENIED"      # superseded
    assert by_id[m2["id"]]["status"] == "SUBMITTED"
    # List is ordered by created_at ascending.
    assert rows[0]["created_at"] <= rows[1]["created_at"]


def test_servicing_approval_on_default_loan_rejected(api):
    """PRD §3.9: "Separately, an accommodation cannot be approved while the loan's `servicing_status` is `DEFAULT`, which is rejected with `ERR_ACCOMMODATION_NOT_ALLOWED` (HTTP 409)."
    PRD §3.9: "The owning `Applicant` requests a servicing action on an `ACTIVE` loan with an `action_type` of `DEFERMENT` or `HARDSHIP`"

    Design: Corner/state_machines/servicing_approval_on_default_loan_rejected
    """
    ctx = setup_loan_with_t1_released()  # T1 released 2026-11-01
    # Sweep to exactly 120 days past the 2027-12-01 due date -> DEFAULT.
    set_clock("2028-03-30T00:00:00Z", ctx["admin_headers"])
    loan = read_loan(ctx)
    assert loan["servicing_status"] == "DEFAULT"

    # The request itself is still admitted (lifecycle is ACTIVE).
    action = request_servicing_action(
        ctx, action_type="HARDSHIP",
        start_date="2028-04-01T00:00:00Z", end_date="2028-07-01T00:00:00Z")
    assert action["status"] == "REQUESTED"

    resp = api.decide_servicing_action(
        action["id"], servicing_action_decision_payload("APPROVED"),
        ctx["servicing_headers"])
    validate_error(resp, ApiErrorId.ERR_ACCOMMODATION_NOT_ALLOWED)

    rows = validate_success(
        api.list_servicing_actions(ctx["loan"]["id"], ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["list_servicing_actions"])
    action_row = [row for row in rows if row["id"] == action["id"]][0]
    assert action_row["status"] == "REQUESTED"
