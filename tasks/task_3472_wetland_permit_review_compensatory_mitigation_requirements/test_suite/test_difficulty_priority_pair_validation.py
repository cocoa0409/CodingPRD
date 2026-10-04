"""Difficulty queue — validation priority pairs (PRD §2.8).

When two checks fail on one request, the pipeline returns the earlier
failure: state tier before the fiscal domain rules, and the
segregation-of-duties gate before the decision prerequisites.
"""
from test_helpers import (
    ApiErrorId,
    create_credit_transaction_payload,
    create_plan,
    make_applicant_headers,
    make_district_engineer_headers,
    render_decision_payload,
    review_plan,
    setup_aa_accepted,
    setup_application_decision_pending,
    setup_operational_bank,
    submit_plan,
    suspend_bank,
    validate_error,
)


def test_state_beats_fiscal_on_bank_txn(api):
    """PRD §2.8: "Every request is checked against an ordered validation
    pipeline, and the first failing check wins — its error is the one
    returned, and no later check masks an earlier failure."
    PRD §2.8: "State preconditions: the target entity must be in a state from
    which the invoked transition is defined, else the per-entity 409 —
    `ERR_JD_INVALID_STATE`, `ERR_APPEAL_INVALID_STATE`,
    `ERR_APPLICATION_INVALID_STATE`, `ERR_AA_INVALID_STATE`,
    `ERR_PLAN_INVALID_STATE`, `ERR_CREDIT_TXN_INVALID_STATE`,
    `ERR_PERMIT_INVALID_STATE`, `ERR_REPORT_INVALID_STATE`,
    `ERR_CASE_INVALID_STATE`, or `ERR_BANK_NOT_OPERATIONAL`. This tier also
    covers three cross-entity state reads: at application submission the
    referenced determination must be `ISSUED`; at credit-transaction creation
    the linked plan must be `APPROVED`; and a bank must be `OPERATIONAL`
    before it accepts reservations."

    The reservation targets a SUSPENDED bank (state tier failure) and
    requests 999.0 credits against 20 available (fiscal domain-rule failure).
    The state error ERR_BANK_NOT_OPERATIONAL wins.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_bank_txn
    """
    ctx = setup_aa_accepted()
    applicant = ctx["applicant"]
    plan = create_plan(ctx["app"], applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)
    bank = setup_operational_bank()
    suspend_bank(bank)

    resp = api.create_credit_transaction(
        create_credit_transaction_payload(
            bank["id"], plan["id"], resource_type="FORESTED_WETLAND", credits=999.0
        ),
        make_applicant_headers(applicant["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_BANK_NOT_OPERATIONAL)


def test_safety_beats_referential_on_decision(api):
    """PRD §3.7: "Four gates stand in front of an issuance. First,
    segregation of duties: the deciding engineer's `X-User-ID` must differ
    from the application's `screening_reviewer_id`, else
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.7: "Fourth, when `compensatory_mitigation_required` is true, one
    of the application's mitigation plans must stand in `CREDITS_SECURED`,
    else `ERR_MITIGATION_NOT_SECURED` (HTTP 422)."

    Render-decision ISSUE attempted by the same X-User-ID that performed
    screening (first gate fails) while the application's plan is only
    APPROVED, never secured (fourth gate also fails). The
    segregation-of-duties error wins.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_decision
    """
    ctx = setup_application_decision_pending()
    app, applicant = ctx["app"], ctx["applicant"]
    plan = create_plan(app, applicant)
    plan = submit_plan(plan, applicant)
    plan = review_plan(plan)  # APPROVED, never secured

    # The caller carries the DistrictEngineer role but reuses the recorded
    # screening reviewer id, tripping the first gate.
    resp = api.render_decision(
        app["id"],
        render_decision_payload("ISSUE"),
        make_district_engineer_headers(app["screening_reviewer_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
