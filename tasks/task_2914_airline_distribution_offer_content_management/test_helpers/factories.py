"""Request-payload builders.

Every builder returns a plain dict ready to be sent as a JSON body. Two rules
hold throughout:

* money fields are Python ints denominated in whole cents — never strings;
* instant fields are full ISO-8601 UTC instants with three fractional digits and
  a ``Z`` suffix — never date-only strings.

Each builder accepts ``**overrides`` so a test can replace or add any field, and
the sentinel ``OMIT`` as an override value deletes a field entirely (used to
probe required-field handling).
"""

from itertools import count
from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    CABIN_ECONOMY,
    CERT_ENV_A,
    CHANNEL_KIND_NDC_AGGREGATOR,
    CONTENT_TIER_STANDARD,
    DEPARTURE_DATE,
    DESTINATION_JFK,
    ITEM_SCOPE_ALL,
    ORIGIN_FRA,
    PARTNER_TYPE_TRAVEL_AGENCY,
    SALE_FROM,
    SALE_TO,
    TRAVEL_FROM,
    TRAVEL_TO,
)

Payload = Dict[str, Any]


class _Omit:
    """Sentinel: an override of this value removes the field from the payload."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "OMIT"


OMIT = _Omit()

_counter = count(1)


def unique_suffix() -> str:
    """A short suffix unique within a single test process."""
    return f"{next(_counter):04d}"


def unique_code(prefix: str) -> str:
    """A short unique code built from ``prefix``."""
    return f"{prefix}{unique_suffix()}"


def _finalise(payload: Payload, overrides: Payload) -> Payload:
    for key, value in overrides.items():
        if isinstance(value, _Omit):
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# --- channels -------------------------------------------------------------
def channel_payload(
    channel_code: str = "CH_MAIN",
    channel_kind: str = CHANNEL_KIND_NDC_AGGREGATOR,
    **overrides: Any,
) -> Payload:
    payload: Payload = {"channel_code": channel_code, "channel_kind": channel_kind}
    return _finalise(payload, overrides)


def full_channel_payload(
    channel_code: str = "CH_FULL",
    channel_kind: str = CHANNEL_KIND_NDC_AGGREGATOR,
    content_tier: str = CONTENT_TIER_STANDARD,
    content_markup_pct: float = 0.0,
    incentive_multiplier: float = 1.0,
    monthly_platform_fee_cents: int = 0,
    per_message_cost_cents: int = 0,
    per_segment_fee_cents: int = 0,
    servicing_parity_change: bool = True,
    servicing_parity_refund: bool = True,
    required_disclosure_codes: Optional[Sequence[str]] = None,
    **overrides: Any,
) -> Payload:
    """A channel payload with every optional dial spelled out explicitly."""
    payload: Payload = {
        "channel_code": channel_code,
        "channel_kind": channel_kind,
        "content_tier": content_tier,
        "content_markup_pct": content_markup_pct,
        "incentive_multiplier": incentive_multiplier,
        "monthly_platform_fee_cents": int(monthly_platform_fee_cents),
        "per_message_cost_cents": int(per_message_cost_cents),
        "per_segment_fee_cents": int(per_segment_fee_cents),
        "servicing_parity_change": servicing_parity_change,
        "servicing_parity_refund": servicing_parity_refund,
        "required_disclosure_codes": list(required_disclosure_codes or []),
    }
    return _finalise(payload, overrides)


def content_policy_payload(**overrides: Any) -> Payload:
    """A content-policy revision carries any subset of the four revisable fields."""
    return _finalise({}, overrides)


def surcharge_rule_payload(
    surcharge_code: str = "SUR_ALL",
    item_scope: str = ITEM_SCOPE_ALL,
    rate_pct: float = 0.10,
    threshold_cents: int = 0,
    min_cents: int = 0,
    max_cents: int = 100000000,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "surcharge_code": surcharge_code,
        "item_scope": item_scope,
        "rate_pct": rate_pct,
        "threshold_cents": int(threshold_cents),
        "min_cents": int(min_cents),
        "max_cents": int(max_cents),
    }
    return _finalise(payload, overrides)


# --- distribution partners ------------------------------------------------
def partner_payload(
    partner_name: str = "Alpha Travel",
    partner_type: str = PARTNER_TYPE_TRAVEL_AGENCY,
    iata_code: str = "12345670",
    home_country: str = "DE",
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "partner_name": partner_name,
        "partner_type": partner_type,
        "iata_code": iata_code,
        "home_country": home_country,
    }
    return _finalise(payload, overrides)


# --- fare filings ---------------------------------------------------------
def fare_filing_payload(
    fare_basis_code: str = "YBASE01",
    origin: str = ORIGIN_FRA,
    destination: str = DESTINATION_JFK,
    cabin: str = CABIN_ECONOMY,
    base_amount_cents: int = 45000,
    sale_from: str = SALE_FROM,
    sale_to: str = SALE_TO,
    travel_from: str = TRAVEL_FROM,
    travel_to: str = TRAVEL_TO,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "fare_basis_code": fare_basis_code,
        "origin": origin,
        "destination": destination,
        "cabin": cabin,
        "base_amount_cents": int(base_amount_cents),
        "sale_from": sale_from,
        "sale_to": sale_to,
        "travel_from": travel_from,
        "travel_to": travel_to,
    }
    return _finalise(payload, overrides)


def filing_state_payload(to_state: str, reason: Optional[str] = None, **overrides: Any) -> Payload:
    payload: Payload = {"to_state": to_state}
    if reason is not None:
        payload["reason"] = reason
    return _finalise(payload, overrides)


def revision_payload(
    expected_fare_filing_version: int,
    base_amount_cents: int = 46000,
    sale_from: str = SALE_FROM,
    sale_to: str = SALE_TO,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "base_amount_cents": int(base_amount_cents),
        "sale_from": sale_from,
        "sale_to": sale_to,
        "expected_fare_filing_version": int(expected_fare_filing_version),
    }
    return _finalise(payload, overrides)


# --- ancillaries and bundles ---------------------------------------------
def ancillary_payload(
    ancillary_code: str = "BAG20",
    name: str = "Checked bag 20kg",
    list_amount_cents: int = 7000,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "ancillary_code": ancillary_code,
        "name": name,
        "list_amount_cents": int(list_amount_cents),
    }
    return _finalise(payload, overrides)


def bundle_payload(
    bundle_code: str = "FLEX01",
    ancillary_codes: Optional[Sequence[str]] = None,
    bundle_discount_pct: float = 0.10,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "bundle_code": bundle_code,
        "ancillary_codes": list(ancillary_codes or ["BAG20"]),
        "bundle_discount_pct": bundle_discount_pct,
    }
    return _finalise(payload, overrides)


# --- agency agreements ---------------------------------------------------
def agreement_payload(
    partner_id: str,
    channel_id: str,
    expected_partner_version: int,
    proposed_incentive_pct: float = 0.025,
    incentive_cap_cents: int = 1000000,
    target_net_revenue_cents: int = 5000000,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "partner_id": partner_id,
        "channel_id": channel_id,
        "proposed_incentive_pct": proposed_incentive_pct,
        "incentive_cap_cents": int(incentive_cap_cents),
        "target_net_revenue_cents": int(target_net_revenue_cents),
        "expected_partner_version": int(expected_partner_version),
    }
    return _finalise(payload, overrides)


def negotiation_payload(
    action: str,
    proposed_incentive_pct: Optional[float] = None,
    note: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {"action": action}
    if proposed_incentive_pct is not None:
        payload["proposed_incentive_pct"] = proposed_incentive_pct
    if note is not None:
        payload["note"] = note
    return _finalise(payload, overrides)


# --- corporate contracts -------------------------------------------------
def contract_payload(
    corporate_partner_id: str,
    negotiated_fare_filing_id: str,
    effective_from: str,
    effective_to: str,
    account_code: str = "ACME-DE",
    max_offer_total_cents: int = 1000000,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "corporate_partner_id": corporate_partner_id,
        "negotiated_fare_filing_id": negotiated_fare_filing_id,
        "account_code": account_code,
        "max_offer_total_cents": int(max_offer_total_cents),
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    return _finalise(payload, overrides)


# --- offers ---------------------------------------------------------------
def offer_payload(
    channel_id: str,
    partner_id: str,
    fare_filing_id: str,
    trip_origin: str = ORIGIN_FRA,
    trip_destination: str = DESTINATION_JFK,
    departure_date: str = DEPARTURE_DATE,
    cabin: str = CABIN_ECONOMY,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "channel_id": channel_id,
        "partner_id": partner_id,
        "fare_filing_id": fare_filing_id,
        "trip_origin": trip_origin,
        "trip_destination": trip_destination,
        "departure_date": departure_date,
        "cabin": cabin,
    }
    return _finalise(payload, overrides)


def publish_payload(
    disclosure_ack_codes: Optional[Sequence[str]] = None, **overrides: Any
) -> Payload:
    payload: Payload = {}
    if disclosure_ack_codes is not None:
        payload["disclosure_ack_codes"] = list(disclosure_ack_codes)
    return _finalise(payload, overrides)


# --- orders ---------------------------------------------------------------
def order_payload(
    offer_id: str,
    disclosure_ack_codes: Optional[Sequence[str]] = None,
    corporate_tracking_ref: Optional[str] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {"offer_id": offer_id}
    if disclosure_ack_codes is not None:
        payload["disclosure_ack_codes"] = list(disclosure_ack_codes)
    if corporate_tracking_ref is not None:
        payload["corporate_tracking_ref"] = corporate_tracking_ref
    return _finalise(payload, overrides)


def payment_payload(
    action: str, payment_amount_cents: Optional[int] = None, **overrides: Any
) -> Payload:
    payload: Payload = {"action": action}
    if payment_amount_cents is not None:
        payload["payment_amount_cents"] = int(payment_amount_cents)
    return _finalise(payload, overrides)


def fulfillment_payload(action: str, **overrides: Any) -> Payload:
    return _finalise({"action": action}, overrides)


# --- service requests ----------------------------------------------------
def service_request_payload(
    request_type: str, requested_change_note: Optional[str] = None, **overrides: Any
) -> Payload:
    payload: Payload = {"request_type": request_type}
    if requested_change_note is not None:
        payload["requested_change_note"] = requested_change_note
    return _finalise(payload, overrides)


def review_payload(action: str, reason: Optional[str] = None, **overrides: Any) -> Payload:
    payload: Payload = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return _finalise(payload, overrides)


# --- certifications and connectivity tests -------------------------------
def certification_payload(
    partner_id: str, channel_id: str, env_code: str = CERT_ENV_A, **overrides: Any
) -> Payload:
    payload: Payload = {
        "partner_id": partner_id,
        "channel_id": channel_id,
        "env_code": env_code,
    }
    return _finalise(payload, overrides)


def connectivity_test_payload(
    test_code: str,
    scheduled_start: str,
    duration_minutes: int = 60,
    is_mandatory: Optional[bool] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "test_code": test_code,
        "scheduled_start": scheduled_start,
        "duration_minutes": int(duration_minutes),
    }
    if is_mandatory is not None:
        payload["is_mandatory"] = is_mandatory
    return _finalise(payload, overrides)


def outcome_payload(outcome: str, score: Optional[int] = None, **overrides: Any) -> Payload:
    payload: Payload = {"outcome": outcome}
    if score is not None:
        payload["score"] = int(score)
    return _finalise(payload, overrides)


def decision_payload(
    decision: str, readiness_variant: Optional[str] = None, **overrides: Any
) -> Payload:
    payload: Payload = {"decision": decision}
    if readiness_variant is not None:
        payload["readiness_variant"] = readiness_variant
    return _finalise(payload, overrides)


__all__: List[str] = [
    "OMIT",
    "ancillary_payload",
    "agreement_payload",
    "bundle_payload",
    "certification_payload",
    "channel_payload",
    "connectivity_test_payload",
    "content_policy_payload",
    "contract_payload",
    "decision_payload",
    "fare_filing_payload",
    "filing_state_payload",
    "full_channel_payload",
    "fulfillment_payload",
    "negotiation_payload",
    "offer_payload",
    "order_payload",
    "outcome_payload",
    "partner_payload",
    "payment_payload",
    "publish_payload",
    "review_payload",
    "revision_payload",
    "service_request_payload",
    "surcharge_rule_payload",
    "unique_code",
    "unique_suffix",
]
