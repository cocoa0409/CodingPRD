"""Payload factories — one per entity, input fields only.

Plans are built with explicit per-call overrides so each test controls its
own thresholds and rates.
"""

# The canonical PRO plan used across most scenarios.
PRO_PLAN_DEFAULTS = {
    "tier": "PRO",
    "seat_limit": 10,
    "included_build_minutes": 300,
    "build_concurrency_limit": 2,
    "included_bandwidth_gb": 100,
    "included_invocations_millions": 5,
    "bandwidth_tier1_rate_cents_per_gb": 10,
    "bandwidth_tier2_rate_cents_per_gb": 5,
    "bandwidth_tier2_threshold_gb": 50,
    "invocation_rate_cents_per_million": 40,
    "seat_price_cents_monthly": 2000,
    "overage_build_minute_rate_cents": 5,
}

HOBBY_PLAN_DEFAULTS = {
    "tier": "HOBBY",
    "seat_limit": 1,
    "included_build_minutes": 100,
    "build_concurrency_limit": 1,
    "included_bandwidth_gb": 10,
    "included_invocations_millions": 1,
    "bandwidth_tier1_rate_cents_per_gb": 20,
    "bandwidth_tier2_rate_cents_per_gb": 10,
    "bandwidth_tier2_threshold_gb": 100,
    "invocation_rate_cents_per_million": 100,
    "seat_price_cents_monthly": 0,
    "overage_build_minute_rate_cents": 10,
}


def create_plan_catalog_payload(**overrides) -> dict:
    defaults = dict(PRO_PLAN_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_team_payload(**overrides) -> dict:
    defaults = {"name": "Acme", "plan_tier": "PRO"}
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {"user_email": "dev@acme.com", "role": "DEVELOPER"}
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {"name": "web", "production_branch": "main"}
    defaults.update(overrides)
    return defaults


def create_git_event_payload(project_id, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "branch": "feat-a",
        "git_ref": "refs/heads/feat-a",
        "commit_sha": "aaa111",
        "region": "IAD",
    }
    defaults.update(overrides)
    return defaults


def create_env_var_payload(**overrides) -> dict:
    defaults = {"key": "API_KEY", "value": "prod-key", "scopes": ["PRODUCTION"]}
    defaults.update(overrides)
    return defaults


def create_domain_payload(**overrides) -> dict:
    defaults = {"name": "example.com"}
    defaults.update(overrides)
    return defaults


def create_redirect_payload(**overrides) -> dict:
    defaults = {"source": "/old", "target": "/new", "status_code": 308, "priority": 10}
    defaults.update(overrides)
    return defaults


def create_usage_period_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_usage_event_payload(deployment_id, **overrides) -> dict:
    defaults = {
        "deployment_id": deployment_id,
        "event_type": "BANDWIDTH",
        "bandwidth_bytes": 1000,
        "region": "IAD",
    }
    defaults.update(overrides)
    return defaults


def create_alert_rule_payload(**overrides) -> dict:
    defaults = {"metric": "BANDWIDTH_BYTES", "threshold_value": 1000, "window_minutes": 60}
    defaults.update(overrides)
    return defaults


def create_spend_cap_payload(**overrides) -> dict:
    defaults = {"cap_cents": 1000, "action": "ALERT_ONLY"}
    defaults.update(overrides)
    return defaults
