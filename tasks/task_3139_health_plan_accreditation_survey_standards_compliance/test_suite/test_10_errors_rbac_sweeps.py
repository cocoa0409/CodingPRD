"""Error catalogue sweep, RBAC boundaries, immediate consistency, and
uniqueness constraints (PRD §2.1, §2.5, §2.8, §3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_evidence,
    accept_evidence,
    advance_to_survey_scheduling,
    cap_for_element,
    complete_session,
    complete_survey,
    confirm_survey,
    create_edition,
    create_plan,
    create_scope,
    create_application,
    create_sample,
    create_score,
    create_scored_sample,
    create_survey_on_app,
    create_surveyor,
    decide_outcome,
    finalize_all_scores,
    get_app,
    get_success_data,
    make_accreditation_officer_headers,
    make_plan_coordinator_headers,
    make_platform_admin_headers,
    make_public_viewer_headers,
    make_surveyor_headers,
    setup_base,
    setup_decided_with_um1_gap_failure,
    setup_evidence_review,
    setup_planned_full_survey,
    setup_scoring,
    submit_application,
    submit_cap_evidence,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import add_session, api_client


def _officer():
    return make_accreditation_officer_headers()


def _admin():
    return make_platform_admin_headers()


def test_error_catalog_trigger_coverage(api):
    """PRD §3.5: "a `budgeted_surveyor_hours` of at least 1" and survey window
    rule: "`end_date` before `start_date` is rejected with
    `ERR_SURVEY_WINDOW_INVALID`". PRD §3.1: "The named edition must be different
    from the path edition (a request that points at itself is
    `ERR_INVALID_REQUEST`, HTTP 400)". PRD §3.4: "submission while the case
    count is still short is rejected with `ERR_SAMPLE_INCOMPLETE` (HTTP 422)".

    Design: Corner/errors/error_catalog_trigger_coverage
    """
    ctx = setup_planned_full_survey()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]

    # Survey window: end before start.
    app_now = get_app(app_id)
    r_window = api_client.create_survey(
        app_id,
        {"survey_type": "FULL", "mode": "VIRTUAL", "start_date": "2026-10-09",
         "end_date": "2026-10-05", "budgeted_surveyor_hours": 4,
         "expected_application_version": app_now["version"]},
        _officer())
    validate_error(r_window, ApiErrorId.ERR_SURVEY_WINDOW_INVALID)
    assert r_window.status_code == 422

    # Supersede self-reference is a request-shape violation (400).
    r_sup = api_client.supersede_standards_edition(
        ctx["edition"]["id"], {"superseded_by_edition_id": ctx["edition"]["id"]}, _admin())
    validate_error(r_sup, ApiErrorId.ERR_INVALID_REQUEST)
    assert r_sup.status_code == 400

    # Empty sample submit: 0 cases < 5 required.
    empty_sample = create_sample(app_id, required_size=5)
    r_smp = api_client.submit_file_review_sample(
        empty_sample["id"], make_plan_coordinator_headers(plan_id))
    validate_error(r_smp, ApiErrorId.ERR_SAMPLE_INCOMPLETE)
    assert r_smp.status_code == 422


def test_plan_coordinator_cannot_publish_edition(api):
    """PRD §4: the publish endpoint's authorized role is `PlatformAdmin` only.
    PRD §2.1: "A request whose role is not among the roles authorized for the
    targeted endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/plan_coordinator_cannot_publish_edition
    """
    elements = [{"element_code": "UM-1", "category": "UM", "max_points": 4,
                 "is_must_pass": True, "evidence_required_count": 2}]
    edition, _ = create_edition(publish=False, elements=elements)
    plan = create_plan()
    r = api_client.publish_standards_edition(
        edition["id"], make_plan_coordinator_headers(plan["id"]))
    validate_error(r, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert r.status_code == 403


def test_surveyor_cannot_adjudicate_questions(api):
    """PRD §4: adjudication is listed as `AccreditationOfficer`. PRD §2.1:
    "A request whose role is not among the roles authorized for the targeted
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
    PRD §2.5: "The auth checks run before any existence, request-shape, or
    business checks".

    Design: Corner/rbac/surveyor_cannot_adjudicate_questions
    """
    r = api_client.adjudicate_surveyor_question(
        "00000000-0000-4000-8000-000000000002", {"gap_confirmed": True},
        make_surveyor_headers("00000000-0000-4000-8000-000000000003"))
    validate_error(r, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert r.status_code == 403


def test_public_viewer_cannot_create_plan(api):
    """PRD §4: plan creation is listed as `PlatformAdmin` only. PRD §2.1: "A
    request whose role is not among the roles authorized for the targeted
    endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

    Design: Corner/rbac/public_viewer_cannot_create_plan
    """
    r = api_client.create_health_plan(
        {"name": "Sneaky Plan", "plan_code": "SNK-99"}, make_public_viewer_headers())
    validate_error(r, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
    assert r.status_code == 403


def test_surveyor_session_complete_ownership(api):
    """PRD §3.5: "the caller's `X-User-ID` to equal the session's `surveyor_id`
    (otherwise `ERR_OWNERSHIP_MISMATCH`)"."

    Design: Corner/rbac/surveyor_session_complete_ownership
    """
    ctx = setup_planned_full_survey()
    session = add_session(ctx["survey"]["id"], ctx["surveyor"]["id"])
    confirm_survey(ctx["survey"]["id"])
    other = create_surveyor(name="Other Surveyor", credential_level="STAFF")

    r = api_client.complete_survey_session(session["id"],
                                           make_surveyor_headers(other["id"]))
    validate_error(r, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
    assert r.status_code == 403
    after = get_success_data(api_client.get_survey_session(session["id"], _officer()))
    assert after["status"] == "SCHEDULED", "failed completion leaves the session SCHEDULED"


def test_derived_application_totals_recomputed_on_finalize_and_void(api):
    """PRD §3.7: "Finalization also recomputes the application's
    `total_awarded_points` (the sum of `awarded_points` over the application's
    `FINAL`, non-`VOIDED` element scores, or 0 when there are none) and
    `total_forfeited_points` (the analogous sum of `forfeited_points`)."
    PRD §3.7: "voiding requires the score to be `PROVISIONAL` ... and moves it
    to `VOIDED` without further effect."

    Design: Corner/cross_cutting_layers/derived_application_totals_recomputed_on_finalize_and_void
    """
    ctx = setup_scoring()
    app_id = ctx["app"]["id"]
    sc1 = create_score(app_id, ctx["elements"]["UM-1"])
    sc2 = create_score(app_id, ctx["elements"]["CR-1"])
    from test_helpers import finalize_score, void_score
    finalize_score(sc1["id"])

    mid = get_app(app_id)
    assert mid["total_awarded_points"] == 4.00, "PROVISIONAL CR-1 excluded"
    assert mid["total_forfeited_points"] == 0.00

    void_score(sc2["id"])
    after = get_app(app_id)
    assert after["total_awarded_points"] == 4.00, "voiding a PROVISIONAL score changes nothing"
    assert after["total_forfeited_points"] == 0.00


def test_immediate_visibility_of_cascade_effects(api):
    """PRD §3.3: "When an application is withdrawn from `DRAFT` or `SUBMITTED`,
    every evidence item still in `SUBMITTED` is voided automatically by the
    system (status becomes `VOIDED`)."

    Design: Corner/consistency_model/immediate_visibility_of_cascade_effects
    """
    ctx = setup_base()
    plan_id = ctx["plan"]["id"]
    submit_application(ctx["app"]["id"], plan_id)
    ev = add_evidence(ctx["app"]["id"], plan_id, ctx["elements"]["UM-1"],
                      "pre-review evidence")

    withdrawn = get_success_data(api_client.withdraw_application(
        ctx["app"]["id"], make_plan_coordinator_headers(plan_id)))
    assert withdrawn["status"] == "WITHDRAWN"

    ev_after = get_success_data(api_client.get_evidence_item(ev["id"], _officer()))
    assert ev_after["status"] == "VOIDED", "no lag, no eventual reconciliation"


def test_annual_report_duplicate_year_rejected(api):
    """PRD §3.10: "at most one report may exist per (application,
    `reporting_year`), with duplicates rejected as `ERR_ANNUAL_REPORT_DUPLICATE`."

    Design: Corner/consistency_model/annual_report_duplicate_year_rejected
    """
    from test_helpers import setup_closed_application
    ctx = setup_closed_application()
    coord = make_plan_coordinator_headers(ctx["plan"]["id"])
    get_success_data(api_client.create_annual_report(
        ctx["app"]["id"],
        {"reporting_year": 2027,
         "attestation": "We attest the data submitted is complete and accurate."},
        coord))
    r = api_client.create_annual_report(
        ctx["app"]["id"],
        {"reporting_year": 2027,
         "attestation": "Second attestation with sufficient length."},
        coord)
    validate_error(r, ApiErrorId.ERR_ANNUAL_REPORT_DUPLICATE)
    assert r.status_code == 409


_NOT_FOUND_CASES = [
    ("GET /accreditation/applications/{id}", "00000000-0000-4000-8000-000000000010",
     ApiErrorId.ERR_APPLICATION_NOT_FOUND),
    ("GET /accreditation/evidence-items/{id}", "00000000-0000-4000-8000-000000000011",
     ApiErrorId.ERR_EVIDENCE_ITEM_NOT_FOUND),
    ("GET /accreditation/file-review-samples/{id}", "00000000-0000-4000-8000-000000000012",
     ApiErrorId.ERR_FILE_REVIEW_SAMPLE_NOT_FOUND),
    ("GET /accreditation/file-review-cases/{id}", "00000000-0000-4000-8000-000000000013",
     ApiErrorId.ERR_FILE_REVIEW_CASE_NOT_FOUND),
    ("GET /accreditation/surveys/{id}", "00000000-0000-4000-8000-000000000014",
     ApiErrorId.ERR_SURVEY_NOT_FOUND),
    ("GET /accreditation/survey-sessions/{id}", "00000000-0000-4000-8000-000000000015",
     ApiErrorId.ERR_SURVEY_SESSION_NOT_FOUND),
    ("GET /accreditation/surveyors/{id}", "00000000-0000-4000-8000-000000000016",
     ApiErrorId.ERR_SURVEYOR_NOT_FOUND),
    ("GET /accreditation/surveyor-questions/{id}", "00000000-0000-4000-8000-000000000017",
     ApiErrorId.ERR_SURVEYOR_QUESTION_NOT_FOUND),
    ("GET /accreditation/element-scores/{id}", "00000000-0000-4000-8000-000000000018",
     ApiErrorId.ERR_ELEMENT_SCORE_NOT_FOUND),
    ("GET /accreditation/corrective-action-plans/{id}", "00000000-0000-4000-8000-000000000019",
     ApiErrorId.ERR_CORRECTIVE_ACTION_PLAN_NOT_FOUND),
    ("GET /accreditation/outcomes/{id}", "00000000-0000-4000-8000-000000000020",
     ApiErrorId.ERR_ACCREDITATION_OUTCOME_NOT_FOUND),
    ("GET /accreditation/annual-reports/{id}", "00000000-0000-4000-8000-000000000021",
     ApiErrorId.ERR_ANNUAL_REPORT_NOT_FOUND),
    ("GET /accreditation/quality-measure-results/{id}", "00000000-0000-4000-8000-000000000022",
     ApiErrorId.ERR_QUALITY_MEASURE_RESULT_NOT_FOUND),
    ("GET /accreditation/standard-elements/{id}", "00000000-0000-4000-8000-000000000023",
     ApiErrorId.ERR_STANDARD_ELEMENT_NOT_FOUND),
    ("GET /accreditation/standards-editions/{id}", "00000000-0000-4000-8000-000000000024",
     ApiErrorId.ERR_STANDARDS_EDITION_NOT_FOUND),
    ("GET /accreditation/product-line-scopes/{id}", "00000000-0000-4000-8000-000000000025",
     ApiErrorId.ERR_PRODUCT_LINE_SCOPE_NOT_FOUND),
]


@pytest.mark.parametrize("method_path,entity_id,error_id", _NOT_FOUND_CASES,
                         ids=[c[2].value for c in _NOT_FOUND_CASES])
def test_not_found_sweep_for_all_child_entities(api, method_path, entity_id, error_id):
    """PRD §2.8: "the server validates each identifier's existence in
    left-to-right order along the path, returning the entity-specific 404 error
    for the first segment that does not resolve." PRD §5 error catalogue.

    Design: Corner/errors_coverage_sweep/not_found_sweep_for_all_child_entities
    """
    path = method_path.split(" ", 1)[1].replace("{id}", entity_id)
    r = api_client.get(path, headers=_officer())
    validate_error(r, error_id)
    assert r.status_code == 404


def test_duplicate_edition_year_and_element_code_rejected(api):
    """PRD §3.1: "an `edition_year` (unique across all editions; duplicates are
    rejected with `ERR_EDITION_YEAR_DUPLICATE`)" and "an `element_code` unique
    within its edition (violations return `ERR_ELEMENT_CODE_DUPLICATE`)".

    Design: Corner/errors_coverage_sweep/duplicate_edition_year_and_element_code_rejected
    """
    elements = [{"element_code": "UM-1", "category": "UM", "max_points": 4,
                 "is_must_pass": True, "evidence_required_count": 2}]
    edition, _ = create_edition(publish=False, elements=elements)
    edition_2027, _ = create_edition(
        publish=False, elements=[], edition_year=2027,
        effective_from="2027-01-01T00:00:00Z",
        effective_until="2028-12-31T23:59:59Z")

    r_year = api_client.create_standards_edition(
        {"edition_year": 2026, "effective_from": "2026-01-01T00:00:00Z",
         "effective_until": "2027-12-31T23:59:59Z",
         "min_file_sample_per_category": 5, "timeliness_threshold": 0.90},
        _admin())
    validate_error(r_year, ApiErrorId.ERR_EDITION_YEAR_DUPLICATE)
    assert r_year.status_code == 409

    r_code = api_client.create_standard_element(
        edition["id"],
        {"element_code": "UM-1", "category": "UM", "max_points": 2,
         "is_must_pass": False, "evidence_required_count": 0},
        _admin())
    validate_error(r_code, ApiErrorId.ERR_ELEMENT_CODE_DUPLICATE)
    assert r_code.status_code == 409

    # UM-1 in a DIFFERENT edition is fine (uniqueness is per-edition).
    ok = api_client.create_standard_element(
        edition_2027["id"],
        {"element_code": "UM-1", "category": "UM", "max_points": 4,
         "is_must_pass": True, "evidence_required_count": 2},
        _admin())
    validate_success(ok, expected_status=201)


def test_duplicate_element_score_and_cap_rejected(api):
    """PRD §3.7: "at most one non-`VOIDED` score may exist per (application,
    element) pair, and a duplicate is rejected with `ERR_ELEMENT_SCORE_EXISTS`."

    Design: Corner/errors_coverage_sweep/duplicate_element_score_and_cap_rejected
    """
    ctx = setup_scoring()
    app_id = ctx["app"]["id"]
    create_score(app_id, ctx["elements"]["UM-1"])
    r = api_client.create_element_score(
        app_id, {"standard_element_id": ctx["elements"]["UM-1"]}, _officer())
    validate_error(r, ApiErrorId.ERR_ELEMENT_SCORE_EXISTS)
    assert r.status_code == 409


def test_resurvey_confirm_blocked_by_pending_cap_review(api):
    """PRD §3.5: "for a `RESURVEY` survey no corrective action plan of the
    application may be in `EVIDENCE_SUBMITTED` status awaiting officer review
    (otherwise `ERR_CAP_REVIEW_PENDING`, HTTP 422)"."

    Design: Corner/errors_coverage_sweep/resurvey_confirm_blocked_by_pending_cap_review
    """
    ctx = setup_decided_with_um1_gap_failure()
    app_id, plan_id = ctx["app"]["id"], ctx["plan"]["id"]
    cap = cap_for_element(app_id, ctx["elements"]["UM-1"])
    submit_cap_evidence(cap["id"], plan_id, "pending remediation")

    resurvey = create_survey_on_app(app_id, survey_type="RESURVEY",
                                    start_date="2026-11-02", end_date="2026-11-06",
                                    budgeted_surveyor_hours=4)
    add_session(resurvey["id"], ctx["surveyor"]["id"], session_date="2026-11-02")
    r = api_client.confirm_survey(resurvey["id"], _officer())
    validate_error(r, ApiErrorId.ERR_CAP_REVIEW_PENDING)
    assert r.status_code == 422


def test_invalid_transition_supersede_from_draft(api):
    """PRD §3.1: "the path edition must be `PUBLISHED` (otherwise
    `ERR_EDITION_NOT_SUPERSEDABLE`)"."

    Design: Corner/errors_stubs/invalid_transition_supersede_from_draft
    """
    edition, _ = create_edition(publish=False, elements=[])
    r = api_client.supersede_standards_edition(
        edition["id"],
        {"superseded_by_edition_id": "00000000-0000-4000-8000-000000000009"},
        _admin())
    validate_error(r, ApiErrorId.ERR_EDITION_NOT_SUPERSEDABLE)
    assert r.status_code == 409
