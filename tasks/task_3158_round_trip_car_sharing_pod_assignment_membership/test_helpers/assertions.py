"""Entity assertions and domain invariant checkers.

Common-field checks (``id`` UUID shape, ISO 8601 timestamps, ``version`` type)
are delegated to the framework's generic helpers.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AccessMethod,
    AccessOutcome,
    ApplicationStatus,
    CleanlinessState,
    IncidentStatus,
    IncidentType,
    MemberKind,
    MembershipStatus,
    MembershipTier,
    ReservationStatus,
    ScreenResult,
    VehicleUseStatus,
)


def _assert_common(data: dict, *, created: bool = True):
    """Every entity in this API carries the full common-field set."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    if created:
        assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["kind"] in [k.value for k in MemberKind]
    assert data["application_status"] in [s.value for s in ApplicationStatus]
    assert data["screen_result"] in [s.value for s in ScreenResult]
    assert isinstance(data["strikes"], int) and data["strikes"] >= 0
    assert isinstance(data["referral_invites"], int) and data["referral_invites"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["wallet_hold_cents"], int) and data["wallet_hold_cents"] >= 0


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["type"] in ("UNIVERSITY", "BUSINESS")
    assert is_valid_uuid(data["primary_member_id"])
    assert isinstance(data["billing_email"], str) and "@" in data["billing_email"]


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["tier"] in [t.value for t in MembershipTier]
    assert data["status"] in [s.value for s in MembershipStatus]
    assert isinstance(data["primary_flag"], bool)
    assert isinstance(data["department_code"], str) and data["department_code"]
    assert data["status_before_freeze"] in (None, "ACTIVE", "SUSPENDED", "NONE")
    assert isinstance(data["membership_billing_cents"], int)
    assert isinstance(data["residual_released_cents"], int)


def assert_pod(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["site_type"] in ("NEIGHBORHOOD", "CAMPUS", "AIRPORT")
    assert isinstance(data["capacity"], int)
    assert isinstance(data["available_bays"], int)
    assert data["available_bays"] >= 0, "available_bays is never negative"
    assert isinstance(data["utilization_score"], (int, float))
    assert data["utilization_score"] >= 0
    assert isinstance(data["fuel_floor_pct"], int)


def assert_vehicle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pod_id"])
    assert isinstance(data["vin"], str) and data["vin"]
    assert data["use_status"] in [s.value for s in VehicleUseStatus]
    assert data["cleanliness_state"] in [s.value for s in CleanlinessState]
    assert isinstance(data["capacity_seats"], int)
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0
    assert isinstance(data["fuel_level_pct"], int) and 0 <= data["fuel_level_pct"] <= 100


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["pod_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert data["status"] in [s.value for s in ReservationStatus]
    assert isinstance(data["reserved_hours"], int) and data["reserved_hours"] >= 0
    assert isinstance(data["late_minutes"], int) and data["late_minutes"] >= 0
    assert data["status_before_overdue"] in (None, "CONFIRMED", "IN_USE", "RETURNED", "NONE")
    if data.get("charge_total_cents") is not None:
        assert isinstance(data["charge_total_cents"], int)
        assert data["charge_total_cents"] >= 0


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["incident_type"] in [t.value for t in IncidentType]
    assert data["status"] in [s.value for s in IncidentStatus]
    assert isinstance(data["damage_fee_charged"], bool)
    assert isinstance(data["fee_version"], int) and data["fee_version"] >= 0
    assert isinstance(data["severity_score"], int)
    assert isinstance(data["severity_fee_cents"], int)
    assert data["insurance_layer"] in (None, "NONE", "STANDARD", "PLUS", "PREMIUM")


def assert_maintenance_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["vehicle_id"])
    assert is_valid_uuid(data["pod_id"])
    assert data["status"] in ("SCHEDULED", "BLOCKED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["blocking"], bool)
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert isinstance(data["reason"], str) and data["reason"]
    assert isinstance(data["released_cents"], int) and data["released_cents"] >= 0


def assert_access_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["method"] in [m.value for m in AccessMethod]
    assert data["outcome"] in [o.value for o in AccessOutcome]
    assert isinstance(data["auto_release_used"], bool)


def assert_fuel_transaction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["gallons_hundredths"], int) and data["gallons_hundredths"] >= 0
    assert data["status"] in ("POSTED", "REVERSED")


def assert_community_signal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["pod_id"])
    assert data["signal_type"] in ("CAMPUS", "CLEANLINESS", "AVAILABILITY")
    assert isinstance(data["message"], str) and data["message"]


def assert_driving_record_report(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["report_status"] in ("SUBMITTED", "RECORDED")
    assert data["report_decision"] in [s.value for s in ScreenResult]
    assert isinstance(data["license_state"], str)
    assert isinstance(data["license_years_held"], int)


def assert_pod_shift_bundle(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["source_pod_id"])
    assert is_valid_uuid(data["dest_pod_id"])
    assert isinstance(data["monthly_pods"], list)
    assert isinstance(data["bundle_fee_cents"], int) and data["bundle_fee_cents"] >= 0
    assert data["status"] == "APPLIED", "APPLIED is the only value the bundle status can take"


def assert_tier_restore_entitlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["membership_id"])
    assert data["tier"] in ("STANDARD", "PLUS", "PREMIUM"), "FROZEN is not an entitlement value"
    assert data["restore_status"] in ("PENDING", "CONSUMED")


# ─── Domain invariants ────────────────────────────────

def assert_wallet_conserved(member: dict):
    """The wallet is one conserved quantity across two fields; neither may go negative."""
    assert member["wallet_credit_cents"] >= 0, "wallet_credit_cents is never negative"
    assert member["wallet_hold_cents"] >= 0, "wallet_hold_cents is never negative"


def assert_pod_bay_invariant(pod: dict):
    """available_bays is capacity minus the parked count, floored at zero."""
    assert pod["available_bays"] >= 0
    assert pod["available_bays"] <= pod["capacity"], (
        "available_bays can never exceed capacity"
    )


def assert_boundary_triplet(observed, lower, at_boundary, upper):
    """Boundary-precision guard: the value must sit strictly inside the expected band."""
    assert lower <= observed <= upper, (
        f"Observed {observed} outside expected band [{lower}, {upper}] around {at_boundary}"
    )