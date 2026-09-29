"""Request-payload builders.

Two disciplines are enforced here: every monetary figure is emitted as a JSON
integer of cents, and every field that names an instant is emitted as a full
ISO 8601 UTC instant rather than a date-only literal.
"""

import itertools
from typing import Any, Dict, Optional

from . import constants as K
from .types import (
    ChargeSettlementAction,
    DeclineReason,
    DeliveryMode,
    FeeWaiverMode,
    InvoiceSettleAction,
    ItemType,
    MaterialType,
    PatronType,
    PodDecision,
    SelectionPolicy,
    ServiceType,
    SettlementMode,
    ShipmentCondition,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    return f"{next(_counter):04d}"


def _clean(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the sentinel `...`, keeping explicit `None`."""
    return {key: value for key, value in payload.items() if value is not ...}


# --- Patrons -----------------------------------------------------------------
def patron_payload(
    external_id: Optional[str] = None,
    full_name: str = "Dana Okonkwo",
    email: str = "dana.okonkwo@example.edu",
    patron_type: str = PatronType.FACULTY,
    department: str = "HIST",
    max_open_requests: Any = ...,
    max_concurrent_loans: Any = ...,
    unpaid_balance_cap_cents: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "external_id": external_id or f"CAMPUS-{unique_suffix()}",
            "full_name": full_name,
            "email": email,
            "patron_type": patron_type,
            "department": department,
            "max_open_requests": max_open_requests,
            "max_concurrent_loans": max_concurrent_loans,
            "unpaid_balance_cap_cents": unpaid_balance_cap_cents,
        }
    )


def patron_update_payload(
    status: Any = ...,
    email: Any = ...,
    max_open_requests: Any = ...,
    max_concurrent_loans: Any = ...,
    unpaid_balance_cap_cents: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "status": status,
            "email": email,
            "max_open_requests": max_open_requests,
            "max_concurrent_loans": max_concurrent_loans,
            "unpaid_balance_cap_cents": unpaid_balance_cap_cents,
        }
    )


def infraction_payload(
    kind: str,
    count: Any = ...,
    unpaid_amount_cents: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "kind": kind,
            "count": count,
            "unpaid_amount_cents": unpaid_amount_cents,
        }
    )


# --- Partners ----------------------------------------------------------------
def partner_payload(
    code: Optional[str] = None,
    name: str = "Northgate University Library",
    consortium_code: str = "NGC",
    base_lending_fee_cents: int = 2000,
    avg_turnaround_days: int = 4,
    ships_physical: bool = True,
    supplies_electronic: bool = True,
    allows_renewals: bool = True,
    loan_period_days: int = 21,
    max_renewals: int = 2,
    status: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "code": code or f"P{unique_suffix()}",
            "name": name,
            "consortium_code": consortium_code,
            "base_lending_fee_cents": base_lending_fee_cents,
            "avg_turnaround_days": avg_turnaround_days,
            "ships_physical": ships_physical,
            "supplies_electronic": supplies_electronic,
            "allows_renewals": allows_renewals,
            "loan_period_days": loan_period_days,
            "max_renewals": max_renewals,
            "status": status,
        }
    )


def partner_update_payload(
    status: Any = ...,
    base_lending_fee_cents: Any = ...,
    avg_turnaround_days: Any = ...,
    ships_physical: Any = ...,
    supplies_electronic: Any = ...,
    allows_renewals: Any = ...,
    loan_period_days: Any = ...,
    max_renewals: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "status": status,
            "base_lending_fee_cents": base_lending_fee_cents,
            "avg_turnaround_days": avg_turnaround_days,
            "ships_physical": ships_physical,
            "supplies_electronic": supplies_electronic,
            "allows_renewals": allows_renewals,
            "loan_period_days": loan_period_days,
            "max_renewals": max_renewals,
        }
    )


# --- Reciprocity agreements --------------------------------------------------
def agreement_payload(
    partner_id: str,
    expected_partner_version: int,
    fee_waiver_mode: str = FeeWaiverMode.NONE,
    settlement_mode: str = SettlementMode.GROSS,
    turnaround_guarantee_days: int = 5,
    effective_from: str = "2026-07-01T00:00:00.000Z",
    effective_to: str = "2026-10-01T00:00:00.000Z",
    capped_waiver_cents: Any = ...,
    balance_tolerance_items: Any = ...,
    supersedes_agreement_id: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "partner_id": partner_id,
            "expected_partner_version": expected_partner_version,
            "fee_waiver_mode": fee_waiver_mode,
            "settlement_mode": settlement_mode,
            "turnaround_guarantee_days": turnaround_guarantee_days,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "capped_waiver_cents": capped_waiver_cents,
            "balance_tolerance_items": balance_tolerance_items,
            "supersedes_agreement_id": supersedes_agreement_id,
        }
    )


# --- Rotas and entries -------------------------------------------------------
def rota_payload(
    name: Optional[str] = None,
    material_type: str = MaterialType.LOAN,
    selection_policy: str = SelectionPolicy.LANDED_COST,
    max_attempts: Any = ...,
    auto_escalate_pod: Any = ...,
    offer_response_hours: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "name": name or f"Rota {unique_suffix()}",
            "material_type": material_type,
            "selection_policy": selection_policy,
            "max_attempts": max_attempts,
            "auto_escalate_pod": auto_escalate_pod,
            "offer_response_hours": offer_response_hours,
        }
    )


def rota_entry_payload(
    rota_id: str,
    partner_id: str,
    expected_rota_version: int,
    manual_rank: int = 1,
    quoted_fee_cents: int = 2000,
    quoted_turnaround_days: int = 4,
    is_enabled: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "rota_id": rota_id,
            "partner_id": partner_id,
            "expected_rota_version": expected_rota_version,
            "manual_rank": manual_rank,
            "quoted_fee_cents": quoted_fee_cents,
            "quoted_turnaround_days": quoted_turnaround_days,
            "is_enabled": is_enabled,
        }
    )


def rota_entry_update_payload(
    is_enabled: Any = ...,
    manual_rank: Any = ...,
) -> Dict[str, Any]:
    return _clean({"is_enabled": is_enabled, "manual_rank": manual_rank})


# --- Bibliographic records ---------------------------------------------------
def bib_item_payload(
    title: str = "Atlantic Trade Networks",
    item_type: str = ItemType.BOOK,
    publication_year: int = 2024,
    issn: Any = ...,
    isbn: Any = ...,
    journal_title: Any = ...,
    local_holding_status: Any = ...,
    licensed_access_status: Any = ...,
    embargo_months: Any = ...,
    list_price_cents: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "title": title,
            "item_type": item_type,
            "publication_year": publication_year,
            "issn": issn,
            "isbn": isbn,
            "journal_title": journal_title,
            "local_holding_status": local_holding_status,
            "licensed_access_status": licensed_access_status,
            "embargo_months": embargo_months,
            "list_price_cents": list_price_cents,
        }
    )


def article_bib_item_payload(
    issn: str = "1234-5678",
    title: str = "Shipping Ledgers of the Baltic",
    publication_year: int = 2024,
    journal_title: str = "Journal of Maritime History",
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = bib_item_payload(
        title=title,
        item_type=ItemType.ARTICLE,
        publication_year=publication_year,
        issn=issn,
        journal_title=journal_title,
        **kwargs,
    )
    return payload


def bib_item_update_payload(
    local_holding_status: Any = ...,
    licensed_access_status: Any = ...,
    embargo_months: Any = ...,
    list_price_cents: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "local_holding_status": local_holding_status,
            "licensed_access_status": licensed_access_status,
            "embargo_months": embargo_months,
            "list_price_cents": list_price_cents,
        }
    )


# --- Requests ----------------------------------------------------------------
def request_payload(
    patron_id: str,
    bib_item_id: str,
    rota_id: str,
    service_type: str = ServiceType.LOAN,
    delivery_mode: str = DeliveryMode.PICKUP,
    needed_by: str = "2026-08-15T00:00:00.000Z",
    max_supply_fee_cents: int = 10000,
    pages_requested: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "patron_id": patron_id,
            "bib_item_id": bib_item_id,
            "rota_id": rota_id,
            "service_type": service_type,
            "delivery_mode": delivery_mode,
            "needed_by": needed_by,
            "max_supply_fee_cents": max_supply_fee_cents,
            "pages_requested": pages_requested,
        }
    )


def copy_request_payload(
    patron_id: str,
    bib_item_id: str,
    rota_id: str,
    pages_requested: int = 20,
    needed_by: str = "2026-08-15T00:00:00.000Z",
    max_supply_fee_cents: int = 10000,
) -> Dict[str, Any]:
    """A `COPY` request, whose `delivery_mode` must be `ELECTRONIC`."""
    return request_payload(
        patron_id=patron_id,
        bib_item_id=bib_item_id,
        rota_id=rota_id,
        service_type=ServiceType.COPY,
        delivery_mode=DeliveryMode.ELECTRONIC,
        needed_by=needed_by,
        max_supply_fee_cents=max_supply_fee_cents,
        pages_requested=pages_requested,
    )


def royalty_clearance_payload(royalty_cents: int) -> Dict[str, Any]:
    return {"royalty_cents": royalty_cents}


def decline_payload(decline_reason: str = DeclineReason.NOT_HELD) -> Dict[str, Any]:
    return {"decline_reason": decline_reason}


def escalate_payload(vendor: str = "Meridian Books") -> Dict[str, Any]:
    return {"vendor": vendor}


def pod_decision_payload(
    decision: str = PodDecision.APPROVE,
    decision_note: Any = ...,
) -> Dict[str, Any]:
    return _clean({"decision": decision, "decision_note": decision_note})


# --- Shipments ---------------------------------------------------------------
def shipment_payload(
    carrier: str = "Consortium Courier",
    tracking_code: Optional[str] = None,
    insured_value_cents: Any = ...,
) -> Dict[str, Any]:
    return _clean(
        {
            "carrier": carrier,
            "tracking_code": tracking_code or f"TRK-{unique_suffix()}",
            "insured_value_cents": insured_value_cents,
        }
    )


def lender_confirm_payload(
    condition: str = ShipmentCondition.OK,
    damage_fee_cents: Any = ...,
) -> Dict[str, Any]:
    return _clean({"condition": condition, "damage_fee_cents": damage_fee_cents})


# --- Loans -------------------------------------------------------------------
def recall_payload(grace_days: Any = ...) -> Dict[str, Any]:
    return _clean({"grace_days": grace_days})


def pay_settlement_payload(payment_cents: int) -> Dict[str, Any]:
    return {"action": ChargeSettlementAction.PAY, "payment_cents": payment_cents}


def waive_settlement_payload() -> Dict[str, Any]:
    return {"action": ChargeSettlementAction.WAIVE}


# --- Electronic delivery -----------------------------------------------------
def electronic_delivery_payload(
    file_token: Optional[str] = None,
    pages_delivered: int = 20,
) -> Dict[str, Any]:
    return {
        "file_token": file_token or f"scan-token-{unique_suffix()}",
        "pages_delivered": pages_delivered,
    }


# --- Settlement --------------------------------------------------------------
def lending_charge_payload(
    partner_id: str,
    item_title: str = "Baltic Shipping Registers",
    service_type: str = ServiceType.LOAN,
    charge_cents: int = 2000,
    incurred_at: str = "2026-08-05T09:00:00.000Z",
) -> Dict[str, Any]:
    return {
        "partner_id": partner_id,
        "item_title": item_title,
        "service_type": service_type,
        "charge_cents": charge_cents,
        "incurred_at": incurred_at,
    }


def invoice_payload(
    period_month: str,
    expected_partner_version: int,
) -> Dict[str, Any]:
    return {
        "period_month": period_month,
        "expected_partner_version": expected_partner_version,
    }


def invoice_settle_payload(
    action: str = InvoiceSettleAction.PAY,
    dispute_reason: Any = ...,
) -> Dict[str, Any]:
    return _clean({"action": action, "dispute_reason": dispute_reason})


# --- Convenience money literals ---------------------------------------------
DEFAULT_QUOTED_FEE_CENTS = 2000
DEFAULT_QUOTED_TURNAROUND_DAYS = 4
DEFAULT_LIST_PRICE_CENTS = 9000
FALLBACK_REPLACEMENT_COST_CENTS = K.DEFAULT_REPLACEMENT_COST_CENTS
