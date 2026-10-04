"""Payload factories — one per creatable resource, input fields only.

Free-text fields default to unique values per call so that back-to-back
creations inside one test never collide.
"""

import itertools
from typing import Any, Dict, List, Optional


_counter = itertools.count(1)


def _suffix() -> str:
    return f"{next(_counter):04d}"


def retailer_payload(
    legal_name: Optional[str] = None,
    store_type: str = "BRICK_AND_MORTAR",
    address: Optional[str] = None,
    lat: float = 40.0,
    lng: float = -105.0,
    storefront_proof_url: Optional[str] = None,
    resale_certificate_no: Optional[str] = None,
    referral_code: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    suffix = _suffix()
    payload: Dict[str, Any] = {
        "legal_name": legal_name if legal_name is not None else f"Retailer {suffix}",
        "store_type": store_type,
        "address": address if address is not None else f"{suffix} Main St",
        "lat": lat,
        "lng": lng,
        "storefront_proof_url": (
            storefront_proof_url
            if storefront_proof_url is not None
            else f"https://proof.example/{suffix}"
        ),
        "resale_certificate_no": (
            resale_certificate_no if resale_certificate_no is not None else f"RC-{suffix}"
        ),
    }
    if referral_code is not None:
        payload["referral_code"] = referral_code
    payload.update(overrides)
    return payload


def brand_payload(
    name: Optional[str] = None,
    contact_email: Optional[str] = None,
    min_order_value_cents: int = 1000,
    default_case_pack_size: int = 1,
    lead_time_days: int = 0,
    payout_delay_days: int = 7,
    **overrides,
) -> Dict[str, Any]:
    suffix = _suffix()
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"Brand {suffix}",
        "contact_email": (
            contact_email
            if contact_email is not None
            else f"brand{suffix}@example.com"
        ),
        "min_order_value_cents": min_order_value_cents,
        "default_case_pack_size": default_case_pack_size,
        "lead_time_days": lead_time_days,
        "payout_delay_days": payout_delay_days,
    }
    payload.update(overrides)
    return payload


def order_line(sku: str = "S1", unit_price_cents: int = 5000, qty: int = 1,
               **overrides) -> Dict[str, Any]:
    line = {"sku": sku, "unit_price_cents": unit_price_cents, "qty": qty}
    line.update(overrides)
    return line


def order_payload(retailer_id: str, brand_id: str,
                  lines: Optional[List[Dict[str, Any]]] = None,
                  **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "retailer_id": retailer_id,
        "brand_id": brand_id,
        "lines": lines if lines is not None else [order_line()],
    }
    payload.update(overrides)
    return payload


def return_auth_payload(order_id: str, order_line_id: str, qty: int,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_id": order_id,
        "lines": [{"order_line_id": order_line_id, "qty": qty}],
    }
    payload.update(overrides)
    return payload


def exclusivity_grant_payload(
    brand_id: str,
    retailer_id: str,
    expected_brand_version: int,
    center_lat: float = 40.0,
    center_lng: float = -105.0,
    radius_km: Optional[float] = None,
    starts_at: str = "2026-08-01T00:00:00Z",
    ends_at: str = "2027-08-01T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_id": brand_id,
        "retailer_id": retailer_id,
        "center_lat": center_lat,
        "center_lng": center_lng,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "expected_brand_version": expected_brand_version,
    }
    if radius_km is not None:
        payload["radius_km"] = radius_km
    payload.update(overrides)
    return payload


def fraud_flag_payload(retailer_id: str, flag_type: str,
                       order_id: Optional[str] = None, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"retailer_id": retailer_id, "flag_type": flag_type}
    if order_id is not None:
        payload["order_id"] = order_id
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def payment_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": amount_cents}
