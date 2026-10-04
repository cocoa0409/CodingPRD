"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "LOCATION_CODE": "OKC-114",
    "LOCATION_NAME": "OKC 114",
    "TIMEZONE": "America/Chicago",
    "STALL_CAPACITY": 4,
    "TARGET_SECONDS": 600,
    "FOOD_PRICE": 500,
    "DRINK_PRICE": 400,
    "MAX_TRAYS": 3,
}


def create_location_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["LOCATION_CODE"],
        "name": DEFAULTS["LOCATION_NAME"],
        "timezone": DEFAULTS["TIMEZONE"],
        "stall_capacity": DEFAULTS["STALL_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_item_payload(**overrides) -> dict:
    defaults = {
        "sku": "FD-1",
        "name": "Food Item",
        "category": "FOOD",
        "base_price_cents": DEFAULTS["FOOD_PRICE"],
        "size_scheme": "NONE",
        "half_price_eligible": False,
    }
    defaults.update(overrides)
    return defaults


def create_customization_option_payload(**overrides) -> dict:
    defaults = {
        "code": "CHERRY",
        "applies_to_category": "DRINK",
        "price_cents": 50,
        "is_size": False,
    }
    defaults.update(overrides)
    return defaults


def create_size_option_payload(**overrides) -> dict:
    defaults = {
        "code": "M",
        "applies_to_category": "ANY",
        "price_cents": 0,
        "is_size": True,
        "size_upcharge_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "guest@example.com",
        "display_name": "Guest",
    }
    defaults.update(overrides)
    return defaults


def create_stall_payload(**overrides) -> dict:
    defaults = {
        "stall_number": 1,
        "kind": "STALL",
    }
    defaults.update(overrides)
    return defaults


def create_carhop_payload(**overrides) -> dict:
    defaults = {
        "name": "Hop",
        "zone": "NORTH",
        "on_shift": True,
        "max_trays": DEFAULTS["MAX_TRAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_drive_thru_order_payload(**overrides) -> dict:
    defaults = {"channel": "DRIVE_THRU"}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {"quantity": 1}
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "code": "PROMO",
        "kind": "PROMO",
        "discount_type": "PERCENT_OFF_ORDER",
        "discount_value": 10,
        "window_start_local": "00:00",
        "window_end_local": "23:59",
        "app_only": False,
    }
    defaults.update(overrides)
    return defaults


def create_happy_hour_offer_payload(**overrides) -> dict:
    defaults = {
        "code": "HH",
        "kind": "HAPPY_HOUR",
        "discount_type": "HALF_PRICE_DRINKS",
        "discount_value": 0,
        "window_start_local": "14:00",
        "window_end_local": "16:00",
        "app_only": False,
    }
    defaults.update(overrides)
    return defaults


def create_service_target_payload(**overrides) -> dict:
    defaults = {
        "channel": "STALL_INTERCOM",
        "weather_mode": "NORMAL",
        "target_seconds": DEFAULTS["TARGET_SECONDS"],
    }
    defaults.update(overrides)
    return defaults


def create_fault_payload(**overrides) -> dict:
    defaults = {
        "kind": "INTERCOM_DEAD",
        "note": "not working",
        "reported_by_role": "CARHOP",
    }
    defaults.update(overrides)
    return defaults
