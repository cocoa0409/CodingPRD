"""Entity assertions and domain invariant checkers for the care management API."""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AdjudicationStatus, AssignmentReason, CadenceTier, CapacityStatus,
    CarePlanStatus, CompliancePosture, ContractStatus, CredentialLevel,
    EngagementStatus, EnrollmentStatus, EventType, GoalDomain, GoalStatus,
    InterventionModality, InterventionStatus, ReferralStatus, RiskTier,
    RoiMethod, Severity, SocialDomain, SocialNeedStatus, StratificationVariant,
    TouchModality, TouchOutcome, TouchStatus, TouchType,
)

_UUID_MSG = "id must be a bare UUID with no type prefix"


def _values(enum_cls):
    return [m.value for m in enum_cls]


def assert_identity_fields(data: dict) -> None:
    """PRD §2.4: every persisted resource carries a bare UUID id and created_at."""
    assert is_valid_uuid(data.get("id", "")), _UUID_MSG
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC instant, got {data.get('created_at')!r}"
    )


def assert_mutable_record_fields(data: dict) -> None:
    """PRD §2.4: mutable resources also carry updated_at and an integer version."""
    assert_identity_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC instant, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_append_only_record_fields(data: dict) -> None:
    """PRD §2.4: the three ledgers carry only id and created_at."""
    assert_identity_fields(data)
    assert "updated_at" not in data, "append-only records have no updated_at"
    assert "version" not in data, "append-only records have no version field"


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_member(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert isinstance(data["external_member_id"], str) and data["external_member_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["chronic_condition_count"], int)
    assert data["chronic_condition_count"] >= 0
    assert data["social_data_consent_status"] in ("GRANTED", "REVOKED")
    for field in ("latest_concurrent_tier", "latest_prospective_tier"):
        assert data.get(field) is None or data[field] in _values(RiskTier)
    for field in ("latest_concurrent_score", "latest_prospective_score"):
        assert data.get(field) is None or isinstance(data[field], int)


def assert_risk_stratification(data: dict) -> None:
    assert_append_only_record_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["variant"] in _values(StratificationVariant)
    assert isinstance(data["as_of_date"], str) and len(data["as_of_date"]) == 10
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 100
    assert data["tier"] in _values(RiskTier)
    assert isinstance(data["included_event_count"], int)
    for field in ("utilization_points", "chronic_points",
                  "social_need_points", "raw_score"):
        assert isinstance(data[field], (int, float))


def assert_program(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["min_risk_tier"] in _values(RiskTier)
    assert data["stratification_variant"] in _values(StratificationVariant)
    assert isinstance(data["required_credential_levels"], list)
    assert data["required_credential_levels"]
    for level in data["required_credential_levels"]:
        assert level in _values(CredentialLevel)
    for field in ("care_plan_review_interval_days", "toc_outreach_hours",
                  "referral_loop_days", "staff_minute_budget", "hourly_cost_cents",
                  "cohort_benchmark_pmpm_cents", "committed_staff_minutes",
                  "delivered_staff_minutes"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_care_manager(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["credential_level"] in _values(CredentialLevel)
    assert isinstance(data["licensed_state_codes"], list)
    assert data["licensed_state_codes"]
    assert isinstance(data["capacity_points"], (int, float))
    assert data["capacity_points"] > 0
    assert isinstance(data["assigned_caseload_points"], (int, float))
    assert data["capacity_status"] in _values(CapacityStatus)
    assert isinstance(data["active_enrollment_count"], int)
    assert_care_manager_ledger_invariants(data)


def assert_care_manager_ledger_invariants(data: dict) -> None:
    """PRD §2.9: capacity_status is OVER_CAPACITY exactly when the ledger
    strictly exceeds the ceiling; equality is still OPEN."""
    load = round(float(data["assigned_caseload_points"]), 1)
    ceiling = round(float(data["capacity_points"]), 1)
    expected = "OVER_CAPACITY" if load > ceiling else "OPEN"
    assert data["capacity_status"] == expected, (
        f"capacity_status should be {expected} for load {load} against "
        f"ceiling {ceiling}, got {data['capacity_status']}"
    )
    assert data["active_enrollment_count"] >= 0


def assert_enrollment(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["program_id"])
    assert is_valid_uuid(data["care_manager_id"])
    assert data["enrollment_status"] in _values(EnrollmentStatus)
    assert data["engagement_status"] in _values(EngagementStatus)
    assert data["risk_tier_at_enrollment"] in _values(RiskTier)
    assert isinstance(data["risk_score_at_enrollment"], int)
    assert data["cadence_tier"] in _values(CadenceTier)
    assert data["cadence_tier_snapshot"] in _values(CadenceTier)
    pre_toc = data.get("pre_toc_cadence_tier")
    assert pre_toc is None or pre_toc in _values(CadenceTier)
    assert isinstance(data["acuity_weight_points"], (int, float))
    assert data["assignment_reason"] in _values(AssignmentReason)
    assert isinstance(data["consecutive_failed_outreach_count"], int)
    assert isinstance(data["reached_touch_count"], int)
    assert isinstance(data["engagement_score"], int)
    assert 0 <= data["engagement_score"] <= 100


def assert_care_plan(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["authored_by_care_manager_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["status"] in _values(CarePlanStatus)
    assert isinstance(data["plan_version_no"], int) and data["plan_version_no"] >= 1
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert isinstance(data["at_risk_goal_count"], int)
    assert data["compliance_posture"] in _values(CompliancePosture)


def assert_care_plan_goal(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert is_valid_uuid(data["care_plan_id"])
    assert data["domain"] in _values(GoalDomain)
    assert isinstance(data["description"], str) and data["description"]
    assert isinstance(data["target_date"], str)
    assert data["status"] in _values(GoalStatus)
    assert isinstance(data["barrier_flag"], bool)
    assert isinstance(data["planned_intervention_count"], int)
    assert isinstance(data["completed_intervention_count"], int)


def assert_intervention(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert is_valid_uuid(data["goal_id"])
    assert data["modality"] in _values(InterventionModality)
    assert isinstance(data["staff_minutes"], int) and data["staff_minutes"] > 0
    assert data["status"] in _values(InterventionStatus)
    assert isinstance(data["cost_cents"], int), "cost_cents is carried in whole cents"


def assert_touch(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["care_manager_id"])
    assert data["touch_type"] in _values(TouchType)
    assert data["modality"] in _values(TouchModality)
    assert is_iso8601_timestamp(data["scheduled_start_at"])
    assert is_iso8601_timestamp(data["scheduled_end_at"])
    assert data["status"] in _values(TouchStatus)
    outcome = data.get("outcome")
    assert outcome is None or outcome in _values(TouchOutcome)
    assert isinstance(data["satisfied_toc_obligation"], bool)


def assert_transition_event(data: dict) -> None:
    assert_append_only_record_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["event_type"] in _values(EventType)
    assert is_iso8601_timestamp(data["occurred_at"])
    assert isinstance(data["facility_name"], str) and data["facility_name"]
    assert isinstance(data["episode_cost_cents"], int)
    assert data["adjudication_status"] in _values(AdjudicationStatus)
    assert isinstance(data["toc_triggered_enrollment_count"], int)


def assert_social_need(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["domain"] in _values(SocialDomain)
    assert data["severity"] in _values(Severity)
    assert data["status"] in _values(SocialNeedStatus)
    assert isinstance(data["escalation_count"], int)
    assert is_iso8601_timestamp(data["identified_at"])


def assert_community_resource(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["served_domains"], list) and data["served_domains"]
    for domain in data["served_domains"]:
        assert domain in _values(SocialDomain)
    assert isinstance(data["service_state_codes"], list)
    assert data["service_state_codes"]
    assert data["contract_status"] in _values(ContractStatus)
    assert isinstance(data["concurrent_slot_capacity"], int)
    assert data["concurrent_slot_capacity"] >= 1
    assert isinstance(data["open_referral_count"], int)
    assert isinstance(data["closed_loop_count"], int)


def assert_referral(data: dict) -> None:
    assert_mutable_record_fields(data)
    assert is_valid_uuid(data["social_need_id"])
    assert is_valid_uuid(data["community_resource_id"])
    assert is_valid_uuid(data["sent_by_care_manager_id"])
    assert data["status"] in _values(ReferralStatus)
    assert is_iso8601_timestamp(data["service_start_at"])
    assert is_iso8601_timestamp(data["service_end_at"])
    assert is_iso8601_timestamp(data["sent_at"])


def assert_roi_measurement(data: dict) -> None:
    assert_append_only_record_fields(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["method"] in _values(RoiMethod)
    for field in ("baseline_pmpm_cents", "monthly_projected_cost_cents",
                  "intervention_month_count", "projected_cost_cents",
                  "actual_cost_cents", "gross_savings_cents",
                  "program_cost_cents", "net_savings_cents"):
        assert isinstance(data[field], int), f"{field} must be a whole-cent integer"
    ratio = data.get("roi_ratio")
    assert ratio is None or isinstance(ratio, (int, float))
    assert isinstance(data["superseded"], bool)
    assert is_iso8601_timestamp(data["measurement_end_at"])


# ─── Domain invariant checkers ────────────────────────────────────────────

def assert_caseload_points(actual, expected) -> None:
    """PRD §2.7: caseload point values are carried to one decimal place."""
    assert float(actual) == pytest.approx(float(expected), abs=0.001), (
        f"Expected caseload points {expected}, got {actual}"
    )


def assert_acuity_weight(enrollment: dict, tier_points: int, multiplier: float) -> None:
    expected = round(tier_points * multiplier + 1e-9, 1)
    assert_caseload_points(enrollment["acuity_weight_points"], expected)


def assert_roi_ratio(actual, expected) -> None:
    """PRD §2.7: the return-on-investment ratio carries two decimal places."""
    if expected is None:
        assert actual is None, f"Expected roi_ratio null, got {actual}"
        return
    assert actual is not None, "Expected a roi_ratio, got null"
    assert float(actual) == pytest.approx(float(expected), abs=0.001), (
        f"Expected roi_ratio {expected}, got {actual}"
    )


def assert_compliance_rate(actual, expected) -> None:
    """PRD §2.7: the compliance rate of the accreditation file carries one decimal."""
    assert float(actual) == pytest.approx(float(expected), abs=0.05), (
        f"Expected compliance_rate_pct {expected}, got {actual}"
    )
