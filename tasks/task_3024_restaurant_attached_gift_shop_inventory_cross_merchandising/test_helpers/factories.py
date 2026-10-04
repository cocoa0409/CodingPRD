"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "BRAND_CODE": "BR-1042",
    "LEGAL_NAME": "Old Mill Retail Partners LLC",
    "FISCAL_PERIOD": "2026-Q3",
    "STORE_NUMBER": "1042",
    "REGION_CODE": "SOUTHEAST",
    "ASSORTMENT_TIER": "REGIONAL_TWEAK",
    "BACKROOM_CAPACITY_UNITS": 400,
    "LOCAL_EVENT_CODES": ["SUMMER_BOAT"],
    "ITEM_NAME": "Hand-Carved Cedar Boat Shelf",
    "ITEM_SKU": "ITM-BOAT-6400",
    "THEME_CODE": "SUMMER",
    "UNIT_RETAIL_CENTS": 6400,
    "UNIT_COST_CENTS": 2400,
    "IMPORT_LEAD_TIME_DAYS": 45,
    "TABLE_NUMBER": "12",
    "RESTAURANT_GUEST_COUNT": 4,
    "RESTAURANT_SUBTOTAL_CENTS": 11200,
}


def create_brand_payload(**overrides) -> dict:
    defaults = {
        "brand_code": DEFAULTS["BRAND_CODE"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "retail_recognition_policy": "FINAL_ONLY",
        "liquidation_trigger_rpg_cents": 700,
        "open_receipt_grace_hours": 24,
        "transfer_variance_tolerance_bps": 200,
        "waiting_area_retail_weight_bps": 6000,
        "tip_minimum_minutes": 240,
        "clearance_buffer_hours": 24,
        "food_storage_corridor_units": 310,
        "max_check_total_cents": 50000,
        "fiscal_period": DEFAULTS["FISCAL_PERIOD"],
    }
    defaults.update(overrides)
    return defaults


def create_brand_payload_minimal(**overrides) -> dict:
    """Only the identifying fields — everything else takes its brand default."""
    defaults = {
        "brand_code": DEFAULTS["BRAND_CODE"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "fiscal_period": DEFAULTS["FISCAL_PERIOD"],
    }
    defaults.update(overrides)
    return defaults


def create_location_payload(brand_id: str, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "store_number": DEFAULTS["STORE_NUMBER"],
        "region_code": DEFAULTS["REGION_CODE"],
        "assortment_tier": DEFAULTS["ASSORTMENT_TIER"],
        "backroom_capacity_units": DEFAULTS["BACKROOM_CAPACITY_UNITS"],
        "clearance_max_active": 3,
        "local_event_codes": list(DEFAULTS["LOCAL_EVENT_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def create_store_day_payload(location_id: str, business_date: str = "2026-09-01T00:00:00Z", **overrides) -> dict:
    defaults = {"location_id": location_id, "business_date": business_date}
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["ITEM_SKU"],
        "name": DEFAULTS["ITEM_NAME"],
        "theme_code": DEFAULTS["THEME_CODE"],
        "nostalgia_flag": False,
        "unit_retail_cents": DEFAULTS["UNIT_RETAIL_CENTS"],
        "unit_cost_cents": DEFAULTS["UNIT_COST_CENTS"],
        "import_lead_time_days": DEFAULTS["IMPORT_LEAD_TIME_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_shift_payload(location_id: str, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "employee_id": "E-101",
        "start_utc": "2026-09-01T09:00:00Z",
        "end_utc": "2026-09-01T13:00:00Z",
        "workcode": "CASHIER",
        "tip_eligible_claim": False,
    }
    defaults.update(overrides)
    return defaults


def create_guest_check_payload(location_id: str, store_day_id: str, presented_shift_id: str, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "store_day_id": store_day_id,
        "table_number": DEFAULTS["TABLE_NUMBER"],
        "restaurant_guest_count": DEFAULTS["RESTAURANT_GUEST_COUNT"],
        "restaurant_subtotal_cents": DEFAULTS["RESTAURANT_SUBTOTAL_CENTS"],
        "presented_shift_id": presented_shift_id,
    }
    defaults.update(overrides)
    return defaults


def create_planogram_version_payload(location_id: str, assortment_tier: str = "REGIONAL_TWEAK",
                                     effective_date: str = "2026-10-01T00:00:00Z",
                                     **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "assortment_tier": assortment_tier,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def retail_line(item_id: str, quantity: int = 1, unit_price_cents: int = 6400,
                discount_pct: float = 0.0, line_kind: str = "RETAIL") -> dict:
    return {
        "item_id": item_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "discount_pct": discount_pct,
        "line_kind": line_kind,
    }


def create_receipt_payload(location_id: str, store_day_id: str, receipt_number: str,
                           lines: list, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "store_day_id": store_day_id,
        "receipt_number": receipt_number,
        "lines": lines,
        "restaurant_share_cents": 0,
        "restaurant_share_basis": "CHECK_TOTAL",
        "payment_method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_clearance_schedule_payload(location_id: str, item_id: str,
                                      expected_item_version: int,
                                      start_date: str = "2026-09-01T00:00:00Z",
                                      end_date: str = "2026-10-01T00:00:00Z",
                                      **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "item_id": item_id,
        "start_date": start_date,
        "end_date": end_date,
        "expected_item_version": expected_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(location_id: str, store_day_id: str, item_id: str,
                            declared_units: int, received_units: int = 0,
                            receiving_zone: str = "BACKROOM", **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "store_day_id": store_day_id,
        "item_id": item_id,
        "declared_units": declared_units,
        "received_units": received_units,
        "receiving_zone": receiving_zone,
    }
    defaults.update(overrides)
    return defaults


def create_capacity_reading_payload(store_day_id: str, measured_at: str,
                                    backroom_units: int, food_storage_units: int = 0,
                                    dated_units: int = 0,
                                    source: str = "CYCLE_COUNT", **overrides) -> dict:
    defaults = {
        "store_day_id": store_day_id,
        "measured_at": measured_at,
        "backroom_units": backroom_units,
        "food_storage_units": food_storage_units,
        "dated_units": dated_units,
        "source": source,
    }
    defaults.update(overrides)
    return defaults


def create_planogram_version_payload(location_id: str, assortment_tier: str = "REGIONAL_TWEAK",
                                     effective_date: str = "2026-10-01T00:00:00Z",
                                     **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "assortment_tier": assortment_tier,
        "effective_date": effective_date,
    }
    defaults.update(overrides)
    return defaults


def create_planogram_slot_payload(planogram_version_id: str, item_id: str,
                                  slot_position: int, facings: int = 1,
                                  min_presentation_units: int = 1, **overrides) -> dict:
    defaults = {
        "planogram_version_id": planogram_version_id,
        "item_id": item_id,
        "slot_position": slot_position,
        "facings": facings,
        "min_presentation_units": min_presentation_units,
    }
    defaults.update(overrides)
    return defaults