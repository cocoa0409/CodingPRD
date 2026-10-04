"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_market(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["market_code"], str) and data["market_code"]
    assert isinstance(data["display_name"], str)
    assert isinstance(data["polygon_geojson"], str)
    assert isinstance(data["response_window_minutes_urgent"], int)
    assert isinstance(data["response_window_minutes_standard"], int)
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["open_visit_count"], int)


def assert_payer_contract(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["payer_code"], str)
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["urgent_base_rate_cents"], int)
    assert isinstance(data["standard_base_rate_cents"], int)
    assert isinstance(data["place_of_service_modifier_pct"], (int, float))
    assert isinstance(data["max_claim_cents"], int)
    assert data["status"] in ["DRAFT", "ACTIVE", "EXPIRED", "TERMINATED"]


def assert_formulary_entry(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["drug_code"], str)
    assert isinstance(data["max_units_per_visit"], int)
    assert isinstance(data["requires_physician_preauth"], bool)
    assert isinstance(data["unit_price_cents"], int)


def assert_patient(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["date_of_birth"], str)
    assert isinstance(data["payer_code"], str)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["pcp_name"], str)
    assert isinstance(data["pcp_npi"], str)
    assert isinstance(data["comorbidity_count"], int)
    assert isinstance(data["home_address_geo"], str)


def assert_care_team(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["market_id"])
    assert isinstance(data["app_user_id"], str)
    assert isinstance(data["tech_user_id"], str)
    assert isinstance(data["supervising_physician_user_id"], str)
    assert isinstance(data["skill_tags"], list)
    assert data["status"] in ["ROSTERED", "AVAILABLE", "ON_DISPATCH", "OFF_DUTY"]
    assert isinstance(data["active_dispatch_count"], int)


def assert_vehicle_shift(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "ACTIVE", "EXTENDED", "CLOSED", "CANCELLED"]
    assert isinstance(data["overtime_minutes"], int)


def assert_visit_request(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "INTAKE", "TRIAGE_PENDING", "TRIAGED", "EMS_DIVERTED", "DECLINED",
        "DISPATCH_PENDING", "EN_ROUTE", "ON_SCENE", "DISPOSITIONED",
        "ESCALATED_TRANSPORT", "CLAIM_DRAFT", "CLAIM_SUBMITTED",
        "CLAIM_ADJUDICATED_PAID", "CLAIM_ADJUDICATED_DENIED",
        "CLAIM_APPEALED", "CLOSED",
    ]
    assert isinstance(data["sla_breached"], bool)


def assert_triage_assessment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["heart_rate"], int)
    assert isinstance(data["systolic_bp"], int)
    assert isinstance(data["spo2_pct"], int)
    assert data["outcome"] in ["DRAFT", "APPROPRIATE", "EMERGENCY_DIVERTED", "INAPPROPRIATE"]


def assert_dispatch_assignment(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "OFFERED", "ACCEPTED", "REJECTED", "EN_ROUTE", "ARRIVED",
        "COMPLETED", "CANCELLED",
    ]


def assert_encounter(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "STARTED", "DIAGNOSTICS", "DISPOSITION_REVIEW",
        "DISCHARGED_HOME", "ESCALATED_TRANSPORT", "ABORTED",
    ]


def assert_diagnostic_order(data: dict):
    _assert_common_fields(data)
    assert data["order_kind"] in ["POCT", "IMAGING", "IV_INFUSION"]
    assert data["status"] in [
        "ORDERED", "COLLECTED", "RESULTED", "VERIFIED", "AMENDED", "CANCELLED",
    ]


def assert_claim(data: dict):
    _assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "ADJUDICATED_PAID", "ADJUDICATED_DENIED", "APPEALED",
    ]
    assert isinstance(data["provisional_total_cents"], int)
    assert isinstance(data["final_total_cents"], int)


def assert_claim_line(data: dict):
    _assert_common_fields(data)
    assert data["line_kind"] in ["BASE_VISIT", "DIAGNOSTIC", "IV_DRUG"]
    assert isinstance(data["amount_cents"], int)


def assert_follow_up_notice(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["QUEUED", "SENT", "FAILED"]


def assert_monitoring_checkin(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "MISSED", "ESCALATED"]
