"""Payload factories — one per resource, carrying only client-supplied input fields.

Money is always an integer count of cents (never a string, never a float).
Instants are always full ISO 8601 UTC instants, never date-only strings.
Mileage carries two decimal places and is emitted as a float.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CAR_COST_MODEL,
    STORE_LAT_MICRO,
    STORE_LON_MICRO,
    TEST_POLYGON,
    TEST_ZONE_MODEL,
    ZONE_EFFECTIVE_FROM,
    ZONE_EFFECTIVE_TO,
)

DEFAULTS = {
    "STORE_NUMBER": "7421",
    "STORE_NAME": "Riverside",
    "ADDRESS_LINE1": "1400 Riverbend Way",
    "CUSTOMER_NAME": "Avery Nunes",
    "CUSTOMER_PHONE": "+15135550142",
    "FOOD_SUBTOTAL_CENTS": 2200,
    "TIP_CENTS": 500,
    "DRIVER_NAME": "Dana Ortiz",
    "LICENSE_NUMBER": "DL-1001",
    "POLICY_NUMBER": "POL-88431",
    "LIABILITY_LIMIT_CENTS": 10_000_000,
    "COVERAGE_FROM": "2026-07-01T00:00:00Z",
    "COVERAGE_TO": "2026-12-31T00:00:00Z",
    "ENVELOPE_NUMBER": "ENV-0001",
    "EVIDENCE_NOTE": "The customer insists the driveway is two blocks inside the map.",
    "COMPLAINT_DESCRIPTION": "The pizza arrived cold and very late.",
}


def create_store_payload(**overrides) -> Dict[str, Any]:
    """Store registration. store_number, name and both coordinates are required;
    every policy field is optional and defaults server-side."""
    payload = {
        "store_number": DEFAULTS["STORE_NUMBER"],
        "name": DEFAULTS["STORE_NAME"],
        "latitude_micro": STORE_LAT_MICRO,
        "longitude_micro": STORE_LON_MICRO,
    }
    payload.update(overrides)
    return payload


def update_store_payload(**overrides) -> Dict[str, Any]:
    """Store policy edit — every field is optional, so the caller supplies only
    what changes."""
    return dict(overrides)


def create_zone_version_payload(
    store_id: str, expected_store_version: int, **overrides
) -> Dict[str, Any]:
    """Delivery-area version publication. Defaults to the shared ring and the
    shared drive-time model."""
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "polygon": [dict(v) for v in TEST_POLYGON],
        "effective_from": ZONE_EFFECTIVE_FROM,
        "effective_to": ZONE_EFFECTIVE_TO,
        "expected_store_version": expected_store_version,
    }
    payload.update(TEST_ZONE_MODEL)
    payload.update(overrides)
    return payload


def polygon_from_pairs(pairs: List[tuple]) -> List[Dict[str, int]]:
    """Build a polygon ring from (latitude_micro, longitude_micro) pairs."""
    return [{"latitude_micro": lat, "longitude_micro": lon} for lat, lon in pairs]


def create_service_address_payload(
    store_id: str, latitude_micro: int, longitude_micro: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "line1": DEFAULTS["ADDRESS_LINE1"],
        "latitude_micro": latitude_micro,
        "longitude_micro": longitude_micro,
    }
    payload.update(overrides)
    return payload


def create_address_dispute_payload(service_address_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "service_address_id": service_address_id,
        "claimed_state": "IN_ZONE",
        "evidence_note": DEFAULTS["EVIDENCE_NOTE"],
    }
    payload.update(overrides)
    return payload


def review_dispute_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def create_driver_payload(store_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "full_name": DEFAULTS["DRIVER_NAME"],
        "license_number": DEFAULTS["LICENSE_NUMBER"],
        "vehicle_class": "CAR",
    }
    payload.update(overrides)
    return payload


def create_mvr_check_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "result": "CLEAR",
        "violation_points": 0,
        "checked_on": "2026-08-01T08:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_insurance_verification_payload(
    expected_driver_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "policy_number": DEFAULTS["POLICY_NUMBER"],
        "coverage_from": DEFAULTS["COVERAGE_FROM"],
        "coverage_to": DEFAULTS["COVERAGE_TO"],
        "liability_limit_cents": DEFAULTS["LIABILITY_LIMIT_CENTS"],
        "expected_driver_version": expected_driver_version,
    }
    payload.update(overrides)
    return payload


def qualification_decision_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def create_vehicle_cost_model_payload(store_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"store_id": store_id}
    payload.update(CAR_COST_MODEL)
    payload.update(overrides)
    return payload


def create_safe_drop_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "amount_cents": int(amount_cents),
        "envelope_number": DEFAULTS["ENVELOPE_NUMBER"],
    }
    payload.update(overrides)
    return payload


def void_safe_drop_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"voided_reason": "Mis-keyed envelope amount"}
    payload.update(overrides)
    return payload


def create_order_payload(store_id: str, service_address_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_id": store_id,
        "service_address_id": service_address_id,
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "customer_phone": DEFAULTS["CUSTOMER_PHONE"],
        "food_subtotal_cents": DEFAULTS["FOOD_SUBTOTAL_CENTS"],
        "tip_cents": DEFAULTS["TIP_CENTS"],
        "payment_method": "CARD",
    }
    payload.update(overrides)
    return payload


def zone_decision_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def disclose_fee_payload(
    disclosed_fee_cents: int, disclosed_tip_cents: int, driver_tip_notice_given: bool = True
) -> Dict[str, Any]:
    return {
        "disclosed_fee_cents": int(disclosed_fee_cents),
        "disclosed_tip_cents": int(disclosed_tip_cents),
        "driver_tip_notice_given": bool(driver_tip_notice_given),
    }


def production_payload(action: str) -> Dict[str, Any]:
    return {"action": action}


def remake_payload(reason: str = "LATE") -> Dict[str, Any]:
    return {"reason": reason}


def create_dispatch_payload(driver_id: str, planned_depart_at: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "driver_id": driver_id,
        "planned_depart_at": planned_depart_at,
    }
    payload.update(overrides)
    return payload


def create_dispatch_stop_payload(order_id: str, hot_bag_slots: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"order_id": order_id}
    if hot_bag_slots is not None:
        payload["hot_bag_slots"] = int(hot_bag_slots)
    return payload


def door_arrival_payload(
    actual_miles: Optional[float] = None, cash_collected_cents: Optional[int] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if actual_miles is not None:
        payload["actual_miles"] = float(actual_miles)
    if cash_collected_cents is not None:
        payload["cash_collected_cents"] = int(cash_collected_cents)
    return payload


def recall_payload(recalled_reason: str = "Shift ended before the route was built") -> Dict[str, Any]:
    return {"recalled_reason": recalled_reason}


def create_complaint_payload(order_id: str, category: str = "LATE", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "category": category,
        "description": DEFAULTS["COMPLAINT_DESCRIPTION"],
    }
    payload.update(overrides)
    return payload


def resolve_complaint_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload
