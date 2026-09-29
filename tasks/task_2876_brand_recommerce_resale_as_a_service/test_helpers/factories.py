"""Payload factories — one per entity, input fields only.

Every money field is a JSON integer of minor units and every mass field a JSON
integer of grams, exactly as PRD §2.5 requires. Every instant is a full
ISO-8601 UTC instant, never a date-only literal.
"""

from typing import Any, Dict, Optional

from .constants import (
    CHANNEL_RESALE_MP,
    CREDIT_POLICY_CORE,
    GRADE_POLICY_OUTERWEAR_B,
    STORE_ST_01,
    TEST_DEFAULTS,
)


def create_customer_payload(**overrides) -> Dict[str, Any]:
    """POST /recommerce/customers — email must be unique and non-empty."""
    payload: Dict[str, Any] = {
        "email": "ava@example.com",
        "full_name": "Ava Reyes",
    }
    payload.update(overrides)
    return payload


def create_grade_policy_payload(**overrides) -> Dict[str, Any]:
    """POST /recommerce/grade-policies — all four rates are basis points."""
    payload: Dict[str, Any] = dict(GRADE_POLICY_OUTERWEAR_B)
    payload.update(overrides)
    return payload


def create_credit_policy_payload(**overrides) -> Dict[str, Any]:
    """POST /recommerce/credit-policies."""
    payload: Dict[str, Any] = dict(CREDIT_POLICY_CORE)
    payload.update(overrides)
    return payload


def create_store_location_payload(**overrides) -> Dict[str, Any]:
    """POST /recommerce/store-locations."""
    payload: Dict[str, Any] = dict(STORE_ST_01)
    payload.update(overrides)
    return payload


def create_refurb_bay_payload(**overrides) -> Dict[str, Any]:
    """POST /recommerce/store-locations/{id}/refurb-bays — store comes from path."""
    payload: Dict[str, Any] = {"code": "BAY-C1", "bay_type": "CLEANING"}
    payload.update(overrides)
    return payload


def create_channel_payload(**overrides) -> Dict[str, Any]:
    """POST /recommerce/channels."""
    payload: Dict[str, Any] = dict(CHANNEL_RESALE_MP)
    payload.update(overrides)
    return payload


