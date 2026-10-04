"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data, with_version=True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int), (
            f"version must be an integer, got {data.get('version')!r}"
        )


def assert_market_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_agent(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert is_valid_uuid(data.get("market_center_id", "")), "market_center_id must be a UUID"
    if data.get("sponsor_agent_id") is not None:
        assert is_valid_uuid(data["sponsor_agent_id"]), "sponsor_agent_id must be a UUID"
    assert data["membership_status"] in ["ENROLLED_PENDING_DOCS", "ACTIVE", "DEPARTED"]
    assert data["cap_status"] in ["UNCAPPED", "CAPPED"]
    assert is_iso8601_timestamp(data.get("join_date", ""))
    assert is_iso8601_timestamp(data.get("cap_year_start", ""))
    assert is_iso8601_timestamp(data.get("cap_year_end", ""))
    assert isinstance(data["accrued_company_dollar"], (int, float))
    assert isinstance(data["pending_payable_profit_share"], (int, float))
    assert isinstance(data["lifetime_profit_share"], (int, float))
    assert isinstance(data["vested"], bool)


def assert_sponsorship_edge(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("parent_agent_id", "")), "parent_agent_id must be a UUID"
    assert is_valid_uuid(data.get("child_agent_id", "")), "child_agent_id must be a UUID"
    assert isinstance(data["depth_level"], int), "depth_level must be an integer"
    assert 1 <= data["depth_level"] <= 7, (
        f"closure is capped at 7 levels, got {data['depth_level']}"
    )
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_onboarding_document(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert data["document_type"] in ["SPONSOR_ATTESTATION", "ICA_SIGNED", "W9"]
    assert isinstance(data["document_ref"], str) and len(data["document_ref"]) > 0
    assert is_iso8601_timestamp(data.get("received_at", ""))


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("filer_agent_id", "")), "filer_agent_id must be a UUID"
    assert is_valid_uuid(data.get("sponsored_agent_id", "")), "sponsored_agent_id must be a UUID"
    assert is_valid_uuid(data.get("evidence_document_id", "")), "evidence_document_id must be a UUID"
    assert isinstance(data["reason"], str)
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert is_iso8601_timestamp(data.get("window_deadline", ""))
    assert data["status"] in [
        "FILED", "UNDER_REVIEW", "RESOLVED_UPHELD",
        "RESOLVED_OVERTURNED", "DISMISSED", "REOPENED",
    ]
    assert isinstance(data["appeal_count"], int)


def assert_commission_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert is_valid_uuid(data.get("market_center_id", "")), "market_center_id must be a UUID"
    assert isinstance(data["gross_commission"], (int, float))
    assert is_iso8601_timestamp(data.get("occurred_on", ""))
    assert isinstance(data["external_ref"], str) and len(data["external_ref"]) > 0
    assert data["status"] in ["POSTED", "SETTLED", "VOID"]
    assert isinstance(data["company_dollar"], (int, float))
    assert isinstance(data["agent_retained"], (int, float))
    assert isinstance(data["cap_applied"], bool)


def assert_period(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("market_center_id", "")), "market_center_id must be a UUID"
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7
    assert data["status"] in ["OPEN", "PRELIMINARY_CLOSED", "FINAL_CLOSE_PENDING", "FINAL_CLOSED"]
    assert isinstance(data["distributed_total"], (int, float))
    assert isinstance(data["center_retained_amount"], (int, float))


def assert_ledger_entry(data: dict):
    # Append-only: id + created_at only. The PRD states this resource has
    # neither updated_at nor version.
    _assert_common(data, with_version=False)
    assert "version" not in data, "append-only ledger entry must not carry a version"
    assert "updated_at" not in data, "append-only ledger entry must not carry updated_at"
    assert is_valid_uuid(data.get("period_id", "")), "period_id must be a UUID"
    assert data["entry_type"] in ["EXPENSE", "ADJUSTMENT"]
    assert isinstance(data["amount"], (int, float))


def assert_distribution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("period_id", "")), "period_id must be a UUID"
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert data["basis"] in ["PROVISIONAL", "FINAL"]
    assert data["status"] in ["PROJECTION", "PAYABLE", "PAID", "CLAWED_BACK", "FORFEITED"]
    assert isinstance(data["amount"], (int, float))
    assert isinstance(data["level_breakdown"], list)


def assert_transfer_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert is_valid_uuid(data.get("from_market_center_id", "")), "from_market_center_id must be a UUID"
    assert is_valid_uuid(data.get("to_market_center_id", "")), "to_market_center_id must be a UUID"
    assert is_iso8601_timestamp(data.get("effective_date", ""))
    assert data["status"] in ["REQUESTED", "APPROVED", "REJECTED", "CANCELLED", "COMPLETED"]
    assert data["downline_preserved"] is True, "downline_preserved is always true"


def assert_vesting_schedule(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agent_id", "")), "agent_id must be a UUID"
    assert is_iso8601_timestamp(data.get("vesting_start_date", ""))
    assert data["status"] in ["ACCRUING", "VESTED", "FORFEITED"]
    assert isinstance(data["vested_ratio_provisional"], (int, float))
    assert isinstance(data["vested_ratio_final"], (int, float))


def assert_resolution(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("period_id", "")), "period_id must be a UUID"
    assert data["resolution_type"] == "FINAL_CLOSE_RATIFICATION"
    assert data["status"] in ["DRAFT", "PROPOSED", "RATIFIED", "REJECTED"]


def assert_pool_conservation(period: dict):
    """The PRD's conservation invariant: distributed_total + center_retained_amount
    equals the period's current pool (provisional_pool before final close,
    profit_share_pool after)."""
    if period.get("profit_share_pool") is not None:
        pool = period["profit_share_pool"]
    else:
        pool = period.get("provisional_pool")
    assert pool is not None, "period has no pool computed yet"
    total = round(period["distributed_total"] + period["center_retained_amount"], 2)
    assert abs(total - pool) < 0.005, (
        f"conservation violated: {period['distributed_total']} + "
        f"{period['center_retained_amount']} != {pool}"
    )
