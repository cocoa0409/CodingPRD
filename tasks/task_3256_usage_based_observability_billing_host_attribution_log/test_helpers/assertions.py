"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .types import (
    AccountStanding,
    BillingPeriodStatus,
    CommitmentStatus,
    DisputeStatus,
    Enforcement,
    ExclusionState,
    IncidentStatus,
    InvoiceStatus,
    Meter,
    MonitorKind,
    MonitorStatus,
    PlanTier,
    SeriesStatus,
)


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer starting at 1"
    )


def assert_billing_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["plan_tier"] in [t.value for t in PlanTier]
    assert isinstance(data["billing_cycle_anchor_day"], int)
    assert 1 <= data["billing_cycle_anchor_day"] <= 28
    assert data["standing"] in [s.value for s in AccountStanding]


def assert_plan_tier_config(data: dict):
    _assert_common_fields(data)
    assert data["plan_tier"] in [t.value for t in PlanTier]
    for field in (
        "max_monitors",
        "included_custom_metrics",
        "host_overage_rate_cents",
        "log_ingest_rate_cents_per_gb",
        "log_index_rate_cents_per_million",
        "custom_metric_rate_cents_per_unit",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, (
            f"{field} must be a non-negative integer"
        )


def assert_billing_period(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert isinstance(data["period_start_utc"], str)
    assert isinstance(data["period_end_utc"], str)
    assert data["status"] in [s.value for s in BillingPeriodStatus]


def assert_host_hour_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_period_id"])
    assert isinstance(data["hour_bucket_utc"], str)
    for field in ("infra_host_count", "container_host_count", "serverless_invocation_count"):
        assert isinstance(data[field], int) and data[field] >= 0


def assert_meter_accumulator(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_period_id"])
    assert data["meter"] in [m.value for m in Meter]
    for field in ("quantity", "committed_consumed_quantity", "on_demand_quantity"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["on_demand_quantity"] == (
        data["quantity"] - data["committed_consumed_quantity"]
    ), "on_demand_quantity must equal quantity minus committed_consumed_quantity (PRD §3.4)"


def assert_log_event(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_period_id"])
    assert isinstance(data["size_bytes"], int) and data["size_bytes"] >= 0
    assert isinstance(data["service_tag"], str)
    assert isinstance(data["ingested_at_utc"], str)
    assert data["exclusion_state"] in [s.value for s in ExclusionState]
    assert data.get("retention_tier_id") is None or isinstance(data["retention_tier_id"], str)


def assert_retention_tier(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["retention_days"], int) and data["retention_days"] >= 0
    assert isinstance(data["effective_from_utc"], str)
    assert isinstance(data["effective_to_utc"], str)
    assert isinstance(data["index_rate_multiplier_bp"], int)


def assert_exclusion_filter(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert isinstance(data["service_tag_pattern"], str)
    assert isinstance(data["sample_rate_pct"], int)
    assert 0 <= data["sample_rate_pct"] <= 100, (
        "sample_rate_pct is confined to the inclusive range 0 through 100 (PRD §3.3)"
    )
    assert isinstance(data["priority"], int)
    assert isinstance(data["enabled"], bool)


def assert_custom_metric_series(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert isinstance(data["metric_name"], str)
    assert isinstance(data["team_id"], str)
    assert isinstance(data["cardinality_estimate"], int) and data["cardinality_estimate"] >= 0
    assert data["status"] in [s.value for s in SeriesStatus]


def assert_cardinality_incident(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["custom_metric_series_id"])
    assert isinstance(data["opened_at_cardinality"], int)
    assert isinstance(data["threshold_used"], int)
    assert data["status"] in [s.value for s in IncidentStatus]


def assert_commitment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert data["meter"] in [m.value for m in Meter]
    for field in (
        "committed_quantity",
        "consumed_quantity",
        "expired_quantity",
        "committed_unit_rate_cents",
        "overage_unit_rate_cents",
    ):
        assert isinstance(data[field], int) and data[field] >= 0
    assert isinstance(data["window_start_utc"], str)
    assert isinstance(data["window_end_utc"], str)
    assert data["status"] in [s.value for s in CommitmentStatus]


def assert_team(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["cost_center"], str)


def assert_usage_record(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_period_id"])
    assert data.get("team_id") is None or isinstance(data["team_id"], str)
    assert data["meter"] in [m.value for m in Meter]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 0
    assert isinstance(data["tag_compliant"], bool)
    assert isinstance(data["disputed"], bool)


def assert_attribution_dispute(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["usage_record_id"])
    assert isinstance(data["raised_by_team_id"], str)
    assert isinstance(data["reason"], str)
    assert data["status"] in [s.value for s in DisputeStatus]


def assert_tag_policy(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert isinstance(data["required_tag_key"], str)
    assert isinstance(data["allowed_values"], list)
    assert data["enforcement"] in [e.value for e in Enforcement]


def assert_monitor(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_account_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["monitor_kind"] in [k.value for k in MonitorKind]
    assert data["status"] in [s.value for s in MonitorStatus]


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["billing_period_id"])
    assert isinstance(data["total_amount_cents"], int) and data["total_amount_cents"] >= 0
    assert data["status"] in [s.value for s in InvoiceStatus]


def assert_invoice_line(data: dict):
    # Immutable once written: carries only id + created_at; updated_at and version
    # are absent (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, "InvoiceLine must not carry updated_at (PRD §2.4)"
    assert "version" not in data, "InvoiceLine must not carry version (PRD §2.4)"
    assert is_valid_uuid(data["invoice_id"])
    assert data["meter"] in [m.value for m in Meter]
    assert isinstance(data["rated_quantity"], int) and data["rated_quantity"] >= 0
    assert isinstance(data["amount_cents"], int)


def assert_commitment_invariants(data: dict):
    """Conservation of commitment quantity (PRD §3.4): consumed plus expired never
    exceeds committed, and on_demand invariants on the accumulator stay consistent."""
    assert data["consumed_quantity"] <= data["committed_quantity"], (
        "consumed_quantity must not exceed committed_quantity"
    )
    assert data["expired_quantity"] >= 0
    if data["status"] == CommitmentStatus.SETTLED.value:
        assert data["consumed_quantity"] + data["expired_quantity"] == (
            data["committed_quantity"]
        ), "settled commitment: consumed + expired == committed (PRD §3.4)"
