"""Entity assertions and domain invariant helpers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_brand(data: dict):
    _assert_common(data)
    assert isinstance(data.get("brand_code"), str) and data["brand_code"]
    assert isinstance(data.get("display_name"), str) and data["display_name"]
    assert data.get("status") in ("ACTIVE", "RETIRED")


def assert_market(data: dict):
    _assert_common(data)
    assert isinstance(data.get("market_code"), str) and data["market_code"]
    assert isinstance(data.get("name"), str) and data["name"]


def assert_brokerage(data: dict):
    _assert_common(data)
    assert isinstance(data.get("legal_name"), str) and data["legal_name"]
    assert is_valid_uuid(data.get("home_market_id", ""))
    assert data.get("status") in ("PROSPECT", "FRANCHISED", "TERMINATED")


def assert_agreement(data: dict):
    _assert_common(data)
    for fk in ("brokerage_id", "brand_id", "market_id"):
        assert is_valid_uuid(data.get(fk, "")), f"{fk} must be a UUID"
    for f in ("base_royalty_rate_bps", "annual_royalty_cap_cents",
              "volume_incentive_threshold_cents", "volume_incentive_rate_bps",
              "ad_fund_rate_bps", "cumulative_billed_royalty_cents",
              "cumulative_gci_cents", "open_cure_count"):
        assert isinstance(data.get(f), int), f"{f} must be an integer"
    assert data.get("status") in (
        "DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED",
        "DEIDENTIFYING", "CLOSED",
    )


def assert_conversion_plan(data: dict):
    _assert_common(data)
    assert isinstance(data.get("milestones"), list)
    assert isinstance(data.get("milestones_done"), int)
    assert isinstance(data.get("ready"), bool)


def assert_agent(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("brokerage_id", ""))
    assert isinstance(data.get("license_no"), str) and data["license_no"]
    assert data.get("status") in ("ACTIVE", "INACTIVE")


def assert_agent_count_report(data: dict):
    # Append-only record: id + created_at only, never updated_at/version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only report must not carry updated_at"
    assert "version" not in data, "append-only report must not carry version"


def assert_gci_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only report must not carry updated_at"
    assert "version" not in data, "append-only report must not carry version"


def assert_royalty_period(data: dict):
    _assert_common(data)
    assert isinstance(data.get("gci_cents"), int)
    assert isinstance(data.get("royalty_due_cents"), int)
    assert isinstance(data.get("provisional_royalty_cents"), int)
    assert isinstance(data.get("ad_fund_due_cents"), int)
    assert data.get("status") in ("ASSESSED", "SETTLED", "WAIVED")


def assert_default_case(data: dict):
    _assert_common(data)
    assert data.get("reason_code") in ("PAYMENT", "BRAND_STANDARDS", "REPORTING", "TERRITORY")
    assert data.get("status") in ("OPEN", "CURING", "RESOLVED", "ESCALATED")


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger entry must not carry updated_at"
    assert "version" not in data, "append-only ledger entry must not carry version"
    assert data.get("entry_type") in ("COLLECT", "SPEND")
    assert isinstance(data.get("amount_cents"), int) and data["amount_cents"] > 0


def assert_council(data: dict):
    _assert_common(data)
    assert isinstance(data.get("seat_count"), int)
    assert isinstance(data.get("member_brokerage_ids"), list)
    assert isinstance(data.get("quorum_votes"), int)


def assert_proposal(data: dict):
    _assert_common(data)
    assert isinstance(data.get("amount_cents"), int)
    assert isinstance(data.get("approvals"), int)
    assert isinstance(data.get("rejections"), int)
    assert data.get("status") in ("DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "EXECUTED")


def assert_audit(data: dict):
    _assert_common(data)
    assert data.get("audit_type") in ("SIGNAGE", "MARKETING", "TECH_ADOPTION", "AGENT_ONBOARDING")
    assert data.get("status") in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")


def assert_deidentification_task(data: dict):
    _assert_common(data)
    assert data.get("category") in (
        "SIGNAGE_REMOVAL", "MARKETING_WITHDRAWAL", "DATA_PURGE",
        "DOMAIN_RELEASE", "DIRECTORY_REMOVAL",
    )
    assert data.get("status") in ("PENDING", "COMPLETED", "VERIFIED")
