"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CENTER_CODE": "SC-001",
    "CENTER_NAME": "Midwest Supply Center",
    "BASE_WEEKLY_CAPACITY": 100000,
    "STORE_NUMBER": "ST-100",
    "OPERATOR_NAME": "Alice Franchise LLC",
    "CREDIT_LIMIT_CENTS": 100000000,
    "SKU": "DOUGH-001",
    "PRODUCT_NAME": "Fresh Dough Ball",
    "PRODUCT_CATEGORY": "DOUGH",
    "BASE_COST_CENTS": 1000,
    "WEEK_START": "2026-09-07T00:00:00Z",
    "ROUTE_CODE": "R1",
    "DAY_OF_WEEK": "MONDAY",
    "TRUCK_CAPACITY": 10000,
    "MARKUP_PCT": 0.15,
    "EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "EFFECTIVE_UNTIL": "2027-01-01T00:00:00Z",
    "QUARTER": "2026-Q3",
    "PROMO_CODE": "SUMMER26",
    "SURGE_MULTIPLIER": 2.0,
    "AGREEMENT_TYPE": "EXCLUSIVE_PURCHASE",
    "EXCLUSIVE_THRESHOLD": 0.95,
    "AGREEMENT_START": "2026-01-01T00:00:00Z",
}


def create_supply_center_payload(**overrides) -> dict:
    defaults = {
        "center_code": DEFAULTS["CENTER_CODE"],
        "display_name": DEFAULTS["CENTER_NAME"],
        "base_weekly_capacity_units": DEFAULTS["BASE_WEEKLY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "store_number": DEFAULTS["STORE_NUMBER"],
        "operator_name": DEFAULTS["OPERATOR_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "category": DEFAULTS["PRODUCT_CATEGORY"],
        "base_cost_cents_per_unit": DEFAULTS["BASE_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_price_book_payload(product_id, expected_center_version, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "store_tier": "STANDARD",
        "markup_pct": DEFAULTS["MARKUP_PCT"],
        "min_quantity": 1,
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_until": DEFAULTS["EFFECTIVE_UNTIL"],
        "expected_center_version": expected_center_version,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": DEFAULTS["ROUTE_CODE"],
        "day_of_week": DEFAULTS["DAY_OF_WEEK"],
        "truck_capacity_units": DEFAULTS["TRUCK_CAPACITY"],
        "assigned_store_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(**overrides) -> dict:
    defaults = {"week_start_date": DEFAULTS["WEEK_START"]}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id, **overrides) -> dict:
    defaults = {"product_id": product_id, "quantity": 10}
    defaults.update(overrides)
    return defaults


def create_promotion_payload(**overrides) -> dict:
    defaults = {
        "promotion_code": DEFAULTS["PROMO_CODE"],
        "start_date": "2026-09-07T00:00:00Z",
        "end_date": "2026-09-14T00:00:00Z",
        "surge_multiplier": DEFAULTS["SURGE_MULTIPLIER"],
        "affected_product_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_rebate_pool_payload(**overrides) -> dict:
    defaults = {"quarter": DEFAULTS["QUARTER"]}
    defaults.update(overrides)
    return defaults


def create_compliance_agreement_payload(**overrides) -> dict:
    defaults = {
        "agreement_type": DEFAULTS["AGREEMENT_TYPE"],
        "start_date": DEFAULTS["AGREEMENT_START"],
        "exclusive_purchase_threshold": DEFAULTS["EXCLUSIVE_THRESHOLD"],
    }
    defaults.update(overrides)
    return defaults


def create_capacity_plan_payload(**overrides) -> dict:
    defaults = {"week_start_date": DEFAULTS["WEEK_START"]}
    defaults.update(overrides)
    return defaults


def create_food_cost_variance_payload(**overrides) -> dict:
    defaults = {"week_start_date": DEFAULTS["WEEK_START"]}
    defaults.update(overrides)
    return defaults


def create_compliance_report_payload(**overrides) -> dict:
    defaults = {
        "week_start_date": DEFAULTS["WEEK_START"],
        "external_purchases_cents": 0,
    }
    defaults.update(overrides)
    return defaults
