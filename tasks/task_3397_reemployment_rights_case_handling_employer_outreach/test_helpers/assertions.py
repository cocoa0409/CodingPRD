"""Domain assertions for the Reemployment Rights Mediation API.

These wrap the shared structural helpers with the vocabulary of this contract:
instants compare on their canonical form rather than on raw strings,
month-valued figures compare at exactly two decimal places, and each entity's
shape is checked once here instead of in every test. Append-only audit records
(ServicePeriod, CaseNote, EligibilityAnalysis, BenefitAssessment,
TrainingRecord) must NOT carry ``updated_at`` or ``version``.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    AWARD_BONUS_BY_TIER,
    DURATION_BAND_DEADLINE_DAYS,
    ESCALATOR_BY_BAND,
)


# ── Instants ───────────────────────────────────────────────────────────────

def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 UTC instants denote the same moment.

    Sub-second rendering is not part of the comparison: both sides are reduced
    to the canonical three-digit form first, so a value rendered without a
    fractional part still matches the same moment rendered with one.
    """
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_instant_format(value: Any, label: str = "instant") -> None:
    """Assert a value is an ISO 8601 UTC instant rendered with a Z suffix."""
    assert isinstance(value, str), f"{label}: expected a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"{label}: not an ISO 8601 UTC instant: {value!r}"
    assert value.endswith("Z"), f"{label}: must be rendered in UTC with a Z suffix: {value!r}"


# ── Numbers ────────────────────────────────────────────────────────────────

