"""Entity assertions and PRD formula helpers.

Formula helpers re-derive expected values straight from the PRD prose so tests
can cross-check computed fields without duplicating arithmetic inline.
"""
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C
from .types import (
    AnnouncementStatus, ApplicationStatus, AssessmentStatus, CertificateEntryStatus,
    CertificateStatus, OfferStatus, AppealStatus, PassOverStatus, PositionStatus,
)


# ---------------------------------------------------------------------------
# PRD formula helpers
# ---------------------------------------------------------------------------
def expected_total_points(k: int, s: int, c: int, i: int) -> int:
    """PRD §3.1: 300*K + 200*S + 250*C + 250*I."""
    return (C.WEIGHT_KNOWLEDGE * k + C.WEIGHT_SUPERVISION * s
            + C.WEIGHT_COMPLEXITY * c + C.WEIGHT_IMPACT * i)


def expected_official_grade(total_points: int) -> int:
    """PRD §3.1: band containing total_points, bands inclusive both ends."""
    for grade, (lo, hi) in C.GRADE_BANDS.items():
        if lo <= total_points <= hi:
            return grade
    raise AssertionError(f"total_points {total_points} outside every grade band")


def expected_provisional_grade(k: int, s: int, c: int, i: int) -> int:
    """PRD §3.1 narrative variant: lowest of the four per-factor grade caps."""
    return min(C.LEVEL_GRADE_CAP[level] for level in (k, s, c, i))


def expected_sme_score(r_k: int, r_s: int, r_a: int) -> int:
    """PRD §3.5 pinned order: round each weighted component half-up to a whole
    number first, then sum, then add the base of 70."""
    def _comp(weight: float, rating: int) -> int:
        return int(Decimal(str(weight * rating * C.SME_SCALE)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP))

    return C.SME_BASE + _comp(C.SME_WEIGHT_KNOWLEDGE, r_k) \
        + _comp(C.SME_WEIGHT_SKILL, r_s) + _comp(C.SME_WEIGHT_ABILITY, r_a)


def expected_category(score: int, bq_cut: int, wq_cut: int) -> str:
    """PRD §3.4: >= bq_cut BEST_QUALIFIED; >= wq_cut WELL_QUALIFIED; else QUALIFIED.
    Boundaries are inclusive at both cut points; raw score only, never augmented."""
    if score >= bq_cut:
        return "BEST_QUALIFIED"
    if score >= wq_cut:
        return "WELL_QUALIFIED"
    return "QUALIFIED"


def expected_required_months(series: dict, official_grade: int) -> int:
    """PRD §3.4: quals_base_months + (official_grade - min_grade) * quals_months_per_grade_step."""
    return (series["quals_base_months"]
            + (official_grade - series["min_grade"]) * series["quals_months_per_grade_step"])


def expected_creditable_months(series: dict, claimed_experience_months: int,
                               claimed_education_months: int) -> int:
    """PRD §3.4: claimed experience + education credit (capped) when the series
    allows substitution, else claimed experience alone."""
    credit = 0
    if series["allows_education_substitution"]:
        credit = min(claimed_education_months, series["education_substitution_cap_months"])
    return claimed_experience_months + credit


