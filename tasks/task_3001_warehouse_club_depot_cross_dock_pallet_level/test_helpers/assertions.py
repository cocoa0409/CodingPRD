"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

VALID_VENDOR_STATUSES = ["ACTIVE", "SUSPENDED", "DEACTIVATED"]
VALID_CLUB_POSTURES = ["NORMAL", "CONSTRAINED", "FROZEN"]
VALID_ITEM_STATUSES = ["DRAFT", "ACTIVE", "DELETION_REVIEW", "DISCONTINUED"]
VALID_ITEM_TYPES = ["REGULAR", "TREASURE_HUNT"]
VALID_APPOINTMENT_STATUSES = ["BOOKED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"]
VALID_PALLET_STATUSES = ["RECEIVED", "ALLOCATED", "SHIPPED", "STRANDED", "RECONCILED"]
VALID_RUN_STATUSES = ["OPEN", "COMMITTED", "CANCELLED"]
VALID_ALLOCATION_STATUSES = ["PROPOSED", "COMMITTED", "SHIPPED", "VOIDED"]
VALID_MEMBER_STATUSES = ["ACTIVE", "SUSPENDED"]
VALID_MEMBER_TIERS = ["GOLD_STAR", "EXECUTIVE"]
VALID_PURCHASE_STATUSES = ["COMPLETED", "REFUNDED"]
VALID_DECISIONS = ["SELL_THROUGH", "MARKDOWN"]
VALID_COMPLAINT_CATEGORIES = ["QUALITY", "AVAILABILITY", "PRICING", "SAFETY"]
VALID_COMPLAINT_STATUSES = ["OPEN", "RESOLVED"]
VALID_CHARGEBACK_REASONS = ["LATE_CHECKIN", "NO_SHOW", "OVER_PALLET_COUNT"]
VALID_CHARGEBACK_STATUSES = ["ASSESSED", "APPEALED", "WAIVED", "CONFIRMED"]
VALID_DEPARTMENTS = ["GAS", "PHARMACY", "OPTICAL"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_region(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["code"], str) and 2 <= len(data["code"]) <= 4
    assert data["code"].isupper() and data["code"].isalpha()
    assert isinstance(data["avg_member_income_cents"], int)
    assert data["avg_member_income_cents"] >= 0


def assert_vendor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["vendor_code"], str)
    assert data["status"] in VALID_VENDOR_STATUSES
    assert isinstance(data["compliance_score_bp"], int)
    assert isinstance(data["total_chargeback_cents"], int)


def assert_club(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("region_id", "")), "region_id must be a UUID"
    assert isinstance(data["club_number"], int) and data["club_number"] > 0
    assert isinstance(data["floor_slot_capacity"], int) and data["floor_slot_capacity"] >= 1
    assert isinstance(data["member_base"], int) and data["member_base"] >= 0
    assert data["posture"] in VALID_CLUB_POSTURES
    assert isinstance(data["allocated_slot_count"], int) and data["allocated_slot_count"] >= 0


def assert_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("vendor_id", "")), "vendor_id must be a UUID"
    assert isinstance(data["sku"], str) and len(data["sku"]) == 7 and data["sku"].isdigit()
    assert data["status"] in VALID_ITEM_STATUSES
    assert data["item_type"] in VALID_ITEM_TYPES
    assert isinstance(data["pallet_qty_units"], int) and data["pallet_qty_units"] >= 1
    assert data["pallets_per_slot"] in (1, 2)
    assert isinstance(data["case_pack_qty"], int) and data["case_pack_qty"] >= 1
    assert isinstance(data["cases_per_layer"], int) and data["cases_per_layer"] >= 1
    assert isinstance(data["max_layers"], int) and data["max_layers"] >= 1


def assert_depot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("region_id", "")), "region_id must be a UUID"
    assert isinstance(data["dock_count"], int) and data["dock_count"] >= 1
    assert isinstance(data["dock_hours_open"], str)
    assert isinstance(data["dock_hours_close"], str)
    assert isinstance(data["slot_length_minutes"], int) and data["slot_length_minutes"] >= 15


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_APPOINTMENT_STATUSES
    assert isinstance(data["pallet_count"], int) and data["pallet_count"] >= 1
    assert isinstance(data["unload_fee_cents"], int) and data["unload_fee_cents"] >= 0
    assert isinstance(data["chargeback_cents"], int) and data["chargeback_cents"] >= 0


def assert_pallet(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_PALLET_STATUSES
    assert isinstance(data["unit_qty"], int) and data["unit_qty"] >= 1
    assert isinstance(data["received_date"], str)


def assert_cross_dock_run(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_RUN_STATUSES
    assert isinstance(data["run_date"], str)
    assert isinstance(data["cutoff_time"], str)


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_ALLOCATION_STATUSES
    assert isinstance(data["floor_slots_reserved"], int) and data["floor_slots_reserved"] >= 1
    assert isinstance(data["run_version"], int) and data["run_version"] >= 1
    assert isinstance(data["allocation_score"], (int, float))


def assert_member(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_MEMBER_STATUSES
    assert data["tier"] in VALID_MEMBER_TIERS
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["membership_number"], str)


def assert_purchase(data: dict):
    _assert_common(data)
    assert data["status"] in VALID_PURCHASE_STATUSES
    assert isinstance(data["unit_qty"], int) and data["unit_qty"] >= 1
    assert isinstance(data["cap_window"], str)


def assert_markdown_decision(data: dict):
    _assert_common(data)
    assert data["decision"] in VALID_DECISIONS
    assert isinstance(data["sell_through_pct"], int)


def assert_complaint(data: dict):
    _assert_common(data)
    assert data["category"] in VALID_COMPLAINT_CATEGORIES
    assert data["status"] in VALID_COMPLAINT_STATUSES
    assert isinstance(data["weight"], (int, float))


def assert_chargeback(data: dict):
    _assert_common(data)
    assert data["reason"] in VALID_CHARGEBACK_REASONS
    assert data["status"] in VALID_CHARGEBACK_STATUSES
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_department_sale(data: dict):
    _assert_common(data)
    assert data["department"] in VALID_DEPARTMENTS
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert isinstance(data["sold_on"], str)


def assert_club_invariants(data: dict):
    """Club derived fields must stay consistent after any operation (PRD §3.4)."""
    assert data["allocated_slot_count"] >= 0, "allocated_slot_count must be non-negative"
    assert data["allocated_slot_count"] <= data["floor_slot_capacity"], (
        "allocated_slot_count must never exceed floor_slot_capacity"
    )
    capacity = data["floor_slot_capacity"]
    threshold = (capacity * 80) // 100
    count = data["allocated_slot_count"]
    if count >= capacity:
        expected = "FROZEN"
    elif count > threshold:
        expected = "CONSTRAINED"
    else:
        expected = "NORMAL"
    assert data["posture"] == expected, (
        f"posture {data['posture']} inconsistent with {count} slots of capacity {capacity}"
    )
