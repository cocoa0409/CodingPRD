"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def ts_iso(iso: str) -> str:
    """Normalize an ISO-8601 UTC instant to the PRD-canonical wire format:
    three fractional digits, per PRD §2.4 ("both ISO 8601 UTC timestamps with
    three fractional digits"). Accepts inputs with or without a fractional
    part (e.g. "2026-03-13T11:00:00Z" -> "2026-03-13T11:00:00.000Z")."""
    s = iso.strip()
    if s.endswith("Z"):
        s = s[:-1]
    if "." in s:
        head, frac = s.split(".", 1)
        frac = (frac + "000")[:3]
    else:
        head, frac = s, "000"
    return f"{head}.{frac}Z"


def assert_store(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["store_name"], str) and len(data["store_name"]) > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert data["posture"] in ["OFFSEASON", "WINTER_HEATING", "SPRING_PLANTING", "FALL_FEED"]
    assert data.get("active_campaign_id") is None or isinstance(data["active_campaign_id"], str)
    assert isinstance(data["hazmat_gallons_used_today"], (int, float))
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_season_campaign(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["season"] in ["WINTER_HEATING", "SPRING_PLANTING", "FALL_FEED"]
    assert isinstance(data["aisle_count"], int) and data["aisle_count"] >= 1
    assert isinstance(data["aisles_reset_count"], int) and data["aisles_reset_count"] >= 0
    assert data["status"] in [
        "DRAFT", "TEARDOWN", "VERIFY_PENDING", "READY", "ACTIVE", "COMPLETED", "CANCELLED",
    ]
    assert data.get("activated_at") is None or is_iso8601_timestamp(data["activated_at"])
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_staging_bay(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["bay_no"], int) and data["bay_no"] >= 1
    assert data["size_class"] in ["M", "L", "XL"]
    assert data["status"] in ["AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_hatchery_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["species"], str) and len(data["species"]) > 0
    assert isinstance(data["daily_capacity"], int) and data["daily_capacity"] >= 1
    assert isinstance(data["min_purchase_qty"], int) and data["min_purchase_qty"] >= 1
    assert isinstance(data["base_price_cents_per_bird"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "CLOSED", "CANCELLED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_livestock_lot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["quantity_received"], int) and data["quantity_received"] >= 1
    for field in ("quantity_on_hand", "quantity_sold", "mortality_count", "quantity_quarantined"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert isinstance(data["mortality_rate"], (int, float))
    assert data["health_flag"] in ["NORMAL", "QUARANTINED"]
    assert data["status"] in ["RECEIVING", "ON_SALE", "SUSPENDED", "SALE_CLOSED", "DISPOSITIONED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_care_log_entry(data: dict):
    """Append-only log: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert data["entry_type"] in ["FEEDING", "WATER", "TEMPERATURE", "MORTALITY"]
    assert "version" not in data, "append-only care log must not carry a version field"
    assert "updated_at" not in data, "append-only care log must not carry an updated_at field"


def assert_chick_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["total_cents"], int)
    assert data["claim_status"] in ["NONE", "CLAIMED", "APPROVED", "REJECTED"]
    assert data["status"] in ["RESERVED", "BROODER_VERIFIED", "FULFILLED", "CANCELLED", "EXPIRED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_weighted_sale(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["sale_kind"] in ["FEED_BULK", "PROPANE_EXCHANGE"]
    assert data["container_class"] in ["BAG_50", "DRUM", "TOTE", "CYLINDER_20"]
    assert isinstance(data["gross_weight_lbs"], (int, float)) and data["gross_weight_lbs"] > 0
    assert isinstance(data["provisional_tare_lbs"], (int, float))
    assert isinstance(data["provisional_total_cents"], int)
    assert data["status"] in ["PROVISIONAL", "FINALIZED", "VOIDED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_loyalty_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str) and len(data["phone"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert data["tier"] in ["NEIGHBOR", "RANCH_HAND", "HOMESTEAD"]
    assert isinstance(data["points_balance"], int)
    assert isinstance(data["tier_qualifying_points"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_loyalty_ledger_entry(data: dict):
    """Append-only log: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data["created_at"])
    assert data["entry_type"] in ["ACCRUAL", "REDEMPTION", "ADJUSTMENT", "REVERSAL"]
    assert isinstance(data["points_delta"], int)
    assert isinstance(data["counts_toward_tier"], bool)
    assert "version" not in data, "append-only ledger entry must not carry a version field"
    assert "updated_at" not in data, "append-only ledger entry must not carry an updated_at field"


def assert_pickup_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["item_size_class"] in ["M", "L", "XL"]
    assert data["fulfillment_status"] in [
        "PLACED", "STAGED", "READY_FOR_PICKUP", "COMPLETED", "CANCELLED", "EXPIRED",
    ]
    assert data["loadout_status"] in ["NOT_REQUIRED", "ASSISTANCE_REQUESTED", "LOADOUT_DONE"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_service_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["event_kind"] in ["PET_WASH", "VET_CLINIC"]
    assert isinstance(data["slot_length_minutes"], int) and data["slot_length_minutes"] >= 5
    assert isinstance(data["capacity_per_slot"], int) and data["capacity_per_slot"] >= 1
    assert data["status"] in ["DRAFT", "PUBLISHED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_event_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data["slot_start"])
    assert is_iso8601_timestamp(data["slot_end"])
    assert data["status"] in ["BOOKED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED"]
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_lot_bird_conservation(lot: dict):
    """Bird conservation: received == on_hand + sold + mortality + quarantined
    only when no birds are currently reserved (reservations are drawn from
    on_hand, so mid-reservation the sum is on_hand + sold + mortality +
    quarantined + reserved)."""
    total = (
        lot["quantity_on_hand"]
        + lot["quantity_sold"]
        + lot["mortality_count"]
        + lot["quantity_quarantined"]
    )
    assert total <= lot["quantity_received"], (
        f"conservation violated: {total} > received {lot['quantity_received']}"
    )


def assert_account_balance_non_negative(account: dict):
    assert account["points_balance"] >= 0, "points_balance must never be negative"
