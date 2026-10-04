"""Payload factories — one per creatable resource, input fields only.

Natural keys (series_code, announcement_number, email) get a unique suffix
per call so repeated factory use inside one test never trips the duplicate-key
rule. Default announcement open period [2026-09-05, 2026-09-20) sits after the
logical-clock startup instant of 2026-09-01T00:00:00Z, so the default sequence
create -> open -> set clock into the window is always reachable.
"""
import itertools
import uuid

_counter = itertools.count(1)


def _uniq() -> str:
    return f"{next(_counter)}-{uuid.uuid4().hex[:8]}"


# Default open period (half-open [open_at, close_at), PRD §2.9); both instants
# are after the clock's startup default so fixtures can open then apply.
DEFAULT_OPEN_AT = "2026-09-05T00:00:00Z"
DEFAULT_CLOSE_AT = "2026-09-20T00:00:00Z"


def create_series_payload(**overrides) -> dict:
    defaults = {
        "series_code": f"{(next(_counter) % 9000) + 1000:04d}",
        "title": f"Program Analyst {_uniq()}",
        "min_grade": 5,
        "max_grade": 12,
        "quals_base_months": 6,
        "quals_months_per_grade_step": 6,
        "allows_education_substitution": True,
        "education_substitution_cap_months": 12,
        "positive_education_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_position_payload(series_id: str, **overrides) -> dict:
    """Default factor levels (2,2,3,2) -> total_points 2250 -> grade 9,
    inside the default series span 5..12."""
    defaults = {
        "series_id": series_id,
        "title": f"Analyst {_uniq()}",
        "org_code": "OPM1",
        "factor_knowledge_level": 2,
        "factor_supervision_level": 2,
        "factor_complexity_level": 3,
        "factor_impact_level": 2,
        "sensitivity_level": "NONE",
    }
    defaults.update(overrides)
    return defaults


def reclassify_position_payload(expected_position_version: int, **overrides) -> dict:
    defaults = {
        "factor_knowledge_level": 2,
        "factor_supervision_level": 2,
        "factor_complexity_level": 3,
        "factor_impact_level": 2,
        "expected_position_version": expected_position_version,
    }
    defaults.update(overrides)
    return defaults


def create_announcement_payload(**overrides) -> dict:
    defaults = {
        "announcement_number": f"OPM-26-{_uniq()}",
        "area_of_consideration": "ALL_US_CITIZENS",
        "hiring_authority": "COMPETITIVE",
        "assessment_method": "CATEGORY_RATING",
        "open_at": DEFAULT_OPEN_AT,
        "close_at": DEFAULT_CLOSE_AT,
        "vacancies_count": 1,
        "bq_cut": 95,
        "wq_cut": 85,
        "certificate_validity_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Applicant {_uniq()}",
        "email": f"applicant-{_uniq()}@example.com",
        "is_us_citizen": True,
        "is_current_federal_employee": False,
        "veteran_preference_claim": "NONE",
    }
    defaults.update(overrides)
    return defaults


def upload_document_payload(doc_type: str = "DD214", **overrides) -> dict:
    defaults = {"doc_type": doc_type}
    defaults.update(overrides)
    return defaults


def submit_application_payload(applicant_id: str, **overrides) -> dict:
    """Default claim 30 experience months qualifies against the default
    series/grade-9 position (required 30)."""
    defaults = {
        "applicant_id": applicant_id,
        "claimed_experience_months": 30,
        "claimed_education_months": 0,
        "self_rating_knowledge": 3,
        "self_rating_skill": 3,
        "self_rating_ability": 3,
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(rating_knowledge: int = 5, rating_skill: int = 5,
                              rating_ability: int = 5, **overrides) -> dict:
    defaults = {
        "rating_knowledge": rating_knowledge,
        "rating_skill": rating_skill,
        "rating_ability": rating_ability,
    }
    defaults.update(overrides)
    return defaults


def submit_assessment_payload(**overrides) -> dict:
    """Empty by default (first submit keeps creation ratings); pass ratings to
    replace them on resubmission."""
    return dict(overrides)


def return_assessment_payload(return_reason: str = "needs more justification", **overrides) -> dict:
    defaults = {"return_reason": return_reason}
    defaults.update(overrides)
    return defaults


def file_appeal_payload(grounds: str = "QUALIFICATION", **overrides) -> dict:
    defaults = {"grounds": grounds}
    defaults.update(overrides)
    return defaults


def adjudicate_appeal_payload(outcome: str = "SUSTAINED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def extend_certificate_payload(additional_days: int, expected_certificate_version: int,
                               **overrides) -> dict:
    defaults = {
        "additional_days": additional_days,
        "expected_certificate_version": expected_certificate_version,
    }
    defaults.update(overrides)
    return defaults


def return_certificate_payload(**overrides) -> dict:
    return dict(overrides)  # optional "reason"


def select_entry_payload(certificate_entry_id: str, **overrides) -> dict:
    defaults = {"certificate_entry_id": certificate_entry_id}
    defaults.update(overrides)
    return defaults


def create_pass_over_request_payload(desired_entry_id: str, **overrides) -> dict:
    defaults = {
        "desired_entry_id": desired_entry_id,
        "reason_code": "INADEQUATE_EXPERIENCE",
        "justification": "better-qualified non-preference candidate available",
    }
    defaults.update(overrides)
    return defaults


def adjudicate_pass_over_payload(outcome: str = "APPROVED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def respond_to_offer_payload(response: str = "ACCEPT", **overrides) -> dict:
    defaults = {"response": response}
    defaults.update(overrides)
    return defaults


def record_suitability_review_payload(outcome: str = "FAVORABLE", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def record_security_clearance_payload(outcome: str = "FAVORABLE_FINAL", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def schedule_eod_payload(eod_date: str, **overrides) -> dict:
    defaults = {"eod_date": eod_date}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
