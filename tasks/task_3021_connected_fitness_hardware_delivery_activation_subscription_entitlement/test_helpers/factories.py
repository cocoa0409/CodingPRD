"""Payload factories — one per creatable entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = TEST_DEFAULTS


def create_membership_payload(**overrides) -> dict:
    """Body for POST /fitness/memberships."""
    payload = {
        "household_name": DEFAULTS["HOUSEHOLD_NAME"],
        "billing_email": DEFAULTS["BILLING_EMAIL"],
        "plan_tier": DEFAULTS["PLAN_TIER"],
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_household_user_payload(**overrides) -> dict:
    """Body for POST /fitness/memberships/{membershipId}/household-users."""
    payload = {
        "display_name": DEFAULTS["DISPLAY_NAME"],
        "email": "ada@x.com",
        "role": "MEMBER",
    }
    payload.update(overrides)
    return payload


def create_device_payload(**overrides) -> dict:
    """Body for POST /fitness/memberships/{membershipId}/devices."""
    payload = {
        "hardware_sku": DEFAULTS["DEVICE_SKU"],
        "serial": DEFAULTS["DEVICE_SERIAL"],
    }
    payload.update(overrides)
    return payload


def create_hardware_order_payload(device_id=None, **overrides) -> dict:
    """Body for POST /fitness/memberships/{membershipId}/hardware-orders."""
    payload = {
        "hardware_sku": DEFAULTS["DEVICE_SKU"],
        "subtotal_cents": DEFAULTS["HARDWARE_SUBTOTAL_CENTS"],
        "financing_method": "FULL_PAYMENT",
    }
    if device_id is not None:
        payload["device_id"] = device_id
    payload.update(overrides)
    return payload


def create_delivery_appointment_payload(device_id, hardware_order_id,
                                        start_at, end_at, **overrides) -> dict:
    """Body for POST /fitness/delivery-appointments."""
    payload = {
        "device_id": device_id,
        "hardware_order_id": hardware_order_id,
        "start_at": start_at,
        "end_at": end_at,
        "zone": "METRO",
        "technician_crew_code": DEFAULTS["CREW_CODE"],
        "stair_flights": 0,
        "has_elevator": False,
    }
    payload.update(overrides)
    return payload


def create_financing_plan_payload(membership_id, order_id, **overrides) -> dict:
    """Body for POST /fitness/financing-plans."""
    payload = {
        "membership_id": membership_id,
        "order_id": order_id,
        "principal_cents": 119_900,
        "term_months": 12,
        "apr_bps": 900,
    }
    payload.update(overrides)
    return payload


def create_service_order_payload(device_id, **overrides) -> dict:
    """Body for POST /fitness/service-orders."""
    payload = {
        "device_id": device_id,
        "reported_fault_code": "BELT_SLIP",
        "diagnosis_note": "belt abrasion",
    }
    payload.update(overrides)
    return payload


def create_part_payload(**overrides) -> dict:
    """Body for POST /fitness/parts-inventory."""
    payload = {
        "part_code": DEFAULTS["PART_CODE"],
        "compatible_sku": DEFAULTS["DEVICE_SKU"],
        "safety_stock_qty": 2,
        "part_lot_key": DEFAULTS["PART_LOT_KEY"],
    }
    payload.update(overrides)
    return payload


def create_class_session_payload(**overrides) -> dict:
    """Body for POST /fitness/class-sessions."""
    payload = {
        "title": "Threshold Ride",
        "instructor_name": DEFAULTS["INSTRUCTOR_NAME"],
        "discipline": "CYCLING",
        "delivery_mode": "ON_DEMAND",
        "starts_at": "2026-09-10T09:00:00Z",
        "ends_at": "2026-09-10T11:00:00Z",
        "capacity": 100,
        "license_starts_at": "2026-09-10T00:00:00Z",
        "license_ends_at": "2026-09-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_class_enrollment_payload(class_session_id, device_id,
                                    enroller_user_id, **overrides) -> dict:
    """Body for POST /fitness/class-enrollments."""
    payload = {
        "class_session_id": class_session_id,
        "device_id": device_id,
        "enroller_user_id": enroller_user_id,
    }
    payload.update(overrides)
    return payload


def create_refurb_batch_payload(source_device_id, **overrides) -> dict:
    """Body for POST /fitness/refurb-batches."""
    payload = {
        "source_device_id": source_device_id,
        "certification_grade": "A",
        "performance_resale_enabled": True,
    }
    payload.update(overrides)
    return payload


def create_delivery_quote_payload(**overrides) -> dict:
    """Body for POST /fitness/delivery-quotes."""
    payload = {
        "hardware_sku": DEFAULTS["DEVICE_SKU"],
        "zone": "METRO",
        "stair_flights": 0,
        "has_elevator": False,
        "assembly_required": False,
    }
    payload.update(overrides)
    return payload


def create_clock_payload(current_utc: str) -> dict:
    """Body for POST /fitness/_clock/set_current_utc."""
    return {"current_utc": current_utc}