"""Entity assertions and value comparators.

``assert_instant`` compares ISO 8601 instants semantically: the contract
renders timestamps with three fractional digits (§2.5) while the logical
clock default is written without any (§2.4), so both spellings of one
instant must compare equal.
"""

from typing import Any, Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def canonical_instant(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO 8601 UTC instant to ``YYYY-MM-DDTHH:MM:SS.mmmZ``."""
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) == 10:  # date-precision value: treat as midnight UTC
        text = f"{text}T00:00:00"
    if text.endswith("Z"):
        text = text[:-1]
    if "." in text:
        head, frac = text.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = text, "000"
    return f"{head}.{frac}Z"


def assert_instant(actual: Optional[str], expected: Optional[str], label: str = "instant") -> None:
    """Assert two ISO 8601 instants (or date-precision values) denote the same moment."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_two_dp(actual: Any, expected: float, label: str = "value") -> None:
    """Assert a number equals the expected value at 2-decimal precision."""
    assert isinstance(actual, (int, float)) and not isinstance(actual, bool), (
        f"{label}: expected a number, got {actual!r}"
    )
    assert abs(float(actual) - expected) < 0.005, (
        f"{label}: expected {expected}, got {actual!r}"
    )


def _assert_common_fields(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def _assert_event_fields(data: dict) -> None:
    """Ledger-style resources carry only id + created_at (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "event resources must not carry updated_at"
    assert "version" not in data, "event resources must not carry version"


def assert_installation(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["command_code"], str) and data["command_code"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["max_internship_duration_days"], int) and data["max_internship_duration_days"] >= 1
    assert isinstance(data["appeal_window_days"], int) and data["appeal_window_days"] >= 1
    assert isinstance(data["requires_tap_complete"], bool)
    assert isinstance(data["excluded_pay_grades"], list)


def assert_service_member(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["service_branch"] in ["ARMY", "NAVY", "AIR_FORCE", "MARINES", "SPACE_FORCE", "COAST_GUARD"]
    assert isinstance(data["pay_grade"], str) and data["pay_grade"]
    assert isinstance(data["skills"], list)
    assert is_valid_uuid(data.get("home_installation_id", ""))
    assert data["service_status"] in ["ACTIVE_DUTY", "SEPARATED"]
    assert data["tap_stage"] in [
        "TAP_NOT_STARTED",
        "PRESEPARATION_COUNSELING_DONE",
        "CORE_CURRICULUM_DONE",
        "CAPSTONE_DONE",
    ]
    assert isinstance(data["active_match_count"], int) and data["active_match_count"] >= 0
    assert isinstance(data["days_until_separation"], int)


def assert_application(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("service_member_id", ""))
    assert is_valid_uuid(data.get("installation_id", ""))
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "UNDER_APPEAL"]
    assert is_iso8601_timestamp(data.get("submitted_at", ""))
    assert isinstance(data["days_until_separation_at_submission"], int)
    assert isinstance(data["appeal_count"], int) and data["appeal_count"] >= 0


def assert_employer(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["industry_code"], str) and data["industry_code"]
    assert data["authorization_status"] in [
        "PENDING_AUTHORIZATION",
        "AUTHORIZED",
        "SUSPENDED",
        "AUTHORIZATION_LAPSED",
        "REVOKED",
    ]
    assert isinstance(data["pending_violations"], int) and data["pending_violations"] >= 0


def assert_opening(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employer_id", ""))
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["required_skills"], list)
    assert data["location_type"] in ["ON_SITE", "REMOTE"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["filled_count"], int) and data["filled_count"] >= 0
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_match(data: dict) -> None:
    _assert_common_fields(data)
    for fk in ("internship_application_id", "employer_opening_id", "service_member_id", "employer_id", "installation_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    assert data["match_status"] in [
        "PROPOSED",
        "INSTALLATION_APPROVED",
        "INSTALLATION_DENIED",
        "ACTIVE",
        "COMPLETED",
        "TERMINATED_EARLY",
        "MATCH_VOIDED",
    ]
    assert data["plan_status"] in ["PLAN_DRAFT", "PLAN_SUBMITTED", "PLAN_APPROVED", "PLAN_RETURNED"]
    assert isinstance(data["learning_objectives"], list)
    assert isinstance(data["plan_revision_count"], int) and data["plan_revision_count"] >= 0
    assert isinstance(data["flagged_wage_violation"], bool)
    assert_two_dp(data["resolution_ratio"], float(data["resolution_ratio"]), "resolution_ratio")
    assert 0.0 <= float(data["resolution_ratio"]) <= 1.0
    assert 0.0 <= float(data["mastery_ratio"]) <= 1.0


def assert_supervision_report(data: dict) -> None:
    _assert_event_fields(data)
    assert is_valid_uuid(data.get("internship_match_id", ""))
    assert isinstance(data["hours_supervised"], int) and data["hours_supervised"] >= 0
    assert isinstance(data["supervisor_name"], str) and data["supervisor_name"]


def assert_wage_record(data: dict) -> None:
    _assert_event_fields(data)
    assert is_valid_uuid(data.get("internship_match_id", ""))
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["is_violation"], bool)


def assert_audit(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("employer_id", ""))
    assert data["status"] in ["OPEN", "CLOSED_CLEARED", "CLOSED_SANCTIONED"]
    assert is_iso8601_timestamp(data.get("opened_at", ""))


def assert_conversion_record(data: dict) -> None:
    _assert_event_fields(data)
    assert is_valid_uuid(data.get("internship_match_id", ""))
    assert isinstance(data["offer_made"], bool)
    assert isinstance(data["offer_accepted"], bool)
    assert isinstance(data["hired"], bool)
    assert data["hired"] == (data["offer_made"] and data["offer_accepted"]), (
        "hired must equal offer_made AND offer_accepted"
    )
