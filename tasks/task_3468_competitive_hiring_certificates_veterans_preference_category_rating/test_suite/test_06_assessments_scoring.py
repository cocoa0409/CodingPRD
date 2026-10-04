"""SME assessment lifecycle and scoring: provisional vs certified variants,
the pinned per-component rounding order, the return-resubmit cycle, category
cut boundaries, and the assessment state and authorship gates.
"""
from test_helpers import (
    HR, ApiErrorId,
    api_client, create_assessment_payload, expected_sme_score,
    get_success_data, make_sme_headers, rate_application, register_applicant,
    screen_application, setup_open_announcement, setup_qualified_application,
    submit_application, validate_error, validate_success,
)

SME_1 = make_sme_headers("sme-1")
SME_2 = make_sme_headers("sme-2")


def _create_assessment(application_id, k, s, a, headers=SME_1):
    resp = api_client.create_assessment(
        application_id, create_assessment_payload(k, s, a), headers)
    return validate_success(resp, 201)


def _submit_assessment(assessment_id, payload=None, headers=SME_1):
    resp = api_client.submit_assessment(assessment_id, payload or {}, headers)
    return validate_success(resp, 200)


def test_application_provisional_vs_sme_certified_score(api):
    """PRD §3.4: "At submission the system scores the self-claim with the same
    formula the SME will later apply (§3.5): the result is stored as
    `provisional_score`, and `provisional_category` maps it against the
    announcement's cut points".
    PRD §3.4: "Because the inputs are self-reported, this provisional pair
    routinely differs from the SME-certified score and category that later
    supersede it."

    Design: Difficulty/dual_variant_calc/application_provisional_vs_sme_certified_score
    """
    ctx = setup_open_announcement()
    announcement = ctx["announcement"]

    applicant = register_applicant()
    application = submit_application(
        announcement, applicant,
        self_rating_knowledge=5, self_rating_skill=5, self_rating_ability=5)
    # Self-reported (5,5,5) -> 70 + 9 + 6 + 15 = 100 -> BEST_QUALIFIED.
    assert application["provisional_score"] == expected_sme_score(5, 5, 5) == 100
    assert application["provisional_category"] == "BEST_QUALIFIED"

    screened = screen_application(application["id"])
    assert screened["status"] == "QUALIFIED"

    # The certified variant over SME ratings (4,4,4) -> 70 + 7 + 5 + 12 = 94.
    _assessment, rated = rate_application(application["id"], 4, 4, 4)
    assert rated["status"] == "RATED"
    assert rated["technical_score"] == expected_sme_score(4, 4, 4) == 94
    assert rated["quality_category"] == "WELL_QUALIFIED"
    assert rated["technical_score"] != application["provisional_score"]


def test_sme_score_pinned_component_rounding_order(api):
    """PRD §3.5: "The pinned order is to round each component half-up to a whole
    number first, then sum the three rounded components, then add the base of
    70" and "summing before rounding produces a different number for some
    inputs — ratings of 3, 1, 1 score 79 under the pinned order but 80 if
    summed first, and ratings of 1, 3, 1 score 79 versus 78 — and only the
    pinned order is correct."

    Design: Difficulty/combinatorial_formula/sme_score_pinned_component_rounding_order
    """
    ctx = setup_open_announcement()
    _applicant, application = setup_qualified_application(ctx["announcement"])

    assessment = _create_assessment(application["id"], 3, 1, 1)
    submitted = _submit_assessment(assessment["id"])
    # Pinned: round(5.4)=5, round(1.2)=1, round(3.0)=3 -> 70 + 9 = 79.
    # Sum-then-round would give 70 + round(9.6) = 80 — the wrong order.
    assert submitted["technical_score"] == expected_sme_score(3, 1, 1) == 79
    assert submitted["technical_score"] != 80
    assert submitted["quality_category"] == "QUALIFIED"  # 79 < wq_cut 85


