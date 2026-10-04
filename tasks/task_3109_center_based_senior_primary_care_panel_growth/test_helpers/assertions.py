"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_center(data: dict):
    """Validate a Center response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["neighborhood_code"], str) and data["neighborhood_code"]
    assert isinstance(data["opened_on"], str) and data["opened_on"]
    assert data["status"] in ["PRE_OPEN", "OPEN", "SATURATED", "CLOSED"]
    assert data["profitability_tier"] in ["RAMP", "BREAKEVEN", "MATURE"]
    assert isinstance(data["maturity_months"], int)
    assert isinstance(data["cumulative_contribution_cents"], int)
    assert isinstance(data["panel_fill_ratio"], (int, float))
    assert isinstance(data["ed_referral_count_current_month"], int)


def assert_care_team(data: dict):
    """Validate a CareTeam response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", "")), "center_id must be a valid UUID"
    assert isinstance(data["team_label"], str) and data["team_label"]
    assert isinstance(data["panel_cap"], int) and data["panel_cap"] >= 1
    assert isinstance(data["physician_count"], int)
    assert isinstance(data["chw_count"], int)
    assert isinstance(data["behavioral_count"], int)
    assert isinstance(data["staffing_score"], (int, float))
    assert isinstance(data["active_panel_count"], int) and data["active_panel_count"] >= 0
    assert isinstance(data["waitlist_depth"], int) and data["waitlist_depth"] >= 0
    assert isinstance(data["accepting"], bool)


def assert_patient(data: dict):
    """Validate a Patient response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert isinstance(data["zip_code"], str) and data["zip_code"]
    assert isinstance(data["risk_score"], (int, float))
    assert isinstance(data["transport_dependent"], bool)
    assert isinstance(data["no_show_strikes"], int) and data["no_show_strikes"] >= 0


def assert_health_plan(data: dict):
    """Validate a HealthPlan response against the PRD contract."""
    _assert_common_fields(data)
    assert isinstance(data["plan_name"], str) and data["plan_name"]
    assert data["contract_type"] in ["FULL_RISK", "SHARED_SAVINGS"]
    assert isinstance(data["base_pmpm_cents"], int)
    assert isinstance(data["risk_adjust_factor"], (int, float))
    assert isinstance(data["revenue_share_pct"], (int, float))


def assert_attribution(data: dict):
    """Validate a PatientAttribution response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("health_plan_id", ""))
    assert is_valid_uuid(data.get("care_team_id", ""))
    assert isinstance(data["effective_month"], str)
    assert data["status"] in [
        "PENDING", "ACTIVE", "WAITLISTED", "DISENROLLED", "REATTRIBUTED",
    ]
    assert "disenrolled_month" in data


def assert_appointment(data: dict):
    """Validate an Appointment response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("care_team_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("room_id", ""))
    assert isinstance(data["start_utc"], str)
    assert data["duration_minutes"] in [20, 40, 60]
    assert data["kind"] in ["PRIMARY", "BEHAVIORAL", "CHW_OUTREACH"]
    assert data["status"] in [
        "SCHEDULED", "CHECKED_IN", "COMPLETED", "COMPLETED_NO_SHOW", "CANCELLED",
    ]


def assert_room(data: dict):
    """Validate a CenterRoom response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert isinstance(data["room_label"], str) and data["room_label"]
    assert isinstance(data["supports_behavioral"], bool)


def assert_vehicle(data: dict):
    """Validate a Vehicle response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert isinstance(data["plate"], str) and data["plate"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["wheelchair_capable"], bool)


def assert_ride_request(data: dict):
    """Validate a RideRequest response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("appointment_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert isinstance(data["pickup_window_start"], str)
    assert isinstance(data["pickup_window_end"], str)
    assert data["status"] in [
        "REQUESTED", "DISPATCHED", "EN_ROUTE", "DELIVERED",
        "FAILED_NO_SHOW", "RECOVERED", "CANCELLED",
    ]
    assert isinstance(data["failure_count"], int) and data["failure_count"] >= 0
    assert "assigned_vehicle_id" in data


def assert_triage_case(data: dict):
    """Validate a TriageCase response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data["channel"] in ["AFTER_HOURS_LINE", "WALK_IN", "CARE_TEAM_ESCALATION"]
    assert data["severity"] in ["LOW", "MODERATE", "HIGH"]
    assert data["status"] in [
        "OPEN", "RESOLVED_DIVERTED", "RESOLVED_ED", "RESOLVED_SELF_CARE", "EXPIRED",
    ]
    assert "disposition" in data


def assert_cost_claim(data: dict):
    """Validate a CostOfCareClaim response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert is_valid_uuid(data.get("patient_id", ""))
    assert isinstance(data["service_month"], str)
    assert data["category"] in [
        "ED_VISIT", "INPATIENT", "SPECIALIST", "PHARMACY", "TRANSPORT", "INTERNAL_VISIT",
    ]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ["SUBMITTED", "ADJUDICATED", "SETTLED", "REJECTED"]


def assert_monthly_settlement(data: dict):
    """Validate a MonthlySettlement response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert isinstance(data["period_month"], str)
    assert data["status"] in ["OPEN", "CLOSED_PROVISIONAL", "FINALIZED", "VOIDED"]


def assert_outreach_event(data: dict):
    """Validate an OutreachEvent response against the PRD contract."""
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert isinstance(data["event_label"], str) and data["event_label"]
    assert isinstance(data["scheduled_on"], str)
    assert isinstance(data["expected_attendance"], int)
    assert isinstance(data["attributed_signups"], int) and data["attributed_signups"] >= 0
