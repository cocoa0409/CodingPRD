"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

WAREHOUSE_SIZES = ("XSMALL", "SMALL", "MEDIUM", "LARGE", "XLARGE", "XXLARGE",
                   "XXXLARGE", "X4LARGE")


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_account(data: dict):
    _assert_common_fields(data, "Account")
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert isinstance(data["account_locator"], str) and data["account_locator"]
    assert data["region"] in ("us-east-1", "us-west-2", "eu-central-1",
                              "ap-southeast-1")
    assert isinstance(data["region_factor"], (int, float)) and data["region_factor"] >= 1.0
    assert data["cloud_provider"] in ("SAME_CLOUD", "CROSS_CLOUD")
    assert data["monitor_scope"] in ("ACCOUNT_ONLY", "INCLUDE_CONSUMERS")
    assert data["account_state"] in ("OPEN", "RESTRICTED", "DRAINING")
    assert_cost_precision(data["posted_consumption_credits_reconciled"], 6)
    assert_cost_precision(data["posted_storage_dollars_reconciled"], 2)


def assert_warehouse(data: dict):
    _assert_common_fields(data, "VirtualWarehouse")
    assert is_valid_uuid(data["account_id"]), "account_id must be a valid UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["size"] in WAREHOUSE_SIZES
    assert isinstance(data["credits_per_hour"], (int, float)) and data["credits_per_hour"] > 0
    assert isinstance(data["auto_suspend_seconds"], int)
    assert 60 <= data["auto_suspend_seconds"] <= 3600
    assert isinstance(data["auto_resume"], bool)
    assert data["status"] in ("SUSPENDED", "STARTING", "RUNNING", "RESIZING", "DRAINING")
    assert isinstance(data["cluster_count"], int) and data["cluster_count"] >= 0
    assert isinstance(data["clusters_min"], int) and data["clusters_min"] >= 1
    assert isinstance(data["clusters_max"], int) and data["clusters_max"] <= 10
    assert data["clusters_max"] >= data["clusters_min"]
    assert isinstance(data["multi_cluster_queued_queries"], int)
    assert isinstance(data["latency_slo_ms"], int) and data["latency_slo_ms"] >= 1


def assert_session(data: dict):
    _assert_common_fields(data, "WarehouseSession")
    assert is_valid_uuid(data["warehouse_id"])
    assert data["size"] in WAREHOUSE_SIZES
    assert isinstance(data["clusters"], int) and data["clusters"] >= 1
    assert is_iso8601_timestamp(data["started_at"])
    assert data["ended_at"] is None or is_iso8601_timestamp(data["ended_at"])
    assert isinstance(data["elapsed_seconds"], int) and data["elapsed_seconds"] >= 0
    assert data["state"] in ("OPEN", "CLOSING", "CLOSED", "RESUMING")
    assert isinstance(data["metered_credits"], (int, float))
    assert isinstance(data["billed_credits"], (int, float))
    assert data["billed_credits"] >= data["metered_credits"], (
        "billed_credits must never fall below metered_credits"
    )
    assert isinstance(data["billed_seconds"], int) and data["billed_seconds"] >= 0
    assert_cost_precision(data["metered_credits"], 6)
    assert_cost_precision(data["billed_credits"], 6)


def assert_contract(data: dict):
    _assert_common_fields(data, "CapacityContract")
    assert is_valid_uuid(data["account_id"])
    assert data["status"] in ("DRAFT", "ACTIVE", "EXHAUSTED", "EXPIRED", "CLOSED")
    assert isinstance(data["drawdown_count"], int) and data["drawdown_count"] >= 0
    assert isinstance(data["remaining_credits"], (int, float))
    assert isinstance(data["drawn_credits"], (int, float))
    assert isinstance(data["rolled_over_credits"], (int, float))
    assert isinstance(data["base_consumed_credits"], (int, float))
    assert isinstance(data["term_end_remaining_credits"], (int, float))
    if data["status"] in ("ACTIVE", "EXHAUSTED"):
        expected = max(
            data["base_credits"] + data["rolled_over_credits"] - data["drawn_credits"],
            0,
        )
        assert data["remaining_credits"] == pytest.approx(expected, abs=1e-6), (
            "remaining_credits must be base_credits + rolled_over_credits - "
            "drawn_credits, floored at 0"
        )


