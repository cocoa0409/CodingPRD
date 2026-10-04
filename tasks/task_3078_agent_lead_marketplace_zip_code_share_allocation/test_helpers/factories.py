"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools
import random

_counter = itertools.count(1)

DEFAULTS = {
    "BASE_LEAD_PRICE_CENTS": 10000,
    "SHARE_BPS": 6000,
    "DURATION_DAYS": 30,
}


def _unique_zip() -> str:
    # Exactly five digits, unique across markets (PRD §3.1).
    return f"{random.randint(0, 99999):05d}"


def _unique_suffix() -> str:
    return str(next(_counter))


def create_market_payload(**overrides) -> dict:
    defaults = {
        "zip_code": _unique_zip(),
        "state_code": "OR",
        "base_lead_price_cents": DEFAULTS["BASE_LEAD_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_brokerage_payload(**overrides) -> dict:
    n = _unique_suffix()
    defaults = {"legal_name": f"Brokerage {n}", "primary_state": "OR"}
    defaults.update(overrides)
    return defaults


def create_agent_payload(brokerage_id, **overrides) -> dict:
    n = _unique_suffix()
    defaults = {
        "full_name": f"Agent {n}",
        "email": f"agent-{n}@example.com",
        "license_number": f"LIC-{n}-{random.randint(1000, 9999)}",
        "license_state": "OR",
        "brokerage_id": brokerage_id,
    }
    defaults.update(overrides)
    return defaults


def create_team_account_payload(lead_agent_id, market_id, **overrides) -> dict:
    n = _unique_suffix()
    defaults = {
        "team_name": f"Team {n}",
        "lead_agent_id": lead_agent_id,
        "market_id": market_id,
    }
    defaults.update(overrides)
    return defaults


def create_team_membership_payload(team_id, agent_id, **overrides) -> dict:
    defaults = {"team_id": team_id, "agent_id": agent_id, "allocation_weight": 1}
    defaults.update(overrides)
    return defaults


def create_share_order_payload(market_id, buyer_agent_id, **overrides) -> dict:
    defaults = {
        "market_id": market_id,
        "buyer_agent_id": buyer_agent_id,
        "share_bps": DEFAULTS["SHARE_BPS"],
        "duration_days": DEFAULTS["DURATION_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, expected_market_version, outcome="SUCCEEDED", **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "outcome": outcome,
        "expected_market_version": expected_market_version,
    }
    defaults.update(overrides)
    return defaults


def create_lead_payload(market_id, listing_id, listing_agent_id, consumer_key=None, **overrides) -> dict:
    """Lead intake payload. PRD §3.4: the submitter provides `market_id`,
    `listing_id`, `consumer_key`, and `listing_agent_id` — all required."""
    n = _unique_suffix()
    defaults = {
        "market_id": market_id,
        "listing_id": listing_id,
        "consumer_key": consumer_key or f"consumer-{n}@example.com",
        "listing_agent_id": listing_agent_id,
    }
    defaults.update(overrides)
    return defaults


def create_accept_payload(expected_lead_version, **overrides) -> dict:
    defaults = {"expected_lead_version": expected_lead_version}
    defaults.update(overrides)
    return defaults


def create_live_connection_payload(lead_id, consumer_key, listing_agent_id, **overrides) -> dict:
    """Live-connection request payload. PRD §3.8: the caller supplies `lead_id`,
    `consumer_key`, and `listing_agent_id`."""
    defaults = {
        "lead_id": lead_id,
        "consumer_key": consumer_key,
        "listing_agent_id": listing_agent_id,
    }
    defaults.update(overrides)
    return defaults


def create_record_payload(duration_seconds=120, consent_given=True, **overrides) -> dict:
    defaults = {"duration_seconds": duration_seconds, "consent_given": consent_given}
    defaults.update(overrides)
    return defaults


def create_rating_payload(lead_id, score=4, **overrides) -> dict:
    defaults = {"lead_id": lead_id, "score": score}
    defaults.update(overrides)
    return defaults


def create_credit_claim_payload(lead_id, **overrides) -> dict:
    defaults = {"lead_id": lead_id, "claim_type": "INVALID", "reason": "test reason"}
    defaults.update(overrides)
    return defaults


def create_listing_payload(market_id, brokerage_id, listing_agent_id, **overrides) -> dict:
    n = _unique_suffix()
    defaults = {
        "external_ref": f"EXT-{n}",
        "market_id": market_id,
        "source_feed": "MLS",
        "brokerage_id": brokerage_id,
        "listing_agent_id": listing_agent_id,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(brokerage_id, **overrides) -> dict:
    defaults = {
        "dispute_type": "LISTING_DISPLAY",
        "brokerage_id": brokerage_id,
        "evidence": "test evidence",
    }
    defaults.update(overrides)
    return defaults
