"""Payload factories — one per entity, input fields only.

Field names match PRD.md verbatim. Defaults reflect the standard test cycle
shape used across the workflow narratives (a four-component cycle with one
ASSESSMENT component and weights summing to exactly 1.000). Date defaults are
on/after the logical clock startup default (2026-09-01T00:00:00Z, PRD §2.4).

Optional fields are OMITTED from the payload unless explicitly supplied, so
server-side defaults (fte_fraction 1.0, max_attempts_per_component 2,
tolerance 0.25, early_bird_multiplier 1.10) are exercised as the PRD declares.
Passing a field as None keeps it omitted; pass an explicit value to send it.
"""
import itertools
import uuid

from .constants import DEFAULT_MAX_ATTEMPTS_PER_COMPONENT

# ---------------------------------------------------------------------------
# Standard fixture defaults (test-construction conveniences, NOT PRD rules)
# ---------------------------------------------------------------------------
STANDARD_CYCLE_CODE = "NB-2027"
STANDARD_WINDOW_OPEN = "2027-01-01T00:00:00Z"
STANDARD_WINDOW_CLOSE = "2027-03-01T00:00:00Z"
STANDARD_RETAKE_CLOSE = "2027-04-15T00:00:00Z"
STANDARD_CERTIFICATION_THRESHOLD = 1.75
STANDARD_COMPONENT_CODES = ("CKA", "P1", "P2", "P3")
STANDARD_ASSESSMENT_COMPONENT = "CKA"
STANDARD_PORTFOLIO_COMPONENTS = ("P1", "P2", "P3")

# Clock instants used by the standard pipelines: a workday inside the
# submission window, and a slot/completion pair satisfying "strictly after
# now" at booking time and ">= slot_start_at" at completion time.
STANDARD_WORK_CLOCK = "2027-01-10T00:00:00Z"
STANDARD_SLOT_START = "2027-01-20T14:00:00Z"
STANDARD_COMPLETION_CLOCK = "2027-01-20T15:00:00Z"

_counter = itertools.count(1)


def _tag() -> str:
    """Short unique suffix so multiple entities in one test never collide on
    unique fields (candidate/assessor email, cycle code)."""
    return f"{next(_counter)}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# CertificationCycle
# ---------------------------------------------------------------------------
def cycle_component(code: str, kind: str, weight: float) -> dict:
    return {"code": code, "kind": kind, "weight": weight}


def standard_cycle_components() -> list:
    """One ASSESSMENT component plus three PORTFOLIO components; weights sum
    to exactly 1.000 (PRD §3.1)."""
    return [
        cycle_component("CKA", "ASSESSMENT", 0.40),
        cycle_component("P1", "PORTFOLIO", 0.20),
        cycle_component("P2", "PORTFOLIO", 0.20),
        cycle_component("P3", "PORTFOLIO", 0.20),
    ]


def create_cycle_payload(**overrides) -> dict:
    payload = {
        "code": f"{STANDARD_CYCLE_CODE}-{_tag()}",
        "components": standard_cycle_components(),
        "submission_window_open": STANDARD_WINDOW_OPEN,
        "submission_window_close": STANDARD_WINDOW_CLOSE,
        "retake_window_close": STANDARD_RETAKE_CLOSE,
        "certification_threshold": STANDARD_CERTIFICATION_THRESHOLD,
        "max_attempts_per_component": DEFAULT_MAX_ATTEMPTS_PER_COMPONENT,
    }
    for key, value in overrides.items():
        if value is None and key == "max_attempts_per_component":
            payload.pop(key, None)  # explicit omission -> exercise the default
        else:
            payload[key] = value
    return payload


def cycle_transition_payload(to: str) -> dict:
    return {"to": to}


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------
def create_candidate_payload(**overrides) -> dict:
    tag = _tag()
    payload = {
        "full_name": f"Candidate {tag}",
        "email": f"cand-{tag}@example.com",
        "license_number": f"LIC-{tag}",
        "license_state": "NM",
        "district_code": "D-100",
        "years_experience": 5,
    }
    payload.update(overrides)
    # fte_fraction is optional (default 1.0); drop when explicitly None.
    if payload.get("fte_fraction") is None:
        payload.pop("fte_fraction", None)
    return payload


def eligibility_evidence_payload(
    license_document_ref: str = "license.pdf",
    employer_verification_ref: str = "employer.pdf",
) -> dict:
    return {
        "license_document_ref": license_document_ref,
        "employer_verification_ref": employer_verification_ref,
    }


