"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_brand_payload(**overrides) -> dict:
    defaults = {
        "brand_code": "MSP",
        "display_name": "Mosaic Plumbing",
        "trade": "PLUMBING",
        "royalty_rate": TEST_DEFAULTS["ROYALTY_RATE"],
        "national_ad_fund_rate": TEST_DEFAULTS["AD_FUND_RATE"],
        "min_certification_level": "APPRENTICE",
        "audit_cycle_months": TEST_DEFAULTS["AUDIT_CYCLE_MONTHS"],
    }
    defaults.update(overrides)
    return defaults


def create_franchisee_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Mosaic Central LLC",
        "principal_name": "Dana Vaughn",
        "entity_type": "LLC",
        "shared_services_enrolled": True,
    }
    defaults.update(overrides)
    return defaults


def create_territory_payload(brand_id, postal_codes=None, **overrides) -> dict:
    defaults = {
        "territory_code": "MS-01",
        "brand_id": brand_id,
        "household_count": TEST_DEFAULTS["HOUSEHOLD_COUNT"],
        "postal_codes": postal_codes if postal_codes is not None else ["75001", "75002"],
        "expansion_right_households": TEST_DEFAULTS["EXPANSION_RIGHT_HOUSEHOLDS"],
        "protected": True,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(franchisee_id, brand_id, territory_id, **overrides) -> dict:
    defaults = {
        "agreement_number": "A-MS-01",
        "franchisee_id": franchisee_id,
        "brand_id": brand_id,
        "territory_id": territory_id,
        "signed_on": TEST_DEFAULTS["SIGNED_ON"],
        "initial_term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "certification_level": "JOURNEYMAN",
    }
    defaults.update(overrides)
    return defaults


def create_transfer_application_payload(agreement_id, territory_id,
                                        applicant_franchisee_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "territory_id": territory_id,
        "applicant_franchisee_id": applicant_franchisee_id,
        "transfer_kind": "RESALE",
        "purchase_price_cents": 5000000,
        "target_territory_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(originating_agreement_id, receiving_agreement_id,
                            **overrides) -> dict:
    defaults = {
        "referral_code": "R1",
        "originating_agreement_id": originating_agreement_id,
        "receiving_agreement_id": receiving_agreement_id,
        "customer_household_ref": "HH-9001",
        "job_description": "Panel upgrade surfaced during a drain cleaning visit",
        "estimated_job_value_cents": 120000,
        "referral_fee_rate": 0.10,
    }
    defaults.update(overrides)
    return defaults


def create_lead_payload(brand_id, **overrides) -> dict:
    defaults = {
        "brand_id": brand_id,
        "source": "CALL_CENTER",
        "household_income_band": "BAND_2",
        "estimated_value_cents": 120000,
    }
    defaults.update(overrides)
    return defaults


def create_national_account_payload(contracted_brands=None, **overrides) -> dict:
    defaults = {
        "account_name": "Northline Property Group",
        "account_type": "PROPERTY_MANAGER",
        "contracted_brands": contracted_brands if contracted_brands is not None else [],
        "service_level_hours": 8,
        "sla_credit_per_breach_cents": 7500,
        "breach_tolerance": 2,
        "annual_commitment_cents": 25000000,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "source": "DIRECT",
        "priority": "STANDARD",
        "service_level_hours": 4,
        "parts_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "audit_kind": "MYSTERY_SHOP",
        "conducted_iso": TEST_DEFAULTS["SIGNED_ON"],
        "raw_score": 80.0,
        "findings_count": 4,
        "auditor_operator_id": TEST_DEFAULTS["AUDITOR_OPERATOR"],
        "critical_findings_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_statement_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
        "gross_revenue_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults