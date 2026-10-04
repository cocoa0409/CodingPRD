"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS as D


def create_store_payload(**overrides) -> dict:
    defaults = {"store_name": D["STORE_NAME"], "region_code": D["REGION_CODE"]}
    defaults.update(overrides)
    return defaults


def create_season_campaign_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "season": "WINTER_HEATING",
        "planogram_map": D["PLANOGRAM_MAP"],
        "aisle_count": D["AISLE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_staging_bay_payload(store_id, **overrides) -> dict:
    defaults = {"store_id": store_id, "bay_no": 1, "size_class": "M"}
    defaults.update(overrides)
    return defaults


def create_hatchery_schedule_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "species": D["SPECIES"],
        "breed": D["BREED"],
        "hatch_date": D["HATCH_DATE"],
        "sale_window_start": D["SALE_WINDOW_START"],
        "sale_window_end": D["SALE_WINDOW_END"],
        "daily_capacity": D["DAILY_CAPACITY"],
        "min_purchase_qty": D["MIN_PURCHASE_QTY"],
        "base_price_cents_per_bird": D["BASE_PRICE_CENTS_PER_BIRD"],
    }
    defaults.update(overrides)
    return defaults


def create_livestock_lot_payload(store_id, schedule_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "hatchery_schedule_id": schedule_id,
        "quantity_received": D["QUANTITY_RECEIVED"],
        "received_at": D["RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_care_log_payload(**overrides) -> dict:
    defaults = {"entry_type": "FEEDING"}
    defaults.update(overrides)
    return defaults


def create_chick_order_payload(store_id, lot_id, account_id, lot_version, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "livestock_lot_id": lot_id,
        "loyalty_account_id": account_id,
        "quantity": D["ORDER_QUANTITY"],
        "pickup_date": D["PICKUP_DATE"],
        "expected_livestock_lot_version": lot_version,
    }
    defaults.update(overrides)
    return defaults


def create_weighted_sale_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "sale_kind": "FEED_BULK",
        "container_class": "DRUM",
        "gross_weight_lbs": 100,
    }
    defaults.update(overrides)
    return defaults


def create_loyalty_account_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Member", "phone": "555-0100"}
    defaults.update(overrides)
    return defaults


def create_pickup_order_payload(store_id, account_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "loyalty_account_id": account_id,
        "item_sku": "GENERATOR-9K",
        "item_size_class": "M",
        "requires_loadout_assistance": False,
    }
    defaults.update(overrides)
    return defaults


def create_service_event_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "event_kind": "PET_WASH",
        "resource_name": "wash-bay-1",
        "event_date": "2026-09-15T00:00:00Z",
        "slot_window_start": "2026-09-15T09:00:00Z",
        "slot_window_end": "2026-09-15T12:00:00Z",
        "slot_length_minutes": 30,
        "cleanup_buffer_minutes": 0,
        "capacity_per_slot": 1,
        "requires_vaccine_record": False,
    }
    defaults.update(overrides)
    return defaults
