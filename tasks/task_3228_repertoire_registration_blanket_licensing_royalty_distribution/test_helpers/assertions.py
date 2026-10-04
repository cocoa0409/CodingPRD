"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    AffiliateStatus,
    WorkStatus,
    ShareClaimStatus,
    LicenseeCategory,
    CreditStanding,
    LicenseStatus,
    DisputeStatus,
    RateCourtCaseStatus,
    PerformanceEventStatus,
    CycleStatus,
    StatementStatus,
    AdjustmentStatus,
    AuditStatus,
    PoolStatus,
)


def _assert_common(data):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_affiliate(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["party_type"] in ("SONGWRITER", "PUBLISHER")
    assert isinstance(data["affiliation_code"], str) and len(data["affiliation_code"]) > 0
    assert data["status"] in AffiliateStatus._value2member_map_
    assert isinstance(data["royalty_balance_cents"], int)
    assert isinstance(data["total_paid_cents"], int)


def assert_work(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert isinstance(data["registered_by_affiliate_id"], str)
    assert data["status"] in WorkStatus._value2member_map_
    assert isinstance(data["aggregate_interest_bps"], int)


def assert_share_claim(data: dict):
    _assert_common(data)
    assert isinstance(data["work_id"], str)
    assert isinstance(data["affiliate_id"], str)
    assert data["role"] in ("WRITER", "PUBLISHER")
    assert 1 <= data["collection_share_bps"] <= 10000
    assert 1 <= data["interest_share_bps"] <= 10000
    assert data["status"] in ShareClaimStatus._value2member_map_


def assert_licensee(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert data["category"] in LicenseeCategory._value2member_map_
    assert isinstance(data["reported_revenue_cents"], int) and data["reported_revenue_cents"] >= 0
    assert isinstance(data["usage_units"], int) and data["usage_units"] >= 0
    assert isinstance(data["blanket_fee_cents"], int)
    assert data["credit_standing"] in CreditStanding._value2member_map_


def assert_license(data: dict):
    _assert_common(data)
    assert isinstance(data["licensee_id"], str)
    assert data["category"] in LicenseeCategory._value2member_map_
    assert data["status"] in LicenseStatus._value2member_map_
    assert isinstance(data["fee_basis_cents"], int)


def assert_rate_dispute(data: dict):
    _assert_common(data)
    assert isinstance(data["license_id"], str)
    assert data["opened_by_role"] in ("LICENSEE", "PRO")
    assert isinstance(data["disputed_fee_cents"], int)
    assert data["status"] in DisputeStatus._value2member_map_
    assert isinstance(data["negotiation_rounds"], int)


def assert_rate_court_case(data: dict):
    _assert_common(data)
    assert isinstance(data["dispute_id"], str)
    assert data["status"] in RateCourtCaseStatus._value2member_map_


def assert_performance_event(data: dict):
    _assert_common(data)
    assert isinstance(data["work_id"], str)
    assert isinstance(data["license_id"], str)
    assert isinstance(data["play_count"], int) and data["play_count"] >= 1
    assert isinstance(data["universe_estimated_plays"], int)
    assert data["status"] in PerformanceEventStatus._value2member_map_
    if data["status"] == "ACCEPTED":
        # credit_units kept at 4 decimal places
        credit = data["credit_units"]
        assert abs(credit * 10000 - round(credit * 10000)) < 1e-6, "credit_units must be rounded to 4 decimal places"


def assert_distribution_cycle(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["status"] in CycleStatus._value2member_map_
    assert isinstance(data["version_epoch"], int)


def assert_royalty_statement(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["affiliate_id"], str)
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["admin_fee_cents"], int)
    assert isinstance(data["net_amount_cents"], int)
    assert isinstance(data["unclaimed_amount_cents"], int)
    assert data["status"] in StatementStatus._value2member_map_


def assert_royalty_adjustment(data: dict):
    _assert_common(data)
    assert isinstance(data["statement_id"], str)
    assert isinstance(data["affiliate_id"], str)
    assert isinstance(data["delta_cents"], int)
    assert data["reason"] in ("LATE_CLAIM", "AUDIT_FINDING", "RATE_COURT_RETRO", "DATA_CORRECTION")
    assert data["status"] in AdjustmentStatus._value2member_map_


def assert_audit_request(data: dict):
    _assert_common(data)
    assert isinstance(data["licensee_id"], str)
    assert data["status"] in AuditStatus._value2member_map_
    assert isinstance(data["findings_delta_cents"], int)


def assert_unclaimed_pool(data: dict):
    _assert_common(data)
    assert isinstance(data["cycle_id"], str)
    assert isinstance(data["balance_cents"], int)
    assert data["status"] in PoolStatus._value2member_map_


def assert_statement_money_invariants(stmt: dict):
    """PRD §3.8/§3.9: net == gross - admin_fee; admin fee never exceeds the payable portion."""
    assert stmt["net_amount_cents"] == stmt["gross_amount_cents"] - stmt["admin_fee_cents"], (
        f"net ({stmt['net_amount_cents']}) must equal gross ({stmt['gross_amount_cents']}) "
        f"minus admin fee ({stmt['admin_fee_cents']})"
    )
    payable = stmt["gross_amount_cents"] - stmt["unclaimed_amount_cents"]
    assert 0 <= stmt["admin_fee_cents"] <= max(payable, 0)
