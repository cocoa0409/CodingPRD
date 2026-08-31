"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AuditStatus, BillingMode, BillingStatus, BreakpointType, ChargeType,
    CollectionStatus, CoTenancyEventStatus, CoTenancyEventType,
    CoTenancyPosture, ExclusionCode, ExclusionProfile, ExclusionStatus,
    KickOutStatus, LeaseStatus, LeaseYearStatus, LedgerEntryType,
    MonitoringStatus, ReliefType, ReportingFrequency, SalesReportSource,
    SalesReportStatus, TenantCategory, TenantStatus, WatchlistStatus,
)


# ─── Instant helpers ──────────────────────────────────────────────────────

def parse_instant(value: str) -> datetime:
    """Parse a UTC instant the service returned, whatever its fractional form."""
    assert isinstance(value, str) and value, f"expected an instant, got {value!r}"
    text = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "instant"):
    """Compare two UTC instants by value rather than by textual spelling."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def plus_days(instant: str, days: int) -> str:
    """Advance an instant by whole twenty-four-hour spans, in UTC."""
    moved = parse_instant(instant) + timedelta(days=days)
    return moved.strftime("%Y-%m-%dT%H:%M:%SZ")


def _values(enum_cls) -> list:
    return [member.value for member in enum_cls]


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp")
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1")


# ─── Entity assertions ────────────────────────────────────────────────────

def assert_center(data: dict):
    _assert_common_fields(data, "ShoppingCenter")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and 1 <= len(data["code"]) <= 16
    assert isinstance(data["total_gla_sqft"], int) and data["total_gla_sqft"] > 0
    assert isinstance(data["anchor_gla_sqft"], int)
    assert 0 <= data["anchor_gla_sqft"] <= data["total_gla_sqft"]
    assert data["fiscal_year_start_month"] in range(1, 13)
    assert isinstance(data["occupied_gla_sqft"], int)
    assert isinstance(data["occupancy_bps"], int)
    assert isinstance(data["open_anchor_count"], int)


def assert_tenant(data: dict):
    _assert_common_fields(data, "Tenant")
    assert is_valid_uuid(data["center_id"])
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["trade_name"], str) and data["trade_name"]
    assert data["category"] in _values(TenantCategory)
    assert isinstance(data["gla_sqft"], int) and data["gla_sqft"] > 0
    assert isinstance(data["is_anchor"], bool)
    assert data["is_anchor"] == (data["category"] in ("ANCHOR", "JUNIOR_ANCHOR")), (
        "is_anchor is true exactly for ANCHOR and JUNIOR_ANCHOR tenants")
    assert data["status"] in _values(TenantStatus)


def assert_lease(data: dict):
    _assert_common_fields(data, "Lease")
    assert is_valid_uuid(data["center_id"])
    assert is_valid_uuid(data["tenant_id"])
    assert isinstance(data["suite_code"], str) and data["suite_code"]
    assert isinstance(data["leased_sqft"], int) and data["leased_sqft"] > 0
    assert isinstance(data["annual_base_rent_cents"], int)
    assert data["annual_base_rent_cents"] > 0
    assert 1 <= data["percentage_rate_bps"] <= 10000
    assert data["breakpoint_type"] in _values(BreakpointType)
    assert isinstance(data["natural_breakpoint_cents"], int)
    assert isinstance(data["effective_breakpoint_cents"], int)
    assert data["billing_mode"] in _values(BillingMode)
    assert data["reporting_frequency"] in _values(ReportingFrequency)
    assert 0 <= data["reporting_deadline_days"] <= 60
    assert data["exclusion_profile"] in _values(ExclusionProfile)
    assert data["status"] in _values(LeaseStatus)
    assert data["co_tenancy_status"] in _values(CoTenancyPosture)
    assert isinstance(data["effective_monthly_rent_cents"], int)
    assert isinstance(data["relief_monthly_credit_cents"], int)
    assert isinstance(data["delinquency_strikes"], int)
    assert isinstance(data["ytd_occupancy_cost_cents"], int)
    assert isinstance(data["occupancy_cost_ratio_bps"], int)
    assert data["watchlist_status"] in _values(WatchlistStatus)


def assert_lease_year(data: dict):
    _assert_common_fields(data, "LeaseYear")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["year_index"], int) and data["year_index"] >= 1
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert parse_instant(data["period_end"]) > parse_instant(data["period_start"])
    assert isinstance(data["breakpoint_cents"], int)
    assert isinstance(data["percentage_rate_bps_snapshot"], int)
    assert data["billing_mode_snapshot"] in _values(BillingMode)
    assert isinstance(data["cumulative_net_sales_cents"], int)
    assert isinstance(data["cumulative_billed_cents"], int)
    assert isinstance(data["open_audit_count"], int)
    assert data["status"] in _values(LeaseYearStatus)


def assert_sales_report(data: dict):
    _assert_common_fields(data, "SalesReport")
    assert is_valid_uuid(data["lease_year_id"])
    assert is_iso8601_timestamp(data["period_start"])
    assert is_iso8601_timestamp(data["period_end"])
    assert parse_instant(data["period_end"]) > parse_instant(data["period_start"])
    assert is_iso8601_timestamp(data["due_at"])
    if data.get("gross_sales_cents") is not None:
        assert isinstance(data["gross_sales_cents"], int)
        assert data["gross_sales_cents"] >= 0
    assert isinstance(data["allowed_exclusions_cents"], int)
    assert isinstance(data["net_sales_cents"], int)
    assert data["source"] in _values(SalesReportSource)
    assert isinstance(data["amendment_round"], int)
    assert 0 <= data["amendment_round"] <= 2
    assert isinstance(data["is_delinquent"], bool)
    assert data["status"] in _values(SalesReportStatus)


def assert_exclusion(data: dict):
    _assert_common_fields(data, "SalesExclusion")
    assert is_valid_uuid(data["sales_report_id"])
    assert data["code"] in _values(ExclusionCode)
    assert isinstance(data["claimed_cents"], int) and data["claimed_cents"] >= 0
    assert isinstance(data["allowed_cents"], int) and data["allowed_cents"] >= 0
    assert data["allowed_cents"] <= data["claimed_cents"], (
        "an allowance may never exceed what was claimed")
    assert data["status"] in _values(ExclusionStatus)


def assert_charge(data: dict):
    _assert_common_fields(data, "PercentageRentCharge")
    assert is_valid_uuid(data["lease_year_id"])
    assert data["charge_type"] in _values(ChargeType)
    assert isinstance(data["amount_cents"], int)
    assert data["billing_status"] in _values(BillingStatus)
    assert data["collection_status"] in _values(CollectionStatus)
    assert isinstance(data["paid_cents"], int) and data["paid_cents"] >= 0


def assert_co_tenancy_clause(data: dict):
    _assert_common_fields(data, "CoTenancyClause")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["required_open_anchor_count"], int)
    assert data["required_open_anchor_count"] >= 0
    assert 0 <= data["required_occupancy_bps"] <= 10000
    assert isinstance(data["cure_period_days"], int)
    assert data["cure_period_days"] >= 0
    assert data["relief_type"] in _values(ReliefType)
    assert 1 <= data["relief_pct_bps"] <= 10000
    assert isinstance(data["termination_right_after_days"], int)
    assert data["termination_right_after_days"] >= 0
    assert data["monitoring_status"] in _values(MonitoringStatus)


def assert_co_tenancy_event(data: dict):
    _assert_common_fields(data, "CoTenancyEvent")
    assert is_valid_uuid(data["clause_id"])
    assert data["event_type"] in _values(CoTenancyEventType)
    assert is_iso8601_timestamp(data["observed_at"])
    assert is_iso8601_timestamp(data["cure_deadline_at"])
    assert data["status"] in _values(CoTenancyEventStatus)


def assert_kick_out_clause(data: dict):
    _assert_common_fields(data, "KickOutClause")
    assert is_valid_uuid(data["lease_id"])
    assert isinstance(data["measurement_year_index"], int)
    assert data["measurement_year_index"] >= 1
    assert isinstance(data["threshold_sales_cents"], int)
    assert data["threshold_sales_cents"] > 0
    assert isinstance(data["election_window_days"], int)
    assert data["election_window_days"] > 0
    assert isinstance(data["waiver_consideration_cents"], int)
    assert data["waiver_consideration_cents"] >= 0
    assert data["status"] in _values(KickOutStatus)


def assert_audit(data: dict):
    _assert_common_fields(data, "SalesAudit")
    assert is_valid_uuid(data["lease_id"])
    assert is_valid_uuid(data["sales_report_id"])
    assert is_iso8601_timestamp(data["audit_window_start"])
    assert is_iso8601_timestamp(data["audit_window_end"])
    assert parse_instant(data["audit_window_end"]) >= parse_instant(
        data["audit_window_start"])
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert data["status"] in _values(AuditStatus)


def assert_ledger_entry(data: dict):
    """A reporting ledger entry is append-only: no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "ledger entry id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_valid_uuid(data["lease_year_id"])
    assert data["entry_type"] in _values(LedgerEntryType)
    assert isinstance(data["delta_net_sales_cents"], int)
    assert isinstance(data["delta_billed_cents"], int)
    assert isinstance(data["note"], str)
    assert "updated_at" not in data, (
        "a reporting ledger entry has no updated_at key")
    assert "version" not in data, (
        "a reporting ledger entry has no version key")


