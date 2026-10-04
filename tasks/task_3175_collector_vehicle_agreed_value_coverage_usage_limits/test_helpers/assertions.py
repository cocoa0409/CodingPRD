"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, what: str):
    assert is_valid_uuid(data.get("id", "")), f"{what}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{what}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{what}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{what}.version must be an int"


def assert_member(data: dict):
    _assert_common(data, "Member")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["has_daily_driver"], bool)
    assert data["driving_record_status"] in (
        "CLEAN",
        "MINOR_VIOLATIONS",
        "MAJOR_VIOLATIONS",
    )
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")


def assert_vehicle(data: dict):
    _assert_common(data, "Vehicle")
    assert isinstance(data["vin"], str) and data["vin"]
    assert isinstance(data["year"], int)
    assert data["vehicle_class"] in (
        "ANTIQUE",
        "CLASSIC",
        "MODERN_COLLECTIBLE",
        "EXOTIC",
    )
    assert data["condition_grade"] in ("EXCELLENT", "GOOD", "FAIR", "PROJECT")
    assert data["storage_type"] in ("ENCLOSED_GARAGE", "CARPORT", "OUTDOOR")
    assert data["primary_use"] in ("SHOW", "PLEASURE", "RESTORATION")
    assert data["eligibility_status"] in ("PENDING", "ELIGIBLE", "INELIGIBLE")
    assert data["documentation_status"] in ("INCOMPLETE", "COMPLETE")
    assert isinstance(data["accepted_photo_count"], int)
    assert data["status"] in (
        "REGISTERED",
        "INSURED",
        "UNDER_RESTORATION",
        "RETIRED",
    )


def assert_photo(data: dict):
    _assert_common(data, "VehiclePhoto")
    assert data["photo_type"] in (
        "FRONT",
        "REAR",
        "DRIVER_SIDE",
        "PASSENGER_SIDE",
        "INTERIOR",
        "ENGINE",
        "ODOMETER",
        "VIN_PLATE",
    )
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "REJECTED")


def assert_valuation_guide(data: dict):
    _assert_common(data, "ValuationGuide")
    assert isinstance(data["edition"], str) and data["edition"]
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")


def assert_appraisal(data: dict):
    _assert_common(data, "Appraisal")
    assert isinstance(data["appraised_value_cents"], int)
    assert data["status"] in ("SUBMITTED", "CERTIFIED", "REJECTED")


def assert_valuation(data: dict):
    _assert_common(data, "Valuation")
    assert data["method"] in ("GUIDE_TOOL", "CERTIFIED_APPRAISAL", "AUCTION_COMPOSITE")
    assert data["status"] in (
        "DRAFT",
        "PROPOSED",
        "APPROVED",
        "REJECTED",
        "SUPERSEDED",
        "STALE",
    )


def assert_policy(data: dict):
    _assert_common(data, "Policy")
    assert data["usage_tier"] in ("LIMITED", "REGULAR", "EXTENDED")
    assert isinstance(data["annual_mileage_allowance"], int)
    assert isinstance(data["agreed_value_cents"], int)
    assert isinstance(data["endorsement_limit_cents"], int)
    assert isinstance(data["coverage_limit_cents"], int)
    assert isinstance(data["premium_cents"], int)
    assert isinstance(data["billable_miles_used"], int)
    assert isinstance(data["overage_charge_cents"], int)
    assert isinstance(data["remaining_allowance_miles"], int)
    assert data["status"] in (
        "QUOTED",
        "PENDING_DOCUMENTS",
        "ACTIVE",
        "UNDER_REVIEW",
        "SUSPENDED",
        "LAPSED",
        "CANCELLED",
    )


def assert_driver(data: dict):
    _assert_common(data, "Driver")
    assert isinstance(data["years_licensed"], int)
    assert isinstance(data["violations_last_3y"], int)
    assert data["status"] in ("LISTED", "REMOVED")


def assert_usage_event(data: dict):
    _assert_common(data, "UsageEvent")
    assert isinstance(data["reported_miles"], int)
    assert data["event_kind"] in ("ORDINARY", "CLUB_EVENT", "PARADE", "EXHIBITION")
    assert isinstance(data["billable_miles"], int)
    assert isinstance(data["overage_charge_cents"], int)
    assert data["status"] in ("RECORDED", "REVERSED")


def assert_repair_shop(data: dict):
    _assert_common(data, "RepairShop")
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["status"] in ("PROVISIONAL", "CERTIFIED", "SUSPENDED")


def assert_claim(data: dict):
    _assert_common(data, "Claim")
    assert data["loss_type"] in ("COLLISION", "THEFT", "FIRE", "VANDALISM", "WEATHER")
    assert data["settlement_variant"] in ("NONE", "REPAIR", "TOTAL_LOSS")
    assert data["status"] in (
        "OPEN",
        "UNDER_INVESTIGATION",
        "REPAIR_AUTHORIZED",
        "TOTAL_LOSS_DECLARED",
        "PAID",
        "CLOSED",
    )


def assert_restoration_project(data: dict):
    _assert_common(data, "RestorationProject")
    assert data["stage"] in (
        "DISASSEMBLY",
        "BODYWORK",
        "MECHANICAL",
        "FINISH",
        "COMPLETE",
    )
    assert isinstance(data["receipts_total_cents"], int)
    assert isinstance(data["endorsement_limit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "COMPLETED")


def assert_club_membership(data: dict):
    _assert_common(data, "ClubMembership")
    assert data["tier"] in ("BASIC", "ENTHUSIAST", "CONCOURS")
    assert isinstance(data["roadside_calls_limit"], int)
    assert isinstance(data["roadside_calls_used"], int)
    assert data["status"] in ("ACTIVE", "LAPSED")


def assert_club_event(data: dict):
    _assert_common(data, "ClubEvent")
    assert isinstance(data["capacity"], int)
    assert isinstance(data["registered_count"], int)
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_registration(data: dict):
    _assert_common(data, "EventRegistration")
    assert data["status"] in ("REGISTERED", "CANCELLED")


def assert_roadside_event(data: dict):
    _assert_common(data, "RoadsideEvent")
    assert data["service_type"] in ("FLATBED_TOW", "BATTERY", "FUEL", "LOCKOUT")
    assert data["status"] in ("DISPATCHED", "COMPLETED", "CANCELLED")


def assert_mileage_ledger_invariant(policy: dict):
    """Compensating invariant: billable + remaining == allowance at all times."""
    assert (
        policy["billable_miles_used"] + policy["remaining_allowance_miles"]
        == policy["annual_mileage_allowance"]
    ), (
        f"ledger invariant broken: {policy['billable_miles_used']} + "
        f"{policy['remaining_allowance_miles']} != {policy['annual_mileage_allowance']}"
    )


def assert_roadside_invariant(membership: dict):
    """roadside_calls_used never exceeds roadside_calls_limit."""
    assert membership["roadside_calls_used"] <= membership["roadside_calls_limit"]
    assert membership["roadside_calls_used"] >= 0
