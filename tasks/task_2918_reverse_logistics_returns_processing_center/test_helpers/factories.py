"""Request-payload builders for every write endpoint.

Monetary amounts are always emitted as JSON numbers (integer counts of cents),
percentages as JSON numbers, and instant fields as full ISO-8601 UTC instants —
never date-only strings and never money-as-string.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    BAY_TYPE_GENERAL,
    CHANNEL_TYPE_AUCTION,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
    HAZARD_NONE,
    OWNERSHIP_CLIENT_OWNED,
    REASON_DEFECTIVE,
    SL_STANDARD,
    STANDARD_EXPIRES_AT,
    STANDARD_ORDER_PLACED_AT,
)


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is None so optional fields stay genuinely absent."""
    return {k: v for k, v in payload.items() if v is not None}


# ─── Configuration surface ──────────────────────────────────────────────


def client_payload(
    name: str = "Northwind Retail",
    client_code: str = "NWR001",
    service_level: str = SL_STANDARD,
    inventory_ownership: str = OWNERSHIP_CLIENT_OWNED,
    restock_grade_floor: Optional[str] = None,
    refund_hold_hours: Optional[int] = None,
    liquidation_floor_pct: Optional[float] = None,
    fraud_tolerance_cents: Optional[int] = None,
    donation_allowed: Optional[bool] = None,
    destroy_requires_dual_signoff: Optional[bool] = None,
    max_refund_exposure_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "client_code": client_code,
        "service_level": service_level,
        "inventory_ownership": inventory_ownership,
        "restock_grade_floor": restock_grade_floor,
        "refund_hold_hours": refund_hold_hours,
        "liquidation_floor_pct": liquidation_floor_pct,
        "fraud_tolerance_cents": fraud_tolerance_cents,
        "donation_allowed": donation_allowed,
        "destroy_requires_dual_signoff": destroy_requires_dual_signoff,
        "max_refund_exposure_cents": max_refund_exposure_cents,
    }
    payload.update(extra)
    return _prune(payload)


def catalog_item_payload(
    client_id: str,
    sku: str = "WIDGET-1",
    description: str = "Cordless widget",
    declared_value_cents: int = 20000,
    unit_weight_grams: int = 1200,
    serialized: bool = False,
    refurb_eligible: bool = False,
    secondary_market_floor_cents: int = 0,
    hazard_class: Optional[str] = None,
    regulated_flag: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "sku": sku,
        "description": description,
        "declared_value_cents": declared_value_cents,
        "unit_weight_grams": unit_weight_grams,
        "serialized": serialized,
        "refurb_eligible": refurb_eligible,
        "secondary_market_floor_cents": secondary_market_floor_cents,
        "hazard_class": hazard_class,
        "regulated_flag": regulated_flag,
    }
    payload.update(extra)
    return _prune(payload)


def processing_bay_payload(
    bay_code: str = "BAY-G1",
    bay_type: str = BAY_TYPE_GENERAL,
    buffer_minutes: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "bay_code": bay_code,
        "bay_type": bay_type,
        "buffer_minutes": buffer_minutes,
    }
    payload.update(extra)
    return _prune(payload)


def channel_payload(
    name: str = "Alpha Auctions",
    channel_code: str = "AUC1",
    channel_type: str = CHANNEL_TYPE_AUCTION,
    accepted_grades: Optional[List[str]] = None,
    fee_pct: float = 0.12,
    hazard_certified: bool = False,
    recall_certified: bool = False,
    min_lot_value_cents: int = 0,
    concurrent_lot_capacity: int = 5,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "name": name,
        "channel_code": channel_code,
        "channel_type": channel_type,
        "accepted_grades": accepted_grades
        if accepted_grades is not None
        else [GRADE_A, GRADE_B, GRADE_C, GRADE_D],
        "fee_pct": fee_pct,
        "hazard_certified": hazard_certified,
        "recall_certified": recall_certified,
        "min_lot_value_cents": min_lot_value_cents,
        "concurrent_lot_capacity": concurrent_lot_capacity,
    }
    payload.update(extra)
    return _prune(payload)


# ─── Authorizations ─────────────────────────────────────────────────────


def rma_payload(
    client_id: str,
    order_reference: str = "SO-1001",
    customer_reference: str = "CUST-1",
    order_placed_at: str = STANDARD_ORDER_PLACED_AT,
    expires_at: str = STANDARD_EXPIRES_AT,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "client_id": client_id,
        "order_reference": order_reference,
        "customer_reference": customer_reference,
        "order_placed_at": order_placed_at,
        "expires_at": expires_at,
    }
    payload.update(extra)
    return _prune(payload)


def rma_line_payload(
    catalog_item_id: str,
    authorized_quantity: int = 1,
    reason_code: str = REASON_DEFECTIVE,
    declared_serial: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "catalog_item_id": catalog_item_id,
        "authorized_quantity": authorized_quantity,
        "reason_code": reason_code,
        "declared_serial": declared_serial,
    }
    payload.update(extra)
    return _prune(payload)


def reissue_payload(
    expected_rma_version: int, expires_at: str = STANDARD_EXPIRES_AT, **extra: Any
) -> Dict[str, Any]:
    payload = {
        "expected_rma_version": expected_rma_version,
        "expires_at": expires_at,
    }
    payload.update(extra)
    return _prune(payload)


