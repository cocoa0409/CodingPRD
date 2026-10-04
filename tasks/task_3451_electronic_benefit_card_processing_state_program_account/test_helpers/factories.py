"""Payload factories — one per write endpoint, client-supplied fields only.

Every `_cents` value is an integer number of cents and is emitted as a JSON
number (PRD §2.6). Derived and system-managed fields are never supplied.
Optional fields are omitted from the payload unless a value is provided, so a
factory never accidentally overrides a server-side default the PRD pins
(PRD §2.11) — pass the field explicitly to override it.

Default item-file dates start at 2026-08-01, before the logical clock's
2026-09-01T00:00:00Z start (PRD §2.4), so default items are ACTIVE from the
very first request and stay reachable at every point a test advances to.
"""
from typing import Any, Dict, List, Optional

from .constants import LOGICAL_CLOCK_DEFAULT_UTC

DEFAULTS: Dict[str, Any] = {
    "STATE_CODE": "TX",
    "RETAILER_NAME": "R1",
    "ACQUIRER_REFERENCE": "ACQ1",
    "CASE_IDENTIFIER": "0000000000",
    "HEAD_OF_HOUSEHOLD_NAME": "H Test",
    "PIN": "1234",
    "NEW_PIN": "4321",
    "BENEFIT_MONTH": "2026-09",
    "ALLOTMENT_AMOUNT_CENTS": 30000,
    "FOOD_UPC": "111111111111",
    "NON_FOOD_UPC": "222222222222",
    "ITEM_EFFECTIVE_FROM": "2026-08-01",
    "INCIDENT_DESCRIPTION": "skimmed at terminal",
    "DISPUTE_REASON": "statement review",
}


def contract_payload(**overrides) -> Dict[str, Any]:
    """POST /ebt/contracts body. Only state_code is required; any §2.11 config
    field may be overridden (e.g. settlement_cutoff_hour_utc=6)."""
    payload: Dict[str, Any] = {"state_code": DEFAULTS["STATE_CODE"]}
    payload.update(overrides)
    return payload


