"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import DEFAULT_LOGICAL_START

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "email": f"customer{n}@example.com",
        "full_name": f"Test Customer {n}",
        "phone": f"555-{1000 + (n % 9000):04d}",
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(customer_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "customer_id": customer_id,
        "serial_number": f"SN-{n:06d}",
        "model_code": "IPHONE_14",
        "activation_lock_enabled": False,
        "proof_of_purchase_on_file": True,
        "purchase_date": "2025-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_coverage_plan_payload(device_id, **overrides) -> dict:
    defaults = {
        "device_id": device_id,
        "plan_type": "APPLECARE_PLUS",
        "starts_on": "2025-01-01T00:00:00Z",
        "expires_on": "2027-01-01T00:00:00Z",
        "accidental_damage_incident_limit": 2,
        "service_fee_cents": 2900,
    }
    defaults.update(overrides)
    return defaults


def create_service_location_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "location_code": f"LOC-{n:04d}",
        "location_type": "RETAIL_STORE",
        "address": f"{n} Test Ave",
        "supports_same_day_repair": True,
        "supports_express_replacement": False,
        "diagnostic_slot_duration_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_depot_location_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "location_code": f"DEPOT-{n:04d}",
        "location_type": "MAIL_IN_DEPOT",
        "address": f"{n} Depot Rd",
        "supports_same_day_repair": False,
        "supports_express_replacement": False,
        "diagnostic_slot_duration_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(location_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "location_id": location_id,
        "full_name": f"Tech {n}",
        "certification_level": "ADVANCED",
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    n = _n()
    defaults = {
        "part_number": f"PN-{n:06d}",
        "model_code": "IPHONE_14",
        "part_category": "DISPLAY",
        "is_whole_unit_replacement": False,
    }
    defaults.update(overrides)
    return defaults


def create_part_inventory_payload(location_id, part_id, **overrides) -> dict:
    defaults = {
        "location_id": location_id,
        "part_id": part_id,
        "on_hand_quantity": 5,
        "express_replacement_quantity": 0,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(
    customer_id, device_id, location_id, technician_id, device_version, **overrides
) -> dict:
    defaults = {
        "customer_id": customer_id,
        "device_id": device_id,
        "location_id": location_id,
        "technician_id": technician_id,
        "slot_start": "2026-09-02T10:00:00Z",
        "slot_end": "2026-09-02T10:30:00Z",
        "issue_category": "SOFTWARE",
        "expected_device_version": device_version,
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(
    appointment_id, device_id, customer_id, origin_location_id, device_version,
    **overrides,
) -> dict:
    issue = overrides.get("issue_category", "SOFTWARE")
    defaults = {
        "appointment_id": appointment_id,
        "device_id": device_id,
        "customer_id": customer_id,
        "origin_location_id": origin_location_id,
        "issue_category": issue,
        "is_accidental_damage": False,
        "data_backup_acknowledged": True,
        "privacy_wipe_consent": True,
        "expected_device_version": device_version,
    }
    defaults.update(overrides)
    return defaults


def create_coverage_entitlement_payload(repair_order_id, coverage_plan_id, **overrides) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "coverage_plan_id": coverage_plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_security_verification_payload(repair_order_id, **overrides) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "verification_type": "ACTIVATION_LOCK_REMOVAL",
    }
    defaults.update(overrides)
    return defaults


def create_repair_shipment_payload(
    repair_order_id, from_location_id, to_location_id, **overrides
) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "shipment_type": "STORE_TO_DEPOT",
    }
    defaults.update(overrides)
    return defaults


def create_quality_follow_up_payload(repair_order_id, customer_id, **overrides) -> dict:
    defaults = {
        "repair_order_id": repair_order_id,
        "customer_id": customer_id,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601=DEFAULT_LOGICAL_START) -> dict:
    return {"to_iso8601": to_iso8601}


__all__ = [name for name in dir() if name.startswith("create_") or name == "set_clock_payload"]
