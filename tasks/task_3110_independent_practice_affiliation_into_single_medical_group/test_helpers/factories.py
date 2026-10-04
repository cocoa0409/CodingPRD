"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_medical_group_payload(**overrides) -> dict:
    defaults = {
        "tin": TEST_DEFAULTS["GROUP_TIN"],
        "display_name": TEST_DEFAULTS["GROUP_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_market_payload(medical_group_id, **overrides) -> dict:
    defaults = {
        "medical_group_id": medical_group_id,
        "name": TEST_DEFAULTS["MARKET_NAME"],
        "state_code": TEST_DEFAULTS["MARKET_STATE"],
        "max_practices": TEST_DEFAULTS["MARKET_MAX_PRACTICES"],
    }
    defaults.update(overrides)
    return defaults


def create_practice_payload(medical_group_id, market_id, **overrides) -> dict:
    defaults = {
        "medical_group_id": medical_group_id,
        "market_id": market_id,
        "legal_name": TEST_DEFAULTS["PRACTICE_LEGAL_NAME"],
        "legacy_tin": TEST_DEFAULTS["PRACTICE_LEGACY_TIN"],
        "org_npi": TEST_DEFAULTS["PRACTICE_ORG_NPI"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(practice_id, **overrides) -> dict:
    n = _n()
    defaults = {
        "practice_id": practice_id,
        "npi": f"{5556660000 + n:010d}",
        "full_name": f"Dr. Test Provider {n}",
        "specialty": "Family Medicine",
        "provider_role": "PHYSICIAN",
        "employment_start_date": "2026-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_affiliation_agreement_payload(practice_id, expected_practice_version, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "distribution_model": "NET_OF_SHARED_SERVICES",
        "non_compete_accepted": True,
        "expected_practice_version": expected_practice_version,
    }
    defaults.update(overrides)
    return defaults


def create_implementation_wave_payload(market_id, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "wave_code": TEST_DEFAULTS["WAVE_CODE"],
        "cutover_start_date": TEST_DEFAULTS["WAVE_START"],
        "cutover_end_date": TEST_DEFAULTS["WAVE_END"],
    }
    defaults.update(overrides)
    return defaults


def create_payer_contract_payload(medical_group_id, **overrides) -> dict:
    defaults = {
        "medical_group_id": medical_group_id,
        "payer_name": TEST_DEFAULTS["PAYER_NAME"],
        "contract_type": TEST_DEFAULTS["CONTRACT_TYPE"],
        "effective_date": TEST_DEFAULTS["CONTRACT_EFFECTIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_rate_payload(payer_contract_id, **overrides) -> dict:
    defaults = {
        "payer_contract_id": payer_contract_id,
        "cpt_code": TEST_DEFAULTS["RATE_CPT"],
        "legacy_rate_cents": TEST_DEFAULTS["RATE_LEGACY"],
        "group_rate_cents": TEST_DEFAULTS["RATE_GROUP"],
    }
    defaults.update(overrides)
    return defaults


def create_credentialing_enrollment_payload(provider_id, payer_contract_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "payer_contract_id": payer_contract_id,
        "channel": "STANDARD",
        "requested_effective_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults


def create_collection_batch_payload(practice_id, payer_contract_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "payer_contract_id": payer_contract_id,
        "period": TEST_DEFAULTS["PERIOD_SEP"],
        "posted_amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_distribution_statement_payload(practice_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "period": TEST_DEFAULTS["PERIOD_SEP"],
    }
    defaults.update(overrides)
    return defaults


def create_incentive_pool_payload(payer_contract_id, **overrides) -> dict:
    defaults = {
        "payer_contract_id": payer_contract_id,
        "period": TEST_DEFAULTS["PERIOD_SEP"],
        "pool_amount_cents": TEST_DEFAULTS["POOL_AMOUNT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_incentive_allocation_payload(pool_id, practice_id, **overrides) -> dict:
    defaults = {
        "pool_id": pool_id,
        "practice_id": practice_id,
        "quality_score": 80,
        "attributed_lives": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_departure_case_payload(practice_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "requested_exit_date": "2027-12-01",
    }
    defaults.update(overrides)
    return defaults


def create_committee_vote_payload(market_id, subject_contract_id, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "motion_type": "PAYER_CONTRACT_RATIFICATION",
        "subject_contract_id": subject_contract_id,
    }
    defaults.update(overrides)
    return defaults
