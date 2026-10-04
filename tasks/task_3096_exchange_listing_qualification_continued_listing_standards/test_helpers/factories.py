"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import (
    GOOD_AUDIT_COMMITTEE,
    GOOD_BOARD,
    GOOD_COMPENSATION_COMMITTEE,
)

_ticker_counter = itertools.count(1)


def create_issuer_payload(**overrides) -> dict:
    n = next(_ticker_counter)
    defaults = {
        "legal_name": f"Test Issuer {n} Corp",
        "ticker_symbol": f"T{n:05d}"[:6],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    """A CAPITAL-targeted application whose metrics pass CAPITAL standard A1
    (stockholders' equity 1,000,000,000 >= 500,000,000; all shared legs pass)."""
    defaults = {
        "target_tier": "CAPITAL",
        "board_directors": [dict(d) for d in GOOD_BOARD],
        "audit_committee": [dict(d) for d in GOOD_AUDIT_COMMITTEE],
        "compensation_committee": [dict(d) for d in GOOD_COMPENSATION_COMMITTEE],
        "stockholders_equity_cents": 1_000_000_000,
        "market_value_listed_securities_cents": 6_000_000_000_000,
        "market_value_unrestricted_publicly_held_cents": 500_000_000,
        "total_revenue_cents": 1_000_000_000,
        "income_from_continuing_operations_cents": 100_000_000,
        "bid_price_cents": 500,
        "publicly_held_shares": 2_000_000,
        "unrestricted_publicly_held_shares": 2_000_000,
        "round_lot_holders": 400,
        "total_shareholders": 400,
        "market_makers": 4,
        "operating_history_months": 60,
    }
    defaults.update(overrides)
    return defaults


def create_snapshot_payload(trade_date, closing_bid_cents=150, **overrides) -> dict:
    """A snapshot whose non-bid metrics comply at every tier (holders 400,
    MVPHS 6,000,000,000 cents clears the 5,000,000,000 GLOBAL continued
    threshold, MVLS 6,000,000,000,000 cents clears the 5,000,000,000,000
    CAPITAL continued threshold)."""
    defaults = {
        "trade_date": trade_date,
        "closing_bid_cents": closing_bid_cents,
        "market_value_publicly_held_cents": 6_000_000_000,
        "market_value_listed_securities_cents": 6_000_000_000_000,
        "round_lot_holders": 400,
        "total_shareholders": 400,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_plan_payload(deficiency_id, **overrides) -> dict:
    defaults = {
        "deficiency_id": deficiency_id,
        "plan_text": "We will cure the deficiency in place.",
        "plan_kind": "CURE_IN_PLACE",
    }
    defaults.update(overrides)
    return defaults


def create_hearings_review_payload(issuer_id, **overrides) -> dict:
    defaults = {
        "issuer_id": issuer_id,
        "panel_name": "Panel-1",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(deficiency_id, review_id, **overrides) -> dict:
    defaults = {
        "deficiency_id": deficiency_id,
        "review_id": review_id,
    }
    defaults.update(overrides)
    return defaults


def create_corporate_action_payload(**overrides) -> dict:
    defaults = {
        "action_type": "REVERSE_SPLIT",
        "split_ratio_denominator": 5,
    }
    defaults.update(overrides)
    return defaults


def create_annual_fee_payload(shares_outstanding, expected_issuer_version) -> dict:
    return {
        "shares_outstanding": shares_outstanding,
        "expected_issuer_version": expected_issuer_version,
    }
