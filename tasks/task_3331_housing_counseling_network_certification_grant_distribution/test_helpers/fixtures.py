"""Composite setup helpers for multi-step preconditions.

Every helper builds its preconditions from scratch against a fresh server
(the harness restarts the API before every test, so each test starts empty).
Setup calls use the lenient get_success_data() so failures surface clearly.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, build_user_headers

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_member_payload,
    submit_assessment_payload,
    adjudicate_assessment_payload,
    create_counselor_payload,
    create_course_payload,
    create_certification_payload,
    create_grant_cycle_payload,
    create_grant_application_payload,
    create_disbursement_payload,
    create_client_file_payload,
    create_expenditure_report_payload,
)
from .test_users import TEST_USERS, make_member_admin_headers

DIRECTOR = TEST_USERS["network_director_headers"]
ASSESSOR = TEST_USERS["assessor_headers"]
REGISTRAR = TEST_USERS["training_registrar_headers"]
OFFICER = TEST_USERS["grant_officer_headers"]
REVIEWER = TEST_USERS["compliance_reviewer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1: members and chartering
# ---------------------------------------------------------------------------

def create_member(**overrides) -> dict:
    """Create one APPLICANT member."""
    payload = create_member_payload(**overrides)
    resp = api_client.create_member(payload, DIRECTOR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_member -> {resp.status_code}: {resp.text}")
    return data


def create_member_under_assessment(member_overrides=None, director_headers=None,
                                   assessor_headers=None, director_user_id="u-director-1",
                                   **assessment_overrides):
    """Member + begin-assessment + submit + score. Returns (member, assessment)."""
    assessor_headers = assessor_headers or build_user_headers("u-assessor-1", "Assessor")
    director_headers = director_headers or build_user_headers(director_user_id, "NetworkDirector")
    member = create_member(**(member_overrides or {}))
    resp = api_client.begin_assessment(member["id"], assessor_headers)
    assessment = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: begin_assessment -> {resp.status_code}: {resp.text}")
    resp = api_client.submit_assessment(
        assessment["id"], submit_assessment_payload(**assessment_overrides), assessor_headers)
    get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: submit_assessment -> {resp.status_code}: {resp.text}")
    resp = api_client.score_assessment(assessment["id"], director_headers)
    scored = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: score_assessment -> {resp.status_code}: {resp.text}")
    return member, scored


def create_provisional_member(member_overrides=None, site_visit_adjustment=0, **kwargs):
    """Member adjudicated with a passing rating -> PROVISIONAL."""
    director_headers = kwargs.pop("director_headers", build_user_headers("u-director-1", "NetworkDirector"))
    member, assessment = create_member_under_assessment(
        member_overrides, director_headers=director_headers, **kwargs)
    resp = api_client.adjudicate_assessment(
        assessment["id"], adjudicate_assessment_payload(site_visit_adjustment=site_visit_adjustment),
        director_headers)
    final = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: adjudicate_assessment -> {resp.status_code}: {resp.text}")
    return member, final


# ---------------------------------------------------------------------------
# Tier 2: counselors, courses, certifications
# ---------------------------------------------------------------------------

def create_counselor(member_id, **overrides) -> dict:
    payload = create_counselor_payload(member_id=member_id, **overrides)
    resp = api_client.create_counselor(payload, DIRECTOR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_counselor -> {resp.status_code}: {resp.text}")
    return data


def create_course(**overrides) -> dict:
    payload = create_course_payload(**overrides)
    resp = api_client.create_course(payload, REGISTRAR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_course -> {resp.status_code}: {resp.text}")
    return data


def set_clock(to_iso8601: str):
    resp = api_client.set_clock(to_iso8601, DIRECTOR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: set_clock -> {resp.status_code}: {resp.text}")
    return data


def enroll(course_id, counselor_id) -> dict:
    resp = api_client.create_enrollment(course_id, {"counselor_id": counselor_id}, REGISTRAR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: enroll -> {resp.status_code}: {resp.text}")
    return data


def grade(enrollment_id, score=TEST_DEFAULTS["DEFAULT_GRADE_SCORE"]) -> dict:
    resp = api_client.grade_enrollment(enrollment_id, {"score": score}, REGISTRAR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: grade -> {resp.status_code}: {resp.text}")
    return data


def complete_course_enrollment(course_id, counselor_id,
                               in_session_at=TEST_DEFAULTS["DEFAULT_IN_SESSION_INSTANT"],
                               score=TEST_DEFAULTS["DEFAULT_GRADE_SCORE"]) -> dict:
    """Enroll and grade to COMPLETED while the course is in session."""
    set_clock(in_session_at)
    enrollment = enroll(course_id, counselor_id)
    return grade(enrollment["id"], score)


def create_certification(counselor_id, program_area="HOMEOWNERSHIP") -> dict:
    payload = create_certification_payload(counselor_id=counselor_id, program_area=program_area)
    resp = api_client.create_certification(payload, REGISTRAR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_certification -> {resp.status_code}: {resp.text}")
    return data


def certify(certification_id) -> dict:
    resp = api_client.certify_certification(certification_id, REGISTRAR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: certify -> {resp.status_code}: {resp.text}")
    return data


def setup_member_with_certified_counselor(
        member_overrides=None, program_area="HOMEOWNERSHIP", course_code="HO-100",
        counselor_overrides=None, delivery_start=None, delivery_end=None,
        in_session_at=None, **assessment_kwargs):
    """PROVISIONAL member + ACTIVE counselor with a COMPLETED course enrollment
    and a CERTIFIED certification in `program_area`.
    Returns (member, counselor, course, enrollment, certification)."""
    member, _assessment = create_provisional_member(member_overrides, **assessment_kwargs)
    counselor = create_counselor(member["id"], **(counselor_overrides or {}))
    course_kwargs = {"course_code": course_code, "program_area": program_area}
    if delivery_start is not None:
        course_kwargs["delivery_start"] = delivery_start
    if delivery_end is not None:
        course_kwargs["delivery_end"] = delivery_end
    course = create_course(**course_kwargs)
    enrollment = complete_course_enrollment(
        course["id"], counselor["id"],
        in_session_at=in_session_at or TEST_DEFAULTS["DEFAULT_IN_SESSION_INSTANT"])
    certification = create_certification(counselor["id"], program_area)
    certification = certify(certification["id"])
    return member, counselor, course, enrollment, certification


def setup_chartered_member_with_counselor(
        member_overrides=None, program_area="HOMEOWNERSHIP", course_code="HO-100",
        counselor_overrides=None, delivery_start=None, delivery_end=None,
        in_session_at=None, **assessment_kwargs):
    """CHARTERED member + one ACTIVE counselor CERTIFIED in `program_area`.
    Returns (member, counselor, certification)."""
    member, counselor, _course, _enrollment, certification = setup_member_with_certified_counselor(
        member_overrides=member_overrides, program_area=program_area,
        course_code=course_code, counselor_overrides=counselor_overrides,
        delivery_start=delivery_start, delivery_end=delivery_end,
        in_session_at=in_session_at,
        **assessment_kwargs)
    resp = api_client.charter_member(member["id"], DIRECTOR)
    member = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: charter_member -> {resp.status_code}: {resp.text}")
    return member, counselor, certification


# ---------------------------------------------------------------------------
# Tier 3: grant lifecycle
# ---------------------------------------------------------------------------

def create_grant_cycle(**overrides) -> dict:
    payload = create_grant_cycle_payload(**overrides)
    resp = api_client.create_grant_cycle(payload, OFFICER)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_grant_cycle -> {resp.status_code}: {resp.text}")
    return data


def create_grant_application(cycle, member, **overrides) -> dict:
    """DRAFT application; refreshes expected_cycle_version from the cycle."""
    payload = create_grant_application_payload(
        cycle_id=cycle["id"], member_id=member["id"],
        expected_cycle_version=cycle["version"], **overrides)
    resp = api_client.create_grant_application(payload, make_member_admin_headers(member["id"]))
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_grant_application -> {resp.status_code}: {resp.text}")
    return data


def submit_application(application, member) -> dict:
    resp = api_client.submit_application(application["id"], make_member_admin_headers(member["id"]))
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: submit_application -> {resp.status_code}: {resp.text}")
    return data


def advance_cycle_to_awarded(cycle, score_applications=None, reviewer_user_id="go-reviewer-1") -> dict:
    """OPEN -> FORMULA_LOCKED -> COMPETITIVE_REVIEW -> (score apps) -> AWARDED."""
    resp = api_client.lock_formula(cycle["id"], OFFICER)
    cycle = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: lock_formula -> {resp.status_code}: {resp.text}")
    resp = api_client.open_competitive_review(cycle["id"], OFFICER)
    cycle = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: open_competitive_review -> {resp.status_code}: {resp.text}")
    for app, score in (score_applications or []):
        resp = api_client.score_application(
            app["id"], {"review_score": score}, build_user_headers(reviewer_user_id, "GrantOfficer"))
        if resp.status_code >= 400:
            pytest.fail(f"Setup failed: score_application -> {resp.status_code}: {resp.text}")
    resp = api_client.finalize_cycle(cycle["id"], OFFICER)
    cycle = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: finalize_cycle -> {resp.status_code}: {resp.text}")
    return cycle


def award_application(application, approver_user_id="go-approver-1") -> dict:
    resp = api_client.award_application(
        application["id"], build_user_headers(approver_user_id, "GrantOfficer"))
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: award_application -> {resp.status_code}: {resp.text}")
    return data


def activate_award(award, additional_match_cents=0) -> dict:
    """Verify match (optional) then activate with a fresh expected version."""
    if additional_match_cents:
        resp = api_client.verify_match(
            award["id"], {"additional_match_cents": additional_match_cents}, OFFICER)
        award = get_success_data(resp)
        if resp.status_code >= 400:
            pytest.fail(f"Setup failed: verify_match -> {resp.status_code}: {resp.text}")
    resp = api_client.activate_award(
        award["id"], {"expected_award_version": award["version"]}, OFFICER)
    award = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: activate_award -> {resp.status_code}: {resp.text}")
    return award


def post_disbursement(award_id, amount_cents) -> dict:
    payload = create_disbursement_payload(award_id=award_id, amount_cents=amount_cents)
    resp = api_client.create_disbursement(payload, OFFICER)
    disb = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_disbursement -> {resp.status_code}: {resp.text}")
    resp = api_client.post_disbursement(disb["id"], OFFICER)
    disb = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: post_disbursement -> {resp.status_code}: {resp.text}")
    return disb


def setup_cycle_with_award(
        member, fiscal_year=2030,
        formula_pool_cents=500000, competitive_pool_cents=0,
        requested_formula_cents=50000, requested_competitive_cents=0,
        pledged_match_cents=20000, review_score=None,
        verify_match_cents=None, activate=True,
        program_area="HOMEOWNERSHIP"):
    """Full grant lifecycle for one CHARTERED member.
    Returns (cycle, application, award)."""
    cycle = create_grant_cycle(
        fiscal_year=fiscal_year, formula_pool_cents=formula_pool_cents,
        competitive_pool_cents=competitive_pool_cents)
    application = create_grant_application(
        cycle, member, program_area=program_area,
        requested_formula_cents=requested_formula_cents,
        requested_competitive_cents=requested_competitive_cents,
        pledged_match_cents=pledged_match_cents)
    application = submit_application(application, member)
    scored = [(application, review_score)] if review_score is not None else []
    cycle = advance_cycle_to_awarded(cycle, scored)
    award = award_application(application)
    if verify_match_cents is not None or activate:
        award = activate_award(award, additional_match_cents=verify_match_cents or 0)
    return cycle, application, award


def setup_active_award_with_disbursement(
        fiscal_year=2030, formula_pool_cents=500000, competitive_pool_cents=500000,
        requested_formula_cents=60000, requested_competitive_cents=50000,
        review_score=80, verify_match_cents=25000, disburse_amount=80000,
        member_overrides=None, course_code="HO-401", **assessment_kwargs):
    """CHARTERED member with an ACTIVE award and one POSTED disbursement.
    Returns (member, cycle, award)."""
    member, _counselor, _cert = setup_chartered_member_with_counselor(
        member_overrides=member_overrides, program_area="HOMEOWNERSHIP",
        course_code=course_code, **assessment_kwargs)
    cycle, _app, award = setup_cycle_with_award(
        member, fiscal_year=fiscal_year,
        formula_pool_cents=formula_pool_cents,
        competitive_pool_cents=competitive_pool_cents,
        requested_formula_cents=requested_formula_cents,
        requested_competitive_cents=requested_competitive_cents,
        review_score=review_score, verify_match_cents=verify_match_cents,
        activate=True)
    post_disbursement(award["id"], disburse_amount)
    resp = api_client.get_grant_award(award["id"], OFFICER)
    award = get_success_data(resp)
    return member, cycle, award


# ---------------------------------------------------------------------------
# Tier 4: expenditure / audit chain
# ---------------------------------------------------------------------------

def submit_expenditure_report(award, member, **overrides) -> dict:
    payload = create_expenditure_report_payload(award_id=award["id"], **overrides)
    resp = api_client.create_expenditure_report(payload, make_member_admin_headers(member["id"]))
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_expenditure_report -> {resp.status_code}: {resp.text}")
    return data


def flag_report_and_get_audit(report) -> tuple:
    """Flag a SUBMITTED report; returns (flagged_report, audit)."""
    resp = api_client.flag_expenditure_report(report["id"], OFFICER)
    report = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: flag_expenditure_report -> {resp.status_code}: {resp.text}")
    resp = api_client.list_compliance_audits(AUDITOR, params={"award_id": report["award_id"]})
    body = get_success_data(resp)
    if resp.status_code >= 400 or not body:
        pytest.fail(f"Setup failed: list_compliance_audits -> {resp.status_code}: {resp.text}")
    return report, body[0]


def issue_audit_findings(audit, disallowance_cents) -> dict:
    resp = api_client.issue_audit_findings(
        audit["id"], {"disallowance_cents": disallowance_cents}, AUDITOR)
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: issue_audit_findings -> {resp.status_code}: {resp.text}")
    return data


# ---------------------------------------------------------------------------
# Tier 5: client files / reviews / performance reviews / probation
# ---------------------------------------------------------------------------

def create_client_file(member, counselor, **overrides) -> dict:
    payload = create_client_file_payload(
        member_id=member["id"], counselor_id=counselor["id"], **overrides)
    resp = api_client.create_client_file(payload, make_member_admin_headers(member["id"]))
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_client_file -> {resp.status_code}: {resp.text}")
    return data


def begin_counseling(client_file, member) -> dict:
    resp = api_client.begin_counseling(client_file["id"], make_member_admin_headers(member["id"]))
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: begin_counseling -> {resp.status_code}: {resp.text}")
    return data


def record_outcome(client_file, member, outcome_code="PURCHASED_HOME", counseling_hours=3.0) -> dict:
    resp = api_client.record_outcome(
        client_file["id"], {"outcome_code": outcome_code, "counseling_hours": counseling_hours},
        make_member_admin_headers(member["id"]))
    data = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: record_outcome -> {resp.status_code}: {resp.text}")
    return data


def setup_member_in_probation(member_overrides=None, course_code="FP-101",
                              review_period="FY2031-H1", escalate_at="2027-01-01T00:00:00Z",
                              **assessment_kwargs):
    """CHARTERED member escalated to PROBATION via an overdue corrective plan.
    Returns (member, counselor, certification, performance_review)."""
    member, counselor, certification = setup_chartered_member_with_counselor(
        member_overrides=member_overrides, program_area="FORECLOSURE_PREVENTION",
        course_code=course_code, **assessment_kwargs)
    resp = api_client.create_performance_review(
        {"member_id": member["id"], "review_period": review_period}, DIRECTOR)
    review = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: create_performance_review -> {resp.status_code}: {resp.text}")
    resp = api_client.score_performance_review(review["id"], {"review_score": 30}, DIRECTOR)
    review = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: score_performance_review -> {resp.status_code}: {resp.text}")
    resp = api_client.resolve_performance_review(review["id"], {"verdict": "CORRECTIVE_ACTION"}, DIRECTOR)
    review = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: resolve_performance_review -> {resp.status_code}: {resp.text}")
    set_clock(escalate_at)
    resp = api_client.escalate_performance_review(review["id"], DIRECTOR)
    review = get_success_data(resp)
    if resp.status_code >= 400:
        pytest.fail(f"Setup failed: escalate_performance_review -> {resp.status_code}: {resp.text}")
    resp = api_client.get_member(member["id"], DIRECTOR)
    member = get_success_data(resp)
    return member, counselor, certification, review
