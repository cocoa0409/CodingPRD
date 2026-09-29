"""Request payload builders.

Every builder emits its keys in the order the endpoint declares its input
fields, because PRD §2.9 resolves body foreign keys "in the order in which the
endpoint declares its input fields" and the first unresolvable reference decides
the rejection. Optional fields are omitted unless supplied so that a builder can
also exercise the server's defaults.

Money is emitted as an integer number of cents and rates/points as JSON numbers,
never as strings (PRD §2.6).
"""

import itertools
from typing import Any, Dict, List, Optional


_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):04d}"


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# --------------------------------------------------------------------------
# Seller registration (PRD §3.1)
# --------------------------------------------------------------------------
def seller_payload(legal_name: Optional[str] = None, email: Optional[str] = None,
                   tax_id_hash: Optional[str] = None,
                   payout_bank_token: Optional[str] = None,
                   address_fingerprint: Optional[str] = None,
                   device_fingerprint: Optional[str] = None,
                   **overrides) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "legal_name": legal_name if legal_name is not None else f"Seller {suffix} Ltd",
        "email": email if email is not None else f"seller{suffix}@corp{suffix}.example",
        "tax_id_hash": tax_id_hash if tax_id_hash is not None else f"tax-{suffix}-hash",
        "payout_bank_token": (
            payout_bank_token if payout_bank_token is not None else f"bank-{suffix}-token"
        ),
        "address_fingerprint": (
            address_fingerprint if address_fingerprint is not None else f"addr-{suffix}-print"
        ),
    }
    if device_fingerprint is not None:
        payload["device_fingerprint"] = device_fingerprint
    payload.update(overrides)
    return payload


