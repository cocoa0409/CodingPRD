"""Request-payload builders.

Every money field is emitted as a JSON number because §2.6 declares that "any
field whose name ends in `_cents` is an integer" and every `_bps` field "is an
integer count of basis points".  Every instant is emitted as a full ISO 8601
UTC value with three fractional digits, the shape §2.4 fixes.

Fields the PRD gives a default are omitted rather than sent when the caller
does not ask for them, so a payload built here exercises the declared default.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    DEFAULT_BACKUP_WITHHOLDING_BPS,
    FEE_MODEL_PERCENT_OF_COMMISSION,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A per-process counter used to satisfy the PRD's uniqueness constraints."""
    return f"{next(_counter):04d}"


# ── instants used across the suite ──────────────────────────────────────────

JUL_04_10_00 = "2026-07-04T10:00:00.000Z"
JUL_04_11_00 = "2026-07-04T11:00:00.000Z"
JUL_04_12_00 = "2026-07-04T12:00:00.000Z"
JUL_05_00_00 = "2026-07-05T00:00:00.000Z"
AUG_05_00_00 = "2026-08-05T00:00:00.000Z"
PERIOD_START_JUL = "2026-07-01T00:00:00.000Z"
PERIOD_END_AUG = "2026-08-01T00:00:00.000Z"
YEAR_2026_START = "2026-01-01T00:00:00.000Z"
YEAR_2027_START = "2027-01-01T00:00:00.000Z"
TAX_EXPIRY_2027 = "2027-12-31T00:00:00.000Z"


# ── §3.1 networks ──────────────────────────────────────────────────────────


def network_payload(
    name: Optional[str] = None,
    fee_model: str = FEE_MODEL_PERCENT_OF_COMMISSION,
    fee_bps: int = 0,
    flat_fee_cents: int = 0,
    statement_currency: str = "USD",
) -> Dict[str, Any]:
    return {
        "name": name or f"Corner Network {unique_suffix()}",
        "fee_model": fee_model,
        "fee_bps": int(fee_bps),
        "flat_fee_cents": int(flat_fee_cents),
        "statement_currency": statement_currency,
    }


# ── §3.1 partners ──────────────────────────────────────────────────────────


def affiliate_payload(
    network_id: str,
    partner_type: str = "CONTENT",
    legal_name: Optional[str] = None,
    contact_email: Optional[str] = None,
    payout_currency: str = "USD",
    parent_affiliate_id: Optional[str] = None,
) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "legal_name": legal_name or f"Beacon Content LLC {suffix}",
        "contact_email": contact_email or f"partner{suffix}@example.com",
        "partner_type": partner_type,
        "network_id": network_id,
        "payout_currency": payout_currency,
    }
    if parent_affiliate_id is not None:
        payload["parent_affiliate_id"] = parent_affiliate_id
    return payload


def status_change_payload(target_status: str, reason: str) -> Dict[str, Any]:
    return {"target_status": target_status, "reason": reason}


# ── §3.2 applications ──────────────────────────────────────────────────────


def application_payload(
    site_url: str = "https://beacon.example",
    primary_traffic_source: str = "ORGANIC_SEARCH",
    monthly_traffic_estimate: int = 200000,
    declared_promo_methods: Optional[List[str]] = None,
    product_categories: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "site_url": site_url,
        "primary_traffic_source": primary_traffic_source,
        "monthly_traffic_estimate": int(monthly_traffic_estimate),
        "declared_promo_methods": list(declared_promo_methods or ["EDITORIAL_CONTENT"]),
        "product_categories": list(product_categories or ["APPAREL"]),
    }


def screen_payload(
    domain_authority: int = 80,
    content_originality_pct: int = 92,
    broken_link_ratio_bps: int = 200,
    brand_safety_flag_count: int = 0,
    restricted_vertical_overlap_bps: int = 0,
) -> Dict[str, Any]:
    return {
        "domain_authority": int(domain_authority),
        "content_originality_pct": int(content_originality_pct),
        "broken_link_ratio_bps": int(broken_link_ratio_bps),
        "brand_safety_flag_count": int(brand_safety_flag_count),
        "restricted_vertical_overlap_bps": int(restricted_vertical_overlap_bps),
    }


