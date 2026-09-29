"""Payload factories.

Each builder produces only the input fields the PRD declares for its endpoint,
with money as JSON numbers (never strings) and instants as full ISO-8601 UTC
instants with millisecond precision. Overrides are applied last so that a test
can vary one field without restating the rest, and passing None keeps an
explicit null in the body.
"""

import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    BUSINESS_DATE_D1,
    STANDARD_OUT_OF_ORDER_ROOM_COUNT,
    STANDARD_PROPERTY,
)
from .types import Payload

_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):04d}"


# ---------------------------------------------------------------------------
# HotelProperty
# ---------------------------------------------------------------------------


def build_property_payload(**overrides: Any) -> Payload:
    payload: Payload = dict(STANDARD_PROPERTY)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Outlet
# ---------------------------------------------------------------------------


def build_outlet_payload(property_id: str, **overrides: Any) -> Payload:
    suffix = unique_suffix()
    payload: Payload = {
        "property_id": property_id,
        "outlet_code": f"OUT-{suffix}",
        "outlet_name": f"Harbor Outlet {suffix}",
        "outlet_type": "FB_OUTLET",
        "requires_shift_settlement": True,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# BusinessDate
# ---------------------------------------------------------------------------


def build_business_date_payload(
    property_id: str, business_date: str = BUSINESS_DATE_D1, **overrides: Any
) -> Payload:
    payload: Payload = {
        "property_id": property_id,
        "business_date": business_date,
        "out_of_order_room_count": STANDARD_OUT_OF_ORDER_ROOM_COUNT,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Folio
# ---------------------------------------------------------------------------


def build_folio_payload(
    property_id: str, arrival_business_date_id: str, **overrides: Any
) -> Payload:
    suffix = unique_suffix()
    payload: Payload = {
        "property_id": property_id,
        "arrival_business_date_id": arrival_business_date_id,
        "confirmation_code": f"CF-{suffix}",
        "guest_name": f"Guest {suffix}",
        "room_number": f"{300 + int(suffix)}",
        "nights_count": 1,
        "contracted_rate_amount": 200.00,
        "rate_plan_code": "BAR",
        "market_segment": "TRANSIENT",
        "settlement_method": "CASH",
        "scheduled_checkout_at": "2026-08-02T11:00:00.000Z",
    }
    payload.update(overrides)
    return payload


def build_check_out_payload(business_date_id: str, **overrides: Any) -> Payload:
    payload: Payload = {"business_date_id": business_date_id}
    payload.update(overrides)
    return payload


def build_payment_payload(
    business_date_id: str, amount: float, **overrides: Any
) -> Payload:
    payload: Payload = {"business_date_id": business_date_id, "amount": amount}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# JournalPosting
# ---------------------------------------------------------------------------


def build_journal_posting_payload(
    business_date_id: str,
    charge_type: str = "MISC_CHARGE",
    amount: float = 25.00,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "business_date_id": business_date_id,
        "charge_type": charge_type,
        "amount": amount,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# OutletTicket
# ---------------------------------------------------------------------------


def build_outlet_ticket_payload(
    outlet_id: str,
    business_date_id: str,
    gross_amount: float = 120.00,
    **overrides: Any,
) -> Payload:
    suffix = unique_suffix()
    payload: Payload = {
        "outlet_id": outlet_id,
        "business_date_id": business_date_id,
        "ticket_number": f"TK-{suffix}",
        "gross_amount": gross_amount,
        "settlement_type": "CASH",
        "opened_at": "2026-08-01T17:30:00.000Z",
    }
    payload.update(overrides)
    return payload


def build_close_ticket_payload(transmitted_at: str, **overrides: Any) -> Payload:
    payload: Payload = {"transmitted_at": transmitted_at}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SettlementBatch
# ---------------------------------------------------------------------------


def build_settlement_batch_payload(
    business_date_id: str,
    outlet_id: str,
    declared_amount: float,
    shift_start_at: str = "2026-08-01T14:00:00.000Z",
    shift_end_at: str = "2026-08-01T22:00:00.000Z",
    tender_type: str = "CASH",
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "business_date_id": business_date_id,
        "outlet_id": outlet_id,
        "tender_type": tender_type,
        "shift_start_at": shift_start_at,
        "shift_end_at": shift_end_at,
        "declared_amount": declared_amount,
    }
    payload.update(overrides)
    return payload


def build_redeclare_payload(declared_amount: float, **overrides: Any) -> Payload:
    payload: Payload = {"declared_amount": declared_amount}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# LedgerAccount
# ---------------------------------------------------------------------------


def build_ledger_account_payload(
    property_id: str, ledger_type: str = "CITY_LEDGER", **overrides: Any
) -> Payload:
    suffix = unique_suffix()
    payload: Payload = {
        "property_id": property_id,
        "ledger_type": ledger_type,
        "account_code": f"LA-{suffix}",
        "gl_account_code": "1230",
        "opening_balance_amount": 0.00,
        "credit_limit_amount": 100000.00,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Allowance
# ---------------------------------------------------------------------------


def build_allowance_payload(
    folio_id: str,
    business_date_id: str,
    requested_amount: float = 100.00,
    reason_code: str = "SERVICE_RECOVERY",
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "folio_id": folio_id,
        "business_date_id": business_date_id,
        "requested_amount": requested_amount,
        "reason_code": reason_code,
        "narrative": "Guest recovery agreed at the desk.",
    }
    payload.update(overrides)
    return payload


def build_approve_payload(approved_amount: float, **overrides: Any) -> Payload:
    payload: Payload = {"approved_amount": approved_amount}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AuthorizationDocument
# ---------------------------------------------------------------------------


def build_authorization_document_payload(
    property_id: str,
    doc_type: str = "COMP_ROOM",
    valid_from_date: str = "2026-08-01",
    valid_to_date: str = "2026-08-03",
    **overrides: Any,
) -> Payload:
    suffix = unique_suffix()
    payload: Payload = {
        "property_id": property_id,
        "doc_type": doc_type,
        "authorized_by_name": "V. Holt, GM",
        "document_reference": f"DOC-{suffix}",
        "valid_from_date": valid_from_date,
        "valid_to_date": valid_to_date,
    }
    payload.update(overrides)
    return payload


def build_review_payload(decision: str = "APPROVE", **overrides: Any) -> Payload:
    payload: Payload = {"decision": decision}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# CardAuthorization
# ---------------------------------------------------------------------------


def build_card_authorization_payload(
    folio_id: str,
    authorized_amount: float = 500.00,
    obtained_at: str = "2026-08-01T08:00:00.000Z",
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "folio_id": folio_id,
        "obtained_at": obtained_at,
        "authorized_amount": authorized_amount,
    }
    payload.update(overrides)
    return payload


def build_decline_payload(decline_code: str = "INSUFFICIENT_FUNDS", **overrides: Any) -> Payload:
    payload: Payload = {"decline_code": decline_code}
    payload.update(overrides)
    return payload


def build_capture_payload(
    captured_amount: float, business_date_id: str, **overrides: Any
) -> Payload:
    payload: Payload = {
        "captured_amount": captured_amount,
        "business_date_id": business_date_id,
    }
    payload.update(overrides)
    return payload


def build_follow_up_payload(follow_up_action: str, **overrides: Any) -> Payload:
    payload: Payload = {"follow_up_action": follow_up_action}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RevenueReport
# ---------------------------------------------------------------------------


def build_revenue_report_payload(
    business_date_id: str,
    expected_business_date_version: int,
    recipient_role_list: Optional[List[str]] = None,
    **overrides: Any,
) -> Payload:
    payload: Payload = {
        "business_date_id": business_date_id,
        "recipient_role_list": (
            ["Controller"] if recipient_role_list is None else recipient_role_list
        ),
        "expected_business_date_version": expected_business_date_version,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AccountingPeriod
# ---------------------------------------------------------------------------


def build_tie_out_payload(gl_control_total_amount: float, **overrides: Any) -> Payload:
    payload: Payload = {"gl_control_total_amount": gl_control_total_amount}
    payload.update(overrides)
    return payload


def without(payload: Dict[str, Any], *fields: str) -> Dict[str, Any]:
    """Copy a payload with the named fields removed, for required-field tests."""
    return {k: v for k, v in payload.items() if k not in fields}
