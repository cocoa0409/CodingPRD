"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_affiliate_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"Test Affiliate {n}",
        "party_type": "PUBLISHER",
        "affiliation_code": f"AC{n}",
    }
    defaults.update(overrides)
    return defaults


def create_work_payload(registered_by_affiliate_id, **overrides) -> dict:
    defaults = {
        "title": f"Test Work {_seq()}",
        "registered_by_affiliate_id": registered_by_affiliate_id,
    }
    defaults.update(overrides)
    return defaults


def create_share_claim_payload(affiliate_id, **overrides) -> dict:
    defaults = {
        "affiliate_id": affiliate_id,
        "role": "PUBLISHER",
        "collection_share_bps": 10000,
        "interest_share_bps": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_licensee_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "legal_name": f"Test Licensee {n}",
        "category": "BROADCASTER",
        "reported_revenue_cents": 300000000000,
        "usage_units": 0,
    }
    defaults.update(overrides)
    return defaults


def issue_license_payload(expected_licensee_version, **overrides) -> dict:
    defaults = {
        "effective_date": "2026-01-01",
        "expiry_date": "2026-12-31",
        "expected_licensee_version": expected_licensee_version,
    }
    defaults.update(overrides)
    return defaults


def open_dispute_payload(**overrides) -> dict:
    defaults = {
        "opened_by_role": "LICENSEE",
        "disputed_fee_cents": 80000000,
    }
    defaults.update(overrides)
    return defaults


def create_performance_payload(work_id, license_id, **overrides) -> dict:
    defaults = {
        "work_id": work_id,
        "license_id": license_id,
        "performance_date": "2026-02-01",
        "medium": "TERRESTRIAL_RADIO",
        "daypart": "DAY",
        "source": "MONITORING",
        "play_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(**overrides) -> dict:
    defaults = {
        "label": f"CYC{_seq()}",
        "period_start": "2026-01-01",
        "period_end": "2026-03-31",
    }
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(**overrides) -> dict:
    defaults = {
        "delta_cents": 1000,
        "reason": "DATA_CORRECTION",
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(**overrides) -> dict:
    defaults = {
        "scope_period_start": "2025-01-01",
        "scope_period_end": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults
