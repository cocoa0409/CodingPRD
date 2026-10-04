"""Payload factories — one per creatable resource, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_network_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Net"),
        "coordinator_org_name": "Coordination Hub",
    }
    defaults.update(overrides)
    return defaults


def create_taxonomy_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("FOOD"),
        "name": "Food",
    }
    defaults.update(overrides)
    return defaults


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Org"),
        "org_type": "CBO",
        "ein": _uniq("EIN"),
    }
    defaults.update(overrides)
    return defaults


def create_offering_payload(**overrides) -> dict:
    defaults = {
        "category_code": "FOOD",
        "description": "Meals",
        "capacity_total": 5,
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Client"),
        "date_of_birth": "1990-01-01",
        "zip_code": "94110",
        "gender": "FEMALE",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "party_a_org_id": None,
        "party_b_org_id": None,
        "effective_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(**overrides) -> dict:
    defaults = {
        "sender_org_id": None,
        "receiver_org_id": None,
        "scope": "FULL",
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "sender_org_id": None,
        "receiver_org_id": None,
        "service_offering_id": None,
        "consent_id": None,
        "category_code": "FOOD",
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    defaults = {
        "category_code": "FOOD",
        "rate_cents_per_unit": 100,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "referral_id": None,
        "funder_org_id": None,
        "claimed_units": 1,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(**overrides) -> dict:
    defaults = {
        "provider_org_id": None,
        "funder_org_id": None,
        "claim_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-09-01",
        "period_end": "2026-09-30",
    }
    defaults.update(overrides)
    return defaults


def create_note_payload(**overrides) -> dict:
    defaults = {
        "body": "case note",
    }
    defaults.update(overrides)
    return defaults
