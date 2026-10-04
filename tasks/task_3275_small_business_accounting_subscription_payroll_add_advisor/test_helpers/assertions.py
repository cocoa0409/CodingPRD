"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_uuid(value, label):
    assert is_valid_uuid(value), "{0} must be a UUID, got {1!r}".format(label, value)


def _assert_iso(value, label):
    assert is_iso8601_timestamp(value), (
        "{0} must be ISO 8601, got {1!r}".format(label, value)
    )


def assert_cents(actual, expected, label):
    assert isinstance(actual, int), "{0} must be int cents, got {1!r}".format(
        label, actual
    )
    assert actual == expected, "{0}: expected {1} cents, got {2}".format(
        label, expected, actual
    )


def assert_accountant_firm(data):
    _assert_uuid(data.get("id", ""), "firm.id")
    _assert_iso(data.get("created_at", ""), "firm.created_at")
    _assert_iso(data.get("updated_at", ""), "firm.updated_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("firm_name"), str) and data["firm_name"]
    assert data.get("proadvisor_tier") in ("SILVER", "GOLD", "PLATINUM")
    assert data.get("firm_status") in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_accountant_user(data):
    _assert_uuid(data.get("id", ""), "accountant_user.id")
    _assert_iso(data.get("created_at", ""), "accountant_user.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("user_status") in ("ACTIVE", "DISABLED")


def assert_client_company(data):
    _assert_uuid(data.get("id", ""), "company.id")
    _assert_iso(data.get("created_at", ""), "company.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("company_status") in ("ACTIVE", "READ_ONLY", "PURGED")
    assert data.get("data_region") in ("US", "EU", "UK")


def assert_company_user(data):
    _assert_uuid(data.get("id", ""), "company_user.id")
    _assert_iso(data.get("created_at", ""), "company_user.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("user_status") in ("INVITED", "ACTIVE", "DISABLED")
    assert data.get("permission_level") in (
        "PRIMARY_ADMIN",
        "COMPANY_ADMIN",
        "STANDARD",
        "REPORTS_ONLY",
        "TIME_TRACKING",
    )


def assert_plan(data):
    """SubscriptionPlan is append-only: id + created_at only — no updated_at,
    no version."""
    _assert_uuid(data.get("id", ""), "plan.id")
    _assert_iso(data.get("created_at", ""), "plan.created_at")
    assert "updated_at" not in data, "plan must not carry updated_at"
    assert "version" not in data, "plan must not carry version"
    assert isinstance(data.get("plan_code"), str) and data["plan_code"]
    assert isinstance(data.get("list_price_cents"), int)
    assert isinstance(data.get("max_seats"), int)


def assert_subscription(data):
    _assert_uuid(data.get("id", ""), "subscription.id")
    _assert_iso(data.get("created_at", ""), "subscription.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("billing_owner") in ("CLIENT", "FIRM")
    assert data.get("lifecycle_status") in (
        "TRIAL",
        "ACTIVE",
        "PAST_DUE",
        "SUSPENDED",
        "CANCELLED_READ_ONLY",
        "CANCELLED_EXPIRED",
        "REACTIVATED",
    )
    assert data.get("billing_status") in ("CURRENT", "PAST_DUE", "UNPAID")


def assert_payroll_addon(data):
    _assert_uuid(data.get("id", ""), "payroll_addon.id")
    _assert_iso(data.get("created_at", ""), "payroll_addon.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("service_level") in ("SELF_SERVICE", "FULL_SERVICE")
    assert data.get("addon_status") in ("ACTIVE", "PAUSED", "CANCELLED")
    assert data.get("tax_filing_status") in (
        "NOT_READY",
        "READY",
        "FILED_CURRENT",
        "PENALTY_RISK",
    )


def assert_payroll_employee(data):
    _assert_uuid(data.get("id", ""), "employee.id")
    _assert_iso(data.get("created_at", ""), "employee.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("employment_status") in ("ACTIVE", "TERMINATED")


def assert_invoice(data):
    _assert_uuid(data.get("id", ""), "invoice.id")
    _assert_iso(data.get("created_at", ""), "invoice.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("invoice_status") in (
        "DRAFT",
        "ISSUED",
        "PAID",
        "PAST_DUE",
        "VOID",
    )
    assert data.get("billed_to") in ("CLIENT", "FIRM")


def assert_bank_connection(data):
    _assert_uuid(data.get("id", ""), "bank_connection.id")
    _assert_iso(data.get("created_at", ""), "bank_connection.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("connection_status") in (
        "PENDING_AUTH",
        "ACTIVE",
        "STALE",
        "DISCONNECTED",
        "REVOKED",
    )


def assert_bank_transaction(data):
    _assert_uuid(data.get("id", ""), "txn.id")
    _assert_iso(data.get("created_at", ""), "txn.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("txn_status") in (
        "UNCATEGORIZED",
        "RULE_SUGGESTED",
        "CATEGORIZED",
        "EXCLUDED",
        "MATCHED_RECONCILED",
    )
    assert isinstance(data.get("amount_cents"), int)


def assert_category(data):
    """Category is append-only: id + created_at only."""
    _assert_uuid(data.get("id", ""), "category.id")
    _assert_iso(data.get("created_at", ""), "category.created_at")
    assert "updated_at" not in data, "category must not carry updated_at"
    assert "version" not in data, "category must not carry version"


def assert_categorization_rule(data):
    _assert_uuid(data.get("id", ""), "rule.id")
    _assert_iso(data.get("created_at", ""), "rule.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("rule_status") in ("ACTIVE", "PAUSED", "DELETED")
    assert data.get("match_field") in (
        "PAYEE_CONTAINS",
        "AMOUNT_EQUALS",
        "AMOUNT_GREATER_THAN",
    )


def assert_reconciliation(data):
    _assert_uuid(data.get("id", ""), "recon.id")
    _assert_iso(data.get("created_at", ""), "recon.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("recon_status") in (
        "DRAFT",
        "IN_PROGRESS",
        "COMPLETED",
        "LOCKED",
    )
    assert isinstance(data.get("cleared_cents"), int)
    assert isinstance(data.get("difference_cents"), int)


def assert_app_integration(data):
    _assert_uuid(data.get("id", ""), "integration.id")
    _assert_iso(data.get("created_at", ""), "integration.created_at")
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert data.get("integration_status") in (
        "LINKED",
        "ACTIVE",
        "CONFLICT_PAUSED",
        "DISCONNECTED",
    )


def assert_sync_conflict(data):
    _assert_uuid(data.get("id", ""), "conflict.id")
    _assert_iso(data.get("created_at", ""), "conflict.created_at")
    assert data.get("conflict_status") in (
        "OPEN",
        "RESOLVED_LOCAL",
        "RESOLVED_REMOTE",
        "IGNORED",
    )


def assert_migration_job(data):
    _assert_uuid(data.get("id", ""), "migration.id")
    _assert_iso(data.get("created_at", ""), "migration.created_at")
    assert data.get("migration_status") in (
        "QUEUED",
        "CONVERTING",
        "COMPLETED_CLEAN",
        "COMPLETED_WITH_LIMITATIONS",
        "FAILED",
        "CANCELLED",
    )


def assert_billing_transfer(data):
    _assert_uuid(data.get("id", ""), "transfer.id")
    _assert_iso(data.get("created_at", ""), "transfer.created_at")
    assert data.get("transfer_status") in (
        "PENDING_CLIENT_ACCEPT",
        "PENDING_FIRM_ACCEPT",
        "COMPLETED",
        "DECLINED",
        "EXPIRED",
        "CANCELLED",
    )


def assert_access_grant(data):
    _assert_uuid(data.get("id", ""), "grant.id")
    _assert_iso(data.get("created_at", ""), "grant.created_at")
    assert data.get("grant_status") in (
        "PENDING_ACCEPT",
        "ACTIVE",
        "REVOKED",
        "EXPIRED",
    )
    assert data.get("access_level") in (
        "FULL_BOOKKEEPING",
        "REPORTS_READ_ONLY",
        "PAYROLL_ONLY",
    )


def assert_export_request(data):
    _assert_uuid(data.get("id", ""), "export.id")
    _assert_iso(data.get("created_at", ""), "export.created_at")
    assert data.get("export_status") in ("PENDING", "READY", "DOWNLOADED", "EXPIRED")
