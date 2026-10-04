"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive int, got {data.get('version')!r}"
    )


def assert_plan_tier(data: dict):
    _assert_common_fields(data)
    assert data["code"] in {"EMERGENCY_ONLY", "SAFETY", "SAFETY_REMOTE", "PREMIUM"}
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    for flag in ("allows_emergency", "allows_remote_commands", "allows_navigation"):
        assert isinstance(data[flag], bool), f"{flag} must be bool"
    assert isinstance(data["allows_data_gb"], (int, float)) and data["allows_data_gb"] >= 0
    assert data["status"] in {"ACTIVE", "RETIRED"}


def assert_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["phone"], str) and data["phone"]
    assert isinstance(data["home_region_code"], str)
    assert data["status"] in {"ACTIVE", "CLOSED"}


def assert_vehicle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) == 17
    assert isinstance(data["make"], str) and isinstance(data["model"], str)
    assert isinstance(data["model_year"], int) and data["model_year"] >= 2015
    assert isinstance(data["region_code"], str)
    assert data["hardware_generation"] in (4, 5)
    assert data["status"] in {"ACTIVE", "STOLEN_REPORTED", "RECOVERED", "DECOMMISSIONED"}
    assert isinstance(data.get("account_id"), str)


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["tier_code"], str)
    assert data["status"] in {
        "TRIAL", "ACTIVE", "PAST_DUE", "LAPSED", "EMERGENCY_RETAINED", "CANCELLED",
    }
    assert isinstance(data.get("trial_start_date"), str)
    assert isinstance(data.get("trial_end_date"), str)
    assert isinstance(data.get("current_period_start"), str)
    assert isinstance(data.get("emergency_only_flag"), bool)
    assert isinstance(data.get("period_remote_commands_used"), int)
    assert isinstance(data.get("conversion_fee_paid_cents"), int)


def assert_coverage_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["region_code"], str)
    for flag in ("has_cellular", "supports_data", "supports_navigation"):
        assert isinstance(data[flag], bool), f"{flag} must be bool"


def assert_crash_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["delta_v_kph"], (int, float)) and data["delta_v_kph"] >= 0
    assert isinstance(data["rollover_detected"], bool)
    assert isinstance(data["airbag_deployed"], bool)
    assert isinstance(data["location_region_code"], str)
    assert isinstance(data["severity_score"], (int, float))
    assert data["severity_band"] in {"MINOR", "MODERATE", "SEVERE"}
    assert data["status"] in {
        "RECEIVED", "ADVISOR_CONNECTED", "DISPATCH_COORDINATED", "CLOSED_NO_INJURY",
        "CLOSED_DISPATCHED", "REJECTED_NO_COVERAGE", "REJECTED_NO_ENTITLEMENT",
    }


def assert_dispatch_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crash_event_id"], str)
    assert isinstance(data["psap_id"], str)
    assert data["status"] in {"PENDING", "LOCATION_SENT", "ACKNOWLEDGED", "CANCELLED"}


def assert_psap(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str)
    assert isinstance(data["accepts_location_transfer"], bool)
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


def assert_stolen_vehicle_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["police_report_number"], str) and data["police_report_number"]
    assert isinstance(data["reporting_agency"], str) and data["reporting_agency"]
    assert data["status"] in {
        "REPORTED", "VERIFIED", "SLOWDOWN_ARMED", "SLOWDOWN_EXECUTED",
        "CLOSED_RECOVERED", "CLOSED_UNVERIFIED",
    }


def assert_remote_command(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert data["command_type"] in {"LOCK", "UNLOCK", "HORN_LIGHTS", "LOCATE"}
    assert data["status"] in {"PENDING", "SENT", "ACKNOWLEDGED", "FAILED", "EXPIRED"}
    assert isinstance(data["is_emergency_command"], bool)
    assert isinstance(data.get("expires_at"), str)


def assert_diagnostic_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["odometer_km"], int) and data["odometer_km"] >= 0
    assert isinstance(data["engine_hours"], int) and data["engine_hours"] >= 0
    assert isinstance(data["dtc_codes"], list)
    assert isinstance(data["oil_life_pct"], int) and 0 <= data["oil_life_pct"] <= 100
    assert isinstance(data["health_score"], int) and 0 <= data["health_score"] <= 100
    assert data["status"] in {"GENERATED", "SERVICE_SCHEDULED"}


def assert_dealer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str)
    assert isinstance(data["service_capacity_per_day"], int)
    assert data["service_capacity_per_day"] >= 1
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


def assert_service_appointment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dealer_id"], str)
    assert isinstance(data["vehicle_id"], str)
    assert isinstance(data["diagnostic_report_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert data["status"] in {"REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED"}


def assert_data_consent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_id"], str)
    assert data["consent_type"] in {"DRIVING_DATA_COLLECTION", "INSURANCE_PROGRAM_SHARING"}
    assert data["status"] in {"GRANTED", "REVOKED", "SUPERSEDED"}
