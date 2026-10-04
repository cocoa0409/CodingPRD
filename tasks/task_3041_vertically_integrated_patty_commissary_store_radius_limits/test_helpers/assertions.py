"""Entity assertions built on the PRD's own contracts.

Each ``assert_*`` checks only what the PRD makes observable: field presence and
type for inputs the caller supplied, the PRD-guaranteed common fields
(``id``, ``created_at``, ``updated_at``, ``version`` from section 2.4), and
initial or post-transition states the PRD states in prose.  Computed fields
are asserted only where the PRD commits to their presence.
"""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, where: str):
    """PRD section 2.4: id is a UUID; created_at/updated_at ISO 8601; version
    an integer that increments by one per mutation."""
    assert is_valid_uuid(data.get("id", "")), f"{where}: id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{where}: created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{where}: updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), \
        f"{where}: version must be an integer, got {data.get('version')!r}"


def assert_supplier(data: dict):
    _assert_common(data, "BeefSupplier")
    assert isinstance(data["supplier_code"], str) and data["supplier_code"]
    assert isinstance(data["spec_profile"], dict)
    for key in ("lean_point_pct", "max_fat_pct", "max_bacterial_count_cfu_g",
                "chilled_never_frozen"):
        assert key in data["spec_profile"], f"spec_profile missing {key}"
    assert isinstance(data["audit_frequency_days"], int)
    assert data["status"] in ("PROBATION", "APPROVED", "SUSPENDED", "RETIRED")


def assert_new_supplier(data: dict):
    """PRD section 3.1: a new supplier starts PROBATION with
    days_since_last_passed_audit 0 and version 1."""
    assert_supplier(data)
    assert data["status"] == "PROBATION", f"expected PROBATION, got {data['status']}"
    assert data["days_since_last_passed_audit"] == 0
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def assert_audit(data: dict):
    _assert_common(data, "Audit")
    assert isinstance(data["supplier_id"], str)
    assert data["status"] in ("SCHEDULED", "RECORDED", "CANCELLED")


def assert_commissary(data: dict):
    _assert_common(data, "Commissary")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["supplier_id"], str)
    assert data["status"] in ("PLANNING", "BUILDING", "OPERATIONAL", "DECOMMISSIONED")
    assert isinstance(data["raw_beef_lbs_on_hand"], (int, float))
    assert isinstance(data["regional_entry_open"], bool)


def assert_truck(data: dict):
    _assert_common(data, "Truck")
    assert isinstance(data["plate"], str) and data["plate"]
    assert data["route_type"] in ("PRIMARY", "RESERVE")
    assert isinstance(data["cooler_capacity_cases"], int)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_route(data: dict):
    _assert_common(data, "DeliveryRoute")
    assert isinstance(data["commissary_id"], str)
    assert isinstance(data["truck_id"], str)
    assert isinstance(data["store_ids"], list)
    assert data["status"] in ("DRAFT", "FINALIZED", "COMPLETED", "CANCELLED")


def assert_menu_item(data: dict):
    _assert_common(data, "MenuItem")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["patty_count"], int)
    assert isinstance(data["produce_units"], int)
    assert isinstance(data["active"], bool)


def assert_store(data: dict):
    _assert_common(data, "Store")
    assert isinstance(data["commissary_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("SITE_REVIEW", "APPROVED", "OPEN", "CLOSED")
    assert data["opening_mode"] in ("NORMAL", "OPENING_SURGE")
    assert isinstance(data["distance_km"], (int, float))


def assert_batch(data: dict):
    _assert_common(data, "DeliveryBatch")
    assert isinstance(data["store_id"], str)
    assert isinstance(data["commissary_id"], str)
    assert isinstance(data["patty_count"], int)
    assert isinstance(data["bun_count"], int)
    assert isinstance(data["produce_units"], int)
    assert isinstance(data["cooler_cases_required"], int)
    assert data["status"] in ("PLANNED", "LOADED", "DELIVERED", "CANCELLED")


def assert_order(data: dict):
    _assert_common(data, "Order")
    assert isinstance(data["store_id"], str)
    assert isinstance(data["placed_by_associate_id"], str)
    assert isinstance(data["lines"], list)
    assert isinstance(data["base_total_cents"], int)
    assert isinstance(data["modifier_charge_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["patties_reserved"], int)
    assert data["status"] in ("PLACED", "SERVED", "CANCELLED")


def assert_associate(data: dict):
    _assert_common(data, "Associate")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_store_id"], str)
    assert data["current_level"] in (
        "LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_4", "LEVEL_5",
        "SHIFT_LEAD", "MANAGER")
    assert isinstance(data["hourly_wage_cents"], int)
    assert isinstance(data["promotion_count"], int)
    assert isinstance(data["active"], bool)


def assert_manager_posting(data: dict):
    _assert_common(data, "ManagerPosting")
    assert isinstance(data["store_id"], str)
    assert isinstance(data["posted_by_id"], str)
    assert data["status"] in ("OPEN", "CLOSED", "CANCELLED")


def assert_manager_application(data: dict):
    _assert_common(data, "ManagerApplication")
    assert isinstance(data["posting_id"], str)
    assert isinstance(data["candidate_associate_id"], str)
    assert data["status"] in ("PENDING", "ACCEPTED", "REJECTED", "WITHDRAWN")


def assert_shift(data: dict):
    _assert_common(data, "ShiftAssignment")
    assert isinstance(data["store_id"], str)
    assert isinstance(data["associate_id"], str)
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_beef_delivery(data: dict):
    _assert_common(data, "BeefDelivery")
    assert isinstance(data["commissary_id"], str)
    assert isinstance(data["supplier_id"], str)
    assert isinstance(data["raw_beef_lbs"], (int, float))
    assert isinstance(data["transit_temp_celsius"], (int, float))
    assert data["status"] in ("SCHEDULED", "IN_TRANSIT", "RECEIVED", "REJECTED")


def assert_production_run(data: dict):
    _assert_common(data, "ProductionRun")
    assert isinstance(data["commissary_id"], str)
    assert isinstance(data["patties_planned"], int)
    assert isinstance(data["buns_planned"], int)
    assert isinstance(data["produce_units_planned"], int)
    assert isinstance(data["beef_lbs_required"], int)
    assert data["status"] in ("PLANNED", "COMPLETED", "CANCELLED")
