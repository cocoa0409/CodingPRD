"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API —
the harness restarts the server before each test, so nothing may be carried
over. Setup calls use ``get_success_data()`` so a broken precondition raises
a clear "Setup step failed" error instead of a confusing assertion failure
further down.

Scenario context convention: composite helpers return a plain dict ("ctx")
that accumulates the artifacts they create. Keys:

    staff header sets : admin_headers, officer_headers, verifier_headers,
        milestone_verifier_headers (a DIFFERENT LossVerifier user, so the
        segregation-of-duties rule is satisfiable), approver_headers,
        servicing_headers, grant_coordinator_headers
    declaration       : the DisasterDeclaration dict
    applicant         : the Applicant dict
    applicant_headers : headers whose X-User-ID == applicant["id"]
    application       : the latest LoanApplication dict
    applications      : every application created through this ctx
    verification      : the latest DamageVerification dict (physical flows)
    loan              : the latest Loan dict (post-approval flows)
    tranches          : the latest tranche schedule list (stage_number ASC)
    receivables       : the latest excess-funds receivable list

Clock discipline: the logical clock starts at 2026-09-01T00:00:00Z; helpers
advance it explicitly through the clock endpoint (never wall-clock time).
Canonical intake instant is 2026-10-02T00:00:00Z; canonical loan acceptance
is 2026-11-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import (
    CANONICAL_COUNTY_BOTH,
    EIDL_COLLATERAL_THRESHOLD_CENTS,
    PHYSICAL_COLLATERAL_THRESHOLD_CENTS,
)
from .factories import (
    application_decision_payload,
    complete_verification_payload,
    create_applicant_payload,
    create_application_payload,
    create_declaration_payload,
    create_verification_payload,
    credit_review_payload,
    grant_award_payload,
    milestone_decision_payload,
    milestone_payload,
    modification_decision_payload,
    modification_request_payload,
    servicing_action_decision_payload,
    servicing_action_payload,
    settlement_payload,
    apply_settlement_payload,
    payment_payload,
)
from .test_users import (
    TEST_USERS,
    fresh_staff_headers,
    fresh_user_id,
    make_anonymous_headers,
    make_applicant_headers,
)

# Opaque staff identities for shared reads/writes that are not
# ownership-gated and not segregation-sensitive.
DEFAULT_ADMIN = TEST_USERS["system_admin_headers"]
DEFAULT_SERVICING = TEST_USERS["servicing_agent_headers"]

# Canonical logical-clock instants used by the fixture timeline.
CLOCK_INTAKE = "2026-10-02T00:00:00Z"
CLOCK_ACCEPT = "2026-11-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: clock + primitives
# ---------------------------------------------------------------------------

def set_clock(current_utc, headers=None):
    """Advance the logical clock (runs the full time-driven sweep)."""
    resp = api.set_clock(current_utc, headers or DEFAULT_ADMIN)
    return get_success_data(resp)


def new_context():
    """Base scenario dict with freshly minted, distinct staff identities."""
    ctx = fresh_staff_headers()
    ctx["applications"] = []
    return ctx


def register_applicant(applicant_type="HOMEOWNER",
                       annual_income_cents=12000000,
                       monthly_debt_cents=100000,
                       **overrides):
    """Self-register an applicant. Returns (applicant, applicant_headers)
    where the headers carry X-User-ID == applicant["id"] (ownership)."""
    payload = create_applicant_payload(
        applicant_type=applicant_type,
        annual_income_cents=annual_income_cents,
        monthly_debt_cents=monthly_debt_cents,
        **overrides,
    )
    resp = api.create_applicant(
        payload, make_anonymous_headers(fresh_user_id("anon-reg")))
    applicant = get_success_data(resp)
    return applicant, make_applicant_headers(applicant["id"])


def setup_declaration(ctx=None, clock=CLOCK_INTAKE, **payload_overrides):
    """Create the canonical declaration (DR-4821, counties 06037 + 06059).

    Sets the clock first, mirroring the canonical intake timeline. Returns
    the declaration dict; also stored on ctx when one is passed.
    """
    if ctx is None:
        ctx = new_context()
    set_clock(clock, ctx["admin_headers"])
    resp = api.create_declaration(
        create_declaration_payload(**payload_overrides), ctx["admin_headers"])
    declaration = get_success_data(resp)
    ctx["declaration"] = declaration
    return declaration