def contract_status_payload(to: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


def program_payload(contract_id: str, program_type: str = "FOOD", **overrides) -> Dict[str, Any]:
    """POST /ebt/programs body. Optional overrides (posting_modulus,
    availability_hour_utc, expungement_inactivity_days, disaster_expiry_days,
    replacement_fee_cents, item_restriction_mode) are omitted unless given so
    they stay null (inherit the contract default). DISASTER programs also need
    disaster_window_start / disaster_window_end passed here."""
    payload: Dict[str, Any] = {"contract_id": contract_id, "program_type": program_type}
    for key in ("item_restriction_mode", "posting_modulus", "availability_hour_utc",
                "expungement_inactivity_days", "disaster_expiry_days",
                "replacement_fee_cents", "disaster_window_start", "disaster_window_end"):
        if key in overrides:
            payload[key] = overrides.pop(key)
    payload.update(overrides)
    return payload


def retailer_payload(contract_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "retailer_name": DEFAULTS["RETAILER_NAME"],
        "acquirer_reference": DEFAULTS["ACQUIRER_REFERENCE"],
    }
    payload.update(overrides)
    return payload


def retailer_status_payload(to: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(overrides)
    return payload


def item_entry(upc: str = DEFAULTS["FOOD_UPC"], food_eligible: bool = True,
               effective_from: str = DEFAULTS["ITEM_EFFECTIVE_FROM"],
               effective_to: Optional[str] = None, **overrides) -> Dict[str, Any]:
    """One item-file entry. effective_to omitted when None (open-ended)."""
    entry: Dict[str, Any] = {
        "upc": upc,
        "food_eligible": food_eligible,
        "effective_from": effective_from,
    }
    if effective_to is not None:
        entry["effective_to"] = effective_to
    entry.update(overrides)
    return entry


def item_file_payload(items: Optional[List[Dict[str, Any]]] = None, **overrides) -> Dict[str, Any]:
    """POST /ebt/retailers/{id}/item-files body (atomic upload)."""
    if items is None:
        items = [item_entry()]
    payload: Dict[str, Any] = {"items": items}
    payload.update(overrides)
    return payload


def case_account_payload(contract_id: str,
                         case_identifier: str = DEFAULTS["CASE_IDENTIFIER"],
                         head_of_household_name: str = DEFAULTS["HEAD_OF_HOUSEHOLD_NAME"],
                         **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "case_identifier": case_identifier,
        "head_of_household_name": head_of_household_name,
    }
    payload.update(overrides)
    return payload


def case_status_payload(to: str, expected_case_account_version: int, **overrides) -> Dict[str, Any]:
    """POST /ebt/case-accounts/{id}/status body — OCC field is non-optional (PRD §2.10)."""
    payload: Dict[str, Any] = {"to": to, "expected_case_account_version": expected_case_account_version}
    payload.update(overrides)
    return payload


def allotment_run_payload(program_id: str,
                          benefit_month: str = DEFAULTS["BENEFIT_MONTH"],
                          amount_cents: int = DEFAULTS["ALLOTMENT_AMOUNT_CENTS"],
                          **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "benefit_month": benefit_month,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def card_payload(case_account_id: str, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"case_account_id": case_account_id}
    payload.update(overrides)
    return payload


def activate_card_payload(pin: str = DEFAULTS["PIN"], **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"pin": pin}
    payload.update(overrides)
    return payload


def pin_reset_payload(new_pin: str = DEFAULTS["NEW_PIN"],
                      current_pin: Optional[str] = None, **overrides) -> Dict[str, Any]:
    """Cardholder callers must supply current_pin; CardholderServices omit it (PRD §3.6)."""
    payload: Dict[str, Any] = {"new_pin": new_pin}
    if current_pin is not None:
        payload["current_pin"] = current_pin
    payload.update(overrides)
    return payload


def purchase_item(upc: str = DEFAULTS["FOOD_UPC"], quantity: int = 1,
                  unit_price_cents: int = 100, **overrides) -> Dict[str, Any]:
    item: Dict[str, Any] = {"upc": upc, "quantity": quantity, "unit_price_cents": unit_price_cents}
    item.update(overrides)
    return item


def purchase_payload(card_id: str, pin: str = DEFAULTS["PIN"],
                     items: Optional[List[Dict[str, Any]]] = None, **overrides) -> Dict[str, Any]:
    """PURCHASE authorization body — items required, withdrawal_amount_cents forbidden."""
    if items is None:
        items = [purchase_item()]
    payload: Dict[str, Any] = {
        "card_id": card_id,
        "pin": pin,
        "authorization_type": "PURCHASE",
        "items": items,
    }
    payload.update(overrides)
    return payload


def withdrawal_payload(card_id: str, pin: str = DEFAULTS["PIN"],
                       withdrawal_amount_cents: int = 500, **overrides) -> Dict[str, Any]:
    """CASH_WITHDRAWAL authorization body — withdrawal_amount_cents required, items forbidden."""
    payload: Dict[str, Any] = {
        "card_id": card_id,
        "pin": pin,
        "authorization_type": "CASH_WITHDRAWAL",
        "withdrawal_amount_cents": withdrawal_amount_cents,
    }
    payload.update(overrides)
    return payload


def claim_payload(case_account_id: str, card_id: str, authorization_ids: List[str],
                  claimed_amount_cents: int,
                  incident_description: str = DEFAULTS["INCIDENT_DESCRIPTION"],
                  freeze_purse: bool = True, **overrides) -> Dict[str, Any]:
    """POST /ebt/claims body. freeze_purse defaults to true, matching the PRD default,
    and is always sent explicitly so behaviour never depends on server defaults."""
    payload: Dict[str, Any] = {
        "case_account_id": case_account_id,
        "card_id": card_id,
        "authorization_ids": authorization_ids,
        "claimed_amount_cents": claimed_amount_cents,
        "incident_description": incident_description,
        "freeze_purse": freeze_purse,
    }
    payload.update(overrides)
    return payload


def claim_status_payload(to: str, substantiated_amount_cents: Optional[int] = None,
                         **overrides) -> Dict[str, Any]:
    """substantiated_amount_cents is required when to=SUBSTANTIATED (PRD §3.8)."""
    payload: Dict[str, Any] = {"to": to}
    if substantiated_amount_cents is not None:
        payload["substantiated_amount_cents"] = substantiated_amount_cents
    payload.update(overrides)
    return payload


def reconcile_payload(actual_settled_cents: int, **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"actual_settled_cents": actual_settled_cents}
    payload.update(overrides)
    return payload


def dispute_payload(settlement_batch_id: str, disputed_amount_cents: int,
                    reason: str = DEFAULTS["DISPUTE_REASON"], **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "settlement_batch_id": settlement_batch_id,
        "disputed_amount_cents": disputed_amount_cents,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def dispute_status_payload(to: str, adjustment_cents: Optional[int] = None,
                           **overrides) -> Dict[str, Any]:
    """adjustment_cents is required when to=UPHELD (PRD §3.9)."""
    payload: Dict[str, Any] = {"to": to}
    if adjustment_cents is not None:
        payload["adjustment_cents"] = adjustment_cents
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str = LOGICAL_CLOCK_DEFAULT_UTC, **overrides) -> Dict[str, Any]:
    """Body for the unprefixed clock endpoint `POST /_clock/set_current_utc` (PRD §2.4)."""
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


__all__ = [name for name in dir() if name.endswith("_payload") or name in (
    "DEFAULTS", "item_entry", "purchase_item")]
