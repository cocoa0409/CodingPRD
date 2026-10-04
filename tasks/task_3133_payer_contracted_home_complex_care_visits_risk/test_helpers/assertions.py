"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def assert_care_program(data):
    _assert_common(data)
    assert isinstance(data["program_code"], str) and data["program_code"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["service_geography_zips"], list)
    assert isinstance(data["urgent_response_sla_hours"], int)
    assert isinstance(data["current_period_index"], int)


def assert_payer_contract(data):
    _assert_common(data)
    assert isinstance(data["care_program_id"], str)
    assert isinstance(data["payer_name"], str) and data["payer_name"]
    assert data["payment_model"] in ("CAPITATED", "SHARED_SAVINGS")


def assert_pcp_provider(data):
    _assert_common(data)
    assert isinstance(data["npi"], str) and data["npi"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["practice_name"], str)
    assert isinstance(data["notification_opt_in"], bool)


def assert_clinician(data):
    _assert_common(data)
    assert data["discipline"] in ("NP", "SW", "BH")
    assert isinstance(data["home_zip"], str)
    assert isinstance(data["max_daily_visits"], int)
    assert isinstance(data["active_daily_visit_count"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_member(data):
    _assert_common(data)
    assert isinstance(data["member_external_id"], str)
    assert isinstance(data["chronic_condition_codes"], list)
    assert isinstance(data["prior_ed_visits_12mo"], int)
    assert isinstance(data["prior_inpatient_admits_12mo"], int)
    assert data["risk_tier"] in ("LOW", "MEDIUM", "HIGH", "VERY_HIGH")


def assert_enrollment(data):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert data["status"] in (
        "IDENTIFIED", "OUTREACH", "CONSENTED", "ACTIVE", "DECLINED", "DISENROLLED",
    )
    assert isinstance(data["is_current"], bool)
    assert isinstance(data["outreach_attempts"], int)


def assert_care_team(data):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "RETIRED")
    assert isinstance(data["composition_complete"], bool)


def assert_visit(data):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert data["visit_type"] in (
        "INITIAL_ASSESSMENT", "ROUTINE_FOLLOWUP", "URGENT", "POST_ED_FOLLOWUP",
    )
    assert data["status"] in (
        "SCHEDULED", "EN_ROUTE", "IN_PROGRESS", "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert isinstance(data["reschedule_count"], int)


def assert_assessment(data):
    _assert_common(data)
    assert isinstance(data["visit_id"], str)
    assert data["status"] in ("DRAFT", "SUBMITTED", "LOCKED")


def assert_episode(data):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert data["trigger_source"] in (
        "MEMBER_CALL", "PCP_ALERT", "PLAN_ALERT", "POST_ED_DISCHARGE",
    )
    assert data["status"] in ("TRIGGERED", "DISPATCHED", "ON_SCENE", "RESOLVED", "LAPSED")


def assert_performance_measurement(data):
    _assert_common(data)
    assert isinstance(data["payer_contract_id"], str)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["period_index"], int)
    for counter in (
        "urgent_episodes_triggered", "urgent_episodes_sla_met",
        "urgent_episodes_avoided_ed", "visits_completed",
        "visits_no_show", "visits_cancelled",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert 0.0 <= data["composite_score"] <= 1.0


def assert_settlement(data):
    _assert_common(data)
    assert isinstance(data["payer_contract_id"], str)
    assert isinstance(data["period_index"], int)
    assert data["status"] in ("PROVISIONAL", "FINALIZED", "PAID", "VOIDED")
    assert isinstance(data["enrolled_member_count"], int)


def assert_medical_cost(data):
    _assert_common(data)
    assert isinstance(data["payer_contract_id"], str)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["period_index"], int)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def unwrap_singleton(data):
    """1:1 sub-resource GET endpoints return the resource; tolerate either an
    object payload or a single-element array payload."""
    if isinstance(data, list):
        assert len(data) <= 1, f"expected at most one row, got {len(data)}"
        return data[0] if data else None
    if isinstance(data, dict) and data:
        return data
    return None
