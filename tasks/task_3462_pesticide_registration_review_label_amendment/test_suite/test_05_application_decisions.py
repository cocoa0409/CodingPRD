"""Application review decisions: the deficiency loop, terminal lockdown, the
approval gate chain (studies, assessment, LOC, tolerance, segregation of
duties), and read-your-writes consistency (PRD §2.2, §3.2–§3.4).
"""
from test_helpers import (
    ApiErrorId,
    ASSESSOR_1_ID,
    TEST_USERS,
    accept_study,
    api_client,
    approve_application,
    assert_application,
    assert_iso_instant_equal,
    create_active_ingredient,
    create_application,
    create_product,
    create_registered_product,
    create_study,
    decide_application,
    get_product,
    list_product_use_sites,
    make_application_decision_payload,
    make_reviewer_headers,
    resubmit_application,
    run_risk_assessment,
    setup_application_in_review,
    submit_application,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
REGISTRANT = TEST_USERS["registrant_alice_headers"]
REVIEWER = TEST_USERS["reviewer_1_headers"]


def _get_application(application_id):
    """Read one application through the PRD §4 GET endpoint."""
    return validate_success(api_client.get_application(application_id, ADMIN))
ASSESSOR = TEST_USERS["assessor_1_headers"]


def test_deficiency_decision_on_draft_application_returns_not_in_review(api):
    """PRD §3.4: "The decision on an `IN_REVIEW` application belongs to a
    `RegistrationReviewer`, whose `decision` payload is `APPROVE`, `DENY`, or
    `DEFICIENCY`; any decision attempted on an application not `IN_REVIEW` fails
    `ERR_APPLICATION_NOT_IN_REVIEW`."

    Design: Corner/state_machines/deficiency_decision_on_draft_application_returns_not_in_review
    """
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"])
    application = create_application(product["id"], REGISTRANT, "NON_FOOD_USE")
    resp = api_client.decide_application(
        application["id"],
        make_application_decision_payload("DEFICIENCY",
                                          deficiency_notes="incomplete package"),
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_APPLICATION_NOT_IN_REVIEW)
    application = _get_application(application["id"])
    assert application["status"] == "DRAFT"
    assert application["deficiency_count"] == 0


def test_application_withdraw_after_approval_returns_already_decided(api):
    """PRD §3.2: "withdrawing an application that has already reached `APPROVED`,
    `DENIED`, or `WITHDRAWN` fails `ERR_APPLICATION_ALREADY_DECIDED`."

    Design: Corner/state_machines/application_withdraw_after_approval_returns_already_decided
    """
    ctx = create_registered_product()
    app_id = ctx["application"]["id"]
    resp = api_client.withdraw_application(app_id, REGISTRANT, payload={})
    validate_error(resp, ApiErrorId.ERR_APPLICATION_ALREADY_DECIDED)
    assert _get_application(app_id)["status"] == "APPROVED"
    assert get_product(ctx["product"]["id"])["status"] == "REGISTERED"


def test_application_deficiency_revision_loop(api):
    """PRD §3.2: "a reviewer who finds the dossier incomplete issues a deficiency
    decision, moving the application `IN_REVIEW` → `DATA_DEFICIENCY`,
    incrementing `deficiency_count` by exactly one, and optionally recording
    `deficiency_notes`."
    PRD §3.2: "The registrant cures and resubmits, moving `DATA_DEFICIENCY` →
    `IN_REVIEW`; resubmission re-checks the required-study completeness rule
    (failing `ERR_MISSING_REQUIRED_STUDIES` if still short), and the request must
    omit `payment_cents` entirely — no second fee is ever charged. Resubmission
    refreshes `submitted_at` but never recomputes `review_due_at`: the statutory
    clock runs from the first submission only."

    Design: Difficulty/non_linear_state_machine/application_deficiency_revision_loop
    """
    ctx = setup_application_in_review()  # NON_FOOD_USE IN_REVIEW, studies present
    app_id = ctx["application"]["id"]

    decide_application(app_id, "DEFICIENCY",
                       reviewer_headers=REVIEWER,
                       deficiency_notes="residue chemistry rationale incomplete")
    resubmit_application(app_id, REGISTRANT)
    decide_application(app_id, "DEFICIENCY",
                       reviewer_headers=REVIEWER,
                       deficiency_notes="efficacy protocol deviation")
    application = _get_application(app_id)
    assert application["status"] == "DATA_DEFICIENCY"
    assert application["deficiency_count"] == 2

    for study in ctx["studies"].values():
        accept_study(study["id"])
    resubmit_application(app_id, REGISTRANT)
    run_risk_assessment(app_id, tier="SCREENING")
    approve_application(app_id, final_classification="GENERAL_USE")

    application = _get_application(app_id)
    assert application["deficiency_count"] == 2
    # First submit 2026-09-01 + 270 days; the two resubmissions never recomputed it.
    assert_iso_instant_equal(application["review_due_at"], "2027-05-29T00:00:00Z",
                             "review_due_at")
    assert application["status"] == "APPROVED"
    assert get_product(ctx["product"]["id"])["status"] == "REGISTERED"


def test_study_second_decision_returns_not_decidable(api):
    """PRD §3.3: "an accept decision moves `RECEIVED` → `ACCEPTED`, a reject
    decision moves `RECEIVED` → `REJECTED`, and any decision attempted on a study
    no longer `RECEIVED` fails `ERR_STUDY_NOT_DECIDABLE`."
    PRD §3.3: "Either decision stamps `decided_by_ref` from the assessor's header
    and `decided_at` from the clock"

    Design: Corner/state_machines/study_second_decision_returns_not_decidable
    """
    ai = create_active_ingredient()
    product = create_product(REGISTRANT, ai["id"])
    application = create_application(product["id"], REGISTRANT, "NON_FOOD_USE")
    study = create_study(application_id=application["id"], study_type="EFFICACY",
                         registrant_headers=REGISTRANT)
    accept_study(study["id"], ASSESSOR)

    resp = api_client.decide_study(
        study["id"], {"decision": "REJECT"}, TEST_USERS["assessor_2_headers"])
    validate_error(resp, ApiErrorId.ERR_STUDY_NOT_DECIDABLE)

    data = validate_success(api_client.get_study(study["id"], ADMIN))
    assert data["status"] == "ACCEPTED"
    assert data["decided_by_ref"] == ASSESSOR_1_ID


def test_approve_without_risk_assessment_returns_no_risk_assessment(api):
    """PRD §3.4: "At least one risk assessment must exist for the application
    (`ERR_NO_RISK_ASSESSMENT`)."

    Design: Corner/errors/approve_without_risk_assessment_returns_no_risk_assessment
    """
    ctx = setup_application_in_review(accept_studies=True)
    app_id = ctx["application"]["id"]
    resp = api_client.decide_application(
        app_id,
        make_application_decision_payload("APPROVE", final_classification="GENERAL_USE"),
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_RISK_ASSESSMENT)
    assert _get_application(app_id)["status"] == "IN_REVIEW"


def test_approve_food_use_without_tolerance_returns_no_proposed_tolerance(api):
    """PRD §3.4: "A `FOOD_USE` or `MIXED_USE` application must have at least one
    `PROPOSED` tolerance on the product, else `ERR_NO_PROPOSED_TOLERANCE`."
    PRD §3.3: "When no tolerance qualifies, the input set is empty and both
    outputs are exactly 0.000."

    Design: Corner/errors/approve_food_use_without_tolerance_returns_no_proposed_tolerance
    """
    ctx = setup_application_in_review(use_pattern="FOOD_USE", accept_studies=True,
                                      with_tolerance=False)
    app_id = ctx["application"]["id"]
    assessment = run_risk_assessment(app_id, tier="SCREENING")
    # Empty tolerance input set -> LOC clear, yet the tolerance gate still stops it.
    assert assessment["dietary_rq"] == 0.0
    assert assessment["level_of_concern_exceeded"] is False

    resp = api_client.decide_application(
        app_id,
        make_application_decision_payload("APPROVE", final_classification="GENERAL_USE"),
        REVIEWER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_PROPOSED_TOLERANCE)
    assert get_product(ctx["product"]["id"])["status"] == "UNREGISTERED"


def test_application_approver_who_ran_latest_assessment_returns_sod(api):
    """PRD §3.4: "And segregation of duties applies: the deciding reviewer's
    `X-User-ID` must differ from the `assessor_ref` of the latest risk assessment,
    else `ERR_SEGREGATION_OF_DUTIES_VIOLATION` (HTTP 403)."

    Design: Corner/validations/application_approver_who_ran_latest_assessment_returns_sod
    """
    ctx = setup_application_in_review(accept_studies=True)
    app_id = ctx["application"]["id"]
    run_risk_assessment(app_id, tier="SCREENING", assessor_headers=ASSESSOR)

    # The same person (X-User-ID ra-1) wearing the reviewer hat cannot approve.
    resp = api_client.decide_application(
        app_id,
        make_application_decision_payload("APPROVE", final_classification="GENERAL_USE"),
        make_reviewer_headers(ASSESSOR_1_ID),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION)
    assert _get_application(app_id)["status"] == "IN_REVIEW"

    approved = approve_application(app_id, final_classification="GENERAL_USE",
                                   reviewer_headers=REVIEWER)
    assert approved["status"] == "APPROVED"
    assert get_product(ctx["product"]["id"])["status"] == "REGISTERED"


def test_immediate_consistency_mutation_visible_in_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.4: "An approval stamps `decided_at`, stores `final_classification` on
    the application, and flips the product `UNREGISTERED` → `REGISTERED` in a
    single cascade."
    PRD §2.5: "`version` (integer): a system-managed integer that increments by
    one on every mutation of the resource."

    Design: Corner/consistency_model/immediate_consistency_mutation_visible_in_response
    """
    ctx = setup_application_in_review(accept_studies=True)
    app_id = ctx["application"]["id"]
    product_id = ctx["product"]["id"]
    run_risk_assessment(app_id, tier="SCREENING")
    version_before = _get_application(app_id)["version"]

    resp = api_client.decide_application(
        app_id,
        make_application_decision_payload("APPROVE", final_classification="GENERAL_USE"),
        REVIEWER,
    )
    data = validate_success(resp)
    assert_application(data)
    assert data["status"] == "APPROVED"
    assert_iso_instant_equal(data["decided_at"], "2026-09-01T00:00:00Z",
                             "decided_at")
    assert data["final_classification"] == "GENERAL_USE"
    assert data["version"] == version_before + 1

    product = get_product(product_id)
    assert product["status"] == "REGISTERED"
    assert product["epa_registration_number"] == "EPA-RR-000001"
    sites = list_product_use_sites(product_id, status="ACTIVE")
    assert {s["site_code"] for s in sites} == {"TURF"}