def assert_drawdown(data: dict):
    _assert_common_fields(data, "CreditDrawdown")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["warehouse_id"])
    assert isinstance(data["amount_credits"], (int, float)) and data["amount_credits"] > 0
    assert data["source_kind"] in ("SESSION", "SHARE_CONSUMPTION", "REPLICATION")
    assert data["status"] in ("ACTIVE", "REVERSED")
    assert data["outcome"] in ("BASE", "ROLLOVER", "OVERAGE")
    assert isinstance(data["overage_usd"], (int, float)) and data["overage_usd"] >= 0
    assert_cost_precision(data["overage_usd"], 2)
    if data["outcome"] in ("BASE", "ROLLOVER"):
        assert data["overage_usd"] == 0.0, (
            "overage_usd must be 0.00 whenever the outcome is BASE or ROLLOVER"
        )


def assert_storage_record(data: dict):
    _assert_common_fields(data, "StorageUsageRecord")
    assert is_valid_uuid(data["account_id"])
    assert is_iso8601_timestamp(data["usage_date"])
    assert data["active_tb"] >= 0 and data["time_travel_tb"] >= 0 and data["fail_safe_tb"] >= 0
    assert 0 <= data["time_travel_days"] <= 90
    assert data["fail_safe_days"] == 7, "fail_safe_days is fixed at 7"
    assert data["billable_storage_tb"] == pytest.approx(
        data["active_tb"] + data["time_travel_tb"] + data["fail_safe_tb"], abs=1e-6
    ), "the billable volume is the sum of all three components"
    assert data["snapshot_state"] in ("FINALIZED", "REVISED")
    assert_cost_precision(data["storage_cost_dollars"], 2)


