"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS as D


def create_publisher_payload(**overrides) -> dict:
    payload = {
        "name": D["PUBLISHER_NAME"],
        "home_region_code": D["PUBLISHER_HOME_REGION"],
    }
    payload.update(overrides)
    return payload


def create_title_payload(**overrides) -> dict:
    payload = {
        "publisher_id": overrides.pop("publisher_id", "PLACEHOLDER"),
        "name": D["TITLE_NAME"],
        "platform_set": list(D["TITLE_PLATFORM_SET"]),
        "day_one_eligible": True,
        "list_price_cents": D["TITLE_LIST_PRICE_CENTS"],
        "unit_sales_30d": D["TITLE_UNIT_SALES_30D"],
    }
    payload.update(overrides)
    return payload


def create_region_payload(**overrides) -> dict:
    payload = {
        "region_code": D["REGION_CODE"],
        "currency_code": D["REGION_CURRENCY"],
        "price_multiplier": D["REGION_PRICE_MULTIPLIER"],
        "availability_ceiling_titles": D["REGION_CEILING_TITLES"],
        "catalog_tier_floor": D["REGION_TIER_FLOOR"],
    }
    payload.update(overrides)
    return payload


def create_maintenance_window(**overrides) -> dict:
    """One planned streaming maintenance window.

    `region_code` is not declared on a submitted window: the enclosing region
    create supplies it, and PRD §2.7 gives a window only `region_code`,
    `maintenance_start`, `maintenance_end` and `capacity_reduction_pct`.
    """
    payload = {
        "maintenance_start": "2026-09-30T00:00:00Z",
        "maintenance_end": "2026-10-05T00:00:00Z",
        "capacity_reduction_pct": 0.25,
    }
    payload.update(overrides)
    return payload


def create_tier_payload(**overrides) -> dict:
    payload = {
        "tier_code": D["TIER_CODE"],
        "monthly_price_cents": D["TIER_MONTHLY_PRICE_CENTS"],
        "console_access": True,
        "pc_access": True,
        "cloud_access": True,
        "online_play_bundle": True,
        "member_discount_pct": D["TIER_MEMBER_DISCOUNT_PCT"],
        "discount_retention_days": D["TIER_DISCOUNT_RETENTION_DAYS"],
        "annual_prepay_credit_ratio": D["TIER_ANNUAL_PREPAY_CREDIT_RATIO"],
    }
    payload.update(overrides)
    return payload


def create_essential_tier_payload(**overrides) -> dict:
    payload = {
        "tier_code": "ESSENTIAL",
        "monthly_price_cents": D["ESSENTIAL_MONTHLY_PRICE_CENTS"],
        "console_access": True,
        "pc_access": False,
        "cloud_access": False,
        "online_play_bundle": False,
        "member_discount_pct": 0.0,
        "discount_retention_days": 0,
        "annual_prepay_credit_ratio": 0.25,
    }
    payload.update(overrides)
    return payload


def create_licensing_deal_payload(**overrides) -> dict:
    payload = {
        "publisher_id": overrides.pop("publisher_id", "PLACEHOLDER"),
        "title_id": overrides.pop("title_id", "PLACEHOLDER"),
        "compensation_model": "HYBRID",
        "guaranteed_compensation_cents": D["DEAL_GUARANTEED_COMPENSATION_CENTS"],
        "monthly_engagement_cap_cents": D["DEAL_MONTHLY_ENGAGEMENT_CAP_CENTS"],
        "engagement_rate_cents_per_hour": D["DEAL_ENGAGEMENT_RATE_CENTS_PER_HOUR"],
        "term_start_date": D["DEAL_TERM_START"],
        "term_end_date": D["DEAL_TERM_END"],
        "add_effective_date": D["DEAL_ADD_EFFECTIVE"],
    }
    payload.update(overrides)
    return payload


def create_catalog_entry_payload(**overrides) -> dict:
    payload = {
        "title_id": overrides.pop("title_id", "PLACEHOLDER"),
        "region_code": D["REGION_CODE"],
        "tiers": ["PREMIUM"],
        "announced_add_date": D["ENTRY_ANNOUNCED_ADD"],
        "removal_date": D["ENTRY_REMOVAL"],
        "release_class": "CATALOG_ADD",
        "popularity_index_cents": D["ENTRY_POPULARITY"],
        "popularity_index_cents_30d_avg": D["ENTRY_POPULARITY_30D"],
    }
    payload.update(overrides)
    return payload


def create_subscriber_payload(**overrides) -> dict:
    payload = {
        "email": D["SUBSCRIBER_EMAIL"],
        "display_name": D["SUBSCRIBER_DISPLAY_NAME"],
        "home_region_code": D["REGION_CODE"],
        "wallet_credit_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(**overrides) -> dict:
    payload = {
        "subscriber_id": overrides.pop("subscriber_id", "PLACEHOLDER"),
        "tier_code": D["TIER_CODE"],
        "billing_period": "MONTHLY",
    }
    payload.update(overrides)
    return payload


def create_engagement_event_payload(**overrides) -> dict:
    payload = {
        "title_id": overrides.pop("title_id", "PLACEHOLDER"),
        "session_hours": 10.0,
        "channel": "CONSOLE",
        "engagement_multiplier": 1.0,
    }
    payload.update(overrides)
    return payload


def create_purchase_payload(**overrides) -> dict:
    payload = {
        "subscriber_id": overrides.pop("subscriber_id", "PLACEHOLDER"),
        "title_id": overrides.pop("title_id", "PLACEHOLDER"),
        "entry_id": overrides.pop("entry_id", "PLACEHOLDER"),
        "region_code": D["REGION_CODE"],
        "quantity": 1,
    }
    payload.update(overrides)
    return payload


def create_availability_projection_payload(**overrides) -> dict:
    payload = {
        "title_id": overrides.pop("title_id", "PLACEHOLDER"),
        "region_code": D["REGION_CODE"],
        "launch_subscriber_count": 1000,
        "tier_step_count": 2,
        "projected_unit_sales_units": 500,
        "release_class": "DAY_ONE",
    }
    payload.update(overrides)
    return payload