def verify_eligibility_payload(decision: str = "APPROVE", note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


# ---------------------------------------------------------------------------
# CalibrationBenchmark
# ---------------------------------------------------------------------------
def create_benchmark_payload(
    component_code: str = "P1",
    content_domain: str = "math",
    known_score: float = 3.00,
    tolerance=None,
) -> dict:
    payload = {
        "component_code": component_code,
        "content_domain": content_domain,
        "known_score": known_score,
    }
    if tolerance is not None:
        payload["tolerance"] = tolerance
    return payload


# ---------------------------------------------------------------------------
# Assessor
# ---------------------------------------------------------------------------
def create_assessor_payload(**overrides) -> dict:
    tag = _tag()
    payload = {
        "full_name": f"Reader {tag}",
        "email": f"reader-{tag}@example.com",
        "home_district_code": "D-900",
    }
    payload.update(overrides)
    return payload


def assessor_transition_payload(to: str) -> dict:
    return {"to": to}


# ---------------------------------------------------------------------------
# AssessmentCenter / AssessmentBooking
# ---------------------------------------------------------------------------
def create_assessment_center_payload(
    name: str = None,
    region_code: str = "NW",
    slot_capacity: int = 5,
) -> dict:
    return {
        "name": name or f"Center {_tag()}",
        "region_code": region_code,
        "slot_capacity": slot_capacity,
    }


def create_booking_payload(
    center_id: str,
    cycle_id: str,
    slot_start_at: str = STANDARD_SLOT_START,
) -> dict:
    return {
        "center_id": center_id,
        "cycle_id": cycle_id,
        "slot_start_at": slot_start_at,
    }


def booking_transition_payload(to: str, earned_score=None) -> dict:
    payload = {"to": to}
    if earned_score is not None:
        payload["earned_score"] = earned_score
    return payload


# ---------------------------------------------------------------------------
# ComponentSubmission
# ---------------------------------------------------------------------------
def create_submission_payload(component_code: str) -> dict:
    return {"component_code": component_code}


def tech_review_payload(decision: str = "ACCEPT", note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------
def video_artifact_payload(
    file_format: str = "mp4",
    file_size_mb: float = 120,
    duration_minutes: float = 10,
    subject_student_count=None,
) -> dict:
    """A compliant VIDEO artifact: mp4, under 500 MB, under 15 minutes.
    PRD §3.3: subject_student_count "must be at least 1 when supplied", so the
    field is omitted entirely unless a count of 1 or more is requested."""
    payload = {
        "artifact_type": "VIDEO",
        "file_format": file_format,
        "file_size_mb": file_size_mb,
        "duration_minutes": duration_minutes,
    }
    if subject_student_count is not None:
        payload["subject_student_count"] = subject_student_count
    return payload


def document_artifact_payload(
    artifact_type: str = "WRITTEN_COMMENTARY",
    file_format: str = "pdf",
    file_size_mb: float = 2,
    subject_student_count=None,
) -> dict:
    """A compliant document artifact (WRITTEN_COMMENTARY / STUDENT_WORK /
    RELEASE_FORM): pdf, under 50 MB."""
    payload = {
        "artifact_type": artifact_type,
        "file_format": file_format,
        "file_size_mb": file_size_mb,
    }
    if subject_student_count is not None:
        payload["subject_student_count"] = subject_student_count
    return payload


def release_form_artifact_payload(file_format: str = "pdf", file_size_mb: float = 1) -> dict:
    return document_artifact_payload(
        artifact_type="RELEASE_FORM",
        file_format=file_format,
        file_size_mb=file_size_mb,
    )


def minimal_portfolio_artifact_payloads(subject_student_count=None) -> list:
    """The minimal compliant portfolio set: one WRITTEN_COMMENTARY plus one
    VIDEO reporting no student count (no RELEASE_FORM required — the §3.3 gate
    fires only when a count of 1 or more is reported)."""
    return [
        document_artifact_payload("WRITTEN_COMMENTARY"),
        video_artifact_payload(subject_student_count=subject_student_count),
    ]


# ---------------------------------------------------------------------------
# ScoringAssignment
# ---------------------------------------------------------------------------
def create_assignment_payload(submission_id=None, benchmark_id=None, assessor_id=None) -> dict:
    """Exactly one of submission_id / benchmark_id must be non-null; omitting
    assessor_id invokes the assessor selector policy."""
    payload = {}
    if submission_id is not None:
        payload["submission_id"] = submission_id
    if benchmark_id is not None:
        payload["benchmark_id"] = benchmark_id
    if assessor_id is not None:
        payload["assessor_id"] = assessor_id
    return payload


def submit_score_payload(score: float) -> dict:
    return {"score": score}


# ---------------------------------------------------------------------------
# RenewalApplication
# ---------------------------------------------------------------------------
def evidence_item(evidence_type: str, description: str, hours: float) -> dict:
    return {
        "evidence_type": evidence_type,
        "description": description,
        "hours": hours,
    }


def create_renewal_payload(evidence_items=None, total_hours: float = 45.0) -> dict:
    """A renewal application carrying >= 1 evidence item. By default a single
    item whose hours equal total_hours (45 passes the approval gate)."""
    if evidence_items is None:
        evidence_items = [
            evidence_item("WORKSHOP", f"{total_hours:g}h workshop series", total_hours)
        ]
    return {"evidence_items": evidence_items}


def review_renewal_payload(decision: str = "APPROVE", note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return payload


# ---------------------------------------------------------------------------
# IncentiveProgram / StipendPayment
# ---------------------------------------------------------------------------
def create_incentive_program_payload(
    name: str = None,
    sponsor_state: str = "NM",
    budget_total_cents: int = 500000,
    base_stipend_cents: int = 300000,
    sponsor_district_code=None,
    early_bird_multiplier=None,
    early_bird_deadline=None,
) -> dict:
    """Statewide program by default (sponsor_district_code omitted -> null).
    early_bird_multiplier defaults server-side to 1.10 when omitted."""
    payload = {
        "name": name or f"Program {_tag()}",
        "sponsor_state": sponsor_state,
        "budget_total_cents": budget_total_cents,
        "base_stipend_cents": base_stipend_cents,
    }
    if sponsor_district_code is not None:
        payload["sponsor_district_code"] = sponsor_district_code
    if early_bird_multiplier is not None:
        payload["early_bird_multiplier"] = early_bird_multiplier
    if early_bird_deadline is not None:
        payload["early_bird_deadline"] = early_bird_deadline
    return payload


def stipend_transition_payload(to: str) -> dict:
    return {"to": to}