def assert_share(data: dict):
    _assert_common_fields(data, "DataShare")
    assert is_valid_uuid(data["provider_account_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["objects_exposed"], int) and data["objects_exposed"] >= 1
    assert isinstance(data["consumer_account_ids"], list)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUSPENDED")
    assert isinstance(data["consumer_query_count"], int) and data["consumer_query_count"] >= 0
    assert isinstance(data["consumer_credits"], (int, float))
    assert_cost_precision(data["consumer_credits"], 6)


def assert_usage_event(data: dict):
    _assert_common_fields(data, "ShareUsageEvent")
    assert is_valid_uuid(data["share_id"])
    assert is_valid_uuid(data["consumer_account_id"])
    assert is_iso8601_timestamp(data["queried_at"])
    assert data["credits_consumed"] > 0
    assert isinstance(data["row_count"], int) and data["row_count"] >= 0
    assert data["attribution"] in ("CONSUMER", "UNATTRIBUTED")
    assert isinstance(data["attributed_row_count"], int)
    assert data["credited_account_id"] is None or is_valid_uuid(data["credited_account_id"])


def assert_listing(data: dict):
    _assert_common_fields(data, "Listing")
    assert is_valid_uuid(data["share_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["pricing_model"] in ("FREE", "FLAT", "USAGE_BASED")
    assert data["flat_price_usd"] >= 0
    assert data["listing_state"] in ("DRAFT", "PUBLISHED", "WITHDRAWN")
    assert data["frozen_price_usd"] is None or data["frozen_price_usd"] >= 0
    assert data["provider_payout_usd"] + data["platform_fee_usd"] == pytest.approx(
        data["gross_credit_volume"], abs=0.005
    ), "provider_payout_usd + platform_fee_usd must equal gross_credit_volume"
    assert_cost_precision(data["provider_payout_usd"], 2)
    assert_cost_precision(data["platform_fee_usd"], 2)


def assert_paid_usage(data: dict):
    _assert_common_fields(data, "PaidShareUsage")
    assert is_valid_uuid(data["listing_id"])
    assert is_valid_uuid(data["buyer_account_id"])
    assert data["credits_used"] > 0
    assert data["usage_state"] in ("PENDING", "SETTLED", "DISPUTED")
    assert data["disputed_by_user_id"] is None or isinstance(data["disputed_by_user_id"], str)


def assert_monitor(data: dict):
    _assert_common_fields(data, "ResourceMonitor")
    assert is_valid_uuid(data["account_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["credit_quota"] > 0
    assert data["interval"] in ("DAILY", "WEEKLY", "MONTHLY")
    assert data["action"] in ("NOTIFY", "SUSPEND", "SUSPEND_IMMEDIATE")
    assert data["monitor_state"] in ("OK", "NOTIFY_SENT", "SUSPENDED")
    assert isinstance(data["interval_consumption_credits"], (int, float))
    assert isinstance(data["used_pct"], (int, float))
    assert is_iso8601_timestamp(data["last_reset_at"])
    assert_cost_precision(data["used_pct"], 6)


def assert_replication(data: dict):
    _assert_common_fields(data, "ReplicationConfiguration")
    assert is_valid_uuid(data["account_id"])
    assert data["target_region"] in ("us-east-1", "us-west-2", "eu-central-1",
                                     "ap-southeast-1")
    assert data["target_cloud"] in ("SAME_CLOUD", "CROSS_CLOUD")
    assert 0 <= data["replicated_tb"] <= 500
    assert isinstance(data["refresh_count"], int) and data["refresh_count"] >= 0
    assert data["replication_state"] in ("CONFIGURED", "REFRESHING", "REFRESHED", "FAILED")
    assert_cost_precision(data["transfer_cost_dollars"], 2)


def assert_ledger_entry(data: dict):
    """A ledger row is append-only: id, created_at and posted_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "AccountLedgerEntry.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "AccountLedgerEntry.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "version" not in data, "an append-only ledger row carries no version"
    assert "updated_at" not in data, "an append-only ledger row carries no updated_at"
    assert data["bucket"] in (
        "CONSUMPTION", "OVERAGE", "ROLLOVER", "REPLICATION", "SHARE_CONSUMPTION",
        "STORAGE", "STORAGE_ADJUST", "PAYOUT", "PAYOUT_ADJUST",
    )
    assert data["source_entity"] in (
        "WarehouseSession", "CreditDrawdown", "StorageUsageRecord",
        "ReplicationConfiguration", "ShareUsageEvent", "Listing", "CapacityContract",
    )
    assert is_valid_uuid(data["source_entity_id"])
    assert is_iso8601_timestamp(data["posted_at"])
    if data["bucket"] in ("CONSUMPTION", "SHARE_CONSUMPTION", "ROLLOVER"):
        assert data["amount_credits"] != 0, (
            "a credit-denominated row carries a non-zero amount_credits"
        )
    if data["bucket"] in ("STORAGE", "OVERAGE", "REPLICATION", "PAYOUT"):
        assert data["amount_credits"] == 0, (
            "STORAGE, OVERAGE, REPLICATION and PAYOUT rows carry amount_credits 0"
        )


# ---------------------------------------------------------------------------
# Domain helpers used by tests and fixtures
# ---------------------------------------------------------------------------

def ledger_bucket_total(entries: list, bucket: str) -> float:
    return sum(
        e.get("amount_usd", 0.0) if bucket in (
            "STORAGE", "STORAGE_ADJUST", "OVERAGE", "REPLICATION",
            "PAYOUT", "PAYOUT_ADJUST",
        ) else e.get("amount_credits", 0.0)
        for e in entries if e["bucket"] == bucket
    )


def assert_account_credit_figure(account: dict, expected: float, abs_tol: float = 1e-6):
    actual = account["posted_consumption_credits_reconciled"]
    assert actual == pytest.approx(expected, abs=abs_tol), (
        f"posted_consumption_credits_reconciled should be {expected}, got {actual}"
    )