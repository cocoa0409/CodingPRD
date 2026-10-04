"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMPANY_NAME": "Test Co",
    "PAYOUT_CURRENCY": "USD",
    "APP_NAME": "TestApp",
    "APP_CATEGORY": "PRODUCTIVITY",
    "SEMVER": "1.0.0",
    "SHOP_PLAN_TIER": "BASIC",
    "CHARGE_DESCRIPTION": "test charge",
    "WEBHOOK_URL": "https://hooks.example.com/handler",
    "REVIEWER_ID": "rev-1",
    "REJECT_REASON": "does not meet review bar",
}


def create_developer_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "contact_email": "dev@example.com",
        "payout_currency": DEFAULTS["PAYOUT_CURRENCY"],
    }
    defaults.update(overrides)
    return defaults


def create_app_payload(developer_id: str, **overrides) -> dict:
    defaults = {
        "developer_id": developer_id,
        "name": DEFAULTS["APP_NAME"],
        "category": DEFAULTS["APP_CATEGORY"],
    }
    defaults.update(overrides)
    return defaults


def create_app_version_payload(**overrides) -> dict:
    defaults = {"semver": DEFAULTS["SEMVER"]}
    defaults.update(overrides)
    return defaults


def create_scope_request_payload(scope_code: str, **overrides) -> dict:
    defaults = {"scope_code": scope_code}
    defaults.update(overrides)
    return defaults


def create_review_window_payload(
    starts_at: str = "2026-09-01T00:00:00Z",
    ends_at: str = "2026-09-15T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "reviewer_id": DEFAULTS["REVIEWER_ID"],
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_merchant_payload(**overrides) -> dict:
    defaults = {
        "shop_domain": "shop.example.com",
        "plan_tier": DEFAULTS["SHOP_PLAN_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_installation_payload(app_id: str, merchant_id: str, **overrides) -> dict:
    defaults = {"app_id": app_id, "merchant_id": merchant_id}
    defaults.update(overrides)
    return defaults


def create_billing_charge_payload(base_amount_cents: int = 1000, **overrides) -> dict:
    defaults = {
        "charge_type": "ONE_TIME",
        "base_amount_cents": base_amount_cents,
        "description": DEFAULTS["CHARGE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(cycle: str = "2026-09", **overrides) -> dict:
    defaults = {"cycle": cycle}
    defaults.update(overrides)
    return defaults


def create_webhook_subscription_payload(**overrides) -> dict:
    defaults = {
        "topic": "app/uninstalled",
        "endpoint_url": DEFAULTS["WEBHOOK_URL"],
    }
    defaults.update(overrides)
    return defaults


def create_permission_scope_payload(**overrides) -> dict:
    defaults = {"code": "read_products", "risk_level": "LOW"}
    defaults.update(overrides)
    return defaults


def create_performance_sample_payload(
    storefront_load_ms: int = 100,
    sampled_at: str = "2026-09-01T00:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "storefront_load_ms": storefront_load_ms,
        "sampled_at": sampled_at,
    }
    defaults.update(overrides)
    return defaults


def create_support_ticket_payload(merchant_id: str, severity: str = "LOW", **overrides) -> dict:
    defaults = {"merchant_id": merchant_id, "severity": severity}
    defaults.update(overrides)
    return defaults