def create_trade_in_payload(
    customer_id: str,
    channel: str = "MAIL_IN",
    store_location_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /recommerce/trade-ins.

    ``store_location_id`` is required for an IN_STORE submission and must be
    null for a MAIL_IN one, so it is only ever placed in the body when the
    caller supplies it.
    """
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "channel": channel,
        "product_category": "OUTERWEAR",
        "declared_grade": "B",
        "msrp_minor": TEST_DEFAULTS["OUTERWEAR_MSRP_MINOR"],
        "item_mass_grams": TEST_DEFAULTS["OUTERWEAR_MASS_GRAMS"],
    }
    if store_location_id is not None:
        payload["store_location_id"] = store_location_id
    payload.update(overrides)
    return payload


def authenticate_trade_in_payload(
    authenticity_result: str = "GENUINE", assessed_grade: Optional[str] = "B", **overrides
) -> Dict[str, Any]:
    """POST /recommerce/trade-ins/{id}/authenticate."""
    payload: Dict[str, Any] = {"authenticity_result": authenticity_result}
    if assessed_grade is not None:
        payload["assessed_grade"] = assessed_grade
    payload.update(overrides)
    return payload


def appeal_trade_in_payload(**overrides) -> Dict[str, Any]:
    """POST /recommerce/trade-ins/{id}/appeal."""
    payload: Dict[str, Any] = {"appeal_reason": "lining is intact, grade B expected"}
    payload.update(overrides)
    return payload


def disposition_payload(
    decision: str = "ACCEPT",
    ownership_treatment: Optional[str] = "OWNED_INVENTORY",
    **overrides,
) -> Dict[str, Any]:
    """POST /recommerce/trade-ins/{id}/disposition."""
    payload: Dict[str, Any] = {"decision": decision}
    if ownership_treatment is not None:
        payload["ownership_treatment"] = ownership_treatment
    payload.update(overrides)
    return payload


def create_refurb_order_payload(
    resale_unit_id: str,
    refurb_bay_id: str,
    window_start_at: str,
    window_end_at: str,
    expected_resale_unit_version: int,
    **overrides,
) -> Dict[str, Any]:
    """POST /recommerce/refurb-orders — carries the unit's expected version."""
    payload: Dict[str, Any] = {
        "resale_unit_id": resale_unit_id,
        "refurb_bay_id": refurb_bay_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "expected_resale_unit_version": expected_resale_unit_version,
    }
    payload.update(overrides)
    return payload


def create_refurb_task_payload(
    task_type: str = "REPAIR", labor_minutes: int = 2, parts_cost_minor: int = 0, **overrides
) -> Dict[str, Any]:
    """POST /recommerce/refurb-orders/{id}/tasks."""
    payload: Dict[str, Any] = {
        "task_type": task_type,
        "labor_minutes": labor_minutes,
        "parts_cost_minor": parts_cost_minor,
    }
    payload.update(overrides)
    return payload


def qc_decision_payload(
    decision: str = "PASS", viability_override_reason: Optional[str] = None, **overrides
) -> Dict[str, Any]:
    """POST /recommerce/refurb-orders/{id}/qc-decision."""
    payload: Dict[str, Any] = {"decision": decision}
    if viability_override_reason is not None:
        payload["viability_override_reason"] = viability_override_reason
    payload.update(overrides)
    return payload


def list_unit_payload(channel_id: str, **overrides) -> Dict[str, Any]:
    """POST /recommerce/resale-units/{id}/list."""
    payload: Dict[str, Any] = {"channel_id": channel_id}
    payload.update(overrides)
    return payload


def create_markdown_campaign_payload(
    channel_id: str,
    product_category: str = "OUTERWEAR",
    window_start_at: str = "2026-08-01T00:00:00Z",
    window_end_at: str = "2026-09-01T00:00:00Z",
    cadence_days: int = 7,
    step_bp: int = 1500,
    floor_pct_bp: int = 6000,
    **overrides,
) -> Dict[str, Any]:
    """POST /recommerce/markdown-campaigns."""
    payload: Dict[str, Any] = {
        "channel_id": channel_id,
        "product_category": product_category,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "cadence_days": cadence_days,
        "step_bp": step_bp,
        "floor_pct_bp": floor_pct_bp,
    }
    payload.update(overrides)
    return payload


def create_resale_order_payload(
    customer_id: str,
    channel_id: str,
    resale_unit_id: str,
    requested_credit_minor: int = 0,
    expected_customer_version: int = 1,
    **overrides,
) -> Dict[str, Any]:
    """POST /recommerce/resale-orders — credit is an integer of minor units."""
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "channel_id": channel_id,
        "resale_unit_id": resale_unit_id,
        "requested_credit_minor": requested_credit_minor,
        "expected_customer_version": expected_customer_version,
    }
    payload.update(overrides)
    return payload


def return_request_payload(reason_type: str = "BUYER_REMORSE", **overrides) -> Dict[str, Any]:
    """POST /recommerce/resale-orders/{id}/return-request."""
    payload: Dict[str, Any] = {"reason_type": reason_type}
    payload.update(overrides)
    return payload


def settle_return_payload(resolution: str = "REFUND", **overrides) -> Dict[str, Any]:
    """POST /recommerce/resale-orders/{id}/settle-return."""
    payload: Dict[str, Any] = {"resolution": resolution}
    payload.update(overrides)
    return payload


def create_diversion_report_payload(
    period_start_at: str = "2026-08-01T00:00:00Z",
    period_end_at: str = "2026-09-01T00:00:00Z",
    supersedes_report_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """POST /recommerce/diversion-reports — half-open period, whole days."""
    payload: Dict[str, Any] = {
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
    }
    if supersedes_report_id is not None:
        payload["supersedes_report_id"] = supersedes_report_id
    payload.update(overrides)
    return payload