# ---------------------------------------------------------------------------
# Entity shape assertions
# ---------------------------------------------------------------------------
def assert_common_fields(data: dict):
    """PRD §2.4 system-managed properties on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_series(data: dict):
    assert_common_fields(data)
    assert isinstance(data["series_code"], str) and data["series_code"]
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["min_grade"], int) and isinstance(data["max_grade"], int)
    assert data["min_grade"] <= data["max_grade"]
    assert isinstance(data["quals_base_months"], int)
    assert isinstance(data["quals_months_per_grade_step"], int)
    assert isinstance(data["allows_education_substitution"], bool)
    assert isinstance(data["education_substitution_cap_months"], int)
    assert isinstance(data["positive_education_required"], bool)


def assert_position(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("series_id", ""))
    assert isinstance(data["title"], str)
    assert isinstance(data["org_code"], str)
    for f in ("factor_knowledge_level", "factor_supervision_level",
              "factor_complexity_level", "factor_impact_level"):
        assert isinstance(data[f], int) and 1 <= data[f] <= 5, f"{f} must be 1..5"
    assert isinstance(data["total_points"], int)
    assert isinstance(data["provisional_grade"], int)
    assert data["official_grade"] is None or isinstance(data["official_grade"], int)
    assert data["sensitivity_level"] in ("NONE", "SECRET", "TOP_SECRET")
    assert data["status"] in {s.value for s in PositionStatus}


def assert_announcement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("position_id", ""))
    assert isinstance(data["announcement_number"], str) and data["announcement_number"]
    assert data["area_of_consideration"] in ("ALL_US_CITIZENS", "STATUS_CANDIDATES", "AGENCY_ONLY")
    assert data["hiring_authority"] in ("COMPETITIVE", "DIRECT_HIRE", "VEOA",
                                        "SCHEDULE_A", "NONCOMPETITIVE_SPOUSE")
    assert data["assessment_method"] in ("CATEGORY_RATING", "UNRANKED")
    assert is_iso8601_timestamp(data["open_at"])
    assert is_iso8601_timestamp(data["close_at"])
    assert isinstance(data["vacancies_count"], int) and data["vacancies_count"] >= 1
    assert isinstance(data["bq_cut"], int) and isinstance(data["wq_cut"], int)
    assert isinstance(data["certificate_validity_days"], int)
    assert isinstance(data["remaining_vacancies"], int)
    assert data["status"] in {s.value for s in AnnouncementStatus}


def assert_applicant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["is_us_citizen"], bool)
    assert isinstance(data["is_current_federal_employee"], bool)
    assert data["veteran_preference_claim"] in ("NONE", "FIVE_POINT",
                                                "TEN_POINT_CP", "TEN_POINT_CPS")
    assert isinstance(data["preference_verified"], bool)
    assert data["preference_points"] in (0, C.PREFERENCE_POINTS_FIVE, C.PREFERENCE_POINTS_TEN)


def assert_document(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert data["doc_type"] in ("DD214", "SF50", "VA_LETTER",
                                "SCHEDULE_A_CERT", "MILITARY_SPOUSE_ORDERS")
    assert isinstance(data["verified"], bool)
    if data["verified"]:
        assert isinstance(data["verified_by"], str) and data["verified_by"]
        assert is_iso8601_timestamp(data["verified_at"])
    else:
        assert data.get("verified_by") is None
        assert data.get("verified_at") is None


def assert_application(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("announcement_id", ""))
    assert is_valid_uuid(data.get("applicant_id", ""))
    assert is_iso8601_timestamp(data["submitted_at"])
    assert isinstance(data["claimed_experience_months"], int)
    assert isinstance(data["claimed_education_months"], int)
    for f in ("self_rating_knowledge", "self_rating_skill", "self_rating_ability"):
        assert isinstance(data[f], int) and 1 <= data[f] <= 5, f"{f} must be 1..5"
    assert isinstance(data["provisional_score"], int)
    assert data["provisional_category"] in ("BEST_QUALIFIED", "WELL_QUALIFIED", "QUALIFIED")
    for f in ("required_experience_months", "creditable_experience_months",
              "technical_score"):
        assert data[f] is None or isinstance(data[f], int), f"{f} must be int or null"
    assert data["quality_category"] is None or data["quality_category"] in (
        "BEST_QUALIFIED", "WELL_QUALIFIED", "QUALIFIED")
    assert is_iso8601_timestamp(data["notified_at"])
    assert data["status"] in {s.value for s in ApplicationStatus}


def assert_assessment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert isinstance(data["sme_user_id"], str) and data["sme_user_id"]
    for f in ("rating_knowledge", "rating_skill", "rating_ability"):
        assert isinstance(data[f], int) and 1 <= data[f] <= 5, f"{f} must be 1..5"
    assert data["technical_score"] is None or isinstance(data["technical_score"], int)
    assert data["quality_category"] is None or data["quality_category"] in (
        "BEST_QUALIFIED", "WELL_QUALIFIED", "QUALIFIED")
    assert data["status"] in {s.value for s in AssessmentStatus}


def assert_certificate(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("announcement_id", ""))
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])
    assert isinstance(data["extension_count"], int) and 0 <= data["extension_count"] <= C.MAX_EXTENSIONS
    assert data["status"] in {s.value for s in CertificateStatus}


def assert_certificate_entry(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("certificate_id", ""))
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["quality_category"] is None or data["quality_category"] in (
        "BEST_QUALIFIED", "WELL_QUALIFIED", "QUALIFIED")
    assert isinstance(data["preference_eligible"], bool)
    assert data["preference_points"] in (0, C.PREFERENCE_POINTS_FIVE, C.PREFERENCE_POINTS_TEN)
    assert data["augmented_score"] is None or isinstance(data["augmented_score"], int)
    assert isinstance(data["rank_position"], int) and data["rank_position"] >= 1
    assert data["status"] in {s.value for s in CertificateEntryStatus}


def assert_pass_over_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("certificate_entry_id", ""))
    assert is_valid_uuid(data.get("desired_entry_id", ""))
    assert data["reason_code"] in ("INADEQUATE_EXPERIENCE", "MISCONDUCT", "OTHER")
    assert isinstance(data["justification"], str)
    assert data["status"] in {s.value for s in PassOverStatus}


def assert_offer(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert is_valid_uuid(data.get("certificate_entry_id", ""))
    assert is_iso8601_timestamp(data["tentative_offered_at"])
    assert is_iso8601_timestamp(data["response_due_at"])
    assert data["responded_at"] is None or is_iso8601_timestamp(data["responded_at"])
    assert data.get("suitability_reviewer_id") is None or isinstance(data["suitability_reviewer_id"], str)
    assert data.get("eod_date") is None or is_iso8601_timestamp(data["eod_date"])
    assert data["status"] in {s.value for s in OfferStatus}


def assert_suitability_review(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("offer_id", ""))
    assert isinstance(data["reviewer_id"], str) and data["reviewer_id"]
    assert data["outcome"] in ("FAVORABLE", "UNFAVORABLE")
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_security_clearance(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("offer_id", ""))
    assert isinstance(data["adjudicator_id"], str) and data["adjudicator_id"]
    assert data["level_required"] in ("NONE", "SECRET", "TOP_SECRET")
    assert data["outcome"] in ("FAVORABLE_INTERIM", "FAVORABLE_FINAL", "UNFAVORABLE")
    assert is_iso8601_timestamp(data["recorded_at"])


def assert_appeal(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("application_id", ""))
    assert data["grounds"] in ("QUALIFICATION", "RATING", "PREFERENCE")
    assert is_iso8601_timestamp(data["filed_at"])
    assert is_iso8601_timestamp(data["deadline_at"])
    assert data["status"] in {s.value for s in AppealStatus}


def assert_appointment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("offer_id", ""))
    assert data["appointment_type"] in ("COMPETITIVE", "DIRECT_HIRE", "SPECIAL_AUTHORITY")
    assert is_iso8601_timestamp(data["eod_date"])
