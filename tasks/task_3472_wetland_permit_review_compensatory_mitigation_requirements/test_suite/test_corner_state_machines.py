"""Corner queue — state machine edges (PRD §3.1-§3.9, §2.5).

Invalid transitions, terminal-state lockdowns, the permit-expiry cascade
that defaults the active plan, and resubmission of a JD-suspended
application with a replacement determination.
"""
import pytest

from test_helpers import (
    AppealOutcome,
    ApiErrorId,
    ApplicationStatus,
    CaseStatus,
    JdStatus,
    Mechanism,
    PermitStatus,
    PlanStatus,
    assert_iso_instants_equal,
    commence_permit,
    confirm_case,
    create_aa,
    create_and_issue_jd,
    create_application,
    create_plan,
    decide_appeal,
    file_appeal,
    get_cases_for_applicant,
    iso_add_days,
    make_applicant_headers,
    purchase_credits,
    render_decision_payload,
    reserve_credits,
    review_aa,
    review_plan,
    review_report_payload,
    set_clock,
    setup_active_permit,
    setup_application_in_alternatives_review,
    setup_aa_accepted,
    setup_atf_application_linked,
    setup_case_opened,
    setup_issued_permit,
    setup_site_with_issued_jd,
    setup_suspended_application,
    setup_operational_bank,
    submit_and_screen_begin,
    submit_application,
    submit_plan,
    validate_error,
    validate_success,
)


def test_corner_jd_double_issue_rejected(api, district_engineer_headers):
    """PRD §3.1: "Operating on a determination in the wrong state — issuing
    one that is not `DRAFT`, or appealing or submitting against one that is
    not `ISSUED` — is rejected with `ERR_JD_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_jd_double_issue_rejected
    """
    _, _, jd = setup_site_with_issued_jd()
    resp = api.issue_jd(jd["id"], district_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_JD_INVALID_STATE)


def test_corner_jd_reversed_terminal_lockdown(api, district_engineer_headers, reviewer_headers):
    """PRD §3.1: "The determination's terminal state is `REVERSED`, reachable
    only through the appeal machinery of §3.2."
    PRD §3.1: "Operating on a determination in the wrong state — issuing one
    that is not `DRAFT`, or appealing or submitting against one that is not
    `ISSUED` — is rejected with `ERR_JD_INVALID_STATE` (HTTP 409)."

    A determination reversed by a SUSTAINED appeal refuses issuance and stays
    REVERSED.

    Design: Corner/state_machines/corner_jd_reversed_terminal_lockdown
    """
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["FORESTED_WETLAND"]}
    )
    appeal = file_appeal(jd, applicant, "Delineation omitted a channel")
    decide_appeal(appeal, AppealOutcome.SUSTAINED.value, "Remand confirmed")

    resp = api.issue_jd(jd["id"], district_engineer_headers)
    validate_error(resp, ApiErrorId.ERR_JD_INVALID_STATE)
    jd_after = validate_success(api.get_jd(jd["id"], reviewer_headers))
    assert jd_after["status"] == JdStatus.REVERSED.value


def test_corner_appeal_double_decide_rejected(api, district_engineer_headers, reviewer_headers):
    """PRD §3.2: "Appeals in any state other than `FILED` refuse a decision
    with `ERR_APPEAL_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_appeal_double_decide_rejected
    """
    applicant, site, jd = setup_site_with_issued_jd(
        site_overrides={"resource_types_present": ["FORESTED_WETLAND"]}
    )
    appeal = file_appeal(jd, applicant, "Grounds")
    decide_appeal(appeal, AppealOutcome.DENIED.value, "Delineation upheld")

    resp = api.decide_appeal(
        appeal["id"],
        {"outcome": "SUSTAINED", "decision_rationale": "Second bite"},
        district_engineer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_APPEAL_INVALID_STATE)
    appeal_after = validate_success(api.get_appeal(appeal["id"], reviewer_headers))
    assert appeal_after["status"] == "DENIED"