def assert_sales_trend(data: dict):
    for field in ("tenant_count", "comp_sqft", "current_net_sales_cents",
                  "prior_net_sales_cents", "comp_growth_bps",
                  "percentage_rent_cents", "sales_psf_cents",
                  "occupancy_cost_ratio_bps"):
        assert field in data, f"the trend report must carry {field}"
        assert isinstance(data[field], int), f"{field} must be an integer"


# ─── Domain invariants ────────────────────────────────────────────────────

def assert_report_net_arithmetic(report: dict):
    """net_sales_cents is gross_sales_cents less allowed_exclusions_cents."""
    if report.get("gross_sales_cents") is None:
        return
    assert report["net_sales_cents"] == (
        report["gross_sales_cents"] - report["allowed_exclusions_cents"]), (
        "net sales must equal gross sales less the allowed exclusions")


def assert_ledger_balances(entries: list, lease_year: dict):
    """The ledger reconstructs both running totals of the reporting year."""
    net_total = sum(entry["delta_net_sales_cents"] for entry in entries)
    billed_total = sum(entry["delta_billed_cents"] for entry in entries)
    assert net_total == lease_year["cumulative_net_sales_cents"], (
        f"ledger net movements sum to {net_total} but the year reads "
        f"{lease_year['cumulative_net_sales_cents']}")
    assert billed_total == lease_year["cumulative_billed_cents"], (
        f"ledger billing movements sum to {billed_total} but the year reads "
        f"{lease_year['cumulative_billed_cents']}")


def assert_relief_credit_consistent(lease: dict, base_monthly_cents: int):
    """The monthly abatement is the unreduced figure less what is payable."""
    assert lease["relief_monthly_credit_cents"] == (
        base_monthly_cents - lease["effective_monthly_rent_cents"]), (
        "relief_monthly_credit_cents must be the unreduced monthly figure "
        "less effective_monthly_rent_cents")


__all__ = [
    "parse_instant", "assert_instant_equals", "plus_days", "assert_center",
    "assert_tenant", "assert_lease", "assert_lease_year",
    "assert_sales_report", "assert_exclusion", "assert_charge",
    "assert_co_tenancy_clause", "assert_co_tenancy_event",
    "assert_kick_out_clause", "assert_audit", "assert_ledger_entry",
    "assert_sales_trend", "assert_report_net_arithmetic",
    "assert_ledger_balances", "assert_relief_credit_consistent",
]
