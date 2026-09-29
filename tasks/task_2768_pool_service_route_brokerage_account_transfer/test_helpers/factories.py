"""Payload factories — one per write endpoint, client-supplied fields only.

Every `_cents` value is an integer number of cents and is emitted as a JSON
number, never a string (PRD §2.6). Derived fields are never supplied.
"""
from typing import Any, Dict

DEFAULTS: Dict[str, Any] = {
    "CLOCK_UTC": "2026-08-01T00:00:00Z",
    "STATE_CODE": "AZ",
    "SELLER_LEGAL_NAME": "Sun Valley Pools LLC",
    "SELLER_LICENSE_NUMBER": "AZ-PA-1001",
    "BUYER_LEGAL_NAME": "Desert Blue Route Co",
    "REGION_CODE": "PHX-NE",
    "CUSTOMER_REF": "A1-SUNRISE",
    "LENDER_NAME": "Sonoran Community Bank",
}


def clock_payload(current_utc: str = DEFAULTS["CLOCK_UTC"], **overrides) -> Dict[str, Any]:
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def state_license_profile_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "state_code": DEFAULTS["STATE_CODE"],
        "required_permit_types": ["PESTICIDE_APPLICATOR", "BUSINESS_TAX"],
        "reciprocity_states": ["NV"],
        "transfer_processing_days": 21,
        "cooling_off_days": 14,
        "provisional_operation_allowed": False,
    }
    payload.update(overrides)
    return payload


def seller_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": DEFAULTS["SELLER_LEGAL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "license_number": DEFAULTS["SELLER_LICENSE_NUMBER"],
    }
    payload.update(overrides)
    return payload


def suspend_seller_payload(**overrides) -> Dict[str, Any]:
    payload = {"suspension_reason_code": "LICENSE_LAPSED"}
    payload.update(overrides)
    return payload


def buyer_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "legal_name": DEFAULTS["BUYER_LEGAL_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "license_status": "LICENSED",
        "prequalified_amount_cents": 30000000,
    }
    payload.update(overrides)
    return payload


def qualify_buyer_payload(decision: str = "APPROVE", **overrides) -> Dict[str, Any]:
    payload = {"decision": decision}
    payload.update(overrides)
    return payload


def route_listing_payload(seller_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "seller_id": seller_id,
        "region_code": DEFAULTS["REGION_CODE"],
        "state_code": DEFAULTS["STATE_CODE"],
        "asking_price_cents": 460000,
        "listed_mrr_cents": 43000,
        "listed_account_count": 3,
        "exclusive_start_date": "2026-08-01",
        "exclusive_end_date": "2026-11-01",
    }
    payload.update(overrides)
    return payload


def withdraw_listing_payload(**overrides) -> Dict[str, Any]:
    payload = {"withdrawal_reason_code": "SELLER_CHANGED_MIND"}
    payload.update(overrides)
    return payload


def route_valuation_payload(basis: str, expected_listing_version: int, **overrides) -> Dict[str, Any]:
    payload = {"basis": basis, "expected_listing_version": expected_listing_version}
    payload.update(overrides)
    return payload


