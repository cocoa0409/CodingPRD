"""Composite setup helpers. Each fixture builds its preconditions from scratch
using only PRD-declared endpoints; the server is restarted (empty database)
before every test, so fixtures never rely on leftover state.

Setup calls use get_success_data() so a setup failure surfaces as a clear
"Setup failed" assertion instead of a confusing downstream error.

Entity-backed roles (Instructor, Student) always thread the real entity id
into the role headers via make_instructor_headers / make_student_headers —
never the shared TEST_USERS constants — because ownership checks compare
X-User-ID against the entity's id (PRD §2.1).
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_ISO
from .factories import (
    create_assignment_payload,
    create_institution_payload,
    create_instructor_payload,
    create_lms_integration_payload,
    create_source_document_payload,
    create_student_payload,
    words,
)
from .test_users import (
    TEST_USERS,
    make_instructor_headers,
    make_student_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INST_ADMIN = TEST_USERS["institutional_admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity helpers
# ---------------------------------------------------------------------------

def reset_clock(to_iso8601: str = DEFAULT_CLOCK_ISO):
    """Pin the logical clock (PRD §2.4)."""
    resp = api_client.set_clock(to_iso8601, ADMIN)
    assert resp.status_code == 200, f"Setup failed: set_clock -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_institution(**overrides):
    """Create an institution; returns the institution dict."""
    resp = api_client.create_institution(create_institution_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_institution -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_active_integration(institution_id: str, **overrides):
    """Create an LmsIntegration and activate it (PENDING -> ACTIVE)."""
    resp = api_client.create_lms_integration(
        institution_id, create_lms_integration_payload(**overrides), ADMIN
    )
    assert resp.status_code == 201, f"Setup failed: create_lms_integration -> {resp.status_code} {resp.text}"
    integration = get_success_data(resp)
    resp = api_client.activate_integration(integration["id"], ADMIN)
    assert resp.status_code == 200, f"Setup failed: activate_integration -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_instructor(institution_id: str, **overrides):
    resp = api_client.create_instructor(institution_id, create_instructor_payload(**overrides), ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_instructor -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_student(institution_id: str, **overrides):
    region = overrides.pop("home_region", None) or overrides.get("residency_region") or "US"
    payload = create_student_payload(home_region=region, **overrides)
    resp = api_client.create_student(institution_id, payload, ADMIN)
    assert resp.status_code == 201, f"Setup failed: create_student -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def grant_consent(student_id: str, version: int):
    """GRANT consent for a student; returns the updated student dict."""
    resp = api_client.record_consent(
        student_id,
        {"expected_student_version": version, "consent_action": "GRANT"},
        make_student_headers(student_id),
    )
    assert resp.status_code == 200, f"Setup failed: GRANT consent -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def withdraw_consent(student_id: str, version: int):
    resp = api_client.record_consent(
        student_id,
        {"expected_student_version": version, "consent_action": "WITHDRAW"},
        make_student_headers(student_id),
    )
    assert resp.status_code == 200, f"Setup failed: WITHDRAW consent -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_assignment(integration_id: str, instructor_id: str, **overrides):
    """Create an assignment under an ACTIVE integration (instructor-owned)."""
    resp = api_client.create_assignment(
        integration_id,
        create_assignment_payload(instructor_id, **overrides),
        make_instructor_headers(instructor_id),
    )
    assert resp.status_code == 201, f"Setup failed: create_assignment -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def submit(assignment_id: str, student_id: str, content_text: str, **overrides):
    """Student intake; returns the created submission dict."""
    payload = {"student_id": student_id, "content_text": content_text}
    payload.update(overrides)
    resp = api_client.create_submission(assignment_id, payload, make_student_headers(student_id))
    assert resp.status_code == 201, f"Setup failed: create_submission -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def process(submission_id: str, instructor_id: str):
    """Run the comparison pipeline; returns the updated submission dict."""
    resp = api_client.process_submission(submission_id, make_instructor_headers(instructor_id))
    assert resp.status_code == 200, f"Setup failed: process_submission -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_source(institution_id: str, **overrides):
    resp = api_client.create_source_document(
        institution_id, create_source_document_payload(**overrides), ADMIN
    )
    assert resp.status_code == 201, f"Setup failed: create_source_document -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def inject_fragment(submission_id: str, source_id: str, matched_word_count: int,
                    match_category: str, offset_start: int):
    """Inject a deterministic fragment; returns the fragment dict."""
    resp = api_client.inject_match(
        {
            "submission_id": submission_id,
            "source_document_id": source_id,
            "matched_word_count": matched_word_count,
            "match_category": match_category,
            "offset_start": offset_start,
        },
        ADMIN,
    )
    assert resp.status_code == 201, f"Setup failed: inject_match -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_report(submission_id: str, instructor_id: str):
    """Fetch the submission's single SimilarityReport (array of 0..1)."""
    resp = api_client.list_similarity_reports(submission_id, make_instructor_headers(instructor_id))
    assert resp.status_code == 200, f"Setup failed: list_similarity_reports -> {resp.status_code} {resp.text}"
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, f"Setup failed: expected 1 report, got {data}"
    return data[0]


