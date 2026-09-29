"""Entity assertions and domain invariant checkers.

Generic primitives (is_valid_uuid, is_iso8601_timestamp, assert_cost_precision)
come from the framework; everything here is PRD-specific.

Note on common fields (PRD §2.4): `ExamAttempt` and `UnmetNeedReport` are
append-only and carry no `updated_at` and no `version` — the assertions below
require those two keys to be ABSENT, not null.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)

from .types import (
    AppealOutcome,
    AssignmentComplianceStatus,
    AssignmentServiceStatus,
    CancelReasonCode,
    ComplaintCategory,
    ComplaintSeverity,
    ComplaintStatus,
    CourthouseStatus,
    CredentialStatus,
    CredentialTier,
    DeliveryMode,
    DisciplinaryActionStatus,
    EthicsTrainingStatus,
    ExamResult,
    ExamType,
    HearingStatus,
    HearingType,
    LanguageTierClass,
    PayClaimStatus,
    PayClaimVariant,
    PriorityClass,
    RemoteEquipmentTier,
    ReportComplianceStatus,
    RosterStatus,
)


def _enum_values(enum_cls) -> List[str]:
    return [member.value for member in enum_cls]


def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: id + created_at + updated_at + version on a mutable entity."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_append_only_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: an append-only entity carries only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "append-only entities must not carry updated_at"
    assert "version" not in data, "append-only entities must not carry version"


def assert_three_fraction_digit_timestamp(value: str) -> None:
    """PRD §2.2: timestamps are ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"timestamp must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO 8601 timestamp: {value!r}"
    assert "." in value, f"timestamp must carry fractional seconds: {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, (
        f"timestamp must carry exactly three fractional digits: {value!r}"
    )


def assert_envelope_meta(body: Dict[str, Any]) -> None:
    """PRD §2.2: meta.api_request_id starts with req_ and the timestamp is ISO 8601."""
    meta = body["meta"]
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with 'req_', got {meta['api_request_id']!r}"
    )
    assert_three_fraction_digit_timestamp(meta["api_request_timestamp"])


# ---------------------------------------------------------------------------
# Configuration entities
# ---------------------------------------------------------------------------
def assert_language(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["code"], str) and len(data["code"]) == 3
    assert data["code"] == data["code"].lower()
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier_class"] in _enum_values(LanguageTierClass)
    assert isinstance(data["oral_exam_available"], bool)
    assert isinstance(data["telephonic_vendor_available"], bool)
    assert isinstance(data["active_credentialed_count"], int)
    assert data["active_credentialed_count"] >= 0


def assert_courthouse(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["county_code"], str) and len(data["county_code"]) == 3
    assert data["county_code"] == data["county_code"].upper()
    assert isinstance(data["courtroom_count"], int) and data["courtroom_count"] >= 1
    assert data["remote_equipment_tier"] in _enum_values(RemoteEquipmentTier)
    assert isinstance(data["vri_concurrent_capacity"], int)
    assert data["vri_concurrent_capacity"] >= 0
    assert data["status"] in _enum_values(CourthouseStatus)
    assert isinstance(data["pay_budget_cents"], int) and data["pay_budget_cents"] >= 0
    assert_courthouse_ledger_invariants(data)


