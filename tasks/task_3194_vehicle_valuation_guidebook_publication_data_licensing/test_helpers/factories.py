"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_region_payload(**overrides) -> dict:
    defaults = {"region_code": _uniq("REG"), "name": "Test Region"}
    defaults.update(overrides)
    return defaults


def create_source_payload(region_id: str, **overrides) -> dict:
    defaults = {
        "source_type": "DEALER",
        "region_id": region_id,
        "name": "Test Source",
        "external_key": _uniq("src"),
    }
    defaults.update(overrides)
    return defaults


def create_configuration_payload(**overrides) -> dict:
    defaults = {
        "make": "Acme",
        "model": "Sedan",
        "year": 2023,
        "trim": "X",
        "segment": "SEDAN",
        "annual_expected_miles": 10000,
        "external_key": _uniq("cfg"),
    }
    defaults.update(overrides)
    return defaults


def create_batch_item_payload(configuration_id: str, region_id: str, **overrides) -> dict:
    defaults = {
        "configuration_id": configuration_id,
        "region_id": region_id,
        "sold_price_cents": 2000000,
        "sale_date": "2026-08-20",
        "mileage": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(source_id: str, items: list, **overrides) -> dict:
    defaults = {
        "source_id": source_id,
        "submission_ref": _uniq("b"),
        "items": items,
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(configuration_id: str, region_id: str, **overrides) -> dict:
    defaults = {
        "configuration_id": configuration_id,
        "region_id": region_id,
        "effective_from": "2026-09-01T00:00:00Z",
        "cadence": "WEEKLY",
        "external_key": _uniq("ser"),
    }
    defaults.update(overrides)
    return defaults


def create_edition_payload(series_id: str, **overrides) -> dict:
    defaults = {
        "series_id": series_id,
        "effective_at": "2026-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_market_shift_payload(**overrides) -> dict:
    defaults = {
        "region_id": None,
        "segment": None,
        "effective_at": "2026-09-01T00:00:00Z",
        "pct_adjustment": 0.02,
    }
    defaults.update(overrides)
    return defaults


def create_cash_offer_payload(edition_id: str, funding_dealer_id: str,
                              consumer_id: str, **overrides) -> dict:
    defaults = {
        "edition_id": edition_id,
        "funding_dealer_id": funding_dealer_id,
        "consumer_id": consumer_id,
        "mileage": 20000,
        "age_years": 2,
        "declared_condition_tier": "GOOD",
        "option_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_license_agreement_payload(**overrides) -> dict:
    defaults = {
        "licensee_ref": _uniq("lic"),
        "permitted_uses": ["DISPLAY"],
        "monthly_event_quota": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(offer_id: str, **overrides) -> dict:
    defaults = {"offer_id": offer_id, "reason_code": "STALE_DATA"}
    defaults.update(overrides)
    return defaults


def create_methodology_payload(**overrides) -> dict:
    defaults = {
        "version_label": _uniq("v2026."),
        "formula_hash": _uniq("hash"),
    }
    defaults.update(overrides)
    return defaults


def create_condition_standard_payload(**overrides) -> dict:
    defaults = {
        "tier": "GOOD",
        "description": "Decent shape",
        "multiplier": 1.00,
    }
    defaults.update(overrides)
    return defaults


def create_option_package_payload(configuration_id: str, **overrides) -> dict:
    defaults = {
        "configuration_id": configuration_id,
        "option_code": _uniq("OPT"),
        "credit_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_consumer_profile_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "email": f"consumer-{n}@example.com",
        "full_name": f"Consumer {n}",
    }
    defaults.update(overrides)
    return defaults


def create_correction_payload(batch_id: str, **overrides) -> dict:
    defaults = {"batch_id": batch_id, "corrected_price_cents": 2400000}
    defaults.update(overrides)
    return defaults
