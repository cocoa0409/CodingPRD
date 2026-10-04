"""Entity assertions and domain invariant checkers."""

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from . import constants as C


def assert_common_fields(data: dict) -> None:
    """Every persisted resource carries id, created_at, updated_at and version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID string, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 instant, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an integer, got {data.get('version')!r}"
    )


def assert_facility(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["licensed"], bool)
    assert data["as_level_max"] in list(C.BASE_DAILY_CENTS)
    assert data["state_min_credential_tier"] in list(C.REQUIRED_SESSIONS_PER_WEEK) or (
        data["state_min_credential_tier"]
        in ("TIER_1_SUPPORT", "TIER_2_COUNSELOR", "TIER_3_LICENSED", "TIER_4_INDEPENDENT")
    )
    assert isinstance(data["is_accepting_admissions"], bool)
    assert data["facility_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["compliance_risk_points"], int)
    assert isinstance(data["ops_epoch"], int)
    assert data["last_ops_run_at"] is None or is_iso8601_timestamp(data["last_ops_run_at"])


def assert_bed(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["level_of_care"] in list(C.BASE_DAILY_CENTS)
    assert isinstance(data["cleaning_turnaround_hours"], int)
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "CLEANING")
    assert data["next_available_at"] is None or is_iso8601_timestamp(data["next_available_at"])


def assert_clinician(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["credential_tier"] in (
        "TIER_1_SUPPORT",
        "TIER_2_COUNSELOR",
        "TIER_3_LICENSED",
        "TIER_4_INDEPENDENT",
    )
    assert isinstance(data["is_medical_provider"], bool)


def assert_credential(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["clinician_id"])
    assert is_valid_uuid(data["facility_id"])
    assert data["status"] in ("ACTIVE", "REVOKED")
    assert isinstance(data["is_usable"], bool)


def assert_service_offering(data: dict) -> None:
    assert_common_fields(data)
    assert data["level_of_care"] in list(C.BASE_DAILY_CENTS)
    assert isinstance(data["requires_medical_provider"], bool)


def assert_payer(data: dict) -> None:
    assert_common_fields(data)
    assert isinstance(data["initial_authorized_days_by_loc"], dict)
    assert isinstance(data["step_down_coverage_map"], dict)
    assert isinstance(data["concurrent_review_interval_days"], int)
    assert isinstance(data["credential_min_tier_by_loc"], dict)


def assert_episode(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["patient_ref"], str) and data["patient_ref"]
    assert data["clinical_status"] in (
        "AWAITING_ASSESSMENT",
        "UNDER_ASSESSMENT",
        "AWAITING_AUTHORIZATION",
        "AWAITING_ADMISSION",
        "IN_TREATMENT",
        "COMPLETED",
        "DISCHARGED",
    )
    assert data["care_level_status"] in (
        "NOT_STARTED",
        "ACTIVE",
        "STEP_DOWN_PENDING",
        "STEPPED_DOWN",
    )
    assert isinstance(data["step_down_count"], int)
    assert isinstance(data["therapy_revenue_cents"], int)
    assert data["admitted_at"] is None or is_iso8601_timestamp(data["admitted_at"])
    assert data["discharged_at"] is None or is_iso8601_timestamp(data["discharged_at"])


def assert_assessment(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["assessor_clinician_id"])
    assert data["status"] in ("IN_PROGRESS", "COMPLETED", "SUPERSEDED", "CANCELLED")
    assert data["placement_basis"] in ("DIMENSION_SUM", "HIGHEST_DIMENSION_FLOOR")
    assert isinstance(data["dimension_scores"], dict)


def assert_authorization(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["payer_id"])
    assert data["posture"] in (
        "PENDING",
        "APPROVED",
        "CONCURRENT_REVIEW_DUE",
        "EXTENDED",
        "STEP_DOWN_REQUIRED",
        "DENIED",
        "EXHAUSTED",
        "EXPIRED",
    )
    assert isinstance(data["days_used"], int)
    assert isinstance(data["concurrent_review_count"], int)
    if data.get("days_remaining") is not None:
        assert data["days_remaining"] >= 0, "days_remaining never goes negative"


def assert_clearance(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert data["clearance_type"] in ("MEDICAL", "PSYCHIATRIC", "TB_SCREEN")
    assert data["status"] in ("PENDING", "CLEARED", "FAILED", "EXPIRED")
    assert data["effective_status"] in (None, "PENDING", "CLEARED", "FAILED", "EXPIRED")
    if data.get("expires_at") is not None:
        assert is_iso8601_timestamp(data["expires_at"])


def assert_withdrawal_management(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert data["protocol"] in ("NONE", "ALCOHOL_TAPER", "OPIOID_AGONIST", "BENZO_TAPER")
    assert isinstance(data["ciwa_score"], int) and 0 <= data["ciwa_score"] <= 30
    assert data["status"] in ("ACTIVE", "MEDICALLY_STABLE", "COMPLICATED")
    assert isinstance(data["dose_records"], list)


def assert_treatment_plan(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["author_clinician_id"])
    assert data["status"] in ("DRAFT", "PENDING_COSIGN", "ACTIVE", "SUPERSEDED", "REJECTED")
    assert isinstance(data["required_sessions_per_week"], int)


def assert_session(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["service_id"])
    assert is_valid_uuid(data["clinician_id"])
    assert data["status"] in ("SCHEDULED", "ATTENDED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["duration_minutes"], int)
    assert isinstance(data["attended"], bool)
    assert isinstance(data["billing_amount_cents"], int)


def assert_level_of_care_change(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert is_valid_uuid(data["authorization_id"])
    assert data["from_level"] in list(C.BASE_DAILY_CENTS)
    assert data["to_level"] in list(C.BASE_DAILY_CENTS)
    assert data["change_type"] in ("STEP_DOWN", "STEP_UP")
    assert data["status"] in (
        "PLANNED",
        "PENDING_DISCHARGE_ORDER",
        "AWAITING_DISCHARGE",
        "COMPLETED",
        "CANCELLED",
    )
    assert data["retry_available_at"] is None or is_iso8601_timestamp(data["retry_available_at"])


def assert_continuing_care_plan(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert data["status"] in ("DRAFT", "ACTIVE", "SUPERSEDED", "CANCELLED")
    assert data["housing_selection_basis"] in ("EXPLICIT", "RANKED_AUTO")
    assert isinstance(data["alumni_contact_interval_days"], int)
    assert isinstance(data["alumni_contacts_required"], int)


def assert_recovery_housing(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert isinstance(data["proximity_rank"], int)
    assert isinstance(data["day_rate_cents"], int)
    assert isinstance(data["capacity_beds"], int)
    assert isinstance(data["licensed"], bool)
    assert data["status"] in ("OPEN", "SUSPENDED")


def assert_alumni_contact(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["episode_id"])
    assert isinstance(data["attempt_number"], int)
    assert data["outcome"] in ("PENDING", "REACHED", "UNREACHABLE", "DECLINED", "NO_CONTACT")
    assert data["record_filed_at"] is None or is_iso8601_timestamp(data["record_filed_at"])


def assert_accreditation(data: dict) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["facility_id"])
    assert data["accreditation_class"] in (
        "ACCREDITATION_BODY",
        "STATE_LICENSE",
        "RECOVERY_HOUSE",
    )
    assert data["status"] in ("GRANTED", "SUSPENDED", "REVOKED", "EXPIRED")
    assert is_iso8601_timestamp(data["effective_at"])
    assert is_iso8601_timestamp(data["expires_at"])


# ------------------------------------------------------------ domain invariants

def assert_episode_invariants(data: dict) -> None:
    """Invariants that must hold on any episode read (PRD §2.9, §3.1)."""
    assert data["step_down_count"] >= 0, "step_down_count never goes negative"
    assert data["therapy_revenue_cents"] >= 0, "revenue is a non-negative integer count of cents"
    if data["clinical_status"] == "IN_TREATMENT":
        assert data["care_level_status"] == "ACTIVE", (
            "an IN_TREATMENT episode carries care_level_status ACTIVE (PRD §3.3)"
        )
    if data["clinical_status"] == "DISCHARGED":
        assert data["discharged_at"] is not None, "a DISCHARGED episode carries discharged_at"


def assert_facility_posture_matches_points(data: dict) -> None:
    """facility_posture is a pure band selection over compliance_risk_points (PRD §2.6)."""
    points = data["compliance_risk_points"]
    if points >= C.POSTURE_FROZEN_MIN:
        expected = "FROZEN"
    elif points >= C.POSTURE_RESTRICTED_MIN:
        expected = "RESTRICTED"
    else:
        expected = "OPEN"
    assert data["facility_posture"] == expected, (
        f"{points} compliance risk points must read {expected}, got {data['facility_posture']}"
    )


def assert_committed_bed_nights(beds, expected: int) -> None:
    """committed_bed_nights is the count of OCCUPIED beds (PRD §2.9)."""
    occupied = [b for b in beds if b["status"] == "OCCUPIED"]
    assert len(occupied) == expected, (
        f"expected {expected} committed bed nights, found {len(occupied)}"
    )


def assert_half_up(expected: float, actual, message: str = "") -> None:
    assert actual == pytest.approx(expected, abs=0.001), (
        message or f"expected {expected}, got {actual}"
    )