def decide_payload(
    decision: str,
    expected_affiliate_version: int,
    decision_notes: str = "reviewed against the screening record",
    conditional_requirements: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "decision_notes": decision_notes,
        "expected_affiliate_version": int(expected_affiliate_version),
    }
    if conditional_requirements is not None:
        payload["conditional_requirements"] = list(conditional_requirements)
    return payload


def resubmit_payload(
    site_url: str = "https://beacon.example/v2",
    primary_traffic_source: str = "CONTENT_NEWSLETTER",
    declared_promo_methods: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "site_url": site_url,
        "primary_traffic_source": primary_traffic_source,
        "declared_promo_methods": list(
            declared_promo_methods or ["EDITORIAL_CONTENT", "EMAIL"]
        ),
    }


# ── §3.3 rate cards ────────────────────────────────────────────────────────


def policy_payload(
    product_category: str = "APPAREL",
    partner_type_scope: Optional[List[str]] = None,
    new_customer_rate_bps: int = 900,
    returning_customer_rate_bps: int = 400,
    effective_from: str = YEAR_2026_START,
    effective_to: str = YEAR_2027_START,
    policy_code: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "policy_code": policy_code or f"RATECARD-{unique_suffix()}",
        "product_category": product_category,
        "partner_type_scope": list(partner_type_scope or ["CONTENT"]),
        "new_customer_rate_bps": int(new_customer_rate_bps),
        "returning_customer_rate_bps": int(returning_customer_rate_bps),
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


def activate_policy_payload(expected_policy_version: int) -> Dict[str, Any]:
    return {"expected_policy_version": int(expected_policy_version)}


# ── §3.4 tracking links and clicks ─────────────────────────────────────────


def tracking_link_payload(
    landing_url: str = "https://retail.example/apparel",
    sub_id: Optional[str] = None,
    cookie_window_days: Optional[int] = None,
    device_graph_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "landing_url": landing_url,
        "sub_id": sub_id or f"sub-{unique_suffix()}",
    }
    if cookie_window_days is not None:
        payload["cookie_window_days"] = int(cookie_window_days)
    if device_graph_enabled is not None:
        payload["device_graph_enabled"] = bool(device_graph_enabled)
    return payload


def disable_link_payload(reason: str = "partner request") -> Dict[str, Any]:
    return {"reason": reason}


def click_payload(
    occurred_at: str = JUL_04_10_00,
    device_id: str = "D1",
    click_type: str = "ORGANIC_CLICK",
    referrer_domain: str = "beacon.example",
    household_id: Optional[str] = None,
    paid_search_keyword: Optional[str] = None,
    is_trademark_term: Optional[bool] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "occurred_at": occurred_at,
        "device_id": device_id,
        "click_type": click_type,
        "referrer_domain": referrer_domain,
    }
    if household_id is not None:
        payload["household_id"] = household_id
    if paid_search_keyword is not None:
        payload["paid_search_keyword"] = paid_search_keyword
    if is_trademark_term is not None:
        payload["is_trademark_term"] = bool(is_trademark_term)
    return payload


# ── §3.5 orders and attribution ────────────────────────────────────────────


def conversion_payload(
    order_ref: Optional[str] = None,
    order_total_cents: int = 100000,
    product_category: str = "APPAREL",
    customer_ref: str = "CUST-1",
    is_new_customer: bool = False,
    placed_at: str = JUL_04_12_00,
    device_id: str = "D1",
    household_id: Optional[str] = None,
    coupon_code_used: Optional[str] = None,
    other_channel_touch: Optional[str] = None,
    other_channel_touch_at: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "order_ref": order_ref or f"ORD-{unique_suffix()}",
        "order_total_cents": int(order_total_cents),
        "product_category": product_category,
        "customer_ref": customer_ref,
        "is_new_customer": bool(is_new_customer),
        "placed_at": placed_at,
        "device_id": device_id,
    }
    if household_id is not None:
        payload["household_id"] = household_id
    if coupon_code_used is not None:
        payload["coupon_code_used"] = coupon_code_used
    if other_channel_touch is not None:
        payload["other_channel_touch"] = other_channel_touch
    if other_channel_touch_at is not None:
        payload["other_channel_touch_at"] = other_channel_touch_at
    return payload


def attribute_payload(expected_conversion_version: int) -> Dict[str, Any]:
    return {"expected_conversion_version": int(expected_conversion_version)}


def order_adjustment_payload(
    adjustment_type: str,
    returned_amount_cents: int,
    occurred_at: str = AUG_05_00_00,
) -> Dict[str, Any]:
    return {
        "adjustment_type": adjustment_type,
        "returned_amount_cents": int(returned_amount_cents),
        "occurred_at": occurred_at,
    }


# ── §3.7 monitoring and violation cases ────────────────────────────────────


def monitoring_scan_payload(
    affiliate_id: str,
    engine: str = "GOOGLE_ADS",
    window_start: str = "2026-06-01T00:00:00.000Z",
    window_end: str = "2026-06-08T00:00:00.000Z",
    trademark_hits: int = 0,
    forced_click_ratio_bps: int = 0,
    cookie_stuffing_index: int = 0,
    unauthorized_coupon_hits: int = 0,
) -> Dict[str, Any]:
    return {
        "affiliate_id": affiliate_id,
        "engine": engine,
        "window_start": window_start,
        "window_end": window_end,
        "trademark_hits": int(trademark_hits),
        "forced_click_ratio_bps": int(forced_click_ratio_bps),
        "cookie_stuffing_index": int(cookie_stuffing_index),
        "unauthorized_coupon_hits": int(unauthorized_coupon_hits),
    }


def violation_case_payload(
    affiliate_id: str,
    violation_type: str = "TRADEMARK_BIDDING",
    evidence_ref: Optional[str] = None,
    detected_at: str = JUL_05_00_00,
    source_scan_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "affiliate_id": affiliate_id,
        "violation_type": violation_type,
        "evidence_ref": evidence_ref or f"evidence-{unique_suffix()}",
        "detected_at": detected_at,
    }
    if source_scan_id is not None:
        payload["source_scan_id"] = source_scan_id
    return payload


def case_transition_payload(
    action: str,
    note: str = "case advanced",
    remediation_evidence_ref: Optional[str] = None,
    verify_outcome: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action, "note": note}
    if remediation_evidence_ref is not None:
        payload["remediation_evidence_ref"] = remediation_evidence_ref
    if verify_outcome is not None:
        payload["verify_outcome"] = verify_outcome
    return payload


# ── §3.8 tax documents ─────────────────────────────────────────────────────


def tax_document_payload(
    form_type: str = "W9",
    tax_id_last4: str = "1234",
    treaty_withholding_bps: int = 0,
    expires_on: str = TAX_EXPIRY_2027,
) -> Dict[str, Any]:
    return {
        "form_type": form_type,
        "tax_id_last4": tax_id_last4,
        "treaty_withholding_bps": int(treaty_withholding_bps),
        "expires_on": expires_on,
    }


def verify_tax_document_payload(verification_outcome: str) -> Dict[str, Any]:
    return {"verification_outcome": verification_outcome}


# ── §3.9 settlement ────────────────────────────────────────────────────────


def payout_batch_payload(
    network_id: str,
    period_start: str = PERIOD_START_JUL,
    period_end: str = PERIOD_END_AUG,
) -> Dict[str, Any]:
    return {
        "network_id": network_id,
        "period_start": period_start,
        "period_end": period_end,
    }


def validate_batch_payload(
    statement_gross_cents: int, statement_fee_cents: int
) -> Dict[str, Any]:
    return {
        "statement_gross_cents": int(statement_gross_cents),
        "statement_fee_cents": int(statement_fee_cents),
    }


def approve_batch_payload(expected_batch_version: int) -> Dict[str, Any]:
    return {"expected_batch_version": int(expected_batch_version)}


def pay_batch_payload(payment_reference: str = "WIRE-2026-08-05") -> Dict[str, Any]:
    return {"payment_reference": payment_reference}


def void_batch_payload(reason: str = "period reopened by the network") -> Dict[str, Any]:
    return {"reason": reason}


def release_hold_payload(reason: str = "hold cleared by finance") -> Dict[str, Any]:
    return {"reason": reason}


#: The rate the §3.9 line math falls back to when no VALID document is on file.
BACKUP_WITHHOLDING_BPS = DEFAULT_BACKUP_WITHHOLDING_BPS