def test_assessment_return_resubmit_revision_cycle(api):
    """PRD §3.5: "A resubmission replaces the three rating fields with the
    payload's values and recomputes both results, and the return-resubmit cycle
    may repeat without bound; every submission increments the assessment's
    `version`."

    Design: Difficulty/non_linear_state_machine/assessment_return_resubmit_revision_cycle
    """
    ctx = setup_open_announcement()
    _applicant, application = setup_qualified_application(ctx["announcement"])

    assessment = _create_assessment(application["id"], 4, 4, 4)
    submitted = _submit_assessment(assessment["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["technical_score"] == 94

    resp = api_client.return_assessment(
        assessment["id"], {"return_reason": "insufficient justification"}, HR)
    returned = validate_success(resp, 200)
    assert returned["status"] == "RETURNED"

    resubmitted = _submit_assessment(
        assessment["id"],
        {"rating_knowledge": 2, "rating_skill": 5, "rating_ability": 5})
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["technical_score"] == expected_sme_score(2, 5, 5) == 95
    assert resubmitted["quality_category"] == "BEST_QUALIFIED"

    resp = api_client.accept_assessment(assessment["id"], HR)
    accepted = validate_success(resp, 200)
    assert accepted["status"] == "ACCEPTED"

    rated = get_success_data(api_client.get_application(application["id"], HR))
    assert rated["status"] == "RATED"
    assert rated["technical_score"] == 95


def test_wq_cut_boundary_scores_85_vs_84(api):
    """PRD §3.4: "a score at or above `bq_cut` yields `BEST_QUALIFIED`, at or
    above `wq_cut` but below `bq_cut` yields `WELL_QUALIFIED`, and anything
    lower yields `QUALIFIED`."

    Design: Corner/calculations/wq_cut_boundary_scores_85_vs_84
    """
    ctx = setup_open_announcement()
    announcement = ctx["announcement"]
    assert announcement["wq_cut"] == 85

    _a1, app85 = setup_qualified_application(announcement)
    assessment85 = _create_assessment(app85["id"], 2, 2, 3)
    submitted85 = _submit_assessment(assessment85["id"])
    # Components 4 + 2 + 9 = 15 -> 85 == wq_cut -> WELL_QUALIFIED (inclusive).
    assert submitted85["technical_score"] == expected_sme_score(2, 2, 3) == 85
    assert submitted85["quality_category"] == "WELL_QUALIFIED"

    _a2, app84 = setup_qualified_application(announcement)
    assessment84 = _create_assessment(app84["id"], 5, 2, 1)
    submitted84 = _submit_assessment(assessment84["id"])
    # Components 9 + 2 + 3 = 14 -> 84 < wq_cut -> QUALIFIED.
    assert submitted84["technical_score"] == expected_sme_score(5, 2, 1) == 84
    assert submitted84["quality_category"] == "QUALIFIED"


def test_submit_on_submitted_assessment_rejected(api):
    """PRD §3.5: "Acting on an assessment in the wrong posture — accepting or
    returning anything not `SUBMITTED`, or submitting from a state other than
    `DRAFT` or `RETURNED` — is rejected with `ERR_ASSESSMENT_NOT_SUBMITTED`
    (HTTP 409)."

    Design: Corner/state_machines/submit_on_submitted_assessment_rejected
    """
    ctx = setup_open_announcement()
    _applicant, application = setup_qualified_application(ctx["announcement"])

    assessment = _create_assessment(application["id"], 4, 4, 4)
    submitted = _submit_assessment(assessment["id"])
    assert submitted["technical_score"] == 94

    resp = api_client.submit_assessment(
        assessment["id"],
        {"rating_knowledge": 5, "rating_skill": 5, "rating_ability": 5},
        SME_1)
    validate_error(resp, ApiErrorId.ERR_ASSESSMENT_NOT_SUBMITTED)

    reread = get_success_data(api_client.get_assessment(assessment["id"], HR))
    assert reread["status"] == "SUBMITTED"
    assert reread["technical_score"] == 94, "rejected resubmission must not recompute the score"


def test_second_draft_assessment_rejected(api):
    """PRD §3.5: "Record concurrency is capped: at most one assessment per
    application may sit in `DRAFT` or `SUBMITTED`, and at most one may ever
    stand `ACCEPTED` — violations surface as `ERR_ACTIVE_ASSESSMENT_EXISTS`
    (HTTP 409), both at creation time and at acceptance time."

    Design: Corner/validations/second_draft_assessment_rejected
    """
    ctx = setup_open_announcement()
    _applicant, application = setup_qualified_application(ctx["announcement"])

    _create_assessment(application["id"], 4, 4, 4)  # DRAFT held by sme-1
    resp = api_client.create_assessment(
        application["id"], create_assessment_payload(5, 5, 5), SME_2)
    validate_error(resp, ApiErrorId.ERR_ACTIVE_ASSESSMENT_EXISTS)


def test_sme_cannot_submit_others_assessment(api):
    """PRD §2.1: "an `SME` acts only on assessments it authored, so submitting
    or resubmitting an assessment requires the acting `X-User-ID` to equal the
    assessment's recorded `sme_user_id`, and a mismatch is `ERR_FORBIDDEN`."

    Design: Corner/rbac/sme_cannot_submit_others_assessment
    """
    ctx = setup_open_announcement()
    _applicant, application = setup_qualified_application(ctx["announcement"])

    assessment = _create_assessment(application["id"], 4, 4, 4)  # authored by sme-1
    resp = api_client.submit_assessment(assessment["id"], {}, SME_2)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
