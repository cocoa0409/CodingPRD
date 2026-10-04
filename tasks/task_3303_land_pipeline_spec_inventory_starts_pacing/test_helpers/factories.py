"""Payload factories — one per entity, input fields only."""
from . import constants as C


def create_land_parcel_payload(**overrides) -> dict:
    defaults = {"name": C.PARCEL_NAME, "market_code": C.MARKET_CODE, "acres": C.ACRES}
    defaults.update(overrides)
    return defaults


def create_option_contract_payload(**overrides) -> dict:
    defaults = {
        "land_parcel_id": overrides.pop("land_parcel_id", None),
        "option_fee_cents": C.OPTION_FEE_CENTS,
        "earnest_money_cents": C.EARNEST_MONEY_CENTS,
        "total_lots": C.TOTAL_LOTS,
        "lot_base_price_cents": C.LOT_BASE_PRICE_CENTS,
    }
    defaults.update(overrides)
    if defaults["land_parcel_id"] is None:
        raise ValueError("land_parcel_id is required")
    return defaults


def create_takedown_payload(**overrides) -> dict:
    defaults = {
        "community_id": overrides.pop("community_id", None),
        "lot_count": 5,
        "window_start": C.SEP_WINDOW_START,
        "window_end": C.SEP_WINDOW_END,
        "expected_contract_version": overrides.pop("expected_contract_version", None),
    }
    defaults.update(overrides)
    if defaults["community_id"] is None or defaults["expected_contract_version"] is None:
        raise ValueError("community_id and expected_contract_version are required")
    return defaults


def create_community_payload(**overrides) -> dict:
    defaults = {
        "name": C.COMMUNITY_NAME,
        "market_code": C.MARKET_CODE,
        "absorption_target_per_month": C.ABSORPTION_TARGET_PER_MONTH,
        "months_supply_target": C.MONTHS_SUPPLY_TARGET,
    }
    defaults.update(overrides)
    return defaults


def create_product_series_payload(**overrides) -> dict:
    defaults = {
        "series_code": C.SERIES_CODE,
        "min_price_cents": C.SERIES_MIN_PRICE_CENTS,
        "max_price_cents": C.SERIES_MAX_PRICE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_home_payload(**overrides) -> dict:
    defaults = {
        "lot_id": overrides.pop("lot_id", None),
        "product_series_id": overrides.pop("product_series_id", None),
        "base_price_cents": C.HOME_BASE_PRICE_CENTS,
    }
    defaults.update(overrides)
    if defaults["lot_id"] is None or defaults["product_series_id"] is None:
        raise ValueError("lot_id and product_series_id are required")
    return defaults


def create_sales_contract_payload(**overrides) -> dict:
    defaults = {
        "home_id": overrides.pop("home_id", None),
        "buyer_name": "Buyer A",
        "contract_price_cents": C.HOME_BASE_PRICE_CENTS,
    }
    defaults.update(overrides)
    if defaults["home_id"] is None:
        raise ValueError("home_id is required")
    return defaults


def create_incentive_payload(**overrides) -> dict:
    defaults = {
        "type": "PRICE_CUT",
        "value_cents": 500_000,
        "window_start": C.SEP_WINDOW_START,
        "window_end": C.SEP_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_trade_partner_payload(**overrides) -> dict:
    defaults = {"name": "FrameCo", "trade": "FRAMING"}
    defaults.update(overrides)
    return defaults


def create_capacity_commitment_payload(**overrides) -> dict:
    defaults = {
        "community_id": overrides.pop("community_id", None),
        "period_start": C.SEP_PERIOD_START,
        "period_end": C.SEP_PERIOD_END_EXCLUSIVE,
        "committed_units": 10,
    }
    defaults.update(overrides)
    if defaults["community_id"] is None:
        raise ValueError("community_id is required")
    return defaults


def create_pacing_plan_payload(**overrides) -> dict:
    defaults = {
        "period_start": C.SEP_PERIOD_START,
        "period_end": C.SEP_WINDOW_END,
        "max_starts": 10,
        "expected_community_version": overrides.pop("expected_community_version", None),
    }
    defaults.update(overrides)
    if defaults["expected_community_version"] is None:
        raise ValueError("expected_community_version is required")
    return defaults
