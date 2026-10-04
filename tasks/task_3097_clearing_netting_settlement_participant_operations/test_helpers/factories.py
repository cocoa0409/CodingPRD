"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

DEFAULTS = {
    "LEGAL_NAME": "Test Clearing Member",
    "LEI": "LEI-TEST-0001",
    "PARTICIPANT_CLASS": "BANK",
    "NET_CAPITAL_CENTS": 2_000_000_000,
    "TICKER": "TST1",
    "CUSIP": "912828ZZ0",
    "PREV_SETTLEMENT_PRICE_CENTS": TEST_DEFAULTS["PREV_SETTLEMENT_PRICE_CENTS"],
}


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "lei": DEFAULTS["LEI"],
        "participant_class": DEFAULTS["PARTICIPANT_CLASS"],
        "net_capital_cents": DEFAULTS["NET_CAPITAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_security_payload(**overrides) -> dict:
    defaults = {
        "ticker": DEFAULTS["TICKER"],
        "cusip": DEFAULTS["CUSIP"],
        "prev_settlement_price_cents": DEFAULTS["PREV_SETTLEMENT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_settlement_window_payload(security_id, **overrides) -> dict:
    defaults = {
        "security_id": security_id,
        "settlement_date": TEST_DEFAULTS["SETTLEMENT_DATE"],
        "trade_entry_deadline": TEST_DEFAULTS["TRADE_ENTRY_DEADLINE"],
        "affirmation_deadline": TEST_DEFAULTS["AFFIRMATION_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_submission_payload(security_id, counterparty_participant_id, **overrides) -> dict:
    defaults = {
        "counterparty_participant_id": counterparty_participant_id,
        "security_id": security_id,
        "side": "BUY",
        "quantity": 100,
        "trade_price_cents": 4000,
        "trade_date": TEST_DEFAULTS["TRADE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_custody_account_payload(**overrides) -> dict:
    defaults = {
        "account_number": "CUST-0001",
        "account_type": "SEGREGATED",
    }
    defaults.update(overrides)
    return defaults


def create_corporate_action_payload(security_id, **overrides) -> dict:
    defaults = {
        "security_id": security_id,
        "action_type": "SPLIT",
        "ratio_numerator": 3,
        "ratio_denominator": 2,
        "effective_date": "2026-09-09",
    }
    defaults.update(overrides)
    return defaults


def create_clearing_fund_payload(security_id, **overrides) -> dict:
    defaults = {
        "security_id": security_id,
        "participant_class": DEFAULTS["PARTICIPANT_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_default_proceeding_payload(participant_id, **overrides) -> dict:
    defaults = {
        "participant_id": participant_id,
        "reason_code": "FINANCIAL_STANDARD_BREACH",
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(fund_component_id, **overrides) -> dict:
    defaults = {
        "bid_price_cents": 2222,
        "quantity": 1000,
        "placed_at": "2026-09-05T10:00:00Z",
        "fund_component_id": fund_component_id,
    }
    defaults.update(overrides)
    return defaults


def create_deposit_posting_payload(**overrides) -> dict:
    defaults = {"amount_cents": 500_000}
    defaults.update(overrides)
    return defaults


def create_fund_payload(**overrides) -> dict:
    """Payload for POST /clearing/net-positions/{id}/fund."""
    defaults = {"amount_cents": 400_000}
    defaults.update(overrides)
    return defaults