# ─── Dock ───────────────────────────────────────────────────────────────


def receipt_payload(
    rma_id: str,
    tracking_reference: str = "TRK-1",
    gross_weight_grams: int = 1400,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "rma_id": rma_id,
        "tracking_reference": tracking_reference,
        "gross_weight_grams": gross_weight_grams,
    }
    payload.update(extra)
    return _prune(payload)


def receipt_line_payload(
    rma_line_id: str,
    quantity: int = 1,
    reason_code: str = REASON_DEFECTIVE,
    scanned_serial: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "rma_line_id": rma_line_id,
        "quantity": quantity,
        "reason_code": reason_code,
        "scanned_serial": scanned_serial,
    }
    payload.update(extra)
    return _prune(payload)


# ─── Return-line actions ────────────────────────────────────────────────


def quarantine_payload(
    bay_id: str,
    quarantine_start_at: str,
    quarantine_end_at: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "bay_id": bay_id,
        "quarantine_start_at": quarantine_start_at,
        "quarantine_end_at": quarantine_end_at,
    }
    payload.update(extra)
    return _prune(payload)


def grade_payload(condition_grade: str = GRADE_C, **extra: Any) -> Dict[str, Any]:
    payload = {"condition_grade": condition_grade}
    payload.update(extra)
    return _prune(payload)


def override_payload(
    disposition: str, override_reason: str = "Supervisor review", **extra: Any
) -> Dict[str, Any]:
    payload = {"disposition": disposition, "override_reason": override_reason}
    payload.update(extra)
    return _prune(payload)


def clear_fraud_hold_payload(
    resolution_note: str = "Manual review cleared the flag", **extra: Any
) -> Dict[str, Any]:
    payload = {"resolution_note": resolution_note}
    payload.update(extra)
    return _prune(payload)


def deny_refund_payload(
    denial_reason: str = "Customer withdrew the claim", **extra: Any
) -> Dict[str, Any]:
    payload = {"denial_reason": denial_reason}
    payload.update(extra)
    return _prune(payload)


def reverse_refund_payload(
    reversal_memo: str = "Chargeback recovered", **extra: Any
) -> Dict[str, Any]:
    payload = {"reversal_memo": reversal_memo}
    payload.update(extra)
    return _prune(payload)


# ─── Refurbishment ──────────────────────────────────────────────────────


def work_order_payload(return_line_id: str, **extra: Any) -> Dict[str, Any]:
    payload = {"return_line_id": return_line_id}
    payload.update(extra)
    return _prune(payload)


def start_test_payload(
    bay_id: str, test_window_start_at: str, test_window_end_at: str, **extra: Any
) -> Dict[str, Any]:
    payload = {
        "bay_id": bay_id,
        "test_window_start_at": test_window_start_at,
        "test_window_end_at": test_window_end_at,
    }
    payload.update(extra)
    return _prune(payload)


def test_result_payload(
    result: str,
    labor_minutes: int = 10,
    parts_cost_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "result": result,
        "labor_minutes": labor_minutes,
        "parts_cost_cents": parts_cost_cents,
    }
    payload.update(extra)
    return _prune(payload)


def repackage_payload(
    packaging_cost_cents: int = 0, resulting_grade: str = GRADE_B, **extra: Any
) -> Dict[str, Any]:
    payload = {
        "packaging_cost_cents": packaging_cost_cents,
        "resulting_grade": resulting_grade,
    }
    payload.update(extra)
    return _prune(payload)


def abandon_payload(
    abandon_reason: str = "Parts unavailable", **extra: Any
) -> Dict[str, Any]:
    payload = {"abandon_reason": abandon_reason}
    payload.update(extra)
    return _prune(payload)


# ─── Disposition orders and feedback ────────────────────────────────────


def disposition_order_payload(
    return_line_id: str,
    expected_return_line_version: int,
    channel_id: Optional[str] = None,
    disposition: Optional[str] = None,
    quantity: Optional[int] = None,
    channel_window_start_at: Optional[str] = None,
    channel_window_end_at: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "return_line_id": return_line_id,
        "expected_return_line_version": expected_return_line_version,
        "channel_id": channel_id,
        "disposition": disposition,
        "quantity": quantity,
        "channel_window_start_at": channel_window_start_at,
        "channel_window_end_at": channel_window_end_at,
    }
    payload.update(extra)
    return _prune(payload)


def execute_payload(
    realized_unit_price_cents: Optional[int] = None, **extra: Any
) -> Dict[str, Any]:
    payload = {"realized_unit_price_cents": realized_unit_price_cents}
    payload.update(extra)
    return _prune(payload)


def cancel_payload(
    cancel_reason: str = "Buyer withdrew", **extra: Any
) -> Dict[str, Any]:
    payload = {"cancel_reason": cancel_reason}
    payload.update(extra)
    return _prune(payload)


def pricing_feedback_payload(
    disposition_order_id: str,
    channel_id: str,
    realized_price_cents: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "disposition_order_id": disposition_order_id,
        "channel_id": channel_id,
        "realized_price_cents": realized_price_cents,
    }
    payload.update(extra)
    return _prune(payload)
