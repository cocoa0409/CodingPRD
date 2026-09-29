"""Payload factories for the parcel billing API.

Each factory returns a complete, valid request body with sensible defaults that
callers override by keyword. Monetary fields are always plain Python ``int``
values in cents so that ``requests`` serialises them as JSON numbers.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    FULL_TIER_TABLE,
    STD_DIM_DIVISOR,
    STD_MIN_CHARGE_CENTS,
    STD_TIER_TABLE,
    ZONE2_RATE_ROWS,
    ZONE5_RATE_ROWS,
)
from .types import Payload, RateRow, TierRow

_tracking_seq = itertools.count(1)
_account_seq = itertools.count(1)
_code_seq = itertools.count(1)


def next_tracking_number(prefix: str = "1Z-T") -> str:
    """A tracking number that is unique within a single test run."""
    return f"{prefix}-{next(_tracking_seq):06d}"


def next_account_number(prefix: str = "SH") -> str:
    """An account number that is unique within a single test run."""
    return f"{prefix}-{next(_account_seq):06d}"


def next_code(prefix: str = "CODE") -> str:
    """A short natural key that is unique within a single test run."""
    return f"{prefix}-{next(_code_seq):04d}"


# ---------------------------------------------------------------------------
# Shipper accounts
# ---------------------------------------------------------------------------
def shipper_account_payload(
    account_number: Optional[str] = None,
    name: str = "Northwind Freight",
    billing_email: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "account_number": account_number or next_account_number(),
        "name": name,
    }
    if billing_email is not None:
        payload["billing_email"] = billing_email
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Service levels
# ---------------------------------------------------------------------------
def service_level_payload(
    code: str = "GROUND",
    name: str = "Ground",
    guarantee_hours: int = 120,
    guaranteed: bool = False,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "code": code,
        "name": name,
        "guarantee_hours": guarantee_hours,
        "guaranteed": guaranteed,
    }
    payload.update(overrides)
    return payload


def express_service_level_payload(**overrides: Any) -> Payload:
    """The guaranteed 24 hour service level used by the guarantee workflows."""
    return service_level_payload(
        code="EXPRESS",
        name="Express 24",
        guarantee_hours=24,
        guaranteed=True,
        **overrides,
    )


def ground_service_level_payload(**overrides: Any) -> Payload:
    """The unguaranteed 120 hour service level."""
    return service_level_payload(
        code="GROUND", name="Ground", guarantee_hours=120, guaranteed=False, **overrides
    )


# ---------------------------------------------------------------------------
# Rate contracts
# ---------------------------------------------------------------------------
def rate_contract_payload(
    shipper_id: str,
    effective_from: str = "2026-01-01",
    effective_to: str = "2026-12-31",
    dim_divisor: int = STD_DIM_DIVISOR,
    min_charge_cents: int = STD_MIN_CHARGE_CENTS,
    rate_table: Optional[List[RateRow]] = None,
    tier_discount_table: Optional[List[TierRow]] = None,
    accessorial_rate_overrides: Optional[Dict[str, int]] = None,
    residential_waived: Optional[bool] = None,
    supersedes_contract_id: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "shipper_id": shipper_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "dim_divisor": dim_divisor,
        "min_charge_cents": min_charge_cents,
        "rate_table": list(rate_table) if rate_table is not None else list(ZONE2_RATE_ROWS),
        "tier_discount_table": (
            list(tier_discount_table)
            if tier_discount_table is not None
            else list(STD_TIER_TABLE)
        ),
    }
    if accessorial_rate_overrides is not None:
        payload["accessorial_rate_overrides"] = dict(accessorial_rate_overrides)
    if residential_waived is not None:
        payload["residential_waived"] = residential_waived
    if supersedes_contract_id is not None:
        payload["supersedes_contract_id"] = supersedes_contract_id
    payload.update(overrides)
    return payload


def multi_zone_rate_contract_payload(shipper_id: str, **overrides: Any) -> Payload:
    """A contract covering zones 2 and 5 with both discount tiers."""
    return rate_contract_payload(
        shipper_id,
        rate_table=list(ZONE2_RATE_ROWS) + list(ZONE5_RATE_ROWS),
        tier_discount_table=list(FULL_TIER_TABLE),
        **overrides,
    )


# ---------------------------------------------------------------------------
# Surcharge windows
# ---------------------------------------------------------------------------
def surcharge_window_payload(
    code: Optional[str] = None,
    kind: str = "DEMAND",
    start_date: str = "2026-08-01",
    end_date: str = "2026-09-01",
    per_package_cents: int = 150,
    oversize_add_cents: Optional[int] = None,
    service_level_id: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "code": code or next_code("WIN"),
        "kind": kind,
        "start_date": start_date,
        "end_date": end_date,
        "per_package_cents": per_package_cents,
    }
    if oversize_add_cents is not None:
        payload["oversize_add_cents"] = oversize_add_cents
    if service_level_id is not None:
        payload["service_level_id"] = service_level_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------
def shipment_payload(
    shipper_id: str,
    service_level_id: str,
    tracking_number: Optional[str] = None,
    zone: int = 2,
    residential_declared: bool = False,
    declared_length_in: float = 12,
    declared_width_in: float = 10,
    declared_height_in: float = 8,
    declared_weight_lbs: float = 6.0,
    delivery_area_class: Optional[str] = None,
    non_conveyable_declared: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "shipper_id": shipper_id,
        "service_level_id": service_level_id,
        "tracking_number": tracking_number or next_tracking_number(),
        "zone": zone,
        "residential_declared": residential_declared,
        "declared_length_in": declared_length_in,
        "declared_width_in": declared_width_in,
        "declared_height_in": declared_height_in,
        "declared_weight_lbs": declared_weight_lbs,
    }
    if delivery_area_class is not None:
        payload["delivery_area_class"] = delivery_area_class
    if non_conveyable_declared is not None:
        payload["non_conveyable_declared"] = non_conveyable_declared
    payload.update(overrides)
    return payload


def scan_payload(
    expected_shipment_version: int,
    scan_source: str = "AUTOMATED_DWS",
    scanned_length_in: float = 12,
    scanned_width_in: float = 10,
    scanned_height_in: float = 8,
    scanned_weight_lbs: float = 6.0,
    non_conveyable_observed: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "scan_source": scan_source,
        "scanned_length_in": scanned_length_in,
        "scanned_width_in": scanned_width_in,
        "scanned_height_in": scanned_height_in,
        "scanned_weight_lbs": scanned_weight_lbs,
        "expected_shipment_version": expected_shipment_version,
    }
    if non_conveyable_observed is not None:
        payload["non_conveyable_observed"] = non_conveyable_observed
    payload.update(overrides)
    return payload


def exception_payload(kind: str, reason: Optional[str] = None, **overrides: Any) -> Payload:
    payload: Payload = {"kind": kind}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def accessorial_payload(
    code: str = "ADDRESS_CORRECTION", reason: Optional[str] = None, **overrides: Any
) -> Payload:
    payload: Payload = {"code": code}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
def invoice_sweep_payload(
    shipper_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
    include_shipment_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "shipper_id": shipper_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    if include_shipment_ids is not None:
        payload["include_shipment_ids"] = list(include_shipment_ids)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Billing adjustments
# ---------------------------------------------------------------------------
def billing_adjustment_payload(
    invoice_line_id: str,
    delta_cents: int,
    expected_invoice_version: int,
    reason: str = "MANUAL",
    note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "invoice_line_id": invoice_line_id,
        "reason": reason,
        "delta_cents": int(delta_cents),
        "expected_invoice_version": expected_invoice_version,
    }
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------
def dispute_payload(
    invoice_line_id: str,
    claim_type: str = "WEIGHT",
    claimed_reason: str = "Billed weight does not match the parcel",
    disputed_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "invoice_line_id": invoice_line_id,
        "claim_type": claim_type,
        "claimed_reason": claimed_reason,
    }
    if disputed_codes is not None:
        payload["disputed_codes"] = list(disputed_codes)
    payload.update(overrides)
    return payload


def evidence_payload(
    item_type: str = "DELIVERY_PHOTO",
    reference: str = "s3://evidence/photo-1.jpg",
    **overrides: Any,
) -> Payload:
    payload: Payload = {"item_type": item_type, "reference": reference}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Guarantee claims
# ---------------------------------------------------------------------------
def guarantee_claim_payload(
    shipment_id: str, claimed_reason: Optional[str] = None, **overrides: Any
) -> Payload:
    payload: Payload = {"shipment_id": shipment_id}
    if claimed_reason is not None:
        payload["claimed_reason"] = claimed_reason
    payload.update(overrides)
    return payload


def guarantee_scan_payload(
    shipper_id: str,
    period_start: str = "2026-08-01",
    period_end: str = "2026-08-31",
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "shipper_id": shipper_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    payload.update(overrides)
    return payload
