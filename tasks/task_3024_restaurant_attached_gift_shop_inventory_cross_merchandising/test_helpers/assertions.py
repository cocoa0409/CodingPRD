"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict, has_version=True):
    """Every resource carries id/created_at; mutated resources also carry
    updated_at (ISO 8601) and version (int)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    if has_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_brand(data: dict):
    assert_common_fields(data)
    assert data["brand_code"]
    assert data["retail_recognition_policy"] in ("FINAL_ONLY", "PROVISIONAL_THEN_FINAL")
    assert data["fiscal_period_status"] in ("OPEN", "CLOSED")
    for field in (
        "provisional_retail_revenue_cents",
        "recognized_retail_revenue_cents",
        "brand_retail_sales_per_guest_cents",
        "liquidation_trigger_rpg_cents",
        "open_receipt_grace_hours",
        "transfer_variance_tolerance_bps",
        "waiting_area_retail_weight_bps",
        "tip_minimum_minutes",
        "clearance_buffer_hours",
        "food_storage_corridor_units",
        "max_check_total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_location(data: dict):
    assert_common_fields(data)
    assert data["region_code"] in ("NORTHEAST", "SOUTHEAST", "MIDWEST", "SOUTHWEST", "WEST")
    assert data["assortment_tier"] in ("FULL", "REGIONAL_TWEAK", "MINIMAL")
    assert isinstance(data["backroom_capacity_units"], int) and data["backroom_capacity_units"] > 0
    assert isinstance(data["local_event_codes"], list)


def assert_location_posture_invariants(data: dict, brand=None):
    """staging_free_units = capacity - occupancy - committed - food corridor."""
    assert data["backroom_occupancy_units"] >= 0
    assert data["backroom_committed_units"] >= 0
    if brand is not None:
        expected = (
            data["backroom_capacity_units"]
            - data["backroom_occupancy_units"]
            - data["backroom_committed_units"]
            - brand["food_storage_corridor_units"]
        )
        assert data["staging_free_units"] == expected, (
            f"staging_free_units {data['staging_free_units']} != derived {expected}"
        )


def assert_store_day(data: dict):
    assert_common_fields(data)
    assert data["day_status"] in ("OPEN", "CLOSED")
    assert data["traffic_state"] in ("QUIET", "STEADY", "RUSH")
    assert data["conversion_gate"] in ("OPEN", "GATED_RESTRICTED", "SUSPENDED")
    if data["day_status"] == "OPEN":
        assert data.get("closed_at") is None, "closed_at must be null while the day is OPEN"


def assert_item(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("ACTIVE", "CLEARANCE", "DISCONTINUED")
    assert data["theme_code"] in (
        "HARVEST",
        "WINTER_HOLIDAY",
        "SPRING",
        "SUMMER",
        "NOSTALGIA_CLASSIC",
    )
    assert isinstance(data["unit_retail_cents"], int) and data["unit_retail_cents"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["clearance_week"], int)


def assert_guest_check(data: dict):
    assert_common_fields(data)
    assert data["check_status"] in ("PENDING", "FINALIZED", "VOIDED")
    assert data["settlement_status"] in ("UNSETTLED", "SETTLED", "REFUNDED")
    assert isinstance(data["retail_subtotal_cents"], int)
    assert isinstance(data["service_fee_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_receipt(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "RECONCILED", "DISPUTED", "SETTLED", "CLOSED")
    assert data["payment_method"] in ("CASH", "CARD", "GIFT_CARD", "SPLIT")
    assert isinstance(data["provisional_retail_cents"], int)
    assert isinstance(data["recognized_retail_cents"], int)
    assert data["recognition_delta_cents"] == (
        data["recognized_retail_cents"] - data["provisional_retail_cents"]
    ), "recognition_delta_cents must equal recognized minus provisional"


def assert_clearance_schedule(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "EXTENDED", "LIQUIDATED", "CANCELLED")
    assert data["stage"] in ("S1", "S2", "S3", "S4")
    assert data["markdown_pct"] in (0, 0.25, 0.40, 0.55, 0.70), (
        f"unexpected markdown_pct {data['markdown_pct']}"
    )
    assert isinstance(data["liquidation_bucket_units"], list)
    assert isinstance(data["remaining_units"], int)


def assert_staff_shift(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["workcode"] in (
        "SERVER",
        "COOK",
        "CASHIER",
        "RETAIL_STOCK",
        "RETAIL_CASHIER",
        "RETAIL_GIFT",
    )
    assert isinstance(data["tip_eligible_minutes"], int)
    if data["tip_eligible"]:
        assert data["workcode"] in ("SERVER", "CASHIER"), (
            "only SERVER and CASHIER are tip-eligible positions"
        )


def assert_transfer(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "IN_TRANSIT", "RECEIVED", "RECONCILED", "VOID_RECEIVING")
    assert data["receiving_zone"] in ("BACKROOM", "FOOD_STORAGE")
    assert data["variance_units"] == data["received_units"] - data["declared_units"]


def assert_planogram_version(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED", "RETIRED")
    assert data["assortment_tier"] in ("FULL", "REGIONAL_TWEAK", "MINIMAL")
    if data["status"] == "DRAFT":
        assert data.get("published_at") is None


def assert_planogram_slot(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "APPLIED", "VERIFIED", "FROZEN", "VACATED")
    assert isinstance(data["facings"], int) and data["facings"] >= 1
    assert isinstance(data["min_presentation_units"], int) and data["min_presentation_units"] >= 1


def assert_capacity_reading(data: dict):
    assert_common_fields(data)
    assert data["source"] in ("RECEIVING", "SALES_FLOOR_MOVE", "CYCLE_COUNT")
    assert data["occupancy_units"] == (
        data["backroom_units"] + data["food_storage_units"] + data["dated_units"]
    ), "occupancy_units must sum the three measured components"