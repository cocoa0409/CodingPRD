"""Request-payload factories.

Every money field is an integer number of cents (PRD S2.7) and every instant is
a full ISO 8601 UTC instant (PRD S2.4) — never a bare date.  Each factory takes
``**overrides`` so a test can vary exactly the one field it is about, and
``without()`` removes a key when the point of the test is an omitted input.
"""

import itertools
from typing import Any, Dict, List, Optional, Sequence

from .constants import DEFAULT_NAIC_CODE, THREE_STATES

_naic_counter = itertools.count(20001)
_policy_counter = itertools.count(1)

_OMITTED = object()


def without(payload: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    """Copy of ``payload`` with the named keys removed."""
    return {k: v for k, v in payload.items() if k not in keys}


def next_naic_code() -> str:
    """A fresh five-digit NAIC code (S3.1 requires uniqueness across insurers)."""
    return f"{next(_naic_counter):05d}"


def next_policy_number(prefix: str = "POL") -> str:
    """A fresh policy number, unique among one insurer's filings (S3.5)."""
    return f"{prefix}-{next(_policy_counter):04d}"


# ---------------------------------------------------------------------------
# S3.1 registry payloads
# ---------------------------------------------------------------------------
def carrier_payload(
    legal_name: str = "Llano Estacado Transport LLC",
    domicile_state: str = "TX",
    self_reported_vehicle_count: int = 25,
    self_reported_driver_count: int = 30,
    self_reported_oos_rate_pct: float = 8.0,
    dba_name: Any = _OMITTED,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "domicile_state": domicile_state,
        "self_reported_vehicle_count": self_reported_vehicle_count,
        "self_reported_driver_count": self_reported_driver_count,
        "self_reported_oos_rate_pct": self_reported_oos_rate_pct,
    }
    if dba_name is not _OMITTED:
        payload["dba_name"] = dba_name
    payload.update(overrides)
    return payload


def process_agent_payload(
    company_name: str = "Gulf Coast Process Agents",
    coverage_states: Optional[Sequence[str]] = None,
    blanket_agent: Any = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_name": company_name,
        "coverage_states": list(coverage_states or THREE_STATES),
    }
    if blanket_agent is not _OMITTED:
        payload["blanket_agent"] = blanket_agent
    payload.update(overrides)
    return payload


def insurer_payload(
    company_name: str = "Permian Mutual Casualty",
    naic_code: str = DEFAULT_NAIC_CODE,
    authorized_states: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_name": company_name,
        "naic_code": naic_code,
        "authorized_states": list(authorized_states or THREE_STATES),
    }
    payload.update(overrides)
    return payload


def fee_payment_payload(
    amount_cents: int, memo: str = "docket filing fee", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": int(amount_cents), "memo": memo}
    payload.update(overrides)
    return payload


def biennial_update_payload(
    self_reported_vehicle_count: int = 25,
    self_reported_driver_count: int = 30,
    self_reported_oos_rate_pct: float = 8.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "self_reported_vehicle_count": self_reported_vehicle_count,
        "self_reported_driver_count": self_reported_driver_count,
        "self_reported_oos_rate_pct": self_reported_oos_rate_pct,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# S3.2 / S3.3 application payloads
# ---------------------------------------------------------------------------
def application_payload(
    carrier_id: str,
    application_kind: str = "NEW",
    transportation_type: str = "FOR_HIRE_PROPERTY",
    requested_operating_states: Optional[Sequence[str]] = None,
    hazmat_endorsement_requested: bool = False,
    hazmat_bulk_capable: bool = False,
    predecessor_authority_id: Any = _OMITTED,
    passenger_seating_capacity: Any = _OMITTED,
    proposed_legal_name: Any = _OMITTED,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "carrier_id": carrier_id,
        "application_kind": application_kind,
        "transportation_type": transportation_type,
        "requested_operating_states": list(requested_operating_states or THREE_STATES),
        "hazmat_endorsement_requested": hazmat_endorsement_requested,
        "hazmat_bulk_capable": hazmat_bulk_capable,
    }
    if predecessor_authority_id is not _OMITTED:
        payload["predecessor_authority_id"] = predecessor_authority_id
    if passenger_seating_capacity is not _OMITTED:
        payload["passenger_seating_capacity"] = passenger_seating_capacity
    if proposed_legal_name is not _OMITTED:
        payload["proposed_legal_name"] = proposed_legal_name
    payload.update(overrides)
    return payload


def vetting_review_payload(
    disposition: str = "PUBLISH",
    findings: str = "no adverse vetting findings",
    denied_reason: Any = _OMITTED,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"disposition": disposition, "findings": findings}
    if denied_reason is not _OMITTED:
        payload["denied_reason"] = denied_reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# S3.4 designation payloads
# ---------------------------------------------------------------------------
def designation_payload(
    process_agent_id: str,
    state_codes: Optional[Sequence[str]] = None,
    effective_from: str = "2026-08-05T00:00:00Z",
    effective_to: Any = _OMITTED,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "process_agent_id": process_agent_id,
        "state_codes": list(state_codes or THREE_STATES),
        "effective_from": effective_from,
    }
    if effective_to is not _OMITTED:
        payload["effective_to"] = effective_to
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# S3.5 insurance filing payloads
# ---------------------------------------------------------------------------
def filing_payload(
    authority_id: str,
    insurer_id: str,
    coverage_limit_cents: int,
    expected_authority_version: int,
    filing_type: str = "BIPD",
    policy_number: Optional[str] = None,
    effective_at: str = "2026-08-05T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "authority_id": authority_id,
        "insurer_id": insurer_id,
        "filing_type": filing_type,
        "coverage_limit_cents": int(coverage_limit_cents),
        "policy_number": policy_number or next_policy_number(filing_type),
        "effective_at": effective_at,
        "expected_authority_version": int(expected_authority_version),
    }
    payload.update(overrides)
    return payload


def cancel_filing_payload(cancellation_effective_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancellation_effective_at": cancellation_effective_at}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# S3.7 audit payloads
# ---------------------------------------------------------------------------
def audit_result_payload(
    audited_oos_rate_pct: float = 4.0,
    audited_driver_violation_count: int = 2,
    audited_vehicle_defect_count: int = 3,
    acute_violation_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "audited_oos_rate_pct": audited_oos_rate_pct,
        "audited_driver_violation_count": int(audited_driver_violation_count),
        "audited_vehicle_defect_count": int(audited_vehicle_defect_count),
        "acute_violation_count": int(acute_violation_count),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# S3.8 cure payload
# ---------------------------------------------------------------------------
def cure_payload(replacement_policy_number: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"replacement_policy_number": replacement_policy_number}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# S3.9 contract and shipment payloads
# ---------------------------------------------------------------------------
def contract_payload(
    expected_authority_version: int,
    shipper_name: str = "Yellow House Grain",
    commodity_class: str = "GENERAL_FREIGHT",
    monthly_committed_revenue_cents: int = 90000000,
    term_start_at: str = "2026-09-01T00:00:00Z",
    term_end_at: str = "2026-12-31T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "shipper_name": shipper_name,
        "commodity_class": commodity_class,
        "monthly_committed_revenue_cents": int(monthly_committed_revenue_cents),
        "term_start_at": term_start_at,
        "term_end_at": term_end_at,
        "expected_authority_version": int(expected_authority_version),
    }
    payload.update(overrides)
    return payload


def shipment_payload(
    origin_state: str = "TX",
    destination_state: str = "OK",
    tender_at: str = "2026-09-02T00:00:00Z",
    expected_delivery_at: str = "2026-09-20T00:00:00Z",
    declared_value_cents: int = 4500000,
    hazmat: Any = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "origin_state": origin_state,
        "destination_state": destination_state,
        "tender_at": tender_at,
        "expected_delivery_at": expected_delivery_at,
        "declared_value_cents": int(declared_value_cents),
    }
    if hazmat is not _OMITTED:
        payload["hazmat"] = hazmat
    payload.update(overrides)
    return payload


OMITTED = _OMITTED

__all__: List[str] = [
    "OMITTED",
    "without",
    "next_naic_code",
    "next_policy_number",
    "carrier_payload",
    "process_agent_payload",
    "insurer_payload",
    "fee_payment_payload",
    "biennial_update_payload",
    "application_payload",
    "vetting_review_payload",
    "designation_payload",
    "filing_payload",
    "cancel_filing_payload",
    "audit_result_payload",
    "cure_payload",
    "contract_payload",
    "shipment_payload",
]
