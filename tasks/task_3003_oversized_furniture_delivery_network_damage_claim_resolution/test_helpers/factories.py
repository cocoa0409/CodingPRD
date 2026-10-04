"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "SUPPLIER_CODE": "SUP-A",
    "SUPPLIER_LEGAL_NAME": "Acme Furniture Co",
    "HUB_CODE": "HUB-A",
    "HUB_NAME": "Northeast Hub",
    "ZONE": "ZONE_NE",
    "ITEM_SKU": "SKU-LG-1",
    "CUSTOMER_EMAIL": "c1@example.com",
    "CUSTOMER_NAME": "Customer One",
    "PLANNED_ARRIVAL": "2026-09-10",
    "ORIGIN_SHIP": "2026-09-07",
}


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "supplier_code": DEFAULTS["SUPPLIER_CODE"],
        "legal_name": DEFAULTS["SUPPLIER_LEGAL_NAME"],
        "drop_ship_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["ITEM_SKU"],
        "dim_length_in": 40,
        "dim_width_in": 40,
        "dim_height_in": 20,
        "weight_lb": 30,
        "declared_value_cents": 80000,
        "white_glove_eligible": True,
    }
    defaults.update(overrides)
    return defaults


def create_hub_payload(**overrides) -> dict:
    defaults = {
        "hub_code": DEFAULTS["HUB_CODE"],
        "name": DEFAULTS["HUB_NAME"],
        "serves_zones": [DEFAULTS["ZONE"]],
        "white_glove_capable": True,
        "daily_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_freight_lane_payload(**overrides) -> dict:
    defaults = {
        "leg_mode": "LTL",
        "dest_zone": DEFAULTS["ZONE"],
        "base_rate_cents": 40000,
        "per_lb_rate_cents": 50,
        "transit_days": 3,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "full_name": DEFAULTS["CUSTOMER_NAME"],
        "destination_zone": DEFAULTS["ZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "service_level": "THRESHOLD",
    }
    defaults.update(overrides)
    return defaults


def create_linehaul_payload(**overrides) -> dict:
    defaults = {
        "planned_arrival_date": DEFAULTS["PLANNED_ARRIVAL"],
        "origin_ship_date": DEFAULTS["ORIGIN_SHIP"],
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-09-12T09:00:00Z",
        "window_end": "2026-09-12T13:00:00Z",
        "crew_id": "CREW-1",
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(**overrides) -> dict:
    defaults = {
        "claimant_role": "CUSTOMER",
        "concealment": "CONCEALED",
    }
    defaults.update(overrides)
    return defaults


def inspect_damage_claim_payload(**overrides) -> dict:
    defaults = {
        "damage_pct": 20,
        "is_structural": False,
        "repair_cost_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_return_authorization_payload(**overrides) -> dict:
    defaults = {
        "reason": "DAMAGE",
    }
    defaults.update(overrides)
    return defaults
