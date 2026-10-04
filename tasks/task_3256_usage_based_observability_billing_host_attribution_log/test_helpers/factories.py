"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "ACCOUNT_NAME": "Acme Observability",
    "ACCOUNT_ANCHOR_DAY": 1,
    "PERIOD_START": "2026-09-01T00:00:00Z",
    "PERIOD_END": "2026-10-01T00:00:00Z",
    "WINDOW_END": "2026-09-30T23:59:59Z",
    "HOUR_BUCKET": "2026-09-01T00:00:00Z",
    "INGESTED_AT": "2026-09-05T00:00:00Z",
    "COMMITTED_RATE": 100,
    "OVERAGE_RATE": 500,
}


def create_billing_account_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ACCOUNT_NAME"],
        "plan_tier": "ENTERPRISE",
        "billing_cycle_anchor_day": DEFAULTS["ACCOUNT_ANCHOR_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_tier_config_payload(**overrides) -> dict:
    from .constants import ENTERPRISE_PLAN

    defaults = dict(ENTERPRISE_PLAN)
    defaults.update(overrides)
    return defaults


def create_billing_period_payload(**overrides) -> dict:
    defaults = {
        "period_start_utc": DEFAULTS["PERIOD_START"],
        "period_end_utc": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_host_hour_record_payload(**overrides) -> dict:
    defaults = {
        "hour_bucket_utc": DEFAULTS["HOUR_BUCKET"],
        "infra_host_count": 5,
        "container_host_count": 1,
        "serverless_invocation_count": 100,
    }
    defaults.update(overrides)
    return defaults


def create_log_event_payload(**overrides) -> dict:
    defaults = {
        "size_bytes": 100,
        "service_tag": "quiet-svc",
        "ingested_at_utc": DEFAULTS["INGESTED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_retention_tier_payload(expected_billing_account_version, **overrides) -> dict:
    defaults = {
        "name": "hot-30d",
        "retention_days": 30,
        "effective_from_utc": DEFAULTS["PERIOD_START"],
        "effective_to_utc": DEFAULTS["PERIOD_END"],
        "index_rate_multiplier_bp": 10000,
        "expected_billing_account_version": expected_billing_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_exclusion_filter_payload(**overrides) -> dict:
    defaults = {
        "service_tag_pattern": "noisy-*",
        "sample_rate_pct": 0,
        "priority": 1,
        "enabled": True,
    }
    defaults.update(overrides)
    return defaults


def create_custom_metric_series_payload(team_id, **overrides) -> dict:
    defaults = {
        "metric_name": "api.latency",
        "team_id": team_id,
    }
    defaults.update(overrides)
    return defaults


def create_rollup_payload(**overrides) -> dict:
    defaults = {"cardinality_estimate": 20000}
    defaults.update(overrides)
    return defaults


def create_commitment_payload(expected_billing_account_version, **overrides) -> dict:
    defaults = {
        "meter": "INFRA_HOST",
        "committed_quantity": 10,
        "window_start_utc": DEFAULTS["PERIOD_START"],
        "window_end_utc": DEFAULTS["WINDOW_END"],
        "committed_unit_rate_cents": DEFAULTS["COMMITTED_RATE"],
        "overage_unit_rate_cents": DEFAULTS["OVERAGE_RATE"],
        "expected_billing_account_version": expected_billing_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_team_payload(**overrides) -> dict:
    defaults = {
        "name": "Platform",
        "cost_center": "CC-100",
    }
    defaults.update(overrides)
    return defaults


def create_usage_record_payload(**overrides) -> dict:
    defaults = {
        "meter": "TRACE",
        "quantity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(raised_by_team_id, **overrides) -> dict:
    defaults = {
        "raised_by_team_id": raised_by_team_id,
        "reason": "wrong team attribution",
    }
    defaults.update(overrides)
    return defaults


def create_tag_policy_payload(**overrides) -> dict:
    defaults = {
        "required_tag_key": "team",
        "allowed_values": ["a", "b"],
        "enforcement": "BLOCK",
    }
    defaults.update(overrides)
    return defaults


def create_monitor_payload(**overrides) -> dict:
    defaults = {
        "name": "cpu-high",
        "monitor_kind": "METRIC",
    }
    defaults.update(overrides)
    return defaults


def create_top_up_payload(**overrides) -> dict:
    defaults = {"top_up_quantity": 5}
    defaults.update(overrides)
    return defaults


def create_remediate_payload(**overrides) -> dict:
    defaults = {"remediation_note": "Dropped high-cardinality tag"}
    defaults.update(overrides)
    return defaults
