"""Payload factories: one per entity, declared input fields only."""

from .constants import TEST_DEFAULTS

DEFAULTS = {
    "SKU": "SUBS-001",
    "ITEM_NAME": "Classic Sub",
    "PLATTER_SKU": "PLAT-CLASSIC",
    "PLATTER_NAME": "Classic Platter",
    "BREAD_SKU": "BREAD-ITA",
    "BREAD_NAME": "Italian Roll",
    "COLD_CUT_SKU": "CC-TURK-01",
    "COLD_CUT_NAME": "Turkey Breast",
    "EMPLOYEE_NUMBER": "E-1001",
    "FULL_NAME": "Ana One",
    "ASSET_TAG": "SL-1",
    "CUSTOMER_NAME": "Northside PTA",
    "FILE_LABEL": "PF-0901",
    "PROMO_CODE": "FEAT-0914",
}


def create_store_payload(**overrides) -> dict:
    payload = {
        "store_number": TEST_DEFAULTS["STORE_NUMBER"],
        "name": TEST_DEFAULTS["STORE_NAME"],
        "deli_case_capacity_lbs": TEST_DEFAULTS["DELI_CASE_CAPACITY_LBS"],
        "hot_bar_capacity_lbs": TEST_DEFAULTS["HOT_BAR_CAPACITY_LBS"],
        "sub_station_count": TEST_DEFAULTS["SUB_STATION_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_item_payload(**overrides) -> dict:
    payload = {
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["ITEM_NAME"],
        "category": "SUB",
        "unit_cost_cents": 480,
        "retail_price_per_lb_cents": 799,
        "case_life_minutes": 240,
        "markdown_window_minutes": 30,
        "allergen_flags": ["WHEAT", "MILK", "SOY"],
        "slicer_required": False,
        "bread_deli_item_id": None,
    }
    payload.update(overrides)
    return payload


def create_bread_item_payload(**overrides) -> dict:
    payload = create_item_payload(
        sku=DEFAULTS["BREAD_SKU"],
        name=DEFAULTS["BREAD_NAME"],
        category="BREAD",
        unit_cost_cents=120,
        retail_price_per_lb_cents=250,
        case_life_minutes=720,
        markdown_window_minutes=60,
        allergen_flags=["WHEAT"],
        slicer_required=False,
        bread_deli_item_id=None,
    )
    payload.update(overrides)
    return payload


def create_cold_cut_item_payload(**overrides) -> dict:
    payload = create_item_payload(
        sku=DEFAULTS["COLD_CUT_SKU"],
        name=DEFAULTS["COLD_CUT_NAME"],
        category="COLD_CUT",
        unit_cost_cents=520,
        retail_price_per_lb_cents=899,
        case_life_minutes=180,
        markdown_window_minutes=30,
        allergen_flags=["MILK"],
        slicer_required=True,
        bread_deli_item_id=None,
    )
    payload.update(overrides)
    payload.pop("bread_deli_item_id", None)
    return payload


def create_platter_item_payload(**overrides) -> dict:
    payload = create_item_payload(
        sku=DEFAULTS["PLATTER_SKU"],
        name=DEFAULTS["PLATTER_NAME"],
        category="CATERING_PLATTER",
        unit_cost_cents=900,
        retail_price_per_lb_cents=1800,
        case_life_minutes=480,
        markdown_window_minutes=60,
        allergen_flags=["MILK", "WHEAT"],
        slicer_required=False,
        bread_deli_item_id=None,
    )
    payload.update(overrides)
    return payload


def create_associate_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "employee_number": DEFAULTS["EMPLOYEE_NUMBER"],
        "full_name": DEFAULTS["FULL_NAME"],
        "primary_role": "DELI_CLERK",
        "allergy_set": ["MILK", "WHEAT", "SOY"],
    }
    payload.update(overrides)
    return payload


def create_certification_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "associate_id": None,
        "cert_type": "SLICER_OPERATION",
        "issued_at": TEST_DEFAULTS["CERT_ISSUED_AT"],
        "expires_at": TEST_DEFAULTS["CERT_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_slicer_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "sanitation_cycle_limit": 25,
    }
    payload.update(overrides)
    return payload


def create_batch_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "deli_item_id": None,
        "produced_by_associate_id": None,
        "batch_code": "B-001",
        "planned_lbs": 4,
    }
    payload.update(overrides)
    return payload


def create_sub_ticket_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "deli_item_id": None,
        "bread_deli_item_id": None,
        "order_channel": "DIGITAL",
        "lines": [{"deli_item_id": None, "half_lb_units": 2, "line_sequence_number": 1}],
    }
    payload.update(overrides)
    return payload


def create_promotion_payload(**overrides) -> dict:
    payload = {
        "promo_code": DEFAULTS["PROMO_CODE"],
        "deli_item_id": None,
        "week_start_date": "2026-09-07T00:00:00Z",
        "week_end_date": "2026-09-14T00:00:00Z",
        "forecast_uplift_pct": 0.1,
        "trailing_baseline_units": 600,
    }
    payload.update(overrides)
    return payload


def create_bread_order_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "bread_deli_item_id": None,
        "promotion_id": None,
        "committed_units": 720,
    }
    payload.update(overrides)
    return payload


def create_price_file_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "file_label": DEFAULTS["FILE_LABEL"],
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2026-10-01T00:00:00Z",
        "item_price_count": 6,
    }
    payload.update(overrides)
    return payload


def create_label_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "subject_type": "PRODUCTION_BATCH",
        "subject_ref_id": None,
        "net_weight_lbs": 1.0,
        "unit_price_cents": 899,
    }
    payload.update(overrides)
    return payload


def create_catering_order_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "platter_deli_item_id": None,
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "platter_count": 3,
        "headcount": 8,
        "lead_time_hours": 30,
        "pickup_window_start": "2026-09-03T15:00:00Z",
        "pickup_window_end": "2026-09-03T15:45:00Z",
        "deposit_cents": 3000,
        "certified_planner_associate_id": None,
        "request_id": "REQ-K1",
    }
    payload.update(overrides)
    return payload


def create_waste_record_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "production_batch_id": None,
        "markdown_by_associate_id": None,
        "reason": "QUALITY",
    }
    payload.update(overrides)
    return payload


def create_sanitation_cycle_payload(**overrides) -> dict:
    payload = {
        "store_id": None,
        "slicer_id": None,
        "cycle_type": "ROUTINE",
        "cycle_minutes": 10,
    }
    payload.update(overrides)
    return payload