def test_corner_application_submit_from_screening_rejected(api):
    """PRD §3.3: "Every other state-targeted application action attempted
    from a state where it is not defined is rejected with
    `ERR_APPLICATION_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "Submission moves an application from `DRAFT` or
    `RETURNED_TO_APPLICANT` to `SUBMITTED`".

    Design: Corner/state_machines/corner_application_submit_from_screening_rejected
    """
    applicant, site, jd = setup_site_with_issued_jd()
    app = create_application(site, jd, applicant)
    app = submit_and_screen_begin(app, applicant)
    assert app["status"] == ApplicationStatus.SCREENING.value

    resp = api.submit_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)


def test_corner_application_withdraw_from_issued_rejected(api, reviewer_headers):
    """PRD §3.3: "The full status vocabulary is `DRAFT`, `SUBMITTED`,
    `SCREENING`, `RETURNED_TO_APPLICANT`, `ALTERNATIVES_REVIEW`,
    `PUBLIC_NOTICE_OPEN`, `DECISION_PENDING`, `ISSUED`, `DENIED`,
    `WITHDRAWN`, and `SUSPENDED_PENDING_JD`, of which `ISSUED`, `DENIED`,
    and `WITHDRAWN` are terminal."
    PRD §3.3: "Every other state-targeted application action attempted from a
    state where it is not defined is rejected with
    `ERR_APPLICATION_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_application_withdraw_from_issued_rejected
    """
    ctx = setup_issued_permit()
    app, applicant = ctx["app"], ctx["applicant"]
    assert app["status"] == ApplicationStatus.ISSUED.value

    resp = api.withdraw_application(app["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)
    app_after = validate_success(api.get_application(app["id"], reviewer_headers))
    assert app_after["status"] == ApplicationStatus.ISSUED.value


def test_corner_render_decision_before_decision_pending_rejected(api, decision_engineer_headers):
    """PRD §3.7: "From `DECISION_PENDING`, the decision belongs to the
    `DistrictEngineer`, who supplies an `outcome` and an optional
    `decision_rationale`."
    PRD §3.3: "Every other state-targeted application action attempted from a
    state where it is not defined is rejected with
    `ERR_APPLICATION_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_render_decision_before_decision_pending_rejected
    """
    applicant, site, jd = setup_site_with_issued_jd()
    app = create_application(site, jd, applicant)
    app = submit_and_screen_begin(app, applicant)
    assert app["status"] == ApplicationStatus.SCREENING.value

    resp = api.render_decision(
        app["id"], render_decision_payload("ISSUE"), decision_engineer_headers
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_INVALID_STATE)


def test_corner_aa_patch_while_submitted_rejected(api):
    """PRD §3.4: "Reviewing an analysis that is not `SUBMITTED`, or revising
    one that is not `REVISION_REQUESTED`, is `ERR_AA_INVALID_STATE`."

    PATCH is the revision-return edge and is only defined from
    REVISION_REQUESTED; PATCH while SUBMITTED fails.

    Design: Corner/state_machines/corner_aa_patch_while_submitted_rejected
    """
    ctx = setup_application_in_alternatives_review()
    aa = create_aa(ctx["app"], ctx["applicant"])
    assert aa["status"] == "SUBMITTED"

    resp = api.patch_alternatives_analysis(
        aa["id"], {"avoidance_narrative": "Rewritten"},
        make_applicant_headers(ctx["applicant"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AA_INVALID_STATE)


def test_corner_plan_secure_from_draft_rejected(api):
    """PRD §3.6: "Securing an `APPROVED` plan is the final financial gate,
    and it is where the provisional requirement becomes final."
    PRD §2.8: "State preconditions: the target entity must be in a state from
    which the invoked transition is defined, else the per-entity 409 —
    `ERR_JD_INVALID_STATE`, `ERR_APPEAL_INVALID_STATE`,
    `ERR_APPLICATION_INVALID_STATE`, `ERR_AA_INVALID_STATE`,
    `ERR_PLAN_INVALID_STATE`, `ERR_CREDIT_TXN_INVALID_STATE`,
    `ERR_PERMIT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`,
    `ERR_CASE_INVALID_STATE`, or `ERR_BANK_NOT_OPERATIONAL`."

    Design: Corner/state_machines/corner_plan_secure_from_draft_rejected
    """
    ctx = setup_aa_accepted()
    plan = create_plan(ctx["app"], ctx["applicant"])
    assert plan["status"] == PlanStatus.DRAFT.value

    resp = api.secure_credits(
        plan["id"], make_applicant_headers(ctx["applicant"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE)


def test_corner_plan_ilf_rejects_secure_credits(api):
    """PRD §3.6: "For `BANK_CREDITS`, the sum of `PURCHASED` transaction
    credits must meet the final requirement for every resource type, else
    `ERR_CREDITS_NOT_SECURED` (HTTP 422); arriving at secure-credits with the
    `IN_LIEU_FEE` mechanism is rejected as a state error,
    `ERR_PLAN_INVALID_STATE`."

    The IN_LIEU_FEE plan (fee 330000.00 = 6.00 FORESTED_WETLAND credits at
    55000 per credit) reaches CREDITS_SECURED only through pay-in-lieu-fee.

    Design: Corner/state_machines/corner_plan_ilf_rejects_secure_credits
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant, mechanism=Mechanism.IN_LIEU_FEE.value)
    assert plan["ilf_fee_due_dollars"] == pytest.approx(330000.00, abs=0.005), (
        "2.0 acres * 3.0 ratio = 6.00 credits at 55000 per credit"
    )
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    assert plan["status"] == PlanStatus.APPROVED.value

    resp = api.secure_credits(plan["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_PLAN_INVALID_STATE)


def test_corner_txn_double_purchase_rejected(api):
    """PRD §3.6: "Purchasing or releasing a transaction no longer `RESERVED`
    is `ERR_CREDIT_TXN_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_txn_double_purchase_rejected
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank(capacity=10.0)
    txn = reserve_credits(bank, plan, applicant, credits=2.0)
    txn = purchase_credits(txn, applicant)
    assert txn["status"] == "PURCHASED"

    resp = api.purchase_credit_transaction(
        txn["id"], make_applicant_headers(applicant["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CREDIT_TXN_INVALID_STATE)


def test_corner_permit_double_commence_rejected(api):
    """PRD §3.8: "The applicant commences work to move a permit `ISSUED` to
    `ACTIVE`; invoking that transition on a permit in any other state is
    `ERR_PERMIT_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_permit_double_commence_rejected
    """
    ctx = setup_issued_permit()
    permit, applicant = ctx["permit"], ctx["applicant"]
    permit = commence_permit(permit, applicant)
    assert permit["status"] == PermitStatus.ACTIVE.value

    resp = api.commence_work(permit["id"], make_applicant_headers(applicant["id"]))
    validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE)


def test_corner_report_review_from_due_rejected(api, reviewer_headers):
    """PRD §3.8: "A `Reviewer` reviews a `SUBMITTED` report by supplying an
    `outcome`."
    PRD §2.8: "State preconditions: the target entity must be in a state from
    which the invoked transition is defined, else the per-entity 409 —
    `ERR_JD_INVALID_STATE`, `ERR_APPEAL_INVALID_STATE`,
    `ERR_APPLICATION_INVALID_STATE`, `ERR_AA_INVALID_STATE`,
    `ERR_PLAN_INVALID_STATE`, `ERR_CREDIT_TXN_INVALID_STATE`,
    `ERR_PERMIT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`,
    `ERR_CASE_INVALID_STATE`, or `ERR_BANK_NOT_OPERATIONAL`."

    The report was never submitted, so review fails.

    Design: Corner/state_machines/corner_report_review_from_due_rejected
    """
    ctx = setup_issued_permit()
    rep1 = ctx["reports"][0]
    assert rep1["status"] == "DUE"

    resp = api.review_monitoring_report(
        rep1["id"], review_report_payload("ACCEPTED"), reviewer_headers
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE)


def test_corner_case_double_confirm_rejected(api, officer_3_headers):
    """PRD §3.9: "Confirmation moves the case `OPENED` to
    `VIOLATION_CONFIRMED`, stamps `confirmed_date`, and starts the penalty
    clock."
    PRD §3.9: "Every other out-of-state case operation is
    `ERR_CASE_INVALID_STATE`."

    A second confirmation (by a third officer, so the segregation gate
    passes) fails on state.

    Design: Corner/state_machines/corner_case_double_confirm_rejected
    """
    _, _, case = setup_case_opened(1.0)
    case = confirm_case(case)
    assert case["case_status"] == CaseStatus.VIOLATION_CONFIRMED.value

    resp = api.confirm_violation(case["id"], officer_3_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


def test_corner_case_verify_on_atf_track_rejected(api, officer_confirmer_headers):
    """PRD §3.9: "On the restoration track, an `EnforcementOfficer` verifies
    the restoration — an act defined only while the case is
    `RESOLUTION_PENDING` with `resolution_track` `RESTORATION`, else
    `ERR_CASE_INVALID_STATE`".

    On the AFTER_THE_FACT_PERMIT track the verify call fails even though the
    case sits in RESOLUTION_PENDING: the gate is on the track dimension.

    Design: Corner/state_machines/corner_case_verify_on_atf_track_rejected
    """
    ctx = setup_atf_application_linked()
    case = ctx["case"]
    assert case["case_status"] == CaseStatus.RESOLUTION_PENDING.value
    assert case["resolution_track"] == "AFTER_THE_FACT_PERMIT"

    resp = api.verify_restoration(case["id"], officer_confirmer_headers)
    validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)


def test_corner_permit_expiry_defaults_active_plan(api, reviewer_headers):
    """PRD §2.5: "Permits in `ISSUED` or `ACTIVE` whose `expiration_date` is
    now in the past (new clock strictly greater) transition to `EXPIRED`, and
    each such permit's linked mitigation plan in `ACTIVE` transitions to
    `DEFAULTED`."
    PRD §2.5: "Monitoring reports in `DUE` whose `due_date` is now in the
    past transition to `OVERDUE` — but only for permits still in `ACTIVE`
    after step 2."

    One clock call past expiration flips the ACTIVE permit to EXPIRED and its
    ACTIVE plan to DEFAULTED; because expiry is evaluated before report
    processing, no MONITORING_BREACH case is opened.

    Design: Corner/state_machines/corner_permit_expiry_defaults_active_plan
    """
    ctx = setup_active_permit()
    permit, plan = ctx["permit"], ctx["plan"]
    assert_iso_instants_equal(
        permit["expiration_date"], iso_add_days(permit["issue_date"], 1825),
        label="permit expiration_date = issue_date + 1825 days",
    )

    set_clock(iso_add_days(permit["expiration_date"], 1))

    permit_after = validate_success(api.get_permit(permit["id"], reviewer_headers))
    assert permit_after["status"] == PermitStatus.EXPIRED.value
    plan_after = validate_success(api.get_mitigation_plan(plan["id"], reviewer_headers))
    assert plan_after["status"] == PlanStatus.DEFAULTED.value, (
        "the expiry cascade defaults the ACTIVE plan"
    )
    cases = get_cases_for_applicant(ctx["applicant"])
    assert cases == [], (
        "expiry at step 2 of the pinned clock order preempts breach "
        "processing at step 4: no MONITORING_BREACH case exists"
    )


def test_corner_suspended_application_resumes_with_new_jd(api):
    """PRD §3.2: "The applicant may resubmit it by naming a `new_jd_id` that
    references a determination for the same site — one that is `ISSUED`,
    carries a `JURISDICTIONAL` determination, and is unexpired at the current
    clock."
    PRD §3.2: "On a successful resubmission the application's `jd_id` is
    replaced with the new determination, `submitted_date` is restamped to the
    clock, and the application returns to `SUBMITTED`."

    Design: Corner/state_machines/corner_suspended_application_resumes_with_new_jd
    """
    ctx = setup_suspended_application()
    app, site, applicant = ctx["app"], ctx["site"], ctx["applicant"]
    assert app["status"] == ApplicationStatus.SUSPENDED_PENDING_JD.value

    jd2 = create_and_issue_jd(site, rationale="Replacement delineation")
    app = submit_application(app, applicant, new_jd_id=jd2["id"])
    assert app["status"] == ApplicationStatus.SUBMITTED.value
    assert app["jd_id"] == jd2["id"], (
        "the REVERSED determination no longer blocks its replacement, and "
        "the suspended application resumes at SUBMITTED with the new jd_id"
    )
