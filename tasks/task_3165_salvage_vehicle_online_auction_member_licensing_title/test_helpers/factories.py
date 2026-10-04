"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counters = itertools.count(1)


def _next() -> int:
    return next(_counters)


def create_yard_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Yard {n}",
        "state_code": TEST_DEFAULTS["YARD_STATE"],
        "daily_storage_rate_cents": TEST_DEFAULTS["DAILY_STORAGE_RATE_CENTS"],
        "free_storage_days": TEST_DEFAULTS["FREE_STORAGE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_seller_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Insurer {n}",
        "seller_type": "INSURER",
        "fee_schedule": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "email": f"buyer{n}@example.com",
        "full_name": f"Buyer {n}",
        "home_state": "CA",
        "tier": "BASIC",
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "state_code": TEST_DEFAULTS["YARD_STATE"],
        "license_type": "DEALER",
        "expires_on": "2027-12-31",
    }
    defaults.update(overrides)
    return defaults


_VIN_POOL = [
    TEST_DEFAULTS["VIN_1"],
    TEST_DEFAULTS["VIN_2"],
    TEST_DEFAULTS["VIN_3"],
    TEST_DEFAULTS["VIN_4"],
    TEST_DEFAULTS["VIN_5"],
]


def _vin(n: int) -> str:
    """Deterministic unique 17-char VIN per counter value."""
    if n <= len(_VIN_POOL):
        return _VIN_POOL[n - 1]
    # Synthesize additional unique 17-char VINs beyond the pool.
    suffix = f"{n:06d}"
    return f"1HGCM82633A{suffix}"[:17].ljust(17, "0")


def create_vehicle_payload(seller_id, yard_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "seller_id": seller_id,
        "yard_id": yard_id,
        "vin": _vin(n),
        "year": 2019,
        "make": "Honda",
        "model": "Accord",
        "lot_type": "STANDARD",
        "reserve_price_cents": 0,
        "sale_type": "PURE",
        "odometer_reading": 50000,
        "damage_codes": ["FRONT"],
    }
    defaults.update(overrides)
    return defaults


def create_title_payload(**overrides) -> dict:
    defaults = {"title_type": "SALVAGE"}
    defaults.update(overrides)
    return defaults


def create_condition_payload(**overrides) -> dict:
    defaults = {
        "primary_damage": "FRONT",
        "run_and_drive_status": "RUN_AND_DRIVE",
    }
    defaults.update(overrides)
    return defaults


def create_image_payload(**overrides) -> dict:
    n = _next()
    defaults = {"image_url": f"https://img.example/{n}"}
    defaults.update(overrides)
    return defaults


def create_auction_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Auction {n}",
        "scheduled_start": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_auction_item_payload(vehicle_id, **overrides) -> dict:
    defaults = {"vehicle_id": vehicle_id}
    defaults.update(overrides)
    return defaults


def create_bid_payload(auction_item_id, amount_cents, **overrides) -> dict:
    defaults = {
        "auction_item_id": auction_item_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_gate_pass_payload(**overrides) -> dict:
    defaults = {
        "slot_start": "2026-09-02T14:00:00Z",
        "slot_end": "2026-09-02T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_export_document_payload(**overrides) -> dict:
    defaults = {
        "document_type": "BILL_OF_LADING",
        "destination_country": "DE",
    }
    defaults.update(overrides)
    return defaults
