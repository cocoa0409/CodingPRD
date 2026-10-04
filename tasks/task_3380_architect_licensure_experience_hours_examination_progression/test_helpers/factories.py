"""Payload factories — input fields only (PRD §3), unique values per call."""
import uuid


def _tag() -> str:
    return uuid.uuid4().hex[:8]


def create_jurisdiction_payload(**overrides) -> dict:
    """PRD §3.1: code and name required; four optional national-standard
    overrides (requires_supplemental_exam, min_total_experience_hours,
    ce_hours_required, ce_hsw_hours_required, ce_carry_over_allowed)."""
    defaults = {
        "code": f"J{_tag()}".upper()[:8],
        "name": "Board One",
    }
    defaults.update(overrides)
    return defaults


def create_candidate_payload(**overrides) -> dict:
    """PRD §3.1: email, full_name, password, home_jurisdiction_code."""
    defaults = {
        "email": f"cand-{_tag()}@example.com",
        "full_name": "Cand One",
        "password": "pw",
        "home_jurisdiction_code": "J1",
    }
    defaults.update(overrides)
    return defaults


def create_supervisor_payload(**overrides) -> dict:
    """PRD §3.1: full_name, unique license_number, jurisdiction_code."""
    defaults = {
        "full_name": "Sup One",
        "license_number": f"LIC-{_tag()}".upper(),
        "jurisdiction_code": "J1",
    }
    defaults.update(overrides)
    return defaults


def create_education_evaluation_payload(**overrides) -> dict:
    """PRD §3.2: path_type, institution_name, semester_credit_hours."""
    defaults = {
        "path_type": "ACCREDITED_DEGREE",
        "institution_name": "State U",
        "semester_credit_hours": 150,
    }
    defaults.update(overrides)
    return defaults


def create_experience_report_payload(**overrides) -> dict:
    """PRD §3.3: candidate_id, supervisor_id, practice_area, hours,
    work_period_start, work_period_end; work_setting optional."""
    defaults = {
        "candidate_id": "",
        "supervisor_id": "",
        "practice_area": "PRACTICE_MANAGEMENT",
        "hours": 40,
        "work_period_start": "2026-01-05",
        "work_period_end": "2026-02-02",
    }
    defaults.update(overrides)
    return defaults


def create_ce_entry_payload(**overrides) -> dict:
    """PRD §3.7: hours (1..24), hsw, completed_date, provider."""
    defaults = {
        "hours": 6,
        "hsw": True,
        "completed_date": "2026-10-06",
        "provider": "AIA",
    }
    defaults.update(overrides)
    return defaults


def create_supplemental_exam_payload(**overrides) -> dict:
    """PRD §3.5: jurisdiction_code, exam_date."""
    defaults = {
        "jurisdiction_code": "JX",
        "exam_date": "2026-10-01",
    }
    defaults.update(overrides)
    return defaults


def create_transmittal_payload(**overrides) -> dict:
    """PRD §3.8: jurisdiction_code."""
    defaults = {"jurisdiction_code": "J2"}
    defaults.update(overrides)
    return defaults


def create_disciplinary_report_payload(**overrides) -> dict:
    """PRD §3.8: candidate_id, jurisdiction_code, non-empty allegation."""
    defaults = {
        "candidate_id": "",
        "jurisdiction_code": "J1",
        "allegation": "stamping unsupervised work",
    }
    defaults.update(overrides)
    return defaults
