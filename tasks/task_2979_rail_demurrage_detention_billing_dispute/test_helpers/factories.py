"""Request payload builders.

Every factory takes ``**overrides`` and applies them with ``dict.update`` after
building its defaults, so a derived factory can never produce a duplicate
keyword argument.  All money is an ``int`` (PRD 2.6) and every instant literal
carries an explicit ``Z`` with three fractional digits (PRD 2.4).

Unique codes satisfy the declared charsets: ``customer_code`` is 1-16
characters of upper-case letters, digits and the hyphen (PRD 3.1), and the
facility, car, tariff and waybill codes are kept inside the same safe alphabet
and inside their own length limits.
"""

import itertools
import random
import string
from typing import Any, Dict

from .constants import (
    AGREEMENT_MONTH,
    BILLING_PERIOD_END,
    BILLING_PERIOD_START,
    CHANNEL_EDI,
    CYCLE_A_CONSTRUCTIVE_AT,
    CYCLE_A_NOTICE_SENT_AT,
    DECISION_ALLOWED,
    EVIDENCE_SWITCH_LIST,
    GROUNDS_RAILROAD_CAUSED_DELAY,
    METHOD_ORDERED_VS_CAPACITY,
    OWNERSHIP_RAILROAD_OWNED,
    REASON_TRACK_FULL,
    SCOPE_WHOLE_INVOICE,
)

_ALPHABET = string.ascii_uppercase + string.digits
_counter = itertools.count(1)


def _token(length: int = 6) -> str:
    """A short unique upper-case token safe for every declared charset."""
    return "".join(random.choice(_ALPHABET) for _ in range(length))


def unique_customer_code() -> str:
    """1-16 chars of upper-case letters, digits and the hyphen (PRD 3.1)."""
    return "CST-%s" % _token(6)  # 10 chars


def unique_facility_code() -> str:
    return "FAC-%s" % _token(6)


def unique_car_mark() -> str:
    return "BNSF%s" % _token(6)


def unique_tariff_code() -> str:
    return "TRF-%s" % _token(6)


def unique_waybill_number() -> str:
    """1-24 characters (PRD 3.2)."""
    return "WB-%s-%d" % (_token(6), next(_counter))


def unique_serving_station_code() -> str:
    """1-8 characters (PRD 3.1)."""
    return "ST%s" % _token(5)


# ---------------------------------------------------------------------------
# PRD 3.1 - reference data
# ---------------------------------------------------------------------------
def customer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_code": unique_customer_code(),
        "name": "Prairie Grain Terminal LLC",
        "serving_station_code": unique_serving_station_code(),
    }
    payload.update(overrides)
    return payload


def facility_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"facility_code": unique_facility_code()}
    payload.update(overrides)
    return payload


def rail_car_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "car_mark": unique_car_mark(),
        "ownership": OWNERSHIP_RAILROAD_OWNED,
    }
    payload.update(overrides)
    return payload


def tariff_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"tariff_code": unique_tariff_code()}
    payload.update(overrides)
    return payload


def credit_hold_payload(on_hold: bool = True, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "on_hold": on_hold,
        "reason": "Account past due for two billing periods.",
    }
    payload.update(overrides)
    return payload


def access_mode_payload(access_mode: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "access_mode": access_mode,
        "reason": "Operating restriction recorded by the railroad.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PRD 3.2 - 3.5 - the placement cycle
# ---------------------------------------------------------------------------
def placement_cycle_payload(
    customer_id: str,
    rail_car_id: str,
    facility_id: str,
    tariff_rule_set_id: str,
    expected_rail_car_version: int,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "rail_car_id": rail_car_id,
        "facility_id": facility_id,
        "tariff_rule_set_id": tariff_rule_set_id,
        "waybill_number": unique_waybill_number(),
        "expected_rail_car_version": expected_rail_car_version,
    }
    payload.update(overrides)
    return payload


def constructive_placement_payload(
    constructive_placement_at: str = CYCLE_A_CONSTRUCTIVE_AT, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "constructive_placement_at": constructive_placement_at,
        "reason_code": REASON_TRACK_FULL,
    }
    payload.update(overrides)
    return payload


def notify_payload(
    sent_at: str = CYCLE_A_NOTICE_SENT_AT, channel: str = CHANNEL_EDI, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"channel": channel, "sent_at": sent_at}
    payload.update(overrides)
    return payload


def acknowledge_payload(ack_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ack_at": ack_at}
    payload.update(overrides)
    return payload


def actual_placement_payload(actual_placement_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_placement_at": actual_placement_at}
    payload.update(overrides)
    return payload


def refuse_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"refusal_reason": "Plant unloading crew unavailable."}
    payload.update(overrides)
    return payload


def release_payload(released_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"released_at": released_at}
    payload.update(overrides)
    return payload


def void_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"void_reason": "Waybill cancelled by the shipper."}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PRD 3.7 - invoicing and average agreements
# ---------------------------------------------------------------------------
def invoice_payload(customer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "billing_period_start": BILLING_PERIOD_START,
        "billing_period_end": BILLING_PERIOD_END,
    }
    payload.update(overrides)
    return payload


def average_agreement_payload(customer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "agreement_month": AGREEMENT_MONTH,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PRD 3.6 - bunching claims
# ---------------------------------------------------------------------------
def bunching_claim_payload(
    customer_id: str,
    cluster_window_start: str,
    cluster_window_end: str,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customer_id": customer_id,
        "cluster_window_start": cluster_window_start,
        "cluster_window_end": cluster_window_end,
        "method": METHOD_ORDERED_VS_CAPACITY,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PRD 3.8 - disputes
# ---------------------------------------------------------------------------
def dispute_payload(
    invoice_id: str,
    expected_invoice_version: int,
    claimed_credit_cents: int,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "invoice_id": invoice_id,
        "scope": SCOPE_WHOLE_INVOICE,
        "grounds": GROUNDS_RAILROAD_CAUSED_DELAY,
        "narrative": "The railroad held the car beyond the tariff free time.",
        "claimed_credit_cents": claimed_credit_cents,
        "expected_invoice_version": expected_invoice_version,
    }
    payload.update(overrides)
    return payload


def evidence_payload(
    observed_at: str,
    evidence_type: str = EVIDENCE_SWITCH_LIST,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_type": evidence_type,
        "observed_at": observed_at,
        "description": "Yard switch list recording the hold on the inbound car.",
    }
    payload.update(overrides)
    return payload


def request_info_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "requested_items": "Provide the gate log for the disputed dates."
    }
    payload.update(overrides)
    return payload


def decide_payload(
    decision: str = DECISION_ALLOWED,
    allowance_pct: Any = 1,
    **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision": decision,
        "allowance_pct": allowance_pct,
        "decision_rationale": "Railroad-caused delay is established on the record.",
    }
    payload.update(overrides)
    return payload


def appeal_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "appeal_narrative": "The first-level allowance understates the delay."
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PRD 3.9 - regulatory complaints
# ---------------------------------------------------------------------------
def complaint_payload(
    demurrage_dispute_id: str, complaint_type: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "demurrage_dispute_id": demurrage_dispute_id,
        "complaint_type": complaint_type,
        "docket_narrative": "The published tariff rate is unreasonable on this lane.",
    }
    payload.update(overrides)
    return payload


def answer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "answer_narrative": "The tariff was applied exactly as published."
    }
    payload.update(overrides)
    return payload


def complaint_decision_payload(
    outcome: str, ordered_credit_cents: int = 0, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "ordered_credit_cents": ordered_credit_cents,
    }
    payload.update(overrides)
    return payload
