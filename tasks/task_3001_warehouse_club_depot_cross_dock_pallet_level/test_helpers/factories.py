"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counters = itertools.count(1)


def _next() -> int:
    return next(_counters)


def _letters(n: int, min_len: int = 2, max_len: int = 4) -> str:
    """Convert a positive int to an uppercase-letters-only code (base 26, A=0).

    Result is between min_len and max_len characters; values wrap modulo
    26**max_len so the code never exceeds max_len. Caller is responsible for
    ensuring distinct codes within a single test.
    """
    n = n % (26 ** max_len)
    chars = []
    while True:
        chars.append(chr(ord("A") + (n % 26)))
        n //= 26
        if n == 0:
            break
    s = "".join(reversed(chars))
    while len(s) < min_len:
        s = "A" + s
    return s


def create_region_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Region {n}",
        "code": _letters(n),
        "avg_member_income_cents": TEST_DEFAULTS["AVG_MEMBER_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Vendor {n}",
        "vendor_code": f"V{(900000 + n) % 1000000:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_club_payload(region_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "region_id": region_id,
        "name": f"Club {n}",
        "club_number": 10000 + n,
        "floor_slot_capacity": TEST_DEFAULTS["CLUB_FLOOR_SLOT_CAPACITY"],
        "member_base": TEST_DEFAULTS["MEMBER_BASE"],
    }
    defaults.update(overrides)
    return defaults


def create_depot_payload(region_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "region_id": region_id,
        "name": f"Depot {n}",
        "dock_count": 2,
        "dock_hours_open": TEST_DEFAULTS["DOCK_HOURS_OPEN"],
        "dock_hours_close": TEST_DEFAULTS["DOCK_HOURS_CLOSE"],
        "slot_length_minutes": TEST_DEFAULTS["SLOT_LENGTH_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_item_payload(vendor_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "vendor_id": vendor_id,
        "sku": f"{(1000000 + n) % 10000000:07d}",
        "description": f"Item {n}",
        "case_pack_qty": TEST_DEFAULTS["CASE_PACK_QTY"],
        "pallet_length_in": TEST_DEFAULTS["PALLET_LENGTH_IN"],
        "pallet_width_in": TEST_DEFAULTS["PALLET_WIDTH_IN"],
        "cases_per_layer": TEST_DEFAULTS["CASES_PER_LAYER"],
        "max_layers": TEST_DEFAULTS["MAX_LAYERS"],
        "item_type": "REGULAR",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(depot_id, vendor_id, delivery_date, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "vendor_id": vendor_id,
        "delivery_date": delivery_date,
        "start_time": "09:00",
        "end_time": "09:30",
        "pallet_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_pallet_payload(appointment_id, item_id, unit_qty, **overrides) -> dict:
    defaults = {
        "appointment_id": appointment_id,
        "item_id": item_id,
        "unit_qty": unit_qty,
    }
    defaults.update(overrides)
    return defaults


def create_cross_dock_run_payload(depot_id, run_date, **overrides) -> dict:
    defaults = {
        "depot_id": depot_id,
        "run_date": run_date,
        "cutoff_time": TEST_DEFAULTS["CUTOFF_TIME"],
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(pallet_id, club_id, expected_cross_dock_run_version, **overrides) -> dict:
    defaults = {
        "pallet_id": pallet_id,
        "club_id": club_id,
        "expected_cross_dock_run_version": expected_cross_dock_run_version,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(club_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "club_id": club_id,
        "membership_number": f"M{(100000000 + n) % 1000000000:09d}",
        "tier": "GOLD_STAR",
    }
    defaults.update(overrides)
    return defaults


def create_purchase_payload(member_id, club_id, item_id, unit_qty, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "club_id": club_id,
        "item_id": item_id,
        "unit_qty": unit_qty,
    }
    defaults.update(overrides)
    return defaults


def create_markdown_decision_payload(expected_item_version, **overrides) -> dict:
    defaults = {
        "decision": "SELL_THROUGH",
        "expected_item_version": expected_item_version,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(member_id, item_id, category, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "item_id": item_id,
        "category": category,
    }
    defaults.update(overrides)
    return defaults


def create_department_sale_payload(club_id, member_id, department, amount_cents, **overrides) -> dict:
    defaults = {
        "club_id": club_id,
        "member_id": member_id,
        "department": department,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults
