"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version starts at 1"


def assert_battery_platform(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUNSETTING", "RETIRED")
    assert isinstance(data["current_generation"], int) and data["current_generation"] >= 0
    assert data["interface_key"] in ("INTERFACE_A", "INTERFACE_B")
    assert data["chemistry_family"] in ("LION_NMC", "LFP")


def assert_battery_pack(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("platform_id", ""))
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["certification_status"] in ("DESIGN", "SUBMITTED", "CERTIFIED", "REJECTED", "RECALLED")
    assert isinstance(data["safety_hold"], bool)
    assert isinstance(data["pack_generation"], int) and data["pack_generation"] >= 1
    assert data["cell_format"] in ("C18650", "C21700", "TABLESS")
    assert data["warranty_days"] > 0 and data["warranty_days"] % 30 == 0
    assert 0 <= data["free_replacement_days"] <= data["warranty_days"]


def assert_charger(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("platform_id", ""))
    assert isinstance(data["charger_generation"], int) and data["charger_generation"] >= 1
    assert data["max_charge_rate_w"] > 0


def assert_tool_model(data: dict):
    _assert_common(data)
    assert data["stage"] in (
        "CONCEPT", "FIELD_RESEARCH", "PROTOTYPE",
        "ENGINEERING_VALIDATION", "LAUNCHED", "DISCONTINUED",
    )
    assert data["trade"] in ("PLUMBING", "ELECTRICAL", "HVAC", "CARPENTRY", "MASONRY", "AUTOMOTIVE")
    assert data["tier"] in ("CONSUMER", "PROFESSIONAL", "TRADE_SPECIALIST")
    assert isinstance(data["adopted_field_research_count"], int)
    assert isinstance(data["adopted_jobsite_observation_count"], int)
    assert isinstance(data["regulatory_compatible_pack_count"], int)
    assert data["min_pack_generation"] <= data["max_pack_generation"]


def assert_research_insight(data: dict):
    _assert_common(data)
    assert data["kind"] in ("FIELD_RESEARCH", "JOBSITE_OBSERVATION")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("SUBMITTED", "ADOPTED", "REJECTED")


def assert_service_center(data: dict):
    _assert_common(data)
    assert isinstance(data["capabilities"], list) and len(data["capabilities"]) >= 1
    assert set(data["capabilities"]) <= {"TOOL_REPAIR", "BATTERY_SERVICE"}
    assert isinstance(data["daily_capacity"], int) and data["daily_capacity"] >= 1


def assert_asset_account(data: dict):
    _assert_common(data)
    assert data["tier"] in ("STANDARD", "PROFESSIONAL", "FLEET")
    assert data["asset_limit"] == {"STANDARD": 10, "PROFESSIONAL": 100, "FLEET": 1000}[data["tier"]]
    assert isinstance(data["active_asset_count"], int) and data["active_asset_count"] >= 0


def assert_tracked_asset(data: dict):
    _assert_common(data)
    assert data["subject_type"] in ("TOOL", "BATTERY")
    assert data["status"] in ("ACTIVE", "REPORTED_LOST", "DECOMMISSIONED")
    assert isinstance(data["is_replacement_unit"], bool)
    assert isinstance(data["anti_theft_lock_enabled"], bool)
    assert is_iso8601_timestamp(data.get("first_paired_at", ""))
    assert is_iso8601_timestamp(data.get("manufactured_at", ""))


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["claim_type"] in ("TOOL_REPAIR", "BATTERY_REPLACEMENT")
    assert data["adjudication_status"] in ("SUBMITTED", "APPROVED", "REJECTED")
    assert data["fulfillment_status"] in ("NONE", "AWAITING_UNIT", "COMPLETED", "CANCELLED")
    assert is_valid_uuid(data.get("service_center_id", ""))


def assert_channel_partner(data: dict):
    _assert_common(data)
    assert data["channel_type"] in ("INDUSTRIAL_DISTRIBUTOR", "HOME_CENTER")
    assert isinstance(data["has_suspended_listings"], bool)
    assert isinstance(data["active_allocation_total"], int) and data["active_allocation_total"] >= 0


def assert_distribution_listing(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "ACTIVE", "SUSPENDED", "ENDED")
    assert isinstance(data["requires_relist_ack"], bool)
    assert isinstance(data["channel_partner_version"], int)
    refs = [data.get("tool_model_id"), data.get("battery_pack_id"), data.get("charger_id")]
    assert sum(1 for r in refs if r) == 1, "exactly one product reference"


def assert_counterfeit_case(data: dict):
    _assert_common(data)
    assert data["status"] in ("REPORTED", "CONFIRMED", "CLEARED")
    assert data["detection_method"] in ("SERIAL_MISMATCH", "CHARGE_ANOMALY", "PHYSICAL_INSPECTION")


def assert_safety_bulletin(data: dict):
    _assert_common(data)
    assert data["severity"] in ("ADVISORY", "URGENT", "RECALL")
    assert data["status"] in ("ISSUED", "SUPERSEDED")
