"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "STORE_NAME": "Flagship",
    "ZONE_CODES": ["941"],
    "TEAM_ID": "T1",
    "WINDOW_START": "2026-09-02T08:00:00Z",
    "WINDOW_END": "2026-09-02T12:00:00Z",
    "CAPACITY_SLOTS": 4,
    "MATTRESS_PRICE": 240000,
    "FIRMWARE": "1.0",
}


def create_store_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["STORE_NAME"],
        "zone_codes": list(DEFAULTS["ZONE_CODES"]),
    }
    defaults.update(overrides)
    return defaults


def create_product_model_payload(**overrides) -> dict:
    defaults = {
        "sku": "MAT-1",
        "name": "Mattress One",
        "category": "MATTRESS",
        "price_cents": DEFAULTS["MATTRESS_PRICE"],
        "replacement_part_price_cents": 0,
        "warranty_months": 120,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(home_store_id, **overrides) -> dict:
    defaults = {
        "home_store_id": home_store_id,
        "email": "a@x.com",
        "full_name": "Ann A",
    }
    defaults.update(overrides)
    return defaults


def create_fit_assessment_payload(customer_id, store_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "store_id": store_id,
        "sleep_position": "BACK",
        "weight_band": "BAND_130_230",
        "partner_sleeper": False,
        "preferred_feel": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, fit_assessment_id, line_items=None,
                         **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "fit_assessment_id": fit_assessment_id,
        "line_items": line_items if line_items is not None
        else [{"sku": "MAT-1", "qty": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_window_payload(store_id, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "team_id": DEFAULTS["TEAM_ID"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
        "capacity_slots": DEFAULTS["CAPACITY_SLOTS"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_visit_payload(order_id, delivery_window_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "delivery_window_id": delivery_window_id,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "kind": "BASE",
        "serial_number": "SN-1",
        "firmware_version": DEFAULTS["FIRMWARE"],
    }
    defaults.update(overrides)
    return defaults


def create_sleep_night_payload(**overrides) -> dict:
    defaults = {
        "night_date": "2026-09-01",
        "minutes_asleep": 420,
        "restlessness_events": 10,
        "avg_heart_rate": 64,
    }
    defaults.update(overrides)
    return defaults


def initiate_trial_return_payload(**overrides) -> dict:
    defaults = {
        "reason": "not for me",
        "refund_destination": "ORIGINAL_PAYMENT",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(order_id, device_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "device_id": device_id,
        "component_category": "CHAMBER",
        "proration_variant": "TIME_BASED",
        "description": "failure",
    }
    defaults.update(overrides)
    return defaults


def create_financing_plan_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "offer_type": "ZERO_APR",
        "term_months": 12,
        "apr_bps": 0,
    }
    defaults.update(overrides)
    return defaults
