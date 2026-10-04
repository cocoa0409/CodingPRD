"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer >= 1"
    )


def assert_licensee(data: dict):
    _assert_common_fields(data, "Licensee")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["service_category"] in (
        "PREEXISTING_SUBSCRIPTION",
        "NONSUBSCRIPTION_AD_SUPPORTED",
        "BUSINESS_ESTABLISHMENT",
    )
    assert data["license_status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "TERMINATED")


def assert_rate_schedule(data: dict):
    _assert_common_fields(data, "RateSchedule")
    assert data["schedule_status"] in ("DRAFT", "EFFECTIVE", "SUPERSEDED")
    assert isinstance(data["rate_per_performance_microcents"], int)
    assert data["rate_per_performance_microcents"] > 0
    assert isinstance(data["min_fee_cents"], int) and data["min_fee_cents"] > 0


def assert_rate_proceeding(data: dict):
    _assert_common_fields(data, "RateProceeding")
    assert data["proceeding_status"] in ("OPEN", "DECIDED", "PUBLISHED", "CLOSED")


def assert_usage_report(data: dict):
    _assert_common_fields(data, "UsageReport")
    assert data["report_status"] in (
        "DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "AMENDED",
    )
    assert isinstance(data["total_performances"], int)
    assert isinstance(data["matched_performances"], int)
    assert isinstance(data["unmatched_performances"], int)


def assert_play_line(data: dict):
    _assert_common_fields(data, "PlayLine")
    assert data["identification_status"] in ("MATCHED", "UNMATCHED")
    assert isinstance(data["performance_count"], int) and data["performance_count"] > 0


def assert_recording(data: dict):
    _assert_common_fields(data, "Recording")
    assert data["catalog_status"] in ("ACTIVE", "WITHDRAWN")
    assert isinstance(data["isrc"], str) and data["isrc"]


def assert_royalty_liability(data: dict):
    _assert_common_fields(data, "RoyaltyLiability")
    assert data["liability_status"] in (
        "COMPUTED", "BILLED", "PAID", "SETTLED", "WRITTEN_OFF",
    )
    for field in (
        "gross_performance_royalty_cents",
        "minimum_fee_cents",
        "amount_due_cents",
        "admin_fee_cents",
        "distributable_pool_cents",
    ):
        assert isinstance(data[field], int), f"RoyaltyLiability.{field} must be int cents"


def assert_liability_invariants(data: dict):
    """PRD §3.5 step five: distributable pool is amount due minus admin fee."""
    assert data["distributable_pool_cents"] == (
        data["amount_due_cents"] - data["admin_fee_cents"]
    ), "distributable_pool_cents must equal amount_due_cents - admin_fee_cents"


def assert_distribution_batch(data: dict):
    _assert_common_fields(data, "DistributionBatch")
    assert data["batch_status"] in ("PLANNED", "EXECUTED", "REVERSED")


def assert_distribution_line(data: dict):
    _assert_common_fields(data, "DistributionLine")
    assert data["payee_type"] in (
        "RIGHTS_OWNER", "FEATURED_ARTIST", "NONFEATURED_FUND",
    )
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    if data["payee_type"] == "FEATURED_ARTIST":
        assert data.get("payee_artist_id") is not None
        assert data.get("payee_rights_owner_id") is None
        assert data.get("fund_type") is None
    elif data["payee_type"] == "RIGHTS_OWNER":
        assert data.get("payee_rights_owner_id") is not None
        assert data.get("payee_artist_id") is None
        assert data.get("fund_type") is None
    else:
        assert data.get("fund_type") in ("AFM", "SAG_AFTRA")
        assert data.get("payee_artist_id") is None
        assert data.get("payee_rights_owner_id") is None


def assert_artist(data: dict):
    _assert_common_fields(data, "Artist")
    assert data["registration_status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "SUSPENDED",
    )


def assert_rights_owner(data: dict):
    _assert_common_fields(data, "RightsOwner")
    assert data["registration_status"] in (
        "PENDING_VERIFICATION", "VERIFIED", "REJECTED", "SUSPENDED",
    )


def assert_ownership_claim(data: dict):
    _assert_common_fields(data, "OwnershipClaim")
    assert data["claim_status"] in (
        "OPEN", "UNDER_REVIEW", "UPHELD", "REJECTED", "WITHDRAWN",
    )
    assert data["claimant_type"] in ("RIGHTS_OWNER", "FEATURED_ARTIST")


def assert_unclaimed_pool(data: dict):
    _assert_common_fields(data, "UnclaimedPool")
    assert data["pool_status"] in (
        "ACCRUING", "MATCHING_CAMPAIGN", "DISTRIBUTION_ELIGIBLE",
        "DISTRIBUTED", "EXPIRED",
    )
    assert isinstance(data["accrued_unmatched_cents"], int)
    assert isinstance(data["campaign_count"], int) and data["campaign_count"] >= 0


def assert_audit_case(data: dict):
    _assert_common_fields(data, "AuditCase")
    assert data["audit_status"] in (
        "OPENED", "FINDINGS_ISSUED", "SETTLED", "CLOSED", "WAIVED",
    )
    assert isinstance(data["assessed_underpayment_cents"], int)
    assert isinstance(data["recovered_cents"], int)