# ---------------------------------------------------------------------------
# Tier 1: application lifecycle chains
# ---------------------------------------------------------------------------

def create_draft(ctx, county_fips=CANONICAL_COUNTY_BOTH,
                 loan_purpose="PHYSICAL_DAMAGE",
                 requested_amount_cents=20000000,
                 applicant_headers=None):
    """Create a DRAFT application for ctx's applicant (or given headers)."""
    resp = api.create_application(
        create_application_payload(
            ctx["declaration"]["id"],
            county_fips=county_fips,
            loan_purpose=loan_purpose,
            requested_amount_cents=requested_amount_cents),
        applicant_headers or ctx["applicant_headers"])
    application = get_success_data(resp)
    ctx["application"] = application
    ctx.setdefault("applications", []).append(application)
    return application


def submit_draft(ctx, application_id=None, applicant_headers=None):
    """Submit a DRAFT application; returns the SUBMITTED application."""
    app_id = application_id or ctx["application"]["id"]
    resp = api.submit_application(
        app_id, applicant_headers or ctx["applicant_headers"])
    application = get_success_data(resp)
    ctx["application"] = application
    return application


def file_credit_review(ctx, credit_score=700,
                       verified_monthly_debt_cents=100000,
                       application_id=None, officer_headers=None):
    """File a credit review; returns the created CreditReview dict."""
    app_id = application_id or ctx["application"]["id"]
    resp = api.create_credit_review(
        app_id,
        credit_review_payload(credit_score=credit_score,
                              verified_monthly_debt_cents=verified_monthly_debt_cents),
        officer_headers or ctx["officer_headers"])
    review = get_success_data(resp)
    ctx["credit_review"] = review
    return review


def open_verification(ctx, method="INSPECTION",
                      valuation_basis="REPLACEMENT_COST",
                      depreciation_pct=None,
                      application_id=None, verifier_headers=None):
    """Open a damage verification on a VERIFICATION application."""
    app_id = application_id or ctx["application"]["id"]
    kwargs = {"method": method, "valuation_basis": valuation_basis}
    if depreciation_pct is not None:
        kwargs["depreciation_pct"] = depreciation_pct
    resp = api.create_damage_verification(
        app_id, create_verification_payload(**kwargs),
        verifier_headers or ctx["verifier_headers"])
    verification = get_success_data(resp)
    ctx["verification"] = verification
    return verification


def complete_verification(ctx, assessed_loss_cents=25000000,
                          insurance_proceeds_cents=5000000,
                          verification_id=None, verifier_headers=None,
                          at_clock=None):
    """Complete a verification (records figures; cascades the application
    to DECISION_PENDING on first completion). ``at_clock`` first moves the
    logical clock so completed_at lands on a chosen instant."""
    ver_id = verification_id or ctx["verification"]["id"]
    if at_clock is not None:
        set_clock(at_clock, ctx["admin_headers"])
    resp = api.complete_damage_verification(
        ver_id,
        complete_verification_payload(
            assessed_loss_cents=assessed_loss_cents,
            insurance_proceeds_cents=insurance_proceeds_cents),
        verifier_headers or ctx["verifier_headers"])
    verification = get_success_data(resp)
    ctx["verification"] = verification
    return verification


def dispute_verification(ctx, verification_id=None, applicant_headers=None):
    """Owning applicant disputes a COMPLETED verification."""
    ver_id = verification_id or ctx["verification"]["id"]
    resp = api.dispute_damage_verification(
        ver_id, applicant_headers or ctx["applicant_headers"])
    verification = get_success_data(resp)
    ctx["verification"] = verification
    return verification


def find_verification(ctx, verification_id):
    """Read one verification back via the application's list endpoint."""
    resp = api.list_damage_verifications(
        ctx["application"]["id"], ctx["officer_headers"])
    rows = get_success_data(resp)
    for row in rows:
        if row["id"] == verification_id:
            return row
    raise AssertionError(f"verification {verification_id} not found in list")


