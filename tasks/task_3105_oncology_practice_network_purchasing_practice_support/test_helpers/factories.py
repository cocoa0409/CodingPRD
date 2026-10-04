"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "NETWORK_NAME": "Test Oncology Network",
    "AGREEMENT_CODE": "GPO-TEST-1",
    "PRACTICE_NAME": "Test Cancer Care",
    "PRACTICE_NPI_PREFIX": "1234567",
    "STATE_CODE": "IA",
    "BASELINE_UNITS": 100,
    "PATHWAY_TARGET_PCT": 0.75,
    "DENIAL_THRESHOLD_PCT": 0.20,
    "BRAND_NAME": "Testcide",
    "GENERIC_NAME": "testcide-xyz",
    "NDC": "00000000001",
    "UNIT_PRICE_CENTS": 1000,
    "PROVIDER_NAME": "Dr. Test Provider",
    "PROVIDER_NPI": "1000000001",
    "REGIMEN_CODE": "AC-T",
    "PAYER_NAME": "Test Mutual",
    "CONTRACT_START": "2026-01-01T00:00:00Z",
    "CONTRACT_END": "2028-01-01T00:00:00Z",
    "LOT_EXPIRY": "2027-09-15T00:00:00Z",
    "ADMINISTERED_AT": "2026-09-02T00:00:00Z",
}

_NDC_COUNTER = {"n": 0}


def next_ndc() -> str:
    """A fresh 11-digit NDC unique within a network."""
    _NDC_COUNTER["n"] += 1
    return "0000{:07d}".format(200 + _NDC_COUNTER["n"])


def next_npi() -> str:
    """A fresh 10-digit organizational NPI."""
    _NDC_COUNTER["n"] += 1
    return "90000{:05d}".format(_NDC_COUNTER["n"])


def create_network_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["NETWORK_NAME"],
        "network_agreement_code": DEFAULTS["AGREEMENT_CODE"],
        "shortage_allocation_method": "PRO_RATA_BASELINE",
        "tier_market_share_boundaries": [
            {"tier": "TIER_3", "min_trailing_12m_purchases_cents": 50_000_000},
            {"tier": "TIER_2", "min_trailing_12m_purchases_cents": 0},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_practice_payload(**overrides) -> dict:
    defaults = {
        "practice_name": DEFAULTS["PRACTICE_NAME"],
        "practice_npi": next_npi(),
        "state_code": DEFAULTS["STATE_CODE"],
        "drug_shortage_baseline_units": DEFAULTS["BASELINE_UNITS"],
        "pathway_steering_target_pct": DEFAULTS["PATHWAY_TARGET_PCT"],
        "denial_ratio_threshold_pct": DEFAULTS["DENIAL_THRESHOLD_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_drug_product_payload(**overrides) -> dict:
    defaults = {
        "ndc": next_ndc(),
        "brand_name": DEFAULTS["BRAND_NAME"],
        "generic_name": DEFAULTS["GENERIC_NAME"],
        "therapeutic_class": "CYTOTOXIC",
        "unit_type": "MG",
        "network_base_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "is_shortage_candidate": False,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PROVIDER_NAME"],
        "npi": DEFAULTS["PROVIDER_NPI"],
        "specialty": "MEDICAL_ONCOLOGY",
        "is_billing_provider": True,
    }
    defaults.update(overrides)
    return defaults


def create_affiliation_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_type": "FULL_AFFILIATION",
        "term_start": DEFAULTS["CONTRACT_START"],
        "term_end": DEFAULTS["CONTRACT_END"],
        "notice_period_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_agreement_payload(**overrides) -> dict:
    defaults = {
        "tier_level": "TIER_1",
        "discount_pct": 0.0,
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": None,
        "routing_includes_out_of_scope": False,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(practice_id: str, drug_product_id: str, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "drug_product_id": drug_product_id,
        "quantity_units": 100,
        "shortage_allocation_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_receipt_payload(**overrides) -> dict:
    defaults = {
        "lot_number": "L-TEST-01",
        "expires_at": DEFAULTS["LOT_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_pathway_protocol_payload(**overrides) -> dict:
    defaults = {
        "protocol_code": "TEST-1L",
        "indication": "BREAST",
        "on_pathway_regimen_codes": ["AC-T"],
        "declared_regimen_codes": ["AC-T", "OTHER"],
        "off_pathway_penalty_score": 0.25,
        "version_label": "2026.1",
    }
    defaults.update(overrides)
    return defaults


def create_treatment_payload(practice_id: str, provider_id: str, drug_product_id: str,
                             pathway_protocol_id: str, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "provider_id": provider_id,
        "drug_product_id": drug_product_id,
        "pathway_protocol_id": pathway_protocol_id,
        "patient_reference": "PT-TEST-01",
        "regimen_code": DEFAULTS["REGIMEN_CODE"],
        "payer_name": DEFAULTS["PAYER_NAME"],
        "administered_units": 100,
        "dose_count": 1,
        "vial_yield_units": 100,
        "admin_fee_cents": 0,
        "administered_at": DEFAULTS["ADMINISTERED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_rebate_program_payload(**overrides) -> dict:
    defaults = {
        "program_name": "Test Rebate Program",
        "drug_ndc_scope": "ALL",
        "market_share_threshold_pct": 0.0,
        "rebate_pct": 0.02,
        "compliance_min_score": 0.0,
        "period_epoch_index": 0,
        "weight_reporting_compliance": 1,
        "weight_adherence_steering": 1,
        "weight_transparency": 1,
    }
    defaults.update(overrides)
    return defaults


def create_rebate_qualification_payload(practice_id: str, rebate_program_id: str, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "rebate_program_id": rebate_program_id,
    }
    defaults.update(overrides)
    return defaults


def create_management_agreement_payload(practice_id: str, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "service_line": "REVENUE_CYCLE",
        "fee_basis": "PERCENT_OF_NET_COLLECTIONS",
        "fee_rate": 0.05,
        "fixed_fee_cents": 0,
        "per_fte_fee_cents": 0,
        "per_claim_fee_cents": 0,
        "fte_count": 0,
        "term_start": "2026-01-01T00:00:00Z",
        "term_end": "2026-06-30T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_research_participation_payload(**overrides) -> dict:
    defaults = {
        "study_protocol_number": "TEST-2026-001",
        "study_phase": "PHASE_II",
        "sponsor_name": "Test Sponsor",
        "target_enrollment": 25,
    }
    defaults.update(overrides)
    return defaults


def create_shortage_payload(drug_product_id: str, **overrides) -> dict:
    defaults = {
        "drug_product_id": drug_product_id,
        "reported_at": "2026-09-01T00:00:00Z",
        "supply_available_units": 400,
        "allocation_method": "PRO_RATA_BASELINE",
    }
    defaults.update(overrides)
    return defaults


def create_pricing_agreement_submit_payload(practice_version: int) -> dict:
    return {"expected_practice_version": practice_version}


def create_administer_payload(practice_version: int, dose_plan: str = "WASTE_BILLED") -> dict:
    return {"dose_plan": dose_plan, "expected_practice_version": practice_version}


def create_claim_submit_payload(practice_version: int, **overrides) -> dict:
    defaults = {"expected_practice_version": practice_version}
    defaults.update(overrides)
    return defaults