def credit_payload(amount_cents: int,
                   external_reference: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if external_reference is not None:
        payload["external_reference"] = external_reference
    return payload


# --------------------------------------------------------------------------
# Policy catalogue (PRD §3.2)
# --------------------------------------------------------------------------
def policy_rule_payload(code: Optional[str] = None,
                        category: str = "LISTING_ACCURACY",
                        base_severity_weight: float = 2.00,
                        removal_scope: str = "ACCOUNT",
                        requires_poa: Optional[bool] = None,
                        **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code if code is not None else f"PR-{unique_suffix()}",
        "category": category,
        "base_severity_weight": base_severity_weight,
        "removal_scope": removal_scope,
    }
    if requires_poa is not None:
        payload["requires_poa"] = requires_poa
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Listings (PRD §3.2)
# --------------------------------------------------------------------------
def listing_payload(seller_id: str, sku: Optional[str] = None,
                    title: Optional[str] = None, category_code: str = "HOME-GOODS",
                    restricted_flag: Optional[bool] = None,
                    **overrides) -> Dict[str, Any]:
    suffix = unique_suffix()
    payload: Dict[str, Any] = {
        "seller_id": seller_id,
        "sku": sku if sku is not None else f"SKU-{suffix}",
        "title": title if title is not None else f"Listing {suffix}",
        "category_code": category_code,
    }
    if restricted_flag is not None:
        payload["restricted_flag"] = restricted_flag
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Metric snapshots (PRD §3.3)
# --------------------------------------------------------------------------
def snapshot_payload(seller_id: str, window_start: str, window_end: str,
                     order_volume: int = 1000,
                     delivered_or_refunded_volume: int = 1000,
                     defect_claims_pending: int = 0,
                     defect_claims_substantiated: int = 0,
                     late_shipments: int = 0,
                     pre_fulfillment_cancellations: int = 0,
                     shipments_total: int = 1000,
                     shipments_with_valid_tracking: int = 1000,
                     source: Optional[str] = None,
                     **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "seller_id": seller_id,
        "window_start": window_start,
        "window_end": window_end,
        "order_volume": order_volume,
        "delivered_or_refunded_volume": delivered_or_refunded_volume,
        "defect_claims_pending": defect_claims_pending,
        "defect_claims_substantiated": defect_claims_substantiated,
        "late_shipments": late_shipments,
        "pre_fulfillment_cancellations": pre_fulfillment_cancellations,
        "shipments_total": shipments_total,
        "shipments_with_valid_tracking": shipments_with_valid_tracking,
    }
    if source is not None:
        payload["source"] = source
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Violations (PRD §3.5)
# --------------------------------------------------------------------------
def violation_payload(seller_id: str, policy_rule_id: str,
                      listing_id: Optional[str] = None,
                      reporter_type: str = "BUYER",
                      evidence_reference: Optional[str] = None,
                      **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"seller_id": seller_id, "policy_rule_id": policy_rule_id}
    if listing_id is not None:
        payload["listing_id"] = listing_id
    payload["reporter_type"] = reporter_type
    payload["evidence_reference"] = (
        evidence_reference if evidence_reference is not None else f"EV-{unique_suffix()}"
    )
    payload.update(overrides)
    return payload


def adjudication_payload(outcome: str,
                         decision_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return payload


# --------------------------------------------------------------------------
# Enforcement actions (PRD §3.6)
# --------------------------------------------------------------------------
def action_payload(violation_id: str,
                   action_type_override: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"violation_id": violation_id}
    if action_type_override is not None:
        payload["action_type_override"] = action_type_override
    return payload


# --------------------------------------------------------------------------
# Plans of action (PRD §3.7)
# --------------------------------------------------------------------------
DEFAULT_ROOT_CAUSE = (
    "Our fulfilment team mis-mapped the carrier scan file for six weeks, so "
    "confirmed shipments were reported late to the marketplace."
)
DEFAULT_CORRECTIVE = ["Rebuilt the carrier scan mapping and reconciled every open order."]
DEFAULT_PREVENTIVE = ["Added a nightly reconciliation alert owned by the ops manager."]


def poa_payload(enforcement_action_id: str,
                expected_enforcement_action_version: int,
                root_cause: Optional[str] = None,
                corrective_measures: Optional[List[str]] = None,
                preventive_measures: Optional[List[str]] = None,
                **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enforcement_action_id": enforcement_action_id,
        "root_cause": root_cause if root_cause is not None else DEFAULT_ROOT_CAUSE,
        "corrective_measures": (
            list(corrective_measures) if corrective_measures is not None
            else list(DEFAULT_CORRECTIVE)
        ),
        "preventive_measures": (
            list(preventive_measures) if preventive_measures is not None
            else list(DEFAULT_PREVENTIVE)
        ),
        "expected_enforcement_action_version": expected_enforcement_action_version,
    }
    payload.update(overrides)
    return payload


def poa_review_payload(decision: str,
                       review_notes: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if review_notes is not None:
        payload["review_notes"] = review_notes
    return payload


# --------------------------------------------------------------------------
# Appeals (PRD §3.8)
# --------------------------------------------------------------------------
DEFAULT_GROUNDS = (
    "The cited defect claims were opened against orders that a courier lost in "
    "transit, and the carrier has since accepted liability in writing."
)
DEFAULT_RATIONALE = (
    "The evidence bundle supports the enforcement decision and the seller's "
    "submission does not rebut the underlying measurements."
)


def appeal_payload(enforcement_action_id: str, plan_of_action_id: Optional[str] = None,
                   grounds: Optional[str] = None, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"enforcement_action_id": enforcement_action_id}
    if plan_of_action_id is not None:
        payload["plan_of_action_id"] = plan_of_action_id
    payload["grounds"] = grounds if grounds is not None else DEFAULT_GROUNDS
    payload.update(overrides)
    return payload


def appeal_decision_payload(outcome: str, denial_reason: Optional[str] = None,
                            rationale: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if denial_reason is not None:
        payload["denial_reason"] = denial_reason
    payload["rationale"] = rationale if rationale is not None else DEFAULT_RATIONALE
    return payload


def escalation_payload(escalation_grounds: Optional[str] = None) -> Dict[str, Any]:
    return {
        "escalation_grounds": (
            escalation_grounds if escalation_grounds is not None
            else "The first-level reviewer did not read the carrier liability letter at all."
        )
    }


# --------------------------------------------------------------------------
# Disbursement holds (PRD §3.9)
# --------------------------------------------------------------------------
def hold_payload(seller_id: str, coverage_start: str, coverage_end: str,
                 expected_seller_version: int,
                 enforcement_action_id: Optional[str] = None,
                 hold_type: str = "RESERVE",
                 reserve_basis: str = "ROLLING",
                 **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"seller_id": seller_id}
    if enforcement_action_id is not None:
        payload["enforcement_action_id"] = enforcement_action_id
    payload["hold_type"] = hold_type
    payload["reserve_basis"] = reserve_basis
    payload["coverage_start"] = coverage_start
    payload["coverage_end"] = coverage_end
    payload["expected_seller_version"] = expected_seller_version
    payload.update(overrides)
    return payload


def release_payload(release_reason: str) -> Dict[str, Any]:
    return {"release_reason": release_reason}


def forfeit_payload(forfeited_amount_cents: int) -> Dict[str, Any]:
    return {"forfeited_amount_cents": forfeited_amount_cents}


# --------------------------------------------------------------------------
# Related-account links (PRD §3.1)
# --------------------------------------------------------------------------
def link_adjudication_payload(decision: str,
                              adjudication_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if adjudication_note is not None:
        payload["adjudication_note"] = adjudication_note
    return payload
