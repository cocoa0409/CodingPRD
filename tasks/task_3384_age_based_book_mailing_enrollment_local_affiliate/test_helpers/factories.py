"""Payload factories — one per creatable resource, input fields only (PRD §3).

Every factory takes ``**overrides`` so tests can control exactly the fields a
claim exercises while the factory supplies PRD-consistent defaults for the
rest. System/computed fields (id, version, enrolled_count, ...) are never
included — supplying them is itself an ERR_INVALID_REQUEST case (PRD §2.5).
"""
from .constants import (
    CLOCK_START,
    DEFAULT_AGREEMENT_EFFECTIVE_FROM,
    DEFAULT_AGREEMENT_EFFECTIVE_TO,
    DEFAULT_AFFILIATE_NAME,
    DEFAULT_CONTACT_EMAIL,
    DEFAULT_ELIGIBLE_POPULATION,
    DEFAULT_FUNDING_SHARE_BP,
    DEFAULT_FUNDRAISING_COMMITMENT_CENTS,
    DEFAULT_MAX_STATE_SHARE_PER_BOOK_CENTS,
    DEFAULT_POPULATION_YEAR,
    DEFAULT_POSTAL_PREFIXES,
    DEFAULT_PRINT_QUANTITY,
    DEFAULT_PROGRAM_NAME,
    DEFAULT_STATE_CODE,
    DEFAULT_TITLE_FROM_MONTH,
    DEFAULT_TITLE_UNTIL_MONTH,
    DEFAULT_WAVE_MONTH,
)

# Default mailing address inside DEFAULT_POSTAL_PREFIXES coverage ("372").
DEFAULT_ADDRESS = {
    "line1": "1 Oak St",
    "city": "Nashville",
    "region": "TN",
    "postal_code": "37201",
    "country": "US",
}

# Band-specific default titles so the five-band bootstrap reads clearly.
DEFAULT_TITLE_BY_BAND = {
    "INFANT": ("The Little Engine", "W Piper"),
    "TODDLER": ("Goodnight Cabin", "M Brown"),
    "TWO": ("Two at the Zoo", "K Ray"),
    "THREE": ("Three Bears Bake", "L Hill"),
    "FOUR": ("Four Seasons Farm", "J Wren"),
}

# Three default children, all INFANT-band at the default wave month 2026-10
# (born 2026-05 / 2026-06 / 2026-07, ages 5/4/3 months then), registered in
# the default logical month 2026-09 — strictly before the wave month, so all
# three are manifest-eligible (PRD §3.7).
DEFAULT_CHILD_SPECS = [
    {
        "full_name": "Ada Barnes",
        "family_name": "Barnes",
        "birth_date": "2026-05-10T00:00:00Z",
        "mailing_address": {
            "line1": "1 Oak St", "city": "Nashville", "region": "TN",
            "postal_code": "37201", "country": "US",
        },
    },
    {
        "full_name": "Bo Carter",
        "family_name": "Carter",
        "birth_date": "2026-06-15T00:00:00Z",
        "mailing_address": {
            "line1": "2 Elm St", "city": "Nashville", "region": "TN",
            "postal_code": "37203", "country": "US",
        },
    },
    {
        "full_name": "Cy Doyle",
        "family_name": "Doyle",
        "birth_date": "2026-07-04T00:00:00Z",
        "mailing_address": {
            "line1": "3 Pine St", "city": "Nashville", "region": "TN",
            "postal_code": "37206", "country": "US",
        },
    },
]


def set_clock_payload(current_utc=CLOCK_START, **overrides):
    payload = {"current_utc": current_utc}
    payload.update(overrides)
    return payload


def create_state_program_payload(**overrides):
    payload = {
        "state_code": DEFAULT_STATE_CODE,
        "name": DEFAULT_PROGRAM_NAME,
        "funding_share_bp": DEFAULT_FUNDING_SHARE_BP,
        "max_state_share_per_book_cents": DEFAULT_MAX_STATE_SHARE_PER_BOOK_CENTS,
    }
    payload.update(overrides)
    return payload