def assert_courthouse_ledger_invariants(data: Dict[str, Any]) -> None:
    """PRD §2.9: available = budget - encumbered - obligated, all integer cents."""
    for field in ("encumbered_pay_cents", "obligated_pay_cents", "available_pay_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["encumbered_pay_cents"] >= 0
    assert data["obligated_pay_cents"] >= 0
    assert data["available_pay_cents"] == (
        data["pay_budget_cents"]
        - data["encumbered_pay_cents"]
        - data["obligated_pay_cents"]
    ), "available_pay_cents must equal budget minus encumbered minus obligated"


def assert_rate_schedule(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["effective_from"], str)
    assert data["effective_through"] is None or isinstance(data["effective_through"], str)
    for field in (
        "master_hourly_cents",
        "certified_hourly_cents",
        "registered_hourly_cents",
        "provisional_hourly_cents",
        "late_cancellation_hours",
        "rare_premium_bracket_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"
    for field in (
        "minimum_call_hours",
        "travel_mileage_rate_cents",
        "travel_free_radius_miles",
        "remote_rate_multiplier",
        "late_cancellation_pay_hours",
        "rare_premium_low_pct",
        "rare_premium_high_pct",
    ):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


# ---------------------------------------------------------------------------
# Roster and credentialing
# ---------------------------------------------------------------------------
def assert_interpreter(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["phone"] is None or isinstance(data["phone"], str)
    assert isinstance(data["home_county_code"], str) and len(data["home_county_code"]) == 3
    assert isinstance(data["accepts_in_person"], bool)
    assert isinstance(data["accepts_remote"], bool)
    assert data["roster_status"] in _enum_values(RosterStatus)
    assert data["ethics_training_status"] in _enum_values(EthicsTrainingStatus)
    assert data["ethics_completed_on"] is None or isinstance(
        data["ethics_completed_on"], str
    )
    assert data["credential_tier"] in _enum_values(CredentialTier)
    assert isinstance(data["credentialed_language_ids"], list)
    assert isinstance(data["complaint_points"], int) and data["complaint_points"] >= 0
    assert_quality_score_bounds(data["rolling_12_month_score"])
    assert_quality_score_bounds(data["lifetime_score"])
    assert isinstance(data["pending_pay_cents"], int) and data["pending_pay_cents"] >= 0
    assert isinstance(data["paid_pay_cents"], int) and data["paid_pay_cents"] >= 0
    assert data["suspension_through"] is None or isinstance(
        data["suspension_through"], str
    )


def assert_quality_score_bounds(score: Any) -> None:
    """PRD §3.2: both quality scores are floored at zero and start at 100."""
    assert isinstance(score, (int, float)), f"quality score must be numeric, got {score!r}"
    assert 0 <= score <= 100, f"quality score out of range: {score!r}"


def assert_credential(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["interpreter_id"])
    assert is_valid_uuid(data["language_id"])
    assert data["target_tier"] in _enum_values(CredentialTier)
    assert data["tier"] is None or data["tier"] in _enum_values(CredentialTier)
    assert data["status"] in _enum_values(CredentialStatus)
    for field in ("written_attempt_count", "oral_attempt_count", "renewal_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    for field in ("written_best_score", "oral_best_score"):
        assert data[field] is None or isinstance(data[field], (int, float))
    for field in ("issued_on", "expires_on", "grace_through"):
        assert data[field] is None or isinstance(data[field], str)
    assert isinstance(data["cycle_credit_hours"], (int, float))


def assert_exam_attempt(data: Dict[str, Any]) -> None:
    """PRD §2.4: ExamAttempt is append-only — no updated_at, no version."""
    assert_append_only_fields(data)
    assert is_valid_uuid(data["credential_id"])
    assert data["exam_type"] in _enum_values(ExamType)
    assert isinstance(data["score"], (int, float)) and 0 <= data["score"] <= 100
    assert isinstance(data["taken_on"], str)
    assert isinstance(data["attempt_ordinal"], int) and data["attempt_ordinal"] >= 1
    assert data["result"] in _enum_values(ExamResult)


# ---------------------------------------------------------------------------
# Calendar, matching and service
# ---------------------------------------------------------------------------
def assert_hearing(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["courthouse_id"])
    assert is_valid_uuid(data["language_id"])
    assert isinstance(data["case_number"], str) and len(data["case_number"]) > 0
    assert data["hearing_type"] in _enum_values(HearingType)
    assert isinstance(data["in_custody"], bool)
    assert_three_fraction_digit_timestamp(data["scheduled_start"])
    assert_three_fraction_digit_timestamp(data["scheduled_end"])
    assert data["requested_delivery_mode"] in _enum_values(DeliveryMode)
    assert data["status"] in _enum_values(HearingStatus)
    assert isinstance(data["lead_time_days"], int)
    assert isinstance(data["priority_score"], int) and 0 <= data["priority_score"] <= 100
    assert data["priority_class"] in _enum_values(PriorityClass)
    assert isinstance(data["continuance_count"], int) and data["continuance_count"] >= 0


def assert_assignment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["hearing_id"])
    assert data["interpreter_id"] is None or is_valid_uuid(data["interpreter_id"])
    assert data["credential_id"] is None or is_valid_uuid(data["credential_id"])
    assert data["credential_tier_snapshot"] is None or (
        data["credential_tier_snapshot"] in _enum_values(CredentialTier)
    )
    assert data["delivery_mode"] in _enum_values(DeliveryMode)
    assert isinstance(data["vendor_served"], bool)
    assert isinstance(data["estimated_one_way_miles"], (int, float))
    assert data["actual_one_way_miles"] is None or isinstance(
        data["actual_one_way_miles"], (int, float)
    )
    assert data["service_status"] in _enum_values(AssignmentServiceStatus)
    assert data["compliance_status"] in _enum_values(AssignmentComplianceStatus)
    assert data["cancel_reason_code"] is None or (
        data["cancel_reason_code"] in _enum_values(CancelReasonCode)
    )


def assert_pay_claim(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["assignment_id"])
    assert is_valid_uuid(data["rate_schedule_id"])
    assert data["variant"] in _enum_values(PayClaimVariant)
    assert data["status"] in _enum_values(PayClaimStatus)
    assert_billable_hours_quarter_increment(data["billable_hours"])
    for field in ("service_cents", "rare_premium_cents", "travel_cents",
                  "provisional_total_cents"):
        assert isinstance(data[field], int), f"{field} must be integer cents"
        assert data[field] >= 0
    assert data["final_total_cents"] is None or isinstance(data["final_total_cents"], int)
    assert isinstance(data["late_cancellation"], bool)
    assert data["payment_reference"] is None or isinstance(data["payment_reference"], str)


def assert_billable_hours_quarter_increment(hours: Any) -> None:
    """PRD §2.8: billable_hours carries two decimals and is a multiple of 0.25."""
    assert isinstance(hours, (int, float)), f"billable_hours must be numeric: {hours!r}"
    quarters = round(float(hours) * 4, 6)
    assert abs(quarters - round(quarters)) < 1e-9, (
        f"billable_hours must be a multiple of 0.25, got {hours!r}"
    )


def assert_pay_components_sum(data: Dict[str, Any], total_field: str) -> None:
    """PRD §2.8: the authoritative total is the sum of the three rounded components."""
    assert data[total_field] == (
        data["service_cents"] + data["rare_premium_cents"] + data["travel_cents"]
    ), (
        f"{total_field} must equal service_cents + rare_premium_cents + travel_cents"
    )


# ---------------------------------------------------------------------------
# Discipline
# ---------------------------------------------------------------------------
def assert_complaint(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["interpreter_id"])
    assert data["assignment_id"] is None or is_valid_uuid(data["assignment_id"])
    assert data["category"] in _enum_values(ComplaintCategory)
    assert data["severity"] in _enum_values(ComplaintSeverity)
    assert isinstance(data["narrative"], str) and len(data["narrative"]) > 0
    assert isinstance(data["filed_by_user_id"], str) and len(data["filed_by_user_id"]) > 0
    assert data["status"] in _enum_values(ComplaintStatus)
    assert isinstance(data["remand_count"], int) and data["remand_count"] >= 0
    for field in ("reviewer_user_id", "adjudicator_user_id", "reviewer_recommendation",
                  "disposition", "adjudicated_at", "appeal_filed_at"):
        assert field in data, f"complaint must expose {field}"


def assert_disciplinary_action(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["complaint_id"])
    assert is_valid_uuid(data["interpreter_id"])
    assert data["action_type"] in ["LETTER", "PROBATION", "SUSPENSION", "REVOCATION"]
    assert isinstance(data["points"], int) and data["points"] >= 0
    assert isinstance(data["effective_from"], str)
    assert data["effective_through"] is None or isinstance(data["effective_through"], str)
    assert data["status"] in _enum_values(DisciplinaryActionStatus)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def assert_unmet_need_report(data: Dict[str, Any]) -> None:
    """PRD §2.4: UnmetNeedReport is append-only — no updated_at, no version."""
    assert_append_only_fields(data)
    assert is_valid_uuid(data["courthouse_id"])
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    for field in ("resolved_hearing_count", "served_hearing_count",
                  "unmet_hearing_count", "rare_language_unmet_count"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["resolved_hearing_count"] == (
        data["served_hearing_count"] + data["unmet_hearing_count"]
    ), "resolved_hearing_count must equal served plus unmet"
    assert isinstance(data["coverage_rate_pct"], (int, float))
    assert 0 <= data["coverage_rate_pct"] <= 100
    assert data["compliance_status"] in _enum_values(ReportComplianceStatus)
    assert isinstance(data["by_language"], dict)


def assert_quality_score_read(data: Dict[str, Any]) -> None:
    """PRD §3.2: the computed read exposes both variants and the point split."""
    assert is_valid_uuid(data["interpreter_id"])
    assert_quality_score_bounds(data["rolling_12_month_score"])
    assert_quality_score_bounds(data["lifetime_score"])
    assert isinstance(data["complaint_points"], int)
    assert isinstance(data["recent_points"], int)
    assert isinstance(data["older_points"], int)


def assert_sweep_response(data: Dict[str, Any]) -> None:
    """PRD §3.10: the sweep answers with swept_at plus the identifier arrays."""
    assert_three_fraction_digit_timestamp(data["swept_at"])
    for field in ("lapsed_credential_ids", "downgraded_interpreter_ids",
                  "expired_action_ids", "reinstated_interpreter_ids",
                  "unmet_hearing_ids", "cancelled_assignment_ids",
                  "voided_pay_claim_ids"):
        assert isinstance(data[field], list), f"{field} must be an array"


def assert_ordered_by(rows: List[Dict[str, Any]], *fields: str) -> None:
    """Assert a listing is ordered ascending on the given field tuple."""
    keys = [tuple(row[f] for f in fields) for row in rows]
    assert keys == sorted(keys), f"rows are not ordered ascending by {fields}: {keys}"
