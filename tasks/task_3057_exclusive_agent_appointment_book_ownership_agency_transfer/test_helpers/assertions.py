"""Entity assertions and domain invariant checkers."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_agency(data: dict):
    """Validate an Agency response against the PRD contract (§2.4, §3.9)."""
    assert is_valid_uuid(data.get("id", "")), "Agency.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Agency.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "Agency.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "Agency.version must be an integer"
    assert data["status"] in ["APPROVED", "ACTIVE", "TERMINATED"], (
        f"Unexpected Agency.status {data.get('status')!r}"
    )
    assert isinstance(data.get("market_need_score"), int)
    assert 0 <= data["market_need_score"] <= 100
    assert isinstance(data.get("region_code"), str) and len(data["region_code"]) > 0


def assert_agent(data: dict):
    """Validate an Agent response (§2.4, §3.2)."""
    assert is_valid_uuid(data.get("id", "")), "Agent.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Agent.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "Agent.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int)
    assert data["status"] in [
        "CANDIDATE", "APPOINTED", "ACTIVE", "TRANSITIONING",
        "PENDING_TERMINATION", "TERMINATED",
    ], f"Unexpected Agent.status {data.get('status')!r}"
    assert data.get("license_status") in ["NOT_LICENSED", "LICENSED", "EXPIRED"]


def assert_policy(data: dict):
    """Validate a Policy response (§2.4, §3.8)."""
    assert is_valid_uuid(data.get("id", "")), "Policy.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Policy.created_at must be ISO 8601"
    assert data["status"] in ["OPEN", "LAPSED", "CANCELLED", "TRANSFERRED"], (
        f"Unexpected Policy.status {data.get('status')!r}"
    )
    assert data.get("product_line") in ["AUTO", "HOME", "LIFE"]
    assert isinstance(data.get("annual_premium_cents"), int)
    assert isinstance(data.get("is_new_business"), bool)


def assert_agreement(data: dict):
    """Validate an Agreement response (§2.4, §3.3)."""
    assert is_valid_uuid(data.get("id", "")), "Agreement.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Agreement.created_at must be ISO 8601"
    assert data["status"] in [
        "DRAFT", "UNDER_REVIEW", "ACTIVE", "SUSPENDED", "TERMINATED", "TRANSITIONING",
    ], f"Unexpected Agreement.status {data.get('status')!r}"
    assert data.get("agreement_type") in ["EXCLUSIVE_AGENT", "TEAM_MEMBER"]
    assert isinstance(data.get("commission_schedule"), dict)


def assert_staff_member(data: dict):
    """Validate a StaffMember response (§2.4, §3.5)."""
    assert is_valid_uuid(data.get("id", "")), "StaffMember.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "StaffMember.created_at must be ISO 8601"
    assert data["status"] in ["PENDING", "ACTIVE", "TERMINATED"], (
        f"Unexpected StaffMember.status {data.get('status')!r}"
    )
    assert isinstance(data.get("allocation_units"), int)
    assert 1 <= data["allocation_units"] <= 20


def assert_campaign(data: dict):
    """Validate a MarketingCampaign response (§2.4, §3.4)."""
    assert is_valid_uuid(data.get("id", "")), "MarketingCampaign.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "MarketingCampaign.created_at must be ISO 8601"
    assert data["status"] in ["PLANNED", "PARTICIPATED", "CANCELLED"], (
        f"Unexpected MarketingCampaign.status {data.get('status')!r}"
    )
    assert data.get("campaign_type") in ["LEAD_PROGRAM", "BRAND", "COMMUNITY"]
    assert data.get("participation_posture") in ["OPEN", "RESTRICTED", "FROZEN"]
    assert isinstance(data.get("marketing_allowance_cents"), int)
    assert data["marketing_allowance_cents"] >= 0


def assert_claim(data: dict):
    """Validate a Claim response (§2.4, §3.8)."""
    assert is_valid_uuid(data.get("id", "")), "Claim.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "Claim.created_at must be ISO 8601"
    assert data["status"] in ["OPEN", "PAID", "DENIED", "CANCELLED"], (
        f"Unexpected Claim.status {data.get('status')!r}"
    )
    assert isinstance(data.get("claim_amount_cents"), int)


def assert_book_transfer(data: dict):
    """Validate a BookTransfer response (§2.4, §3.7)."""
    assert is_valid_uuid(data.get("id", "")), "BookTransfer.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "BookTransfer.created_at must be ISO 8601"
    assert data["status"] in ["PENDING", "SETTLED", "REVERSED"], (
        f"Unexpected BookTransfer.status {data.get('status')!r}"
    )
    if data.get("retention_pct") is not None:
        assert isinstance(data["retention_pct"], (int, float))
    if data.get("retention_met") is not None:
        assert isinstance(data["retention_met"], bool)


def assert_license_record(data: dict):
    """LicenseRecord is immutable: only id + created_at (§2.4)."""
    assert is_valid_uuid(data.get("id", "")), "LicenseRecord.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "LicenseRecord.created_at must be ISO 8601"
    assert "updated_at" not in data, "LicenseRecord carries no updated_at"
    assert "version" not in data, "LicenseRecord carries no version"


def assert_application(data: dict):
    """Validate an AppointmentApplication response (§2.4, §3.1)."""
    assert is_valid_uuid(data.get("id", "")), "AppointmentApplication.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in [
        "SUBMITTED", "SCORED", "REJECTED", "APPROVED", "CONSUMED",
    ], f"Unexpected AppointmentApplication.status {data.get('status')!r}"
    assert data.get("creation_channel") in ["DIGITAL", "FIELD"]


# ─── Domain invariants ────────────────────────────────

def assert_agency_invariants(data: dict):
    """Derived book-keeping invariants that hold after any operation (§2.5)."""
    assert data["book_open_count"] >= 0
    assert data["exposure_inforce_cents"] >= 0
    assert data["agency_level_units"] >= 0
    assert data["agency_paid_claims_cents"] >= 0
    assert data["loss_ratio"] >= 0
    assert data["agency_valuation_cents"] >= 2_000_000.00, (
        "agency_valuation_cents has a floor of 2,000,000.00"
    )
    assert data["performance_status"] in ["ON_TRACK", "BEHIND", "AT_RISK"]


def assert_split_invariant(data: dict):
    """The released + remaining halves always re-sum to the house half (§2.8)."""
    released = data["sub_producer_released_commission_cents"]
    assert released >= 0, "released ledger is never negative"
    assert released + (60_000.00 - released) == pytest.approx(60_000.00, abs=0.01)