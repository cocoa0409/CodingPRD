"""Payload factories — one per entity, input fields only.

Factories build the request bodies the contract declares for each create or
transition endpoint. Computed and system-managed fields are never included.
"""

DEFAULTS = {
    "PLAN_CODE": "HCA",
    "LEGAL_NAME": "Home Plan CA",
    "SERVICE_AREA_STATES": ["CA"],
    "MEMBER_NUMBER": "M1",
    "FULL_NAME": "Pat One",
    "ACCOUNT_NAME": "Acme Corp",
    "EMPLOYER_GROUP_ID": "ACME-1",
    "TERRITORY_STATES": ["TX"],
    "ACCOUNT_START": "2026-01-01",
    "ACCOUNT_END": "2026-12-31",
    "PROVIDER_NPI": "1234567890",
    "PROCEDURE_CODE": "99213",
    "NEGOTIATED_RATE_CENTS": 30000,
    "RATE_START": "2026-01-01",
    "RATE_END": "2027-01-01",
    "TIER1_CAP_CENTS": 10000,
    "TIER1_FEE_CENTS": 150,
    "TIER2_RATE": 0.02,
    "DISCOUNT_PCT": 0,
    "FEE_START": "2026-01-01",
    "FEE_END": "2026-12-31",
    "SERVICE_DATE": "2026-08-10",
    "SERVICE_STATE": "TX",
    "BILLED_AMOUNT_CENTS": 20000,
    "ADJUSTMENT_REASON": "repricing",
    "BATCH_PERIOD_START": "2026-08-01",
    "BATCH_PERIOD_END": "2026-08-31",
}


def plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": DEFAULTS["PLAN_CODE"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "service_area_states": list(DEFAULTS["SERVICE_AREA_STATES"]),
    }
    defaults.update(overrides)
    return defaults


def member_payload(home_plan_id: str, **overrides) -> dict:
    defaults = {
        "home_plan_id": home_plan_id,
        "member_number": DEFAULTS["MEMBER_NUMBER"],
        "full_name": DEFAULTS["FULL_NAME"],
        "national_account_id": None,
    }
    defaults.update(overrides)
    return defaults


def national_account_payload(controlling_plan_id: str, **overrides) -> dict:
    defaults = {
        "controlling_plan_id": controlling_plan_id,
        "account_name": DEFAULTS["ACCOUNT_NAME"],
        "employer_group_id": DEFAULTS["EMPLOYER_GROUP_ID"],
        "territory_states": list(DEFAULTS["TERRITORY_STATES"]),
        "effective_start": DEFAULTS["ACCOUNT_START"],
        "effective_end": DEFAULTS["ACCOUNT_END"],
    }
    defaults.update(overrides)
    return defaults


def rate_schedule_payload(plan_id: str, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "provider_npi": DEFAULTS["PROVIDER_NPI"],
        "procedure_code": DEFAULTS["PROCEDURE_CODE"],
        "negotiated_rate_cents": DEFAULTS["NEGOTIATED_RATE_CENTS"],
        "effective_start": DEFAULTS["RATE_START"],
        "effective_end": DEFAULTS["RATE_END"],
    }
    defaults.update(overrides)
    return defaults


def access_fee_schedule_payload(home_plan_id: str, host_plan_id: str, **overrides) -> dict:
    defaults = {
        "home_plan_id": home_plan_id,
        "host_plan_id": host_plan_id,
        "tier1_cap_cents": DEFAULTS["TIER1_CAP_CENTS"],
        "tier1_fee_cents": DEFAULTS["TIER1_FEE_CENTS"],
        "tier2_rate": DEFAULTS["TIER2_RATE"],
        "national_account_discount_pct": DEFAULTS["DISCOUNT_PCT"],
        "effective_start": DEFAULTS["FEE_START"],
        "effective_end": DEFAULTS["FEE_END"],
    }
    defaults.update(overrides)
    return defaults


def claim_payload(member_id: str, host_plan_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "host_plan_id": host_plan_id,
        "provider_npi": DEFAULTS["PROVIDER_NPI"],
        "procedure_code": DEFAULTS["PROCEDURE_CODE"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "service_state": DEFAULTS["SERVICE_STATE"],
        "billed_amount_cents": DEFAULTS["BILLED_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def adjustment_payload(expected_claim_version: int, **overrides) -> dict:
    defaults = {
        "reason": DEFAULTS["ADJUSTMENT_REASON"],
        "delta_allowed_cents": -5000,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def settlement_batch_payload(debtor_plan_id: str, creditor_plan_id: str, **overrides) -> dict:
    defaults = {
        "debtor_plan_id": debtor_plan_id,
        "creditor_plan_id": creditor_plan_id,
        "period_start": DEFAULTS["BATCH_PERIOD_START"],
        "period_end": DEFAULTS["BATCH_PERIOD_END"],
        "settlement_variant": "NET",
    }
    defaults.update(overrides)
    return defaults


def refinalize_payload(expected_settlement_batch_version: int) -> dict:
    return {"expected_settlement_batch_version": expected_settlement_batch_version}


def eligibility_inquiry_payload(inquiring_plan_id: str, home_plan_id: str, **overrides) -> dict:
    defaults = {
        "inquiring_plan_id": inquiring_plan_id,
        "home_plan_id": home_plan_id,
        "member_number": DEFAULTS["MEMBER_NUMBER"],
    }
    defaults.update(overrides)
    return defaults


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
