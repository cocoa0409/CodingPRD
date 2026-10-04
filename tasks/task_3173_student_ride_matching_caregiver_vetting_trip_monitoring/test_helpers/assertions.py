"""Entity assertions and domain invariant checkers.

Every entity assertion validates the system-managed field quartet declared in
PRD §2.7 together with the entity's own declared fields.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
)


def assert_common_fields(data: dict):
    """Every addressable resource carries id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_district(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("billing_email"), str) and data["billing_email"]
    assert isinstance(data.get("contract_rate_per_ride_cents"), int)
    assert isinstance(data.get("contract_rate_per_mile_cents"), int)
    assert isinstance(data.get("outstanding_balance_cents"), int)
    assert isinstance(data.get("credit_balance_cents"), int)
    assert data["account_status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data.get("trips_scheduled_total"), int)
    assert isinstance(data.get("no_school_dates"), list)
    assert isinstance(data.get("support_center_alert_enabled"), bool)


def assert_rider(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data["program_type"] in [
        "FOSTER_CARE", "HOMELESS_MCKINNEY_VENTO", "SPECIAL_EDUCATION", "GENERAL",
    ]
    assert isinstance(data.get("spi_level"), int) and 1 <= data["spi_level"] <= 5
    assert isinstance(data.get("authorized_adults"), list)
    assert isinstance(data.get("notify_on_pickup"), bool)
    assert isinstance(data.get("notify_on_dropoff"), bool)
    assert isinstance(data.get("active_ride_request_count"), int)
    assert data["status"] in ["ACTIVE", "INACTIVE"]


def assert_driver(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert isinstance(data.get("caregiver_experience_months"), int)
    assert data["vehicle_class"] in ["SEDAN", "SUV", "WHEELCHAIR_VAN"]
    assert isinstance(data.get("seat_capacity"), int)
    assert data["child_seat_type"] in ["NONE", "BOOSTER", "HARNESS", "INTEGRATED"]
    assert isinstance(data.get("approved_seat_count"), int)
    assert isinstance(data.get("incident_strike_count"), int)
    assert data["status"] in [
        "PENDING", "BACKGROUND_CHECK", "INSPECTION", "ACTIVE", "SUSPENDED",
        "INACTIVE",
    ]


def assert_background_check(data: dict):
    assert_common_fields(data)
    assert data["check_type"] in [
        "FINGERPRINT_FBI", "FINGERPRINT_STATE", "COUNTY_COURT",
        "SEX_OFFENDER_REGISTRY",
    ]
    assert data["result"] in ["PENDING", "CLEARED", "FAILED"]
    assert isinstance(data.get("expires_on"), str)


def assert_inspection(data: dict):
    assert_common_fields(data)
    assert data["vehicle_class"] in ["SEDAN", "SUV", "WHEELCHAIR_VAN"]
    assert isinstance(data.get("seat_count"), int)
    assert data["result"] in ["PENDING", "PASSED", "FAILED"]
    assert isinstance(data.get("seat_credit"), int)


def assert_contract(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED"]
    assert data["billing_period"] in ["WEEKLY", "SEMI_MONTHLY", "MONTHLY"]
    assert isinstance(data.get("per_ride_rate_cents"), int)
    assert isinstance(data.get("per_mile_rate_cents"), int)


def assert_ride_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "SCHEDULED",
        "SERIES_SUSPENDED", "REJECTED", "CANCELLED",
    ]
    assert isinstance(data.get("revision_count"), int)
    assert isinstance(data.get("recurring_series_active"), bool)
    assert data["trip_type"] in ["AM_SCHOOL", "PM_SCHOOL", "MIDDAY", "ACTIVITY"]


def assert_trip(data: dict):
    assert_common_fields(data)
    assert data["trip_state"] in [
        "SCHEDULED", "DRIVER_EN_ROUTE", "AWAITING_STUDENT", "STUDENT_ONBOARD",
        "IN_TRANSIT", "COMPLETED", "CANCELLED",
    ]
    assert data["safety_state"] in ["NORMAL", "DISCREPANCY", "LOCKED"]
    assert isinstance(data.get("billable_ride_units"), int)
    assert data["billable_ride_units"] in [0, 1, 2]


def assert_handoff(data: dict):
    assert_common_fields(data)
    assert data["leg"] in ["PICKUP", "DROPOFF"]
    assert data["expected_party"] in [
        "SCHOOL_STAFF", "AUTHORIZED_ADULT", "PLACEMENT_WORKER",
    ]
    assert data["verification_method"] in [
        "PHOTO_ID", "PIN", "PHYSICAL_SIGNATURE",
    ]
    assert isinstance(data.get("authorized"), bool)
    assert data["result"] in ["PASSED", "FAILED"]


def assert_incident(data: dict):
    assert_common_fields(data)
    assert data["category"] in [
        "NO_SHOW_UNVERIFIED", "DRIVER_MISCONDUCT", "VEHICLE_UNSAFE",
        "HANDOFF_DISPUTE", "STUDENT_DISTRESS",
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in ["REPORTED", "UNDER_REVIEW", "RESOLVED", "VOIDED"]
    assert isinstance(data.get("student_impact_score"), int)
    assert 0 <= data["student_impact_score"] <= 100


def assert_alert(data: dict):
    assert_common_fields(data)
    assert data["alert_type"] in [
        "TRIP_DELAY", "GEOFENCE_BREACH", "HANDOFF_DISPUTE", "STUDENT_ABSENT",
    ]
    assert data["severity"] in ["LOW", "MEDIUM", "HIGH"]
    assert data["status"] in ["OPEN", "RESOLVED"]
    assert isinstance(data.get("notify_caregiver"), bool)
    assert isinstance(data.get("notify_school"), bool)
    assert isinstance(data.get("notify_support_center"), bool)
    assert isinstance(data.get("released_by_resolution"), bool)


def assert_geofence(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("label"), str)
    assert isinstance(data.get("center_lat"), (int, float))
    assert isinstance(data.get("center_lon"), (int, float))
    assert isinstance(data.get("radius_miles"), (int, float))


def assert_geofence_check(data: dict):
    assert_common_fields(data)
    assert isinstance(data.get("inside"), bool)
    assert isinstance(data.get("observed_lat"), (int, float))
    assert isinstance(data.get("observed_lon"), (int, float))


def assert_statement(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "ISSUED", "PAID", "VOIDED"]
    assert isinstance(data.get("total_amount_cents"), int)
    assert isinstance(data.get("applied_credit_cents"), int)
    assert isinstance(data.get("total_ride_units"), int)
    assert_cost_precision(data["total_amount_cents"])


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_driver_qualification_invariants(data: dict):
    """Invariants that hold on any driver read (PRD §2.4 / §3.3)."""
    assert data["approved_seat_count"] >= 0
    assert data["approved_seat_count"] <= 10, "never reported above the ceiling of ten seats"
    assert data["incident_strike_count"] >= 0
    if data["status"] in ("PENDING", "INACTIVE"):
        assert data["compliance_expires_at"] is None, \
            "a PENDING or INACTIVE driver reports no compliance expiry"


def assert_district_invariants(data: dict):
    """District accounting invariants (PRD §3.1 / §3.10)."""
    assert data["outstanding_balance_cents"] >= 0
    assert data["credit_balance_cents"] >= 0
    assert data["trips_scheduled_total"] >= 0


def assert_trip_completed_invariants(data: dict):
    """Shape of a completed trip (PRD §3.8)."""
    assert data["trip_state"] == "COMPLETED"
    assert data["completed_at"] is not None
    assert data["billable_ride_units"] in (1, 2)


__all__ = [
    "assert_common_fields", "assert_district", "assert_rider", "assert_driver",
    "assert_background_check", "assert_inspection", "assert_contract",
    "assert_ride_request", "assert_trip", "assert_handoff", "assert_incident",
    "assert_alert", "assert_geofence", "assert_geofence_check",
    "assert_statement", "assert_driver_qualification_invariants",
    "assert_district_invariants", "assert_trip_completed_invariants",
    "assert_version_incremented", "assert_timestamp_format",
]