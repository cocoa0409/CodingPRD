"""Payload factories — one per entity, input fields only."""


def create_payer_client_payload(**overrides) -> dict:
    defaults = {
        "payer_name": "Acme Health Plan",
        "fee_percent": 0.25,
        "fee_cap_cents_per_claim": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_repricing_policy_payload(payer_client_id, **overrides) -> dict:
    defaults = {
        "payer_client_id": payer_client_id,
        "claim_type": "PROFESSIONAL",
        "network_status": "OUT_OF_NETWORK",
        "methodology": "PERCENT_OF_MEDICARE",
        "percent_of_medicare": 1.50,
        "priority": 1,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "npi": "1000000000",
        "legal_name": "Test Provider LLC",
        "tin": "T-000",
    }
    defaults.update(overrides)
    return defaults


def create_network_agreement_payload(provider_id, **overrides) -> dict:
    defaults = {
        "network_name": "Net-1",
        "provider_id": provider_id,
        "discount_percent": 0.40,
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_medicare_entry_payload(**overrides) -> dict:
    defaults = {
        "procedure_code": "99283",
        "region_code": "R1",
        "base_rate_cents": 10000,
        "geographic_adjustment_factor": 1.10,
        "effective_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_ucr_rate_payload(**overrides) -> dict:
    defaults = {
        "procedure_code": "99283",
        "region_code": "R1",
        "percentile_50_cents": 18000,
        "percentile_80_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(payer_client_id, provider_id, **overrides) -> dict:
    defaults = {
        "payer_client_id": payer_client_id,
        "provider_id": provider_id,
        "external_claim_ref": "CLM-1",
        "claim_type": "PROFESSIONAL",
        "network_status": "OUT_OF_NETWORK",
        "service_date": "2026-09-10T00:00:00Z",
        "patient_responsibility_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(**overrides) -> dict:
    defaults = {
        "procedure_code": "99283",
        "quantity_units": 2,
        "unit_charge_cents": 30000,
        "region_code": "R1",
    }
    defaults.update(overrides)
    return defaults


def create_negotiation_case_payload(claim_id, **overrides) -> dict:
    defaults = {"claim_id": claim_id}
    defaults.update(overrides)
    return defaults


def create_offer_payload(offer_cents, expected_case_version, **overrides) -> dict:
    defaults = {
        "offer_cents": offer_cents,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(counter_cents, **overrides) -> dict:
    defaults = {"counter_cents": counter_cents}
    defaults.update(overrides)
    return defaults


def create_open_negotiation_payload(claim_id, **overrides) -> dict:
    defaults = {"claim_id": claim_id, "initiated_by": "PAYER"}
    defaults.update(overrides)
    return defaults


def create_idr_submission_payload(claim_id, open_negotiation_id, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "open_negotiation_id": open_negotiation_id,
        "payer_offer_cents": 30000,
        "provider_offer_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(determination_id, **overrides) -> dict:
    defaults = {
        "determination_id": determination_id,
        "appeal_reason": "rate dispute",
    }
    defaults.update(overrides)
    return defaults


def create_feed_batch_payload(payer_client_id, **overrides) -> dict:
    defaults = {
        "payer_client_id": payer_client_id,
        "feed_type": "CLAIM_INTAKE",
        "record_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_fee_invoice_payload(payer_client_id, claim_ids, **overrides) -> dict:
    defaults = {"payer_client_id": payer_client_id, "claim_ids": list(claim_ids)}
    defaults.update(overrides)
    return defaults