def create_affiliate_payload(state_program_id, **overrides):
    payload = {
        "name": DEFAULT_AFFILIATE_NAME,
        "state_program_id": state_program_id,
        "postal_prefixes": list(DEFAULT_POSTAL_PREFIXES),
        "contact_email": DEFAULT_CONTACT_EMAIL,
    }
    payload.update(overrides)
    return payload


def create_agreement_payload(expected_affiliate_version, **overrides):
    """OCC token is mandatory (PRD §2.7: a non-optional field)."""
    payload = {
        "effective_from": DEFAULT_AGREEMENT_EFFECTIVE_FROM,
        "effective_to": DEFAULT_AGREEMENT_EFFECTIVE_TO,
        "local_fundraising_commitment_cents": DEFAULT_FUNDRAISING_COMMITMENT_CENTS,
        "expected_affiliate_version": expected_affiliate_version,
    }
    payload.update(overrides)
    return payload


def create_population_stat_payload(**overrides):
    payload = {
        "effective_year": DEFAULT_POPULATION_YEAR,
        "eligible_population": DEFAULT_ELIGIBLE_POPULATION,
    }
    payload.update(overrides)
    return payload


def create_child_payload(affiliate_id, **overrides):
    address = overrides.pop("mailing_address", None) or dict(DEFAULT_ADDRESS)
    payload = {
        "affiliate_id": affiliate_id,
        "full_name": "Ada Barnes",
        "family_name": "Barnes",
        "birth_date": "2026-05-10T00:00:00Z",
        "mailing_address": address,
    }
    payload.update(overrides)
    return payload


def create_address_change_payload(new_address=None, **overrides):
    payload = {"new_address": new_address if new_address is not None else dict(DEFAULT_ADDRESS)}
    payload.update(overrides)
    return payload


def decide_address_change_payload(outcome="APPROVE", **overrides):
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


def create_title_payload(age_band, **overrides):
    title_name, author = DEFAULT_TITLE_BY_BAND.get(age_band, ("Catalog Book", "A Writer"))
    payload = {
        "title_name": title_name,
        "author": author,
        "age_band": age_band,
        "available_from_month": DEFAULT_TITLE_FROM_MONTH,
        "available_until_month": DEFAULT_TITLE_UNTIL_MONTH,
    }
    payload.update(overrides)
    return payload


def create_selection_payload(mailing_month, age_band, title_id, **overrides):
    payload = {
        "mailing_month": mailing_month,
        "age_band": age_band,
        "title_id": title_id,
    }
    payload.update(overrides)
    return payload


def reopen_selection_payload(reason=None, **overrides):
    payload = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def create_print_order_payload(selection_id, quantity=DEFAULT_PRINT_QUANTITY,
                               is_reprint=False, **overrides):
    payload = {
        "selection_id": selection_id,
        "quantity": quantity,
        "is_reprint": is_reprint,
    }
    payload.update(overrides)
    return payload


def create_wave_payload(mailing_month=DEFAULT_WAVE_MONTH, **overrides):
    payload = {"mailing_month": mailing_month}
    payload.update(overrides)
    return payload


def dispute_invoice_payload(outcome, credit_amount_cents=None, **overrides):
    """credit_amount_cents is omitted entirely when None — a missing credit on
    RESOLVE_UPHELD is itself a testable rejection (PRD §3.8)."""
    payload = {"outcome": outcome}
    if credit_amount_cents is not None:
        payload["credit_amount_cents"] = credit_amount_cents
    payload.update(overrides)
    return payload


__all__ = [
    "DEFAULT_ADDRESS",
    "DEFAULT_TITLE_BY_BAND",
    "DEFAULT_CHILD_SPECS",
    "set_clock_payload",
    "create_state_program_payload",
    "create_affiliate_payload",
    "create_agreement_payload",
    "create_population_stat_payload",
    "create_child_payload",
    "create_address_change_payload",
    "decide_address_change_payload",
    "create_title_payload",
    "create_selection_payload",
    "reopen_selection_payload",
    "create_print_order_payload",
    "create_wave_payload",
    "dispute_invoice_payload",
]
