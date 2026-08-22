"""Payload factories — one per resource, input fields only."""

from .constants import CLOCK_LISTED, TEST_DEFAULTS


def clock_payload(to_iso8601: str, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_bpo_vendor_payload(**overrides) -> dict:
    payload = {
        "vendor_name": "Sierra Valuation Partners",
        "license_state": "NV",
        "daily_inspection_capacity": 2,
    }
    payload.update(overrides)
    return payload


def create_case_payload(**overrides) -> dict:
    payload = {
        "property_address": "118 Larkspur Ln, Reno NV",
        "investor_type": "GSE",
        "unpaid_principal_balance_cents": TEST_DEFAULTS["UPB_CENTS"],
        "servicer_name": TEST_DEFAULTS["SERVICER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_hardship_package_payload(**overrides) -> dict:
    payload = {
        "hardship_reason": "JOB_LOSS",
        "monthly_income_cents": 380_000,
        "monthly_expenses_cents": 512_000,
        "liquid_assets_cents": 640_000,
    }
    payload.update(overrides)
    return payload


def file_document_payload(doc_type: str, **overrides) -> dict:
    payload = {
        "doc_type": doc_type,
        "issued_on": TEST_DEFAULTS["DOC_ISSUED_ON"],
        "reference_label": f"{doc_type}-1",
    }
    payload.update(overrides)
    return payload


def review_document_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def package_decision_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_listing_payload(**overrides) -> dict:
    payload = {
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "commission_pct": TEST_DEFAULTS["COMMISSION_PCT"],
        "listed_at": CLOCK_LISTED,
    }
    payload.update(overrides)
    return payload


def price_reduction_payload(new_list_price_cents: int, **overrides) -> dict:
    payload = {"new_list_price_cents": new_list_price_cents}
    payload.update(overrides)
    return payload


def withdraw_listing_payload(ended_at: str, **overrides) -> dict:
    payload = {"ended_at": ended_at}
    payload.update(overrides)
    return payload


def create_offer_payload(**overrides) -> dict:
    payload = {
        "buyer_name": "R. Alvarez",
        "buyer_financing": "CASH",
        "offer_price_cents": TEST_DEFAULTS["OFFER_PRICE_CENTS"],
        "earnest_money_cents": TEST_DEFAULTS["EARNEST_MONEY_CENTS"],
        "requested_closing_days": TEST_DEFAULTS["REQUESTED_CLOSING_DAYS"],
    }
    payload.update(overrides)
    return payload


def servicer_decision_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def revise_offer_payload(offer_price_cents: int, **overrides) -> dict:
    payload = {"offer_price_cents": offer_price_cents}
    payload.update(overrides)
    return payload


def create_net_sheet_payload(variant: str, expected_offer_version: int, **overrides) -> dict:
    payload = {
        "variant": variant,
        "title_escrow_cents": TEST_DEFAULTS["TITLE_ESCROW_CENTS"],
        "property_tax_arrears_cents": TEST_DEFAULTS["PROPERTY_TAX_ARREARS_CENTS"],
        "hoa_arrears_cents": TEST_DEFAULTS["HOA_ARREARS_CENTS"],
        "expected_offer_version": expected_offer_version,
    }
    payload.update(overrides)
    return payload


def order_valuation_payload(vendor_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "valuation_type": "BPO_EXTERIOR",
        "effective_date": "2026-08-06T00:00:00Z",
        "inspection_start": "2026-08-06T09:00:00Z",
        "inspection_end": "2026-08-06T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def record_value_payload(value_cents: int, **overrides) -> dict:
    payload = {"value_cents": value_cents}
    payload.update(overrides)
    return payload


def file_dispute_payload(claimed_value_cents: int, comparable_count: int, **overrides) -> dict:
    payload = {
        "claimed_value_cents": claimed_value_cents,
        "comparable_count": comparable_count,
        "rationale": "Closed comps above the BPO",
    }
    payload.update(overrides)
    return payload


def adjudicate_payload(resolution: str, **overrides) -> dict:
    payload = {"resolution": resolution}
    payload.update(overrides)
    return payload


def create_junior_lien_payload(**overrides) -> dict:
    payload = {
        "lien_position": 2,
        "holder_name": "Truckee Credit Union",
        "holder_user_id": TEST_DEFAULTS["HOLDER_USER_ID"],
        "balance_cents": TEST_DEFAULTS["LIEN_BALANCE_CENTS"],
    }
    payload.update(overrides)
    return payload


def lien_demand_payload(demand_cents: int, **overrides) -> dict:
    payload = {"demand_cents": demand_cents}
    payload.update(overrides)
    return payload


def lien_response_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_mi_claim_payload(**overrides) -> dict:
    payload = {
        "mi_provider": "Summit MI",
        "coverage_pct": 0.25,
        "claim_reference": "MI-4471",
    }
    payload.update(overrides)
    return payload


def mi_decision_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def issue_approval_letter_payload(offer_id: str, expected_case_version: int, **overrides) -> dict:
    payload = {
        "offer_id": offer_id,
        "approved_net_proceeds_cents": 22_122_539,
        "commission_cap_pct": 0.055,
        "seller_relocation_incentive_cents": 300_000,
        "deficiency_waiver": "WAIVED",
        "conditions": ["Arms-length affidavit required"],
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def file_extension_request_payload(requested_days: int, **overrides) -> dict:
    payload = {
        "requested_days": requested_days,
        "reason": "Buyer lender underwriting delay",
    }
    payload.update(overrides)
    return payload


def extension_decision_payload(outcome: str, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload
