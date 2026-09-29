"""Entity assertions, money/timestamp helpers and domain invariant checkers."""

import re
from typing import Optional

import pytest
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AppointmentStatus,
    BenefitsPackage,
    BiosafetyLevel,
    ComplianceStatus,
    DocumentStatus,
    DocumentType,
    ExitRecordStatus,
    ExportReviewStatus,
    GrievanceStatus,
    LabGrantStatus,
    LaboratoryStatus,
    PostdocStatus,
    ReappointmentReviewStatus,
    ScreeningTier,
    SuspensionReason,
    VerificationStatus,
    VisaCaseStatus,
)

MONEY_TOLERANCE = 0.005

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})$"
)


# ─── Timestamp canonicalisation ───────────────────────────────────────────

def canonical_timestamp(value: str) -> str:
    """Normalise an ISO 8601 UTC instant to exactly three fractional digits.

    Sub-second precision width is a formatting choice; comparisons in this
    suite are on the instant, so `...:59Z`, `...:59.9Z` and `...:59.900Z` all
    canonicalise to the same string before being compared.
    """
    if not isinstance(value, str):
        return value
    match = _TS_RE.match(value.strip())
    if not match:
        return value
    date_part, time_part, frac, _zone = match.groups()
    frac = (frac or "")[:3].ljust(3, "0")
    return f"{date_part}T{time_part}.{frac}Z"


def assert_timestamp_equals(actual: str, expected: str, label: str = "timestamp") -> None:
    """Compare two instants irrespective of fractional-digit width."""
    assert canonical_timestamp(actual) == canonical_timestamp(expected), (
        f"Expected {label} {expected}, got {actual}"
    )


def assert_millisecond_precision(value: str, label: str = "timestamp") -> None:
    """Assert the instant carries exactly three fractional-second digits."""
    match = _TS_RE.match(value)
    assert match, f"{label} is not an ISO 8601 UTC instant: {value!r}"
    frac = match.group(3)
    assert frac is not None and len(frac) == 3, (
        f"Expected exactly three fractional-second digits on {label}, got {value!r}"
    )


def assert_date_equals(actual: str, expected: str, label: str = "date") -> None:
    assert actual == expected, f"Expected {label} {expected}, got {actual}"


# ─── Money ────────────────────────────────────────────────────────────────

def assert_money(actual, expected: float, label: str = "amount") -> None:
    """Monetary amounts are JSON numbers carried to exactly two decimals."""
    assert not isinstance(actual, str), (
        f"{label} must be a JSON number, not a string: {actual!r}"
    )
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected {label} {expected}, got {actual}"
    )
    assert_cost_precision(float(actual))


def assert_award_ledger(funding_source: dict, expected_encumbered: float,
                        expected_available: float) -> None:
    """The award's two ledger figures, and the identity that binds them."""
    assert_money(funding_source["encumbered_usd"], expected_encumbered, "encumbered_usd")
    assert_money(
        funding_source["available_balance_usd"], expected_available, "available_balance_usd"
    )
    assert funding_source["available_balance_usd"] == pytest.approx(
        funding_source["annual_budget_usd"] - funding_source["encumbered_usd"], abs=0.005
    ), "available_balance_usd must be annual_budget_usd less encumbered_usd"


# ─── Common system-managed properties ─────────────────────────────────────

def assert_common_fields(data: dict, entity_label: str = "record") -> None:
    """`id`, `created_at`, `updated_at` and `version` are carried by every record."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_label}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_label}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_label}.version must be an integer starting at 1, "
        f"got {data.get('version')!r}"
    )


def assert_envelope_meta(body: dict) -> None:
    """The success envelope's request identifier and timestamp."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert_millisecond_precision(meta["api_request_timestamp"], "api_request_timestamp")


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_postdoc(data: dict) -> None:
    assert_common_fields(data, "Postdoc")
    assert isinstance(data["full_name"], str) and 0 < len(data["full_name"]) <= 120
    assert "@" in data["email"]
    assert re.match(r"^[A-Z]{2}$", data["citizenship_country"]), (
        f"citizenship_country must be two uppercase letters, "
        f"got {data['citizenship_country']!r}"
    )
    assert isinstance(data["requires_sponsorship"], bool)
    assert isinstance(data["phd_award_date"], str)
    assert isinstance(data["prior_external_months_in_rank"], int)
    assert 0 <= data["prior_external_months_in_rank"] <= 60
    assert isinstance(data["o1_endorsement_on_file"], bool)
    assert isinstance(data["j1_two_year_bar_flag"], bool)
    assert isinstance(data["restricted_party_flag"], bool)
    assert data["status"] in [s.value for s in PostdocStatus]
    assert isinstance(data["total_months_in_rank"], int)


