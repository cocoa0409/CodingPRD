"""Payload factories - one per creatable resource, input fields only.

Every factory accepts ``**overrides`` so a test controls exactly the fields it
cares about and inherits sensible defaults for the rest. System-managed and
computed fields are never offered.
"""

from typing import Any, Dict, List, Optional


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def carrier_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "carrier_name": "Test Carrier",
        "scac_code": "TSTC",
    }
    defaults.update(overrides)
    return defaults


def shipper_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "company_name": "Test Shipper",
    }
    defaults.update(overrides)
    return defaults


def consignee_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "company_name": "Test Consignee",
        "destination_code": "LAX",
    }
    defaults.update(overrides)
    return defaults


def connection_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "channel": "TMS",
        "supported_modes": ["TRUCKLOAD"],
    }
    defaults.update(overrides)
    return defaults


def credentials_payload(credential_ref: str = "vault://test") -> Dict[str, Any]:
    return {"credential_ref": credential_ref}


def begin_testing_payload(
    testing_window_start: str = "2026-09-01T00:00:00Z",
    testing_window_end: str = "2026-09-10T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "testing_window_start": testing_window_start,
        "testing_window_end": testing_window_end,
    }


def suspend_payload(reason: str = "manual audit") -> Dict[str, Any]:
    return {"reason": reason}


def heartbeat_payload(
    reported_at: str = "2026-09-01T00:00:00Z",
    payload_completeness_pct: int = 100,
) -> Dict[str, Any]:
    return {
        "reported_at": reported_at,
        "payload_completeness_pct": payload_completeness_pct,
    }


def purchase_order_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "po_number": "PO-1",
        "destination_code": "LAX",
        "booking_reference": "BK-1",
    }
    defaults.update(overrides)
    return defaults


def facility_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "facility_name": "Test Facility",
        "facility_type": "DESTINATION",
    }
    defaults.update(overrides)
    return defaults


def shipment_payload(
    carrier_id: str,
    connection_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "carrier_id": carrier_id,
        "connection_id": connection_id,
        "mode": "TRUCKLOAD",
        "tracking_reference": "TRK-1",
        "mode_reference": "PRO-1",
        "destination_code": "DAL",
        "planned_departure_at": "2026-09-01T00:00:00Z",
        "planned_arrival_at": "2026-09-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def event_payload(
    event_time: str,
    event_type: str,
    delay_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_time": event_time, "event_type": event_type}
    if delay_minutes is not None:
        payload["delay_minutes"] = delay_minutes
    return payload


def identity_link_payload(
    purchase_order_id: str,
    expected_po_version: int,
) -> Dict[str, Any]:
    return {
        "purchase_order_id": purchase_order_id,
        "expected_po_version": expected_po_version,
    }


def resolve_payload(resolution: str = "FALSE_ALARM") -> Dict[str, Any]:
    return {"resolution": resolution}


def appointment_payload(
    shipment_id: str,
    window_start: str,
    window_end: str,
    expected_facility_version: int,
) -> Dict[str, Any]:
    return {
        "shipment_id": shipment_id,
        "window_start": window_start,
        "window_end": window_end,
        "expected_facility_version": expected_facility_version,
    }


def complete_appointment_payload(
    actual_arrival_at: str,
    actual_departure_at: str,
) -> Dict[str, Any]:
    return {
        "actual_arrival_at": actual_arrival_at,
        "actual_departure_at": actual_departure_at,
    }


def data_share_grant_payload(
    grantee_type: str,
    grantee_id: str,
    scope: str = "FULL_TRACE",
    effective_from: str = "2026-09-01T00:00:00Z",
    expires_at: str = "2026-12-31T00:00:00Z",
) -> Dict[str, Any]:
    return {
        "grantee_type": grantee_type,
        "grantee_id": grantee_id,
        "scope": scope,
        "effective_from": effective_from,
        "expires_at": expires_at,
    }