def report_grant(ctx, award_amount_cents, program_name=None,
                 purpose_category=None):
    """GrantCoordinator reports a grant on the application."""
    purpose = purpose_category or ctx["application"]["loan_purpose"]
    resp = api.create_grant_award(
        ctx["application"]["id"],
        grant_award_payload(
            program_name=program_name or "FEMA-OTG",
            award_amount_cents=award_amount_cents,
            purpose_category=purpose),
        ctx["grant_coordinator_headers"])
    return get_success_data(resp)


def decide_application(ctx, decision="APPROVED", with_collateral=None,
                       collateral_description=None,
                       collateral_value_cents=None,
                       application_id=None, approver_headers=None):
    """Render the application decision.

    with_collateral None = auto: collateral fields are included exactly when
    the requested amount strictly exceeds the purpose's collateral threshold
    (value defaults to the requested amount so value >= approved holds).
    Pass with_collateral=False to force omission (error-path tests).
    """
    app = ctx["application"]
    requested = app["requested_amount_cents"]
    if with_collateral is None:
        threshold = (EIDL_COLLATERAL_THRESHOLD_CENTS
                     if app["loan_purpose"] == "ECONOMIC_INJURY"
                     else PHYSICAL_COLLATERAL_THRESHOLD_CENTS)
        with_collateral = requested > threshold
    if with_collateral:
        collateral_description = collateral_description or "primary residence"
        if collateral_value_cents is None:
            collateral_value_cents = requested
    resp = api.decide_application(
        application_id or app["id"],
        application_decision_payload(
            decision=decision,
            collateral_description=collateral_description,
            collateral_value_cents=collateral_value_cents),
        approver_headers or ctx["approver_headers"])
    application = get_success_data(resp)
    ctx["application"] = application
    return application


# ---------------------------------------------------------------------------
# Tier 2: named pipeline stages
# ---------------------------------------------------------------------------

def setup_draft_application(_ctx=None, applicant_type="HOMEOWNER",
                            annual_income_cents=12000000,
                            monthly_debt_cents=100000,
                            county_fips=CANONICAL_COUNTY_BOTH,
                            loan_purpose="PHYSICAL_DAMAGE",
                            requested_amount_cents=20000000,
                            **applicant_overrides):
    """Declaration + applicant + DRAFT application. Returns ctx.

    Pass ``_ctx`` from an earlier composite to build a SECOND applicant/
    application on the SAME declaration (declaration_number is unique, so
    re-declaring DR-4821 in one test would fail). The fresh applicant's
    headers replace ctx["applicant_headers"]; capture any earlier loan/
    application ids into locals before the second pass.
    """
    ctx = _ctx if _ctx is not None else new_context()
    if "declaration" not in ctx:
        setup_declaration(ctx)
    applicant, headers = register_applicant(
        applicant_type=applicant_type,
        annual_income_cents=annual_income_cents,
        monthly_debt_cents=monthly_debt_cents,
        **applicant_overrides)
    ctx["applicant"] = applicant
    ctx["applicant_headers"] = headers
    create_draft(ctx, county_fips=county_fips, loan_purpose=loan_purpose,
                 requested_amount_cents=requested_amount_cents)
    return ctx


def setup_submitted_application(**kwargs):
    """... + submit. Returns ctx with the application in SUBMITTED."""
    ctx = setup_draft_application(**kwargs)
    submit_draft(ctx)
    return ctx


def setup_application_in_verification(credit_score=700,
                                      verified_monthly_debt_cents=100000,
                                      **kwargs):
    """... + credit PASS on a PHYSICAL_DAMAGE application -> VERIFICATION."""
    ctx = setup_submitted_application(**kwargs)
    file_credit_review(ctx, credit_score=credit_score,
                       verified_monthly_debt_cents=verified_monthly_debt_cents)
    return ctx


def setup_application_in_decision_pending(
        assessed_loss_cents=25000000, insurance_proceeds_cents=5000000,
        valuation_basis="REPLACEMENT_COST", depreciation_pct=None,
        method="INSPECTION", complete_clock=None,
        credit_score=700, verified_monthly_debt_cents=100000, **kwargs):
    """... up to DECISION_PENDING.

    PHYSICAL_DAMAGE: credit PASS -> VERIFICATION, then verification opened
    and completed. ECONOMIC_INJURY: credit PASS lands in DECISION_PENDING
    directly (no verification step exists).
    """
    ctx = setup_submitted_application(**kwargs)
    file_credit_review(ctx, credit_score=credit_score,
                       verified_monthly_debt_cents=verified_monthly_debt_cents)
    if ctx["application"]["loan_purpose"] != "ECONOMIC_INJURY":
        open_verification(ctx, method=method, valuation_basis=valuation_basis,
                          depreciation_pct=depreciation_pct)
        complete_verification(ctx,
                              assessed_loss_cents=assessed_loss_cents,
                              insurance_proceeds_cents=insurance_proceeds_cents,
                              at_clock=complete_clock)
    return ctx


def setup_declined_application(credit_score=639,
                               verified_monthly_debt_cents=100000, **kwargs):
    """... + a FAIL credit review -> DECLINED (default: score below 640)."""
    ctx = setup_submitted_application(**kwargs)
    file_credit_review(ctx, credit_score=credit_score,
                       verified_monthly_debt_cents=verified_monthly_debt_cents)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: loan origination and activation
# ---------------------------------------------------------------------------

def read_loan(ctx, loan_id=None, headers=None):
    """GET the loan; refreshes ctx['loan']. Returns the Loan dict."""
    lid = loan_id or ctx["loan"]["id"]
    resp = api.get_loan(lid, headers or ctx.get("servicing_headers",
                                                DEFAULT_SERVICING))
    loan = get_success_data(resp)
    ctx["loan"] = loan
    return loan


def loan_version(ctx):
    """Fresh loan version for OCC-guarded writes (refreshes ctx['loan'])."""
    return read_loan(ctx)["version"]


def list_tranche_data(ctx, loan_id=None, headers=None):
    """GET the tranche schedule (stage_number ASC); refreshes ctx['tranches']."""
    lid = loan_id or ctx["loan"]["id"]
    resp = api.list_tranches(lid, headers or ctx.get("servicing_headers",
                                                     DEFAULT_SERVICING))
    tranches = get_success_data(resp)
    ctx["tranches"] = tranches
    return tranches


def list_receivable_data(ctx, loan_id=None, headers=None):
    """GET excess-funds receivables; refreshes ctx['receivables']."""
    lid = loan_id or ctx["loan"]["id"]
    resp = api.list_excess_funds_receivables(
        lid, headers or ctx.get("servicing_headers", DEFAULT_SERVICING))
    receivables = get_success_data(resp)
    ctx["receivables"] = receivables
    return receivables


def setup_approved_loan(with_collateral=None,
                        collateral_description=None,
                        collateral_value_cents=None, **kwargs):
    """... + APPROVED decision. Returns ctx with loan + tranche schedule."""
    ctx = setup_application_in_decision_pending(**kwargs)
    decide_application(ctx, decision="APPROVED",
                       with_collateral=with_collateral,
                       collateral_description=collateral_description,
                       collateral_value_cents=collateral_value_cents)
    loan_id = ctx["application"]["loan_id"]
    ctx["loan"] = read_loan(ctx, loan_id=loan_id)
    list_tranche_data(ctx)
    return ctx


def accept_loan(ctx, at_clock=CLOCK_ACCEPT, applicant_headers=None):
    """Move the clock, then the owning applicant accepts the loan
    (PENDING_ACCEPTANCE -> ACTIVE; tranche stage 1 becomes ELIGIBLE)."""
    if at_clock is not None:
        set_clock(at_clock, ctx["admin_headers"])
    resp = api.accept_loan(ctx["loan"]["id"],
                           applicant_headers or ctx["applicant_headers"])
    get_success_data(resp)
    read_loan(ctx)
    list_tranche_data(ctx)
    return ctx["loan"]


def setup_active_loan(accept_clock=CLOCK_ACCEPT, **kwargs):
    """... + loan accepted and ACTIVE. Returns ctx."""
    ctx = setup_approved_loan(**kwargs)
    accept_loan(ctx, at_clock=accept_clock)
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: disbursement, milestones, modifications
# ---------------------------------------------------------------------------

