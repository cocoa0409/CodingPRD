"""Payload factories — one per entity, input fields only."""
from typing import Any, Dict, Optional


def create_seller_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "legal_name": "Test Seller LLC",
        "seller_state": "TX",
        "seller_type": "LLC",
    }
    defaults.update(overrides)
    return defaults


def create_buyer_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "legal_name": "Test Buyer LLC",
        "buyer_state": "TX",
        "entity_type": "LLC",
        "proof_of_funds_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_certification_program_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": "CertStd",
        "min_inspection_score": 50,
        "min_title_grade": "C",
        "requires_lease_disclosure": False,
        "guarantee_months_cap": 6,
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(seller_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "seller_id": seller_id,
        "address_line": "1 Test St",
        "listing_state": "TX",
        "asking_price_cents": 10_000_000,
        "listing_kind": "SINGLE",
        "seller_asks_confidential": False,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_report_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "inspector_name": "Inspector One",
        "inspection_date": "2026-08-01T00:00:00Z",
        "overall_score": 80,
        "roof_score": 80,
        "systems_score": 80,
        "disclosed_defects": [],
        "title_grade": "A",
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "tenant_alias": "T-1",
        "monthly_rent_cents": 100_000,
        "lease_start": "2026-01-01T00:00:00Z",
        "lease_end": "2027-01-01T00:00:00Z",
        "deposit_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_payment_record_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "due_date": "2026-01-01T00:00:00Z",
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_underwriting_report_payload(buyer_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "buyer_id": buyer_id,
        "rent_estimate_cents": 200_000,
        "vacancy_rate_bps": 500,
        "opex_rate_bps": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(buyer_id: str, expected_listing_version: int, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "buyer_id": buyer_id,
        "amount_cents": 9_000_000,
        "earnest_money_cents": 50_000,
        "financing_type": "CASH",
        "expected_listing_version": expected_listing_version,
    }
    defaults.update(overrides)
    return defaults


def create_property_manager_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "company_name": "PM Co",
        "markets": ["TX"],
        "onboarding_fee_bps": 150,
        "monthly_fee_bps": 800,
    }
    defaults.update(overrides)
    return defaults


def create_management_referral_payload(property_manager_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"property_manager_id": property_manager_id}
    defaults.update(overrides)
    return defaults


def create_guarantee_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "guarantee_kind": "VACANCY",
        "coverage_months": 3,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "opened_by": "BUYER",
        "condition_code": "ROOF-1",
        "remedy_cents": 0,
    }
    defaults.update(overrides)
    return defaults
