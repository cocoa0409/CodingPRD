"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data, entity_name):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_name}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_name}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_name}.version must be an int"


def assert_club(data: dict):
    _assert_common(data, "Club")
    assert isinstance(data["club_code"], str) and data["club_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["territory_state_codes"], list)
    assert isinstance(data["default_arrival_target_minutes"], int) and data["default_arrival_target_minutes"] >= 1
    assert data["billing_policy"] in ("SCHEDULE", "ACTUAL")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_tier(data: dict):
    _assert_common(data, "MembershipTier")
    assert data["code"] in ("CLASSIC", "PLUS", "PREMIER")
    for field in (
        "annual_dues_cents", "included_tow_miles", "annual_call_cap",
        "lockout_benefit_cents", "household_member_price_cents",
        "overage_rate_cents_per_mile", "upgrade_waiting_days", "rank",
    ):
        assert isinstance(data[field], int), f"MembershipTier.{field} must be an int"
    assert isinstance(data["battery_service_included"], bool)


def assert_membership(data: dict):
    _assert_common(data, "Membership")
    assert is_valid_uuid(data.get("home_club_id", ""))
    assert isinstance(data["primary_member_name"], str) and data["primary_member_name"]
    assert isinstance(data["primary_member_email"], str) and data["primary_member_email"]
    assert data["tier_code"] in ("CLASSIC", "PLUS", "PREMIER")
    assert data["status"] in ("ACTIVE", "GRACE", "LAPSED", "REINSTATED", "CANCELLED")
    assert is_iso8601_timestamp(data["enrolled_at"])
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert isinstance(data["reinstatement_count"], int) and data["reinstatement_count"] >= 0
    assert isinstance(data["calls_used_current_term"], int) and data["calls_used_current_term"] >= 0
    assert isinstance(data["account_credit_cents"], int)


def assert_household_member(data: dict):
    _assert_common(data, "HouseholdMember")
    assert is_valid_uuid(data.get("membership_id", ""))
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["relationship"] in ("SPOUSE", "CHILD", "PARENT", "OTHER")
    assert isinstance(data["is_primary"], bool)
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]
    assert data["status"] in ("ACTIVE", "REMOVED")


def assert_membership_event(data: dict):
    """MembershipEvent is immutable: it carries only id + created_at of the common
    fields — updated_at and version are absent (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "MembershipEvent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "MembershipEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "MembershipEvent must not carry updated_at"
    assert "version" not in data, "MembershipEvent must not carry version"
    assert data["event_type"] in (
        "ENROLLMENT", "UPGRADE", "DOWNGRADE", "RENEWAL", "LAPSE",
        "REINSTATEMENT", "CANCELLATION", "WAITING_PERIOD_SATISFIED",
    )
    assert is_valid_uuid(data.get("membership_id", ""))


def assert_provider(data: dict):
    _assert_common(data, "ServiceProvider")
    assert is_valid_uuid(data.get("servicing_club_id", ""))
    assert data["provider_kind"] in ("OWNED", "CONTRACTED")
    assert isinstance(data["capabilities"], list)
    assert isinstance(data["home_base_state_code"], str)
    assert 0.5 <= data["sla_multiplier"] <= 3.0
    assert 0 <= data["shift_start_minute"] <= 1439
    assert 0 <= data["shift_end_minute"] <= 1439
    assert isinstance(data["max_concurrent_dispatches"], int) and data["max_concurrent_dispatches"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_truck_part_stock(data: dict):
    _assert_common(data, "TruckPartStock")
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["part_sku"], str) and data["part_sku"]
    assert data["part_kind"] in ("BATTERY", "TIRE", "FUEL_CAN", "LOCKSMITH_KIT")
    assert isinstance(data["quantity_on_hand"], int) and data["quantity_on_hand"] >= 0


def assert_service_call(data: dict):
    _assert_common(data, "ServiceCall")
    assert is_valid_uuid(data.get("membership_id", ""))
    assert is_valid_uuid(data.get("requesting_member_id", ""))
    assert data["service_type"] in ("TOW", "BATTERY", "LOCKOUT", "TIRE", "FUEL", "WINCH")
    assert is_valid_uuid(data.get("servicing_club_id", ""))
    assert isinstance(data["is_pre_existing_need"], bool)
    assert data["benefit_tier_code"] in ("CLASSIC", "PLUS", "PREMIER")
    assert isinstance(data["benefit_eligible"], bool)
    assert data["status"] in ("REQUESTED", "DISPATCHED", "EN_ROUTE", "ON_SCENE", "COMPLETED", "CANCELLED", "EXPIRED")
    assert data["cancel_reason"] in ("NONE", "MEMBER_REQUEST", "NO_PROVIDER", "DUPLICATE")


def assert_dispatch(data: dict):
    _assert_common(data, "Dispatch")
    assert is_valid_uuid(data.get("service_call_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert isinstance(data["sequence_number"], int) and data["sequence_number"] >= 1
    assert is_iso8601_timestamp(data["assigned_at"])
    assert is_iso8601_timestamp(data["promised_arrive_by"])
    assert isinstance(data["parts_charge_cents"], int)
    assert isinstance(data["mileage_charge_cents"], int)
    assert isinstance(data["total_member_charge_cents"], int)
    assert data["status"] in ("ASSIGNED", "ACCEPTED", "EN_ROUTE", "ARRIVED", "COMPLETED", "FAILED", "CANCELLED")
    assert data["failure_reason"] in ("NONE", "PROVIDER_DECLINED", "NO_PARTS", "MEMBER_NO_SHOW")


def assert_settlement_period(data: dict):
    _assert_common(data, "SettlementPeriod")
    assert is_valid_uuid(data.get("servicing_club_id", ""))
    assert data["status"] in ("OPEN", "CLOSED", "ASSESSED")
    assert isinstance(data["total_foreign_call_count"], int) and data["total_foreign_call_count"] >= 0
    assert isinstance(data["total_gross_cents"], int) and data["total_gross_cents"] >= 0


def assert_settlement_line(data: dict):
    _assert_common(data, "SettlementLine")
    assert is_valid_uuid(data.get("service_call_id", ""))
    assert is_valid_uuid(data.get("home_club_id", ""))
    assert is_valid_uuid(data.get("servicing_club_id", ""))
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["excluded"], bool)
    assert data["status"] in ("PENDING", "SWEPT", "ASSESSED", "REVERSED")


def assert_ancillary_product(data: dict):
    _assert_common(data, "AncillaryProduct")
    assert data["product_type"] in ("TRAVEL_AGENCY", "INSURANCE_AGENCY", "IDENTITY_PROTECTION")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["min_tier_code"] in ("CLASSIC", "PLUS", "PREMIER")
    assert 0 <= data["commission_bps"] <= 5000
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_ancillary_sale(data: dict):
    _assert_common(data, "AncillarySale")
    assert is_valid_uuid(data.get("membership_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["sold_by_agent_id"], str) and data["sold_by_agent_id"]
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert data["status"] in ("ACTIVE", "REFUNDED")