def release_stage(ctx, stage_index=0):
    """Release ctx['tranches'][stage_index] (must be ELIGIBLE); refreshes
    loan + schedule. Returns the released tranche."""
    tranche = ctx["tranches"][stage_index]
    resp = api.release_tranche(tranche["id"],
                               ctx.get("servicing_headers", DEFAULT_SERVICING))
    released = get_success_data(resp)
    read_loan(ctx)
    list_tranche_data(ctx)
    return released


def verify_milestone(ctx, claimed_cost_cents, verified_cost_cents=None,
                     description="roof replaced", decision="VERIFIED",
                     verifier_headers=None):
    """Borrower reports a milestone; a LossVerifier OTHER than the damage
    verifier of record decides it. Returns the decided milestone."""
    if verified_cost_cents is None:
        verified_cost_cents = claimed_cost_cents
    resp = api.create_milestone(
        ctx["loan"]["id"],
        milestone_payload(description=description,
                          claimed_cost_cents=claimed_cost_cents),
        ctx["applicant_headers"])
    milestone = get_success_data(resp)
    resp = api.decide_milestone(
        milestone["id"],
        milestone_decision_payload(decision=decision,
                                   verified_cost_cents=verified_cost_cents),
        verifier_headers or ctx["milestone_verifier_headers"])
    decided = get_success_data(resp)
    list_tranche_data(ctx)
    return decided


def setup_loan_with_t1_released(**kwargs):
    """ACTIVE loan with tranche stage 1 RELEASED. Returns ctx."""
    ctx = setup_active_loan(**kwargs)
    release_stage(ctx, 0)
    return ctx


def setup_loan_with_t1_t2_released(verified_milestone_cents=2500000,
                                   at_clock=None, **kwargs):
    """ACTIVE loan with T1 and T2 RELEASED: a milestone verified at
    ``verified_milestone_cents`` (default == stage-1 amount, the boundary
    that flips stage 2 to ELIGIBLE) sits between the two releases.
    ``at_clock`` optionally moves the clock before the T2 release."""
    ctx = setup_loan_with_t1_released(**kwargs)
    verify_milestone(ctx, claimed_cost_cents=verified_milestone_cents)
    if at_clock is not None:
        set_clock(at_clock, ctx["admin_headers"])
    release_stage(ctx, 1)
    return ctx


def create_modification(ctx, requested_amount_cents, reason=None):
    """OCC-compliant modification create: reads the fresh loan version
    first. Refreshes ctx['loan'] (the create bumps loan.version)."""
    version = loan_version(ctx)
    resp = api.create_modification_request(
        ctx["loan"]["id"],
        modification_request_payload(
            requested_amount_cents=requested_amount_cents,
            expected_loan_version=version, reason=reason),
        ctx["applicant_headers"])
    modification = get_success_data(resp)
    read_loan(ctx)
    return modification


def decide_modification(ctx, modification_id, decision="APPROVED"):
    """LoanApprover decides a modification; refreshes the loan."""
    resp = api.decide_modification_request(
        modification_id, modification_decision_payload(decision=decision),
        ctx["approver_headers"])
    modification = get_success_data(resp)
    read_loan(ctx)
    list_tranche_data(ctx)
    return modification


# ---------------------------------------------------------------------------
# Tier 5: settlements, receivables, servicing actions, payments
# ---------------------------------------------------------------------------

def report_settlement(ctx, settlement_amount_cents,
                      received_date="2026-12-15T00:00:00Z"):
    """Borrower reports a post-disbursement insurance settlement."""
    resp = api.create_insurance_settlement(
        ctx["loan"]["id"],
        settlement_payload(settlement_amount_cents=settlement_amount_cents,
                           received_date=received_date),
        ctx["applicant_headers"])
    settlement = get_success_data(resp)
    ctx["settlement"] = settlement
    return settlement


