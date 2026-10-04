"""Payload factories — one per creation/action payload, input fields only.

Only ``source: input`` fields appear here; system-stamped and computed
fields are never sent. Optional inputs (``descriptor``,
``lead_credential_id``, ``supervisor_credential_id``, ``visit_id``,
``hours_earned``, ``notes``, ``reason``) are included only when a non-None
value is supplied, so the server-side default (null / omission) is never
masked by the factory.

Uniqueness: ``display_name`` is unique case-insensitively across schools
and catalog ``version_label`` is unique, so display names and free-text
labels carry a monotonically increasing suffix by default. The catalog
payload default is the frozen test edition whose per-level numbers the
test recipes assert against (540 practicum hours and 180 work minutes for
EARLY_CHILDHOOD, 30 CE hours, 36 validity months, 3 window months, 6 grace
months, 12 tenure months, 1 travel-buffer day, 30 plan days).
"""

import itertools

from .constants import (
    CLOCK_START_ISO,
    MIN_DUES_CENTS,
    RENEWAL_BASE_FEE_CENTS,
)

_counter = itertools.count(1)


def _suffix() -> str:
    return "{0:04d}".format(next(_counter))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def set_clock_payload(to_iso8601: str = CLOCK_START_ISO, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Standards catalog — the frozen test edition ("Standards 2026")
# ---------------------------------------------------------------------------
def create_standards_catalog_payload(**overrides) -> dict:
    payload = {
        "version_label": "Standards 2026",
        "effective_from": "2026-01-01",
        "min_uninterrupted_work_minutes_by_level": {
            "INFANT_TODDLER": 90,
            "EARLY_CHILDHOOD": 180,
            "ELEMENTARY_I": 180,
            "ELEMENTARY_II": 180,
            "SECONDARY": 120,
        },
        "max_students_per_adult_by_level": {
            "INFANT_TODDLER": 5,
            "EARLY_CHILDHOOD": 15,
            "ELEMENTARY_I": 15,
            "ELEMENTARY_II": 16,
            "SECONDARY": 20,
        },
        "materials_pass_threshold": 0.9,
        "min_multi_age_span_years_by_level": {
            "INFANT_TODDLER": 2,
            "EARLY_CHILDHOOD": 3,
            "ELEMENTARY_I": 3,
            "ELEMENTARY_II": 3,
            "SECONDARY": 2,
        },
        "practicum_min_hours_by_level": {
            "INFANT_TODDLER": 300,
            "EARLY_CHILDHOOD": 540,
            "ELEMENTARY_I": 540,
            "ELEMENTARY_II": 540,
            "SECONDARY": 400,
        },
        "ce_hours_required": 30,
        "credential_validity_months": 36,
        "renewal_window_months": 3,
        "renewal_grace_months": 6,
        "min_membership_months_before_accreditation": 12,
        "consultant_travel_buffer_days": 1,
        "plan_response_days": 30,
    }
    payload.update(overrides)
    return payload


def create_next_catalog_payload(**overrides) -> dict:
    """The successor edition used by catalog-ordering and pinning probes:
    later effective_from, higher EARLY_CHILDHOOD/ELEMENTARY work-period and
    practicum bars (200 minutes / 600 hours) so the two editions diverge."""
    payload = create_standards_catalog_payload(
        version_label="Standards 2027",
        effective_from="2027-01-01",
        min_uninterrupted_work_minutes_by_level={
            "INFANT_TODDLER": 90,
            "EARLY_CHILDHOOD": 200,
            "ELEMENTARY_I": 200,
            "ELEMENTARY_II": 200,
            "SECONDARY": 120,
        },
        practicum_min_hours_by_level={
            "INFANT_TODDLER": 300,
            "EARLY_CHILDHOOD": 600,
            "ELEMENTARY_I": 600,
            "ELEMENTARY_II": 600,
            "SECONDARY": 400,
        },
    )
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Schools, brand, dues, standing
# ---------------------------------------------------------------------------
def create_school_payload(**overrides) -> dict:
    tag = _suffix()
    descriptor = overrides.pop("descriptor", None)
    payload = {
        "name": overrides.pop("name", "Test School {0}".format(tag)),
        "display_name": overrides.pop("display_name", "Schoolhouse {0}".format(tag)),
        "uses_method_name": overrides.pop("uses_method_name", False),
        "contact_email": overrides.pop("contact_email", "school-{0}@example.org".format(tag)),
    }
    if descriptor is not None:
        payload["descriptor"] = descriptor
    payload.update(overrides)
    return payload


def update_brand_payload(**overrides) -> dict:
    descriptor = overrides.pop("descriptor", None)
    payload = {
        "display_name": overrides.pop("display_name", "Schoolhouse {0}".format(_suffix())),
        "uses_method_name": overrides.pop("uses_method_name", False),
    }
    if descriptor is not None:
        payload["descriptor"] = descriptor
    payload.update(overrides)
    return payload


def record_dues_payment_payload(**overrides) -> dict:
    payload = {
        "period_start": overrides.pop("period_start", "2026-09-01"),
        "period_end": overrides.pop("period_end", "2027-09-01"),
        "amount_cents": overrides.pop("amount_cents", MIN_DUES_CENTS),
    }
    payload.update(overrides)
    return payload


def set_standing_payload(to_standing: str, **overrides) -> dict:
    reason = overrides.pop("reason", None)
    payload = {"to_standing": to_standing}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Classrooms, transfers, audits
# ---------------------------------------------------------------------------
def create_classroom_payload(school_id: str, **overrides) -> dict:
    lead = overrides.pop("lead_credential_id", None)
    payload = {
        "school_id": school_id,
        "name": overrides.pop("name", "Room {0}".format(_suffix())),
        "age_level": overrides.pop("age_level", "EARLY_CHILDHOOD"),
        "declared_age_span_years": overrides.pop("declared_age_span_years", 3),
        "enrolled_student_count": overrides.pop("enrolled_student_count", 20),
        "assistant_count": overrides.pop("assistant_count", 1),
    }
    if lead is not None:
        payload["lead_credential_id"] = lead
    payload.update(overrides)
    return payload


def transfer_students_payload(to_classroom_id: str, student_count: int, **overrides) -> dict:
    payload = {"to_classroom_id": to_classroom_id, "student_count": student_count}
    payload.update(overrides)
    return payload


def compliant_materials_groups() -> list:
    """Two groups at 9/10 each: per-group 0.90, mean 0.90 — exactly at the
    frozen test edition's 0.9 materials threshold, hence passing."""
    return [
        {"domain": "PRACTICAL_LIFE", "required_count": 10, "present_count": 9},
        {"domain": "SENSORIAL", "required_count": 10, "present_count": 9},
    ]


def create_classroom_audit_payload(classroom_id: str, **overrides) -> dict:
    visit_id = overrides.pop("visit_id", None)
    payload = {
        "classroom_id": classroom_id,
        "students_present": overrides.pop("students_present", 24),
        "adults_present": overrides.pop("adults_present", 2),
        "observed_uninterrupted_minutes": overrides.pop("observed_uninterrupted_minutes", 180),
        "materials_groups": overrides.pop("materials_groups", compliant_materials_groups()),
    }
    if visit_id is not None:
        payload["visit_id"] = visit_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Teacher education programs and adult learners
# ---------------------------------------------------------------------------
def create_program_payload(**overrides) -> dict:
    payload = {
        "name": overrides.pop("name", "Program {0}".format(_suffix())),
        "age_levels_offered": overrides.pop("age_levels_offered", ["EARLY_CHILDHOOD"]),
        "course_contact_hours_by_level": overrides.pop(
            "course_contact_hours_by_level", {"EARLY_CHILDHOOD": 300}
        ),
        "practicum_hours_by_level": overrides.pop(
            "practicum_hours_by_level", {"EARLY_CHILDHOOD": 540}
        ),
    }
    payload.update(overrides)
    return payload


def set_program_status_payload(to_status: str, **overrides) -> dict:
    reason = overrides.pop("reason", None)
    payload = {"to_status": to_status}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def create_adult_learner_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": overrides.pop("full_name", "Learner {0}".format(_suffix())),
        "age_level": overrides.pop("age_level", "EARLY_CHILDHOOD"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Practicum placements
# ---------------------------------------------------------------------------
DEFAULT_PLACEMENT_START_DATE = "2026-09-15"
DEFAULT_PLACEMENT_END_DATE = "2027-03-15"
DEFAULT_WORK_DATE = "2026-12-01"


def create_practicum_placement_payload(learner_id: str, host_school_id: str, **overrides) -> dict:
    supervisor = overrides.pop("supervisor_credential_id", None)
    payload = {
        "learner_id": learner_id,
        "host_school_id": host_school_id,
        "start_date": overrides.pop("start_date", DEFAULT_PLACEMENT_START_DATE),
        "end_date": overrides.pop("end_date", DEFAULT_PLACEMENT_END_DATE),
    }
    if supervisor is not None:
        payload["supervisor_credential_id"] = supervisor
    payload.update(overrides)
    return payload


def log_hours_payload(hours: int, work_date: str = DEFAULT_WORK_DATE, **overrides) -> dict:
    payload = {"hours": hours, "work_date": work_date}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
def create_credential_payload(learner_id: str, age_level: str = "EARLY_CHILDHOOD", **overrides) -> dict:
    payload = {"learner_id": learner_id, "age_level": age_level}
    payload.update(overrides)
    return payload


def renew_credential_payload(fee_cents: int = RENEWAL_BASE_FEE_CENTS, **overrides) -> dict:
    payload = {"fee_cents": fee_cents}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# School applications
# ---------------------------------------------------------------------------
def create_school_application_payload(
    school_id: str, app_type: str, expected_school_version: int, **overrides
) -> dict:
    payload = {
        "school_id": school_id,
        "type": app_type,
        "expected_school_version": expected_school_version,
    }
    payload.update(overrides)
    return payload


def review_application_payload(outcome: str, **overrides) -> dict:
    notes = overrides.pop("notes", None)
    payload = {"outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Self-studies
# ---------------------------------------------------------------------------
def create_self_study_payload(
    school_id: str, expected_school_version: int, narrative: str = None, **overrides
) -> dict:
    payload = {
        "school_id": school_id,
        "narrative": narrative if narrative is not None else "Self-study {0}".format(_suffix()),
        "expected_school_version": expected_school_version,
    }
    payload.update(overrides)
    return payload


def review_self_study_payload(outcome: str, **overrides) -> dict:
    notes = overrides.pop("notes", None)
    payload = {"outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Verification visits
# ---------------------------------------------------------------------------
DEFAULT_VISIT_WINDOW_START = "2026-10-01"
DEFAULT_VISIT_WINDOW_END = "2026-10-03"


def create_verification_visit_payload(
    school_id: str, self_study_id: str, consultant_id: str, **overrides
) -> dict:
    payload = {
        "school_id": school_id,
        "self_study_id": self_study_id,
        "consultant_id": consultant_id,
        "window_start": overrides.pop("window_start", DEFAULT_VISIT_WINDOW_START),
        "window_end": overrides.pop("window_end", DEFAULT_VISIT_WINDOW_END),
    }
    payload.update(overrides)
    return payload


def file_visit_report_payload(verdict: str = "COMPLIANT", findings=None, **overrides) -> dict:
    payload = {
        "findings": findings if findings is not None else ["All standards met"],
        "verdict": verdict,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Improvement plans
# ---------------------------------------------------------------------------
def respond_to_plan_payload(response_notes: str, expected_improvement_plan_version: int, **overrides) -> dict:
    payload = {
        "response_notes": response_notes,
        "expected_improvement_plan_version": expected_improvement_plan_version,
    }
    payload.update(overrides)
    return payload


def review_plan_payload(outcome: str, **overrides) -> dict:
    notes = overrides.pop("notes", None)
    payload = {"outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PD events and the CE ledger
# ---------------------------------------------------------------------------
DEFAULT_EVENT_START_AT = "2027-01-31T09:00:00Z"
DEFAULT_EVENT_END_AT = "2027-02-01T17:00:00Z"


def create_pd_event_payload(**overrides) -> dict:
    payload = {
        "title": overrides.pop("title", "PD Session {0}".format(_suffix())),
        "provider_name": overrides.pop("provider_name", "Society"),
        "start_at": overrides.pop("start_at", DEFAULT_EVENT_START_AT),
        "end_at": overrides.pop("end_at", DEFAULT_EVENT_END_AT),
        "ce_hours": overrides.pop("ce_hours", 18),
    }
    payload.update(overrides)
    return payload


def record_attendance_payload(credential_id: str, hours_earned=None, **overrides) -> dict:
    payload = {"credential_id": credential_id}
    if hours_earned is not None:
        payload["hours_earned"] = hours_earned
    payload.update(overrides)
    return payload