def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a two-decimal-place figure, the precision all month values carry."""
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert round(float(actual), 2) == round(float(expected), 2), (
        f"{label}: expected {expected} at 2 decimal places, got {actual}"
    )


# ── Common field sets ──────────────────────────────────────────────────────

def assert_mutable_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """Primary resources carry id, created_at, updated_at and a version counter."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID: {data.get('id')!r}"
    assert_instant_format(data.get("created_at"), f"{label}.created_at")
    assert_instant_format(data.get("updated_at"), f"{label}.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_append_only_common_fields(data: Dict[str, Any], label: str = "record") -> None:
    """Audit records carry only id and created_at - never updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID: {data.get('id')!r}"
    assert_instant_format(data.get("created_at"), f"{label}.created_at")
    assert "updated_at" not in data, f"{label} must not carry updated_at (append-only)"
    assert "version" not in data, f"{label} must not carry version (append-only)"


# ── Per-entity shapes ──────────────────────────────────────────────────────

def assert_service_member(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "ServiceMember")
    for field in ("full_name", "email"):
        assert isinstance(data.get(field), str) and data[field], f"ServiceMember.{field} must be a non-empty string"
    assert data.get("branch") in ("ARMY", "NAVY", "AIR_FORCE", "MARINES", "COAST_GUARD", "SPACE_FORCE")
    assert data.get("component") in ("ARMY_RESERVE", "NAVY_RESERVE", "MARINE_RESERVE", "ARMY_GUARD", "AIR_GUARD")


def assert_employer(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "Employer")
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert data.get("sector") in (
        "MANUFACTURING", "RETAIL", "HEALTHCARE", "LOGISTICS",
        "GOVERNMENT", "CONSTRUCTION", "HOSPITALITY", "TECHNOLOGY",
    )
    assert data.get("size_tier") in ("SMALL", "MEDIUM", "LARGE")
    for counter in ("resolved_case_count", "open_case_count"):
        assert isinstance(data.get(counter), int) and data[counter] >= 0, (
            f"Employer.{counter} must be a non-negative integer, got {data.get(counter)!r}"
        )
    assert data.get("recognition_tier") in ("NONE", "BRONZE", "SILVER", "GOLD")


def assert_ombudsman(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "Ombudsman")
    for field in ("full_name", "email"):
        assert isinstance(data.get(field), str) and data[field], f"Ombudsman.{field} must be a non-empty string"
    assert data.get("status") in ("TRAINEE", "CERTIFIED", "ON_LEAVE", "EXPIRED", "DECERTIFIED")
    assert data.get("employer_affiliation_id") is None or isinstance(data["employer_affiliation_id"], str)
    assert data.get("certified_on") is None or is_iso8601_timestamp(data["certified_on"])
    assert data.get("certification_expires_on") is None or is_iso8601_timestamp(data["certification_expires_on"])
    assert isinstance(data.get("active_caseload"), int) and data["active_caseload"] >= 0
    assert isinstance(data.get("total_training_hours"), (int, float)) and data["total_training_hours"] >= 0


def assert_service_period(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "ServicePeriod")
    for field in ("member_id", "employer_id"):
        assert is_valid_uuid(data.get(field, "")), f"ServicePeriod.{field} must be a valid UUID"
    assert_instant_format(data.get("start_date"), "ServicePeriod.start_date")
    assert data.get("end_date") is None or is_iso8601_timestamp(data["end_date"])
    assert data.get("orders_type") in (
        "DRILL", "ANNUAL_TRAINING", "ACTIVE_DUTY", "NATIONAL_EMERGENCY", "PRESIDENTIAL_CALLUP",
    )
    assert data.get("notice_given_at") is None or is_iso8601_timestamp(data["notice_given_at"])
    if data.get("end_date") is None:
        assert data.get("duration_days") is None, "duration_days stays null while the period is ongoing"
    else:
        assert isinstance(data.get("duration_days"), int) and data["duration_days"] >= 0
    assert isinstance(data.get("chargeable"), bool)
    if data.get("orders_type") in ("NATIONAL_EMERGENCY", "PRESIDENTIAL_CALLUP"):
        assert data["chargeable"] is False, "cap-exempt orders must be non-chargeable"


def assert_reemployment_case(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "ReemploymentCase")
    for field in ("member_id", "employer_id"):
        assert is_valid_uuid(data.get(field, "")), f"ReemploymentCase.{field} must be a valid UUID"
    assert data.get("issue_type") in ("REEMPLOYMENT", "BENEFITS", "PENSION", "DISCRIMINATION", "RETALIATION")
    assert isinstance(data.get("description"), str)
    assert data.get("application_submitted_at") is None or is_iso8601_timestamp(data["application_submitted_at"])
    assert isinstance(data.get("excuse_claimed"), bool)
    assert data.get("excuse_category") in (None, "ORDERS_SHORT_FUSE", "OPERATIONAL_NECESSITY", "CLASSIFIED_MISSION")
    assert data.get("assigned_ombudsman_id") is None or isinstance(data["assigned_ombudsman_id"], str)
    assert data.get("status") in (
        "INTAKE", "TRIAGE", "ASSIGNED", "IN_MEDIATION", "AWAITING_RESPONSE",
        "ESCALATION_PENDING", "RESOLVED_INFORMAL", "REFERRED",
        "CLOSED_WITHDRAWN", "CLOSED_UNRESOLVED",
    )
    assert isinstance(data.get("open_round_count"), int) and data["open_round_count"] >= 0
    assert isinstance(data.get("documentation_complete"), bool)
    assert data.get("escalated_at") is None or is_iso8601_timestamp(data["escalated_at"])
    assert data.get("closed_at") is None or is_iso8601_timestamp(data["closed_at"])


def assert_mediation_round(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "MediationRound")
    assert is_valid_uuid(data.get("case_id", "")), "MediationRound.case_id must be a valid UUID"
    assert isinstance(data.get("round_number"), int) and data["round_number"] >= 1
    assert isinstance(data.get("proposal_text"), str) and data["proposal_text"]
    assert data.get("addressed_to") in ("EMPLOYER", "MEMBER")
    assert_instant_format(data.get("response_deadline"), "MediationRound.response_deadline")
    assert data.get("status") in ("PROPOSED", "ACCEPTED", "COUNTERED", "DECLINED", "EXPIRED", "CLOSED_MOOT")
    assert data.get("response") in (None, "ACCEPT", "COUNTER", "DECLINE")
    assert data.get("counter_text") is None or isinstance(data["counter_text"], str)
    assert data.get("responded_at") is None or is_iso8601_timestamp(data["responded_at"])


def assert_case_note(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "CaseNote")
    assert is_valid_uuid(data.get("case_id", "")), "CaseNote.case_id must be a valid UUID"
    assert data.get("note_type") in ("INTAKE", "CONTACT", "EMPLOYER_EDUCATION", "RESOLUTION", "AUDIT")
    assert isinstance(data.get("body"), str)
    assert isinstance(data.get("author_role"), str) and data["author_role"]
    assert isinstance(data.get("author_id"), str)


def assert_eligibility_analysis(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "EligibilityAnalysis")
    assert is_valid_uuid(data.get("case_id", "")), "EligibilityAnalysis.case_id must be a valid UUID"
    assert isinstance(data.get("sequence_number"), int) and data["sequence_number"] >= 1
    assert data.get("variant") in ("STRICT", "LENIENT")
    assert data.get("notice_hours_advance") is None or isinstance(data["notice_hours_advance"], (int, float))
    assert isinstance(data.get("notice_satisfied"), bool)
    assert isinstance(data.get("cumulative_chargeable_days"), int) and data["cumulative_chargeable_days"] >= 0
    assert isinstance(data.get("service_limit_ok"), bool)
    assert isinstance(data.get("disputed_period_duration_days"), int) and data["disputed_period_duration_days"] >= 0
    assert data.get("duration_band") in ("SHORT", "MID", "LONG")
    assert isinstance(data.get("application_deadline_days"), int)
    assert_instant_format(data.get("application_deadline_date"), "EligibilityAnalysis.application_deadline_date")
    assert isinstance(data.get("deadline_satisfied"), bool)
    assert data.get("escalator_position_class") in (
        "SAME_POSITION", "SENIORITY_ESCALATED", "ESCALATED_WITH_RETRAINING",
    )
    assert isinstance(data.get("overall_eligible"), bool)


def assert_benefit_assessment(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "BenefitAssessment")
    assert is_valid_uuid(data.get("case_id", "")), "BenefitAssessment.case_id must be a valid UUID"
    for field in ("health_continuation_months", "pension_credit_months_official", "pension_credit_months_alternate"):
        assert isinstance(data.get(field), (int, float)) and data[field] >= 0, (
            f"BenefitAssessment.{field} must be a non-negative number, got {data.get(field)!r}"
        )
    assert isinstance(data.get("education_required"), bool)
    assert isinstance(data.get("education_satisfied"), bool)


def assert_referral(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "Referral")
    assert is_valid_uuid(data.get("case_id", "")), "Referral.case_id must be a valid UUID"
    assert data.get("agency") in ("DOL_VETS", "DOJ_CIVIL_RIGHTS", "OPM")
    assert isinstance(data.get("summary"), str)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "RETURNED_FOR_INFO", "ACKNOWLEDGED", "WITHDRAWN")
    assert data.get("submitted_at") is None or is_iso8601_timestamp(data["submitted_at"])
    assert data.get("info_request_note") is None or isinstance(data["info_request_note"], str)
    assert isinstance(data.get("created_by_ombudsman_id"), str) and data["created_by_ombudsman_id"]


def assert_statement_of_support(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "StatementOfSupport")
    assert is_valid_uuid(data.get("employer_id", "")), "StatementOfSupport.employer_id must be a valid UUID"
    for field in ("signer_name", "signer_title"):
        assert isinstance(data.get(field), str) and data[field], f"StatementOfSupport.{field} must be non-empty"
    assert isinstance(data.get("term_months"), int) and data["term_months"] >= 1
    assert data.get("status") in ("PLEDGED", "SIGNED", "LAPSED", "REVOKED")
    assert data.get("signed_on") is None or is_iso8601_timestamp(data["signed_on"])
    assert data.get("expires_on") is None or is_iso8601_timestamp(data["expires_on"])


def assert_recognition_award(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "RecognitionAward")
    assert is_valid_uuid(data.get("employer_id", "")), "RecognitionAward.employer_id must be a valid UUID"
    assert data.get("tier") in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data.get("rationale"), str)
    assert isinstance(data.get("nominated_by_id"), str) and data["nominated_by_id"]
    assert isinstance(data.get("nominated_by_role"), str) and data["nominated_by_role"]
    assert data.get("status") in ("NOMINATED", "VETTED", "CONFERRED", "DECLINED")
    for field in ("score_base", "score_bonus", "score_final"):
        assert data.get(field) is None or isinstance(data[field], int), (
            f"RecognitionAward.{field} must be null or an integer, got {data.get(field)!r}"
        )
    assert data.get("tier_qualified") in (None, "BRONZE", "SILVER", "GOLD")


def assert_outreach_event(data: Dict[str, Any]) -> None:
    assert_mutable_common_fields(data, "OutreachEvent")
    for field in ("title", "venue"):
        assert isinstance(data.get(field), str) and data[field], f"OutreachEvent.{field} must be non-empty"
    assert_instant_format(data.get("starts_at"), "OutreachEvent.starts_at")
    assert_instant_format(data.get("ends_at"), "OutreachEvent.ends_at")
    assert data.get("topic") in ("RIGHTS_OVERVIEW", "BENEFITS_BRIEFING", "EMPLOYER_RECOGNITION", "HIRING_FAIR")
    assert data.get("status") in ("PLANNED", "OPEN", "CONCLUDED", "CANCELLED")


def assert_training_record(data: Dict[str, Any]) -> None:
    assert_append_only_common_fields(data, "TrainingRecord")
    assert is_valid_uuid(data.get("ombudsman_id", "")), "TrainingRecord.ombudsman_id must be a valid UUID"
    assert data.get("module_code") in (
        "CORE_LAW", "MEDIATION_SKILLS", "DOCUMENTATION", "ETHICS_NEUTRALITY", "ELECTIVE",
    )
    assert isinstance(data.get("hours"), (int, float)) and data["hours"] > 0
    assert isinstance(data.get("exam_score"), int) and 0 <= data["exam_score"] <= 100
    assert_instant_format(data.get("completed_on"), "TrainingRecord.completed_on")
    assert isinstance(data.get("proctor_id"), str) and data["proctor_id"]


def assert_sector_trend_report(data: Dict[str, Any]) -> None:
    assert isinstance(data.get("sector"), str) and data["sector"]
    assert_instant_format(data.get("period_start"), "SectorTrendReport.period_start")
    assert_instant_format(data.get("period_end"), "SectorTrendReport.period_end")
    for field in ("total_cases", "repeat_employer_count", "resolved_count"):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            f"SectorTrendReport.{field} must be a non-negative integer, got {data.get(field)!r}"
        )
    assert data.get("top_issue_type") in (
        None, "REEMPLOYMENT", "BENEFITS", "PENSION", "DISCRIMINATION", "RETALIATION",
    )


# ── Domain invariants ──────────────────────────────────────────────────────

def assert_analysis_band_consistency(data: Dict[str, Any]) -> None:
    """The band pins the deadline length and the escalator class, by the PRD's table."""
    band = data.get("duration_band")
    if band in DURATION_BAND_DEADLINE_DAYS:
        assert data.get("application_deadline_days") == DURATION_BAND_DEADLINE_DAYS[band], (
            f"band {band} must carry deadline {DURATION_BAND_DEADLINE_DAYS[band]} days, "
            f"got {data.get('application_deadline_days')}"
        )
        assert data.get("escalator_position_class") == ESCALATOR_BY_BAND[band], (
            f"band {band} must map to {ESCALATOR_BY_BAND[band]}, "
            f"got {data.get('escalator_position_class')}"
        )
    if isinstance(data.get("notice_satisfied"), bool) and isinstance(data.get("service_limit_ok"), bool) \
            and isinstance(data.get("deadline_satisfied"), bool):
        expected = data["notice_satisfied"] and data["service_limit_ok"] and data["deadline_satisfied"]
        assert data.get("overall_eligible") == expected, (
            f"overall_eligible must be the conjunction of the three component booleans: "
            f"expected {expected}, got {data.get('overall_eligible')}"
        )


def assert_award_score_invariants(data: Dict[str, Any]) -> None:
    """A vetted award's final score is base plus the bonus keyed on the qualified tier."""
    if data.get("score_base") is None:
        assert data.get("tier_qualified") is None
        assert data.get("score_bonus") is None
        assert data.get("score_final") is None
        return
    tier = data.get("tier_qualified")
    assert tier in AWARD_BONUS_BY_TIER, f"tier_qualified must be set once scores exist, got {tier!r}"
    assert data.get("score_bonus") == AWARD_BONUS_BY_TIER[tier], (
        f"score_bonus for {tier} must be {AWARD_BONUS_BY_TIER[tier]}, got {data.get('score_bonus')}"
    )
    assert data.get("score_final") == data["score_base"] + data["score_bonus"], (
        f"score_final must be score_base + score_bonus: "
        f"{data.get('score_base')} + {data.get('score_bonus')} != {data.get('score_final')}"
    )