def get_assessment(submission_id: str, instructor_id: str):
    resp = api_client.list_ai_assessments(submission_id, make_instructor_headers(instructor_id))
    assert resp.status_code == 200, f"Setup failed: list_ai_assessments -> {resp.status_code} {resp.text}"
    data = get_success_data(resp)
    assert isinstance(data, list) and len(data) == 1, f"Setup failed: expected 1 assessment, got {data}"
    return data[0]


def finalize_report(report_id: str, instructor_id: str, interpretation: str = "NOT_MISCONDUCT"):
    resp = api_client.finalize_report(
        report_id, {"instructor_interpretation": interpretation}, make_instructor_headers(instructor_id)
    )
    assert resp.status_code == 200, f"Setup failed: finalize_report -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def create_grade(submission_id: str, instructor_id: str, score_points=50, **overrides):
    payload = {"score_points": score_points}
    payload.update(overrides)
    resp = api_client.create_grade_entry(submission_id, payload, make_instructor_headers(instructor_id))
    assert resp.status_code == 201, f"Setup failed: create_grade_entry -> {resp.status_code} {resp.text}"
    return get_success_data(resp)


def get_assignment_version(assignment_id: str, instructor_id: str) -> int:
    resp = api_client.get_assignment(assignment_id, make_instructor_headers(instructor_id))
    assert resp.status_code == 200, f"Setup failed: get_assignment -> {resp.status_code} {resp.text}"
    return get_success_data(resp)["version"]


# ---------------------------------------------------------------------------
# Tier 2: hierarchy builders
# ---------------------------------------------------------------------------

def setup_institution_with_active_integration(region: str = "US", inst_overrides=None,
                                              integ_overrides=None):
    """Institution + one ACTIVE integration. Returns (institution, integration)."""
    inst = create_institution(**(dict(residency_region=region, **(inst_overrides or {}))))
    integ = create_active_integration(inst["id"], **(integ_overrides or {}))
    return inst, integ


def setup_basic_scenario(region: str = "US", inst_overrides=None, integ_overrides=None,
                         assignment_overrides=None, consent: bool = True,
                         student_overrides=None):
    """Institution + ACTIVE integration + instructor + student + assignment.

    Returns (inst, integ, instr, student, assignment).
    When consent=True the student's consent is GRANTED (required by STRICT
    intake). The student's home_region defaults to the institution region.
    """
    inst, integ = setup_institution_with_active_integration(region, inst_overrides, integ_overrides)
    instr = create_instructor(inst["id"])
    so = dict(student_overrides or {})
    so.setdefault("home_region", region)
    student = create_student(inst["id"], **so)
    asg = create_assignment(integ["id"], instr["id"], **(assignment_overrides or {}))
    if consent:
        grant_consent(student["id"], student["version"])
    return inst, integ, instr, student, asg


def setup_processed_submission(region: str = "US", content_text: str = "alpha beta gamma",
                               inst_overrides=None, integ_overrides=None,
                               assignment_overrides=None, submission_overrides=None):
    """Full happy path: scenario + one submission processed to REPORT_READY.

    Returns (inst, integ, instr, student, asg, submission).
    """
    inst, integ, instr, student, asg = setup_basic_scenario(
        region, inst_overrides, integ_overrides, assignment_overrides
    )
    sub = submit(asg["id"], student["id"], content_text, **(submission_overrides or {}))
    process(sub["id"], instr["id"])
    return inst, integ, instr, student, asg, sub


def setup_finalized_report(region: str = "US", content_text: str = "alpha beta gamma",
                           assignment_overrides=None, interpretation: str = "NOT_MISCONDUCT"):
    """Scenario + processed submission + grade entry + FINALIZED report.

    Returns (inst, integ, instr, student, asg, submission, report, grade).
    """
    inst, integ, instr, student, asg, sub = setup_processed_submission(
        region, content_text, assignment_overrides=assignment_overrides
    )
    grade = create_grade(sub["id"], instr["id"])
    report = get_report(sub["id"], instr["id"])
    finalize_report(report["id"], instr["id"], interpretation)
    report = get_report(sub["id"], instr["id"])
    return inst, integ, instr, student, asg, sub, report, grade


# ---------------------------------------------------------------------------
# Tier 4: fragment/source scenario builders
# ---------------------------------------------------------------------------

def inject_fragments(submission_id: str, fragments):
    """Inject many fragments. Each item: (source_id, matched_word_count,
    match_category, offset_start). Returns the fragment dicts in order."""
    return [inject_fragment(submission_id, src, wc, cat, off) for src, wc, cat, off in fragments]


def create_sources(institution_id: str, count: int, region: str = "US", source_type: str = "INTERNET"):
    return [
        create_source(institution_id, source_type=source_type, uri=f"https://src.example/{uuid.uuid4()}",
                      region=region)
        for _ in range(count)
    ]