def apply_settlement(ctx, settlement_id=None, at_clock=None):
    """OCC-compliant settlement apply: optional clock move, fresh loan
    version, apply. Refreshes loan, tranches, receivables. Returns the
    APPLIED settlement."""
    sid = settlement_id or ctx["settlement"]["id"]
    if at_clock is not None:
        set_clock(at_clock, ctx["admin_headers"])
    version = loan_version(ctx)
    resp = api.apply_insurance_settlement(
        sid, apply_settlement_payload(expected_loan_version=version),
        ctx.get("servicing_headers", DEFAULT_SERVICING))
    settlement = get_success_data(resp)
    ctx["settlement"] = settlement
    read_loan(ctx)
    list_tranche_data(ctx)
    list_receivable_data(ctx)
    return settlement


def void_settlement(ctx, settlement_id=None):
    """Void an APPLIED settlement (compensates the cascade). Refreshes
    loan, tranches, receivables."""
    sid = settlement_id or ctx["settlement"]["id"]
    resp = api.void_insurance_settlement(
        sid, ctx.get("servicing_headers", DEFAULT_SERVICING))
    settlement = get_success_data(resp)
    ctx["settlement"] = settlement
    read_loan(ctx)
    list_tranche_data(ctx)
    list_receivable_data(ctx)
    return settlement


def setup_loan_with_applied_settlement(settlement_amount_cents=12000000,
                                       apply_clock="2026-12-15T00:00:00Z",
                                       received_date="2026-12-15T00:00:00Z",
                                       **kwargs):
    """ACTIVE loan with T1 released + one settlement reported and APPLIED.
    Returns ctx with settlement, refreshed loan/tranches/receivables."""
    ctx = setup_loan_with_t1_released(**kwargs)
    report_settlement(ctx, settlement_amount_cents,
                      received_date=received_date)
    apply_settlement(ctx, at_clock=apply_clock)
    return ctx


def pay_receivable(ctx, amount_cents, receivable_id=None,
                   applicant_headers=None):
    """Borrower pays down the excess-funds receivable; refreshes both."""
    rid = receivable_id or ctx["receivables"][0]["id"]
    resp = api.pay_excess_funds_receivable(
        rid, {"amount_cents": amount_cents},
        applicant_headers or ctx["applicant_headers"])
    receivable = get_success_data(resp)
    read_loan(ctx)
    list_receivable_data(ctx)
    return receivable


def request_servicing_action(ctx, action_type="DEFERMENT",
                             start_date="2027-01-01T00:00:00Z",
                             end_date="2027-03-01T00:00:00Z"):
    """Borrower requests a deferment/hardship half-open window."""
    resp = api.create_servicing_action(
        ctx["loan"]["id"],
        servicing_action_payload(action_type=action_type,
                                 start_date=start_date, end_date=end_date),
        ctx["applicant_headers"])
    action = get_success_data(resp)
    ctx["servicing_action"] = action
    return action


def decide_servicing_action(ctx, action_id=None, decision="APPROVED"):
    """ServicingAgent decides a REQUESTED action; refreshes the loan."""
    aid = action_id or ctx["servicing_action"]["id"]
    resp = api.decide_servicing_action(
        aid, servicing_action_decision_payload(decision=decision),
        ctx.get("servicing_headers", DEFAULT_SERVICING))
    action = get_success_data(resp)
    ctx["servicing_action"] = action
    read_loan(ctx)
    return action


def post_payment(ctx, amount_cents, applicant_headers=None):
    """Borrower posts a loan payment (fees -> interest -> principal
    waterfall). Refreshes the loan. Returns the POSTED Payment dict."""
    resp = api.create_payment(ctx["loan"]["id"], payment_payload(amount_cents),
                              applicant_headers or ctx["applicant_headers"])
    payment = get_success_data(resp)
    ctx["payment"] = payment
    read_loan(ctx)
    return payment


def reverse_payment(ctx, payment_id=None):
    """ServicingAgent reverses a POSTED payment; refreshes the loan."""
    pid = payment_id or ctx["payment"]["id"]
    resp = api.reverse_payment(
        pid, ctx.get("servicing_headers", DEFAULT_SERVICING))
    payment = get_success_data(resp)
    ctx["payment"] = payment
    read_loan(ctx)
    return payment
