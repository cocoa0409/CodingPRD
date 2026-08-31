"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

PARTNERSHIP_STATUSES = ["PROSPECT", "MOU_PENDING", "ACTIVE", "SUSPENDED", "ARCHIVED"]
GRADE_BANDS = ["K_2", "G3_5", "G6_8", "G9_12"]
ITEM_CATEGORIES = ["WRITING", "PAPER", "BINDER", "HYGIENE", "BACKPACK"]
SITE_TYPES = ["RETAIL", "CORPORATE", "SCHOOL", "LIBRARY"]
BATCH_CONDITIONS = ["NEW", "GENTLY_USED", "DAMAGED"]
RESTRICTION_TYPES = ["UNRESTRICTED", "ITEM_RESTRICTED", "SCHOOL_RESTRICTED"]


def assert_common_fields(data: dict):
    """Every persisted resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_school(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"].strip()
    assert isinstance(data["district_code"], str) and data["district_code"].strip()
    assert 0.0 <= float(data["title_i_pct"]) <= 1.0
    assert isinstance(data["enrollment_count"], int) and data["enrollment_count"] >= 1
    assert isinstance(data["max_concurrent_seats"], int) and data["max_concurrent_seats"] >= 1
    assert data["partnership_status"] in PARTNERSHIP_STATUSES
    for counter in (
        "target_student_count",
        "students_served_interim_count",
        "students_served_audited_count",
        "no_show_count",
        "kits_delivered_count",
    ):
        assert isinstance(data[counter], int) and data[counter] >= 0, (
            f"{counter} must be a non-negative integer"
        )
    assert float(data["impact_index_interim"]) >= 0.0
    assert float(data["impact_index_audited"]) >= 0.0


def assert_supply_item(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and 1 <= len(data["sku"]) <= 32
    assert data["category"] in ITEM_CATEGORIES
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 1
    assert isinstance(data["bulk_pack_size"], int) and data["bulk_pack_size"] >= 1
    assert isinstance(data["hygiene_sealed_required"], bool)
    assert isinstance(data["catalog_active"], bool)


def assert_grade_kit_spec(data: dict):
    assert_common_fields(data)
    assert data["grade_band"] in GRADE_BANDS
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]
    assert isinstance(data["student_target_count"], int) and data["student_target_count"] >= 1
    assert isinstance(data["kit_unit_cost_cents"], int) and data["kit_unit_cost_cents"] >= 0
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0


def assert_kit_spec_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["qty_per_student"], int) and data["qty_per_student"] >= 1
    assert isinstance(data["substitutable"], bool)


def assert_drive_cycle(data: dict):
    assert_common_fields(data)
    assert data["cadence"] in ["BACK_TO_SCHOOL", "YEAR_ROUND"]
    assert data["status"] in [
        "DRAFT", "COLLECTING", "SORTING", "DISTRIBUTION", "RECONCILED", "CLOSED",
    ]
    for field in (
        "cash_received_cents",
        "cash_allocated_cents",
        "cash_available_cents",
        "unrestricted_gross_cents",
        "supplemental_cap_cents",
        "total_items_on_hand",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_collection_site(data: dict):
    assert_common_fields(data)
    assert data["site_type"] in SITE_TYPES
    assert data["operational_status"] in ["PENDING", "ACTIVE", "PAUSED", "CLOSED"]
    assert data["pledge_status"] in ["NONE", "PLEDGED", "PLEDGE_ACTIVE", "FULFILLED", "LAPSED"]
    assert isinstance(data["bin_capacity"], int) and data["bin_capacity"] >= 1
    assert isinstance(data["pledged_item_count"], int) and data["pledged_item_count"] >= 0
    assert isinstance(data["accepted_item_count"], int) and data["accepted_item_count"] >= 0


def assert_donation_batch(data: dict):
    assert_common_fields(data)
    assert data["condition"] in BATCH_CONDITIONS
    assert data["status"] in [
        "RECEIVED", "INSPECTED", "ACCEPTED", "QUARANTINED", "REMEDIATED", "DISCARDED",
    ]
    assert isinstance(data["qty_declared"], int) and data["qty_declared"] >= 1
    assert isinstance(data["qty_accepted"], int) and data["qty_accepted"] >= 0
    assert isinstance(data["qty_rejected"], int) and data["qty_rejected"] >= 0
    assert isinstance(data["sealed"], bool)


def assert_inventory_position(data: dict):
    assert_common_fields(data)
    for field in (
        "on_hand_qty",
        "reserved_qty",
        "distributed_qty",
        "damaged_qty",
        "accepted_donated_qty",
        "purchased_received_qty",
        "adjustment_qty",
        "in_transit_qty",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_unit_conservation(position: dict):
    """on_hand + reserved + distributed + damaged == donated + purchased + adjustments."""
    left = (
        position["on_hand_qty"]
        + position["reserved_qty"]
        + position["distributed_qty"]
        + position["damaged_qty"]
    )
    right = (
        position["accepted_donated_qty"]
        + position["purchased_received_qty"]
        + position["adjustment_qty"]
    )
    assert left == right, (
        f"unit conservation broken on position {position.get('id')}: "
        f"on_hand+reserved+distributed+damaged={left} but "
        f"donated+purchased+adjustment={right}"
    )


def assert_cash_conservation(cycle: dict):
    """cash_available_cents == cash_received_cents - cash_allocated_cents."""
    assert (
        cycle["cash_available_cents"]
        == cycle["cash_received_cents"] - cycle["cash_allocated_cents"]
    ), (
        f"cash conservation broken on cycle {cycle.get('id')}: "
        f"received={cycle['cash_received_cents']} allocated={cycle['cash_allocated_cents']} "
        f"available={cycle['cash_available_cents']}"
    )


def assert_cash_donation(data: dict):
    assert_common_fields(data)
    assert data["restriction_type"] in RESTRICTION_TYPES
    assert data["status"] in ["RECEIVED", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert data["available_cents"] == data["amount_cents"] - data["allocated_cents"]


def assert_purchase_order(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "RECEIVED", "CANCELLED"]
    assert isinstance(data["ordered_qty"], int)
    assert isinstance(data["line_subtotal_cents"], int)
    assert isinstance(data["admin_fee_cents"], int)
    assert data["total_cost_cents"] == data["line_subtotal_cents"] + data["admin_fee_cents"]
    assert isinstance(data["funding_allocations"], list)


def assert_volunteer_event(data: dict):
    assert_common_fields(data)
    assert data["event_type"] in ["SORTING", "ASSEMBLY"]
    assert data["status"] in ["SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]
    assert isinstance(data["volunteer_count"], int) and data["volunteer_count"] >= 1
    assert isinstance(data["planned_kit_capacity"], int) and data["planned_kit_capacity"] >= 0
    assert isinstance(data["assembled_kit_count"], int) and data["assembled_kit_count"] >= 0


def assert_distribution_event(data: dict):
    assert_common_fields(data)
    assert data["grade_band"] in GRADE_BANDS
    assert data["status"] in ["DRAFT", "PUBLISHED", "LOCKED", "CLOSED", "CANCELLED"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert 0.0 <= float(data["provisional_fill_pct"]) <= 100.0
    assert 0.0 <= float(data["final_fill_pct"]) <= 100.0
    for counter in ("confirmed_count", "waitlist_count", "served_student_count"):
        assert isinstance(data[counter], int) and data[counter] >= 0


def assert_student_registration(data: dict):
    assert_common_fields(data)
    assert data["grade_band"] in GRADE_BANDS
    assert data["eligibility_status"] in [
        "PENDING", "VERIFIED", "CONFIRMED", "WAITLISTED",
        "FULFILLED", "NO_SHOW", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["reserved_unit_count"], int) and data["reserved_unit_count"] >= 0
    assert isinstance(data["free_lunch_eligible"], bool)
    assert isinstance(data["income_verified"], bool)


def assert_teacher_request(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "FULFILLED"]
    assert isinstance(data["qty_requested"], int) and data["qty_requested"] >= 1
    assert isinstance(data["request_cost_cents"], int) and data["request_cost_cents"] >= 0


def assert_pct_equals(actual, expected, label="percentage"):
    """Percentages are stored to exactly 2 decimal places."""
    assert round(float(actual) - float(expected), 6) == 0.0, (
        f"{label} expected {expected}, got {actual}"
    )
