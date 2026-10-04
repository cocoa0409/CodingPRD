"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def assert_common_fields(data: dict):
    """Every resource carries id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating an omitted fractional part."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, message: str = ""):
    """Compare two instants by value, ignoring fractional-digit formatting."""
    assert actual, f"expected an instant, got {actual!r}. {message}"
    assert parse_instant(actual) == parse_instant(expected), (
        f"expected instant {expected}, got {actual}. {message}"
    )


def assert_money_field(data: dict, field: str):
    value = data.get(field)
    assert isinstance(value, int) and not isinstance(value, bool), (
        f"{field} must be integer cents, got {value!r}"
    )


def assert_region(data: dict):
    assert_common_fields(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["state_codes"], list)
    assert isinstance(data["coordinator_user_id"], str)
    assert isinstance(data["volunteer_pool_target"], int) and data["volunteer_pool_target"] >= 1
    assert isinstance(data["authorized_agency_codes"], list)
    assert isinstance(data["available_volunteer_count"], int)
    assert isinstance(data["deployed_volunteer_count"], int)
    assert isinstance(data["blood_continuity_index"], (int, float))
    assert data["blood_continuity_status"] in ("CRITICAL", "STRAINED", "NORMAL")


def assert_operation(data: dict):
    assert_common_fields(data)
    assert data["phase"] in ("MOBILIZATION", "ACTIVE", "DEMOBILIZATION", "CLOSED")
    assert isinstance(data["open_shelter_count"], int)
    assert_money_field(data, "restricted_fund_balance_cents")


def assert_shelter_site(data: dict):
    assert_common_fields(data)
    assert data["agreement_status"] in (
        "PENDING_INSPECTION", "APPROVED", "SUSPENDED", "EXPIRED")
    assert isinstance(data["capacity_verified_beds"], int)
    assert isinstance(data["accessibility_verified"], bool)
    assert isinstance(data["functional_needs_verified"], bool)


def assert_shelter_operation(data: dict):
    assert_common_fields(data)
    assert data["posture"] in (
        "PENDING_OPEN", "OPEN", "RESTRICTED", "CONSOLIDATING", "CLOSED")
    assert isinstance(data["occupied_beds"], int)
    assert isinstance(data["registered_client_count"], int)
    assert isinstance(data["staffed_volunteer_count"], int)
    assert isinstance(data["staffing_sufficiency"], (int, float))
    assert 0.0 <= float(data["staffing_sufficiency"]) <= 1.0


def assert_shelter_operation_invariants(data: dict):
    assert data["occupied_beds"] >= 0
    assert data["occupied_beds"] <= data["registered_client_count"]
    assert data["staffing_sufficiency"] <= 1.0


def assert_volunteer(data: dict):
    assert_common_fields(data)
    assert data["credential_status"] in ("PENDING", "ACTIVE", "EXPIRED")
    assert data["deployment_availability"] in (
        "AVAILABLE", "DEPLOYED", "RESTING", "UNAVAILABLE")
    assert isinstance(data["qualified_role_codes"], list)
    assert isinstance(data["rotation_days_used_ytd"], int)
    assert data["rotation_days_used_ytd"] >= 0


def assert_deployment(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "IN_TRANSIT", "ARRIVED", "ON_SHIFT",
        "ROTATION_ENDED", "RECALLED", "CANCELLED")
    assert data["travel_mode"] in ("AIR", "GROUND", "SELF")
    assert isinstance(data["rotation_days"], int)
    assert_money_field(data, "travel_cost_cents")


def assert_shift(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["functional_area"] in (
        "REGISTRATION", "DORMITORY", "FEEDING", "HEALTH", "REUNIFICATION", "SECURITY")


def assert_client(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1


def assert_registration(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("REGISTERED", "CHECKED_OUT", "TRANSFERRED", "REUNIFIED")
    assert data["reunification_status"] in ("NOT_REQUESTED", "PENDING", "VERIFIED")


def assert_client_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "INTAKE", "ELIGIBILITY_REVIEW", "RECOVERY_PLANNING", "REFERRED",
        "MONITORING", "CLOSED", "REOPENED")
    assert data["eligibility_status"] in ("PENDING", "VERIFIED", "INELIGIBLE", "EXPIRED")
    assert isinstance(data["recovery_plan_revision"], int)
    assert_money_field(data, "entitlement_cents")


def assert_referral(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED", "DECLINED", "COMPLETED", "CANCELLED")
    assert data["assistance_type"] in (
        "HOUSING", "FOOD", "MEDICAL", "TRANSPORTATION", "UTILITY", "FUNERAL", "OCCUPATIONAL")
    assert isinstance(data["estimated_value_cents"], int)


def assert_assistance_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SUBMITTED", "ELIGIBILITY_VERIFIED", "APPROVED", "DENIED",
        "CARD_ISSUED", "DISBURSED", "REVERSED")
    assert data["card_status"] in ("NOT_ISSUED", "ISSUED", "ACTIVE", "REDEEMED", "VOIDED")
    assert_money_field(data, "duplication_offset_cents")
    assert_money_field(data, "approved_amount_cents")


def assert_fund_pool(data: dict):
    assert_common_fields(data)
    assert data["restriction_type"] in (
        "UNRESTRICTED", "DONOR_RESTRICTED_DISASTER",
        "DONOR_RESTRICTED_BLOOD", "DONOR_RESTRICTED_LOCAL")
    assert_money_field(data, "total_received_cents")
    assert_money_field(data, "committed_cents")
    assert_money_field(data, "disbursed_cents")
    assert_money_field(data, "remaining_cents")


def assert_fund_pool_invariants(data: dict):
    assert data["remaining_cents"] >= 0, "remaining_cents must never go negative"
    assert data["committed_cents"] >= 0
    assert data["disbursed_cents"] >= 0
    assert (
        data["remaining_cents"] + data["committed_cents"] + data["disbursed_cents"]
        == data["total_received_cents"]
    ), "remaining + committed + disbursed must equal total_received_cents"


def assert_cost_ledger_entry(data: dict):
    assert_common_fields(data)
    assert data["cost_category"] in (
        "SHELTER_OPERATIONS", "FEEDING", "VOLUNTEER_TRAVEL", "FINANCIAL_ASSISTANCE",
        "HEALTH_SERVICES", "BLOOD_COLLECTION", "LOGISTICS")
    assert data["entry_type"] in ("CHARGE", "REVERSAL")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1


def assert_blood_drive(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert isinstance(data["target_units"], int) and data["target_units"] >= 1
    assert isinstance(data["collected_units"], int)
    assert isinstance(data["usable_units"], int)
    assert data["usable_units"] <= data["collected_units"]


def assert_blood_continuity_status(index: float, status: str):
    """The status thresholds applied in order: <0.50 CRITICAL, <0.80 STRAINED, else NORMAL."""
    if index < 0.50:
        assert status == "CRITICAL", f"index {index} should be CRITICAL, got {status}"
    elif index < 0.80:
        assert status == "STRAINED", f"index {index} should be STRAINED, got {status}"
    else:
        assert status == "NORMAL", f"index {index} should be NORMAL, got {status}"
