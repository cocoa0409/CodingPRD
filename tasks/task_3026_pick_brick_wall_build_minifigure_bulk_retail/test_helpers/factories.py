"""Payload factories — one per resource, input fields only."""
import itertools

_counter = itertools.count(1)


def next_code(prefix: str) -> str:
    """Globally unique suffix so two tests sharing a process never collide."""
    return f"{prefix}{next(_counter):05d}"


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_code": next_code("LEGO-"),
        "display_name": "Brick Yard Test",
        "wall_bin_capacity_grams": 2000,
        "event_capacity_units": 40,
        "checklist_required": True,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(home_store_id: str, **overrides) -> dict:
    defaults = {
        "email": f"member.{next(_counter)}@example.com",
        "display_name": "Test Member",
        "home_store_id": home_store_id,
    }
    defaults.update(overrides)
    return defaults


def create_element_payload(**overrides) -> dict:
    defaults = {
        "element_code": next_code("9"),
        "element_name": "Brick 2x4",
        "theme": "Town",
        "unit_mass_grams": 2.5,
        "cost_basis_cents": 6,
        "make_ready_lead_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_wall_bin_payload(store_id: str, element_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "element_id": element_id,
        "bin_label": next_code("BIN"),
        "bin_capacity_grams": 1000,
        "bin_mass_grams": 600,
    }
    defaults.update(overrides)
    return defaults


def create_fusion_order_payload(store_id: str, member_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "member_id": member_id,
        "cup_size": "LARGE",
        "pricing_model": "CUP_FILL",
        "declared_mass_grams": 400,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(wall_bin_id: str, allocation_grams: int, **overrides) -> dict:
    defaults = {
        "wall_bin_id": wall_bin_id,
        "allocation_grams": allocation_grams,
    }
    defaults.update(overrides)
    return defaults


def create_exit_inspection_payload(fusion_order_id: str, fusion_order_version: int,
                                   **overrides) -> dict:
    defaults = {
        "fusion_order_id": fusion_order_id,
        "outcome": "CLEAR",
        "checklist_result": "COMPLETED",
        "reviewed_by_user_id": "assoc-test",
        "expected_fusion_order_version": fusion_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_minifigure_build_payload(store_id: str, member_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "member_id": member_id,
    }
    defaults.update(overrides)
    return defaults


def create_theme_launch_payload(**overrides) -> dict:
    defaults = {
        "theme": "Town",
        "exclusive_set_sku": next_code("LEGO-SET-"),
        "allocated_exclusive_units": 10,
        "exclusive_set_unit_price_cents": 1400,
        "per_customer_limit": 1,
        "days_from_default_clock": 3,
        "vip_early_days_before_release": 1,
    }
    defaults.update(overrides)
    return defaults


def create_launch_queue_payload(member_id: str, launch_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "launch_id": launch_id,
        "priority_class": "GENERAL",
        "requested_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_store_event_payload(store_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "event_kind": "BUILD_EVENT",
        "title": "Weekend Build",
        "capacity_units": 1,
        "days_from_default_clock": 1,
        "duration_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(store_event_id: str, member_id: str, **overrides) -> dict:
    defaults = {
        "store_event_id": store_event_id,
        "member_id": member_id,
        "seats": 1,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_request_payload(store_id: str, member_id: str, element_id: str,
                                       member_version: int, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "member_id": member_id,
        "element_id": element_id,
        "quantity_missing": 1,
        "proof_of_purchase_supplied": False,
        "window_days": 30,
        "expected_member_version": member_version,
    }
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "entry_kind": "MANUAL_ADJUSTMENT",
        "points_delta": 100,
        "reason": "Test adjustment",
    }
    defaults.update(overrides)
    return defaults