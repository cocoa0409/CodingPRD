"""Payload factories — one per entity, input fields only (PRD §4 endpoints)."""
import uuid

DEFAULTS = {
    "PARTNER_NAME": "Pat Morgan",
    "PARTNER_ROLE": "MANAGING_PARTNER",
    "MARKET_GROUP_NAME": "Central TX",
    "RESTAURANT_NAME": "Roadhouse A",
    "RESTAURANT_CITY": "Austin",
    "RESTAURANT_STATE": "TX",
    "TERM_START": "2027-01-01",
    "TERM_END": "2032-01-01",
    "BUY_IN_REQUIRED_CENTS": 2500000,
    "PAYMENT_AMOUNT_CENTS": 2500000,
    "COVERAGE_START": "2027-01-01",
    "COVERAGE_END": "2027-12-31",
    "OVERRIDE_PCT": 5,
    "BASIS": "PER_RESTAURANT_POSITIVE",
    "PERIOD_START": "2027-01-01",
    "PERIOD_END": "2027-02-01",
    "LINE_ITEM_CATEGORY": "REVENUE",
    "LINE_ITEM_AMOUNT": 5000000,
    "ENTRY_STATUS": "FINALIZED",
    "CUT_CODE": "SIR_8",
    "EXPECTED_YIELD_PCT": 70,
    "WASTE_TOLERANCE_PCT": 0,
    "STANDARD_COST_PER_LB_CENTS": 300,
    "SUB_PRIMAL_WEIGHT_LBS": 10.0,
    "PROGRAM_NAME": "2027 Stock",
    "PROGRAM_TYPE": "STOCK_GRANT",
    "PERF_START": "2027-01-01",
    "PERF_END": "2027-12-31",
    "STOCK_UNITS_POOL": 1000,
    "CLAIM_TEXT": "Profit figure contested",
}


def create_partner_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PARTNER_NAME"],
        "email": f"partner-{uuid.uuid4().hex[:8]}@x.com",
        "role_in_program": DEFAULTS["PARTNER_ROLE"],
    }
    defaults.update(overrides)
    return defaults


def create_market_group_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["MARKET_GROUP_NAME"]}
    defaults.update(overrides)
    return defaults


def create_restaurant_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RESTAURANT_NAME"],
        "city": DEFAULTS["RESTAURANT_CITY"],
        "state_code": DEFAULTS["RESTAURANT_STATE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
        "buy_in_required_cents": DEFAULTS["BUY_IN_REQUIRED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_buy_in_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": DEFAULTS["PAYMENT_AMOUNT_CENTS"]}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "coverage_start_date": DEFAULTS["COVERAGE_START"],
        "coverage_end_date": DEFAULTS["COVERAGE_END"],
        "override_pct": DEFAULTS["OVERRIDE_PCT"],
        "basis": DEFAULTS["BASIS"],
    }
    defaults.update(overrides)
    return defaults


def create_profit_period_payload(**overrides) -> dict:
    defaults = {
        "period_start_date": DEFAULTS["PERIOD_START"],
        "period_end_date": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(**overrides) -> dict:
    defaults = {
        "category": DEFAULTS["LINE_ITEM_CATEGORY"],
        "amount_cents": DEFAULTS["LINE_ITEM_AMOUNT"],
        "entry_status": DEFAULTS["ENTRY_STATUS"],
    }
    defaults.update(overrides)
    return defaults


def create_yield_standard_payload(**overrides) -> dict:
    defaults = {
        "cut_code": DEFAULTS["CUT_CODE"],
        "expected_yield_pct": DEFAULTS["EXPECTED_YIELD_PCT"],
        "waste_tolerance_pct": DEFAULTS["WASTE_TOLERANCE_PCT"],
        "standard_cost_per_lb_cents": DEFAULTS["STANDARD_COST_PER_LB_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_meat_cut_batch_payload(**overrides) -> dict:
    defaults = {
        "cut_code": DEFAULTS["CUT_CODE"],
        "sub_primal_weight_lbs": DEFAULTS["SUB_PRIMAL_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_award_program_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROGRAM_NAME"],
        "program_type": DEFAULTS["PROGRAM_TYPE"],
        "performance_period_start_date": DEFAULTS["PERF_START"],
        "performance_period_end_date": DEFAULTS["PERF_END"],
        "stock_units_pool": DEFAULTS["STOCK_UNITS_POOL"],
    }
    defaults.update(overrides)
    return defaults


def create_award_grant_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"claim_text": DEFAULTS["CLAIM_TEXT"]}
    defaults.update(overrides)
    return defaults
