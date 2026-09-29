"""Payload factories — one per write endpoint, input fields only."""
from typing import Optional

from .constants import (
    ACCOUNT_CONFIG,
    APPROVAL_TIERS,
    CORE_SUPPORT_BUNDLE,
    POLICY_CONFIG,
    PRODUCT_CORE,
)


def desk_policy_payload(**overrides) -> dict:
    payload = dict(POLICY_CONFIG)
    payload.update(overrides)
    return payload


def approval_tier_payload(desk_policy_id: str, tier_level: int, **overrides) -> dict:
    template = next(t for t in APPROVAL_TIERS if t["tier_level"] == tier_level)
    payload = dict(template)
    payload["desk_policy_id"] = desk_policy_id
    payload.update(overrides)
    return payload


def product_payload(**overrides) -> dict:
    payload = dict(PRODUCT_CORE)
    payload.update(overrides)
    return payload


def volume_tier_payload(
    product_id: str,
    tier_level: int,
    min_quantity: int,
    max_quantity: Optional[int] = None,
    tier_discount_pct: float = 0.0,
    **overrides,
) -> dict:
    payload = {
        "product_id": product_id,
        "tier_level": tier_level,
        "min_quantity": min_quantity,
        "tier_discount_pct": tier_discount_pct,
    }
    if max_quantity is not None:
        payload["max_quantity"] = max_quantity
    payload.update(overrides)
    return payload


def bundle_rule_payload(anchor_product_id: str, attached_product_id: str, **overrides) -> dict:
    payload = {
        "anchor_product_id": anchor_product_id,
        "attached_product_id": attached_product_id,
        "bundle_discount_pct": CORE_SUPPORT_BUNDLE["bundle_discount_pct"],
        "min_attach_quantity_ratio": CORE_SUPPORT_BUNDLE["min_attach_quantity_ratio"],
    }
    payload.update(overrides)
    return payload


def account_payload(**overrides) -> dict:
    payload = dict(ACCOUNT_CONFIG)
    payload.update(overrides)
    return payload


def credit_decision_payload(credit_status: str, credit_note: Optional[str] = None) -> dict:
    payload = {"credit_status": credit_status}
    if credit_note is not None:
        payload["credit_note"] = credit_note
    return payload


def quote_payload(account_id: str, title: str = "Northwind FY26 Expansion", term_months: int = 12,
                  **overrides) -> dict:
    payload = {"account_id": account_id, "title": title, "term_months": term_months}
    payload.update(overrides)
    return payload


def quote_patch_payload(**overrides) -> dict:
    return dict(overrides)


def quote_line_payload(
    quote_id: str,
    product_id: str,
    quantity: int,
    requested_discount_pct: Optional[float] = None,
    **overrides,
) -> dict:
    payload = {"quote_id": quote_id, "product_id": product_id, "quantity": quantity}
    if requested_discount_pct is not None:
        payload["requested_discount_pct"] = requested_discount_pct
    payload.update(overrides)
    return payload


def quote_line_patch_payload(**overrides) -> dict:
    return dict(overrides)


def nonstandard_term_payload(
    quote_id: str,
    term_category: str,
    requested_numeric_value: float,
    requested_text: Optional[str] = None,
    hold_product_id: Optional[str] = None,
    hold_start_date: Optional[str] = None,
    hold_end_date: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "quote_id": quote_id,
        "term_category": term_category,
        "requested_numeric_value": requested_numeric_value,
    }
    if requested_text is not None:
        payload["requested_text"] = requested_text
    if hold_product_id is not None:
        payload["hold_product_id"] = hold_product_id
    if hold_start_date is not None:
        payload["hold_start_date"] = hold_start_date
    if hold_end_date is not None:
        payload["hold_end_date"] = hold_end_date
    payload.update(overrides)
    return payload


def term_review_payload(decision: str, reviewer_note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if reviewer_note is not None:
        payload["reviewer_note"] = reviewer_note
    return payload


def competitive_exception_payload(
    quote_id: str,
    competitor_name: str = "Competitor Alpha",
    competitor_quoted_total_cents: int = 1500000,
    evidence_reference: str = "EVID-2026-0001",
    justification: str = "Competitor undercut the renewal on identical scope.",
    **overrides,
) -> dict:
    payload = {
        "quote_id": quote_id,
        "competitor_name": competitor_name,
        "competitor_quoted_total_cents": competitor_quoted_total_cents,
        "evidence_reference": evidence_reference,
        "justification": justification,
    }
    payload.update(overrides)
    return payload


def exception_decision_payload(decision: str, decision_note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def exception_revoke_payload(decision_note: Optional[str] = None) -> dict:
    payload = {}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def revrec_assessment_payload(quote_id: str, **overrides) -> dict:
    payload = {"quote_id": quote_id}
    payload.update(overrides)
    return payload


def revrec_decision_payload(decision: str, assessment_note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if assessment_note is not None:
        payload["assessment_note"] = assessment_note
    return payload


def step_decision_payload(decision: str, decision_note: Optional[str] = None) -> dict:
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


def renegotiate_payload(expected_quote_version: int, **overrides) -> dict:
    payload = {"expected_quote_version": expected_quote_version}
    payload.update(overrides)
    return payload


def delegation_grant_payload(
    grantee_user_id: str,
    tier_level: int,
    max_discount_pct: float,
    starts_at: str,
    ends_at: str,
    **overrides,
) -> dict:
    payload = {
        "grantee_user_id": grantee_user_id,
        "tier_level": tier_level,
        "max_discount_pct": max_discount_pct,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def order_form_payload(
    quote_id: str,
    expected_quote_version: int,
    signer_name: str = "Dana Signer",
    signer_email: str = "dana.signer@northwind.example",
    **overrides,
) -> dict:
    payload = {
        "quote_id": quote_id,
        "expected_quote_version": expected_quote_version,
        "signer_name": signer_name,
        "signer_email": signer_email,
    }
    payload.update(overrides)
    return payload


def signature_payload(outcome: str, signed_by_name: Optional[str] = None) -> dict:
    payload = {"outcome": outcome}
    if signed_by_name is not None:
        payload["signed_by_name"] = signed_by_name
    return payload


def reverse_booking_payload(reversal_reason: str = "Booked against the wrong entity.") -> dict:
    return {"reversal_reason": reversal_reason}
