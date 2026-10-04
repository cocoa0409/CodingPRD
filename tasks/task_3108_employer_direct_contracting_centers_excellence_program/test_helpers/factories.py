"""Payload factories — one per entity, input fields only."""
from .constants import RATES, unique_token


def create_rate_book_payload(**overrides) -> dict:
    defaults = {
        "book_code": unique_token("RB"),
        "rates": dict(RATES),
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(rate_book_id: str, **overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer " + unique_token("EMP"),
        "ein": unique_token("EIN"),
        "baseline_rate_book": rate_book_id,
    }
    defaults.update(overrides)
    return defaults


def create_bundle_template_payload(**overrides) -> dict:
    defaults = {
        "procedure_family": "ORTHO_JOINT",
        "label": "Primary Total Knee (OP)",
        "warranty_days": 90,
        "implant_component_cap_cents": 500000,
        "readmit_policy": "ALL_CAUSE",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(
    employer_id: str,
    template_id: str,
    bundle_price_cents: int = 3000000,
    **overrides,
) -> dict:
    defaults = {
        "employer_id": employer_id,
        "template_id": template_id,
        "effective_from": "2026-09-01T00:00:00Z",
        "effective_to": "2027-09-01T00:00:00Z",
        "bundle_price_cents": bundle_price_cents,
        "rate_components": {
            "facility": bundle_price_cents - 600000,
            "professional": 300000,
            "implant": 200000,
            "anesthesia": 100000,
        },
        "outlier_threshold_cents": 5000000,
        "outlier_share_pct": 0,
        "episode_cap_per_month": 50,
        "concurrent_capacity": 50,
        "travel_benefit_cents": 0,
        "lodging_benefit_cents": 0,
        "companion_allowed": False,
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(employer_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "full_name": "Pat " + unique_token("N"),
        "dob": "1970-01-01",
        "member_id": unique_token("M"),
    }
    defaults.update(overrides)
    return defaults


def create_episode_payload(
    patient_id: str,
    contract_id: str,
    **overrides,
) -> dict:
    defaults = {
        "patient_id": patient_id,
        "contract_id": contract_id,
        "intake_request_id": unique_token("IR"),
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    defaults = {"doc_type": "IMAGING", "result": "CANDIDATE"}
    defaults.update(overrides)
    return defaults


def create_review_payload(conclusion: str, expected_episode_version: int) -> dict:
    return {
        "conclusion": conclusion,
        "expected_episode_version": expected_episode_version,
    }


def create_schedule_payload(
    requested_day_seq: int, expected_episode_version: int
) -> dict:
    return {
        "requested_day_seq": requested_day_seq,
        "expected_episode_version": expected_episode_version,
    }


def create_care_item_payload(**overrides) -> dict:
    defaults = {
        "phase": "PRE_OP",
        "local_provider_name": "Local PT",
        "required": False,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(
    claim_type: str,
    service_date_seq: int,
    billed_cents: int,
    expected_episode_version: int,
    **overrides,
) -> dict:
    defaults = {
        "claim_type": claim_type,
        "submitting_entity": "HOSPITAL",
        "service_date_seq": service_date_seq,
        "billed_cents": billed_cents,
        "expected_episode_version": expected_episode_version,
    }
    defaults.update(overrides)
    return defaults


def create_readmission_payload(**overrides) -> dict:
    defaults = {"related": True, "provider_billed_cents": 150000}
    defaults.update(overrides)
    return defaults


def create_benefit_payload(
    kind: str,
    amount_cents: int,
    expected_episode_version: int,
    **overrides,
) -> dict:
    defaults = {
        "kind": kind,
        "traveler": "PATIENT",
        "amount_cents": amount_cents,
        "expected_episode_version": expected_episode_version,
    }
    defaults.update(overrides)
    return defaults


def create_reprice_payload(
    expected_contract_version: int,
    new_bundle_price_cents: int,
    new_rate_components: dict,
) -> dict:
    return {
        "expected_contract_version": expected_contract_version,
        "new_bundle_price_cents": new_bundle_price_cents,
        "new_rate_components": new_rate_components,
    }
