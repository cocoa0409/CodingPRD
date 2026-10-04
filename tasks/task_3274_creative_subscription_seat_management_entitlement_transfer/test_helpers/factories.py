"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ORG_NAME": "Test Org",
    "ORG_TYPE": "TEAM",
    "ADMIN_EMAIL": "admin@example.com",
    "ADMIN_FULL_NAME": "Test Admin",
    "ADMIN_KIND": "SYSTEM_ADMIN",
    "USER_EMAIL": "user@example.com",
    "USER_FULL_NAME": "Test User",
    "RESELLER_NAME": "Test Reseller",
    "RESELLER_REGION": "NA",
    "RESELLER_TIER": "GOLD",
    "PLAN_CODE": "TEST_PLAN",
    "PLAN_SEGMENT": "TEAM",
    "PLAN_BILLING_MODEL": "MONTHLY",
    "PLAN_MONTHLY_PRICE_CENTS": 3000,
    "PLAN_ANNUAL_MONTHLY_PRICE_CENTS": 3000,
    "PLAN_STORAGE_GB_PER_SEAT": 20,
    "PLAN_SEAT_LIMIT": -1,
    "PLAN_DEPLOYMENT_MODES": ["NAMED_USER"],
    "PLAN_ALLOWS_OFFLINE": False,
    "PLAN_MAX_DEVICES": 2,
    "PLAN_WINDOW_DAYS": 14,
    "PLAN_ETF_RATE_PCT": 0,
    "VERSION_LABEL": "2026.1",
    "VERSION_RELEASE_DATE": "2026-01-15T00:00:00Z",
    "SEATS_PURCHASED": 1,
    "DEVICE_FINGERPRINT": "fp-0001",
    "DEVICE_LABEL": "Test Laptop",
    "PACKAGE_NAME": "Test Package",
    "PACKAGE_MODE": "NAMED_USER",
    "ADDON_KIND": "STOCK_CREDITS",
    "ADDON_QUOTA": 100,
    "ADDON_OVERAGE_PRICE": 0,
    "ASSET_TITLE": "Test Asset",
    "ASSET_SIZE_MB": 100,
    "ORDER_SEATS": 1,
    "ORDER_REGION": "NA",
}

BOOTSTRAP_ADMIN_PLACEHOLDER = "00000000-0000-0000-0000-000000000000"


def create_organization_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ORG_NAME"],
        "org_type": DEFAULTS["ORG_TYPE"],
        "primary_admin_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
    }
    defaults.update(overrides)
    return defaults


def create_admin_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["ADMIN_EMAIL"],
        "full_name": DEFAULTS["ADMIN_FULL_NAME"],
        "admin_kind": DEFAULTS["ADMIN_KIND"],
        "org_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
    }
    defaults.update(overrides)
    return defaults


def create_end_user_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["USER_EMAIL"],
        "full_name": DEFAULTS["USER_FULL_NAME"],
        "org_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
    }
    defaults.update(overrides)
    return defaults


def create_reseller_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RESELLER_NAME"],
        "region": DEFAULTS["RESELLER_REGION"],
        "tier": DEFAULTS["RESELLER_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["PLAN_CODE"],
        "segment": DEFAULTS["PLAN_SEGMENT"],
        "billing_model": DEFAULTS["PLAN_BILLING_MODEL"],
        "monthly_price_cents": DEFAULTS["PLAN_MONTHLY_PRICE_CENTS"],
        "annual_monthly_price_cents": DEFAULTS["PLAN_ANNUAL_MONTHLY_PRICE_CENTS"],
        "storage_gb_per_seat": DEFAULTS["PLAN_STORAGE_GB_PER_SEAT"],
        "seat_limit": DEFAULTS["PLAN_SEAT_LIMIT"],
        "deployment_modes": list(DEFAULTS["PLAN_DEPLOYMENT_MODES"]),
        "allows_offline_activation": DEFAULTS["PLAN_ALLOWS_OFFLINE"],
        "max_devices_per_seat": DEFAULTS["PLAN_MAX_DEVICES"],
        "cancellation_window_days": DEFAULTS["PLAN_WINDOW_DAYS"],
        "etf_rate_pct": DEFAULTS["PLAN_ETF_RATE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_product_version_payload(**overrides) -> dict:
    defaults = {
        "plan_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "version_label": DEFAULTS["VERSION_LABEL"],
        "release_date": DEFAULTS["VERSION_RELEASE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(**overrides) -> dict:
    defaults = {
        "org_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "plan_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "seats_purchased": DEFAULTS["SEATS_PURCHASED"],
    }
    defaults.update(overrides)
    return defaults


def create_seat_payload(**overrides) -> dict:
    defaults = {
        "subscription_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "expected_subscription_version": 1,
    }
    defaults.update(overrides)
    return defaults


def assign_seat_payload(**overrides) -> dict:
    defaults = {
        "end_user_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
    }
    defaults.update(overrides)
    return defaults


def create_device_payload(**overrides) -> dict:
    defaults = {
        "end_user_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "device_fingerprint": DEFAULTS["DEVICE_FINGERPRINT"],
        "label": DEFAULTS["DEVICE_LABEL"],
    }
    defaults.update(overrides)
    return defaults


def activate_entitlement_payload(**overrides) -> dict:
    defaults = {
        "device_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
    }
    defaults.update(overrides)
    return defaults


def create_transfer_request_payload(**overrides) -> dict:
    defaults = {
        "org_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "seat_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "to_user_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "requested_by_admin_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "expected_seat_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_cancellation_request_payload(**overrides) -> dict:
    defaults = {
        "subscription_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "requested_by_admin_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_service_payload(**overrides) -> dict:
    defaults = {
        "subscription_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "kind": DEFAULTS["ADDON_KIND"],
        "quota_total": DEFAULTS["ADDON_QUOTA"],
        "overage_unit_price_cents": DEFAULTS["ADDON_OVERAGE_PRICE"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(**overrides) -> dict:
    defaults = {
        "owner_user_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "title": DEFAULTS["ASSET_TITLE"],
        "size_mb": DEFAULTS["ASSET_SIZE_MB"],
    }
    defaults.update(overrides)
    return defaults


def create_deployment_package_payload(**overrides) -> dict:
    defaults = {
        "org_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "created_by_admin_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "name": DEFAULTS["PACKAGE_NAME"],
        "plan_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "deployment_mode": DEFAULTS["PACKAGE_MODE"],
    }
    defaults.update(overrides)
    return defaults


def create_reseller_order_payload(**overrides) -> dict:
    defaults = {
        "org_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "plan_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "seats": DEFAULTS["ORDER_SEATS"],
        "region": DEFAULTS["ORDER_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_compliance_audit_payload(**overrides) -> dict:
    defaults = {
        "org_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
        "opened_by_admin_id": BOOTSTRAP_ADMIN_PLACEHOLDER,
    }
    defaults.update(overrides)
    return defaults
