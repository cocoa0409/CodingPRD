"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_OWNER_STATUSES = ["ACTIVE", "SUSPENDED", "EXITED"]
_AGREEMENT_STATUSES = [
    "DRAFT", "ACTIVE", "SUSPENDED", "TERMINATION_PENDING", "TERMINATED", "EXPIRED",
]
_POSTURES = ["UNMANAGED", "ONBOARDING", "MANAGED", "TRANSITIONING_OUT", "DISPOSED"]
_PROPERTY_STATUSES = ["OPEN", "CLOSED"]
_ONBOARDING_STATUSES = [
    "INTAKE", "DATA_VERIFIED", "LEDGER_IMPORTED", "VENDOR_REVIEW",
    "READY", "ACTIVATED", "ABORTED",
]
_LEASE_STATUSES = ["ACTIVE", "NOTICE", "VACATED"]
_ASSIGNMENT_STATUSES = ["PENDING", "ASSUMED", "ASSIGNED_TO_MANAGER", "TERMINATED"]
_BUDGET_KINDS = ["ANNUAL", "REFORECAST"]
_BUDGET_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "SUPERSEDED"]
_PRICING_STATUSES = ["PROPOSED", "PUBLISHED", "OWNER_OVERRIDDEN", "WITHDRAWN"]
_STAFF_STATUSES = ["ACTIVE", "INACTIVE"]
_STATEMENT_BASES = ["CASH", "ACCRUAL"]
_STATEMENT_STATUSES = ["OPEN", "CLOSED", "RESTATED"]
_LEDGER_KINDS = ["RENT", "FEE", "RECOVERY", "CONCESSION", "EXPENSE", "PAYROLL"]
_LEDGER_STATUSES = ["POSTED", "VOID"]
_PACKAGE_TYPES = ["MONTHLY_OWNER", "LENDER"]
_PACKAGE_STATUSES = ["DRAFT", "GENERATED", "DELIVERED"]
_CLAIM_TYPES = ["RESIDENT_INCIDENT", "EMPLOYMENT"]
_INDEMNIFIED_BY = ["OWNER", "MANAGER", "SHARED"]
_CLAIM_STATUSES = ["OPEN", "UNDER_REVIEW", "SETTLED", "CLOSED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["distribution_day_of_month"], int)
    assert 1 <= data["distribution_day_of_month"] <= 28
    assert data["status"] in _OWNER_STATUSES


def assert_agreement(data: dict):
    _assert_common(data)
    assert data["status"] in _AGREEMENT_STATUSES
    assert isinstance(data["minimum_monthly_fee_cents"], int)
    assert isinstance(data["incentive_threshold_egi_cents"], int)
    assert isinstance(data["termination_fee_tail_cents"], int)


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_count"], int)
    assert data["management_posture"] in _POSTURES
    assert data["status"] in _PROPERTY_STATUSES


def assert_onboarding(data: dict):
    _assert_common(data)
    assert data["status"] in _ONBOARDING_STATUSES
    assert isinstance(data["deposits_received_cents"], int)
    assert isinstance(data["prepaid_rent_cents"], int)
    assert isinstance(data["delinquency_cents"], int)


def assert_resident(data: dict):
    _assert_common(data)
    assert data["lease_status"] in _LEASE_STATUSES
    assert isinstance(data["unit_label"], str) and len(data["unit_label"]) > 0


def assert_vendor_contract(data: dict):
    _assert_common(data)
    assert data["assignment_status"] in _ASSIGNMENT_STATUSES
    assert isinstance(data["monthly_cost_cents"], int)


def assert_budget(data: dict):
    _assert_common(data)
    assert data["kind"] in _BUDGET_KINDS
    assert data["status"] in _BUDGET_STATUSES
    assert isinstance(data["operating_revenue_cents"], int)
    assert isinstance(data["operating_expense_cents"], int)
    assert isinstance(data["capex_total_cents"], int)


def assert_pricing(data: dict):
    _assert_common(data)
    assert data["status"] in _PRICING_STATUSES
    assert isinstance(data["recommended_rent_cents"], int)


def assert_staff(data: dict):
    _assert_common(data)
    assert data["status"] in _STAFF_STATUSES
    assert isinstance(data["hourly_cost_cents"], int)
    assert isinstance(data["scheduled_hours_per_week"], int)


def assert_statement(data: dict):
    _assert_common(data)
    assert data["basis"] in _STATEMENT_BASES
    assert data["status"] in _STATEMENT_STATUSES
    assert isinstance(data["collected_revenue_cents"], int)
    assert isinstance(data["base_fee_cents"], int)
    assert isinstance(data["incentive_fee_cents"], int)
    assert isinstance(data["payroll_charge_cents"], int)
    assert isinstance(data["management_fee_total_cents"], int)


def assert_ledger_entry(data: dict):
    _assert_common(data)
    assert data["kind"] in _LEDGER_KINDS
    assert data["status"] in _LEDGER_STATUSES
    assert isinstance(data["amount_cents"], int)


def assert_report(data: dict):
    _assert_common(data)
    assert data["package_type"] in _PACKAGE_TYPES
    assert data["status"] in _PACKAGE_STATUSES
    assert isinstance(data["distribution_amount_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["claim_type"] in _CLAIM_TYPES
    assert data["indemnified_by"] in _INDEMNIFIED_BY
    assert data["status"] in _CLAIM_STATUSES
    assert isinstance(data["reserved_amount_cents"], int)


def assert_claim_settlement(data: dict):
    """Append-only row (PRD §2.5): id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "ClaimSettlement must not expose version"
    assert "updated_at" not in data, "ClaimSettlement must not expose updated_at"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["manager_share_cents"], int)
    assert isinstance(data["owner_share_cents"], int)


def assert_settlement_invariants(data: dict):
    """PRD §3.9: shares always sum to the settlement amount exactly."""
    assert data["manager_share_cents"] + data["owner_share_cents"] == data["amount_cents"], (
        "manager_share_cents + owner_share_cents must equal amount_cents"
    )
    assert data["manager_share_cents"] >= 0
    assert data["owner_share_cents"] >= 0


def assert_statement_fee_invariants(data: dict):
    """PRD §3.6: management_fee_total_cents == base_fee_cents + incentive_fee_cents."""
    assert data["management_fee_total_cents"] == (
        data["base_fee_cents"] + data["incentive_fee_cents"]
    ), "management_fee_total_cents must equal base_fee_cents + incentive_fee_cents"
    assert data["base_fee_cents"] >= 0
    assert data["incentive_fee_cents"] >= 0
