"""Payload factories — one per creatable resource, input fields only.

Every factory takes **overrides so tests can pin exactly the values an
assertion depends on. Identifiers (codes, emails, article numbers) are
randomized per call because several are unique across the database.
"""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_store_payload(**overrides) -> dict:
    # low_stock_threshold is optional per the PRD (defaults server-side to 5);
    # it is only sent when a caller overrides it.
    defaults = {
        "name": f"Store {_n()}",
        "code": f"ST-{_n():04d}",
    }
    defaults.update(overrides)
    return defaults


def create_article_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "article_number": f"ART-{n:05d}",
        "name": f"Article {n}",
        "category": "ACCESSORY",
        "pick_policy": "SELF_SERVE",
        "price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_carton_payload(**overrides) -> dict:
    defaults = {
        "carton_seq": 1,
        "aisle": "01",
        "bin": "01",
        "weight_kg": 5,
        "volume_m3": 0.05,
    }
    defaults.update(overrides)
    return defaults


def create_bin_stock_payload(**overrides) -> dict:
    defaults = {
        "store_id": None,
        "carton_id": None,
        "on_hand": 0,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "email": f"customer{n}@example.com",
        "full_name": f"Customer {n}",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {"store_id": None}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {"article_id": None, "qty": 1}
    defaults.update(overrides)
    return defaults


def checkout_payload(**overrides) -> dict:
    return dict(overrides)


def create_reservation_payload(**overrides) -> dict:
    defaults = {"store_id": None, "article_id": None, "qty": 1}
    defaults.update(overrides)
    return defaults


def create_delivery_slot_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "store_id": None,
        "service_date": "2026-09-10",
        "vehicle_id": f"VAN-{n}",
        "zone": "ZONE_A",
        "capacity_weight_kg": 100,
        "capacity_volume_m3": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_booking_payload(**overrides) -> dict:
    defaults = {
        "slot_id": None,
        "access_type": "ELEVATOR",
        "floor": 1,
        "expected_slot_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_assembly_standard_payload(**overrides) -> dict:
    defaults = {"article_id": None, "minutes_per_unit": 30}
    defaults.update(overrides)
    return defaults


def create_assembly_job_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "provider_id": f"CREW-{n}",
        "window_start": "2026-09-10T10:00:00Z",
        "window_end": "2026-09-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_spare_part_claim_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "article_id": None,
        "part_number": f"P-{n}",
        "part_value_cents": 100,
        "reason": "part missing from the box",
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(**overrides) -> dict:
    return dict(overrides)


def create_return_line_payload(**overrides) -> dict:
    defaults = {
        "article_id": None,
        "qty": 1,
        "assembly_state": "UNOPENED",
    }
    defaults.update(overrides)
    return defaults
