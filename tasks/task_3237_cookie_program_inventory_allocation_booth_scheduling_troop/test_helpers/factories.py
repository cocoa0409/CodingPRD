"""Payload factories — one per entity, input fields only."""

SEASON_OPENS = "2027-01-01T00:00:00Z"
SEASON_CLOSES = "2027-02-01T00:00:00Z"

_season_seq = 0
_troop_seq = 0


def _next_season_code() -> str:
    global _season_seq
    _season_seq += 1
    return f"COOKIE-{_season_seq:04d}"


def _next_troop_number() -> str:
    global _troop_seq
    _troop_seq += 1
    return f"T-{_troop_seq:03d}"


def create_season_payload(**overrides) -> dict:
    defaults = {
        "code": _next_season_code(),
        "name": "Test Season",
        "ordering_opens_at": SEASON_OPENS,
        "ordering_closes_at": SEASON_CLOSES,
    }
    defaults.update(overrides)
    return defaults


def create_troop_payload(**overrides) -> dict:
    defaults = {
        "troop_number": _next_troop_number(),
        "name": "Test Troop",
        "service_unit": "SU-1",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "variety_code": "TM",
        "name": "Thin Mints",
        "unit_price_cents": 600,
        "troop_proceeds_cents": 100,
        "allergen_tags": [],
        "packages_per_case": 1,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(troop_id: str, **overrides) -> dict:
    defaults = {"troop_id": troop_id}
    defaults.update(overrides)
    return defaults


def create_order_payload(troop_id: str, kind: str = "INITIAL", **overrides) -> dict:
    defaults = {"troop_id": troop_id, "kind": kind}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id: str, package_qty: int, **overrides) -> dict:
    defaults = {"product_id": product_id, "package_qty": package_qty}
    defaults.update(overrides)
    return defaults


def create_site_payload(expected_season_version: int, **overrides) -> dict:
    defaults = {
        "name": "Depot 1",
        "address": "1 Depot Way",
        "capacity_units": 10000,
        "expected_season_version": expected_season_version,
    }
    defaults.update(overrides)
    return defaults


def create_baker_po_payload(product_id: str, quantity: int, delivery_site_id: str, **overrides) -> dict:
    defaults = {
        "baker_name": "ABC",
        "product_id": product_id,
        "quantity": quantity,
        "delivery_site_id": delivery_site_id,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_payload(season_id: str, product_id: str, package_qty: int, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "product_id": product_id,
        "package_qty": package_qty,
    }
    defaults.update(overrides)
    return defaults


def create_booth_location_payload(**overrides) -> dict:
    defaults = {
        "host_business_name": "Grocer Co",
        "address": "9 Main St",
        "host_permission_granted": True,
    }
    defaults.update(overrides)
    return defaults


def create_booth_slot_payload(location_id: str, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "start_at": "2027-02-10T14:00:00Z",
        "end_at": "2027-02-10T16:00:00Z",
        "capacity_troops": 1,
    }
    defaults.update(overrides)
    return defaults


def create_booth_request_payload(troop_id: str, mode: str = "FIRST_COME", **overrides) -> dict:
    defaults = {"troop_id": troop_id, "mode": mode}
    defaults.update(overrides)
    return defaults


def create_digital_order_payload(
    troop_id: str, items: list, fulfillment_type: str = "SHIPPED", **overrides
) -> dict:
    defaults = {
        "troop_id": troop_id,
        "customer_email": "customer@example.com",
        "fulfillment_type": fulfillment_type,
        "items": items,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "participant_name": "Scout A",
        "parent_name": "Parent A",
        "signed_responsibility": True,
        "assigned_packages": 0,
        "paid_amount_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "reason": "allergen mislabel",
        "effective_at": "2027-01-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
