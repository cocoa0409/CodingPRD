"""Payload factories — one per entity, input fields only."""
import itertools

_counters = itertools.count(1)


def _next() -> int:
    return next(_counters)


def create_product_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "product_code": f"P-AUTO-{n}",
        "line_of_business": "AUTO",
        "state_code": "TX",
        "channel_availability": "BOTH",
        "coverage_rates": {
            "LIABILITY": {"BASIC": 50000, "STANDARD": 70000},
            "COLLISION": {"STANDARD": 90000, "PLUS": 120000},
        },
        "min_premium_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_rater_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "rater_code": f"PL-RATER-{n}",
        "display_name": f"PL Rater {n}",
        "feed_format_version": "v4.2",
        "accepted_line_of_business": "AUTO",
    }
    defaults.update(overrides)
    return defaults


def create_feed_publication_payload(product_id, expected_rater_version, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2027-01-01T00:00:00Z",
        "rate_table_payload": {"table": "default"},
        "expected_rater_version": expected_rater_version,
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "agency_name": f"Agency {n}",
        "principal_name": f"Principal {n}",
        "resident_state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "state_code": "TX",
        "line_of_business": "AUTO",
        "effective_start": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_commission_schedule_payload(expected_agent_version, **overrides) -> dict:
    defaults = {
        "line_of_business": "AUTO",
        "effective_start": "2026-01-01T00:00:00Z",
        "tiers": [{"up_to_cents": None, "rate_pct": 0.10}],
        "contingent_bonus_eligible": False,
        "expected_agent_version": expected_agent_version,
    }
    defaults.update(overrides)
    return defaults


def create_consumer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "email": f"consumer-{n}@example.com",
        "full_name": f"Casey {n}",
        "date_of_birth": "1990-01-01",
        "home_state_code": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(consumer_id, product_id, **overrides) -> dict:
    defaults = {
        "consumer_id": consumer_id,
        "product_id": product_id,
        "channel": "DIRECT",
        "coverages": [{"coverage_code": "LIABILITY", "tier": "BASIC"}],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "COLLISION",
        "incurred_amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_commission_statement_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bonus_pool_payload(**overrides) -> dict:
    defaults = {
        "year": 2026,
        "pool_total_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_portfolio_review_payload(**overrides) -> dict:
    defaults = {
        "reason": "scheduled review",
    }
    defaults.update(overrides)
    return defaults


def create_bundle_placement_payload(**overrides) -> dict:
    defaults = {
        "unaffiliated_carrier_name": "Unaffiliated Home Mutual",
        "home_premium_cents": 240000,
        "total_commission_cents": 36500,
    }
    defaults.update(overrides)
    return defaults
