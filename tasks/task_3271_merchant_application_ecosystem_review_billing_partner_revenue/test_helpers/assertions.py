"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_developer_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("company_name"), str) and data["company_name"]
    assert isinstance(data.get("contact_email"), str) and data["contact_email"]
    assert data.get("payout_currency") in {"USD", "EUR", "GBP"}
    assert data.get("status") in {"ACTIVE", "SUSPENDED", "CLOSED"}
    assert isinstance(data.get("lifetime_gross_cents"), int)


def assert_app(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("developer_id"), str) and data["developer_id"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert data.get("status") in {
        "DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "LISTED", "SUSPENDED", "DELISTED",
    }
    assert data.get("listing_status") in {"UNLISTED", "LISTED", "DELISTED"}
    assert data.get("category") in {
        "PRODUCTIVITY", "MARKETING", "FULFILLMENT", "ANALYTICS", "FINANCE",
    }
    assert data.get("performance_state") in {"COMPLIANT", "DEGRADED", "DELISTED_PERFORMANCE"}
    assert data.get("revenue_share_tier") in {"T0", "T1", "T2"}


def assert_app_version(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("app_id"), str) and data["app_id"]
    assert isinstance(data.get("semver"), str) and data["semver"]
    assert data.get("status") in {
        "SUBMITTED", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED",
        "PUBLISHED", "SUPERSEDED",
    }
    assert isinstance(data.get("review_round"), int) and data["review_round"] >= 0


def assert_permission_scope(data: dict):
    # Catalog entries are immutable: only id and created_at, no version/updated_at.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("code"), str) and data["code"]
    assert data.get("risk_level") in {"LOW", "MEDIUM", "HIGH"}


def assert_scope_request(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("app_version_id"), str) and data["app_version_id"]
    assert isinstance(data.get("scope_code"), str) and data["scope_code"]
    assert data.get("status") in {"PENDING", "APPROVED", "DENIED"}


def assert_review_window(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("app_version_id"), str) and data["app_version_id"]
    assert isinstance(data.get("reviewer_id"), str) and data["reviewer_id"]
    assert is_iso8601_timestamp(data.get("starts_at", "")), "starts_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("ends_at", "")), "ends_at must be ISO 8601"
    assert data.get("status") in {"SCHEDULED", "CANCELLED", "COMPLETED"}


def assert_merchant_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("shop_domain"), str) and data["shop_domain"]
    assert data.get("plan_tier") in {"BASIC", "GROWTH", "ENTERPRISE"}


def assert_installation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("app_id"), str) and data["app_id"]
    assert isinstance(data.get("merchant_id"), str) and data["merchant_id"]
    assert data.get("status") in {
        "PENDING_CONSENT", "ACTIVE", "RECONSENT_REQUIRED", "SUSPENDED",
        "UNINSTALLING", "UNINSTALLED",
    }


def assert_consent_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("installation_id"), str) and data["installation_id"]
    assert isinstance(data.get("scope_code"), str) and data["scope_code"]
    assert data.get("status") in {"GRANTED", "REVOKED"}


def assert_webhook_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("installation_id"), str) and data["installation_id"]
    assert isinstance(data.get("topic"), str) and data["topic"]
    assert isinstance(data.get("endpoint_url"), str) and data["endpoint_url"]
    assert data.get("status") in {"ACTIVE", "FAILING", "DISABLED"}


def assert_billing_charge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("installation_id"), str) and data["installation_id"]
    assert isinstance(data.get("billing_cycle"), str) and len(data["billing_cycle"]) == 7
    assert data.get("charge_type") in {"RECURRING", "USAGE", "ONE_TIME"}
    assert data.get("status") in {
        "PENDING", "APPROVED", "DECLINED", "INVOICED", "REVERSED", "SETTLED",
    }
    assert isinstance(data.get("base_amount_cents"), int)
    assert isinstance(data.get("discount_amount_cents"), int)
    assert isinstance(data.get("final_amount_cents"), int)
    assert isinstance(data.get("platform_share_cents"), int)
    assert isinstance(data.get("developer_net_cents"), int)
    assert isinstance(data.get("description"), str)


def assert_charge_invariants(data: dict):
    """final = base - discount; net = final - share."""
    assert data["final_amount_cents"] == data["base_amount_cents"] - data["discount_amount_cents"], (
        f"final_amount_cents {data['final_amount_cents']} != "
        f"base {data['base_amount_cents']} - discount {data['discount_amount_cents']}"
    )
    assert data["developer_net_cents"] == (
        data["final_amount_cents"] - data["platform_share_cents"]
    ), (
        f"developer_net_cents {data['developer_net_cents']} != "
        f"final {data['final_amount_cents']} - share {data['platform_share_cents']}"
    )


def assert_monthly_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("merchant_id"), str) and data["merchant_id"]
    assert isinstance(data.get("cycle"), str) and len(data["cycle"]) == 7
    assert data.get("status") in {"OPEN", "ISSUED", "PAID", "VOID"}
    assert isinstance(data.get("total_cents"), int)


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("developer_id"), str) and data["developer_id"]
    assert isinstance(data.get("charge_id"), str) and data["charge_id"]
    assert data.get("entry_type") in {"ACCRUAL", "REVERSAL", "ADJUSTMENT"}
    assert isinstance(data.get("amount_cents"), int)
    assert data.get("entry_variant") in {"PROVISIONAL", "FINAL"}
    assert isinstance(data.get("cycle"), str) and len(data["cycle"]) == 7


def assert_performance_sample(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("installation_id"), str) and data["installation_id"]
    assert isinstance(data.get("storefront_load_ms"), int) and data["storefront_load_ms"] > 0
    assert is_iso8601_timestamp(data.get("sampled_at", "")), "sampled_at must be ISO 8601"


def assert_governance_strike(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("app_id"), str) and data["app_id"]
    assert data.get("reason") in {
        "DATA_DELETION_OVERDUE", "WEBHOOK_NONCOMPLIANCE", "PERFORMANCE_BREACH", "SUPPORT_BREACH",
    }
    assert data.get("status") in {"ACTIVE", "EXPIRED", "CLEARED"}
    assert is_iso8601_timestamp(data.get("strike_start", "")), "strike_start must be ISO 8601"
    assert is_iso8601_timestamp(data.get("strike_ends_at", "")), (
        "strike_ends_at must be ISO 8601"
    )


def assert_support_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("app_id"), str) and data["app_id"]
    assert isinstance(data.get("merchant_id"), str) and data["merchant_id"]
    assert data.get("severity") in {"LOW", "MEDIUM", "HIGH"}
    assert isinstance(data.get("sla_hours"), int)
    assert data.get("status") in {"OPEN", "ANSWERED", "ESCALATED", "RESOLVED", "DISPUTED"}
    assert isinstance(data.get("sla_breached"), bool)