def assert_faculty_mentor(data: dict) -> None:
    assert_common_fields(data, "FacultyMentor")
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["department"], str) and len(data["department"]) > 0
    assert isinstance(data["mentor_training_valid_through"], str)
    assert isinstance(data["max_concurrent_postdocs"], int)
    assert 1 <= data["max_concurrent_postdocs"] <= 12
    assert isinstance(data["active_postdoc_count"], int)
    assert data["active_postdoc_count"] >= 0


def assert_funding_source(data: dict) -> None:
    assert_common_fields(data, "FundingSource")
    assert isinstance(data["sponsor_name"], str) and len(data["sponsor_name"]) > 0
    assert data["funding_type"] in [
        "FEDERAL_GRANT", "FOUNDATION_GRANT", "EXTERNAL_FELLOWSHIP",
        "INSTITUTIONAL_FELLOWSHIP",
    ]
    assert data["salary_floor_policy"] in ["NIH_SCALE", "INSTITUTIONAL_MIN"]
    assert data["annual_budget_usd"] > 0
    assert_cost_precision(float(data["annual_budget_usd"]))
    assert isinstance(data["requires_mentoring_plan"], bool)
    assert isinstance(data["requires_idp"], bool)
    assert data["verification_status"] in [s.value for s in VerificationStatus]
    assert_cost_precision(float(data["encumbered_usd"]))
    assert_cost_precision(float(data["available_balance_usd"]))


def assert_laboratory(data: dict) -> None:
    assert_common_fields(data, "Laboratory")
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["biosafety_level"] in [b.value for b in BiosafetyLevel]
    assert 1 <= data["bench_capacity"] <= 40
    assert 0 <= data["decontamination_buffer_days"] <= 30
    assert data["status"] in [s.value for s in LaboratoryStatus]


def assert_appointment(data: dict) -> None:
    assert_common_fields(data, "Appointment")
    for fk in ("postdoc_id", "mentor_id", "funding_source_id"):
        assert is_valid_uuid(data[fk]), f"Appointment.{fk} must be a UUID"
    assert data["appointment_status"] in [s.value for s in AppointmentStatus]
    assert data["compliance_status"] in [s.value for s in ComplianceStatus]
    assert data["title_classification"] in [
        "POSTDOC_FELLOW", "POSTDOC_SCHOLAR_EMPLOYEE", "POSTDOC_ASSOCIATE",
    ]
    assert data["employment_class"] in ["EMPLOYEE", "FELLOWSHIP"]
    assert data["annual_salary_usd"] > 0
    assert isinstance(data["prepared_by_user_id"], str)
    for whole in ("term_months", "months_in_rank_at_start",
                  "cumulative_months_in_rank_at_end", "reinstated_count"):
        assert isinstance(data[whole], int), (
            f"Appointment.{whole} must be a whole integer, got {data[whole]!r}"
        )
    assert data["benefits_package"] in [b.value for b in BenefitsPackage]
    assert_cost_precision(float(data["salary_floor_usd"]))
    assert_cost_precision(float(data["encumbrance_usd"]))


def assert_visa_case(data: dict) -> None:
    assert_common_fields(data, "VisaCase")
    assert is_valid_uuid(data["appointment_id"])
    assert data["visa_category"] in ["TN", "J1_RESEARCH_SCHOLAR", "H1B", "O1"]
    assert data["processing_track"] in ["STANDARD", "PREMIUM"]
    assert data["status"] in [s.value for s in VisaCaseStatus]
    assert isinstance(data["rfe_round_count"], int) and data["rfe_round_count"] >= 0


