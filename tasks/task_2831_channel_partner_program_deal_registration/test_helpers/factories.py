"""Payload factories - one per entity, carrying only the input fields the PRD accepts.

Money is always an integer number of cents and margin rates are always numeric decimal
fractions; every instant is a full ISO-8601 UTC timestamp with millisecond precision.
"""

from typing import Any, Dict

from .constants import TEST_DEFAULTS


def create_partner_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_name": TEST_DEFAULTS["COMPANY_NAME"],
        "partner_type": "DISTRIBUTOR",
        "marketing_commitment_cents": 0,
    }
    payload.update(overrides)
    return payload


def update_partner_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_certification_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "engineer_name": TEST_DEFAULTS["ENGINEER_NAME"],
        "track": "TECH_EXPERT",
        "issued_at": TEST_DEFAULTS["CERT_ISSUED_AT"],
        "expires_at": TEST_DEFAULTS["CERT_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_account_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "account_name": TEST_DEFAULTS["ACCOUNT_NAME"],
        "region_code": TEST_DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def direct_pursuit_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"pursuit_note": "enterprise renewal owned by field sales"}
    payload.update(overrides)
    return payload


def create_account_mapping_payload(
    partner_id: str, account_id: str, expected_account_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "account_id": account_id,
        "product_line": TEST_DEFAULTS["PRODUCT_LINE"],
        "exclusivity_scope": "PRODUCT_LINE",
        "effective_from": "2026-03-01T00:00:00.000Z",
        "effective_until": "2026-06-30T23:59:59.999Z",
        "expected_account_version": expected_account_version,
    }
    payload.update(overrides)
    return payload


def respond_account_mapping_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def create_deal_registration_payload(partner_id: str, account_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "account_id": account_id,
        "product_line": TEST_DEFAULTS["PRODUCT_LINE"],
        "expected_amount_cents": TEST_DEFAULTS["EXPECTED_AMOUNT_CENTS"],
        "expected_close_date": TEST_DEFAULTS["EXPECTED_CLOSE_DATE"],
    }
    payload.update(overrides)
    return payload


def review_registration_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def decide_registration_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def escalate_conflict_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"escalation_note": "partner disputes the coverage claim"}
    payload.update(overrides)
    return payload


def resolve_conflict_payload(resolution: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "resolution": resolution,
        "resolution_note": "director decision recorded",
    }
    payload.update(overrides)
    return payload


def create_special_pricing_request_payload(
    registration_id: str, expected_registration_version: int, **overrides
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "registration_id": registration_id,
        "requested_extra_margin_pct": 0.02,
        "justification": "competitive displacement pricing",
        "expected_registration_version": expected_registration_version,
    }
    payload.update(overrides)
    return payload


def decide_special_pricing_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def create_mdf_allocation_payload(partner_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "period_start": "2026-02-01T00:00:00.000Z",
        "period_end": "2026-06-30T23:59:59.999Z",
    }
    payload.update(overrides)
    return payload


def create_mdf_claim_payload(allocation_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "allocation_id": allocation_id,
        "activity_type": "EVENT",
        "requested_cents": 20_000,
    }
    payload.update(overrides)
    return payload


def create_proof_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "doc_type": "ATTENDEE_LIST",
        "spend_amount_cents": 12_000,
        "audience_reach": 140,
    }
    payload.update(overrides)
    return payload


def validate_claim_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload


def settle_claim_payload(action: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def create_order_invoice_payload(partner_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "order_type": "STOCKING",
        "list_amount_cents": TEST_DEFAULTS["LIST_AMOUNT_CENTS"],
    }
    payload.update(overrides)
    return payload


def credit_memo_payload(credit_memo_cents: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "credit_memo_cents": credit_memo_cents,
        "credit_reason": "post-ship price adjustment",
    }
    payload.update(overrides)
    return payload


def create_performance_review_payload(partner_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "partner_id": partner_id,
        "period_start": "2026-01-01T00:00:00.000Z",
        "period_end": "2026-01-31T23:59:59.999Z",
        "findings_count": 0,
    }
    payload.update(overrides)
    return payload


def remediate_review_payload(**overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"remediation_note": "all audit findings closed out"}
    payload.update(overrides)
    return payload


def decide_review_payload(decision: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload
