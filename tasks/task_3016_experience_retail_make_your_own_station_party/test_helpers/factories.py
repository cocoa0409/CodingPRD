"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "STORE_NAME": "Test Store",
    "PARTY_ROOM_COUNT": 2,
    "MODEL_NAME": "Test Bear",
    "MODEL_BASE_PRICE_CENTS": 2000,
    "MODEL_STUFFING_GRAMS": 100,
    "STATION_CAPACITY": 4,
    "FIBER_INITIAL_QTY": 100000,
    "SOUND_CHIP_INITIAL_QTY": 100,
    "GIFT_CARD_BALANCE_CENTS": 10000,
    "PARTY_GUEST_COUNT": 6,
    "PARTY_START": "2026-10-10T18:00:00Z",
}

_customer_seq = {"n": 0}
_sku_seq = {"n": 0}
_code_seq = {"n": 0}


def _next(seq):
    seq["n"] += 1
    return seq["n"]


def create_store_payload(**overrides):
    payload = {
        "name": DEFAULTS["STORE_NAME"],
        "party_room_count": DEFAULTS["PARTY_ROOM_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides):
    n = _next(_customer_seq)
    payload = {
        "email": f"customer{n}@example.com",
        "full_name": f"Customer {n}",
    }
    payload.update(overrides)
    return payload


def create_staff_payload(store_id, role_title="PARTY_HOST", **overrides):
    payload = {
        "store_id": store_id,
        "display_name": "Staff Member",
        "role_title": role_title,
    }
    payload.update(overrides)
    return payload


def create_station_payload(store_id, station_type, **overrides):
    payload = {
        "store_id": store_id,
        "station_type": station_type,
        "capacity": DEFAULTS["STATION_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_plush_model_payload(**overrides):
    n = _next(_sku_seq)
    payload = {
        "name": DEFAULTS["MODEL_NAME"],
        "sku": f"SKU-{n:04d}",
        "base_price_cents": DEFAULTS["MODEL_BASE_PRICE_CENTS"],
        "is_licensed": False,
        "required_stuffing_grams": DEFAULTS["MODEL_STUFFING_GRAMS"],
        "sound_chip_compatible": False,
    }
    payload.update(overrides)
    return payload


def create_consumable_payload(store_id, consumable_type, **overrides):
    default_qty = (
        DEFAULTS["FIBER_INITIAL_QTY"]
        if consumable_type == "STUFFING_FIBER"
        else DEFAULTS["SOUND_CHIP_INITIAL_QTY"]
    )
    payload = {
        "store_id": store_id,
        "consumable_type": consumable_type,
        "initial_qty": default_qty,
    }
    payload.update(overrides)
    return payload


def create_collection_drop_payload(plush_model_id, **overrides):
    payload = {
        "name": "Test Drop",
        "plush_model_id": plush_model_id,
        "drop_start": "2026-10-01T00:00:00Z",
        "drop_end": "2026-11-01T00:00:00Z",
        "per_customer_limit": 5,
        "total_units": 10,
    }
    payload.update(overrides)
    return payload


def create_workshop_payload(store_id, customer_id, plush_model_id, **overrides):
    payload = {
        "store_id": store_id,
        "customer_id": customer_id,
        "plush_model_id": plush_model_id,
        "origin_type": "WALK_IN",
    }
    payload.update(overrides)
    return payload


def create_party_payload(store_id, customer_id, **overrides):
    payload = {
        "store_id": store_id,
        "customer_id": customer_id,
        "party_start": DEFAULTS["PARTY_START"],
        "duration_minutes": 120,
        "guest_count": DEFAULTS["PARTY_GUEST_COUNT"],
        "package_tier": "BASIC",
        "staffing_mode": "SELF_GUIDED",
    }
    payload.update(overrides)
    return payload


def create_party_guest_payload(party_reservation_id, **overrides):
    payload = {
        "party_reservation_id": party_reservation_id,
        "guest_name": "Guest",
    }
    payload.update(overrides)
    return payload


def create_build_ship_order_payload(store_id, customer_id, plush_model_id, **overrides):
    payload = {
        "store_id": store_id,
        "customer_id": customer_id,
        "plush_model_id": plush_model_id,
        "sound_chip_requested": False,
        "recipient_name": "Recipient",
    }
    payload.update(overrides)
    return payload


def create_gift_card_payload(**overrides):
    n = _next(_code_seq)
    payload = {
        "code": f"GC-{n:04d}",
        "initial_balance_cents": DEFAULTS["GIFT_CARD_BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_registry_payload(customer_id, **overrides):
    payload = {
        "customer_id": customer_id,
        "name": "Test Registry",
    }
    payload.update(overrides)
    return payload