def assert_development_document(data: dict) -> None:
    assert_common_fields(data, "DevelopmentDocument")
    assert is_valid_uuid(data["appointment_id"])
    assert data["doc_type"] in [d.value for d in DocumentType]
    assert data["status"] in [s.value for s in DocumentStatus]
    assert isinstance(data["postdoc_acknowledged"], bool)
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_export_control_review(data: dict) -> None:
    assert_common_fields(data, "ExportControlReview")
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert data["status"] in [s.value for s in ExportReviewStatus]
    assert isinstance(data["restricted_party_hit"], bool)
    assert isinstance(data["controlled_technology_flag"], bool)
    assert isinstance(data["deemed_export_license_required"], bool)
    if data["screening_tier"] is not None:
        assert data["screening_tier"] in [t.value for t in ScreeningTier]


def assert_lab_access_grant(data: dict) -> None:
    assert_common_fields(data, "LabAccessGrant")
    assert is_valid_uuid(data["appointment_id"])
    assert is_valid_uuid(data["laboratory_id"])
    assert 1 <= data["bench_seats"] <= 10
    assert data["status"] in [s.value for s in LabGrantStatus]
    assert data["suspension_reason"] in [r.value for r in SuspensionReason]
    assert isinstance(data["requested_by_user_id"], str)


def assert_reappointment_review(data: dict) -> None:
    assert_common_fields(data, "ReappointmentReview")
    assert is_valid_uuid(data["appointment_id"])
    assert isinstance(data["review_cycle"], int) and data["review_cycle"] >= 1
    assert data["status"] in [s.value for s in ReappointmentReviewStatus]
    assert isinstance(data["term_extension_days"], int)


def assert_grievance(data: dict) -> None:
    assert_common_fields(data, "Grievance")
    assert is_valid_uuid(data["reappointment_review_id"])
    assert data["category"] in ["PROCEDURAL", "NOTICE_UNTIMELY", "RETALIATION"]
    assert isinstance(data["narrative"], str) and len(data["narrative"]) > 0
    assert data["status"] in [s.value for s in GrievanceStatus]
    assert isinstance(data["filed_by_user_id"], str)


def assert_exit_record(data: dict) -> None:
    assert_common_fields(data, "ExitRecord")
    assert is_valid_uuid(data["appointment_id"])
    assert data["exit_reason"] in [
        "TERM_COMPLETION", "NON_RENEWAL", "RESIGNATION", "COMPLIANCE_TERMINATION",
    ]
    assert data["status"] in [s.value for s in ExitRecordStatus]
    assert isinstance(data["ip_disclosure_count"], int)
    assert isinstance(data["lab_access_cleared"], bool)
    assert isinstance(data["final_months_posted"], int)


# ─── Domain invariant checkers ────────────────────────────────────────────

def assert_appointment_state(appointment: dict,
                             appointment_status: Optional[str] = None,
                             compliance_status: Optional[str] = None) -> None:
    """The two independent state dimensions carried on the appointment row."""
    if appointment_status is not None:
        assert appointment["appointment_status"] == appointment_status, (
            f"Expected appointment_status {appointment_status}, "
            f"got {appointment['appointment_status']}"
        )
    if compliance_status is not None:
        assert appointment["compliance_status"] == compliance_status, (
            f"Expected compliance_status {compliance_status}, "
            f"got {appointment['compliance_status']}"
        )


def assert_risk_score(actual, expected: float) -> None:
    """`risk_score` is the one quantity carried to one decimal place."""
    assert actual == pytest.approx(expected, abs=0.005), (
        f"Expected risk_score {expected}, got {actual}"
    )
    assert round(float(actual), 1) == pytest.approx(float(actual), abs=1e-9), (
        f"risk_score must carry at most one decimal place, got {actual}"
    )


def assert_released_encumbrance(appointment: dict, funding_source: dict,
                                expected_encumbered: float,
                                expected_available: float) -> None:
    """A release sets the appointment's own figure to zero and rolls the award back."""
    assert_money(appointment["encumbrance_usd"], 0.00, "appointment.encumbrance_usd")
    assert_award_ledger(funding_source, expected_encumbered, expected_available)


def assert_null_notice_fields(review: dict) -> None:
    """The renewal branch touches no notice field and no term field."""
    for field in ("notice_days_required", "notice_deadline_date", "notice_issued_at",
                  "notice_timely", "grievance_window_end", "pre_notice_term_end_date"):
        assert review[field] is None, (
            f"Expected {field} to be null on a renewed review, got {review[field]!r}"
        )
    assert review["term_extension_days"] == 0, (
        f"Expected term_extension_days 0, got {review['term_extension_days']}"
    )