def service_account_payload(listing_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "listing_id": listing_id,
        "customer_ref": DEFAULTS["CUSTOMER_REF"],
        "service_start_date": "2019-03-15",
        "route_day": "TUE",
        "monthly_service_fee_cents": 12000,
        "avg_monthly_chemical_cents": 4000,
        "avg_monthly_repair_cents": 1500,
        "chemical_billing_method": "INCLUDED",
        "billing_frequency": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def exclude_account_payload(**overrides) -> Dict[str, Any]:
    payload = {"exclusion_reason_code": "DISPUTED_HISTORY"}
    payload.update(overrides)
    return payload


def introduce_account_payload(deal_id: str, introduction_date: str, **overrides) -> Dict[str, Any]:
    payload = {"deal_id": deal_id, "introduction_date": introduction_date}
    payload.update(overrides)
    return payload


def replacement_account_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "customer_ref": "A2-MESA-REPLACEMENT",
        "service_start_date": "2021-04-01",
        "route_day": "MON",
        "monthly_service_fee_cents": 12000,
        "avg_monthly_chemical_cents": 0,
        "avg_monthly_repair_cents": 0,
        "chemical_billing_method": "INCLUDED",
        "billing_frequency": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def billing_history_record_payload(account_id: str, period_month: str, **overrides) -> Dict[str, Any]:
    payload = {
        "account_id": account_id,
        "period_month": period_month,
        "billed_service_cents": 12000,
        "billed_chemical_cents": 4000,
        "billed_repair_cents": 1500,
        "collected_cents": 17500,
        "source": "BANK_VERIFIED",
    }
    payload.update(overrides)
    return payload


def deal_payload(listing_id: str, buyer_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "listing_id": listing_id,
        "buyer_id": buyer_id,
        "offer_price_cents": 340000,
        "financing_type": "SELLER_NOTE",
        "down_payment_cents": 120000,
        "note_principal_cents": 220000,
        "retention_guarantee_days": 90,
    }
    payload.update(overrides)
    return payload


def counter_offer_payload(counter_price_cents: int, **overrides) -> Dict[str, Any]:
    payload = {"counter_price_cents": counter_price_cents}
    payload.update(overrides)
    return payload


def reoffer_payload(offer_price_cents: int, down_payment_cents: int,
                    note_principal_cents: int, **overrides) -> Dict[str, Any]:
    payload = {
        "offer_price_cents": offer_price_cents,
        "down_payment_cents": down_payment_cents,
        "note_principal_cents": note_principal_cents,
    }
    payload.update(overrides)
    return payload


def accept_deal_payload(retention_guarantee_days: int = 90, **overrides) -> Dict[str, Any]:
    payload = {"retention_guarantee_days": retention_guarantee_days}
    payload.update(overrides)
    return payload


def clear_diligence_payload(valuation_id: str, **overrides) -> Dict[str, Any]:
    payload = {"valuation_id": valuation_id}
    payload.update(overrides)
    return payload


def approve_financing_payload(approved_amount_cents: int, **overrides) -> Dict[str, Any]:
    payload = {
        "lender_name": DEFAULTS["LENDER_NAME"],
        "approved_amount_cents": approved_amount_cents,
    }
    payload.update(overrides)
    return payload


def terminate_deal_payload(**overrides) -> Dict[str, Any]:
    payload = {"termination_reason_code": "BUYER_WITHDREW"}
    payload.update(overrides)
    return payload


def escrow_deposit_payload(amount_cents: int, **overrides) -> Dict[str, Any]:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def apply_license_transfer_payload(applied_on: str, **overrides) -> Dict[str, Any]:
    payload = {"applied_on": applied_on}
    payload.update(overrides)
    return payload


def decide_license_transfer_payload(decision: str, decided_on: str, **overrides) -> Dict[str, Any]:
    payload = {"decision": decision, "decided_on": decided_on}
    payload.update(overrides)
    return payload


def waive_license_transfer_payload(waiver_basis: str = "RECIPROCITY_HOME_STATE_LICENSE",
                                   **overrides) -> Dict[str, Any]:
    payload = {"waiver_basis": waiver_basis}
    payload.update(overrides)
    return payload


def attrition_event_payload(deal_id: str, account_id: str, event_type: str,
                            effective_date: str, mrr_delta_cents: int,
                            attributed_to: str, expected_deal_version: int,
                            **overrides) -> Dict[str, Any]:
    payload = {
        "deal_id": deal_id,
        "account_id": account_id,
        "event_type": event_type,
        "effective_date": effective_date,
        "mrr_delta_cents": mrr_delta_cents,
        "attributed_to": attributed_to,
        "expected_deal_version": expected_deal_version,
    }
    payload.update(overrides)
    return payload


def clawback_settlement_payload(deal_id: str, remedy_basis: str = "REPLACEMENT_BASIS",
                                **overrides) -> Dict[str, Any]:
    payload = {"deal_id": deal_id, "remedy_basis": remedy_basis}
    payload.update(overrides)
    return payload


def propose_settlement_payload(adjustment_cents: int, **overrides) -> Dict[str, Any]:
    payload = {"adjustment_cents": adjustment_cents}
    payload.update(overrides)
    return payload


def dispute_settlement_payload(**overrides) -> Dict[str, Any]:
    payload = {"dispute_reason_code": "VALUATION_DISPUTED"}
    payload.update(overrides)
    return payload


def settle_settlement_payload(adjustment_cents: int, **overrides) -> Dict[str, Any]:
    payload = {"adjustment_cents": adjustment_cents}
    payload.update(overrides)
    return payload
